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

from app.models.enums import ImportRowClass, ImportRowReviewStatus
from app.models.import_staging import ImportBatch, ImportRow
from app.models.job import Job
from app.services.case_number import build_case_number
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
    return {
        "full_name": _str(parsed.get("customer_name")).strip(),
        "email": emails[0] if emails else None,
        "phone": phones[0] if phones else None,
        # Single-line only; no suburb/state/postcode parsing in v1 (D5).
        "address_line1": address or None,
        "extra_emails": emails[1:],
        "extra_phones": phones[1:],
    }


def map_job_preview(parsed: dict, *, predicted_case_number: str, legacy_reference: str | None) -> dict:
    """Preview the Job fields a commit would set (D3/D9). No persistence."""
    sale = parse_date_maybe(_str(parsed.get("sale_date")))
    install = parse_date_maybe(_str(parsed.get("install_date")))

    system_bits = [
        ("Panels", parsed.get("no_of_panels")),
        ("Panel", parsed.get("panel_raw")),
        ("Inverter", parsed.get("inverter_raw")),
        ("Meter", parsed.get("meter_no")),
        ("NMI", parsed.get("nmi_raw")),
        ("Distributor", parsed.get("distributor_inferred") or parsed.get("distributor_raw")),
        ("Retailer", parsed.get("retailer_raw")),
        ("MSB", parsed.get("msb_state")),
    ]
    install_bits = [
        ("Day", parsed.get("install_day")),
        ("Time", parsed.get("install_time")),
        ("Installer", parsed.get("installer_raw")),
    ]
    approval_bits = [
        ("Approval", parsed.get("approval_state")),
        ("Pending date", parsed.get("approval_pending_date")),
    ]

    def join(bits: list[tuple[str, Any]]) -> str | None:
        parts = [f"{label}: {_str(v).strip()}" for label, v in bits if _str(v).strip()]
        return " | ".join(parts) or None

    return {
        "predicted_case_number": predicted_case_number,
        "legacy_reference": legacy_reference,
        "status": PREVIEW_JOB_STATUS,
        "sale_date": sale.isoformat() if sale else None,
        "install_date": install.isoformat() if install else None,
        "salesperson_text": _str(parsed.get("salesperson")).strip() or None,
        "system_details": join(system_bits),
        "install_details": join(install_bits),
        "approval_details": join(approval_bits),
        "notes": _str(parsed.get("notes_raw")).strip() or None,
        # Surfaced so the preview UI can flag an old-system removal before commit.
        "removes_old_system": bool(parsed.get("removes_old_system")),
        "customer_name_notes": _str(parsed.get("customer_name_notes")).strip() or None,
    }


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

    # Chronological order: dated rows first (by source date), undated rows last,
    # each tie-broken by original sheet order (D2).
    def sort_key(row: ImportRow) -> tuple[bool, date, int]:
        src, _year = case_year_source(row.parsed or {}, current_year=current_year)
        return (src is None, src or date.min, row.source_row_index)

    eligible.sort(key=sort_key)

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
                    ),
                }
            )

    return {
        "batch_id": batch.id,
        "total_rows": len(rows),
        "eligible_count": len(eligible),
        "excluded": excluded,
        "would_create": {"customers": len(eligible), "jobs": len(eligible)},
        "predicted_case_numbers_by_year": by_year,
        "sample_limit": sample_limit,
        "sample_truncated": len(eligible) > len(samples),
        "samples": samples,
    }
