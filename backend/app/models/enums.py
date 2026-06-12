"""Enumerations shared across models and schemas.

Kept in one place so the API, DB, and frontend (via generated types) agree on the
allowed values. Stored as strings in PostgreSQL for readability and easy search.
"""

from __future__ import annotations

import enum


class RoleName(str, enum.Enum):
    """Canonical role identities. Seeded into the `roles` table.

    Roles are also stored as rows (so they can carry descriptions and evolve),
    but this enum is the source of truth for the fixed set the app understands.
    """

    ADMIN = "admin"
    SCHEDULING = "scheduling"
    APPROVALS = "approvals"
    SUPPORT = "support"
    SALES_ADMIN = "sales_admin"


class JobStatus(str, enum.Enum):
    """Lifecycle status of a job. Drives dashboards and filtering."""

    NEW = "new"
    AWAITING_APPROVAL = "awaiting_approval"
    READY_TO_SCHEDULE = "ready_to_schedule"
    BOOKED_FOR_INSTALL = "booked_for_install"
    INSTALLED = "installed"
    POST_INSTALL_CALL_REQUIRED = "post_install_call_required"
    REVIEW_REQUEST_REQUIRED = "review_request_required"
    MAINTENANCE_REQUIRED = "maintenance_required"
    SUPPORT = "support"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ActivityType(str, enum.Enum):
    """Append-only timeline event categories.

    Not exhaustive — extend as new logged actions appear. The activity row also
    stores free-form `description` and structured `meta` for detail.
    """

    JOB_CREATED = "job_created"
    JOB_UPDATED = "job_updated"
    JOB_STATUS_CHANGED = "job_status_changed"
    JOB_DELETED = "job_deleted"
    INSTALL_RESCHEDULED = "install_rescheduled"
    CUSTOMER_CREATED = "customer_created"
    CUSTOMER_UPDATED = "customer_updated"
    CUSTOMER_DELETED = "customer_deleted"
    TASK_ASSIGNED = "task_assigned"
    TASK_COMPLETED = "task_completed"
    NOTE_ADDED = "note_added"
    FILE_UPLOADED = "file_uploaded"
    FILE_DELETED = "file_deleted"
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
