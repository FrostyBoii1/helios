"""Job label schemas (Phase L1, read-only).

Definitions (the catalogue) and assignments (a job's labels). Write payloads are
deferred to L2/L3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import JobLabelCategory, JobLabelSource


class JobLabelAssignRequest(BaseModel):
    """Body for adding a label to a job (Phase L2): the label definition's key."""

    key: str = Field(..., min_length=1, max_length=60)


class JobApprovalRequest(BaseModel):
    """Set a job's approval state via the dedicated structured control."""

    state: Literal["none", "required", "pending", "approved"]
    pending_date: str | None = Field(default=None, max_length=40)


class JobApprovalRead(BaseModel):
    """A job's current approval state (derived from its approval label)."""

    state: Literal["none", "required", "pending", "approved"]
    pending_date: str | None = None


class JobLabelDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    name: str
    category: JobLabelCategory
    color: str
    description: str | None = None
    is_system: bool
    is_auto: bool
    sort_order: int


class JobLabelAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    label_id: int
    source: JobLabelSource
    assigned_by_id: int | None = None
    note: str | None = None
    created_at: datetime
    label: JobLabelDefinitionRead
