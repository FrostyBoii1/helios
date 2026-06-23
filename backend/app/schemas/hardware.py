"""Hardware catalogue + alias admin schemas (Hardware Parser lane, Stage 2A — admin API).

Admin-only management of the canonical hardware catalogue and its parser aliases. These shapes
mirror the Stage-1 tables; nothing here is consumed by Jobs/imports/parser yet (catalogue is
still reference data). `spec_id` is immutable (preserves the stable seeded id) — it is set on
create but NOT in the update shape.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import HardwareAliasType, HardwareCategory


# --------------------------------------------------------------------------- #
# Catalogue
# --------------------------------------------------------------------------- #
class HardwareCatalogueBase(BaseModel):
    category: HardwareCategory
    canonical_model: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    brand: str | None = Field(default=None, max_length=160)
    phases: str | None = Field(default=None, max_length=30)
    nominal_kw: float | None = None
    capacity_kwh: float | None = None
    wattage_w: int | None = None
    model_options: list[str] | None = None
    attributes: dict | None = None
    is_active: bool = True


class HardwareCatalogueCreate(HardwareCatalogueBase):
    """Admin create. `spec_id` is the stable catalogue id (unique); `spec_source` is set
    server-side to mark the entry admin-authored."""

    spec_id: str = Field(..., min_length=1, max_length=120)


class HardwareCatalogueUpdate(BaseModel):
    """Partial update — every field optional. `spec_id` and `spec_source` are NOT editable
    (the stable id is preserved)."""

    category: HardwareCategory | None = None
    canonical_model: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    brand: str | None = Field(default=None, max_length=160)
    phases: str | None = Field(default=None, max_length=30)
    nominal_kw: float | None = None
    capacity_kwh: float | None = None
    wattage_w: int | None = None
    model_options: list[str] | None = None
    attributes: dict | None = None
    is_active: bool | None = None


class HardwareCatalogueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    spec_id: str
    category: str
    canonical_model: str | None
    display_name: str | None
    brand: str | None
    phases: str | None
    nominal_kw: float | None
    capacity_kwh: float | None
    wattage_w: int | None
    model_options: list | None
    attributes: dict | None
    spec_source: str
    is_active: bool
    # Active (non-deleted) alias count, computed by the list/detail endpoints.
    alias_count: int = 0
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class HardwareCatalogueList(BaseModel):
    items: list[HardwareCatalogueRead]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------------------- #
# Lean staff search (authenticated, NOT admin) — hardware autocomplete
# --------------------------------------------------------------------------- #
class HardwareSearchResult(BaseModel):
    """Lean canonical-hardware row for staff autocomplete. Carries ONLY display/disambiguation
    fields — deliberately NO aliases / alias_count, NO attributes / spec_source / created_by /
    is_active / timestamps / deleted_at, and only active, non-deleted rows are ever returned. `id`
    is the catalogue DB id (a future selection may record it as ``canonical_hardware_id_at_parse_time``
    provenance — never a live reference); `spec_id` is the stable external id."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    spec_id: str
    category: str
    display_name: str | None
    canonical_model: str | None
    brand: str | None
    phases: str | None
    nominal_kw: float | None
    capacity_kwh: float | None
    wattage_w: int | None
    model_options: list | None


class HardwareSearchList(BaseModel):
    items: list[HardwareSearchResult]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------------------- #
# Aliases (admin-only — never exposed to normal users)
# --------------------------------------------------------------------------- #
class HardwareAliasBase(BaseModel):
    alias: str = Field(..., min_length=1, max_length=255)
    alias_type: HardwareAliasType
    confidence_override: str | None = Field(default=None, max_length=40)
    decision_log_id: str | None = Field(default=None, max_length=120)


class HardwareAliasCreate(HardwareAliasBase):
    """Admin create. `source_examples` are evidence only and are never aliases — the alias
    type vocabulary is exactly exact / loose / case_sensitive."""


class HardwareAliasUpdate(BaseModel):
    alias: str | None = Field(default=None, min_length=1, max_length=255)
    alias_type: HardwareAliasType | None = None
    confidence_override: str | None = Field(default=None, max_length=40)
    decision_log_id: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None


class HardwareAliasRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    hardware_id: int
    alias: str
    alias_type: str
    confidence_override: str | None
    decision_log_id: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class HardwareAliasList(BaseModel):
    items: list[HardwareAliasRead]
    total: int
