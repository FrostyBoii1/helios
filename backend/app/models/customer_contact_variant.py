"""Customer alternate contact/identity/address variants (Stage 2 — storage + read).

A ``CustomerContactVariant`` preserves an ALTERNATE set of customer-level identity /
contact / address details for a LIVE customer, for when the same real customer is
known by a different name / email / phone / address (e.g. a merged-away duplicate, an
import row, manual entry, or a document). The ``Customer``'s own primary columns stay
authoritative; variants are additive, read-only context shown beside the primary
details — never overwriting them.

This is NOT for job-specific notes or per-job site addresses (those stay on Jobs), and
NOT a parse of the customer's free-text notes — variants come only from structured
sources. Source-derived variants are immutable snapshots for now; archived via
``deleted_at`` (SoftDeleteMixin).

STAGE 2 builds ONLY this table + a read API + a read-only Customer-Detail card. Nothing
populates variants yet: merge capture, import/manual capture, backfill, promote-to-
primary, and edit/archive are all later stages. FK columns only (no ORM relationships)
to avoid an ambiguous multi-customer-FK relationship config — the service queries by
``customer_id``.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base
from app.models.enums import CustomerContactVariantSource
from app.models.mixins import IntPkMixin, SoftDeleteMixin, TimestampMixin


class CustomerContactVariant(IntPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "customer_contact_variants"

    # The LIVE customer this alternate detail set belongs to.
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )

    # Optional human label, e.g. "Old address" / "From merge" (user-set in a later stage).
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Alternate identity/contact/address fields — all optional; mirror Customer's shape.
    display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suburb: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str | None] = mapped_column(String(60), nullable=True)
    postcode: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Provenance: where this variant came from (required) + optional source links. Stored
    # as a string (the CustomerContactVariantSource vocabulary). Prefer explicit
    # provenance over guessing — links point at the structured source, never parsed prose.
    source_type: Mapped[CustomerContactVariantSource] = mapped_column(
        String(20), nullable=False, index=True
    )
    # The soft-deleted merged loser (source_type='merged_customer') — a Customer self-FK.
    source_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True
    )
    source_import_row_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_rows.id"), nullable=True
    )
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id"), nullable=True
    )

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<CustomerContactVariant {self.id} customer={self.customer_id} "
            f"source={self.source_type}>"
        )
