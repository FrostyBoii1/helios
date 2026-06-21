"""Seed the DB hardware catalogue + aliases from the curated spec YAML (Stage 1).

Idempotent: re-running never duplicates rows (catalogue is keyed by the spec's stable
``spec_id``; aliases by (hardware_id, alias, alias_type)) and never clobbers later admin edits
(insert-if-missing, not upsert-overwrite). Reads the tracked spec from
``docs/parser_specs/hardware/`` (the read-only mount at ``/app/parser_specs/hardware`` in the
backend container, or a repo-relative path in a plain checkout).

source_examples are DELIBERATELY NOT inserted as aliases (the safer of the two owner options):
they are evidence/fixture strings, not matchable aliases, and leaving them out of the alias
table means a future matcher can never mistake one for an alias. They remain in the spec YAML.
Parser policy (ignore rules / specific corrections / guard phrases / brand-only & wattage-only
panel routing / normalization) stays in the versioned config — it is NOT seeded into the DB.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import HardwareAliasType, HardwareCategory
from app.models.hardware import HardwareAlias, HardwareCatalogue

# docs/parser_specs/hardware — container read-only mount, else repo-relative.
_CANDIDATE_DIRS = [
    Path("/app/parser_specs/hardware"),
    Path(__file__).resolve().parents[3] / "docs" / "parser_specs" / "hardware",
]

_HARDWARE_RULES = "hardware_parser_runtime_rules_v9_1.yaml"
_PANEL_RULES = "panel_parser_rules_v1_1.yaml"


def spec_dir() -> Path:
    for p in _CANDIDATE_DIRS:
        if p.is_dir():
            return p
    raise FileNotFoundError(
        f"Hardware parser spec dir not found (tried {[str(p) for p in _CANDIDATE_DIRS]})."
    )


def _load(name: str) -> dict[str, Any]:
    return yaml.safe_load((spec_dir() / name).read_text(encoding="utf-8"))


def _attrs(entry: dict, keys: tuple[str, ...]) -> dict | None:
    out = {k: entry[k] for k in keys if entry.get(k) not in (None, [], {}, "")}
    return out or None


def _get_or_create(db: Session, *, spec_id: str, fields: dict) -> tuple[HardwareCatalogue, bool]:
    obj = db.scalar(select(HardwareCatalogue).where(HardwareCatalogue.spec_id == spec_id))
    if obj is not None:
        return obj, False
    obj = HardwareCatalogue(spec_id=spec_id, **fields)
    db.add(obj)
    db.flush()  # assign id for alias FK
    return obj, True


def _ensure_alias(
    db: Session, *, hardware_id: int, alias: str, alias_type: str,
    confidence_override: str | None = None, decision_log_id: str | None = None,
) -> bool:
    exists = db.scalar(
        select(HardwareAlias).where(
            HardwareAlias.hardware_id == hardware_id,
            HardwareAlias.alias == alias,
            HardwareAlias.alias_type == alias_type,
        )
    )
    if exists is not None:
        return False
    db.add(
        HardwareAlias(
            hardware_id=hardware_id, alias=alias, alias_type=alias_type,
            confidence_override=confidence_override, decision_log_id=decision_log_id,
        )
    )
    return True


def seed_hardware_catalogue(db: Session) -> dict[str, int]:
    """Insert any missing catalogue entries + matchable aliases from the spec YAML. Returns
    ``{hardware_created, alias_created}`` (the NEW rows this call inserted; 0/0 on a re-run).
    The caller's transaction is committed at the end."""
    counts = {"hardware_created": 0, "alias_created": 0}
    runtime = _load(_HARDWARE_RULES)

    # Inverters + batteries.
    for e in runtime["hardware_catalog"]:
        obj, created = _get_or_create(
            db, spec_id=e["id"],
            fields=dict(
                category=e["category"],
                canonical_model=e.get("canonical_model"),
                brand=e.get("manufacturer"),
                phases=e.get("phases"),
                nominal_kw=e.get("nominal_kw"),
                capacity_kwh=e.get("capacity_kwh"),
                spec_source="hardware_parser_runtime_rules_v9_1",
                attributes=_attrs(e, ("notes", "negative_patterns", "confidence")),
            ),
        )
        counts["hardware_created"] += int(created)
        for a in e.get("exact_aliases") or []:
            counts["alias_created"] += int(
                _ensure_alias(db, hardware_id=obj.id, alias=a, alias_type=HardwareAliasType.EXACT.value)
            )
        for a in e.get("loose_aliases") or []:
            counts["alias_created"] += int(
                _ensure_alias(db, hardware_id=obj.id, alias=a, alias_type=HardwareAliasType.LOOSE.value)
            )
        # source_examples: intentionally NOT inserted (evidence only).

    # Metering (first-class catalogue hardware).
    for e in runtime["metering_catalog"]:
        obj, created = _get_or_create(
            db, spec_id=e["id"],
            fields=dict(
                category=HardwareCategory.METERING.value,
                canonical_model=e.get("canonical_model"),
                spec_source="hardware_parser_runtime_rules_v9_1",
                attributes=_attrs(e, ("notes",)),
            ),
        )
        counts["hardware_created"] += int(created)
        for a in e.get("exact_aliases") or []:
            counts["alias_created"] += int(
                _ensure_alias(db, hardware_id=obj.id, alias=a, alias_type=HardwareAliasType.EXACT.value)
            )

    # Panels (separate spec; model may be NULL with model_options; case-sensitive aliases).
    panel = _load(_PANEL_RULES)
    for e in panel["canonical_panels"]:
        obj, created = _get_or_create(
            db, spec_id=e["canonical_id"],
            fields=dict(
                category=HardwareCategory.PANEL.value,
                canonical_model=e.get("model"),
                display_name=e.get("display_name"),
                brand=e.get("brand"),
                wattage_w=e.get("wattage_w"),
                model_options=e.get("model_options"),
                spec_source="panel_rules_v1_1",
                attributes=_attrs(e, ("notes", "requires_model_precision_review")),
            ),
        )
        counts["hardware_created"] += int(created)
        for a in e.get("exact_aliases") or []:
            value = a["value"] if isinstance(a, dict) else a
            case_sensitive = bool(isinstance(a, dict) and a.get("case_sensitive"))
            alias_type = (
                HardwareAliasType.CASE_SENSITIVE.value if case_sensitive
                else HardwareAliasType.EXACT.value
            )
            counts["alias_created"] += int(
                _ensure_alias(
                    db, hardware_id=obj.id, alias=value, alias_type=alias_type,
                    confidence_override=(a.get("confidence_override") if isinstance(a, dict) else None),
                    decision_log_id=(a.get("decision_log_id") if isinstance(a, dict) else None),
                )
            )
        # brand_only_aliases / wattage_only / non_panel_ambiguous: parser policy, not catalogue
        # aliases — intentionally NOT seeded (stays in the versioned config).

    db.commit()
    get_logger("seed").info("hardware_catalogue_seeded", **counts)
    return counts
