"""Hardware Parser lane, Stage 1 — DB catalogue + alias storage and seed.

Verifies the migration creates the tables and the seed loads the curated spec idempotently
(catalogue keyed by stable spec_id, aliases by (hardware_id, alias, alias_type)), with the
spec's hard rules preserved: source_examples are NOT matchable aliases, ambiguous panels keep
model NULL + model_options, the case-sensitive Jinko/JINKO pair stays distinct, and metering is
first-class catalogue hardware. Storage + seed only — nothing reads the catalogue yet.

Isolation: the dev DB is already seeded, so each test CLEARS the two tables inside its
rollback-isolated savepoint, re-seeds deterministically, asserts, and the outer rollback
restores the dev seed — the live catalogue is never mutated by the test run.
"""
from __future__ import annotations

import yaml
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.hardware.seed import seed_hardware_catalogue, spec_dir
from app.models.hardware import HardwareAlias, HardwareCatalogue


def _expected_from_yaml() -> tuple[int, int]:
    """(catalogue_count, matchable_alias_count) the seed SHOULD load — computed straight from
    the spec YAML, so the assertion proves completeness rather than pinning a magic number.
    Excludes source_examples (never aliases) and panel brand-only/wattage-only policy."""
    d = spec_dir()
    rt = yaml.safe_load((d / "hardware_parser_runtime_rules_v9_1.yaml").read_text(encoding="utf-8"))
    pr = yaml.safe_load((d / "panel_parser_rules_v1_1.yaml").read_text(encoding="utf-8"))
    cat = len(rt["hardware_catalog"]) + len(rt["metering_catalog"]) + len(pr["canonical_panels"])
    aliases = 0
    for e in rt["hardware_catalog"]:
        aliases += len(e.get("exact_aliases") or []) + len(e.get("loose_aliases") or [])
    for e in rt["metering_catalog"]:
        aliases += len(e.get("exact_aliases") or [])
    for e in pr["canonical_panels"]:
        aliases += len(e.get("exact_aliases") or [])
    return cat, aliases


def _clear(db: Session) -> None:
    db.execute(delete(HardwareAlias))   # children first (FK)
    db.execute(delete(HardwareCatalogue))
    db.flush()


def _seed_fresh(db: Session) -> dict[str, int]:
    _clear(db)
    return seed_hardware_catalogue(db)


def test_migration_created_tables():
    names = set(inspect(engine).get_table_names())
    assert "hardware_catalogue" in names
    assert "hardware_aliases" in names


def test_seed_loads_expected_counts(db_session: Session):
    exp_cat, exp_alias = _expected_from_yaml()
    counts = _seed_fresh(db_session)
    assert counts == {"hardware_created": exp_cat, "alias_created": exp_alias}

    assert db_session.scalar(select(func.count()).select_from(HardwareCatalogue)) == exp_cat
    assert db_session.scalar(select(func.count()).select_from(HardwareAlias)) == exp_alias
    by_cat = dict(
        db_session.execute(
            select(HardwareCatalogue.category, func.count()).group_by(HardwareCatalogue.category)
        ).all()
    )
    # All four categories present; metering is first-class.
    assert set(by_cat) == {"inverter", "battery", "panel", "metering"}
    assert by_cat["panel"] == 20 and by_cat["metering"] == 7

    # Representative inverter row carries its spec fields.
    inv = db_session.scalar(
        select(HardwareCatalogue).where(HardwareCatalogue.spec_id == "alpha_ess_smile_g3_b5_inv")
    )
    assert inv.category == "inverter"
    assert inv.canonical_model == "Alpha ESS SMILE-G3-B5-INV"
    assert inv.brand == "Alpha ESS" and inv.phases == "three_phase"
    assert inv.spec_source == "hardware_parser_runtime_rules_v9_1"


def test_seed_is_idempotent(db_session: Session):
    first = _seed_fresh(db_session)
    total_cat = db_session.scalar(select(func.count()).select_from(HardwareCatalogue))
    total_alias = db_session.scalar(select(func.count()).select_from(HardwareAlias))

    second = seed_hardware_catalogue(db_session)  # re-run, no clear
    assert second == {"hardware_created": 0, "alias_created": 0}  # nothing duplicated
    assert db_session.scalar(select(func.count()).select_from(HardwareCatalogue)) == total_cat
    assert db_session.scalar(select(func.count()).select_from(HardwareAlias)) == total_alias
    assert first["hardware_created"] == total_cat  # the first run created them all


def test_source_examples_are_not_matchable_aliases(db_session: Session):
    _seed_fresh(db_session)
    # No alias row is of the reserved evidence type, and every alias is a real matchable type.
    assert db_session.scalar(
        select(func.count()).select_from(HardwareAlias).where(HardwareAlias.alias_type == "source_example")
    ) == 0
    types = {t for (t,) in db_session.execute(select(HardwareAlias.alias_type).distinct()).all()}
    assert types <= {"exact", "loose", "case_sensitive"}

    # Cross-check: no seeded alias value equals any spec source_example (they were never loaded).
    rt = yaml.safe_load((spec_dir() / "hardware_parser_runtime_rules_v9_1.yaml").read_text(encoding="utf-8"))
    source_examples = {
        " ".join(str(ex).split()).casefold()
        for e in rt["hardware_catalog"] + rt["metering_catalog"]
        for ex in (e.get("source_examples") or [])
    }
    seeded_aliases = {
        " ".join(a.split()).casefold()
        for (a,) in db_session.execute(select(HardwareAlias.alias)).all()
    }
    assert source_examples.isdisjoint(seeded_aliases)


def test_ambiguous_panel_keeps_model_null_with_options(db_session: Session):
    _seed_fresh(db_session)
    amb = db_session.scalar(
        select(HardwareCatalogue).where(HardwareCatalogue.spec_id == "panel_suntech_415_ambiguous")
    )
    assert amb.category == "panel"
    assert amb.canonical_model is None                      # never guessed
    assert amb.model_options == ["STP415S-78H/Vfh", "Ultra V mini STP415S-C54/Umhm"]
    assert amb.display_name == "415W Suntech Power" and amb.wattage_w == 415


def test_case_sensitive_jinko_aliases_distinct(db_session: Session):
    _seed_fresh(db_session)
    rows = db_session.scalars(
        select(HardwareAlias).where(HardwareAlias.alias.in_(("Jinko 440", "JINKO 440")))
    ).all()
    by_alias = {a.alias: a for a in rows}
    assert set(by_alias) == {"Jinko 440", "JINKO 440"}
    assert all(a.alias_type == "case_sensitive" for a in rows)
    # They resolve to DIFFERENT panels (case-sensitive distinction preserved).
    assert by_alias["Jinko 440"].hardware_id != by_alias["JINKO 440"].hardware_id


def test_metering_is_first_class_hardware(db_session: Session):
    _seed_fresh(db_session)
    meters = db_session.scalars(
        select(HardwareCatalogue).where(HardwareCatalogue.category == "metering")
    ).all()
    assert len(meters) == 7
    generic = next(m for m in meters if m.spec_id == "meter_generic")
    assert generic.canonical_model == "Meter"
    # It has matchable aliases like any other hardware.
    assert db_session.scalar(
        select(func.count()).select_from(HardwareAlias).where(HardwareAlias.hardware_id == generic.id)
    ) > 0


def test_soft_delete_fields_exist_and_aliases_stay_associated(db_session: Session):
    _seed_fresh(db_session)
    hw = db_session.scalar(
        select(HardwareCatalogue).where(HardwareCatalogue.spec_id == "panel_longi_lr5_54hth_440m")
    )
    # Soft-delete-ready storage shape.
    assert hw.deleted_at is None and hw.is_active is True
    alias_ids_before = {
        a.id for a in db_session.scalars(select(HardwareAlias).where(HardwareAlias.hardware_id == hw.id)).all()
    }
    assert alias_ids_before  # has aliases

    # Soft-deleting the catalogue entry leaves its aliases associated (FK + rows intact) — the
    # restore-ready shape; no cascade delete.
    from datetime import datetime, timezone

    hw.deleted_at = datetime.now(timezone.utc)
    db_session.flush()
    alias_ids_after = {
        a.id for a in db_session.scalars(select(HardwareAlias).where(HardwareAlias.hardware_id == hw.id)).all()
    }
    assert alias_ids_after == alias_ids_before
    assert db_session.get(HardwareCatalogue, hw.id).deleted_at is not None
