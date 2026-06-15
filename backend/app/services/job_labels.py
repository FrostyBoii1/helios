"""Job label services (Phase L1, read-only).

Pure read helpers over the label catalogue and a job's assignments. Write paths
(assign/remove, auto-assign on commit) arrive in later phases.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import JobLabelSource
from app.models.job_label import JobLabelAssignment, JobLabelDefinition


def list_label_definitions(
    db: Session, *, include_deleted: bool = False
) -> list[JobLabelDefinition]:
    """All label definitions in stable display order (sort_order, then id).

    Soft-deleted definitions are excluded unless ``include_deleted`` is True.
    """
    stmt = select(JobLabelDefinition)
    if not include_deleted:
        stmt = stmt.where(JobLabelDefinition.deleted_at.is_(None))
    stmt = stmt.order_by(JobLabelDefinition.sort_order, JobLabelDefinition.id)
    return list(db.scalars(stmt).all())


def get_label_by_key(db: Session, key: str) -> JobLabelDefinition | None:
    """A single active definition by its slug, or None."""
    return db.scalar(
        select(JobLabelDefinition).where(
            JobLabelDefinition.key == key,
            JobLabelDefinition.deleted_at.is_(None),
        )
    )


def list_job_labels(db: Session, job_id: int) -> list[JobLabelAssignment]:
    """A job's label assignments, ordered by their definition's display order.

    Assignments whose definition has been soft-deleted are excluded. Returns an
    empty list for a job with no labels.
    """
    stmt = (
        select(JobLabelAssignment)
        .join(JobLabelDefinition, JobLabelAssignment.label_id == JobLabelDefinition.id)
        .where(
            JobLabelAssignment.job_id == job_id,
            JobLabelDefinition.deleted_at.is_(None),
        )
        .order_by(JobLabelDefinition.sort_order, JobLabelAssignment.id)
    )
    return list(db.scalars(stmt).all())


# --------------------------------------------------------------------------- #
# Assignment (Phase L3) — idempotent assign + pure import auto-label derivation
# --------------------------------------------------------------------------- #
def assign_label_by_key(
    db: Session,
    *,
    job_id: int,
    key: str,
    source: JobLabelSource,
    assigned_by_id: int | None = None,
    note: str | None = None,
) -> JobLabelAssignment | None:
    """Idempotently assign the label ``key`` to a job.

    Returns the existing assignment if the (job, label) pair is already present
    (no duplicate is created), the new assignment on first creation, or ``None``
    if ``key`` is not a known active label. Caller commits.
    """
    label = get_label_by_key(db, key)
    if label is None:
        return None
    existing = db.scalar(
        select(JobLabelAssignment).where(
            JobLabelAssignment.job_id == job_id,
            JobLabelAssignment.label_id == label.id,
        )
    )
    if existing is not None:
        return existing
    assignment = JobLabelAssignment(
        job_id=job_id,
        label_id=label.id,
        source=source,
        assigned_by_id=assigned_by_id,
        note=note,
    )
    db.add(assignment)
    db.flush()
    return assignment


def auto_label_keys(
    parsed: dict[str, Any] | None, details: dict[str, Any] | None
) -> list[tuple[str, str | None]]:
    """Pure: the (label_key, note) pairs to auto-assign to a committed job from its
    parsed candidate + structured details.

    Conservative rules (Phase L3 — no battery/solar inference yet):
      * approval_state == "approved" -> approval_approved
      * approval_state == "pending"  -> approval_pending (note carries pending date)
      * details.flags.removes_old_system -> decommission_pre_existing
        (note carries the decommission marker text)

    Labels are additive: the approval reference phrase and any source text stay in
    details.notes.review_notes — this never reads or mutates them.
    """
    parsed = parsed or {}
    details = details or {}
    out: list[tuple[str, str | None]] = []

    state = str(parsed.get("approval_state") or "").strip().lower()
    if state == "approved":
        out.append(("approval_approved", None))
    elif state == "pending":
        pending = str(parsed.get("approval_pending_date") or "").strip()
        out.append(("approval_pending", f"pending {pending}" if pending else None))

    flags = details.get("flags") or {}
    if flags.get("removes_old_system"):
        marker = str(flags.get("decommission_marker") or "").strip()
        out.append(("decommission_pre_existing", marker or None))

    return out
