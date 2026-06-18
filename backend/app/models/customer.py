"""Customer model.

A customer is a person/organisation that may have ONE OR MORE jobs over time.
Customer and Job are deliberately separate entities (see business_rules.md).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.mixins import IntPkMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.job import Job


class Customer(IntPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "customers"

    full_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)

    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suburb: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    state: Mapped[str | None] = mapped_column(String(60), nullable=True)
    postcode: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    # Legacy/imported source notes (provenance, "other emails/phones", and the
    # rendered import blob). Kept read-only in the UI — distinct from the manual
    # staff-communication field below.
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Manual staff communication notes (Phase A). A free-form, always-visible,
    # editable scratchpad — deliberately separate from imported source notes so
    # the two never mix. Never written by the import pipeline.
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ----- B4-1: explicit-merge storage (no execution yet) ------------------ #
    # When this customer is the LOSER of an explicit admin merge, this points at
    # the WINNER it was merged into; NULL => live / never merged. Self-referential
    # and immutable once set (B4 owner decision). A merged loser is ALSO
    # soft-deleted (deleted_at) by merge EXECUTION — that is B4-2 and is NOT
    # implemented yet. The FK is NO ACTION (Postgres default) so soft-deleting a
    # loser never cascades onto its winner. ``resolve_active_customer()`` walks
    # this chain to the live winner. STORAGE ONLY: no read / search / import /
    # reverse path reads this column yet.
    merged_into_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True, index=True
    )
    # When the merge happened (set together with merged_into_customer_id at B4-2).
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Non-destructive cascade: customers are soft-deleted (deleted_at), never
    # hard-deleted, so child jobs must NOT be cascade-deleted. "save-update,
    # merge" persists relationship changes without delete/orphan-removal.
    jobs: Mapped[list["Job"]] = relationship(
        back_populates="customer",
        cascade="save-update, merge",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Customer {self.id} {self.full_name}>"
