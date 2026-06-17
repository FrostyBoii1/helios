"""Import commit PREVIEW service (Phase C0 — read-only, ZERO live writes).

Computes what a future commit-to-live (Phase C1) WOULD create from an import
batch, without writing anything: which rows are eligible, why others are
excluded, the Customer/Job fields each eligible row would map to, and the case
numbers that would be assigned given the CURRENT database state.

NOTHING in this module creates or modifies Customer/Job/Task/Activity/Document/
NAS records, and it does not touch ImportBatch or ImportRow. It is pure
read-only computation. Actual creation is Phase C1 and is intentionally NOT here.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models.customer import Customer
from app.models.enums import ImportRowClass, ImportRowReviewStatus
from app.models.import_staging import ImportBatch, ImportCustomerGroup, ImportRow
from app.models.job import Job
from app.services.case_number import build_case_number
from app.services.customers import get_customer
from app.services.import_parser import parse_date_maybe

# Imported (COMPLETED-sheet) jobs would be created with this status (D3).
PREVIEW_JOB_STATUS = "installed"

# Row classes that could ever become a live job (mirror the review approval set).
COMMITTABLE_CLASSES = (ImportRowClass.JOB.value, ImportRowClass.AMBIGUOUS.value)

# Case-year sanity range. A row whose derived case-number year falls outside
# this band almost certainly has a malformed source date (e.g. parsing to year
# 202 or 2002) and must be corrected in staging before it can commit — otherwise
# it would mint a nonsensical case number like "SCS-202-00001".
MIN_CASE_YEAR = 2020


def case_year_in_range(year: int, *, current_year: int) -> bool:
    return MIN_CASE_YEAR <= year <= current_year + 1


# --------------------------------------------------------------------------- #
# Pure helpers (no DB)
# --------------------------------------------------------------------------- #
def _str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _has_unresolved_error(row: ImportRow) -> bool:
    return any(i.severity == "error" and not i.resolved for i in row.issues)


def commit_sort_key(
    row: ImportRow,
    *,
    groups: dict[int, ImportCustomerGroup],
    rows_by_id: dict[int, ImportRow],
    current_year: int,
) -> tuple:
    """Chronological order that keeps each group CONTIGUOUS and PRIMARY-FIRST (B3-3).

    A group is positioned by its primary's source date; within the group the primary
    sorts first, then dependents by source order. Ungrouped rows keep their original
    (undated-last, date, source_index) order — the first three tuple elements match
    the pre-B3-3 key, so ungrouped ordering is unchanged. Used by BOTH preview and
    commit so the two agree.
    """
    gid = row.customer_group_id
    grp = groups.get(gid) if gid is not None else None
    if grp is not None:
        anchor = rows_by_id.get(grp.primary_row_id) or row  # position by the primary
        asrc, _ = case_year_source(anchor.parsed or {}, current_year=current_year)
        within = 0 if row.id == grp.primary_row_id else 1
        return (asrc is None, asrc or date.min, anchor.source_row_index, within, row.source_row_index)
    src, _ = case_year_source(row.parsed or {}, current_year=current_year)
    return (src is None, src or date.min, row.source_row_index, 0, row.source_row_index)


def case_year_source(parsed: dict, *, current_year: int) -> tuple[date | None, int]:
    """Derive the (sort_date, case_year) for a row (D2).

    Year comes from sale_date, else install_date, else the current year. The
    returned date is the parsed source date used for chronological ordering
    (None when neither parses).
    """
    sale = parse_date_maybe(_str(parsed.get("sale_date")))
    install = parse_date_maybe(_str(parsed.get("install_date")))
    source = sale or install
    year = source.year if source is not None else current_year
    return source, year


def map_customer_preview(parsed: dict, raw: dict) -> dict:
    """Preview the Customer fields a commit would set (D4/D5/D9). No persistence."""
    emails = [e for e in (parsed.get("emails") or []) if _str(e).strip()]
    phones = [
        _str(p.get("number")).strip()
        for p in (parsed.get("phones") or [])
        if _str(p.get("number")).strip()
    ]
    # Prefer the reviewer-editable parsed address; fall back to the raw cell.
    address = _str(parsed.get("address")).strip() or _str(raw.get("address")).strip()
    # Conservative AU address split (Phase-7 cleanup). Mirrors build_customer_data
    # exactly so the preview shows the SAME fields commit will write: when
    # parse_address structured the cell we surface suburb/state/postcode; when it
    # could not, `line1` holds the raw address and the rest stay blank.
    ap = parsed.get("address_parts") or {}
    return {
        "full_name": _str(parsed.get("customer_name")).strip(),
        "email": emails[0] if emails else None,
        "phone": phones[0] if phones else None,
        "address_line1": ap.get("line1") or (address or None),
        "suburb": ap.get("suburb"),
        "state": ap.get("state"),
        "postcode": ap.get("postcode"),
        "extra_emails": emails[1:],
        "extra_phones": phones[1:],
    }


def map_job_preview(
    parsed: dict,
    *,
    predicted_case_number: str,
    legacy_reference: str | None,
    raw: dict | None = None,
    batch_id: int = 0,
    source_row_index: int = 0,
) -> dict:
    """Preview the Job fields a commit would set (D3/D9). No persistence.

    When ``raw`` is provided (the commit-preview path), the structured ``details``
    is included AND the legacy blobs are rendered with the SAME
    ``render_legacy_blobs`` the commit uses (Phase 2b) — so the preview matches
    exactly what commit will write (pass ``batch_id``/``source_row_index`` so the
    provenance line matches too). Callers that omit ``raw`` get the legacy
    pipe-string shape (back-compat)."""
    sale = parse_date_maybe(_str(parsed.get("sale_date")))
    install = parse_date_maybe(_str(parsed.get("install_date")))

    out: dict[str, Any] = {
        "predicted_case_number": predicted_case_number,
        "legacy_reference": legacy_reference,
        "status": PREVIEW_JOB_STATUS,
        "sale_date": sale.isoformat() if sale else None,
        "install_date": install.isoformat() if install else None,
        "salesperson_text": _str(parsed.get("salesperson")).strip() or None,
        # Surfaced so the preview UI can flag an old-system removal before commit.
        "removes_old_system": bool(parsed.get("removes_old_system")),
        "customer_name_notes": _str(parsed.get("customer_name_notes")).strip() or None,
        "details": None,
    }

    if raw is not None:
        # Phase 2b: render the blobs from the same structured details the commit
        # writes, so preview blobs are byte-identical to the committed job.
        from app.services.import_details import build_details, render_legacy_blobs

        details = parsed.get("details") or build_details(parsed, raw)
        blobs = render_legacy_blobs(
            details, parsed,
            batch_id=batch_id, source_row_index=source_row_index,
            legacy_reference=legacy_reference,
        )
        out["details"] = details
        out["system_details"] = blobs["system_details"]
        out["install_details"] = blobs["install_details"]
        out["approval_details"] = blobs["approval_details"]
        out["notes"] = blobs["notes"]
        return out

    # Legacy pipe-string preview (no raw): unchanged shape for back-compat.
    def join(bits: list[tuple[str, Any]]) -> str | None:
        parts = [f"{label}: {_str(v).strip()}" for label, v in bits if _str(v).strip()]
        return " | ".join(parts) or None

    out["system_details"] = join([
        ("Panels", parsed.get("no_of_panels")),
        ("Panel", parsed.get("panel_raw")),
        ("Inverter", parsed.get("inverter_raw")),
        ("Meter", parsed.get("meter_no")),
        ("NMI", parsed.get("nmi_raw")),
        ("Distributor", parsed.get("distributor_inferred") or parsed.get("distributor_raw")),
        ("Retailer", parsed.get("retailer_raw")),
        ("MSB", parsed.get("msb_state")),
    ])
    out["install_details"] = join([
        ("Day", parsed.get("install_day")),
        ("Time", parsed.get("install_time")),
        ("Installer", parsed.get("installer_raw")),
    ])
    out["approval_details"] = join([
        ("Approval", parsed.get("approval_state")),
        ("Pending date", parsed.get("approval_pending_date")),
    ])
    out["notes"] = _str(parsed.get("notes_raw")).strip() or None
    return out


# --------------------------------------------------------------------------- #
# Eligibility classification
# --------------------------------------------------------------------------- #
EXCLUSION_REASONS = (
    "already_committed",
    "blank_or_divider",
    "not_approved",
    "unresolved_error",
    "missing_customer_name",
    "invalid_case_year",
    # B2-2: row resolved to an existing customer that is now missing/soft-deleted.
    "resolved_customer_invalid",
    # B3-3: a grouped DEPENDENT whose group's primary won't create a customer this
    # commit (primary not eligible / not yet committed).
    "group_primary_unavailable",
    # B3-3: a grouped DEPENDENT whose group already committed a customer that is now
    # missing/soft-deleted.
    "group_customer_invalid",
)


def classify_row(row: ImportRow, *, current_year: int | None = None) -> str | None:
    """Return None if the row is eligible to commit, else its exclusion reason.

    Disjoint, priority-ordered so reasons sum cleanly with the eligible count.
    `current_year` defaults to now; passed in by callers that already computed it.
    """
    year_now = current_year if current_year is not None else datetime.now(timezone.utc).year
    if row.committed_customer_id is not None or row.committed_job_id is not None:
        return "already_committed"
    if row.row_class not in COMMITTABLE_CLASSES:
        return "blank_or_divider"
    if row.review_status != ImportRowReviewStatus.APPROVED.value:
        return "not_approved"
    if _has_unresolved_error(row):
        return "unresolved_error"
    if not _str((row.parsed or {}).get("customer_name")).strip():
        return "missing_customer_name"
    # Malformed source date -> nonsensical case-number year. Block until fixed.
    _src, year = case_year_source(row.parsed or {}, current_year=year_now)
    if not case_year_in_range(year, current_year=year_now):
        return "invalid_case_year"
    return None


# Terminal review states whose group membership is preserved as audit (never detached).
_GROUP_TERMINAL = (
    ImportRowReviewStatus.COMMITTED.value,
    ImportRowReviewStatus.REVERSED.value,
)


def plan_group_commit(
    group: ImportCustomerGroup, member_rows: list[ImportRow], eligible_ids: set[int]
) -> tuple[int | None, list[int]]:
    """A (stabilization): shared planner used by BOTH preview (predict) and commit
    (apply) so the two always agree on grouped rows.

    Given a group's member rows and the set of per-row-eligible ids (``classify_row``
    returned None), return ``(effective_primary_id, detach_ids)``:

      * ``effective_primary_id`` — the stored primary if it is eligible, else the
        lowest-source-index eligible member (re-promotion); the stored primary when the
        group already committed a customer (historical); None when the group is not
        being committed into (no eligible member and not already committed).
      * ``detach_ids`` — non-eligible, non-terminal members (pending-unapproved /
        rejected / skipped / error). At commit these are detached so they are not left
        stranded in a now-locked committed group; committed/reversed members stay
        (audit). Empty when the group is not being committed into.

    Pure (no DB).
    """
    members = sorted(member_rows, key=lambda r: r.source_row_index)
    eligible = [m for m in members if m.id in eligible_ids]
    committed = group.committed_customer_id is not None
    if not (eligible or committed):
        return None, []
    detach = [
        m.id for m in members
        if m.id not in eligible_ids and m.review_status not in _GROUP_TERMINAL
    ]
    if committed:
        effective_primary = group.primary_row_id  # dependents attach to committed_customer_id
    else:  # eligible is non-empty here
        effective_primary = (
            group.primary_row_id if group.primary_row_id in eligible_ids else eligible[0].id
        )
    return effective_primary, detach


# --------------------------------------------------------------------------- #
# Preview (read-only)
# --------------------------------------------------------------------------- #
def preview(db: Session, batch: ImportBatch, *, sample_limit: int = 50) -> dict:
    """Compute the commit preview for a batch. Performs ZERO writes."""
    current_year = datetime.now(timezone.utc).year

    rows = list(
        db.scalars(
            select(ImportRow)
            .options(joinedload(ImportRow.issues))
            .where(ImportRow.batch_id == batch.id)
            .order_by(ImportRow.source_row_index)
        ).unique()
    )

    excluded = dict.fromkeys(EXCLUSION_REASONS, 0)
    eligible: list[ImportRow] = []
    for row in rows:
        reason = classify_row(row)
        if reason is None:
            eligible.append(row)
        else:
            excluded[reason] += 1

    # Among otherwise-eligible rows, validate B2 'existing' resolutions and B3
    # group memberships so PREVIEW and COMMIT agree. Read-only.
    #   * B2-2: an 'existing' resolution to a missing/soft-deleted customer is
    #     excluded (resolved_customer_invalid).
    #   * B3-3: a grouped PRIMARY creates the group's customer; a grouped DEPENDENT
    #     is valid only if the group already committed a LIVE customer, or its
    #     primary is eligible this commit. Otherwise it is excluded.
    groups = {
        g.id: g
        for g in db.scalars(
            select(ImportCustomerGroup).where(ImportCustomerGroup.batch_id == batch.id)
        ).all()
    }
    rows_by_id = {r.id: r for r in rows}
    eligible_ids = {r.id for r in eligible}
    # A (stabilization): each group's EFFECTIVE primary (re-promoted to the lowest
    # source-index eligible member when the stored primary is not eligible) — preview
    # PREDICTS it, commit APPLIES it, via the same plan_group_commit, so the two agree.
    members_by_group: dict[int, list[ImportRow]] = {}
    for r in rows:
        if r.customer_group_id is not None:
            members_by_group.setdefault(r.customer_group_id, []).append(r)
    eff_primary: dict[int, int | None] = {
        g.id: plan_group_commit(g, members_by_group.get(g.id, []), eligible_ids)[0]
        for g in groups.values()
    }
    attach_customer: dict[int, Customer] = {}        # B2 'existing' -> live customer
    group_role: dict[int, tuple[str, int, int]] = {}  # row.id -> (action, group_id, primary_row_id)
    group_dep_customer: dict[int, Customer] = {}     # dep on an already-committed group customer
    still_eligible: list[ImportRow] = []
    for row in eligible:
        mode = row.customer_resolution_mode or None
        if mode == "existing":
            target = get_customer(db, row.resolved_customer_id)
            if target is None:
                excluded["resolved_customer_invalid"] += 1
                continue
            attach_customer[row.id] = target
        elif mode == "group":
            g = groups.get(row.customer_group_id)
            if g is None:
                excluded["group_primary_unavailable"] += 1
                continue
            ep = eff_primary.get(g.id)
            if g.committed_customer_id is not None:
                cust = get_customer(db, g.committed_customer_id)
                if cust is None:
                    excluded["group_customer_invalid"] += 1
                    continue
                group_role[row.id] = ("group_dependent", g.id, g.primary_row_id)
                group_dep_customer[row.id] = cust
            elif ep is not None and row.id == ep:
                group_role[row.id] = ("group_primary", g.id, ep)
            elif ep is not None:
                group_role[row.id] = ("group_dependent", g.id, ep)
            else:
                excluded["group_primary_unavailable"] += 1
                continue
        still_eligible.append(row)
    eligible = still_eligible

    # Chronological order, group-contiguous + primary-first (shared with commit).
    eligible.sort(
        key=lambda r: commit_sort_key(r, groups=groups, rows_by_id=rows_by_id, current_year=current_year)
    )

    # Predicted case numbers: start each year from the CURRENT live count and walk
    # the eligible rows in chronological order. Pure prediction — no reservation.
    base_counts: dict[int, int] = {}
    running: dict[int, int] = {}
    by_year: dict[str, int] = {}
    samples: list[dict] = []

    for row in eligible:
        parsed = row.parsed or {}
        raw = row.raw or {}
        _src, year = case_year_source(parsed, current_year=current_year)
        if year not in base_counts:
            prefix = f"SCS-{year}-"
            base_counts[year] = (
                db.scalar(
                    select(func.count()).select_from(Job).where(Job.case_number.like(f"{prefix}%"))
                )
                or 0
            )
            running[year] = 0
        running[year] += 1
        by_year[str(year)] = by_year.get(str(year), 0) + 1
        predicted = build_case_number(year, base_counts[year] + running[year])

        if len(samples) < sample_limit:
            # customer_action: create | attach (B2 existing) | group_primary |
            # group_dependent. resolved_customer_* shows the live target for an
            # attach / a dependent on an already-committed group customer.
            role = group_role.get(row.id)
            target = attach_customer.get(row.id)
            if role is not None:
                action, grp_id, prim = role
                disp = group_dep_customer.get(row.id)
            elif target is not None:
                action, grp_id, prim, disp = "attach", None, None, target
            else:
                action, grp_id, prim, disp = "create", None, None, None
            samples.append(
                {
                    "row_id": row.id,
                    "source_row_index": row.source_row_index,
                    "legacy_reference": row.legacy_reference,
                    "case_year": year,
                    "predicted_case_number": predicted,
                    "customer": map_customer_preview(parsed, raw),
                    "job": map_job_preview(
                        parsed,
                        predicted_case_number=predicted,
                        legacy_reference=row.legacy_reference,
                        raw=raw,
                        batch_id=batch.id,
                        source_row_index=row.source_row_index,
                    ),
                    "customer_action": action,
                    "resolved_customer_id": disp.id if disp is not None else None,
                    "resolved_customer_name": disp.full_name if disp is not None else None,
                    "group_id": grp_id,
                    "primary_row_id": prim,
                }
            )

    # would_create.customers = pure-new rows + each group's primary (the group's one
    # customer). Attaches (B2 existing) + grouped dependents create no customer.
    creates = sum(1 for r in eligible if r.id not in attach_customer and r.id not in group_role)
    group_primaries = sum(1 for r in eligible if group_role.get(r.id, ("",))[0] == "group_primary")
    return {
        "batch_id": batch.id,
        "total_rows": len(rows),
        "eligible_count": len(eligible),
        "excluded": excluded,
        "would_create": {"customers": creates + group_primaries, "jobs": len(eligible)},
        "would_attach_jobs": len(attach_customer),
        "predicted_case_numbers_by_year": by_year,
        "sample_limit": sample_limit,
        "sample_truncated": len(eligible) > len(samples),
        "samples": samples,
    }
