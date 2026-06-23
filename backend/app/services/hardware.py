"""Hardware catalogue + alias admin domain logic (Stage 2A — admin API).

CRUD + search/filter + soft-delete/restore over the Stage-1 catalogue, admin-only. NEVER
hard-deletes (soft-delete via `deleted_at`). The catalogue stays reference data: nothing here
touches Jobs/imports/parser, and edits/deletes/restores cannot affect Job hardware (Jobs hold
no reference to this catalogue). `spec_id` is immutable (the stable seeded id is preserved);
admin-created entries get `spec_source='admin'`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.hardware import HardwareAlias, HardwareCatalogue


class HardwareError(Exception):
    """An admin-API guard failure carrying the HTTP status to surface. Raised BEFORE any
    mutation, so the request transaction stays clean (the endpoint need not roll back)."""

    def __init__(self, reason: str, http_status: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.http_status = http_status


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


# --------------------------------------------------------------------------- #
# Catalogue
# --------------------------------------------------------------------------- #
def list_hardware(
    db: Session,
    *,
    q: str | None = None,
    category: str | None = None,
    brand: str | None = None,
    phase: str | None = None,
    nominal_kw: float | None = None,
    capacity_kwh: float | None = None,
    wattage_w: int | None = None,
    deleted: str = "exclude",
    active_only: bool = False,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[HardwareCatalogue], int]:
    """(page of catalogue, total). `deleted`: exclude (default, not soft-deleted) / only (the
    DELETED section) / include (both). `active_only` additionally requires the spec `is_active`
    flag (the admin catalogue list shows inactive entries; the staff search endpoint sets it True).
    `q` searches spec_id/canonical_model/display_name/brand."""
    filters = []
    if deleted == "exclude":
        filters.append(HardwareCatalogue.deleted_at.is_(None))
    elif deleted == "only":
        filters.append(HardwareCatalogue.deleted_at.is_not(None))
    # "include" -> no deleted filter
    if active_only:
        filters.append(HardwareCatalogue.is_active.is_(True))

    if category:
        filters.append(HardwareCatalogue.category == _enum_value(category))
    if brand:
        filters.append(HardwareCatalogue.brand == brand)
    if phase:
        filters.append(HardwareCatalogue.phases == phase)
    if nominal_kw is not None:
        filters.append(HardwareCatalogue.nominal_kw == nominal_kw)
    if capacity_kwh is not None:
        filters.append(HardwareCatalogue.capacity_kwh == capacity_kwh)
    if wattage_w is not None:
        filters.append(HardwareCatalogue.wattage_w == wattage_w)
    if q:
        like = f"%{q.strip()}%"
        filters.append(
            or_(
                HardwareCatalogue.spec_id.ilike(like),
                HardwareCatalogue.canonical_model.ilike(like),
                HardwareCatalogue.display_name.ilike(like),
                HardwareCatalogue.brand.ilike(like),
            )
        )

    total = db.scalar(select(func.count()).select_from(HardwareCatalogue).where(*filters)) or 0
    stmt = (
        select(HardwareCatalogue)
        .where(*filters)
        .order_by(
            HardwareCatalogue.category,
            HardwareCatalogue.brand,
            HardwareCatalogue.display_name,
            HardwareCatalogue.canonical_model,
            HardwareCatalogue.id,
        )
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all()), total


def alias_counts_for(db: Session, hardware_ids: list[int]) -> dict[int, int]:
    """Active (non-deleted) alias count per hardware id — ONE query (no N+1)."""
    if not hardware_ids:
        return {}
    rows = db.execute(
        select(HardwareAlias.hardware_id, func.count())
        .where(HardwareAlias.hardware_id.in_(hardware_ids), HardwareAlias.deleted_at.is_(None))
        .group_by(HardwareAlias.hardware_id)
    ).all()
    return {hid: count for hid, count in rows}


def get_hardware(db: Session, hardware_id: int, *, include_deleted: bool = True) -> HardwareCatalogue | None:
    stmt = select(HardwareCatalogue).where(HardwareCatalogue.id == hardware_id)
    if not include_deleted:
        stmt = stmt.where(HardwareCatalogue.deleted_at.is_(None))
    return db.scalar(stmt)


def create_hardware(db: Session, *, data: dict[str, Any], actor_id: int) -> HardwareCatalogue:
    """Create an admin catalogue entry. `spec_id` is required + unique; `spec_source='admin'`.
    Raises HardwareError before any mutation."""
    spec_id = (data.get("spec_id") or "").strip()
    if not spec_id:
        raise HardwareError("spec_id_required", 400)
    if db.scalar(select(HardwareCatalogue).where(HardwareCatalogue.spec_id == spec_id)) is not None:
        raise HardwareError("spec_id_exists", 409)
    fields = {k: _enum_value(v) if k == "category" else v for k, v in data.items() if k != "spec_id"}
    hw = HardwareCatalogue(spec_id=spec_id, spec_source="admin", created_by_id=actor_id, **fields)
    db.add(hw)
    db.flush()
    return hw


def update_hardware(db: Session, *, hardware: HardwareCatalogue, data: dict[str, Any]) -> list[str]:
    """Apply a partial update (spec_id/spec_source are not editable). Returns changed fields."""
    changed: list[str] = []
    for field, value in data.items():
        if field == "category":
            value = _enum_value(value)
        if getattr(hardware, field) != value:
            setattr(hardware, field, value)
            changed.append(field)
    return changed


def soft_delete_hardware(db: Session, hardware: HardwareCatalogue) -> None:
    """Soft-delete (never hard-delete). Aliases are left associated (restore keeps them intact)."""
    if hardware.deleted_at is None:
        hardware.deleted_at = datetime.now(timezone.utc)


def restore_hardware(db: Session, hardware: HardwareCatalogue) -> None:
    if hardware.deleted_at is not None:
        hardware.deleted_at = None


# --------------------------------------------------------------------------- #
# Aliases (admin-only)
# --------------------------------------------------------------------------- #
def list_aliases(db: Session, *, hardware_id: int, deleted: str = "exclude") -> list[HardwareAlias]:
    filters = [HardwareAlias.hardware_id == hardware_id]
    if deleted == "exclude":
        filters.append(HardwareAlias.deleted_at.is_(None))
    elif deleted == "only":
        filters.append(HardwareAlias.deleted_at.is_not(None))
    stmt = (
        select(HardwareAlias)
        .where(*filters)
        .order_by(HardwareAlias.alias_type, HardwareAlias.alias, HardwareAlias.id)
    )
    return list(db.scalars(stmt).all())


def get_alias(db: Session, alias_id: int, *, hardware_id: int | None = None) -> HardwareAlias | None:
    stmt = select(HardwareAlias).where(HardwareAlias.id == alias_id)
    if hardware_id is not None:
        stmt = stmt.where(HardwareAlias.hardware_id == hardware_id)
    return db.scalar(stmt)


def create_alias(db: Session, *, hardware: HardwareCatalogue, data: dict[str, Any]) -> HardwareAlias:
    """Create an alias for `hardware`. The unique (hardware_id, alias, alias_type) constraint
    means a same-key row can only pre-exist as a SOFT-DELETED one — in that case restore it
    (so the admin can't create a true duplicate); an active duplicate -> 409."""
    alias = (data.get("alias") or "").strip()
    if not alias:
        raise HardwareError("alias_required", 400)
    alias_type = _enum_value(data.get("alias_type"))
    existing = db.scalar(
        select(HardwareAlias).where(
            HardwareAlias.hardware_id == hardware.id,
            HardwareAlias.alias == alias,
            HardwareAlias.alias_type == alias_type,
        )
    )
    if existing is not None:
        if existing.deleted_at is None:
            raise HardwareError("alias_exists", 409)
        existing.deleted_at = None  # restore the soft-deleted same-key alias
        existing.confidence_override = data.get("confidence_override")
        existing.decision_log_id = data.get("decision_log_id")
        return existing
    obj = HardwareAlias(
        hardware_id=hardware.id, alias=alias, alias_type=alias_type,
        confidence_override=data.get("confidence_override"),
        decision_log_id=data.get("decision_log_id"),
    )
    db.add(obj)
    db.flush()
    return obj


def update_alias(db: Session, *, alias: HardwareAlias, data: dict[str, Any]) -> list[str]:
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if key == "alias" and isinstance(value, str):
            value = value.strip()
        if key == "alias_type" and value is not None:
            value = _enum_value(value)
        cleaned[key] = value
    # If the alias key changes, guard the unique (hardware_id, alias, alias_type). The DB
    # constraint is FULL — it spans soft-deleted rows (there is no partial `deleted_at IS NULL`
    # index), so a soft-deleted alias still owns its key. The clash query therefore deliberately
    # does NOT filter on deleted_at: renaming an active alias onto a key held by a soft-deleted
    # one must be a clean 409 (the admin restores that alias instead), never a flush-time
    # IntegrityError. This is the principled mirror of create_alias, which *restores* on a
    # soft-deleted same-key row because no second active row is in play; an update has one, so it
    # must reject. Do NOT add `deleted_at.is_(None)` here — it would turn the 409 into a 500.
    new_alias = cleaned.get("alias", alias.alias)
    new_type = cleaned.get("alias_type", alias.alias_type)
    if (new_alias, new_type) != (alias.alias, alias.alias_type):
        clash = db.scalar(
            select(HardwareAlias).where(
                HardwareAlias.hardware_id == alias.hardware_id,
                HardwareAlias.alias == new_alias,
                HardwareAlias.alias_type == new_type,
                HardwareAlias.id != alias.id,
            )
        )
        if clash is not None:
            raise HardwareError("alias_exists", 409)
    changed: list[str] = []
    for key, value in cleaned.items():
        if getattr(alias, key) != value:
            setattr(alias, key, value)
            changed.append(key)
    return changed


def soft_delete_alias(db: Session, alias: HardwareAlias) -> None:
    if alias.deleted_at is None:
        alias.deleted_at = datetime.now(timezone.utc)


def restore_alias(db: Session, alias: HardwareAlias) -> None:
    # The unique (hardware_id, alias, alias_type) constraint guarantees no active same-key row
    # exists, so a soft-deleted alias can always be safely restored.
    if alias.deleted_at is not None:
        alias.deleted_at = None
