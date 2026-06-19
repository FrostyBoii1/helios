"""Job schemas: create, partial update, status change, read, paginated list."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import JobLabelCategory, JobStatus


class JobBase(BaseModel):
    """Editable descriptive + scheduling fields (all optional)."""

    title: str | None = Field(default=None, max_length=200)
    system_details: str | None = None
    install_details: str | None = None
    approval_details: str | None = None
    notes: str | None = None
    internal_notes: str | None = None
    # Structured, registry-shaped attributes. On CREATE (commit) this is a full
    # object; on UPDATE (Phase 4b) it is treated as a path-restricted PARTIAL
    # PATCH — validated against the field registry and deep-merged, never a full
    # replacement (see services.details_patch + endpoints.jobs.update_job).
    details: dict[str, Any] | None = None
    sale_date: date | None = None
    install_date: date | None = None
    salesperson_id: int | None = None
    assigned_user_id: int | None = None


class JobCreate(JobBase):
    """Create payload. Status always starts at NEW; case_number is generated."""

    customer_id: int


class JobUpdate(JobBase):
    """Partial update of descriptive fields and/or install_date."""


class JobStatusUpdate(BaseModel):
    status: JobStatus


class CustomerRef(BaseModel):
    """Lightweight customer reference embedded in job responses. suburb/state are
    additive read-only fields used by the Jobs list's Suburb/State column."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    suburb: str | None = None
    state: str | None = None


class JobLabelChip(BaseModel):
    """Minimal label info embedded per job for the Jobs list (chips + filtering),
    so the list never needs a per-row /jobs/{id}/labels round-trip."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    color: str
    category: JobLabelCategory
    is_system: bool


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_number: str
    legacy_reference: str | None = None
    customer_id: int
    customer: CustomerRef
    # Read-only, API-COMPUTED provenance: when a customer MERGE moved this job into its
    # current customer under a DIFFERENT (loser/source) name, that original name — so a
    # merged customer's job list can show "originally <name>". Null for normal/same-name/
    # unmerged jobs. Derived from CUSTOMER_MERGED activity metadata; the job's real customer
    # source of truth is unchanged. Populated by the list + detail endpoints only.
    source_customer_name: str | None = None
    status: JobStatus
    # Operational labels (approval/decommission/admin/etc.) for the Jobs list. The
    # list endpoint batch-loads these; other JobRead producers leave it empty (the
    # Job detail page reads labels via its own /jobs/{id}/labels call).
    labels: list[JobLabelChip] = []
    title: str | None = None
    system_details: str | None = None
    install_details: str | None = None
    approval_details: str | None = None
    notes: str | None = None
    internal_notes: str | None = None
    details: dict[str, Any] | None = None
    sale_date: date | None = None
    install_date: date | None = None
    salesperson_id: int | None = None
    assigned_user_id: int | None = None
    created_at: datetime
    updated_at: datetime


class JobList(BaseModel):
    items: list[JobRead]
    total: int
    limit: int
    offset: int
