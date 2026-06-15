"""Job label (operational flag) models — Phase L1.

Two tables, following the established normalized + soft-delete + audit patterns:

  * ``JobLabelDefinition`` — the catalogue of labels (seeded system presets +
    later user-created). Carries display metadata (name, category, color,
    description) and policy flags (``is_system`` = protected/locked from casual
    edit, ``is_auto`` = assignable by the import commit). Soft-deleted so a
    retired label never orphans history.
  * ``JobLabelAssignment`` — a many-to-many link between a Job and a definition,
    with provenance (``source``, ``assigned_by_id``) and an optional ``note``
    (e.g. the decommission marker or an approval reference). A unique constraint
    enforces at most one assignment per (job, label). Removal is a hard delete
    (logged separately via Activity in later phases), so "active" == "exists".

Phase L1 is a READ-ONLY foundation: models + migration + seed + read APIs. No
write endpoints, no import_commit auto-assignment, and no Job relationship change
yet (those arrive in L2/L3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.enums import JobLabelCategory, JobLabelSource
from app.models.mixins import IntPkMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    pass


class JobLabelDefinition(IntPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "job_label_definitions"

    # Stable machine slug (unique), e.g. "approval_approved". Never shown raw.
    key: Mapped[str] = mapped_column(String(60), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[JobLabelCategory] = mapped_column(String(20), nullable=False, index=True)
    # Display colour token (e.g. "green"/"amber"/"red"); the frontend maps it to a
    # concrete Tailwind class. Kept as a token, not a raw hex, for theming.
    color: Mapped[str] = mapped_column(String(40), nullable=False, default="slate")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Protected preset: cannot be casually removed/edited by ordinary label editing
    # (approval + decommission presets). User-created labels are is_system=False.
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Eligible for automatic assignment by the import commit (Phase L3).
    is_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<JobLabelDefinition {self.id} {self.key!r} category={self.category}>"


class JobLabelAssignment(IntPkMixin, TimestampMixin, Base):
    __tablename__ = "job_label_assignments"
    __table_args__ = (
        UniqueConstraint("job_id", "label_id", name="uq_job_label_assignments_job_label"),
    )

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    label_id: Mapped[int] = mapped_column(
        ForeignKey("job_label_definitions.id"), nullable=False, index=True
    )
    source: Mapped[JobLabelSource] = mapped_column(
        String(20), nullable=False, default=JobLabelSource.MANUAL
    )
    assigned_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Optional supporting text: a decommission marker, an approval reference, etc.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    label: Mapped["JobLabelDefinition"] = relationship(lazy="joined")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<JobLabelAssignment {self.id} job={self.job_id} label={self.label_id}>"
