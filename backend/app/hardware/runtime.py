"""Hardware parser RUNTIME (Hardware Parser lane, Stage 4A) — the catalogue-consuming matcher.

A standalone, READ-ONLY service: given hardware text fragments + source metadata, it reads the
admin-editable DB catalogue + aliases and the versioned policy config (``app.hardware.rules``)
and produces a ``JobHardwarePatch``-valid hardware snapshot. It is the "parser brain" proven in
isolation BEFORE any import wiring.

Guarantees (Stage 4A scope):
  * NEVER mutates the catalogue / aliases / jobs / imports — it only reads.
  * NEVER matches ``source_examples`` (they are not seeded as aliases, so they cannot match).
  * NEVER guesses an unknown model — unmatched useful text is preserved as editable raw text
    (``model_text`` with ``unconfirmed_raw_text`` confidence) plus a review warning.
  * Panels keep ``model: null`` unless a real catalogue model is confidently identified; ambiguous
    panels carry ``model_options``; brand-only / wattage-only preserve text without guessing.
  * Output is validated against ``JobHardwarePatch`` (extra='forbid') before returning, so it can
    only ever emit a snapshot the Job-details patch will accept.

Source-agnostic: inputs are plain strings + ``source_type`` / ``source_field`` metadata (not
completed-sheet column assumptions), so a future NAS / proposal / manual source reuses it. NOT
wired into import ingest / preview / commit in this stage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.hardware.rules import ParserRules, load_rules
from app.models.enums import HardwareAliasType, HardwareCategory
from app.models.hardware import HardwareAlias, HardwareCatalogue
from app.schemas.job_hardware import JobHardwarePatch

_HW_CATEGORIES = {HardwareCategory.INVERTER.value, HardwareCategory.BATTERY.value,
                  HardwareCategory.METERING.value}
_BUCKET_BY_CATEGORY = {
    HardwareCategory.INVERTER.value: "inverters",
    HardwareCategory.BATTERY.value: "batteries",
    HardwareCategory.METERING.value: "metering",
}
# Explicit quantity prefix: "N x MODEL" / "N × MODEL" / "N*MODEL" (an x / × / * separator with
# optional surrounding spaces). The leading digits + separator are a strong quantity signal.
_QTY_RE = re.compile(r"^\s*(\d+)\s*[x×*]\s*(.*\S)\s*$", re.IGNORECASE)
# Bare "N MODEL" quantity (digits + whitespace + remainder, no x/×/* separator). Honoured ONLY
# when the stripped remainder resolves to a catalogue hit (see the matcher) — so ambiguous unit /
# capacity text ("40kw hrs", "10kw 3 phase") can never be mis-split into a quantity.
_BARE_QTY_RE = re.compile(r"^\s*(\d+)\s+(.*\S)\s*$")
# Battery ENERGY-capacity evidence ("40kw hrs", "40kwh", "20 kWh", "30kw hr") — preserved as a
# hardware note, NEVER attached to an inverter/battery model_text. Bare "kw" (inverter POWER, no
# "h") is intentionally NOT matched.
_CAPACITY_RE = re.compile(r"^\s*\d+(?:\.\d+)?\s*kw\s*h(?:rs?|ours?)?\s*$", re.IGNORECASE)
_WATTAGE_RE = re.compile(r"(\d{3,4})\s*w\b", re.IGNORECASE)


def _clean(text: str) -> str:
    """Whitespace-collapse, case preserved (the case-sensitive comparison form)."""
    return " ".join(str(text).split()).strip()


def _key(text: str) -> str:
    """Case-insensitive comparison key."""
    return _clean(text).casefold()


def _normalize_encoding(text: str, rules: ParserRules) -> str:
    out = text
    for bad, good in rules.ascii_equivalents.items():
        out = out.replace(bad, good)
    return out


@dataclass(frozen=True)
class _Entry:
    id: int
    category: str
    canonical_model: str | None
    display_name: str | None
    brand: str | None
    wattage_w: int | None
    model_options: list | None
    attributes: dict | None


@dataclass(frozen=True)
class _Hit:
    entry: _Entry
    alias_type: str
    confidence_override: str | None


class _Index:
    """Alias lookup maps built once from the DB (read-only)."""

    def __init__(self, db: Session) -> None:
        self.exact_ci: dict[str, _Hit] = {}
        self.loose_ci: dict[str, _Hit] = {}
        self.case_sensitive: dict[str, _Hit] = {}
        self.by_model_ci: dict[str, _Entry] = {}
        rows = db.execute(
            select(HardwareAlias, HardwareCatalogue)
            .join(HardwareCatalogue, HardwareAlias.hardware_id == HardwareCatalogue.id)
            .where(HardwareAlias.deleted_at.is_(None), HardwareCatalogue.deleted_at.is_(None))
        ).all()
        for alias, cat in rows:
            entry = _Entry(
                id=cat.id, category=cat.category, canonical_model=cat.canonical_model,
                display_name=cat.display_name, brand=cat.brand,
                wattage_w=cat.wattage_w, model_options=cat.model_options, attributes=cat.attributes,
            )
            if cat.canonical_model:
                self.by_model_ci.setdefault(_key(cat.canonical_model), entry)
            hit = _Hit(entry=entry, alias_type=alias.alias_type, confidence_override=alias.confidence_override)
            if alias.alias_type == HardwareAliasType.EXACT.value:
                self.exact_ci.setdefault(_key(alias.alias), hit)
            elif alias.alias_type == HardwareAliasType.LOOSE.value:
                self.loose_ci.setdefault(_key(alias.alias), hit)
            elif alias.alias_type == HardwareAliasType.CASE_SENSITIVE.value:
                self.case_sensitive.setdefault(_clean(alias.alias), hit)


def _confidence(hit: _Hit) -> str:
    if hit.confidence_override:
        return hit.confidence_override
    if hit.entry.category == HardwareCategory.PANEL.value:
        return "alias"
    conf = (hit.entry.attributes or {}).get("confidence") or {}
    if hit.alias_type == HardwareAliasType.LOOSE.value:
        return conf.get("loose", "unconfirmed_raw_text")
    return conf.get("exact", "exact")


def _negative_match(entry: _Entry, fragment_key: str) -> bool:
    for pat in (entry.attributes or {}).get("negative_patterns") or []:
        if str(pat).casefold() in fragment_key:
            return True
    return False


def _extract_quantity(fragment: str) -> tuple[int, str]:
    """Pull a leading ``N x`` / ``N ×`` / ``N*`` quantity; return (qty, remainder)."""
    m = _QTY_RE.match(fragment)
    if m:
        return int(m.group(1)), m.group(2)
    return 1, fragment


def _extract_bare_quantity(fragment: str) -> tuple[int, str]:
    """Pull a leading bare ``N MODEL`` quantity (no x/×/* separator); return (qty, remainder).
    The caller MUST only honour this when the remainder resolves to a catalogue hit."""
    m = _BARE_QTY_RE.match(fragment)
    if m:
        return int(m.group(1)), m.group(2)
    return 1, fragment


def _site_bucket(fragment_key: str, rules: ParserRules) -> str | None:
    for bucket, keywords in rules.site_note_keywords.items():
        for kw in keywords:
            if kw and kw in fragment_key:
                return bucket
    return None


def _item(entry: _Entry | None, model_text: str | None, *, quantity: int, confidence: str,
          source_fragment: str, source_type: str, source_field: str, rules: ParserRules) -> dict:
    return {
        "model_text": model_text,
        "quantity": quantity,
        "confidence": confidence,
        "parser_owned": True,
        "source_fragment": source_fragment,
        "source_type": source_type,
        "source_field": source_field,
        "canonical_hardware_id_at_parse_time": entry.id if entry else None,
        "parser_rule_version": rules.hardware_rule_version,
    }


def _parse_hardware_cell(
    text: str, idx: _Index, rules: ParserRules, *, source_type: str, source_field: str,
    out: dict, warnings: list[str],
) -> None:
    """Parse the inverter/battery/metering hardware cell into out['inverters'|'batteries'|
    'metering'] + out['site_notes']. Never guesses; preserves unmatched useful text."""
    cleaned = _clean(_normalize_encoding(text, rules))
    if not cleaned:
        return
    whole_key = _key(cleaned)

    # 1. Whole-string ignore rule.
    if whole_key in rules.ignore_rules:
        return
    # 2. Whole-string specific correction (overrides guard phrases).
    if whole_key in rules.specific_corrections:
        for model in rules.specific_corrections[whole_key]:
            entry = idx.by_model_ci.get(_key(model))
            out["inverters"].append(_item(
                entry, model, quantity=1, confidence="manual_correction",
                source_fragment=cleaned, source_type=source_type, source_field=source_field,
                rules=rules))
        return
    # 3. Guard phrases (no correction matched) — preserve, do NOT infer a model.
    if any(g in whole_key for g in rules.guard_phrases):
        out["inverters"].append(_item(
            None, cleaned, quantity=1, confidence="manual_review",
            source_fragment=cleaned, source_type=source_type, source_field=source_field, rules=rules))
        warnings.append(f"Guarded hardware text preserved for manual review (not inferred): {cleaned!r}")
        return

    # 4. Fragment-by-fragment matching.
    for frag in _split_fragments(cleaned):
        fkey = _key(frag)
        if not fkey:
            continue
        bucket = _site_bucket(fkey, rules)
        if bucket is not None:
            out["site_notes"].setdefault(bucket, []).append(frag)
            continue
        qty, core = _extract_quantity(frag)
        ckey = _key(core)
        hit = idx.exact_ci.get(fkey) or idx.exact_ci.get(ckey) or idx.loose_ci.get(fkey) or idx.loose_ci.get(ckey)
        if hit is None:
            # Bare "N MODEL" quantity — honoured ONLY when the stripped model resolves (safe:
            # unit / capacity text like "40kw hrs" never resolves, so it cannot be mis-split).
            bqty, bcore = _extract_bare_quantity(frag)
            if bqty != 1:
                bkey = _key(bcore)
                bhit = idx.exact_ci.get(bkey) or idx.loose_ci.get(bkey)
                if bhit is not None:
                    qty, core, ckey, hit = bqty, bcore, bkey, bhit
        if hit and hit.entry.category in _HW_CATEGORIES and not _negative_match(hit.entry, fkey):
            bucket_key = _BUCKET_BY_CATEGORY[hit.entry.category]
            out[bucket_key].append(_item(
                hit.entry, hit.entry.canonical_model, quantity=qty, confidence=_confidence(hit),
                source_fragment=frag, source_type=source_type, source_field=source_field, rules=rules))
        elif _CAPACITY_RE.match(core):
            # Battery capacity evidence (kWh / kw hrs) — preserve as a hardware note, NEVER a model
            # and NEVER appended to the inverter/battery model_text.
            out["site_notes"].setdefault("raw_misc", []).append(frag)
        else:
            # Unmatched useful text — preserve the model CORE as editable raw text with the quantity
            # stored separately (so an explicit quantity is shown once, never doubled into the text).
            out["inverters"].append(_item(
                None, core, quantity=qty, confidence="unconfirmed_raw_text",
                source_fragment=frag, source_type=source_type, source_field=source_field, rules=rules))
            warnings.append(f"Unmatched hardware preserved as raw text: {frag!r}")


# Top-level separators that combine component fragments in a hardware cell. Stage 4A split only on
# "+" and a SPACED " - "; P1 adds "/", "·", "•", "&", and the whole words "and" / "with" — the
# joiners the real workbook uses for inverter/battery/metering/capacity bundles. Each is chosen so
# it cannot occur INSIDE a catalogue model: a model-internal hyphen is never space-padded (so
# "X1-BOOST-5K-G4" survives — only a spaced " - " splits), and "/", "•", "&", "and", "with" appear
# in no inverter/battery/metering model. ("·" is included for safety but is normally rewritten to
# "-" by _normalize_encoding before this runs, so a "MODEL · 25kWh" cell already splits via the
# spaced-hyphen rule.) Panel parsing never uses this splitter.
_FRAGMENT_SPLIT_RE = re.compile(
    r"\s*\+\s*"          # "+"
    r"|\s+-\s+"          # spaced hyphen (never a model-internal hyphen)
    r"|\s*[/·•&]\s*"     # slash / middot / bullet / ampersand
    r"|\s+and\s+"        # the word "and"
    r"|\s+with\s+",      # the word "with"
    re.IGNORECASE,
)


def _split_fragments(text: str) -> list[str]:
    """Split a combined hardware cell into component fragments on the model-safe top-level
    separators in ``_FRAGMENT_SPLIT_RE``. Each fragment is resolved independently by the caller, so
    a bundle like "INV / 2 x BATT · 25kWh" yields the inverter, the qty-2 battery and the capacity
    note instead of one raw blob. (P1; multi-fragment capacity-in-noun extraction is a follow-up.)"""
    parts = _FRAGMENT_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p and p.strip()]


def _extract_wattage(text: str) -> int | None:
    m = _WATTAGE_RE.search(text)
    return int(m.group(1)) if m else None


def _parse_panel_cell(
    text: str, idx: _Index, rules: ParserRules, *, quantity_hint: int | None,
    warnings: list[str],
) -> dict | None:
    """Parse the panel cell. model stays null unless a real catalogue model is confidently
    identified; ambiguous -> model_options; brand-only / wattage-only preserve text."""
    cleaned = _clean(_normalize_encoding(text, rules))
    if not cleaned or _key(cleaned) in rules.panel_strict_ignore:
        return None

    hit = idx.case_sensitive.get(cleaned) or idx.exact_ci.get(_key(cleaned))
    if hit and hit.entry.category == HardwareCategory.PANEL.value:
        e = hit.entry
        panel = _panel_base(quantity_hint, source_fragment=cleaned, rules=rules)
        panel.update({
            "brand": e.brand,
            "display_name": e.display_name,
            "model": e.canonical_model,            # null for an ambiguous catalogue panel
            "model_options": e.model_options or None,
            "wattage_w": e.wattage_w,
            "confidence": _confidence(hit),
            "canonical_hardware_id_at_parse_time": e.id,
        })
        if quantity_hint and e.wattage_w:
            panel["panel_array_kw"] = round(quantity_hint * e.wattage_w / 1000, 2)
        if e.canonical_model is None:
            warnings.append(f"Ambiguous panel {cleaned!r} — model left null with model_options for review.")
        return panel

    # Brand-only shorthand (versioned config) — preserve brand, model null.
    ba = rules.panel_brand_only.get(_key(cleaned))
    if ba is not None:
        warnings.append("Brand-only panel source could not be resolved without wattage or system-size evidence.")
        panel = _panel_base(quantity_hint, source_fragment=cleaned, rules=rules)
        panel.update({"brand": ba.get("brand"), "display_name": cleaned, "model": None,
                      "confidence": ba.get("confidence") or "unconfirmed_raw_text"})
        return panel

    # Wattage-only — preserve wattage, never guess brand/model.
    wattage = _extract_wattage(cleaned)
    if wattage is not None:
        panel = _panel_base(quantity_hint, source_fragment=cleaned, rules=rules)
        panel.update({"display_name": cleaned, "model": None, "wattage_w": wattage,
                      "confidence": "unconfirmed_raw_text"})
        return panel

    # Otherwise preserve as raw text — NEVER guess the closest model.
    warnings.append(f"Panel source preserved as raw text (not resolved to a catalogue model): {cleaned!r}")
    panel = _panel_base(quantity_hint, source_fragment=cleaned, rules=rules)
    panel.update({"display_name": cleaned, "model": None, "confidence": "unconfirmed_raw_text"})
    return panel


def _panel_base(quantity_hint: int | None, *, source_fragment: str, rules: ParserRules) -> dict:
    return {
        "quantity": quantity_hint,
        "parser_owned": True,
        "source_fragment": source_fragment,
        "parser_rule_version": rules.panel_rule_version,
    }


def parse_hardware(
    db: Session,
    *,
    inverter_text: str | None = None,
    panel_text: str | None = None,
    quantity_hint: int | None = None,
    source_type: str = "workbook",
    source_field: str = "hardware",
) -> dict:
    """Parse hardware text into a ``JobHardwarePatch``-valid snapshot dict (validated before
    return). READ-ONLY: reads the DB catalogue/aliases + versioned rules; mutates nothing.

    ``inverter_text`` is the inverter/battery/metering hardware cell; ``panel_text`` is the panel
    cell (parsed by the stricter panel rules); ``quantity_hint`` is the already-parsed panel count.
    """
    rules = load_rules()
    idx = _Index(db)
    warnings: list[str] = []
    out: dict = {"inverters": [], "batteries": [], "metering": [], "site_notes": {}}

    if inverter_text and inverter_text.strip():
        _parse_hardware_cell(
            inverter_text, idx, rules, source_type=source_type, source_field=source_field,
            out=out, warnings=warnings)

    panel = None
    if panel_text and panel_text.strip():
        panel = _parse_panel_cell(
            panel_text, idx, rules, quantity_hint=quantity_hint, warnings=warnings)

    snapshot: dict = {
        "inverters": out["inverters"],
        "batteries": out["batteries"],
        "metering": out["metering"],
        "site_notes": out["site_notes"] or None,
        "warnings": warnings or None,
    }
    if panel is not None:
        snapshot["panel"] = panel

    # Adapter: validate against the Job snapshot schema (extra='forbid') and emit a clean dict.
    return JobHardwarePatch.model_validate(snapshot).model_dump(exclude_none=True)
