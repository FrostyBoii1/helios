# Hardware Parser Validation Notes v9.1

Scope: validation-cleanup pass only. Parser implementation was not performed.

## Results

- exact_aliases collisions: 0
- loose_aliases collisions: 0
- exact/loose cross-collisions: 0
- duplicate fixture IDs: 0
- source_examples also present as aliases: 0
- specific_corrections outputs missing catalog targets: 0

**Blocking validation collisions: 0**

No blocking collisions remain. The package is validation-clean for handoff, subject to normal implementation tests.


## Cleanup summary

- Direct aliases moved to source_examples: 115
- Collision/ambiguity direct aliases removed: 18
- Duplicate source_examples that matched active aliases removed: 5
- Duplicate fixture ID `export_only_no_meter` was renamed on the duplicate fixture.
- Fixture outputs were normalized to the full expected output shape.
- Alias collision validation is now a hard implementation gate.