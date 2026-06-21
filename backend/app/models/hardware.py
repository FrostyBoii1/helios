"""Hardware catalogue + aliases (Hardware Parser lane, Stage 1 — storage foundation).

A DB-backed canonical hardware catalogue (inverter / battery / panel / metering) and its
parser aliases, seeded from the curated spec in ``docs/parser_specs/hardware/``. This is the
long-term source of truth for hardware models and matchable aliases; admins will edit it via
Settings > Hardware in a later stage, and a future runtime parser will read THIS catalogue.

KEYSTONE: Job hardware will be stored as an editable per-job SNAPSHOT (``Job.details.hardware``
JSONB, a later stage) that NEVER depends on this catalogue. Catalogue renames / alias edits /
soft-deletes / restores must NOT change already-parsed Job hardware — a Job may store a
``canonical_hardware_id_at_parse_time`` (this table's ``spec_id``/id) for DEBUGGING only, never
as a live reference. Stage 1 creates ONLY the tables + seed; nothing reads them yet.

FK-only (no ORM relationship to Job/Customer) — the catalogue is reference data, independent
of live CRM business data; it is NOT cleared by the dev reset tools.
"""
from __future__ import annotations

from datetime import datetime  # noqa: F401  (used by mixins' type hints)

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, UniqueConstraint, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base
from app.models.mixins import IntPkMixin, SoftDeleteMixin, TimestampMixin


class HardwareCatalogue(IntPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "hardware_catalogue"

    # Stable id from the curated spec (e.g. "alpha_ess_smile_g3_b5_inv", "meter_generic",
    # "panel_longi_lr5_54hth_440m"). Unique — the seed's idempotency key and the value a future
    # Job snapshot may record as canonical_hardware_id_at_parse_time (debug only, never live).
    spec_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)

    # Category (HardwareCategory): inverter / battery / panel / metering.
    category: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Canonical model text. May be NULL for an ambiguous panel (model_options instead).
    canonical_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Job-facing display name (panels carry one, e.g. "440W LONGi Solar").
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)

    # Type-specific spec fields (all optional; populated per category).
    phases: Mapped[str | None] = mapped_column(String(30), nullable=True)       # inverter
    nominal_kw: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)   # inverter
    capacity_kwh: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)  # battery
    wattage_w: Mapped[int | None] = mapped_column(Integer, nullable=True)        # panel

    # Ambiguous-panel possible models (single canonical model must be NULL when set).
    model_options: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Extra spec metadata kept as-is (notes, requires_model_precision_review, confidence rules,
    # negative_patterns, …). NOT named "metadata" (reserved on the declarative Base).
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Provenance: which curated rule file/version this entry was seeded from.
    spec_source: Mapped[str] = mapped_column(String(80), nullable=False)

    # Catalogue active flag (mirrors the spec's `active`); distinct from soft-delete (deleted_at).
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    # Admin who created/edited a non-seed entry later (seed leaves NULL).
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<HardwareCatalogue {self.spec_id} {self.category}>"


class HardwareAlias(IntPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "hardware_aliases"
    __table_args__ = (
        # Idempotent seed + no duplicate alias rows per hardware entry.
        UniqueConstraint("hardware_id", "alias", "alias_type"),
    )

    hardware_id: Mapped[int] = mapped_column(
        ForeignKey("hardware_catalogue.id"), nullable=False, index=True
    )
    # Raw alias text exactly as in the spec (the matcher normalises at match time per the
    # versioned normalization rules — we do NOT bake normalization into stored data).
    alias: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # HardwareAliasType: exact / loose / case_sensitive. source_examples are evidence only and
    # are NEVER stored as aliases (there is no source_example alias type).
    alias_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Optional per-alias overrides carried from the spec.
    confidence_override: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_log_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<HardwareAlias {self.alias!r} ({self.alias_type}) hw={self.hardware_id}>"
