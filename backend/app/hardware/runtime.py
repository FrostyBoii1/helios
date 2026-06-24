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

# P2 brand-prefix normalization: known leading brand/manufacturer prefixes the workbook writes in
# front of a BARE catalogue model (the catalogue often stores the bare model — "SH10RT",
# "X1-SMT-10K-G2"). When a fragment does NOT match directly, the brand (and an OPTIONAL single
# leading power token like "10kW") is stripped and the REMAINDER is re-looked-up; a hit is accepted
# ONLY when that remainder is itself a catalogue alias (never a guess). Kept as a small, version-
# controlled CODE constant — deliberately NOT seeded as catalogue aliases (no hundreds of duplicate
# brand-prefixed rows) and NOT added to the vendored v9.1 spec YAML. Casefolded; longest-first at use
# so "solax power" wins over "solax".
_BRAND_PREFIXES = tuple(sorted({
    "alpha ess", "alpha-ess",
    "sungrow",
    "solax power", "solax",
    "saj",
    "goodwe",
    "solis",
    "neovolt", "nevolt",
}, key=len, reverse=True))
# A single leading POWER token ("10kW", "5 kw") — strippable noise between brand and model. It does
# NOT match ENERGY/capacity ("kWh" / "kw hrs": there is no word boundary after "kw"), so battery
# capacity evidence is never consumed by the brand-prefix strip.
_LEADING_POWER_RE = re.compile(r"^\d+(?:\.\d+)?\s*kw\b\s*", re.IGNORECASE)
# A trailing hardware-TYPE noun ("SBR128 BATT", "SH10RT inverter") — descriptive noise after the
# model, not part of it. Requires a leading space so a model ending in "-INV" (e.g.
# "SMILE-G3-B5-INV") is never touched. Only stripped as a normalization retry, re-validated below.
_TRAILING_NOISE_RE = re.compile(r"\s+(?:batteries|battery|batt|inverters?|inv)\.?$", re.IGNORECASE)

# P3 unmatched-fragment routing signals — consulted ONLY after catalogue matching fails, to keep
# battery/metering EVIDENCE out of the inverter bucket. They never infer a catalogue id or model.
# Battery: a "batt"-prefixed word ("batt"/"battery"/"batteries") or a Sungrow "SBR<digit>" shorthand.
_BATTERY_HINT_RE = re.compile(r"\bbatt|\bsbr\d", re.IGNORECASE)
# Metering: a "meter"-prefixed word ("meter"/"metering"/"meters") or "current transformer". A bare
# "CT" is deliberately OMITTED — it stays in site_notes.ct via _site_bucket (unchanged convention).
_METERING_HINT_RE = re.compile(r"\bmeter|current transformer", re.IGNORECASE)


def _hardware_signal(frag: str) -> str | None:
    """Return 'metering' / 'batteries' when a fragment carries clear metering or battery HARDWARE
    language, else None. Conservative: no signal means the caller treats the fragment as an inverter,
    so ambiguous inverter capacity (e.g. 'Solis 5kw', 'Goodwe 10kw') is never mis-routed to a battery
    or meter. Used both to keep such a fragment out of a NON-CT site-note bucket and to bucket an
    unmatched fragment correctly. Never infers a catalogue id."""
    low = frag.casefold()
    if _METERING_HINT_RE.search(low):
        return "metering"
    if _BATTERY_HINT_RE.search(low):
        return "batteries"
    return None


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


def _normalized_hit(core: str, idx: "_Index") -> "_Hit | None":
    """P2 conservative brand/noise normalization for a fragment that did NOT match directly. Tries
    resolving ``core`` after stripping a known leading brand/manufacturer prefix (+ an optional single
    leading power token like "10kW") and/or a trailing hardware-type noun ("... BATT" / "... inverter").
    A hit is returned ONLY when a transformed remainder is ITSELF a catalogue alias — it never guesses,
    and never resolves brand-only or capacity-only text (those produce no resolving candidate). The
    matched alias's confidence / category / provenance are used unchanged by the caller (quantity and
    the original source_fragment stay as-is; model_text becomes the resolved canonical model)."""
    collapsed = _clean(core)
    candidates: list[str] = []

    def _add_brand_strip(s: str) -> None:
        low = s.casefold()
        for brand in _BRAND_PREFIXES:                 # longest-first ("solax power" before "solax")
            if not low.startswith(brand + " "):
                continue
            rem = s[len(brand) + 1:].strip()          # brand names are ASCII -> casefold len matches
            if rem:
                candidates.append(rem)                # "Solax Power X1-SMT-10K-G2" -> "X1-SMT-10K-G2"
                powerless = _LEADING_POWER_RE.sub("", rem, count=1).strip()
                if powerless and powerless != rem:
                    candidates.append(powerless)      # "Sungrow 10kW SH10RT" -> "SH10RT"
            return                                    # brand matched (empty remainder = brand-only)

    _add_brand_strip(collapsed)
    trimmed = _TRAILING_NOISE_RE.sub("", collapsed).strip()
    if trimmed and trimmed != collapsed:
        candidates.append(trimmed)                    # "SBR128 BATT" -> "SBR128"
        _add_brand_strip(trimmed)                     # "Sungrow SH10RT inverter" -> "SH10RT"

    if "(" in collapsed or ")" in collapsed:          # P7: parentheses are formatting noise around a model
        deparen = " ".join(collapsed.replace("(", " ").replace(")", " ").split())
        if deparen and deparen != collapsed:
            candidates.append(deparen)                # "SolaX (X1-SMT-10K-G2)" -> "SolaX X1-SMT-10K-G2"
            _add_brand_strip(deparen)                 # -> "X1-SMT-10K-G2" (hits ONLY if a real alias)

    for cand in candidates:
        hit = idx.exact_ci.get(_key(cand)) or idx.loose_ci.get(_key(cand))
        if hit is not None:
            return hit
    return None


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


def _emit_bundle(bundle: dict, idx: "_Index", rules: ParserRules, *, cleaned: str,
                 source_type: str, source_field: str, out: dict) -> None:
    """Emit a deterministic P6b whole-cell bundle interpretation: each declared inverter / battery
    becomes an item (canonical ``model_text`` + the resolved catalogue id), and each note goes to
    ``site_notes.raw_misc``. The whole cleaned cell is the ``source_fragment``; quantity defaults to 1;
    confidence is the per-item value when given, else the rule's."""
    rule_conf = bundle.get("confidence", "manual_correction")
    for cat in ("inverters", "batteries"):
        for spec in bundle.get(cat) or []:
            model = spec["model"]
            out[cat].append(_item(
                idx.by_model_ci.get(_key(model)), model, quantity=spec.get("quantity", 1),
                confidence=spec.get("confidence") or rule_conf, source_fragment=cleaned,
                source_type=source_type, source_field=source_field, rules=rules))
    for note in bundle.get("notes") or []:
        out["site_notes"].setdefault("raw_misc", []).append(note)


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
    # 2b. P6b deterministic whole-cell bundle interpretation (owner-confirmed shorthand / bundles):
    # an EXACT normalized whole-cell match emits a fixed set of typed inverter/battery items + notes
    # (overrides guard phrases, like a specific correction). Anything not matched falls through.
    bundle = rules.bundle_interpretations.get(whole_key)
    if bundle is not None:
        _emit_bundle(bundle, idx, rules, cleaned=cleaned, source_type=source_type,
                     source_field=source_field, out=out)
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
        # CT always stays site_notes.ct (unchanged). For the other site buckets (export_limit /
        # underground / comms), a fragment that is actually metering/battery HARDWARE (e.g. "smart
        # meter 5kw export") is NOT swallowed as a site note — it falls through to be matched /
        # P3-routed to the metering/battery bucket instead.
        if bucket is not None and (bucket == "ct" or _hardware_signal(frag) is None):
            out["site_notes"].setdefault(bucket, []).append(frag)
            continue
        qty, core = _extract_quantity(frag)
        ckey = _key(core)
        hit = idx.exact_ci.get(fkey) or idx.exact_ci.get(ckey) or idx.loose_ci.get(fkey) or idx.loose_ci.get(ckey)
        if hit is None:
            # Leading bare "N MODEL" quantity (no x/×/* separator), e.g. "1 SBR128 battery" or
            # "2 SBR128 batteries". The quantity is honoured ONLY when the remainder resolves —
            # directly OR via P2 normalization (brand-prefix / trailing hardware-noun) — so a leading
            # number that is actually part of unmatched text ("2 Frobnicator 9000", "40kw hrs") is
            # never mis-split. P5: N == 1 is now included (the remainder must still resolve), so
            # "1 SBR128 battery" -> battery SBR128 qty 1 instead of a raw "1 SBR128 battery" item.
            bqty, bcore = _extract_bare_quantity(frag)
            if bcore != frag:
                bkey = _key(bcore)
                bhit = (idx.exact_ci.get(bkey) or idx.loose_ci.get(bkey)
                        or _normalized_hit(bcore, idx))
                if bhit is not None:
                    qty, core, ckey, hit = bqty, bcore, bkey, bhit
        if hit is None:
            # P2: brand/manufacturer-prefix (+ trailing hardware-noun) normalization. "Sungrow 10kW
            # SH10RT" / "Solax Power X1-SMT-10K-G2" / "SBR128 BATT" carry a known catalogue model behind
            # brand (+ optional power) and/or after a trailing type-noun; strip and resolve the
            # remainder. Accepted ONLY when the remainder is a real catalogue alias (never a guess);
            # brand-only / capacity-only text stays raw. Quantity + the original source_fragment are
            # unchanged; model_text becomes the resolved canonical model.
            nhit = _normalized_hit(core, idx)
            if nhit is not None:
                hit = nhit
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
            # P3: route to the bucket the fragment's language indicates — battery ("12.8kw batt",
            # "1 SBR096 battery") and metering ("export meter") evidence go to their OWN bucket instead
            # of always 'inverters', so a Job never displays a battery or meter as an inverter. Still
            # raw (no canonical id, no model guess); 'inverters' stays the default for text with no
            # strong battery/metering signal (ambiguous inverter capacity like 'Solis 5kw' stays here).
            bucket_key = _hardware_signal(frag) or "inverters"
            out[bucket_key].append(_item(
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


def _aggregate_items(items: list[dict]) -> list[dict]:
    """Quantity aggregation (spec ``aggregation_rules``): items resolving to the SAME catalogue model
    (same ``canonical_hardware_id_at_parse_time``) AND the same ``confidence`` collapse into ONE item
    with the summed quantity, preserving every contributing ``source_fragment``. This is what makes
    "2 × SMILE-BAT-13.3P + extension 13.3p" a single battery of quantity 3. UNMATCHED raw items (no
    canonical id) and items differing in model or confidence are left separate (``do_not_aggregate``);
    first-occurrence order is preserved (``ordering_rules: source_order``)."""
    out: list[dict] = []
    merged_by_key: dict[tuple, dict] = {}
    for it in items:
        cid = it.get("canonical_hardware_id_at_parse_time")
        key = (cid, it.get("confidence")) if cid is not None else None
        if key is not None and key in merged_by_key:
            target = merged_by_key[key]
            target["quantity"] = (target.get("quantity") or 1) + (it.get("quantity") or 1)
            frag = it.get("source_fragment")
            if frag and frag not in (target.get("source_fragment") or ""):
                target["source_fragment"] = f"{target.get('source_fragment', '')} + {frag}".strip(" +")
        else:
            out.append(it)
            if key is not None:
                merged_by_key[key] = it
    return out


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
        # Collapse same-model/same-confidence duplicates into one quantity-summed item.
        for bucket in ("inverters", "batteries", "metering"):
            out[bucket] = _aggregate_items(out[bucket])

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
