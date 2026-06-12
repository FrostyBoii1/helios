"""Activity (timeline/audit) read schemas.

Read-only: the timeline surfaces the append-only audit trail. Responses include
both the human `description` and the raw structured `meta`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import ActivityType


class ActorRef(BaseModel):
    """The user who performed the action (null for system-generated events)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    activity_type: ActivityType
    description: str
    meta: dict[str, Any] | None = None
    created_at: datetime
    actor: ActorRef | None = None
    customer_id: int | None = None
    job_id: int | None = None


class ActivityList(BaseModel):
    items: list[ActivityRead]
    total: int
    limit: int
    offset: int
