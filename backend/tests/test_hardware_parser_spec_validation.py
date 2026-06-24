"""Stage 0 — Hardware Parser SPEC validation gates (no runtime, no DB, no parser yet).

These tests treat the curated parser package in ``docs/parser_specs/hardware/`` as LAW and
assert the acceptance-gate invariants from the spec/validation-notes BEFORE any catalogue
table, seed, parser, or UI is built. They are pure file + YAML checks (no app import, no DB):

  * all spec/fixture files load and are non-empty
  * catalogue IDs are unique (hardware + metering + panel)
  * fixture IDs are unique (duplicate fixture IDs must fail)
  * ``source_examples`` are never also aliases (hard rule: evidence, not matchable)
  * exact/loose alias collisions are detected (none allowed except case-sensitive panel pairs)
  * every confidence value is from the approved vocabulary for its package
  * the panel parser's stricter ``model: null`` rules hold (brand/wattage-only/ambiguous)
  * the known ``parser_rule_version`` drift (runtime says v8, package is v9.1) is pinned/reported

The spec files are vendored verbatim and must NOT be edited to make a test pass — a failure
means the curated package drifted or a real collision was introduced.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# The vendored spec lives in docs/parser_specs/hardware. In the backend container it is a
# read-only mount at /app/parser_specs/hardware (see docker-compose); in a plain repo checkout
# it is <repo>/docs/parser_specs/hardware. Use whichever exists.
_CANDIDATE_DIRS = [
    Path("/app/parser_specs/hardware"),
    Path(__file__).resolve().parents[2] / "docs" / "parser_specs" / "hardware",
]
SPEC_DIR = next((p for p in _CANDIDATE_DIRS if p.is_dir()), _CANDIDATE_DIRS[0])

_MD_FILES = (
    "hardware_parser_spec_v9_1.md",
    "hardware_parser_decision_log_v9_1.md",
    "hardware_parser_validation_notes_v9_1.md",
    "panel_parser_spec_v1_1.md",
    "panel_parser_decision_log_v1_1.md",
    "panel_parser_validation_notes_v1_1.md",
)
_YAML_FILES = (
    "hardware_parser_runtime_rules_v9_1.yaml",
    "hardware_parser_test_fixtures_v9_1.yaml",
    "panel_parser_rules_v1_1.yaml",
    "panel_parser_fixtures_v1_1.yaml",
)


def _load(name: str) -> Any:
    return yaml.safe_load((SPEC_DIR / name).read_text(encoding="utf-8"))


def _norm(value: Any, *, case_sensitive: bool = False) -> str:
    """Whitespace-collapse an alias; casefold unless the alias is flagged case-sensitive."""
    s = " ".join(str(value).split()).strip()
    return s if case_sensitive else s.casefold()


def _hardware_aliases(entry: dict) -> list[str]:
    """exact + loose alias strings for a hardware/metering catalogue entry (plain strings)."""
    out: list[str] = []
    for key in ("exact_aliases", "loose_aliases"):
        for a in entry.get(key) or []:
            if isinstance(a, str):
                out.append(a)
            elif isinstance(a, dict) and "value" in a:  # defensive
                out.append(a["value"])
    return out


# --------------------------------------------------------------------------- #
# Sanity: the spec is reachable and loads
# --------------------------------------------------------------------------- #
def test_spec_dir_resolves():
    assert SPEC_DIR.is_dir(), (
        f"Hardware parser spec dir not found. Tried: "
        f"{[str(p) for p in _CANDIDATE_DIRS]} — is the docs/parser_specs read-only mount present?"
    )


def test_all_files_load_and_nonempty():
    for name in _MD_FILES:
        text = (SPEC_DIR / name).read_text(encoding="utf-8")
        assert text.strip(), f"{name} is empty"
    for name in _YAML_FILES:
        data = _load(name)
        assert data, f"{name} did not load to a non-empty document"
        assert isinstance(data, dict), f"{name} top-level should be a mapping"


# --------------------------------------------------------------------------- #
# Unique catalogue IDs (hardware + metering + panel)
# --------------------------------------------------------------------------- #
def test_catalogue_ids_unique():
    runtime = _load("hardware_parser_runtime_rules_v9_1.yaml")
    hw_ids = [e["id"] for e in runtime["hardware_catalog"]]
    meter_ids = [e["id"] for e in runtime["metering_catalog"]]
    panel = _load("panel_parser_rules_v1_1.yaml")
    panel_ids = [e["canonical_id"] for e in panel["canonical_panels"]]

    for label, ids in (("hardware_catalog", hw_ids), ("metering_catalog", meter_ids),
                       ("panel canonical_panels", panel_ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        assert not dupes, f"Duplicate IDs in {label}: {dupes}"

    # All hardware-side catalogue IDs (hardware + metering) must be globally unique too.
    all_hw = hw_ids + meter_ids
    cross = sorted({i for i in all_hw if all_hw.count(i) > 1})
    assert not cross, f"Catalogue ID collisions across hardware+metering: {cross}"


# --------------------------------------------------------------------------- #
# Duplicate fixture IDs must fail
# --------------------------------------------------------------------------- #
def test_fixture_ids_unique():
    hw = _load("hardware_parser_test_fixtures_v9_1.yaml")["fixtures"]
    panel = _load("panel_parser_fixtures_v1_1.yaml")["fixtures"]
    for label, fixtures in (("hardware", hw), ("panel", panel)):
        ids = [f["id"] for f in fixtures]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        assert not dupes, f"Duplicate {label} fixture IDs: {dupes}"


# --------------------------------------------------------------------------- #
# source_examples are NOT aliases (hard rule)
# --------------------------------------------------------------------------- #
def test_source_examples_not_loaded_as_aliases():
    runtime = _load("hardware_parser_runtime_rules_v9_1.yaml")
    entries = runtime["hardware_catalog"] + runtime["metering_catalog"]
    alias_set = {_norm(a) for e in entries for a in _hardware_aliases(e)}

    offenders: list[str] = []
    for e in entries:
        for ex in e.get("source_examples") or []:
            if _norm(ex) in alias_set:
                offenders.append(f"{e['id']}: {ex!r}")
    assert not offenders, f"source_examples also present as aliases (forbidden): {offenders}"


# --------------------------------------------------------------------------- #
# exact/loose alias collisions detected
# --------------------------------------------------------------------------- #
def test_hardware_alias_collisions():
    runtime = _load("hardware_parser_runtime_rules_v9_1.yaml")
    entries = runtime["hardware_catalog"] + runtime["metering_catalog"]

    exact: dict[str, set[str]] = {}
    loose: dict[str, set[str]] = {}
    for e in entries:
        for a in e.get("exact_aliases") or []:
            exact.setdefault(_norm(a if isinstance(a, str) else a.get("value")), set()).add(e["id"])
        for a in e.get("loose_aliases") or []:
            loose.setdefault(_norm(a if isinstance(a, str) else a.get("value")), set()).add(e["id"])

    exact_collisions = {k: sorted(v) for k, v in exact.items() if len(v) > 1}
    assert not exact_collisions, f"exact_alias maps to >1 catalogue item: {exact_collisions}"
    loose_collisions = {k: sorted(v) for k, v in loose.items() if len(v) > 1}
    assert not loose_collisions, f"loose_alias maps to >1 catalogue item: {loose_collisions}"
    cross = sorted(set(exact) & set(loose))
    assert not cross, f"alias present in BOTH exact and loose matchers: {cross}"


def test_panel_alias_collisions_respect_case_sensitivity():
    panel = _load("panel_parser_rules_v1_1.yaml")
    # Case-sensitive aliases (e.g. 'Jinko 440' vs 'JINKO 440') intentionally resolve to
    # different models, so they are keyed WITH original case; everything else is casefolded.
    exact: dict[str, set[str]] = {}
    for e in panel["canonical_panels"]:
        for a in e.get("exact_aliases") or []:
            value = a["value"] if isinstance(a, dict) else a
            cs = bool(isinstance(a, dict) and a.get("case_sensitive"))
            exact.setdefault(_norm(value, case_sensitive=cs), set()).add(e["canonical_id"])
    collisions = {k: sorted(v) for k, v in exact.items() if len(v) > 1}
    assert not collisions, f"panel exact_alias maps to >1 panel (after case rules): {collisions}"


# --------------------------------------------------------------------------- #
# Confidence values from the approved vocabularies
# --------------------------------------------------------------------------- #
def test_confidence_values_in_vocabulary():
    runtime = _load("hardware_parser_runtime_rules_v9_1.yaml")
    hw_vocab = set(runtime["confidence_levels"])
    panel = _load("panel_parser_rules_v1_1.yaml")
    panel_vocab = set(panel["confidence_levels"])

    # Hardware catalogue confidence rules.
    for e in runtime["hardware_catalog"]:
        for v in (e.get("confidence") or {}).values():
            assert v in hw_vocab, f"{e['id']}: bad catalogue confidence {v!r} not in {sorted(hw_vocab)}"

    # Hardware fixtures: every parsed item confidence.
    hw_fixtures = _load("hardware_parser_test_fixtures_v9_1.yaml")["fixtures"]
    for f in hw_fixtures:
        for bucket in ("inverters", "batteries", "metering"):
            for item in (f["expected"].get(bucket) or []):
                assert item["confidence"] in hw_vocab, (
                    f"hardware fixture {f['id']}: confidence {item['confidence']!r} not in vocab"
                )

    # Panel fixtures + panel alias confidence overrides.
    for e in panel["canonical_panels"]:
        for a in e.get("exact_aliases") or []:
            if isinstance(a, dict) and a.get("confidence_override"):
                assert a["confidence_override"] in panel_vocab, (
                    f"panel {e['canonical_id']}: bad confidence_override {a['confidence_override']!r}"
                )
    panel_fixtures = _load("panel_parser_fixtures_v1_1.yaml")["fixtures"]
    for f in panel_fixtures:
        conf = (f["expected"].get("panel") or {}).get("confidence")
        if conf is not None:
            assert conf in panel_vocab, f"panel fixture {f['id']}: confidence {conf!r} not in vocab"


# --------------------------------------------------------------------------- #
# Panel parser preserves its stricter model-null rules
# --------------------------------------------------------------------------- #
def test_panel_model_null_rules():
    panel = _load("panel_parser_rules_v1_1.yaml")

    # Ambiguous catalogue entries (with model_options) must keep model null.
    for e in panel["canonical_panels"]:
        if e.get("model_options"):
            assert e.get("model") is None, (
                f"panel {e['canonical_id']} has model_options but model is not null"
            )

    # Brand-only aliases must declare a model-null preserving action (never populate model).
    for ba in panel.get("brand_only_aliases") or []:
        action = str(ba.get("action", ""))
        assert "model_null" in action or "preserve" in action, (
            f"brand_only alias {ba.get('source')!r} action {action!r} does not preserve model-null"
        )

    # Wattage-only policy examples preserve wattage but never guess brand/model.
    for ex in (panel.get("wattage_only_policy") or {}).get("examples") or []:
        assert ex.get("model") is None and ex.get("brand") is None, (
            f"wattage-only example {ex.get('source')!r} must have null brand+model"
        )

    # Fixtures: unconfirmed_raw_text panels and any model_options fixture keep model null.
    for f in _load("panel_parser_fixtures_v1_1.yaml")["fixtures"]:
        p = f["expected"].get("panel") or {}
        if p.get("confidence") == "unconfirmed_raw_text" or p.get("model_options"):
            assert p.get("model") is None, (
                f"panel fixture {f['id']}: model must be null for brand/wattage-only/ambiguous"
            )


# --------------------------------------------------------------------------- #
# parser_rule_version drift is detected/reported (known v8-vs-v9.1 artifact)
# --------------------------------------------------------------------------- #
def test_parser_rule_version_drift_is_pinned_and_reported():
    runtime = _load("hardware_parser_runtime_rules_v9_1.yaml")
    hw_fixtures = _load("hardware_parser_test_fixtures_v9_1.yaml")
    panel = _load("panel_parser_rules_v1_1.yaml")
    panel_fixtures = _load("panel_parser_fixtures_v1_1.yaml")

    # KNOWN versions pinned verbatim. The hardware runtime's output parser_rule_version is
    # "hardware_parser_rules_v8" even though the package is v9.1 — a documented naming DRIFT
    # carried from the curated source. Pinning it here DETECTS any future unexpected change
    # and REPORTS the drift so implementation does not silently rely on a moving version.
    assert runtime["version"] == "hardware_parser_runtime_rules_v9_validation_clean"
    assert runtime["output_shape"]["parser_rule_version"] == "hardware_parser_rules_v8"
    assert runtime["schema_version"] == "hardware_parser_runtime_schema_v8"
    assert hw_fixtures["version"] == "hardware_parser_test_fixtures_v9_validation_clean"
    assert panel["version"] == "panel_rules_v1_1"
    assert panel_fixtures["version"] == "panel_fixtures_v1_1"
    assert panel_fixtures["parser_rule_version"] == "panel_rules_v1_1"

    # The DRIFT itself: hardware runtime output version does not carry the v9 package marker.
    hw_output_version = runtime["output_shape"]["parser_rule_version"]
    assert "v9" not in hw_output_version, (
        "Expected the documented v8-vs-v9.1 hardware parser_rule_version drift; if this "
        "changed, reconcile the version across spec/runtime/fixtures intentionally."
    )


# --------------------------------------------------------------------------- #
# P6b bundle_interpretations: emitted models must exist; ids/match keys unique; confidence in vocab
# --------------------------------------------------------------------------- #
def test_bundle_interpretations_are_valid():
    runtime = _load("hardware_parser_runtime_rules_v9_1.yaml")
    bundles = runtime.get("bundle_interpretations") or []
    if not bundles:
        return
    canon = {
        _norm(e["canonical_model"])
        for e in (runtime["hardware_catalog"] + runtime["metering_catalog"])
        if e.get("canonical_model")
    }
    vocab = set(runtime["confidence_levels"])
    missing, bad_conf = [], []
    for b in bundles:
        for cat in ("inverters", "batteries"):
            for item in b.get(cat) or []:
                if _norm(item["model"]) not in canon:
                    missing.append(f"{b['id']}: {item['model']!r}")
                if item.get("confidence") and item["confidence"] not in vocab:
                    bad_conf.append(f"{b['id']}: {item['confidence']!r}")
        if b.get("confidence") and b["confidence"] not in vocab:
            bad_conf.append(f"{b['id']}: {b['confidence']!r}")
    assert not missing, f"bundle_interpretations reference missing canonical models: {missing}"
    assert not bad_conf, f"bundle_interpretations use confidence not in vocab: {bad_conf}"

    ids = [b["id"] for b in bundles]
    assert len(ids) == len(set(ids)), f"duplicate bundle_interpretation ids: {ids}"
    matches = [_norm(b["match"]) for b in bundles]
    assert len(matches) == len(set(matches)), "duplicate bundle_interpretation match keys"
