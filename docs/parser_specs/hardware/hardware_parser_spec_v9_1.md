# Hardware Parser Implementation Spec v9.1

Source basis: `Inverters(1).txt`, the v5/v6 parser maps, the v1 runtime YAML, and manual corrections supplied during the parser design pass.

This file is the human implementation spec. It is **not** the only runtime source. The parser should load the machine-readable runtime config from `hardware_parser_runtime_rules_v9_1.yaml` and prove behaviour with `hardware_parser_test_fixtures_v9_1.yaml`.

## v9.1 Purpose

v9.1 keeps the parser package from a planning artefact into a safer implementation source.

The package remains separated into:

1. **Canonical hardware catalogue** — actual hardware models and safe aliases/fragments.
2. **Runtime parser rules** — machine-readable extraction rules.
3. **Source examples** — evidence only, not aliases.
4. **Test fixtures** — full raw workbook strings with expected parsed output.
5. **Decision log** — owner-approved weird mappings, ignore rules, and manual corrections.

## Hard Rule: Source Examples Are Not Aliases

`source_examples` must not be used as parser aliases.

They are evidence strings from the workbook. Many contain bundles, notes, meters, batteries, quantities, export limits, WiFi/comms, or other fragments.

Example:

```text
Alpha ESS SMILE5-INV + 2 x Alpha ESS battery + meter
```

This is not a simple alias for one inverter. It must be treated as a raw fixture-style input that may parse into:

```yaml
inverters: []
batteries: []
metering: []
site_notes: []
```

Only strings listed under `exact_aliases` or `loose_aliases` may be used as aliases.

## CRM Hardware Database Concept

The hardware database is the source of truth. The parser is only a translator.

The CRM should have a maintainable hardware catalogue that can be updated without code changes. The parser rules should be treated as a live-update configuration file, not hard-coded parser logic.

Recommended database shape:

```yaml
hardware_catalogue:
  id: uuid
  manufacturer: SolaX
  model: X1-SMT-10K-G2
  category: inverter
  phases: single_phase
  nominal_kw: 10
  capacity_kwh: null
  active: true
  created_at: timestamp
  updated_at: timestamp
```

Recommended parser alias shape:

```yaml
hardware_parser_alias:
  id: uuid
  hardware_id: uuid
  alias: Solax 10kw
  alias_type: loose
  confidence: unconfirmed_raw_text
  parser_rule_version: hardware_parser_rules_v9_1
  active: true
```

The Markdown/spec remains the human working map. The YAML/config is the runtime source. The CRM should allow adding new hardware and aliases over time, then updating the parser config/version.

## Hardware Fields Are Editable Textboxes

Hardware fields in the CRM are **manual editable textboxes**, not fixed dropdowns.

The parser can seed blank fields and update parser-owned fields. It must not overwrite manually edited hardware fields unless a user explicitly confirms the overwrite.

Each parsed hardware item must preserve:

```yaml
model:
quantity:
confidence:
parser_owned:
source_fragment:
```

`source_fragment` is mandatory. It is the exact portion of the source string that created the parsed item after encoding normalisation.

## Unknown / Vague Hardware Rule

If the parser cannot confidently resolve a hardware fragment to a known canonical model, it must not invent a model and must not choose the closest match.

Instead:

1. Put the exact relevant unmatched hardware fragment into the appropriate editable hardware textbox.
2. Set `confidence: unconfirmed_raw_text` or `manual_review`.
3. Set `parser_owned: true`.
4. Preserve the source fragment.
5. Continue scanning the rest of the source string for metering, CT, export limits, underground, WiFi/comms, batteries, and quantities.

Example:

```text
Unknown Brand HyperBattery 12.5 + meter
```

Expected:

```yaml
batteries:
  - model: Unknown Brand HyperBattery 12.5
    quantity: 1
    confidence: unconfirmed_raw_text
    parser_owned: true
    source_fragment: Unknown Brand HyperBattery 12.5
metering:
  - model: Meter
    quantity: 1
    confidence: exact
    parser_owned: true
    source_fragment: meter
```

## Confidence Levels

Use these exact confidence values:

- `exact` — exact canonical model or exact alias match.
- `alias` — safe known alias match.
- `inferred_from_capacity` — model inferred from a capacity pattern that is safe enough to map, such as known battery capacity mapping.
- `unconfirmed_raw_text` — preserved source text because the parser cannot safely resolve it.
- `manual_review` — known risky or unresolved source text requiring staff attention.
- `manual_correction` — owner-approved correction from the decision log.

Loose aliases should be used carefully. Phrases like `Solax 5kw` or `Sungrow 5kw` can be ambiguous and should only produce a canonical model when the runtime rule explicitly says it is safe. Otherwise preserve the raw text.

## Encoding Normalisation

Normalise encoding before parsing.

Required replacements:

```yaml
×: ×
·: ·
```

ASCII-safe equivalents may be used internally:

```yaml
×: x
·: -
```

Runtime rule files should be cleaned. Broken mojibake should only appear in test fixtures where intentionally testing dirty input.

## Parser Priority Order

1. Preserve original raw evidence.
2. Normalise text encoding.
3. Extract quantities.
4. Apply decision-log manual corrections and ignore rules.
5. Extract batteries and battery quantities.
6. Extract metering.
7. Extract site/internal-note fragments: CT, export limits, underground, WiFi/comms/accessories.
8. Extract inverter models.
9. Preserve unresolved hardware fragments into editable hardware textboxes.
10. Attach confidence, parser ownership, source fragments, warnings, and parser rule version.
11. Store raw evidence and normalised evidence.

## Structured Site Notes

Internally, keep notes structured:

```yaml
site_notes:
  ct: []
  export_limit: []
  underground: []
  comms: []
  raw_misc: []
```

The UI may display these as normal Job Internal Notes, but the parser should keep structure internally.

Examples:

```yaml
raw: Goodwe 8kw + smart meter 5kw export
metering:
  - model: Smart Meter
site_notes:
  export_limit:
    - 5kw export
job_internal_notes_display:
  - smart meter 5kw export
```

CT is not hardware for v1. CT fragments go to `site_notes.ct` and may display in Job Internal Notes.

WiFi/comms/logger/stick wording is not classified as hardware for v1. It goes to `site_notes.comms`.

Underground goes to `site_notes.underground`.

Export limits go to `site_notes.export_limit`.

## Metering Labels

Metering labels supported in v8:

- `Meter`
- `Smart Meter`
- `3P Meter`
- `2P Meter`
- `ALPHA Meter`
- `Chint Meter`
- `Backstop Meter`

Metering must not be baked into inverter or battery model labels.

## Quantity Rule

Quantity is a field, not part of the model name.

Correct:

```yaml
model: X1-BOOST-5K-G4
quantity: 2
```

Wrong:

```yaml
model: 2 x X1-BOOST-5K-G4
```

Supported quantity patterns include `2 x`, `2 ×`, `x 2`, `1 x`, and `1 ×`.

## Bundle Rule

A single raw source string can produce multiple parsed hardware records.

Example:

```text
Solax 5kw Hybrid/5kw normal + 25kw batt
```

Expected:

```yaml
inverters:
  - model: X1-HYBRID-5.0-D-G4
  - model: X1-BOOST-5K-G4
batteries:
  - model: 25kw batt
    confidence: unconfirmed_raw_text
```

Full bundle strings belong in test fixtures, not simple alias lists.

## Guard Phrases / Negative Patterns

Guard phrases must be handled before normal alias matching:

- `used`
- `reusing`
- `old`
- `existing`
- `going back on`
- `customer supplied`
- `install only`
- `changed to`
- `now`
- `n/a`
- `electrical work`

These phrases can radically change meaning. Some are ignore rules. Some are owner-approved manual corrections. Some require review. The decision log is authoritative for these cases.

## Workflow Boundary

The hardware parser must not create workflow labels, approval statuses, tasks, or decommissioning decisions.

The hardware parser extracts hardware and hardware-adjacent notes only.

Separate workflow logic may later consume parsed hardware and notes to create labels/tasks, but that is outside this parser.

## Manual Edit / Reparse Rules

The parser may:

- Seed blank hardware fields.
- Update parser-owned fields on reparse.
- Preserve raw evidence and normalised evidence.

The parser may not:

- Overwrite manually edited hardware without explicit confirmation.
- Delete staff-entered hardware notes without confirmation.
- Replace unconfirmed raw text with a guessed model.

## Runtime YAML Validation

`hardware_parser_runtime_rules_v9_1.yaml` must validate before the parser starts.

Validation should check:

- Unique hardware IDs.
- Unique canonical model/category combinations unless intentionally allowed.
- All aliases are strings.
- `source_examples` are not loaded as aliases.
- No mojibake in runtime strings unless explicitly allowed.
- Every hardware catalogue entry has category, canonical model, manufacturer, confidence rules, and alias arrays.

## Acceptance Gates

Implementation is not complete unless all gates pass:

1. Runtime YAML validates.
2. Every fixture in `hardware_parser_test_fixtures_v9_1.yaml` passes.
3. Unknown hardware is preserved, not guessed.
4. Manual edits are not overwritten.
5. Parser rule version is stored on each parsed job.
6. Every parsed item preserves `source_fragment`.
7. `source_examples` are not used as aliases.
8. CT/export/underground/WiFi are routed to structured site notes.
9. Hardware parser does not create workflow labels/tasks.
10. Full backend test suite is green.

## Files in v8 Package

- `hardware_parser_spec_v8.md`
- `hardware_parser_runtime_rules_v9_1.yaml`
- `hardware_parser_test_fixtures_v9_1.yaml`
- `hardware_parser_decision_log_v8.md`
- `hardware_parser_implementation_package_v8.zip`


---

# v8 Hardening Addendum

## 1. Source Examples Are Evidence Only

`source_examples` must never be loaded into the runtime alias matcher. They are retained as evidence and fixture candidates only. A source example only becomes matchable after it is deliberately promoted into `exact_aliases` or `loose_aliases`.

This prevents full workbook bundle strings from being treated as if they equal one inverter or one battery.

## 2. Full Expected Output Shape Is Mandatory

Every parser fixture must include the complete output shape:

```yaml
expected:
  inverters: []
  batteries: []
  metering: []
  site_notes:
    ct: []
    export_limit: []
    underground: []
    comms: []
    raw_misc: []
  job_internal_notes_display: []
  ignored: false
  warnings: []
```

Omitted fields are not allowed in v8 fixtures.

## 3. Required Fields On Every Parsed Hardware Item

Every parsed inverter, battery, and meter item must include:

```yaml
model:
quantity:
confidence:
parser_owned:
source_fragment:
source_type:
source_field:
```

`source_fragment` is mandatory because it is the quickest way to debug bad parsing.

## 4. Ambiguous Hardware Is Preserved As Raw Text

If a source fragment could validly refer to multiple actual models, do not guess. Preserve the source fragment in the relevant editable hardware textbox.

Example:

```text
Solax 5kw
```

Must parse as:

```yaml
inverters:
  - model: Solax 5kw
    quantity: 1
    confidence: unconfirmed_raw_text
    parser_owned: true
    source_fragment: Solax 5kw
```

It must not silently become `X1-BOOST-5K-G4`, because it could also mean `X1-SMT-5K-G2` or `X1-HYBRID-5.0-D-G4`.

The parser should still scan the same source string for known batteries, metering, CT, export limits, underground references, WiFi/comms, and other supported note fragments.

## 5. Alias Collision Validation

Before implementation is accepted:

- no `exact_alias` may map to two different canonical models
- no `loose_alias` may map to two different canonical models unless intentionally marked ambiguous/manual-review
- no `source_examples` may be loaded into the alias matcher
- every `specific_correction.output` must point to a real canonical model or a deliberate raw/manual-review output
- every catalogue ID must be unique

Any collision blocks implementation until fixed.

## 6. Aggregation Rules

If the same canonical model is parsed more than once with the same confidence and same source class, aggregate it into one output item with quantity summed. Preserve all contributing source fragments.

Do not aggregate different models, different confidence levels, or materially different source fragments.

## 7. Ordering Rules

Output order must be stable:

1. inverters in source order
2. batteries in source order
3. metering in source order
4. site notes in source order within each note bucket

Stable ordering avoids flaky fixtures and unstable UI diffs.

## 8. Hardware Database Scope Boundary

The CRM hardware database is the long-term source of truth, but v1 may load hardware rules from YAML. Do not build a full editable hardware-catalogue UI/database unless explicitly scoped.

The hardware textboxes in the CRM are manually editable text fields, not locked dropdowns. Parser-owned fields may be seeded or refreshed, but manual staff edits must not be overwritten without explicit confirmation.

## 9. Workflow Boundary

The hardware parser extracts hardware and hardware-adjacent notes only. It must not infer workflow labels, approval status, decommissioning tasks, admin work, or operational tasks. Separate workflow rules may consume parsed hardware later.

## 10. Acceptance Gates

Implementation is not complete until:

- runtime YAML parses
- runtime schema validates
- catalogue IDs are unique
- aliases are collision-checked
- `source_examples` are ignored by the alias matcher
- every fixture passes
- unknown hardware is preserved, not guessed
- manual edits are protected
- parser version is stored on parsed jobs
- source fragments are preserved
- backend test suite is green


## v9 Validation Cleanup Addendum

This package is still not a parser implementation. It is a validation-clean implementation source.

Hard rules added/confirmed:

- `source_examples` are not aliases and must never be loaded into exact, loose, or fuzzy alias matching.
- Full workbook/source strings that contain bundles, batteries, metering, CT, export limits, WiFi/comms, quantities, installation notes, or other site-note fragments must remain fixtures/evidence unless deliberately promoted.
- Vague capacity-only hardware text such as `Solax 5kw` must not be guessed into a specific model. Preserve the raw source fragment in the editable hardware field with `confidence: unconfirmed_raw_text`, while still extracting any other identifiable meters, batteries, CT, export, underground, or comms fragments.
- Fixture output shape is mandatory and complete for every fixture.
- Validation must report zero blocking alias collisions before implementation begins.
