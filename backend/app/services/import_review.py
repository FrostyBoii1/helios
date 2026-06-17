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
from app.models.import_staging import (
    ImportBatch,
    ImportCustomerGroup,
    ImportIssue,
    ImportRow,
)
from app.schemas.import_staging import PARSED_EDIT_FIELDS
from app.services.customers import get_customer
from app.services.import_field_registry import allowed_details_paths

APPROVABLE_CLASSES = (ImportRowClass.JOB.value, ImportRowClass.AMBIGUOUS.value)

# A row's internal_notes_override may only be edited before it is finalized. Once
# approved (or committed/reversed) it is locked — the reviewer must reopen the row
# to edit it again.
_OVERRIDE_LOCKED_STATES = frozenset({
    ImportRowReviewStatus.APPROVED.value,
    ImportRowReviewStatus.COMMITTED.value,
    ImportRowReviewStatus.REVERSED.value,
})

# B2-1: customer resolution, like internal_notes_override, may only be changed
# while the row is still PENDING — once approved/committed/reversed it is locked
# (reopen to change). Mirrors the override lock so review and resolution can't
# drift after a row is finalized.
_RESOLUTION_LOCKED_STATES = _OVERRIDE_LOCKED_STATES


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
    # internal_notes_override is a column on the row (NOT part of `parsed`). Applied
    # by KEY PRESENCE (the endpoint uses model_dump(exclude_unset=True)) so the
    # client can send null (reset to generated), "" (commit blank), or text (commit
    # verbatim). Locked once the row is approved/committed/reversed.
    override_set = "internal_notes_override" in edits
    override_value = edits.pop("internal_notes_override", None)
    field_edits = {k: v for k, v in edits.items() if k in PARSED_EDIT_FIELDS}

    if override_set and row.review_status in _OVERRIDE_LOCKED_STATES:
        raise ValueError(
            "Internal notes can only be edited before approval — reopen the row to edit."
        )

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
    if override_set:
        row.internal_notes_override = override_value

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
    # D (stabilization): committed and reversed rows are terminal — they own (or owned)
    # live records, so they cannot be reopened to pending through the normal review
    # path. A reverse-then-recommit flow is a separate, larger guarded design.
    if new_status == ImportRowReviewStatus.PENDING and row.review_status in (
        ImportRowReviewStatus.COMMITTED.value,
        ImportRowReviewStatus.REVERSED.value,
    ):
        raise ValueError("Committed and reversed rows are final and cannot be reopened.")
    row.review_status = new_status
    row.reviewer_id = actor_id
    row.reviewed_at = _now()
    if notes is not None:
        row.review_notes = notes
    _mark_reviewing(batch)
    return row


# --------------------------------------------------------------------------- #
# B2-1: manual same-customer resolution (storage only — no commit effect yet)
# --------------------------------------------------------------------------- #
def _ensure_resolution_editable(row: ImportRow) -> None:
    """Guard: resolution may only change while the row is pending and uncommitted."""
    if row.committed_customer_id is not None or row.committed_job_id is not None:
        raise ValueError("This row is already committed — its customer resolution is locked.")
    if row.review_status in _RESOLUTION_LOCKED_STATES:
        raise ValueError(
            "Customer resolution can only be changed while the row is pending — "
            "reopen the row to edit."
        )


def _stamp_resolution(row: ImportRow, *, actor_id: int) -> None:
    row.resolved_by_id = actor_id
    row.resolved_at = _now()


def set_resolution_existing(
    db: Session,
    batch: ImportBatch,
    row: ImportRow,
    *,
    customer_id: int,
    actor_id: int,
    reason: str | None = None,
) -> ImportRow:
    """Resolve the row to an EXISTING live customer (B2-1, storage only).

    Raises ValueError if the row is locked or the target customer does not exist /
    is soft-deleted. Never silently falls back to "new".
    """
    _ensure_resolution_editable(row)
    customer = get_customer(db, customer_id)  # excludes soft-deleted (deleted_at)
    if customer is None:
        raise ValueError(f"Customer {customer_id} was not found or has been deleted.")
    _leave_group(db, row)  # B3-2: switching to an existing customer detaches any group
    row.customer_resolution_mode = "existing"
    row.resolved_customer_id = customer.id
    row.customer_resolution_reason = reason
    _stamp_resolution(row, actor_id=actor_id)
    _mark_reviewing(batch)
    return row


def set_resolution_new(
    db: Session,
    batch: ImportBatch,
    row: ImportRow,
    *,
    actor_id: int,
    reason: str | None = None,
) -> ImportRow:
    """Resolve the row to explicitly create a NEW customer (B2-1, storage only)."""
    _ensure_resolution_editable(row)
    _leave_group(db, row)  # B3-2: switching to "new" detaches any group
    row.customer_resolution_mode = "new"
    row.resolved_customer_id = None
    row.customer_resolution_reason = reason
    _stamp_resolution(row, actor_id=actor_id)
    _mark_reviewing(batch)
    return row


def clear_resolution(
    db: Session, batch: ImportBatch, row: ImportRow, *, actor_id: int
) -> ImportRow:
    """Clear the row's resolution back to unresolved (B2-1, storage only)."""
    _ensure_resolution_editable(row)
    _leave_group(db, row)  # B3-2: clearing also detaches any group
    row.customer_resolution_mode = None
    row.resolved_customer_id = None
    row.customer_resolution_reason = None
    row.resolved_by_id = None
    row.resolved_at = None
    _mark_reviewing(batch)
    return row


# --------------------------------------------------------------------------- #
# B3-2: pending-row grouping (storage only — no commit effect yet)
# --------------------------------------------------------------------------- #
GROUPABLE_CLASSES = APPROVABLE_CLASSES  # job/ambiguous


def get_group(db: Session, batch_id: int, group_id: int) -> ImportCustomerGroup | None:
    return db.scalar(
        select(ImportCustomerGroup).where(
            ImportCustomerGroup.id == group_id, ImportCustomerGroup.batch_id == batch_id
        )
    )


def list_groups(db: Session, batch_id: int) -> list[ImportCustomerGroup]:
    return list(
        db.scalars(
            select(ImportCustomerGroup)
            .where(ImportCustomerGroup.batch_id == batch_id)
            .order_by(ImportCustomerGroup.id)
        ).all()
    )


def group_member_rows(db: Session, group_id: int) -> list[ImportRow]:
    """Members of a group, in source order.

    Flushes first so PENDING membership writes made earlier in the same request
    (e.g. a row's customer_group_id just set/cleared) are visible to this SELECT
    REGARDLESS of the session's autoflush setting. Production get_db()/SessionLocal
    uses autoflush=False, so the reconcile / dict-building / unlock logic must not
    rely on implicit autoflush (the test session is autoflush=True, which would
    otherwise mask this)."""
    db.flush()
    return list(
        db.scalars(
            select(ImportRow)
            .where(ImportRow.customer_group_id == group_id)
            .order_by(ImportRow.source_row_index)
        ).all()
    )


def _clear_group_fields(row: ImportRow) -> None:
    """Detach a row from its group and reset 'group' resolution back to unresolved.
    (A row resolved to existing/new keeps that mode; only 'group' is cleared.)"""
    row.customer_group_id = None
    if row.customer_resolution_mode == "group":
        row.customer_resolution_mode = None
        row.customer_resolution_reason = None
        row.resolved_by_id = None
        row.resolved_at = None


def _leave_group(db: Session, row: ImportRow) -> None:
    """Remove a row from any group, then reconcile that group: auto-dissolve if it
    drops below 2 members, or auto-promote a new primary if the primary left. The
    caller sets the row's NEW mode (existing/new/null) afterwards."""
    gid = row.customer_group_id
    if gid is None:
        return
    row.customer_group_id = None
    group = db.get(ImportCustomerGroup, gid)
    if group is None:
        return
    members = group_member_rows(db, gid)  # autoflush -> excludes the leaving row
    if len(members) < 2:
        for m in members:
            _clear_group_fields(m)  # lone member reverts to unresolved
        db.flush()  # clear member FKs before deleting the group (mutual FK)
        db.delete(group)
    elif group.primary_row_id == row.id:
        group.primary_row_id = members[0].id  # auto-promote lowest source_row_index


def _validate_groupable(db: Session, batch: ImportBatch, row: ImportRow) -> None:
    if row.row_class not in GROUPABLE_CLASSES:
        raise ValueError(
            f"Only job/ambiguous rows can be grouped (row {row.id} is {row.row_class})."
        )
    _ensure_resolution_editable(row)  # pending + uncommitted (same lock as resolution)


def _ensure_group_unlocked(db: Session, group: ImportCustomerGroup) -> None:
    """A group's structure may change only while ALL members are pending."""
    for m in group_member_rows(db, group.id):
        if (
            m.committed_customer_id is not None
            or m.committed_job_id is not None
            or m.review_status in _RESOLUTION_LOCKED_STATES
        ):
            raise ValueError(
                "This group is locked — a member has been approved/committed. "
                "Reopen the member to change the group."
            )


def _set_group_membership(
    db: Session, group: ImportCustomerGroup, row: ImportRow, *, actor_id: int
) -> None:
    # B (stabilization): never silently STEAL a row out of another group. If it is
    # already a member of THIS group, this is an idempotent no-op; if it belongs to a
    # DIFFERENT group, reject — the reviewer must remove it from that group first (or
    # join this row to the existing group rather than pulling the member out).
    if row.customer_group_id == group.id:
        return
    if row.customer_group_id is not None:
        raise ValueError(
            "This row is already in another group — remove it from that group first, "
            "or join this row to the existing group."
        )
    row.customer_group_id = group.id
    row.customer_resolution_mode = "group"
    row.resolved_customer_id = None  # mutual exclusion with B2 existing-resolution
    _stamp_resolution(row, actor_id=actor_id)


def create_group(
    db: Session,
    batch: ImportBatch,
    *,
    primary_row_id: int,
    member_row_ids: list[int],
    actor_id: int,
    reason: str | None = None,
) -> ImportCustomerGroup:
    """Create a group from the primary row + the given members (>= 2 rows total)."""
    ids = list(dict.fromkeys([primary_row_id, *member_row_ids]))  # unique, primary first
    if len(ids) < 2:
        raise ValueError("A group needs at least 2 rows.")
    rows: list[ImportRow] = []
    for rid in ids:
        r = get_row(db, batch.id, rid)
        if r is None:
            raise ValueError(f"Row {rid} is not in this batch.")
        _validate_groupable(db, batch, r)
        rows.append(r)
    group = ImportCustomerGroup(
        batch_id=batch.id, primary_row_id=primary_row_id, created_by_id=actor_id, reason=reason
    )
    db.add(group)
    db.flush()  # assign group.id
    for r in rows:
        _set_group_membership(db, group, r, actor_id=actor_id)
    _mark_reviewing(batch)
    return group


def add_to_group(
    db: Session, batch: ImportBatch, group: ImportCustomerGroup, *, row_id: int, actor_id: int
) -> ImportCustomerGroup:
    _ensure_group_unlocked(db, group)
    row = get_row(db, batch.id, row_id)
    if row is None:
        raise ValueError(f"Row {row_id} is not in this batch.")
    _validate_groupable(db, batch, row)
    _set_group_membership(db, group, row, actor_id=actor_id)
    _mark_reviewing(batch)
    return group


def remove_from_group(
    db: Session, batch: ImportBatch, group: ImportCustomerGroup, *, row_id: int, actor_id: int
) -> ImportCustomerGroup | None:
    """Remove a member. Returns the group, or None if it auto-dissolved (< 2 left)."""
    _ensure_group_unlocked(db, group)
    row = get_row(db, batch.id, row_id)
    if row is None or row.customer_group_id != group.id:
        raise ValueError(f"Row {row_id} is not a member of this group.")
    _clear_group_fields(row)
    members = group_member_rows(db, group.id)  # autoflush -> excludes the removed row
    if len(members) < 2:
        for m in members:
            _clear_group_fields(m)
        db.flush()  # clear member FKs before deleting the group
        db.delete(group)
        _mark_reviewing(batch)
        return None
    if group.primary_row_id == row_id:
        group.primary_row_id = members[0].id  # auto-promote lowest source_row_index
    _mark_reviewing(batch)
    return group


def set_group_primary(
    db: Session, batch: ImportBatch, group: ImportCustomerGroup, *, primary_row_id: int, actor_id: int
) -> ImportCustomerGroup:
    _ensure_group_unlocked(db, group)
    member_ids = {m.id for m in group_member_rows(db, group.id)}
    if primary_row_id not in member_ids:
        raise ValueError("The primary must be a member of the group.")
    group.primary_row_id = primary_row_id
    _mark_reviewing(batch)
    return group


def dissolve_group(
    db: Session, batch: ImportBatch, group: ImportCustomerGroup, *, actor_id: int
) -> None:
    """Dissolve a group: clear every member's group fields, then delete the group."""
    _ensure_group_unlocked(db, group)
    for m in group_member_rows(db, group.id):
        _clear_group_fields(m)
    db.flush()  # clear member FKs before deleting the group (mutual FK)
    db.delete(group)
    _mark_reviewing(batch)


def group_to_dict(db: Session, group: ImportCustomerGroup) -> dict:
    """Assemble a CustomerGroupRead-shaped dict (id, primary, members) for the API."""
    members = group_member_rows(db, group.id)
    return {
        "id": group.id,
        "batch_id": group.batch_id,
        "primary_row_id": group.primary_row_id,
        "committed_customer_id": group.committed_customer_id,
        "created_by_id": group.created_by_id,
        "created_at": group.created_at,
        "reason": group.reason,
        "member_row_ids": [m.id for m in members],
        "members": [
            {
                "row_id": m.id,
                "source_row_index": m.source_row_index,
                "customer_name": (m.parsed or {}).get("customer_name"),
                "is_primary": m.id == group.primary_row_id,
            }
            for m in members
        ],
    }


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
