"""Activity logging service.

Central helper for appending immutable timeline/audit entries. Endpoints call
`log_activity(...)` whenever an auditable action occurs. The caller controls the
transaction (commit happens with the surrounding unit of work).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models.activity import Activity
from app.models.enums import ActivityType


def list_activities(
    db: Session,
    *,
    customer_id: int | None = None,
    job_id: int | None = None,
    include_imports: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Activity], int]:
    """Return (page of activities, total) for a customer and/or job timeline.

    Activities are append-only and never soft-deleted, so they remain readable
    even if the linked customer/job is later soft-deleted (audit access). A
    customer's timeline includes job activities, because job events are logged
    with both customer_id and job_id. Ordered newest-first.

    `include_imports` defaults to True (no behaviour change). Pass False to omit
    the bulk RECORD_IMPORTED provenance entries — e.g. from a global/dashboard
    feed — without hiding them from a specific job/customer timeline.
    """
    filters = []
    if customer_id is not None:
        filters.append(Activity.customer_id == customer_id)
    if job_id is not None:
        filters.append(Activity.job_id == job_id)
    if not include_imports:
        filters.append(Activity.activity_type != ActivityType.RECORD_IMPORTED)

    total = db.scalar(select(func.count()).select_from(Activity).where(*filters)) or 0

    stmt = (
        select(Activity)
        .options(joinedload(Activity.actor))
        .where(*filters)
        .order_by(Activity.created_at.desc(), Activity.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = list(db.scalars(stmt).all())
    return items, total


def log_activity(
    db: Session,
    *,
    activity_type: ActivityType,
    description: str,
    actor_id: int | None = None,
    customer_id: int | None = None,
    job_id: int | None = None,
    meta: dict[str, Any] | None = None,
) -> Activity:
    """Create and add (not commit) an activity row."""
    entry = Activity(
        activity_type=activity_type,
        description=description,
        actor_id=actor_id,
        customer_id=customer_id,
        job_id=job_id,
        meta=meta,
    )
    db.add(entry)
    return entry
