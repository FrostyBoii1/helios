"""Import review service (Phase B1).

Human review over staged rows: edit the parsed candidate (whitelisted fields),
approve/reject/skip/reopen rows, resolve issues, and bulk-approve clean rows.
NOTHING here writes to live Customer/Job/Task/Activity/Document/NAS — only the
import_* staging tables are touched. Committing to live tables is Phase C.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from app.models.enums import ImportBatchStatus, ImportRowClass, ImportRowReviewStatus
from app.models.import_staging import ImportBatch, ImportIssue, ImportRow
from app.schemas.import_staging import PARSED_EDIT_FIELDS
from app.services.import_field_registry import allowed_details_paths

APPROVABLE_CLASSES = (ImportRowClass.JOB.value, ImportRowClass.AMBIGUOUS.value)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_batch(db: Session, batch_id: int) -> ImportBatch | None:
    return db.scalar(
        select(ImportBatch).where(
            ImportBatch.id == batch_id, ImportBatch.deleted_at.is_(None)
        )
    )


def get_row(db: Session, batch_id: int, row_id: int) -> ImportRow | None:
    return db.scalar(
        select(ImportRow)
        .options(joinedload(ImportRow.issues))
        .where(ImportRow.id == row_id, ImportRow.batch_id == batch_id)
    )


def get_issue(db: Session, batch_id: int, issue_id: int) -> ImportIssue | None:
    return db.scalar(
        select(ImportIssue).where(
            ImportIssue.id == issue_id, ImportIssue.batch_id == batch_id
        )
    )


def _mark_reviewing(batch: ImportBatch) -> None:
    if batch.status == ImportBatchStatus.PARSED:
        batch.status = ImportBatchStatus.REVIEWING


def has_unresolved_error(row: ImportRow) -> bool:
    return any(i.severity == "error" and not i.resolved for i in row.issues)


def _flatten_leaves(patch: dict, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested patch to ``{"<section>.<key>...": value}`` leaf paths."""
    out: dict[str, Any] = {}
    for k, v in (patch or {}).items():
        path = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten_leaves(v, path + "."))
        else:
            out[path] = v
    return out


def apply_details_patch(parsed: dict, patch: dict) -> dict:
    """Return a NEW parsed dict with the details patch deep-merged, path-restricted.

    Only the registry's editable ``job.details.<section>.<key>`` leaf paths may be
    written; any other path (unknown section/key, or a derived/read-only path such
    as flags/provenance/notes.misfiled) raises ValueError (-> HTTP 422). Never
    mutates the input in place.
    """
    leaves = _flatten_leaves(patch)
    allowed = allowed_details_paths()
    disallowed = sorted(p for p in leaves if p not in allowed)
    if disallowed:
        raise ValueError(f"Disallowed details path(s): {disallowed}")

    parsed = copy.deepcopy(parsed or {})
    details = parsed.get("details")
    details = copy.deepcopy(details) if isinstance(details, dict) else {}
    details.setdefault("_v", 2)
    for path, value in leaves.items():
        section, key = path.split(".", 1)
        sect = details.get(section)
        sect = dict(sect) if isinstance(sect, dict) else {}
        sect[key] = value
        details[section] = sect
    parsed["details"] = details
    return parsed


def edit_row(db: Session, batch: ImportBatch, row: ImportRow, edits: dict, *, actor_id: int) -> ImportRow:
    """Apply whitelisted flat edits and/or a structured details patch + optional
    review note (last-write-wins).

    Deep-snapshots the parser's output into `original_parsed` on the first edit so
    nested details edits cannot mutate the preserved suggestion.
    """
    review_notes = edits.pop("review_notes", None)
    details_patch = edits.pop("details", None)
    field_edits = {k: v for k, v in edits.items() if k in PARSED_EDIT_FIELDS}

    if field_edits or details_patch:
        if row.original_parsed is None:
            # Deep copy so subsequent nested details edits never touch the snapshot.
            row.original_parsed = copy.deepcopy(row.parsed or {})
        # Work on a deep copy (validate the details patch BEFORE assigning).
        merged = (
            apply_details_patch(row.parsed or {}, details_patch)
            if details_patch
            else copy.deepcopy(row.parsed or {})
        )
        merged.update(field_edits)
        row.parsed = merged

    if review_notes is not None:
        row.review_notes = review_notes

    row.reviewer_id = actor_id
    row.reviewed_at = _now()
    _mark_reviewing(batch)
    return row


def set_review_status(
    db: Session,
    batch: ImportBatch,
    row: ImportRow,
    new_status: ImportRowReviewStatus,
    *,
    actor_id: int,
    notes: str | None = None,
) -> ImportRow:
    """Approve / reject / skip / reopen a row. Raises ValueError on a gate breach."""
    if new_status == ImportRowReviewStatus.APPROVED:
        if row.row_class not in APPROVABLE_CLASSES:
            raise ValueError("Only job/ambiguous rows can be approved")
        if has_unresolved_error(row):
            raise ValueError("Resolve all error-severity issues before approving")
    row.review_status = new_status
    row.reviewer_id = actor_id
    row.reviewed_at = _now()
    if notes is not None:
        row.review_notes = notes
    _mark_reviewing(batch)
    return row


def resolve_issue(
    db: Session, issue: ImportIssue, *, actor_id: int, note: str | None = None
) -> ImportIssue:
    issue.resolved = True
    issue.resolution_note = note
    issue.resolved_by_id = actor_id
    issue.resolved_at = _now()
    return issue


def bulk_approve_clean(db: Session, batch: ImportBatch, *, actor_id: int) -> tuple[int, int]:
    """Approve all pending job/ambiguous rows with no unresolved error issues.

    Returns (approved_count, eligible_examined). Transactional — caller commits.
    """
    error_row_ids = select(ImportIssue.row_id).where(
        ImportIssue.batch_id == batch.id,
        ImportIssue.severity == "error",
        ImportIssue.resolved.is_(False),
    )
    eligible = [
        ImportRow.batch_id == batch.id,
        ImportRow.review_status == ImportRowReviewStatus.PENDING.value,
        ImportRow.row_class.in_(APPROVABLE_CLASSES),
        ImportRow.id.not_in(error_row_ids),
    ]
    examined_total = db.scalar(
        select(func.count()).select_from(ImportRow).where(
            ImportRow.batch_id == batch.id,
            ImportRow.review_status == ImportRowReviewStatus.PENDING.value,
            ImportRow.row_class.in_(APPROVABLE_CLASSES),
        )
    ) or 0
    result = db.execute(
        update(ImportRow)
        .where(*eligible)
        .values(
            review_status=ImportRowReviewStatus.APPROVED,
            reviewer_id=actor_id,
            reviewed_at=_now(),
        )
        .execution_options(synchronize_session=False)
    )
    _mark_reviewing(batch)
    return result.rowcount or 0, examined_total


def summary(db: Session, batch: ImportBatch) -> dict:
    def counts(col):
        rows = db.execute(
            select(col, func.count()).where(ImportRow.batch_id == batch.id).group_by(col)
        ).all()
        return {str(k): v for k, v in rows}

    issue_rows = db.execute(
        select(ImportIssue.severity, func.count())
        .where(ImportIssue.batch_id == batch.id)
        .group_by(ImportIssue.severity)
    ).all()
    unresolved_error_rows = db.scalar(
        select(func.count(func.distinct(ImportIssue.row_id))).where(
            ImportIssue.batch_id == batch.id,
            ImportIssue.severity == "error",
            ImportIssue.resolved.is_(False),
        )
    ) or 0
    error_row_ids = select(ImportIssue.row_id).where(
        ImportIssue.batch_id == batch.id,
        ImportIssue.severity == "error",
        ImportIssue.resolved.is_(False),
    )
    eligible_clean_count = db.scalar(
        select(func.count()).select_from(ImportRow).where(
            ImportRow.batch_id == batch.id,
            ImportRow.review_status == ImportRowReviewStatus.PENDING.value,
            ImportRow.row_class.in_(APPROVABLE_CLASSES),
            ImportRow.id.not_in(error_row_ids),
        )
    ) or 0
    return {
        "batch_id": batch.id,
        "by_review_status": counts(ImportRow.review_status),
        "by_row_class": counts(ImportRow.row_class),
        "issues_by_severity": {str(k): v for k, v in issue_rows},
        "unresolved_error_rows": unresolved_error_rows,
        "eligible_clean_count": eligible_clean_count,
    }
