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
    # resolve to the canonical model. (P1 now SPLITS it on the embedded ' and ' into raw fragments;
    # the invariant is that no fragment resolves, NOT that the whole string stays a single item.)
    example = "ALPHA ESS M5 5KW INVERTER AND 15KW BATTERY"
    out = parse_hardware(seeded, inverter_text=example)
    items = out["inverters"] + out["batteries"] + out["metering"]
    assert items, "expected the source_example preserved as raw text"
    assert all(it.get("canonical_hardware_id_at_parse_time") is None for it in items)
    assert all(it["confidence"] == "unconfirmed_raw_text" for it in items)
    all_text = " ".join((it.get("model_text") or "") for it in items)
    assert "SMILE-M5" not in all_text  # never resolved to the Alpha ESS SMILE-M5 canonical model


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


# --------------------------------------------------------------------------- #
# P1: separator splitting — the real workbook joins fragments with "/", "and", "&", "·", "•",
# "with" (not just "+" / spaced "-"). Splitting on these lets each catalogued component resolve
# instead of collapsing the whole cell into one raw blob, while never breaking a model-internal
# token and never letting a source_example resolve.
# --------------------------------------------------------------------------- #
def test_slash_splits_inverter_and_battery(seeded):
    """A "/"-joined bundle of two catalogued models (audit: 'SH10RT/SBR128 BATT') splits into the
    inverter and the battery rather than collapsing into one raw blob."""
    out = parse_hardware(seeded, inverter_text="SH10RT/SBR128")
    inv = _only(out["inverters"])
    bat = _only(out["batteries"])
    assert inv["model_text"] == "SH10RT" and inv["canonical_hardware_id_at_parse_time"]
    assert bat["model_text"] == "SBR128" and bat["canonical_hardware_id_at_parse_time"]


def test_and_splits_inverter_and_qty_battery(seeded):
    """' and ' joins an inverter + a quantified battery in the real workbook; both resolve and the
    battery quantity is preserved (audit: '1 x SAJ H2-10K-S3 and 2 x SAJ B2-15.0-HV1')."""
    out = parse_hardware(seeded, inverter_text="1 x SAJ H2-10K-S3 and 2 x SAJ B2-15.0-HV1")
    inv = _only(out["inverters"])
    bat = _only(out["batteries"])
    assert inv["model_text"] == "SAJ H2-10K-S3" and inv["quantity"] == 1
    assert bat["model_text"] == "SAJ B2-15.0-HV1" and bat["quantity"] == 2


def test_middot_splits_and_routes_capacity(seeded):
    """'and' + '·' bundle (audit: '1 x SAJ H2-25K-T3-AU and 2 × SAJ B2-25.0-HV1 · 25kWh'): inverter,
    qty-2 battery, and the trailing capacity preserved as a note — never glued into a model_text."""
    out = parse_hardware(seeded, inverter_text="1 x SAJ H2-25K-T3-AU and 2 × SAJ B2-25.0-HV1 · 25kWh")
    inv = _only(out["inverters"])
    bat = _only(out["batteries"])
    assert inv["model_text"] == "SAJ H2-25K-T3-AU"
    assert bat["model_text"] == "SAJ B2-25.0-HV1" and bat["quantity"] == 2
    assert "25kWh" in out["site_notes"]["raw_misc"]
    all_text = " ".join((it.get("model_text") or "")
                        for b in ("inverters", "batteries", "metering") for it in out.get(b, []))
    assert "25kwh" not in all_text.lower()


def test_ampersand_splits_bundle(seeded):
    out = parse_hardware(seeded, inverter_text="SH10RT & SBR128")
    assert _only(out["inverters"])["model_text"] == "SH10RT"
    assert _only(out["batteries"])["model_text"] == "SBR128"


def test_with_splits_meter_from_inverter(seeded):
    """' with ' separates an inverter from its meter so the meter resolves to first-class metering
    instead of contaminating the inverter text."""
    out = parse_hardware(seeded, inverter_text="SH10RT with meter")
    assert _only(out["inverters"])["model_text"] == "SH10RT"
    met = _only(out["metering"])
    assert met["canonical_hardware_id_at_parse_time"]


def test_slash_keeps_capacity_out_of_inverter_text(seeded):
    """'2 x Sungrow Hybrid 5kw/16kw hrs battery': the '/' split breaks the cell into separate
    fragments so the battery-capacity text never glues onto the inverter fragment (before P1 the
    whole cell was one raw blob)."""
    out = parse_hardware(seeded, inverter_text="2 x Sungrow Hybrid 5kw/16kw hrs battery")
    items = out["inverters"] + out["batteries"] + out["metering"]
    texts = [it.get("model_text") or "" for it in items]
    assert len(items) >= 2, texts                                  # the '/' split it apart
    # No single item glues the inverter power and the battery capacity together.
    assert not any("5kw" in t.lower() and "16kw" in t.lower() for t in texts), texts
    assert any("16kw" in t.lower() for t in texts), texts          # capacity kept as its own fragment


def test_model_internal_punctuation_not_oversplit(seeded):
    """A catalogue model with internal hyphens is matched whole — the splitter must not break it
    apart (only a SPACED ' - ' splits, never a model-internal hyphen)."""
    out = parse_hardware(seeded, inverter_text="X1-BOOST-5K-G4")
    inv = _only(out["inverters"])
    assert inv["model_text"] == "X1-BOOST-5K-G4"
    assert inv["canonical_hardware_id_at_parse_time"]


def test_middot_capacity_suffix_splits_to_raw_unchanged(seeded):
    """A '·' capacity/spec suffix is rewritten to a spaced '-' by _normalize_encoding, so a cell like
    'SolaX Smart EV Charger · 22kW' splits into separate fragments via the existing hyphen rule —
    exactly as it did BEFORE P1 (no regression). The fragments are preserved raw; nothing is guessed.
    (The catalogue alias keeps a raw '·', which normalized input can't reach — a pre-existing trait,
    not introduced here.)"""
    out = parse_hardware(seeded, inverter_text="SolaX Smart EV Charger · 22kW")
    items = out["inverters"] + out["batteries"] + out["metering"]
    assert len(items) >= 2, items                                  # split, not one blob
    assert all(it.get("canonical_hardware_id_at_parse_time") is None for it in items)
    assert "22kW" in [it.get("model_text") for it in items]


def test_mid_fragment_quantity_preserved_verbatim(seeded):
    """A non-leading 'N x' quantity (mid-fragment) is NOT a top-level separator and is preserved in
    the raw text — never silently dropped or over-split (resolution of such forms is P2)."""
    out = parse_hardware(seeded, inverter_text="Sungrow Hybrid 2 x 5kw")
    inv = _only(out["inverters"])
    assert inv["model_text"] == "Sungrow Hybrid 2 x 5kw"   # one fragment; "2 x" kept
    assert inv["confidence"] == "unconfirmed_raw_text"


# --------------------------------------------------------------------------- #
# P2: brand-prefix / noise normalization — resolve a BARE catalogue model that the workbook prefixed
# with brand (+ optional power) text or suffixed with a hardware-type noun, WITHOUT guessing or
# bloating the catalogue. Resolves ONLY when the stripped remainder is itself a catalogue alias.
# --------------------------------------------------------------------------- #
def test_brand_prefix_solax_power_resolves(seeded):
    out = parse_hardware(seeded, inverter_text="Solax Power X1-SMT-10K-G2")
    inv = _only(out["inverters"])
    assert inv["model_text"] == "X1-SMT-10K-G2"                   # resolved canonical, not the raw text
    assert inv["canonical_hardware_id_at_parse_time"]
    assert inv["source_fragment"] == "Solax Power X1-SMT-10K-G2"  # provenance keeps the original fragment


def test_brand_prefix_sungrow_resolves(seeded):
    out = parse_hardware(seeded, inverter_text="Sungrow SH10RT")
    inv = _only(out["inverters"])
    assert inv["model_text"] == "SH10RT" and inv["canonical_hardware_id_at_parse_time"]


def test_brand_prefix_with_leading_power_resolves(seeded):
    out = parse_hardware(seeded, inverter_text="Sungrow 10kW SH10RT")
    inv = _only(out["inverters"])
    assert inv["model_text"] == "SH10RT" and inv["canonical_hardware_id_at_parse_time"]


def test_p1_plus_p2_slash_bundle_fully_resolves(seeded):
    """The audit case: 'Sungrow 10kW SH10RT/SBR128 BATT' splits on '/' (P1) then resolves the brand-
    prefixed inverter and the trailing-noun battery (P2)."""
    out = parse_hardware(seeded, inverter_text="Sungrow 10kW SH10RT/SBR128 BATT")
    inv = _only(out["inverters"])
    bat = _only(out["batteries"])
    assert inv["model_text"] == "SH10RT" and inv["canonical_hardware_id_at_parse_time"]
    assert bat["model_text"] == "SBR128" and bat["canonical_hardware_id_at_parse_time"]


def test_brand_prefix_preserves_quantity(seeded):
    out = parse_hardware(seeded, inverter_text="2 x Sungrow SH10RT")
    inv = _only(out["inverters"])
    assert inv["model_text"] == "SH10RT" and inv["quantity"] == 2


def test_saj_prefixed_still_resolves_directly(seeded):
    # SAJ aliases already INCLUDE the brand, so this matches directly (the strip is a harmless no-op).
    out = parse_hardware(seeded, inverter_text="SAJ H2-10K-S3")
    assert _only(out["inverters"])["model_text"] == "SAJ H2-10K-S3"


def test_alpha_ess_known_alias_resolves(seeded):
    out = parse_hardware(seeded, inverter_text="Alpha ESS SMILE-G3-B5-INV")
    inv = _only(out["inverters"])
    assert inv["model_text"] == "Alpha ESS SMILE-G3-B5-INV"
    assert inv["canonical_hardware_id_at_parse_time"]


@pytest.mark.parametrize("text", ["Sungrow", "Solax", "Goodwe"])
def test_brand_only_does_not_resolve(seeded, text):
    out = parse_hardware(seeded, inverter_text=text)
    items = out["inverters"] + out["batteries"] + out["metering"]
    assert all(it.get("canonical_hardware_id_at_parse_time") is None for it in items)


@pytest.mark.parametrize("text", ["Solis 5kw", "Goodwe 10kw", "Sungrow 5kw"])
def test_capacity_only_stays_raw(seeded, text):
    """Brand + capacity-only ('Solis 5kw') must NOT resolve to a model — there is no exact model to
    pick, so it stays unconfirmed raw for review (decision log D-v9.1-002)."""
    out = parse_hardware(seeded, inverter_text=text)
    items = out["inverters"] + out["batteries"] + out["metering"]
    assert items, "the capacity-only text is preserved as raw"
    assert all(it.get("canonical_hardware_id_at_parse_time") is None for it in items)
    assert all(it["confidence"] in ("unconfirmed_raw_text", "manual_review") for it in items)


def test_brand_strip_never_resolves_source_example(seeded):
    """Brand normalization must not let a source_example resolve: 'Alpha ESS SMILE-M5 5KW INVERTER'
    (a curated example fragment) strips to nothing a catalogue alias matches — it stays raw."""
    out = parse_hardware(seeded, inverter_text="Alpha ESS M5 5KW INVERTER")
    items = out["inverters"] + out["batteries"] + out["metering"]
    assert all(it.get("canonical_hardware_id_at_parse_time") is None for it in items)
    assert "SMILE-M5" not in " ".join((it.get("model_text") or "") for it in items)


# --------------------------------------------------------------------------- #
# P3: route UNMATCHED battery/metering-like fragments to the right bucket (not 'inverters'), so a Job
# never shows battery/meter evidence as an inverter. Raw only — no catalogue id is ever invented.
# --------------------------------------------------------------------------- #
def test_unmatched_battery_word_routes_to_batteries(seeded):
    # A genuinely-unknown battery (no catalogue match) routes to the batteries bucket as raw evidence,
    # never the inverter bucket. (A catalogued model like "1 SBR096 battery" instead RESOLVES via P5
    # leading-quantity + trailing-noun cleanup — covered by the P5 tests.)
    out = parse_hardware(seeded, inverter_text="Frobnicator battery")
    assert out["inverters"] == []
    bat = _only(out["batteries"])
    assert bat["model_text"] == "Frobnicator battery"
    assert bat["confidence"] == "unconfirmed_raw_text"
    assert bat.get("canonical_hardware_id_at_parse_time") is None   # never invented


def test_unmatched_capacity_batt_routes_to_batteries(seeded):
    out = parse_hardware(seeded, inverter_text="12.8kw batt")
    assert out["inverters"] == []
    bat = _only(out["batteries"])
    assert bat["model_text"] == "12.8kw batt"
    assert bat.get("canonical_hardware_id_at_parse_time") is None


def test_sbr128_batt_stays_matched_battery_after_p2(seeded):
    # P2 strips the trailing "BATT" -> SBR128 resolves; it must be a MATCHED battery (not a P3 raw item).
    out = parse_hardware(seeded, inverter_text="SBR128 BATT")
    bat = _only(out["batteries"])
    assert bat["model_text"] == "SBR128" and bat["canonical_hardware_id_at_parse_time"]
    assert out["inverters"] == []


def test_unmatched_export_meter_routes_to_metering(seeded):
    out = parse_hardware(seeded, inverter_text="1 export meter")
    assert out["inverters"] == []
    met = _only(out["metering"])
    assert met["model_text"] == "1 export meter"
    assert met.get("canonical_hardware_id_at_parse_time") is None


def test_smart_meter_export_routes_to_metering_not_site_or_inverter(seeded):
    """Has both 'meter' (metering hardware) and '5kw export' (an export-limit site keyword): the meter
    hardware wins — it lands in metering, never the inverter bucket and never swallowed as a site note."""
    out = parse_hardware(seeded, inverter_text="smart meter 5kw export")
    assert out["inverters"] == []
    met = _only(out["metering"])
    assert "meter" in met["model_text"].lower()
    assert met.get("canonical_hardware_id_at_parse_time") is None
    assert "export_limit" not in (out.get("site_notes") or {})


def test_quantity_preserved_when_routing_to_battery(seeded):
    out = parse_hardware(seeded, inverter_text="6 x 3.2 batt")
    bat = _only(out["batteries"])
    assert bat["quantity"] == 6 and bat["model_text"] == "3.2 batt"
    assert out["inverters"] == []


@pytest.mark.parametrize("text", ["Solis 5kw", "Goodwe 10kw"])
def test_ambiguous_inverter_capacity_stays_inverter(seeded, text):
    """No battery/metering signal -> stays raw INVERTER (P3 must not route ambiguous inverter capacity
    to battery/metering)."""
    out = parse_hardware(seeded, inverter_text=text)
    inv = _only(out["inverters"])
    assert inv["confidence"] == "unconfirmed_raw_text"
    assert out["batteries"] == [] and out["metering"] == []


def test_ct_still_routes_to_site_notes(seeded):
    # P3 must NOT regress CT: a bare CT keyword stays in site_notes.ct, not metering.
    out = parse_hardware(seeded, inverter_text="Solis 10kw + CT")
    assert out["site_notes"]["ct"] == ["CT"]
    assert out["metering"] == []


# --------------------------------------------------------------------------- #
# P4: evidence-based catalogue adds — real workbook hardware that was still raw now resolves
# (no guessing; only models with workbook/curated-spec evidence were added).
# --------------------------------------------------------------------------- #
def test_p4_t_bat_hs25_2_resolves_battery(seeded):
    # "Solax Power T-BAT HS25.2" -> P2 strips "solax power" -> the new bare "T-BAT HS25.2" alias.
    out = parse_hardware(seeded, inverter_text="Solax Power T-BAT HS25.2")
    bat = _only(out["batteries"])
    assert bat["model_text"] == "SolaX T-BAT HS25.2" and bat["canonical_hardware_id_at_parse_time"]
    assert out["inverters"] == []


def test_p4_t_bat_hs32_4_resolves_battery(seeded):
    out = parse_hardware(seeded, inverter_text="Solax Power T-BAT HS32.4")
    assert _only(out["batteries"])["model_text"] == "SolaX T-BAT HS32.4"


def test_p4_neovolt_bw_bat_10_1_resolves_battery(seeded):
    # "Neovolt BW-BAT-10.1" (hyphen, no trailing P) -> P2 strips "neovolt" -> new "BW-BAT-10.1" alias.
    out = parse_hardware(seeded, inverter_text="Neovolt BW-BAT-10.1")
    bat = _only(out["batteries"])
    assert bat["model_text"] == "Neovolt BW-BAT-10.1P" and bat["canonical_hardware_id_at_parse_time"]


def test_p4_smile_m_bat_5p_vi_resolves_battery(seeded):
    # SMILE-M-BAT-5P VI was missing as an entry (only iii/iv/v existed); now a matched battery.
    out = parse_hardware(seeded, inverter_text="Alpha ESS SMILE-M-BAT-5P VI")
    bat = _only(out["batteries"])
    assert bat["model_text"] == "SMILE-M-BAT-5P VI" and bat["canonical_hardware_id_at_parse_time"]


def test_p4_tesla_manufacturer_corrected():
    # The Tesla Powerwall 3 entries had manufacturer "Unknown"; P4 corrects both to "Tesla" in the
    # SPEC. The fix applies on a FRESH seed (the idempotent seed inserts-if-missing and never
    # clobbers an already-seeded row), so this asserts the vendored spec rather than a live DB row.
    runtime = yaml.safe_load(
        (spec_dir() / "hardware_parser_runtime_rules_v9_1.yaml").read_text(encoding="utf-8")
    )
    tesla = [e for e in runtime["hardware_catalog"] if "Tesla Powerwall 3" in e["canonical_model"]]
    assert len(tesla) == 2, [e["canonical_model"] for e in tesla]
    assert all(e["manufacturer"] == "Tesla" for e in tesla), [e["manufacturer"] for e in tesla]


def test_p4_seed_is_idempotent(seeded):
    # The catalogue is already seeded by the fixture; a second seed must insert nothing.
    assert seed_hardware_catalogue(seeded) == {"hardware_created": 0, "alias_created": 0}


def test_p4_catalogue_adds_do_not_resolve_ambiguous_capacity(seeded):
    # The new entries must NOT make ambiguous capacity-only text resolve to a model.
    for text in ("Solis 5kw", "Goodwe 10kw"):
        out = parse_hardware(seeded, inverter_text=text)
        inv = _only(out["inverters"])
        assert inv["confidence"] == "unconfirmed_raw_text"
        assert inv.get("canonical_hardware_id_at_parse_time") is None


# --------------------------------------------------------------------------- #
# P5: leading bare-quantity resolution + metering/capacity correctness. (Metering vocab and
# capacity-in-noun routing were already handled by P3; these confirm them and add the new
# leading-quantity behaviour.)
# --------------------------------------------------------------------------- #
def test_p5_leading_quantity_one_resolves_battery(seeded):
    # "1 SBR128 battery": leading bare "1" honoured (remainder resolves via P2 trailing-noun cleanup).
    out = parse_hardware(seeded, inverter_text="1 SBR128 battery")
    bat = _only(out["batteries"])
    assert bat["model_text"] == "SBR128" and bat["quantity"] == 1
    assert bat["canonical_hardware_id_at_parse_time"]
    assert out["inverters"] == []


def test_p5_leading_quantity_two_resolves_battery(seeded):
    out = parse_hardware(seeded, inverter_text="2 SBR128 batteries")
    bat = _only(out["batteries"])
    assert bat["model_text"] == "SBR128" and bat["quantity"] == 2


def test_p5_leading_quantity_not_split_when_remainder_unresolved(seeded):
    # A leading number is NOT treated as a quantity when the remainder does not resolve.
    out = parse_hardware(seeded, inverter_text="2 Frobnicator 9000")
    inv = _only(out["inverters"])
    assert inv["model_text"] == "2 Frobnicator 9000" and inv["quantity"] == 1


def test_p5_capacity_noun_battery_not_inverter(seeded):
    # "16kw hrs battery": battery wording, no model -> raw BATTERY evidence (not inverter model_text).
    out = parse_hardware(seeded, inverter_text="16kw hrs battery")
    assert out["inverters"] == []
    bat = _only(out["batteries"])
    assert bat["model_text"] == "16kw hrs battery"
    assert bat.get("canonical_hardware_id_at_parse_time") is None


def test_p5_pure_capacity_routes_to_raw_misc(seeded):
    # "40kw hrs": capacity-only, no battery/metering noun -> hardware note, never an item model_text.
    out = parse_hardware(seeded, inverter_text="40kw hrs")
    assert out["inverters"] == [] and out["batteries"] == [] and out["metering"] == []
    assert out["site_notes"]["raw_misc"] == ["40kw hrs"]


def test_p5_with_meter_resolves_metering(seeded):
    # " with " splits (P1); the meter resolves to first-class metering, not inverter text.
    out = parse_hardware(seeded, inverter_text="Goodwe 10kw with meter")
    assert out["metering"] and out["metering"][0]["model_text"] == "Meter"


# --------------------------------------------------------------------------- #
# P6a: known shorthand aliases (Vast / 13.3p / extension / Neovolt) + the two Swatten component
# entries + quantity aggregation. (The heavier whole-cell bundle interpretations + notes + the
# Solis/mixed cases are P6b.)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", ["Vast 10kw", "Solax Vast 10kw", "VAST 10K INVERTER", "SolaX Power VAST 10k"])
def test_p6a_vast_shorthand_resolves_inverter(seeded, text):
    out = parse_hardware(seeded, inverter_text=text)
    assert _only(out["inverters"])["model_text"] == "X1-VAST-10K"


@pytest.mark.parametrize("text", ["13.3p", "extension 13.3p", "Alpha ESS 13.3p", "ext 13.3p"])
def test_p6a_alpha_13_3p_shorthand_resolves_battery(seeded, text):
    out = parse_hardware(seeded, inverter_text=text)
    assert _only(out["batteries"])["model_text"] == "SMILE-BAT-13.3P"


@pytest.mark.parametrize("text", ["10.1 neovolt", "EXTENSION NEOVOLT 10.1"])
def test_p6a_neovolt_reversed_shorthand_resolves_battery(seeded, text):
    out = parse_hardware(seeded, inverter_text=text)
    assert _only(out["batteries"])["model_text"] == "Neovolt BW-BAT-10.1P"


def test_p6a_extension_aggregates_quantity(seeded):
    # "2 × SMILE-BAT-13.3P + extension 13.3P" -> ONE battery of quantity 3 (aggregation_rules), with
    # both contributing source fragments preserved.
    out = parse_hardware(seeded, inverter_text="2 × Alpha ESS SMILE-BAT-13.3P + extension 13.3P")
    bat = _only(out["batteries"])
    assert bat["model_text"] == "SMILE-BAT-13.3P" and bat["quantity"] == 3
    assert "extension" in bat["source_fragment"].lower()


def test_p6a_aggregation_keeps_different_models_separate(seeded):
    # The canonical bundle keeps the inverter and the (qty-2) battery as separate items.
    out = parse_hardware(seeded, inverter_text="SAJ H2-10K-S3-A + 2 × SAJ B2-20.0-HV1 - 40kw hrs")
    assert _only(out["inverters"])["model_text"] == "SAJ H2-10K-S3-A"
    bat = _only(out["batteries"])
    assert bat["model_text"] == "SAJ B2-20.0-HV1" and bat["quantity"] == 2


def test_p6a_swatten_component_entries_exist(seeded):
    for model, cat in (("Swatten SiH-5kW-TH", "inverter"), ("Swatten SieB-H19K2-F", "battery")):
        row = seeded.scalar(select(HardwareCatalogue).where(HardwareCatalogue.canonical_model == model))
        assert row is not None and row.category == cat and row.brand == "Swatten", model


def test_p6a_shorthand_does_not_over_resolve_ambiguous(seeded):
    # The new aliases must not make plain ambiguous capacity resolve.
    for text in ("Solis 5kw", "Goodwe 10kw"):
        out = parse_hardware(seeded, inverter_text=text)
        assert _only(out["inverters"])["confidence"] == "unconfirmed_raw_text"
