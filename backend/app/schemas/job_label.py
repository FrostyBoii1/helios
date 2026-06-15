"""Job label schemas (Phase L1, read-only).

Definitions (the catalogue) and assignments (a job's labels). Write payloads are
deferred to L2/L3.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import JobLabelCategory, JobLabelSource


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
