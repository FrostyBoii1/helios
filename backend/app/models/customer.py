"""Customer model.

A customer is a person/organisation that may have ONE OR MORE jobs over time.
Customer and Job are deliberately separate entities (see business_rules.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, Text
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

    # Non-destructive cascade: customers are soft-deleted (deleted_at), never
    # hard-deleted, so child jobs must NOT be cascade-deleted. "save-update,
    # merge" persists relationship changes without delete/orphan-removal.
    jobs: Mapped[list["Job"]] = relationship(
        back_populates="customer",
        cascade="save-update, merge",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Customer {self.id} {self.full_name}>"
