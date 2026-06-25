"""Read schemas for import staging (Phase A — inspect a parsed batch)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    internal_notes_override: str | None = None
    reviewer_id: int | None = None
    reviewed_at: datetime | None = None
    committed_customer_id: int | None = None
    committed_job_id: int | None = None
    # B2-1: manual same-customer resolution intent (storage only; read-only here).
    # mode: null = unresolved (new customer at commit), "new" = explicit new,
    # "existing" = attach to resolved_customer_id. Does not affect commit yet (B2-2).
    resolved_customer_id: int | None = None
    customer_resolution_mode: str | None = None
    customer_resolution_reason: str | None = None
    resolved_by_id: int | None = None
    resolved_at: datetime | None = None
    # B3-2: membership in a pending-row group (mode == "group"); storage only.
    customer_group_id: int | None = None
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
    customer_name_notes: str | None = None
    address: str | None = None
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

    # Phase 3a: partial, path-restricted patch into parsed["details"]. Only the
    # registry's editable job.details.* leaf paths are accepted (validated in the
    # review service); arbitrary keys/sections are rejected.
    details: dict[str, Any] | None = None

    review_notes: str | None = None
    # Override of the seeded Job.internal_notes (a column on ImportRow, NOT part of
    # `parsed`). NULL = generated default, "" = blank, text = verbatim. The review
    # service applies it by key-presence (model_dump(exclude_unset=True)), so the
    # client can explicitly send null to reset to the generated default.
    internal_notes_override: str | None = None
    # legacy_reference is a COLUMN on ImportRow (NOT part of `parsed`): commit-to-live and
    # duplicate detection read row.legacy_reference. The review service applies it to the
    # column and locks it once the row is committed/reversed — so an admin can correct a
    # duplicate SOURCE reference (two distinct jobs that share one ref) before commit.
    # max_length matches the String(64) ImportRow/Job column so an over-long ref is a clean
    # 422 at the schema, never a DataError 500 at commit.
    legacy_reference: str | None = Field(default=None, max_length=64)


# Flat scalar fields merged directly into `parsed` (excludes review_notes, the
# structured details patch, internal_notes_override, and legacy_reference — all handled
# specially in the review service, not merged into `parsed`).
PARSED_EDIT_FIELDS = frozenset(ImportRowEdit.model_fields) - {
    "review_notes",
    "details",
    "internal_notes_override",
    "legacy_reference",
}


# --------------------------------------------------------------------------- #
# Phase 3a — read-only field registry (drives the structured review UI)
# --------------------------------------------------------------------------- #
class FieldSpecRead(BaseModel):
    key: str
    label: str
    section: str
    entity: str
    storage: str
    input_type: str
    visible_when_blank: bool
    category: str
    editable: bool
    source_columns: list[str]
    captured: str
    validation: dict[str, Any]


class FieldRegistryRead(BaseModel):
    sections: list[dict[str, str]]
    fields: list[FieldSpecRead]
    editable_details_paths: list[str]


class ReviewActionRequest(BaseModel):
    """Optional note for reject/skip/reopen actions."""

    notes: str | None = None


class CustomerGroupCreateRequest(BaseModel):
    """Create a pending-row group (B3-2). `primary_row_id` is included as a member
    automatically; `member_row_ids` are the other rows. A group needs >= 2 rows."""

    model_config = ConfigDict(extra="forbid")

    primary_row_id: int
    member_row_ids: list[int] = []
    reason: str | None = None


class CustomerGroupAddRowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_id: int


class CustomerGroupSetPrimaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary_row_id: int


class CustomerGroupMember(BaseModel):
    row_id: int
    source_row_index: int
    customer_name: str | None = None
    is_primary: bool
    # Read-only group-status visibility (committed/reversed members + re-promoted
    # primary after a reverse).
    review_status: str = "pending"
    committed_customer_id: int | None = None


class CustomerGroupRead(BaseModel):
    """A pending-row group (B3-2, storage only). Does not affect commit/preview/
    reverse until B3-3."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int
    primary_row_id: int
    # Unused in B3-2 (set by B3-3 when the primary commits).
    committed_customer_id: int | None = None
    created_by_id: int | None = None
    created_at: datetime
    reason: str | None = None
    member_row_ids: list[int] = []
    members: list[CustomerGroupMember] = []


class CustomerGroupMutationResult(BaseModel):
    """Result of a group mutation that MAY dissolve the group (e.g. remove-row
    dropping it below 2 members). `group` is null when the group was dissolved."""

    dissolved: bool
    group: CustomerGroupRead | None = None


class CustomerResolutionRequest(BaseModel):
    """Set or clear a row's manual same-customer resolution (B2-1, storage only).

    ``mode``:
      * "existing" -> attach this row's job to ``customer_id`` (required; must be
        an existing, non-deleted customer);
      * "new"      -> explicitly resolve to a NEW customer (``customer_id`` ignored);
      * "clear"    -> clear the resolution back to unresolved.

    Editable only while the row is pending (the review service enforces the lock).
    Does NOT affect commit-to-live, preview, or reverse yet (that is B2-2).
    """

    model_config = ConfigDict(extra="forbid")

    mode: Literal["existing", "new", "clear"]
    customer_id: int | None = None
    reason: str | None = None


class IssueResolveRequest(BaseModel):
    resolution_note: str | None = None


class BulkApproveResult(BaseModel):
    approved: int
    eligible_examined: int


class ImportBatchSummary(BaseModel):
    batch_id: int
    by_review_status: dict[str, int]
    by_row_class: dict[str, int]
    # Active (UNRESOLVED) issue counts by severity. Resolved issues are audit/history
    # only and are excluded here, consistent with the severity filter and the per-row
    # IssueBadges. (Type unchanged; only the semantics narrowed to unresolved-only.)
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
    # Additive flags (default-safe): old-system removal + preserved name-cell text.
    removes_old_system: bool = False
    customer_name_notes: str | None = None
    # Phase 2a: registry-shaped structured details (read-only in commit-preview).
    details: dict[str, Any] | None = None


class CommitRowPreview(BaseModel):
    row_id: int
    source_row_index: int
    legacy_reference: str | None = None
    case_year: int
    predicted_case_number: str
    customer: CommitCustomerPreview
    job: CommitJobPreview
    # B2-2/B3-3: how this row's customer is handled. "create" = new customer;
    # "attach" = B2 existing-customer attach; "group_primary" = creates the group's
    # one customer; "group_dependent" = attaches to the group's customer.
    customer_action: Literal["create", "attach", "group_primary", "group_dependent"] = "create"
    resolved_customer_id: int | None = None
    resolved_customer_name: str | None = None
    # B3-3: set on grouped rows so the UI can render the group.
    group_id: int | None = None
    primary_row_id: int | None = None


class CommitExcludedCounts(BaseModel):
    already_committed: int
    blank_or_divider: int
    not_approved: int
    unresolved_error: int
    missing_customer_name: int
    invalid_case_year: int
    # B2-2: row resolved to an existing customer that is now missing/soft-deleted.
    resolved_customer_invalid: int = 0
    # B3-3: grouped dependent whose group's primary won't create a customer this
    # commit, or whose committed group customer is now missing/soft-deleted.
    group_primary_unavailable: int = 0
    group_customer_invalid: int = 0


class CommitWouldCreate(BaseModel):
    customers: int
    jobs: int


class ImportCommitPreview(BaseModel):
    batch_id: int
    total_rows: int
    eligible_count: int
    excluded: CommitExcludedCounts
    would_create: CommitWouldCreate
    # B2-2: eligible jobs that attach to an existing customer (jobs created without
    # a new customer). would_create.customers already excludes these.
    would_attach_jobs: int = 0
    predicted_case_numbers_by_year: dict[str, int]
    sample_limit: int
    sample_truncated: bool
    samples: list[CommitRowPreview]


# --------------------------------------------------------------------------- #
# Phase C1 — commit-to-live (creates Customer + Job)
# --------------------------------------------------------------------------- #
class ImportCommitRequest(BaseModel):
    # Omit to commit all eligible rows (up to the per-call cap). When provided,
    # only these rows are considered (ineligible ones are returned as skips).
    row_ids: list[int] | None = None


class CommitRowResult(BaseModel):
    row_id: int
    source_row_index: int | None = None
    legacy_reference: str | None = None
    status: str  # committed | skipped | failed
    reason: str | None = None
    error: str | None = None
    case_number: str | None = None
    customer_id: int | None = None
    job_id: int | None = None


class ImportCommitResult(BaseModel):
    batch_id: int
    batch_status: str
    attempted: int
    committed: int
    skipped: int
    failed: int
    remaining_eligible: int
    cap: int
    capped_out: int
    results: list[CommitRowResult]


# --------------------------------------------------------------------------- #
# Phase C3 — per-row reverse/undo (soft-delete the created Customer + Job)
# --------------------------------------------------------------------------- #
class ReverseCheck(BaseModel):
    row_id: int
    reversible: bool
    reason: str | None = None
    customer_id: int | None = None
    job_id: int | None = None
    case_number: str | None = None


class ReverseResult(BaseModel):
    row_id: int
    status: str  # reversed | blocked
    reason: str | None = None
    customer_id: int | None = None
    job_id: int | None = None
    case_number: str | None = None


class MatchCandidateRead(BaseModel):
    """One advisory same-customer candidate for an import row (Section B1).

    Advisory only — no action is implied. ``kind`` is "batch_row" (another row in
    the same import batch) or "live_customer" (an existing customer). ``reasons``
    are human-readable match signals; ``confidence`` is one of strong/medium/weak.
    """

    kind: Literal["batch_row", "live_customer"]
    name: str
    confidence: Literal["strong", "medium", "weak"]
    reasons: list[str]
    row_id: int | None = None
    source_row_index: int | None = None
    customer_id: int | None = None
    # B (stabilization): the batch-row candidate's pending group (if any), so the UI
    # can offer "Join this group" rather than silently stealing the row. Null for a
    # live-customer candidate or an ungrouped row.
    customer_group_id: int | None = None
