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

from app.models.enums import ActivityType, ImportBatchStatus, ImportRowReviewStatus, JobStatus
from app.models.import_staging import ImportBatch, ImportRow
from app.models.job import Job
from app.services import jobs as jobs_service
from app.services.activity import log_activity
from app.services.customers import create_customer
from app.services.import_commit_preview import (
    case_year_source,
    classify_row,
    map_customer_preview,
    map_job_preview,
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
    # Prefer the cleaned, reviewer-editable note; fall back to the raw extract.
    extracted = _str(parsed.get("customer_name_notes")).strip() or _str(
        parsed.get("name_extracted_notes")
    ).strip()
    if extracted:
        note_lines.append("From name cell: " + extracted)
    note_lines.append(f"Imported from legacy workbook (batch {batch_id}, row {source_row_index}).")
    return {
        "full_name": pv["full_name"],
        "email": pv["email"],
        "phone": pv["phone"],
        "address_line1": pv["address_line1"],
        "notes": "\n".join(note_lines) or None,
    }


def build_job_data(parsed: dict, *, legacy_reference: str | None, batch_id: int, source_row_index: int) -> dict:
    """Job model kwargs (excluding case_number/customer_id/status, which the
    create path sets). Detail fields come from the shared preview mapper; the
    notes field preserves payment/compliance/salesperson + provenance (D6)."""
    pv = map_job_preview(parsed, predicted_case_number="", legacy_reference=legacy_reference)

    note_lines: list[str] = []
    # Old-system removal is operationally critical — put it first so staff see it
    # at the top of the Job notes, not buried below payment/compliance detail.
    if parsed.get("removes_old_system"):
        marker = _str(parsed.get("decommission_marker")).strip()
        note_lines.append(
            "REMOVE OLD SYSTEM - decommission the existing system"
            + (f" (flagged: {marker})" if marker else "")
            + "."
        )
    # Preserved meaningful text from the Customer Name cell (approval removed).
    name_cell_notes = _str(parsed.get("customer_name_notes")).strip()
    if name_cell_notes:
        note_lines.append("From name cell: " + name_cell_notes)
    if pv["salesperson_text"]:
        note_lines.append("Salesperson: " + pv["salesperson_text"])
    payment = parsed.get("payment") or {}
    pay_bits = [
        f"{k}: {_str(payment.get(k)).strip()}"
        for k in ("total", "deposit", "balance", "result", "notes")
        if _str(payment.get(k)).strip()
    ]
    if pay_bits:
        note_lines.append("Payment — " + ", ".join(pay_bits))
    compliance = parsed.get("compliance") or {}
    comp_bits = [
        f"{k}: {_str(compliance.get(k)).strip()}"
        for k in ("accreditation_code", "welcome_call")
        if _str(compliance.get(k)).strip()
    ]
    if comp_bits:
        note_lines.append("Compliance — " + ", ".join(comp_bits))
    raw_notes = _str(parsed.get("notes_raw")).strip()
    if raw_notes:
        note_lines.append("Notes: " + raw_notes)
    note_lines.append(
        f"Imported from legacy workbook (batch {batch_id}, row {source_row_index}"
        + (f", ref {legacy_reference}" if legacy_reference else "")
        + ")."
    )

    return {
        "legacy_reference": legacy_reference,
        "sale_date": parse_date_maybe(_str(parsed.get("sale_date"))),
        "install_date": parse_date_maybe(_str(parsed.get("install_date"))),
        "system_details": pv["system_details"],
        "install_details": pv["install_details"],
        "approval_details": pv["approval_details"],
        "notes": "\n".join(note_lines) or None,
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

    try:
        customer = create_customer(
            db, data=build_customer_data(parsed, raw, batch_id=batch_id, source_row_index=sidx)
        )
        db.flush()  # assign customer.id
        _src, year = case_year_source(parsed, current_year=current_year)
        job = jobs_service.create_job(
            db,
            customer_id=customer.id,
            data=build_job_data(parsed, legacy_reference=legacy, batch_id=batch_id, source_row_index=sidx),
            year=year,
            status=JobStatus.INSTALLED,
        )
        row.committed_customer_id = customer.id
        row.committed_job_id = job.id
        row.review_status = ImportRowReviewStatus.COMMITTED.value
        log_activity(
            db,
            activity_type=ActivityType.RECORD_IMPORTED,
            description="Imported from legacy workbook.",
            actor_id=actor_id,
            customer_id=customer.id,
            job_id=job.id,
            meta={"batch_id": batch_id, "source_row_index": sidx, "legacy_reference": legacy},
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
