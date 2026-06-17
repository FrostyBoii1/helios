"""Spreadsheet import staging models (Phase A — parse-only).

These tables hold parsed legacy-workbook data for human review. NOTHING here
writes to live Customer/Job; rows are committed to live tables only by a future,
separately-approved commit phase. Raw cell values are preserved verbatim;
structured candidates and issues are stored as JSONB / first-class rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.enums import ImportBatchStatus, ImportRowClass, ImportRowReviewStatus
from app.models.mixins import IntPkMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class ImportBatch(IntPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """One ingest of a workbook sheet. Stores filename + hash only (never a path)."""

    __tablename__ = "import_batches"

    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(120), nullable=False)
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[ImportBatchStatus] = mapped_column(
        String(20), default=ImportBatchStatus.PARSING, nullable=False, index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    total_rows: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    job_rows: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    divider_rows: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    blank_rows: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    ambiguous_rows: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    issue_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped["User | None"] = relationship()
    rows: Mapped[list["ImportRow"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ImportBatch {self.id} {self.source_filename!r} status={self.status}>"


class ImportRow(IntPkMixin, TimestampMixin, Base):
    """A single parsed spreadsheet row. `raw` preserves every cell verbatim."""

    __tablename__ = "import_rows"

    batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id"), nullable=False, index=True
    )
    source_row_index: Mapped[int] = mapped_column(BigInteger, nullable=False)
    row_class: Mapped[ImportRowClass] = mapped_column(String(20), nullable=False, index=True)
    legacy_reference: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    parsed: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Immutable snapshot of the parser's output, taken on the first reviewer edit
    # so the original suggestion is preserved alongside the edited `parsed`.
    original_parsed: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    context_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    review_status: Mapped[ImportRowReviewStatus] = mapped_column(
        String(20), default=ImportRowReviewStatus.PENDING, nullable=False, index=True
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Reviewer's explicit override of what import commit seeds into
    # Job.internal_notes. NULL = use the generated build_imported_notes default;
    # "" (empty string) = commit blank internal notes; any other text = commit it
    # verbatim. Editable only before approval (the review service guards this).
    internal_notes_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Set ONLY by the future commit phase; null in Phase A (proves no live writes).
    committed_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True
    )
    committed_job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)

    # ----- B2: manual same-customer resolution intent ----------------------- #
    # The reviewer's explicit pre-commit choice for THIS row's customer:
    #   * customer_resolution_mode NULL      -> unresolved; commit creates a new
    #                                           customer (current default behaviour);
    #   * customer_resolution_mode "new"     -> reviewer explicitly chose a new
    #                                           customer (resolved_customer_id NULL);
    #   * customer_resolution_mode "existing"-> attach the job to the EXISTING
    #                                           customer in resolved_customer_id.
    # These fields ARE read by import commit / commit-preview / reverse (B2-2 onward):
    # an 'existing' resolution attaches the job to that live customer, while 'new'/NULL
    # creates one. The review service enforces the mode/customer invariant and only
    # allows edits while the row is pending (locked once approved/committed/reversed).
    resolved_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True, index=True
    )
    customer_resolution_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    customer_resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ----- B3: pending-row grouping ----------------------------------------- #
    # Membership in an ImportCustomerGroup: a set of import rows the reviewer marked
    # as ONE future/live customer with multiple jobs (the group commits to a single
    # Customer at B3-3). Mutually exclusive with resolved_customer_id — a row is
    # unresolved/new, OR resolved to an existing customer ('existing'), OR grouped
    # ('group', customer_group_id set, resolved_customer_id NULL). This grouping IS
    # read by import commit / commit-preview / reverse (B3-3 onward); the review
    # service enforces the mutual exclusion + lock rules. Grouping is a concept
    # distinct from the same-customer resolution above.
    customer_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_customer_groups.id"), nullable=True, index=True
    )

    batch: Mapped["ImportBatch"] = relationship(back_populates="rows")
    issues: Mapped[list["ImportIssue"]] = relationship(
        back_populates="row", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ImportRow {self.id} batch={self.batch_id} class={self.row_class}>"


class ImportIssue(IntPkMixin, TimestampMixin, Base):
    """A data-quality flag attached to a row (kind + severity + message)."""

    __tablename__ = "import_issues"

    row_id: Mapped[int] = mapped_column(ForeignKey("import_rows.id"), nullable=False, index=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    field: Mapped[str | None] = mapped_column(String(60), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    resolved: Mapped[bool] = mapped_column(default=False, nullable=False)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    row: Mapped["ImportRow"] = relationship(back_populates="issues")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ImportIssue {self.id} row={self.row_id} {self.kind}/{self.severity}>"


class ImportCustomerGroup(IntPkMixin, TimestampMixin, Base):
    """A reviewer-defined group of import rows that become ONE future/live customer
    with multiple jobs.

    ``primary_row_id`` is the row that CREATES the customer at commit (B3-3); the other
    members attach their jobs to that customer. This grouping IS read by import commit /
    commit-preview / reverse (B3-3 onward): preview predicts "1 customer + N jobs",
    commit creates the shared customer and attaches dependents, and reverse re-promotes
    the primary / clears ``committed_customer_id`` as members are reversed. Membership
    and the mode/customer mutual-exclusion + lock rules are enforced by the import review
    service. This is staged import-workflow state, NOT a Customer model relation: FK
    columns only (no ORM relationships) to avoid a rows<->groups circular relationship
    config; the service queries members by ``import_rows.customer_group_id``.
    """

    __tablename__ = "import_customer_groups"

    batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id"), nullable=False, index=True
    )
    primary_row_id: Mapped[int] = mapped_column(
        ForeignKey("import_rows.id"), nullable=False, index=True
    )
    # Set by B3-3 when the primary commits (the created live customer). NULL until then.
    committed_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ImportCustomerGroup {self.id} batch={self.batch_id} primary={self.primary_row_id}>"
