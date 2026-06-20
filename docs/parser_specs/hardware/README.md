# Hardware & Panel Parser Spec (curated "law")

These files are the **owner-approved, version-controlled source of truth** for the Helios
hardware parser lane. They were authored offline (the `v9.1` hardware package + the `v1.1`
panel package) and vendored here verbatim in **Stage 0** of the Hardware Parser lane.

They are **documentation / law / fixtures only** — runtime application code does **not** load
these files directly. The implementation plan is: seed a DB-backed hardware catalogue from
this spec, and have the runtime parser read the (admin-editable) DB catalogue. These files
remain the contract the implementation is proven against.

## Files

| File | What it is |
|------|------------|
| `hardware_parser_spec_v9_1.md` | Human implementation spec (inverter/battery/meter). Hard rules + acceptance gates. |
| `hardware_parser_runtime_rules_v9_1.yaml` | Machine-readable runtime config: `hardware_catalog` (inverters/batteries), `metering_catalog`, `ignore_rules`, `specific_corrections`, `global_guard_phrases`, normalization, ordering/aggregation rules. |
| `hardware_parser_test_fixtures_v9_1.yaml` | Full raw→expected fixtures. **Every fixture must pass** before the parser is accepted. |
| `hardware_parser_decision_log_v9_1.md` | Owner-approved weird mappings, ignore rules, manual corrections. |
| `hardware_parser_validation_notes_v9_1.md` | Validation-clean status (0 blocking collisions). |
| `panel_parser_spec_v1_1.md` | Panel spec (separate package — wattage/quantity/system-size; no phase). |
| `panel_parser_rules_v1_1.yaml` | `canonical_panels` + aliases (incl. case-sensitive) + brand/wattage-only policy. |
| `panel_parser_fixtures_v1_1.yaml` | Panel fixtures. |
| `panel_parser_decision_log_v1_1.md` | Panel decisions. |
| `panel_parser_validation_notes_v1_1.md` | Panel validation-clean status. |

## Hard rules (carried from the spec — do not violate in implementation)

- `source_examples` are **evidence only**, never aliases / never loaded into the matcher.
- Unknown/vague hardware is **preserved as raw text, never guessed** to the closest model.
- Hardware fields are **editable textboxes**; the parser seeds blanks and may refresh
  parser-owned fields, but **never overwrites manual edits without explicit confirmation**.
- The hardware parser **does not create workflow labels/tasks** (separate concern).
- Panels are stricter: `model` is **null** unless a real catalogue model is confidently
  identified (raw text goes to `display_name`, ambiguous → `model_options`).
- Each parsed item stores `model/quantity/confidence/parser_owned/source_fragment/source_type/
  source_field` + the parser rule version.
- **Job hardware is stored as an editable per-job snapshot** that never depends on the live
  catalogue: catalogue renames / alias edits / deletes / restores must NOT change already
  parsed Job hardware (the snapshot-stability law — see `docs/business_rules.md`).

## Validation gate

`backend/tests/test_hardware_parser_spec_validation.py` validates this package on every test
run (unique catalogue/fixture IDs, no alias collisions, `source_examples` not aliases,
confidence vocabularies, panel `model: null` rules, and the known `parser_rule_version`
drift). The backend container reads this directory via a read-only mount
(`./docs/parser_specs:/app/parser_specs:ro` in `docker-compose.yml`).

## Known drift (intentionally pinned, not yet reconciled)

The hardware runtime's `output_shape.parser_rule_version` is `hardware_parser_rules_v8` even
though the package is `v9.1`. This is a naming artifact from the curated source; the validator
pins it so it can't change silently. Reconcile deliberately in a later stage.
