"""Job label services (Phase L1, read-only).

Pure read helpers over the label catalogue and a job's assignments. Write paths
(assign/remove, auto-assign on commit) arrive in later phases.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

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
