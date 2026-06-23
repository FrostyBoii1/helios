"""Hardware Parser lane, Stage 4A — standalone parser runtime (catalogue-consuming matcher).

Proves the required behaviours against the REAL seeded catalogue + the versioned rules config:
exact / loose / case-sensitive alias matching, source_examples never match, guard-phrase
suppression, specific-correction override, ignore rules, unknown-text preserved (never guessed),
panel model-null / model_options, metering as first-class hardware, list-based site_notes, output
validates against JobHardwarePatch, and parsing mutates nothing. No import wiring is exercised.

Synthetic, rollback-isolated db_session; the catalogue is seeded (idempotent) into it.
"""
from __future__ import annotations

import pytest
import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.hardware.rules import spec_dir
from app.hardware.runtime import parse_hardware
from app.hardware.seed import seed_hardware_catalogue
from app.models.enums import HardwareAliasType
from app.models.hardware import HardwareAlias, HardwareCatalogue
from app.schemas.job_hardware import JobHardwarePatch


@pytest.fixture()
def seeded(db_session: Session) -> Session:
    seed_hardware_catalogue(db_session)  # idempotent
    return db_session


# --------------------------------------------------------------------------- #
# Alias matching
# --------------------------------------------------------------------------- #
def test_exact_alias_match(seeded):
    out = parse_hardware(seeded, inverter_text="Alpha ESS SMILE-G3-B5-INV")
    invs = out["inverters"]
    assert len(invs) == 1
    assert invs[0]["model_text"] == "Alpha ESS SMILE-G3-B5-INV"
    assert invs[0]["confidence"] == "exact"
    assert invs[0]["parser_owned"] is True
    assert invs[0]["canonical_hardware_id_at_parse_time"] > 0  # provenance only


def test_loose_alias_match(seeded):
    # Pull a real loose alias from the seeded catalogue (robust to spec changes).
    row = seeded.execute(
        select(HardwareAlias, HardwareCatalogue)
        .join(HardwareCatalogue, HardwareAlias.hardware_id == HardwareCatalogue.id)
        .where(HardwareAlias.alias_type == HardwareAliasType.LOOSE.value)
    ).first()
    assert row is not None, "expected at least one seeded loose alias"
    alias, cat = row

    out = parse_hardware(seeded, inverter_text=alias.alias)
    matched = [
        it for bucket in ("inverters", "batteries", "metering")
        for it in out.get(bucket, [])
        if it.get("canonical_hardware_id_at_parse_time") == cat.id
    ]
    assert matched, f"loose alias {alias.alias!r} did not resolve to its catalogue entry"
    # A loose match carries the spec's lower confidence, not "exact".
    assert matched[0]["confidence"] != "exact"


def test_case_sensitive_jinko_resolves_distinct_panels(seeded):
    lower = parse_hardware(seeded, panel_text="Jinko 440", quantity_hint=20)
    upper = parse_hardware(seeded, panel_text="JINKO 440", quantity_hint=20)
    assert lower["panel"]["model"] == "JKM440N-54HL4"
    assert upper["panel"]["model"] == "JKM440N-54HL4R-B"
    assert lower["panel"]["model"] != upper["panel"]["model"]
    # A differently-cased, non-seeded form is NOT guessed (model null -> dropped by exclude_none).
    other = parse_hardware(seeded, panel_text="jinko 440", quantity_hint=20)
    assert other["panel"].get("model") is None


def test_source_examples_never_match(seeded):
    # A full source_example string is evidence only — it is not a matchable alias and must NOT
    # resolve to the canonical model; it is preserved as raw unconfirmed text.
    example = "ALPHA ESS M5 5KW INVERTER AND 15KW BATTERY"
    out = parse_hardware(seeded, inverter_text=example)
    inv = out["inverters"][0]
    assert inv["model_text"] == example                     # preserved verbatim
    assert inv["model_text"] != "Alpha ESS SMILE-M5 inverter"  # NOT resolved via the source_example
    assert inv["confidence"] == "unconfirmed_raw_text"
    assert inv.get("canonical_hardware_id_at_parse_time") is None


# --------------------------------------------------------------------------- #
# Guard phrases / corrections / ignore rules
# --------------------------------------------------------------------------- #
def test_guard_phrase_suppresses_inference(seeded):
    out = parse_hardware(seeded, inverter_text="old Goodwe 10kw 3 Phase inverter")
    inv = out["inverters"][0]
    assert inv["confidence"] == "manual_review"
    assert inv["model_text"] == "old Goodwe 10kw 3 Phase inverter"  # not inferred to a model
    assert inv.get("canonical_hardware_id_at_parse_time") is None
    assert out["warnings"]


def test_specific_correction_maps_and_overrides_guard(seeded):
    # A plain correction.
    out = parse_hardware(seeded, inverter_text="SMA 10kW")
    assert out["inverters"][0]["model_text"] == "STP10.0-3AV-40"
    assert out["inverters"][0]["confidence"] == "manual_correction"

    # A correction whose text ALSO contains a guard phrase ("reusing") — the correction wins.
    out2 = parse_hardware(seeded, inverter_text="Reusing Fronius Inverter")
    assert out2["inverters"][0]["model_text"] == "SYMO-6.0-3-M"
    assert out2["inverters"][0]["confidence"] == "manual_correction"


def test_ignore_rule_drops_hardware(seeded):
    out = parse_hardware(seeded, inverter_text="Used 10kw Solax")
    assert out["inverters"] == [] and out["batteries"] == [] and out["metering"] == []


def test_unknown_hardware_preserved_not_guessed(seeded):
    out = parse_hardware(seeded, inverter_text="Frobnicator 9000 inverter")
    inv = out["inverters"][0]
    assert inv["model_text"] == "Frobnicator 9000 inverter"
    assert inv["confidence"] == "unconfirmed_raw_text"
    assert inv.get("canonical_hardware_id_at_parse_time") is None
    assert out["warnings"]


# --------------------------------------------------------------------------- #
# Panels (stricter model-null rules)
# --------------------------------------------------------------------------- #
def test_panel_brand_only_keeps_model_null(seeded):
    out = parse_hardware(seeded, panel_text="Longi", quantity_hint=30)
    p = out["panel"]
    assert p.get("model") is None  # null -> dropped by exclude_none
    assert p["brand"] == "LONGi Solar"
    assert p["confidence"] == "unconfirmed_raw_text"
    assert out["warnings"]


def test_panel_ambiguous_keeps_model_options_model_null(seeded):
    out = parse_hardware(seeded, panel_text="Suntech 415", quantity_hint=20)
    p = out["panel"]
    assert p.get("model") is None  # null -> dropped by exclude_none
    assert p["model_options"] and len(p["model_options"]) >= 2
    assert p["confidence"] == "manual_review"


def test_panel_exact_alias_resolves_model_and_array_kw(seeded):
    out = parse_hardware(seeded, panel_text="Longi 440", quantity_hint=30)
    p = out["panel"]
    assert p["model"] == "LR5-54HTH-440M" and p["brand"] == "LONGi Solar"
    assert p["wattage_w"] == 440 and p["panel_array_kw"] == 13.2


# --------------------------------------------------------------------------- #
# Hardware quantity preservation + capacity-evidence routing (the "2 × MODEL" bug)
# --------------------------------------------------------------------------- #
def _only(items: list[dict]) -> dict:
    assert len(items) == 1, f"expected exactly one item, got {items!r}"
    return items[0]


def test_bundle_preserves_quantity_and_keeps_capacity_out_of_model_text(seeded):
    """The reported blocker: 'SAJ H2-10K-S3-A + 2 × SAJ B2-20.0-HV1 - 40kw hrs' must split into a
    qty-1 inverter, a qty-2 battery, and the '40kw hrs' capacity preserved as a hardware note —
    NOT a third raw inverter item and NOT glued onto any model_text."""
    out = parse_hardware(seeded, inverter_text="SAJ H2-10K-S3-A + 2 × SAJ B2-20.0-HV1 - 40kw hrs")

    inv = _only(out["inverters"])
    assert inv["model_text"] == "SAJ H2-10K-S3-A"
    assert inv["quantity"] == 1
    assert inv["confidence"] == "exact"

    bat = _only(out["batteries"])
    assert bat["model_text"] == "SAJ B2-20.0-HV1"   # canonical model only — no "2 × " prefix
    assert bat["quantity"] == 2                       # explicit quantity preserved

    # The trailing capacity evidence is preserved as a hardware note, never an inverter/battery item
    # and never contaminating a model_text.
    assert out["site_notes"]["raw_misc"] == ["40kw hrs"]
    all_model_text = " | ".join(
        it.get("model_text") or ""
        for bucket in ("inverters", "batteries", "metering")
        for it in out.get(bucket, [])
    )
    assert "40kw" not in all_model_text.lower()
    JobHardwarePatch.model_validate(out)             # still a valid snapshot


@pytest.mark.parametrize("text", [
    "SAJ H2-10K-S3-A + 2 × SAJ B2-20.0-HV1",   # × (multiplication sign)
    "SAJ H2-10K-S3-A + 2 x SAJ B2-20.0-HV1",   # x (letter)
    "SAJ H2-10K-S3-A + 2*SAJ B2-20.0-HV1",     # * (asterisk, no spaces)
    "SAJ H2-10K-S3-A + 2 SAJ B2-20.0-HV1",     # bare "N MODEL" (resolves -> safe to split)
])
def test_quantity_separators_all_yield_qty_two_battery(seeded, text):
    out = parse_hardware(seeded, inverter_text=text)
    bat = _only(out["batteries"])
    assert bat["model_text"] == "SAJ B2-20.0-HV1"
    assert bat["quantity"] == 2
    assert _only(out["inverters"])["model_text"] == "SAJ H2-10K-S3-A"


def test_bare_number_not_split_when_model_does_not_resolve(seeded):
    """A bare leading number is honoured as a quantity ONLY when the remainder resolves to a
    catalogue model — otherwise unit/capacity text would be mis-split. An unresolved bare-number
    fragment is preserved verbatim (quantity falls back to 1)."""
    out = parse_hardware(seeded, inverter_text="2 Frobnicator 9000")
    inv = _only(out["inverters"])
    assert inv["model_text"] == "2 Frobnicator 9000"   # the leading "2" is NOT stripped
    assert inv["quantity"] == 1
    assert inv["confidence"] == "unconfirmed_raw_text"


def test_bare_kw_power_is_not_treated_as_capacity_evidence(seeded):
    """Capacity routing targets ENERGY units (kWh / kw hrs). Bare 'kw' is inverter POWER and must
    stay an ordinary (unmatched) item, not get diverted into a capacity note."""
    out = parse_hardware(seeded, inverter_text="10kw inverter")
    assert out.get("site_notes") in (None, {}) or "raw_misc" not in (out.get("site_notes") or {})
    assert _only(out["inverters"])["model_text"] == "10kw inverter"


def test_unmatched_explicit_quantity_strips_prefix_into_quantity_field(seeded):
    """An UNMATCHED fragment carrying an explicit 'N ×' prefix stores the quantity separately and
    the model CORE as text (so the quantity is rendered once, never doubled into model_text)."""
    out = parse_hardware(seeded, inverter_text="3 × Frobnicator 9000")
    inv = _only(out["inverters"])
    assert inv["model_text"] == "Frobnicator 9000"
    assert inv["quantity"] == 3
    assert inv["confidence"] == "unconfirmed_raw_text"


# --------------------------------------------------------------------------- #
# Metering + site_notes + schema conformance + no-mutation
# --------------------------------------------------------------------------- #
def test_metering_is_first_class(seeded):
    out = parse_hardware(seeded, inverter_text="meter 3p")
    assert len(out["metering"]) == 1
    assert out["metering"][0]["model_text"] == "3P Meter"
    assert out["metering"][0]["confidence"] == "exact"


def test_site_notes_are_lists(seeded):
    out = parse_hardware(seeded, inverter_text="+ CT")
    assert isinstance(out["site_notes"]["ct"], list)
    assert out["site_notes"]["ct"] == ["CT"]
    # The list-based shape validates under the (revised) JobHardwarePatch schema.
    JobHardwarePatch.model_validate(out)


def test_output_always_validates_against_jobhardwarepatch(seeded):
    for kwargs in (
        {"inverter_text": "Alpha ESS SMILE-G3-B5-INV"},
        {"inverter_text": "meter 3p + CT"},
        {"panel_text": "Suntech 415", "quantity_hint": 10},
        {"inverter_text": "totally unknown thing"},
        {},  # empty input -> empty (but valid) snapshot
    ):
        out = parse_hardware(seeded, **kwargs)
        # Re-validation must succeed and add no unknown keys (extra='forbid').
        JobHardwarePatch.model_validate(out)


def test_parsing_does_not_mutate_catalogue_or_aliases(seeded):
    cat_before = seeded.scalar(select(func.count()).select_from(HardwareCatalogue))
    alias_before = seeded.scalar(select(func.count()).select_from(HardwareAlias))
    sample = seeded.scalar(select(HardwareCatalogue).where(HardwareCatalogue.canonical_model.is_not(None)))
    model_before, updated_before = sample.canonical_model, sample.updated_at

    parse_hardware(seeded, inverter_text="Alpha ESS SMILE-G3-B5-INV + meter 3p", panel_text="Longi 440")

    assert seeded.scalar(select(func.count()).select_from(HardwareCatalogue)) == cat_before
    assert seeded.scalar(select(func.count()).select_from(HardwareAlias)) == alias_before
    seeded.refresh(sample)
    assert sample.canonical_model == model_before and sample.updated_at == updated_before


# --------------------------------------------------------------------------- #
# Practical fixture coverage (panel package — single-fragment, no system-size derivation)
# --------------------------------------------------------------------------- #
def test_panel_fixture_model_null_safety(seeded):
    """For panel fixtures my matcher handles (a single source_fragment, no proposal/system-size
    derivation), the conservative model-null rule must hold and resolved models must match. Full
    multi-fragment hardware bundles + system-size derivation are a documented follow-up."""
    fixtures = yaml.safe_load(
        (spec_dir() / "panel_parser_fixtures_v1_1.yaml").read_text(encoding="utf-8")
    )["fixtures"]
    # Confidences that require proposal/NAS/system-size evidence the Stage-4A matcher does not
    # consume — those fixtures are a documented follow-up, skipped here.
    _DERIVED = {"derived_from_system_size", "proposal_overrode_sheet"}
    checked = 0
    for f in fixtures:
        if f.get("proposal_system_size_kw") is not None:
            continue  # derivation deferred (needs proposal/NAS evidence)
        src = f.get("source_fragment")
        exp = (f["expected"].get("panel") or {})
        if not src or "panel" not in f["expected"] or exp.get("confidence") in _DERIVED:
            continue
        out = parse_hardware(seeded, panel_text=src, quantity_hint=f.get("existing_quantity_value"))
        got = out.get("panel") or {}
        # Safety-critical: model-null parity (never guess a model the fixture leaves null).
        assert (got.get("model") is None) == (exp.get("model") is None), (
            f"panel fixture {f['id']}: model-null mismatch (got {got.get('model')!r}, "
            f"expected {exp.get('model')!r})"
        )
        if exp.get("model") is not None:
            assert got.get("model") == exp["model"], f"panel fixture {f['id']}: model mismatch"
        checked += 1
    assert checked >= 5, "expected to exercise several panel fixtures"
