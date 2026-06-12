"""Activity timeline endpoint (read-only).

Surfaces the append-only audit trail. Any authenticated user may read; at least
one of customer_id / job_id must be provided (no global feed in this phase).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.activity import ActivityList, ActivityRead
from app.services.activity import list_activities

router = APIRouter()


@router.get("", response_model=ActivityList)
def list_activity_timeline(
    customer_id: int | None = Query(default=None),
    job_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ActivityList:
    if customer_id is None and job_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide customer_id and/or job_id",
        )

    items, total = list_activities(
        db, customer_id=customer_id, job_id=job_id, limit=limit, offset=offset
    )
    return ActivityList(
        items=[ActivityRead.model_validate(a) for a in items],
        total=total,
        limit=limit,
        offset=offset,
    )
