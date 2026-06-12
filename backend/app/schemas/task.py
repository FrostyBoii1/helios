"""Task schemas: create, partial update, completion, read, paginated list."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TaskPriority, TaskStatus
from app.schemas.job import CustomerRef


class UserRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str


class JobRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_number: str


class TaskBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    priority: TaskPriority | None = None
    due_date: datetime | None = None
    customer_id: int | None = None
    job_id: int | None = None
    assigned_to_id: int | None = None


class TaskCreate(TaskBase):
    """Create payload. created_by is taken from the authenticated user."""


class TaskUpdate(BaseModel):
    """Partial update of descriptive fields and/or assignee."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    priority: TaskPriority | None = None
    due_date: datetime | None = None
    customer_id: int | None = None
    job_id: int | None = None
    assigned_to_id: int | None = None


class TaskComplete(BaseModel):
    notes: str | None = None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None = None
    status: TaskStatus
    priority: TaskPriority
    due_date: datetime | None = None
    is_overdue: bool

    customer_id: int | None = None
    job_id: int | None = None
    assigned_to_id: int | None = None
    created_by_id: int | None = None

    assigned_to: UserRef | None = None
    created_by: UserRef | None = None
    completed_by: UserRef | None = None
    customer: CustomerRef | None = None
    job: JobRef | None = None

    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TaskList(BaseModel):
    items: list[TaskRead]
    total: int
    limit: int
    offset: int
