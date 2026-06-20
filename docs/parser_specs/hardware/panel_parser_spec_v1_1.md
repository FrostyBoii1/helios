# Hardware Parser Panel Rules v1.1

## Purpose

This package defines the panel-specific parsing rules for Helios.

Panel parsing stays separate from the inverter/battery/meter hardware parser package because panels behave differently:

- panel quantity is already parsed separately;
- wattage is critical;
- brand/model may be partial or implied;
- phase does not apply;
- system-size maths may be needed to derive the actual panel wattage/model;
- sheet data is not fully trusted and proposal/NAS evidence may be more authoritative.

The goal is conservative classification with aggressive evidence preservation.

## Core Rules

- Panel quantity is already parsed separately.
- Do not build quantity extraction into this panel parser pass.
- Brand is optional evidence, not mandatory truth.
- `model` must only contain an actual catalogue model.
- If the real model cannot be confidently determined, `model` must be null.
- Do not put raw source text into `model`.
- Source fragments must be preserved.
- Panel fields are editable textboxes, not locked dropdowns.
- Parser-owned values must not overwrite manual staff edits without explicit confirmation.
- Sheet data is imported evidence, not guaranteed truth.
- Proposal/NAS evidence is more authoritative when available.

## Output Shape

```yaml
panel:
  quantity: existing_quantity_value
  brand: optional
  display_name: editable job-facing name
  model: actual_catalogue_model_or_null
  model_options: optional list of possible catalogue models when exact model is ambiguous
  canonical_id: optional
  wattage_w: optional
  panel_array_kw: optional
  confidence: exact | alias | derived_from_system_size | proposal_overrode_sheet | unconfirmed_raw_text | manual_review
  parser_owned: true
  source_fragment: original matched source text
  parser_rule_version: panel_rules_v1
```

## Brand-Only Source Rule

If the source only gives a brand or vague panel text, do not place that raw text into `model`.

Correct example:

```yaml
source: "Longi"
result:
  brand: "LONGi Solar"
  display_name: "Longi"
  model: null
  wattage_w: null
  confidence: unconfirmed_raw_text
  parser_owned: true
  source_fragment: "Longi"
```

## Wattage Derivation Rule

Wattage is the primary way to determine the actual panel model.

Future NAS/proposal parsing should derive wattage using:

```text
system_size_kw / panel_quantity * 1000 = panel_wattage_w
```

Example:

```text
13.20kW / 30 panels = 440W panels
```

Allow a tolerance of plus or minus 2W.

If the derived wattage is within +/-2W of a catalogue wattage, it may match.

If outside tolerance, flag for manual review.

## Panel Array kW Rule

Every job with parsed panels should calculate and display total panel kW when both quantity and wattage are known:

```text
panel_quantity * wattage_w / 1000 = panel_array_kw
```

Example:

```text
30 * 440W = 13.20kW
```

## Ignore vs Preserve Rules

### Strict Ignore Values

These values contain no useful hardware, operational, or review information and may be discarded during panel parsing:

```text
-
/
N/A
na
```

These should not create hardware, notes, warnings, or review items.

### Non-Panel / Ambiguous Values

These values must not become panel aliases and must not automatically resolve to panel hardware:

```text
AE 440 or TW
TO AE PANELS
3 x tigo Optimisers
Ben installed
2 x batteries
ALPHA ESS 10KW
Alpha ESS SMILE-BAT-13.3P
```

Parser behaviour:

- Do not create panel hardware.
- Do not create panel aliases.
- Do not attempt wattage derivation.
- Do not map to a panel model.

Instead:

- Preserve the original source fragment.
- Route the value explicitly where possible.
- Allow future parsers to consume the information if relevant.

Valid routed destinations:

```text
internal_note
review_evidence
accessory_hardware_candidate
battery_hardware_candidate
optimiser_candidate
manual_review
```

Do not silently drop anything unless it is in Strict Ignore Values.

## Stable Catalogue IDs

Every canonical panel should have a stable ID.

Example:

```yaml
canonical_id: panel_longi_lr5_54hth_440m
brand: LONGi Solar
display_name: 440W LONGi Solar
model: LR5-54HTH-440M
wattage_w: 440
hardware_type: panel
```

## Case-Sensitive Alias Rule

Some aliases cannot be normalised blindly.

`Jinko 440` and `JINKO 440` intentionally resolve to different model values. Do not collapse them unless later corrected.

## Conflict Behaviour

If sheet data and proposal/NAS data conflict, proposal/NAS wins.

The sheet value must still be preserved for audit/debugging.

## NAS Parser Footprint

Future NAS/proposal parser must support:

1. Reading explicit panel brand/model/wattage from proposals.
2. Reading total system size.
3. Reading already-known panel quantity.
4. Deriving wattage from system size and quantity.
5. Using derived wattage + brand to select the panel model where safe.
6. Flagging model ambiguity for review when multiple real panel models share the same shorthand.
7. Preserving sheet source fragments even when proposal/NAS overrides them.
8. Flagging unrecognised proposal/NAS panel model numbers for review so new models can be added safely.

## Implementation Boundary

Panel parsing should be a separate module/config:

```text
panel_parser_rules_v1_1.yaml
panel_parser_fixtures_v1_1.yaml
panel_parser_decision_log_v1_1.md
```

The existing v9.1 hardware parser package remains the core inverter/battery/meter package.


## v1.1 Tightening Notes

### Confidence vs Routed Destination

Confidence describes parsing certainty, not the type/category of the routed value.

Do not use values such as `accessory_hardware` as confidence levels.

Use:

```yaml
confidence: manual_review
routed_destination: optimiser_candidate
```

not:

```yaml
confidence: accessory_hardware
```

### Ambiguous Model Options

If a sheet alias maps to multiple possible real panel models, do not store a comma-separated list inside `model`.

Use:

```yaml
model: null
model_options:
  - STP415S-78H/Vfh
  - Ultra V mini STP415S-C54/Umhm
requires_model_precision_review: true
```

This keeps `model` reserved for a single actual catalogue model.

### Unknown Wattage-Only Values

If the source gives wattage but no brand/model, preserve the wattage but do not guess the brand.

Example:

```yaml
source: "440W panels"
result:
  brand: null
  display_name: "440W panels"
  model: null
  canonical_id: null
  wattage_w: 440
  confidence: unconfirmed_raw_text
  source_fragment: "440W panels"
```

### TW Brand-Only Safety

The alias `TW` is short and risky.

`TW 440`, `TW 465`, and `TW Solar 465` may resolve when wattage is present.

A standalone `TW` should be preserved as brand evidence only and should not resolve to a model unless wattage/system-size evidence confirms the panel.
