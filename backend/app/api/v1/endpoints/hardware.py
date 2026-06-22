"""Hardware catalogue + alias admin endpoints (Hardware Parser lane, Stage 2A).

ALL endpoints are admin-only (``Depends(require_admin)``) — both reads and writes — so the
catalogue management API (and especially aliases) is never reachable by a normal user. This is
catalogue management only: nothing here touches Jobs/imports/parser, and edits/deletes/restores
cannot affect Job hardware. Soft-delete + restore only — never hard-deletes.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.enums import HardwareCategory
from app.models.user import User
from app.schemas.hardware import (
    HardwareAliasCreate,
    HardwareAliasList,
    HardwareAliasRead,
    HardwareAliasUpdate,
    HardwareCatalogueCreate,
    HardwareCatalogueList,
    HardwareCatalogueRead,
    HardwareCatalogueUpdate,
)
from app.services import hardware as hardware_service

router = APIRouter()

DeletedMode = Literal["exclude", "only", "include"]


def _read(db: Session, hardware) -> HardwareCatalogueRead:
    """Serialise a catalogue entry + its active alias count."""
    hardware.alias_count = hardware_service.alias_counts_for(db, [hardware.id]).get(hardware.id, 0)
    return HardwareCatalogueRead.model_validate(hardware)


# --------------------------------------------------------------------------- #
# Catalogue
# --------------------------------------------------------------------------- #
@router.get("", response_model=HardwareCatalogueList)
def list_hardware(
    q: str | None = Query(default=None, description="Search spec_id/model/display_name/brand"),
    category: HardwareCategory | None = Query(default=None),
    brand: str | None = Query(default=None),
    phase: str | None = Query(default=None, description="inverter phase, e.g. three_phase"),
    nominal_kw: float | None = Query(default=None),
    capacity_kwh: float | None = Query(default=None),
    wattage_w: int | None = Query(default=None),
    deleted: DeletedMode = Query(default="exclude", description="exclude / only (DELETED) / include"),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> HardwareCatalogueList:
    items, total = hardware_service.list_hardware(
        db, q=q, category=category.value if category else None, brand=brand, phase=phase,
        nominal_kw=nominal_kw, capacity_kwh=capacity_kwh, wattage_w=wattage_w,
        deleted=deleted, limit=limit, offset=offset,
    )
    counts = hardware_service.alias_counts_for(db, [h.id for h in items])
    for h in items:
        h.alias_count = counts.get(h.id, 0)
    return HardwareCatalogueList(
        items=[HardwareCatalogueRead.model_validate(h) for h in items],
        total=total, limit=limit, offset=offset,
    )


@router.post("", response_model=HardwareCatalogueRead, status_code=status.HTTP_201_CREATED)
def create_hardware(
    payload: HardwareCatalogueCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
) -> HardwareCatalogueRead:
    try:
        hw = hardware_service.create_hardware(db, data=payload.model_dump(), actor_id=actor.id)
    except hardware_service.HardwareError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.reason)
    db.commit()
    db.refresh(hw)
    return _read(db, hw)


@router.get("/{hardware_id}", response_model=HardwareCatalogueRead)
def get_hardware(
    hardware_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> HardwareCatalogueRead:
    hw = hardware_service.get_hardware(db, hardware_id)
    if hw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hardware not found")
    return _read(db, hw)


@router.patch("/{hardware_id}", response_model=HardwareCatalogueRead)
def update_hardware(
    hardware_id: int,
    payload: HardwareCatalogueUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> HardwareCatalogueRead:
    hw = hardware_service.get_hardware(db, hardware_id)
    if hw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hardware not found")
    hardware_service.update_hardware(db, hardware=hw, data=payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(hw)
    return _read(db, hw)


@router.delete("/{hardware_id}", response_model=HardwareCatalogueRead)
def delete_hardware(
    hardware_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> HardwareCatalogueRead:
    """Soft-delete (moves the entry to the DELETED section; never hard-deletes; aliases kept)."""
    hw = hardware_service.get_hardware(db, hardware_id, include_deleted=False)
    if hw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hardware not found")
    hardware_service.soft_delete_hardware(db, hw)
    db.commit()
    db.refresh(hw)
    return _read(db, hw)


@router.post("/{hardware_id}/restore", response_model=HardwareCatalogueRead)
def restore_hardware(
    hardware_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> HardwareCatalogueRead:
    hw = hardware_service.get_hardware(db, hardware_id)
    if hw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hardware not found")
    hardware_service.restore_hardware(db, hw)
    db.commit()
    db.refresh(hw)
    return _read(db, hw)


# --------------------------------------------------------------------------- #
# Aliases (admin-only — normal users never reach these)
# --------------------------------------------------------------------------- #
def _require_hardware(db: Session, hardware_id: int):
    hw = hardware_service.get_hardware(db, hardware_id)
    if hw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hardware not found")
    return hw


@router.get("/{hardware_id}/aliases", response_model=HardwareAliasList)
def list_aliases(
    hardware_id: int,
    deleted: DeletedMode = Query(default="exclude"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> HardwareAliasList:
    _require_hardware(db, hardware_id)
    aliases = hardware_service.list_aliases(db, hardware_id=hardware_id, deleted=deleted)
    return HardwareAliasList(
        items=[HardwareAliasRead.model_validate(a) for a in aliases], total=len(aliases)
    )


@router.post("/{hardware_id}/aliases", response_model=HardwareAliasRead, status_code=status.HTTP_201_CREATED)
def create_alias(
    hardware_id: int,
    payload: HardwareAliasCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> HardwareAliasRead:
    hw = _require_hardware(db, hardware_id)
    try:
        alias = hardware_service.create_alias(db, hardware=hw, data=payload.model_dump())
    except hardware_service.HardwareError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.reason)
    db.commit()
    db.refresh(alias)
    return HardwareAliasRead.model_validate(alias)


@router.patch("/{hardware_id}/aliases/{alias_id}", response_model=HardwareAliasRead)
def update_alias(
    hardware_id: int,
    alias_id: int,
    payload: HardwareAliasUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> HardwareAliasRead:
    _require_hardware(db, hardware_id)
    alias = hardware_service.get_alias(db, alias_id, hardware_id=hardware_id)
    if alias is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alias not found")
    try:
        hardware_service.update_alias(db, alias=alias, data=payload.model_dump(exclude_unset=True))
    except hardware_service.HardwareError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.reason)
    db.commit()
    db.refresh(alias)
    return HardwareAliasRead.model_validate(alias)


@router.delete("/{hardware_id}/aliases/{alias_id}", response_model=HardwareAliasRead)
def delete_alias(
    hardware_id: int,
    alias_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> HardwareAliasRead:
    """Soft-delete an alias (never hard-deletes)."""
    _require_hardware(db, hardware_id)
    alias = hardware_service.get_alias(db, alias_id, hardware_id=hardware_id)
    if alias is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alias not found")
    hardware_service.soft_delete_alias(db, alias)
    db.commit()
    db.refresh(alias)
    return HardwareAliasRead.model_validate(alias)


@router.post("/{hardware_id}/aliases/{alias_id}/restore", response_model=HardwareAliasRead)
def restore_alias(
    hardware_id: int,
    alias_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> HardwareAliasRead:
    _require_hardware(db, hardware_id)
    alias = hardware_service.get_alias(db, alias_id, hardware_id=hardware_id)
    if alias is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alias not found")
    hardware_service.restore_alias(db, alias)
    db.commit()
    db.refresh(alias)
    return HardwareAliasRead.model_validate(alias)
