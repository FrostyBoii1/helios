"""Activity logging service.

Central helper for appending immutable timeline/audit entries. Endpoints call
`log_activity(...)` whenever an auditable action occurs. The caller controls the
transaction (commit happens with the surrounding unit of work).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.enums import ActivityType


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
