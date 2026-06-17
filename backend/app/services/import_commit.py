"""Import commit-to-live engine (Phase C1).

Creates live Customer + Job records from APPROVED staged rows. Reuses the C0
preview's eligibility (`classify_row`) and field mapping (`map_customer_preview`,
`map_job_preview`) so what the commit-preview shows is what the commit creates.

Safety model (see _commit_one):
  * Eligibility is re-checked here, server-side — never trusted from the client.
  * Each row is committed on its own (per-row durability); a row failure rolls
    back only that row and is recorded — no orphaned Customer/Job, no blocking
    of the other rows.
  * Already-committed rows are skipped; a row whose legacy_reference already
    exists on a live Job is skipped (idempotent re-run, no duplicates).
  * Create-only: existing live records are never updated or deleted.
  * Conservative first-release cap of COMMIT_CAP rows per call.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models.enums import (
    ActivityType,
    ImportBatchStatus,
    ImportRowReviewStatus,
    JobLabelSource,
    JobStatus,
)
from app.models.customer import Customer
from app.models.import_staging import ImportBatch, ImportRow
from app.models.job import Job
from app.services import job_labels as job_labels_service
from app.services import jobs as jobs_service
from app.services.activity import log_activity
from app.services.customers import create_customer, get_customer
from app.services.import_commit_preview import (
    case_year_source,
    classify_row,
    map_customer_preview,
)
from app.services.import_details import (
    build_details,
    build_imported_notes,
    render_legacy_blobs,
)
from app.services.import_parser import parse_date_maybe

# Conservative cap for this first live-write release (owner decision D3).
COMMIT_CAP = 25


def _str(value: object) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


# --------------------------------------------------------------------------- #
# Field builders (reuse the C0 preview mappers; add provenance) — D6
# --------------------------------------------------------------------------- #
def build_customer_data(parsed: dict, raw: dict, *, batch_id: int, source_row_index: int) -> dict:
    """Customer model kwargs for a row. Structured fields come from the shared
    preview mapper; extra contacts + provenance are preserved in notes."""
    pv = map_customer_preview(parsed, raw)
    note_lines: list[str] = []
    if pv["extra_emails"]:
        note_lines.append("Other emails: " + ", ".join(pv["extra_emails"]))
    if pv["extra_phones"]:
        note_lines.append("Other phones: " + ", ".join(pv["extra_phones"]))
    # Use the cleaned, reviewer-editable note only. We deliberately do NOT fall back
    # to the raw extract: when the cleaner emptied it, the removed text was pure
    # approval-status / decommission / approval-ACTION-phrase junk (e.g. "DO
    # APPROVAL" — R2/A3) whose meaning is carried by a label, and it must not be
    # resurrected into the customer file.
    extracted = _str(parsed.get("customer_name_notes")).strip()
    if extracted:
        note_lines.append("From name cell: " + extracted)
    note_lines.append(f"Imported from legacy workbook (batch {batch_id}, row {source_row_index}).")
    # Conservative AU address split (Phase-7 parser cleanup). When parse_address
    # confidently structured the cell, populate suburb/state/postcode; otherwise
    # `line1` holds the raw address and the rest stay blank. Falls back to the
    # preview mapper's single-line address for rows staged before address_parts
    # existed (back-compat). No matching/dedup or property logic here.
    ap = parsed.get("address_parts") or {}
    return {
        "full_name": pv["full_name"],
        "email": pv["email"],
        "phone": pv["phone"],
        "address_line1": ap.get("line1") or pv["address_line1"],
        "suburb": ap.get("suburb"),
        "state": ap.get("state"),
        "postcode": ap.get("postcode"),
        "notes": "\n".join(note_lines) or None,
    }


def build_job_data(
    parsed: dict, raw: dict, *, legacy_reference: str | None, batch_id: int, source_row_index: int
) -> dict:
    """Job model kwargs (excluding case_number/customer_id/status, which the
    create path sets).

    Phase 2b: writes the structured ``details`` (computed if the staged row
    predates Phase 2a) and derives the legacy ``*_details`` / ``notes`` blobs
    from it via the shared ``render_legacy_blobs`` renderer — so the blobs stay
    populated and exactly match the commit-preview."""
    details = parsed.get("details") or build_details(parsed, raw)
    blobs = render_legacy_blobs(
        details, parsed,
        batch_id=batch_id, source_row_index=source_row_index, legacy_reference=legacy_reference,
    )
    return {
        "legacy_reference": legacy_reference,
        "sale_date": parse_date_maybe(_str(parsed.get("sale_date"))),
        "install_date": parse_date_maybe(_str(parsed.get("install_date"))),
        "details": details,
        "system_details": blobs["system_details"],
        "install_details": blobs["install_details"],
        "approval_details": blobs["approval_details"],
        "notes": blobs["notes"],
    }


# --------------------------------------------------------------------------- #
# Commit
# --------------------------------------------------------------------------- #
def _live_legacy_ref_exists(db: Session, legacy_reference: str) -> bool:
    return db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.legacy_reference == legacy_reference, Job.deleted_at.is_(None))
    ) > 0


def _eligible_uncommitted_count(db: Session, batch_id: int) -> int:
    rows = db.scalars(
        select(ImportRow)
        .options(joinedload(ImportRow.issues))
        .where(ImportRow.batch_id == batch_id)
    ).unique()
    return sum(1 for r in rows if classify_row(r) is None)


def seed_internal_notes(job: Job, *, override: str | None = None) -> None:
    """Seed ``Job.internal_notes`` on commit — ONLY when it is blank, so a manual
    note is never overwritten.

    ``override`` is the import row's ``internal_notes_override``:
      * None -> use the generated build_imported_notes default (existing behavior);
      * ""   -> commit BLANK internal notes (leave it unset);
      * text -> commit that text verbatim.
    """
    if _str(job.internal_notes).strip():
        return
    if override is not None:
        # Reviewer override: "" -> blank internal notes; any other text -> verbatim.
        job.internal_notes = override or None
        return
    imported = build_imported_notes(job.details)
    if imported:
        job.internal_notes = imported


def _commit_one(db: Session, row: ImportRow, *, actor_id: int, batch_id: int, current_year: int) -> dict:
    """Create Customer+Job for one eligible row and link it. Per-row durable.

    On any error the row's work is rolled back (no orphan) and a 'failed' result
    is returned; other rows are unaffected.
    """
    parsed = row.parsed or {}
    raw = row.raw or {}
    rid, sidx, legacy = row.id, row.source_row_index, row.legacy_reference
    base = {"row_id": rid, "source_row_index": sidx, "legacy_reference": legacy}

    # Idempotency: don't duplicate a legacy reference that's already live.
    if legacy and _live_legacy_ref_exists(db, legacy):
        return {**base, "status": "skipped", "reason": "duplicate_legacy_reference"}

    # B2-2: a row resolved to an EXISTING customer attaches its job to that
    # customer instead of creating a new one. Re-validate the target in THIS
    # transaction; if it is gone, FAIL the row — never silently create a new
    # customer, never clear the stored resolution.
    attach = row.customer_resolution_mode == "existing"
    resolved_customer: Customer | None = None
    if attach:
        resolved_customer = get_customer(db, row.resolved_customer_id)  # active only
        if resolved_customer is None:
            still_exists = (
                row.resolved_customer_id is not None
                and db.get(Customer, row.resolved_customer_id) is not None
            )
            reason = "resolved_customer_deleted" if still_exists else "resolved_customer_missing"
            return {**base, "status": "failed", "reason": reason}

    try:
        if attach:
            # Use the existing customer as-is; never created, never mutated.
            customer = resolved_customer
        else:
            customer = create_customer(
                db, data=build_customer_data(parsed, raw, batch_id=batch_id, source_row_index=sidx)
            )
            db.flush()  # assign customer.id
        _src, year = case_year_source(parsed, current_year=current_year)
        job = jobs_service.create_job(
            db,
            customer_id=customer.id,
            data=build_job_data(parsed, raw, legacy_reference=legacy, batch_id=batch_id, source_row_index=sidx),
            year=year,
            status=JobStatus.INSTALLED,
        )
        row.committed_customer_id = customer.id
        row.committed_job_id = job.id
        row.review_status = ImportRowReviewStatus.COMMITTED.value
        # Safety net: seed internal notes — the reviewer's internal_notes_override
        # wins when set (NULL falls back to the generated build_imported_notes
        # default); ONLY when blank, so a manual note is never overwritten.
        seed_internal_notes(job, override=row.internal_notes_override)
        # Provenance activity. For an attach, mark it so an auditor can see the job
        # was added to an existing customer (and who resolved it).
        description = "Imported from legacy workbook."
        meta: dict = {"batch_id": batch_id, "source_row_index": sidx, "legacy_reference": legacy}
        if attach:
            description = "Imported from legacy workbook; job attached to an existing customer."
            meta["attached_to_existing_customer"] = True
            meta["resolved_customer_id"] = customer.id
            if row.resolved_by_id is not None:
                meta["resolved_by_id"] = row.resolved_by_id
        log_activity(
            db,
            activity_type=ActivityType.RECORD_IMPORTED,
            description=description,
            actor_id=actor_id,
            customer_id=customer.id,
            job_id=job.id,
            meta=meta,
        )
        # Phase L3: auto-assign import-derived labels (approval state, decommission)
        # in the SAME per-row transaction. Additive + idempotent — never reads or
        # alters the preserved review_notes / source text. assigned_by_id = the
        # commit operator (provenance, mirrors RECORD_IMPORTED.actor_id); source =
        # import_auto marks it machine-derived rather than a manual UI choice.
        for label_key, label_note in job_labels_service.auto_label_keys(parsed, job.details or {}):
            job_labels_service.assign_label_by_key(
                db,
                job_id=job.id,
                key=label_key,
                source=JobLabelSource.IMPORT_AUTO,
                assigned_by_id=actor_id,
                note=label_note,
            )
        db.commit()  # per-row durability
        return {
            **base,
            "status": "committed",
            "case_number": job.case_number,
            "customer_id": customer.id,
            "job_id": job.id,
        }
    except Exception as exc:  # noqa: BLE001 - record + continue; never orphan
        db.rollback()
        return {**base, "status": "failed", "error": type(exc).__name__}


def commit_batch(
    db: Session,
    batch: ImportBatch,
    *,
    actor_id: int,
    row_ids: list[int] | None = None,
) -> dict:
    """Commit eligible approved rows (capped at COMMIT_CAP) to live records."""
    current_year = datetime.now(timezone.utc).year

    rows = list(
        db.scalars(
            select(ImportRow)
            .options(joinedload(ImportRow.issues))
            .where(ImportRow.batch_id == batch.id)
            .order_by(ImportRow.source_row_index)
        ).unique()
    )
    by_id = {r.id: r for r in rows}

    results: list[dict] = []

    # Requested rows that can't be committed are reported as skips up front.
    if row_ids is not None:
        candidate_rows: list[ImportRow] = []
        for rid in row_ids:
            r = by_id.get(rid)
            if r is None:
                results.append({"row_id": rid, "status": "skipped", "reason": "not_in_batch"})
                continue
            reason = classify_row(r, current_year=current_year)
            if reason is not None:
                results.append(
                    {
                        "row_id": r.id,
                        "source_row_index": r.source_row_index,
                        "legacy_reference": r.legacy_reference,
                        "status": "skipped",
                        "reason": reason,
                    }
                )
                continue
            candidate_rows.append(r)
    else:
        candidate_rows = [r for r in rows if classify_row(r, current_year=current_year) is None]

    # Chronological order (matches the preview): dated rows first, then sheet order.
    def sort_key(r: ImportRow) -> tuple[bool, date, int]:
        src, _year = case_year_source(r.parsed or {}, current_year=current_year)
        return (src is None, src or date.min, r.source_row_index)

    candidate_rows.sort(key=sort_key)

    to_process = candidate_rows[:COMMIT_CAP]
    capped_out = len(candidate_rows) - len(to_process)

    if to_process and batch.status not in (
        ImportBatchStatus.COMMITTED.value,
        ImportBatchStatus.COMMITTED_PARTIAL.value,
    ):
        batch.status = ImportBatchStatus.COMMITTING.value
        db.commit()

    committed = failed = skipped = 0
    for r in to_process:
        res = _commit_one(db, r, actor_id=actor_id, batch_id=batch.id, current_year=current_year)
        results.append(res)
        if res["status"] == "committed":
            committed += 1
        elif res["status"] == "failed":
            failed += 1
        else:
            skipped += 1

    # Count skips that came from the row_ids pre-pass too.
    skipped = sum(1 for x in results if x["status"] == "skipped")

    remaining_eligible = _eligible_uncommitted_count(db, batch.id)
    batch = db.get(ImportBatch, batch.id)
    if remaining_eligible == 0:
        batch.status = ImportBatchStatus.COMMITTED.value
    elif committed > 0:
        batch.status = ImportBatchStatus.COMMITTED_PARTIAL.value
    # else: leave the prior status untouched (nothing was committed this call)
    db.commit()

    return {
        "batch_id": batch.id,
        "batch_status": batch.status,
        "attempted": committed + failed,
        "committed": committed,
        "skipped": skipped,
        "failed": failed,
        "remaining_eligible": remaining_eligible,
        "cap": COMMIT_CAP,
        "capped_out": capped_out,
        "results": results,
    }
