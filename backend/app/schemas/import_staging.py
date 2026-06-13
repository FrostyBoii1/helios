"""Read schemas for import staging (Phase A — inspect a parsed batch)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import ImportBatchStatus, ImportRowClass, ImportRowReviewStatus


class ImportBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_filename: str
    sheet_name: str
    file_sha256: str | None = None
    status: ImportBatchStatus
    total_rows: int
    job_rows: int
    divider_rows: int
    blank_rows: int
    ambiguous_rows: int
    issue_count: int
    notes: str | None = None
    created_by_id: int | None = None
    created_at: datetime


class ImportBatchList(BaseModel):
    items: list[ImportBatchRead]
    total: int


class ImportIssueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    severity: str
    field: str | None = None
    message: str
    resolved: bool
    # Resolution audit (read-only; surfaced for the review UI).
    resolution_note: str | None = None
    resolved_by_id: int | None = None
    resolved_at: datetime | None = None


class ImportRowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_row_index: int
    row_class: ImportRowClass
    legacy_reference: str | None = None
    raw: dict[str, Any] | None = None
    parsed: dict[str, Any] | None = None
    # Immutable parser output snapshot, set on the first reviewer edit; lets the
    # UI mark which parsed fields a reviewer has changed.
    original_parsed: dict[str, Any] | None = None
    context_text: str | None = None
    review_status: ImportRowReviewStatus
    review_notes: str | None = None
    reviewer_id: int | None = None
    reviewed_at: datetime | None = None
    committed_customer_id: int | None = None
    committed_job_id: int | None = None
    issues: list[ImportIssueRead] = []


class ImportRowList(BaseModel):
    items: list[ImportRowRead]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------------------- #
# Phase B review schemas
# --------------------------------------------------------------------------- #
class PhoneEntry(BaseModel):
    number: str
    label: str = ""


class ImportRowEdit(BaseModel):
    """Whitelisted, typed edits to a row's parsed candidate.

    Only these fields may be changed — arbitrary parsed-JSON patches are NOT
    accepted. Unset fields are left untouched. `review_notes` updates the row
    note (not part of `parsed`).
    """

    model_config = ConfigDict(extra="forbid")

    customer_name: str | None = None
    salesperson: str | None = None
    sale_date: str | None = None
    install_date: str | None = None
    install_day: str | None = None
    install_time: str | None = None
    approval_state: str | None = None
    approval_pending_date: str | None = None
    distributor_inferred: str | None = None
    retailer_raw: str | None = None
    nmi_raw: str | None = None
    meter_no: str | None = None
    no_of_panels: str | None = None
    panel_raw: str | None = None
    inverter_raw: str | None = None
    msb_state: str | None = None
    notes_raw: str | None = None
    emails: list[str] | None = None
    phones: list[PhoneEntry] | None = None

    review_notes: str | None = None


# Fields above that are merged into `parsed` (everything except review_notes).
PARSED_EDIT_FIELDS = frozenset(ImportRowEdit.model_fields) - {"review_notes"}


class ReviewActionRequest(BaseModel):
    """Optional note for reject/skip/reopen actions."""

    notes: str | None = None


class IssueResolveRequest(BaseModel):
    resolution_note: str | None = None


class BulkApproveResult(BaseModel):
    approved: int
    eligible_examined: int


class ImportBatchSummary(BaseModel):
    batch_id: int
    by_review_status: dict[str, int]
    by_row_class: dict[str, int]
    issues_by_severity: dict[str, int]
    unresolved_error_rows: int
    # Pending job/ambiguous rows with no unresolved error issue — i.e. how many
    # rows a bulk "approve clean" would approve right now.
    eligible_clean_count: int


# --------------------------------------------------------------------------- #
# Phase C0 — commit PREVIEW (read-only; describes what a future commit WOULD do)
# --------------------------------------------------------------------------- #
class CommitCustomerPreview(BaseModel):
    full_name: str
    email: str | None = None
    phone: str | None = None
    address_line1: str | None = None
    extra_emails: list[str] = []
    extra_phones: list[str] = []


class CommitJobPreview(BaseModel):
    predicted_case_number: str
    legacy_reference: str | None = None
    status: str
    sale_date: str | None = None
    install_date: str | None = None
    salesperson_text: str | None = None
    system_details: str | None = None
    install_details: str | None = None
    approval_details: str | None = None
    notes: str | None = None


class CommitRowPreview(BaseModel):
    row_id: int
    source_row_index: int
    legacy_reference: str | None = None
    case_year: int
    predicted_case_number: str
    customer: CommitCustomerPreview
    job: CommitJobPreview


class CommitExcludedCounts(BaseModel):
    already_committed: int
    blank_or_divider: int
    not_approved: int
    unresolved_error: int
    missing_customer_name: int


class CommitWouldCreate(BaseModel):
    customers: int
    jobs: int


class ImportCommitPreview(BaseModel):
    batch_id: int
    total_rows: int
    eligible_count: int
    excluded: CommitExcludedCounts
    would_create: CommitWouldCreate
    predicted_case_numbers_by_year: dict[str, int]
    sample_limit: int
    sample_truncated: bool
    samples: list[CommitRowPreview]
