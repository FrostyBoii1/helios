"""Versioned hardware-parser RULES config loader (Hardware Parser lane, Stage 4A).

The runtime parser (``app.hardware.runtime``) reads two inputs: the admin-editable DB catalogue
+ aliases (matchable identities) and THIS versioned config — the parser POLICY that the owner
decided stays version-controlled, not admin-editable: normalization/encoding, ignore rules,
specific corrections, global guard phrases, the site-note keyword buckets, panel brand-only /
wattage-only routing, the confidence vocabularies, and the pinned ``parser_rule_version`` strings.

Pure + read-only: loads the tracked YAML from ``docs/parser_specs/hardware/`` (the read-only
container mount, else repo-relative — reusing ``app.hardware.seed.spec_dir``) and caches it. It
NEVER touches the DB, jobs, imports, or the catalogue.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import yaml

from app.hardware.seed import spec_dir

_HARDWARE_RULES = "hardware_parser_runtime_rules_v9_1.yaml"
_PANEL_RULES = "panel_parser_rules_v1_1.yaml"


def _norm(value: Any) -> str:
    """Whitespace-collapse + casefold — the case-insensitive comparison key."""
    return " ".join(str(value).split()).strip().casefold()


@dataclass(frozen=True)
class ParserRules:
    """Parsed, cached view of the versioned parser policy (not admin-editable)."""

    # Encoding replacements applied before matching (e.g. mojibake ``×`` -> ``x``).
    ascii_equivalents: dict[str, str]
    # Whole-string ignore: normalized match text -> reason.
    ignore_rules: dict[str, str]
    # Whole-string manual corrections (override guard phrases): normalized match -> list of
    # canonical model strings to emit (confidence ``manual_correction``).
    specific_corrections: dict[str, list[str]]
    # Guard phrases that suppress model inference unless a specific correction applies.
    guard_phrases: tuple[str, ...]
    # Site-note keyword buckets -> the snapshot site_notes field they populate.
    #   internal_note_fragments.{ct, export_limit, underground, wifi_comms}
    site_note_keywords: dict[str, tuple[str, ...]]  # snapshot-field -> lowercase keywords
    # Panel brand-only shorthands: normalized source -> {brand, confidence?}.
    panel_brand_only: dict[str, dict[str, Any]]
    # Panel values to ignore outright ("-", "/", "N/A", "na").
    panel_strict_ignore: frozenset[str]
    # Confidence vocabularies (for validation / fallback).
    hardware_confidence_vocab: frozenset[str]
    panel_confidence_vocab: frozenset[str]
    # Pinned parser_rule_version strings (owner decision: keep as-is).
    hardware_rule_version: str
    panel_rule_version: str
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def _load(name: str) -> dict[str, Any]:
    return yaml.safe_load((spec_dir() / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_rules() -> ParserRules:
    hw = _load(_HARDWARE_RULES)
    panel = _load(_PANEL_RULES)

    enc = (hw.get("encoding_policy") or {}).get("ascii_safe_equivalents") or {}
    ignore = {_norm(r["match"]): r.get("reason", "") for r in hw.get("ignore_rules") or []}
    corrections = {
        _norm(c["match"]): list(c.get("output") or []) for c in hw.get("specific_corrections") or []
    }
    guards = tuple(_norm(p) for p in (hw.get("global_guard_phrases") or {}).get("phrases") or [])

    frags = hw.get("internal_note_fragments") or {}
    # wifi_comms in the spec maps to the snapshot's `comms` bucket.
    site_keywords = {
        "ct": tuple(k.casefold() for k in frags.get("ct") or []),
        "export_limit": tuple(k.casefold() for k in frags.get("export_limit") or []),
        "underground": tuple(k.casefold() for k in frags.get("underground") or []),
        "comms": tuple(k.casefold() for k in frags.get("wifi_comms") or []),
    }

    brand_only: dict[str, dict[str, Any]] = {}
    for ba in panel.get("brand_only_aliases") or []:
        brand_only[_norm(ba["source"])] = {
            "brand": ba.get("brand"),
            "confidence": ba.get("confidence"),  # e.g. manual_review for risky shorthand
        }
    strict_ignore = frozenset(
        _norm(v) for v in ((panel.get("policy") or {}).get("strict_ignore_values") or [])
    )

    return ParserRules(
        ascii_equivalents=dict(enc),
        ignore_rules=ignore,
        specific_corrections=corrections,
        guard_phrases=guards,
        site_note_keywords=site_keywords,
        panel_brand_only=brand_only,
        panel_strict_ignore=strict_ignore,
        hardware_confidence_vocab=frozenset(hw.get("confidence_levels") or []),
        panel_confidence_vocab=frozenset(panel.get("confidence_levels") or []),
        hardware_rule_version=(hw.get("output_shape") or {}).get(
            "parser_rule_version", "hardware_parser_rules_v8"
        ),
        panel_rule_version=str(panel.get("version", "panel_rules_v1_1")),
        raw={"hardware": hw, "panel": panel},
    )
