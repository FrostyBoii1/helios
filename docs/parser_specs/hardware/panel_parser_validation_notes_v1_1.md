# Hardware Parser Panel Validation Notes v1.1

Validation scope: panel parser rule package only.

## Blocking Validation Status

- duplicate canonical IDs: 0
- duplicate fixture IDs: 0
- exact alias collisions: 0
- strict ignore values also present as aliases: 0
- non-panel ambiguous values present as panel aliases: 0
- brand-only aliases mapped directly to model: 0
- case-sensitive Jinko collision: intentionally allowed by case-sensitive metadata
- source examples used as aliases: not applicable in this package

## Manual Review / Known Ambiguity

The following are intentional manual-review or precision-review entries:

- `Suntech 415`
- `REC 460's`
- `AE 440 or TW`
- `TO AE PANELS`
- `3 x tigo Optimisers`
- `Ben installed`
- `2 x batteries`
- `ALPHA ESS 10KW`
- `Alpha ESS SMILE-BAT-13.3P`

## Implementation Gates

Before implementation is accepted:

1. Runtime YAML must parse.
2. Runtime YAML must pass schema validation.
3. Canonical IDs must be unique.
4. Fixture IDs must be unique.
5. Exact aliases must not collide unless explicitly case-sensitive and decision-logged.
6. Strict ignore values must not appear as panel aliases.
7. Non-panel/ambiguous values must not appear as panel aliases.
8. Brand-only values must not populate `model`.
9. Every fixture must pass.
10. Source fragments must be preserved.
11. Parser rule version must be stored.
12. Manual staff edits must not be overwritten without explicit confirmation.


## v1.1 Cleanup Status

- invalid confidence value `accessory_hardware`: removed from fixtures
- ambiguous comma-separated Suntech model: replaced with `model_options`
- ambiguous comma-separated REC model: replaced with `model_options`
- standalone `TW` exact model alias: removed
- standalone `TW` preserved as brand evidence/manual review unless derivable
- wattage-only fixture added
- out-of-tolerance derivation fixture added
- +/- 2W used instead of special-character tolerance wording


## v1.2 Cosmetic/Consistency Cleanup

- Normalized all fixture `parser_rule_version` values to `panel_rules_v1_1`.
- Updated stale implementation filename references in the spec.
- No panel catalogue mappings changed.
- No parser behavior rules changed.
