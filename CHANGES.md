# CHANGES.md

This file records every meaningful deviation from the baseline specification
(`BASE.txt`). The baseline is the source of truth; anything that departs from it
must be justified here, per project governance.

Each entry records: **what** changed, **why**, **files affected**, whether it is
**temporary or permanent**, and any **risks / follow-up**.

---

## 2026-06-25 — Import review R3: hardware context in the grouping-candidate preview

- **Why:** the grouping-candidate preview (`CandidateRowPreviewModal` — the read-only "is this the same
  customer?" modal) showed only identity/status fields and **no hardware**, so a reviewer couldn't compare
  candidate jobs by system. **Owner rule:** show only *useful* system hardware context — phase, panels,
  inverter, battery — never a broad details dump (no metering/CT/notes/roof/storey).
- **What (frontend only):**
  - New pure helper `deriveHardwareContext(details)` ([hardwareDisplay.ts](frontend/src/lib/hardwareDisplay.ts))
    returns `{ phase, panels, inverter, battery }`, reusing the existing `panelDisplay` /
    `joinModels` ("N × MODEL") conventions. **Phase comes from `details.system.phase`** (humanised
    single/two/three → "Single/Two/Three-phase", raw fallback otherwise) — NOT the hardware snapshot.
    `battery` is `null` when there is no battery.
  - `CandidateRowPreviewModal` ([CandidateRowPreviewModal.tsx](frontend/src/components/imports/CandidateRowPreviewModal.tsx))
    renders Phase / Panels / Inverter (always, `—` when empty) and Battery (only when present), placed after
    Approval and before Group. The data was **already on the wire** (the modal already reads `parsed.details`),
    so **no backend/API change**.
- **Deliberately excluded:** metering, CT/electrical site notes, raw notes, roof type, storey — to avoid
  re-introducing a broad dump. `deriveSystemHardware` (which includes metering/CT) was **not** reused here.
- **Scope / no regression:** no backend, no migration, no live-data path. Resolved-issue filtering (R1) and
  blank-row handling (R2) untouched. The modal stays strictly read-only.
- **Tests / checks:** the repo has **no frontend test runner** (no vitest/jest, no `test` script), so no
  committed unit test was added (adding a test framework is out of R3 scope). The pure helper's logic was
  proven via a runner-agnostic Node check of all four cases (populated → 4 fields; battery hidden when absent;
  null/missing → clean empties, no crash; only phase/panels/inverter/battery — no metering/CT/notes leak), plus
  frontend **typecheck + lint + build** all green. Follow-up: add vitest in a separate slice to commit the
  helper/component tests.
- **Files:** `frontend/src/lib/hardwareDisplay.ts`, `frontend/src/components/imports/CandidateRowPreviewModal.tsx`;
  docs (CHANGES, DEVELOPER_HANDOFF, business_rules). Permanent.

---

## 2026-06-25 — Import review R1: resolved issues excluded from active error/warning filters & counts

- **Why:** resolving an error/warning still left the row in the `severity=error`/`severity=warning` queue and
  still inflated the per-severity summary count, even though the per-row badges (`IssueBadges`) already excluded
  resolved issues — a server/UI inconsistency. **Owner rule:** resolved issues are audit/history only; active
  error/warning queues and counts must include UNRESOLVED issues only.
- **What (backend only, 2 query fixes):**
  1. Row severity filter `GET /imports/{batch}/rows?severity=…` ([imports.py](backend/app/api/v1/endpoints/imports.py),
     `list_import_rows`): the issue subselect now requires `ImportIssue.resolved.is_(False)`. Severity-agnostic, so
     **warnings behave like errors** automatically (and `info`).
  2. Summary `issues_by_severity` ([import_review.py](backend/app/services/import_review.py), `summary`): the
     per-severity group-by now counts unresolved issues only. Schema field type unchanged
     ([import_staging.py](backend/app/schemas/import_staging.py) — comment added documenting the narrowed semantics).
- **Expected behaviour:** a row whose ONLY error is resolved disappears from `severity=error`; same for warnings;
  a row keeping a second UNRESOLVED same-severity issue stays visible; summary per-severity counts drop on resolve.
- **Preserved:** resolved issues remain on the row (`ImportRowRead.issues`) for audit/history when a row is fetched
  directly — only the active *filter* and *counts* exclude them. `unresolved_error_rows`, `eligible_clean_count`,
  and the approval gate (errors block approval; warnings intentionally do not) are **unchanged**.
- **Scope / no regression:** no migration (uses the existing `ImportIssue.resolved` column); **no frontend change**
  (the severity param is forwarded verbatim and `issues_by_severity` is not rendered); no parser/import-commit/
  ingest/reparse/hardware/live-data change. Full backend suite + alembic + `git diff --check` clean.
- **Tests:** `tests/test_import_review.py` — resolve-error drops row from `severity=error`; resolve-warning drops
  from `severity=warning`; second unresolved same-severity issue keeps the row; summary counts drop for error AND
  warning; resolved issue is filtered out of the active queue yet preserved on the row.
- **Files:** `backend/app/api/v1/endpoints/imports.py`, `backend/app/services/import_review.py`,
  `backend/app/schemas/import_staging.py`, `backend/tests/test_import_review.py`; docs (CHANGES,
  DEVELOPER_HANDOFF, business_rules). Permanent.

---

## 2026-06-25 — Hardware Parser P8c: Alpha M5 duplicate-canonical consolidation

- **Why:** the catalogue carried **two entries for the same inverter** — `Alpha ESS SMILE-M5 inverter`
  (`alpha_ess_smile_m5_inverter`, db id 1172) and `Alpha ESS SMILE-M5-S-INV` (`alpha_ess_smile_m5_s_inv`,
  db id 1173). The duplicate is what blocked the P8b `alpha ess m5 5kw inverter` alias (the ambiguity that
  was deferred to an owner decision). **Owner decision:** they are the **same hardware** for parser purposes;
  the single survivor is **`alpha_ess_smile_m5_s_inv` / `Alpha ESS SMILE-M5-S-INV`**.
- **What:** removed the duplicate `alpha_ess_smile_m5_inverter` entry from the spec; **merged** its aliases
  and `source_examples` onto the survivor and added the M5 inverter shorthand as **exact** aliases of the
  survivor — `Alpha ESS M5 5kw inverter`, `Alpha ESS SMILE-M5 inverter`, `UPGRADE TO M5 30KW` (joining the
  existing `Smile M5` / `Alpha ESS SMILE-M5-S-INV`). All M5 inverter shorthand now resolves to the one survivor.
- **Reference-data DB cleanup (non-production dev/test DB only):** because the seed is **insert/update-only and
  never removes** an entry that disappears from the spec, the already-persisted duplicate **catalogue row 1172
  was soft-deleted** (`deleted_at` set) along with its two aliases (`Alpha ESS SMILE-M5 inverter`,
  `UPGRADE TO M5 30KW`). Nothing hard-deleted. This prevents a stale row from owning the moved alias and making
  `_Index` resolution non-deterministic.
- **Snapshot rule preserved (no live mutation):** **zero** live `Job.details.hardware` snapshots referenced the
  duplicate id 1172 (verified before the soft-delete); the survivor's 27 referencing snapshots are untouched.
  No live Jobs / Customers / ImportRows / committed links changed. Catalogue cleanup does **not** mutate snapshots.
- **Conservative / no regression:** genuinely-ambiguous brand+capacity (`Solis 5kw`, `Sungrow 5kw`…), `smile 5`,
  and `13.3p alpha smile 5 inv` still stay raw (asserted). One active catalogue row owns the M5 inverter
  canonical (no alias collision). Spec validator + seed idempotency + `alembic check` clean; **no migration**
  (uses the existing `deleted_at` columns). Affects FUTURE parsing only — not retro-applied to live snapshots.
- **Tests:** `tests/test_hardware_runtime.py` new P8c section (5 M5 shorthand strings → survivor; exactly one
  active M5 inverter entry). Three former "M5 stays raw" tests updated where this owner decision supersedes
  them (`test_source_examples_never_match` rewritten to the durable whole-string-not-an-alias invariant;
  `test_brand_strip_never_resolves_source_example` and import's `test_source_examples_not_matched_through_import`
  re-pointed to still-raw brand+capacity examples); the P8b ambiguous-shorthand guard dropped the now-resolving
  M5 case.
- **Scope:** hardware parser spec YAML + tests + docs, plus a reference-data soft-delete of one catalogue row +
  its aliases. No runtime/parser-logic change, no new catalogue entries, no import/commit/live behavior, no
  frontend, no migration.
- **Files:** `docs/parser_specs/hardware/hardware_parser_runtime_rules_v9_1.yaml`,
  `backend/tests/test_hardware_runtime.py`, `backend/tests/test_import_hardware.py`; docs (CHANGES,
  DEVELOPER_HANDOFF, business_rules). Permanent.

---

## 2026-06-24 — Hardware Parser P8b: one safe catalogue alias (post-import raw cleanup)

- **Why:** the post-import raw-hardware audit flagged a few deterministic alias gaps; only the genuinely
  unambiguous one is safe to add now.
- **What:** added a single exact alias — **`ESS SMILE-BAT-13.3P` → `SMILE-BAT-13.3P`** — a bare-`ESS`
  brand-prefix variant of the already-aliased, **single, unambiguous** Alpha 13.3P battery (e.g. the cell
  `ESS SMILE-BAT-13.3P + Inverter smile`). No new catalogue entries; no runtime/code change.
- **Investigated and REJECTED as unsafe (left raw):** the audit's other candidate
  `alpha ess m5 5kw inverter → SMILE-M5-S-INV` was **NOT added** — "M5" is ambiguous between **two** catalogue
  inverter entries (`Alpha ESS SMILE-M5 inverter` vs `Alpha ESS SMILE-M5-S-INV`), the exact text is a curated
  `source_example` of the former, and an existing invariant (`test_brand_strip_never_resolves_source_example`)
  deliberately keeps it raw. Mapping it to one entry would be a guess → deferred to an owner decision
  (disambiguate the two M5 entries first).
- **Conservative / no regression:** never fuzzy; ambiguous brand+capacity (`Solis 5kw`…), `smile 5`,
  `13.3p alpha smile 5 inv`, and the M5 text all stay raw (asserted). No alias collision / no
  source_example-as-alias (spec validator green). **No migration; affects FUTURE parsing only — not
  retro-applied to the 1,710 live snapshots.**
- **Tests:** `tests/test_hardware_runtime.py` P8b section (13.3P alias resolves; the ambiguous + M5 cases
  stay raw). **733 backend tests pass**; spec-validation + `alembic check` clean.
- **Scope:** hardware parser spec YAML + tests + docs only. No runtime/parser-logic change, no catalogue
  entries, no import/commit/live behavior, no frontend, no migration.
- **Files:** `docs/parser_specs/hardware/hardware_parser_runtime_rules_v9_1.yaml`,
  `backend/tests/test_hardware_runtime.py`; docs (CHANGES, DEVELOPER_HANDOFF). Permanent.

---

## 2026-06-24 — Import review: editable staging `legacy_reference` (correct duplicate source refs pre-commit)

- **Why:** the clean reimport surfaced legitimately-distinct jobs that share one source `legacy_reference`
  in the workbook (e.g. `SC0049` covering two different customers/addresses). At commit, the
  duplicate-reference guard creates the first and silently skips the second — losing a real job. Reviewers
  had no in-app way to correct a reference; the alternatives were direct SQL (bypasses the review system)
  or another wipe + workbook fix + re-ingest.
- **What:** `legacy_reference` is now an admin-editable staging field on `ImportRow`, **column-only**:
  - added to `ImportRowEdit` (schema, bounded `max_length=64` to match the `String(64)` column so an
    over-long ref is a clean 422, never a DataError 500) and EXCLUDED from `PARSED_EDIT_FIELDS`, so the
    review service handles it specially and it is **never merged into `parsed`** (parsed keeps the parser's
    original reference as provenance; the `ImportRow.legacy_reference` column is authoritative for commit);
  - `import_review.edit_row` pops `legacy_reference`, applies it to the column (empty/whitespace → `None`,
    mirroring ingest), and **locks it on committed/reversed rows** via a new
    `_LEGACY_REF_LOCKED_STATES = {committed, reversed}` — a pending OR approved row stays editable (unlike
    `internal_notes_override`/customer-resolution, which also lock on approved) so a duplicate ref can be
    fixed right before commit.
- **No behavior change elsewhere:** parser untouched; case-number generation untouched (the year comes from
  `sale_date`→`install_date`, never the reference); commit-to-live unchanged except that it naturally reads
  the corrected `row.legacy_reference` column for duplicate detection and the created Job's reference. **No
  migration** (the column already exists; `alembic check` clean).
- **Tests:** `tests/test_import_review.py` (column updates; new value not written into parsed; editable
  after approve; empty→None; rejected on committed/reversed; over-64-char ref → clean 422) +
  `tests/test_import_commit.py` (baseline shared-ref second-row skip; after editing the 2nd row's ref BOTH
  distinct jobs commit; collapsing two distinct refs onto one commits exactly one — no live duplicate;
  case-number year stays from sale/install, not the edited reference). **726 backend tests pass**;
  `alembic check` clean.
- **Scope:** backend import-review schema + service + tests + docs only. No parser, no migration, no
  commit-engine logic change, no live-data mutation.
- **Frontend (separate slice, NOT done here):** the review modal currently renders `legacy_reference`
  read-only and its `ImportRowEdit` interface omits the field, so the **API accepts it now but the UI cannot
  send it yet** — exposing it needs a `legacy_reference` input + the field added to the frontend
  `ImportRowEdit`. Until then, corrections go via `PATCH /api/v1/imports/{batch}/rows/{row}`.
- **Files:** `backend/app/schemas/import_staging.py`, `backend/app/services/import_review.py`,
  `backend/tests/test_import_review.py`, `backend/tests/test_import_commit.py`; docs (CHANGES,
  DEVELOPER_HANDOFF, business_rules). Permanent.

---

## 2026-06-24 — Hardware Parser P7: deterministic pre-reimport coverage polish (spec + runtime)

- **Why:** the pre-reimport readiness audit confirmed the parser is broadly reimport-ready but found a set of
  KNOWN, deterministic coverage gaps — chiefly that the real-workbook Swatten "All In One 19.2" phrasings were
  under-covered (the P6b bundle keys used a word order / spacing the actual cells do not), plus a few exact
  alias gaps. P7 closes those gaps WITHOUT changing the parser's conservative policy: still exact-only, never
  fuzzy; ambiguous / capacity-only text stays raw/manual_review by design.
- **What (four additive changes):**
  - **De-parenthesised model resolution** (`runtime.py` `_normalized_hit`): a fragment that did not match
    directly is retried with `(`/`)` stripped (and a brand-stripped form), e.g. `SolaX (X1-SMT-10K-G2)` →
    `X1-SMT-10K-G2`. A hit is returned ONLY when the de-parenned remainder is itself an existing catalogue
    alias — purely additive, never guesses. Also correctly resolves Sungrow `(SH10RT)`/`(SH10RS)` and Goodwe
    `(GW10KAU-DT)`.
  - **Neovolt capacity-suffix aliases** on `neovolt_bw_bat_10_1p`: `Neovolt BW-BAT-10.1kWh`, `BW-BAT-10.1kWh`,
    `Neovolt BW-BAT-10.1kw hr`, `BW-BAT-10.1kw hr` (10.1kWh is the model's own capacity → unambiguous; the two
    colliding `source_examples` were removed per the evidence-only policy).
  - **13.3P extension typo/abbrev aliases** on `smile_bat_13_3p`: `exten 13.3p`, `ext 13.3p alpha`,
    `extenson 13.3p`, `extenston 13.3p`, `extens 13.3p battery`, `extension battery 13.3p`, `13.3p alpha`
    (model-unambiguous — `13.3P` = `SMILE-BAT-13.3P`; aggregates with the base battery into a summed quantity).
  - **15 Swatten whole-cell bundles** (`p7_bundle_swatten_*` + one SolaX combo): the real workbook phrasings
    (`Swatten 19.2kw All In One`, `Swatten 19.2 ALL IN ONE`, `… - 3 phase`, `All in One … Battery/INV`,
    `All In one Swatten 19.2 - 1 x 5kw 1P/3P and 6 x 3.2 batt`, …) → `Swatten SiH-5kW-TH` + `Swatten
    SieB-H19K2-F`; `SWATTEN 19.2WKW BATTERY` → battery only; `2 x … ALL IN ONE - 3 phase` → qty 2 of each;
    `SolaX Power X1-SMT-10K-G2 + SWATTEN ALL IN 19.2KW BATT` → `X1-SMT-10K-G2` (exact) + Swatten battery.
    `Swatten SiH-5kW-TH` is a single-phase SKU and a distinct 3-phase Swatten model is unconfirmed, so the
    four bundles whose source cell explicitly says **3 phase / 3P** also preserve that wording in
    `site_notes.raw_misc` (`Swatten source says 3 phase` / `… 3P`) rather than asserting a (possibly wrong)
    3-phase model — the phase signal is kept for human review, the model stays the owner-confirmed pair.
- **Conservative / no regression — verified:** still never fuzzy (only exact aliases, exact whole-cell
  bundles, and exact de-paren-then-exact-alias resolve). Plain ambiguous brand+capacity (`Solis 5kw`,
  `Goodwe 10kw`), capacity-only (`15kw battery`), extension-without-a-model-token (`exten battery`,
  `extension 10.1`), dash-split `Neovolt BW-BAT - 10.1kw hr`, and the `X1-BOOST-5K` (no generation) /
  `X3-Pro-10kw` Swatten combos (uncatalogued/uncertain models) all stay raw by design. A per-cell
  before/after parse diff over the whole COMPLETED sheet (1,686 hardware rows) shows **62 cells improved
  (raw → resolved), 0 regressions** — no cell lost or changed an existing canonical id.
- **Audit delta over COMPLETED (resolved-id metric):** clean **1,278 → 1,338**, raw **405 → 345**. Catalogue
  rows unchanged at 170 (only aliases added: +11 → 311; bundle_interpretations 10 → 25).
- **Scope:** hardware parser spec + runtime + tests + docs only. No frontend, Settings/import/Job UI, import
  commit/reverse, NAS/proposal, scheduling, migration, seed code, or data files. No clean-wipe / reimport.
- **Tests:** `tests/test_hardware_runtime.py` adds a P7 section (parenthesised models resolve + a non-model in
  parens stays raw; Neovolt capacity-suffix; extension typo variants + base aggregation + generic-extension
  stays raw; every Swatten phrasing → unit, battery-only, qty-2, and the SolaX combo); spec validator passes
  unchanged. **710 backend tests pass**; spec-validation green; `alembic check` clean.
- **Files:** `backend/app/hardware/runtime.py`,
  `docs/parser_specs/hardware/hardware_parser_runtime_rules_v9_1.yaml`,
  `backend/tests/test_hardware_runtime.py`; docs (CHANGES, DEVELOPER_HANDOFF — incl. fixing the stale
  167→170 catalogue count). Permanent.
- **Deferred:** the uncertain-model Swatten/extension cells noted above (left raw), and the (still
  un-authorized) clean-wipe + reimport — P7 is the final deterministic polish before that owner decision.

---

## 2026-06-24 — Hardware Parser P6b: deterministic whole-cell bundle interpretation + notes (spec + runtime)

- **Why:** the heavier half of the owner-confirmed bundle/shorthand pass — workbook shorthand whose
  meaning is a fixed multi-model bundle, a low-confidence contextual mapping, or a hardware note that
  generic aliases alone cannot express. **Deterministic only** (owner-confirmed exact patterns); a cell
  not explicitly covered falls through to ordinary matching and stays raw/review.
- **What:**
  - **New `bundle_interpretations` mechanism** (spec section + `rules.py` loader + runtime step
    `_emit_bundle` in `_parse_hardware_cell`): an EXACT normalized whole-cell match emits a fixed set
    of typed inverter/battery items (canonical `model_text` + resolved catalogue id, per-item or rule
    confidence, quantity) + notes (→ `site_notes.raw_misc`). It runs after specific_corrections /
    before guards (so an owner-confirmed bundle wins), and is never fuzzy. 10 rules: Swatten
    All-In-One (→ `Swatten SiH-5kW-TH` + `Swatten SieB-H19K2-F`); mixed SolaX+Alpha
    `X1-SMT-10K-G2 + Alpha ESS SMILE M5 20KW BATTERY` (→ `X1-SMT-10K-G2` + `SMILE-M5-S-INV` + 2×
    `SMILE-G3-BAT-10.1P`, **manual_review**); `Smile M5 inverter/SMILE-M-BAT-5PIII - 15kw batt`; five
    VAST/T-BAT cells with notes (`Battery with base`, `2 x BMS`, `12 batteries of 3.6kw hrs`) and
    capacity inference (`28.8kw battery` → `T-BAT HS28.8`, **inferred_from_capacity**); and the
    **Solis-context** cell (→ `X1-VAST-10K` + `T-BAT HS21.6` + note `Solis 5kw was installed`, with the
    Solis emitted **as a note, not current hardware**, per owner guidance — `Solis-1P5K-4G` was mapped
    to existing `S5-GR1P5K`, but in this install-context cell the Solis is not emitted at all).
  - **Shorthand aliases** (resolve the cleanly-decomposing cells generally): bare `T-BAT HS21.6` /
    `T-BAT HS28.8` / `t-bat21.6`; `Smile M5` → `Alpha ESS SMILE-M5-S-INV`; no-space
    `SMILE-M-BAT-5PIII/IV/V/VI`; `15kw Alpha Stack` → `SMILE-M-BAT-5P III`, `30kw Alpha Stack` →
    `SMILE-M-BAT-5P VI`; `Neovolt 5kw DC` / `Neovolt 5kw AC` → `Neovolt BW-INV-SPB5K`. Combined with
    P1 split + P6a aggregation, the two Alpha-stack and two Neovolt-reversed cells resolve fully (e.g.
    `2 x Neovolt 5kw AC Inverters/6 x 10.1 Neovolt Batteries` → 2× inverter + 6× battery).
- **Conservative / no regression:** never fuzzy — only the listed exact whole-cell patterns and exact
  aliases resolve; plain ambiguous `Solis 5kw` / `Goodwe 10kw` still stay raw; capacity never
  contaminates `model_text` (`· 29.4kWh` → `raw_misc`); contextual/inferred interpretations are flagged
  `manual_review` / `inferred_from_capacity`. Spec validator extended to verify every bundle model
  exists + unique ids/match keys + confidence vocab. Idempotent seed (+12 aliases, then `0/0`).
- **Audit delta over COMPLETED:** original metric (manual_review counted as raw, same basis as P6a's
  1,202/481) → clean **1,222 / raw 461**; per-component resolved metric → clean **1,278** (the ~56-row
  gap is cells P6b correctly interprets at `manual_review`/`inferred_from_capacity` — resolved but
  deliberately review-flagged). Cumulative P1→P6b: ~645 → ~1,222 (strict) / ~1,278 (resolved).
- **Scope:** hardware parser spec + runtime + tests + docs only. No frontend, Settings/import/Job UI,
  import commit/reverse, NAS/proposal, scheduling, migration, seed code, or data files.
- **Tests:** `tests/test_hardware_runtime.py` adds a P6b section asserting EVERY owner example (correct
  buckets, quantities, confidence/manual_review, notes preserved, capacity not in model_text, Solis not
  emitted as hardware) + plain-ambiguous-stays-raw; `tests/test_hardware_parser_spec_validation.py`
  validates the bundle section. **680 backend tests pass**; spec-validation green; `alembic check` clean.
- **Files:** `docs/parser_specs/hardware/hardware_parser_runtime_rules_v9_1.yaml`,
  `backend/app/hardware/rules.py`, `backend/app/hardware/runtime.py`,
  `backend/tests/test_hardware_runtime.py`, `backend/tests/test_hardware_parser_spec_validation.py`;
  docs (CHANGES, DEVELOPER_HANDOFF). Permanent.
- **Deferred:** broader bundle variants beyond the owner-confirmed exact strings (left raw by design);
  emitting historical/decommissioned hardware as a distinct concept; and the (un-authorized) clean-wipe
  + reimport.

---

## 2026-06-24 — Hardware Parser P6a: known shorthand aliases + quantity aggregation (spec + runtime)

- **Why:** the first, lower-risk half of the owner-confirmed "known bundle/shorthand interpretation"
  pass — the safe, general parts: shorthand aliases the owner identified, the two Swatten component
  entries, and quantity aggregation. (The heavier whole-cell bundle-interpretation mechanism + note
  extraction + the Solis/mixed-cell cases are deferred to **P6b**.)
- **What:**
  - **Shorthand aliases** (`docs/parser_specs/hardware/hardware_parser_runtime_rules_v9_1.yaml`):
    `Vast 10kw` / `Vast 10K` → `X1-VAST-10K`; `13.3p` / `extension 13.3p` / `ext 13.3p` →
    `SMILE-BAT-13.3P`; `10.1 neovolt` / `extension neovolt 10.1` → `Neovolt BW-BAT-10.1P`. Combined
    with P2 brand-strip + P1 trailing-noun cleanup these also resolve `Solax Vast 10kw`,
    `VAST 10K INVERTER`, `Alpha ESS 13.3p`, etc.
  - **Two new Swatten component entries** (owner-named exact models, prerequisites for the P6b
    Swatten-All-In-One bundle rule): `Swatten SiH-5kW-TH` (inverter, 5 kW) and `Swatten SieB-H19K2-F`
    (battery).
  - **Quantity aggregation** (`app/hardware/runtime.py`, implementing the spec's `aggregation_rules`):
    items resolving to the SAME catalogue model AND the same confidence collapse into one item with the
    summed quantity, preserving every contributing `source_fragment`. So
    `2 × Alpha ESS SMILE-BAT-13.3P + extension 13.3P` → ONE battery `SMILE-BAT-13.3P` quantity **3**.
    `do_not_aggregate` is respected — different models/confidence stay separate (the canonical SAJ
    bundle keeps inverter + qty-2 battery as two items), and unmatched raw items never merge.
- **Architecture rule documented** (`docs/business_rules.md`): the **spreadsheet is the first-pass
  import source of truth; NAS parsing is future supporting evidence and fallback, never a mandatory
  per-import dependency.** Where spreadsheet-parser confidence is high enough, import does not require
  NAS; genuinely ambiguous hardware stays raw/`manual_review` rather than blocking on NAS.
- **Conservative / no regression:** new aliases never make plain ambiguous capacity resolve
  (`Solis 5kw`/`Goodwe 10kw` still raw); aggregation only merges truly-identical matched items; every
  P1–P5 case unchanged. Spec validator passes (unique IDs, no alias collisions, source_examples-not-
  aliases). Idempotent seed (`+2 entries / +9 aliases`, then `0/0`).
- **Audit delta over COMPLETED (confidence metric):** fully-clean rows **1,172 → 1,202 (+30)**; raw
  rows **511 → 481**. (Cumulative P1→P6a: ~645 → ~1,202.)
- **Scope:** hardware parser spec + runtime + tests + docs only. No frontend, Settings/import/Job UI,
  import commit/reverse, NAS/proposal, scheduling, migration, data files, or seed code.
- **Tests:** `tests/test_hardware_runtime.py` adds a P6a section (Vast / 13.3p / Neovolt shorthand
  resolve; `extension` aggregates to qty 3; aggregation keeps different models separate; the two
  Swatten entries exist; shorthand does not over-resolve `Solis 5kw`). **661 backend tests pass**;
  spec-validation green; `alembic check` clean. (A hardware admin-API test's fixture search `q=f_bat`
  collided with the battery spec_id substring — the entry was renamed `swatten_sieb_h19k2_battery` to
  avoid it; no test weakened.)
- **Files:** `docs/parser_specs/hardware/hardware_parser_runtime_rules_v9_1.yaml`,
  `backend/app/hardware/runtime.py`, `backend/tests/test_hardware_runtime.py`,
  `docs/business_rules.md`; docs (CHANGES, DEVELOPER_HANDOFF). Permanent.
- **Deferred to P6b:** the whole-cell **bundle-interpretation mechanism** (Swatten All-In-One → SiH +
  SieB; Alpha M5 stack; mixed SolaX+Alpha → low-confidence; Neovolt reversed-order full cells); **note
  extraction** (`2 x BMS`, `12 batteries of 3.6kw hrs`, `with base`, `Solis 5kw was installed`); the
  Solis-context inverter mapping to the existing **`S5-GR1P5K`** (manual_review); and capacity→T-BAT
  derivation (`28.8kw battery`→`T-BAT HS28.8`, `inferred_from_capacity`). Then the (un-authorized)
  clean-wipe + reimport.

---

## 2026-06-24 — Hardware Parser P5: leading bare-quantity resolution (runtime only)

- **Why:** the last straightforward correctness gap from the audit — a fragment with a LEADING bare
  quantity (no `×`/`x`/`*` separator) and a trailing hardware noun, e.g. `1 SBR128 battery` /
  `2 SBR128 batteries`, stayed a raw `1 SBR128 battery` item instead of resolving to the catalogued
  battery `SBR128` with the right quantity. (The audit's other P5 items — metering vocab `export
  meter`/`smart meter 5kw export`/`with meter` and capacity-in-noun `16kw hrs battery`/`15kw battery`/
  `40kw hrs` — were already handled correctly by P3's bucket routing + the capacity/site-note rules;
  this slice adds regression tests confirming them and makes no further change there.)
- **What (`app/hardware/runtime.py` only):** the bare-quantity retry in `_parse_hardware_cell` now (a)
  honours a leading quantity of **any** value including `1` (previously only `N >= 2`), and (b)
  resolves the remainder via **P2 normalization** (`_normalized_hit`: brand-prefix + trailing
  hardware-noun) in addition to a direct alias lookup. The quantity is taken **only when the remainder
  resolves to a real catalogue alias** — so a leading number that is actually part of unmatched text
  (`2 Frobnicator 9000`) or a unit (`40kw hrs`) is never mis-split. Gated on `bcore != frag` (a leading
  number was actually present).
- **Conservative / no regression:** never guesses a model; `source_fragment` and quantity preserved;
  `2 Frobnicator 9000` still stays raw `2 Frobnicator 9000` (qty 1); `40kw hrs` still → `raw_misc`;
  `Solis 5kw`/`Goodwe 10kw` still raw; every P1–P4 case unchanged (`Sungrow 10kW SH10RT/SBR128 BATT`,
  the canonical SAJ string, `Solax Power X1-SMT-10K-G2`, T-BAT/Neovolt/SMILE-M-BAT-5P VI). No
  catalogue/spec/seed change, no migration.
- **Behaviour, before → after (live):** `1 SBR128 battery` → battery `SBR128` ×1 (was raw
  `1 SBR128 battery`); `2 SBR128 batteries` → battery `SBR128` ×2; `1 SBR096 battery` → battery
  `SBR096` ×1. Metering/capacity unchanged from P3 (`1 export meter`/`export meter`/`smart meter 5kw
  export` → raw metering; `16kw hrs battery`/`15kw battery` → raw batteries; `40kw hrs` → `raw_misc`;
  `with meter` → matched `Meter`).
- **Audit delta over COMPLETED (confidence metric):** fully-clean rows **1,171 → 1,172**; raw rows
  **512 → 511** (small — the leading-bare-quantity pattern is uncommon, and the fragments it fixes
  often sit in rows with other unresolved parts; the gain is correctness, not match-rate).
- **Scope:** backend parser runtime + tests only. No frontend, Settings/import/Job UI, import
  commit/reverse, NAS/proposal, scheduling, migration, data files, catalogue seed, or vendored
  `parser_specs` YAML.
- **Tests:** `tests/test_hardware_runtime.py` adds a P5 section (leading-qty 1/2 → battery; leading
  number not split when the remainder doesn't resolve; `16kw hrs battery` → raw battery not inverter;
  `40kw hrs` → `raw_misc`; `with meter` → metering). One P3 test was retargeted from `1 SBR096
  battery` (which now correctly RESOLVES) to a genuinely-unmatched `Frobnicator battery` so it still
  proves the unmatched→batteries routing. **647 backend tests pass**; spec-validation green; `alembic
  check` clean.
- **Files:** `backend/app/hardware/runtime.py`, `backend/tests/test_hardware_runtime.py`; docs
  (CHANGES, DEVELOPER_HANDOFF). Permanent.
- **Deferred (next slices):** Swatten All-In-One policy pass; the `13.3p`/`extension 13.3p` Alpha
  shorthand; reversed-order/suffix variants (`10.1 neovolt`, `vast 10kw`, `smile m5`); broader
  catalogue additions; and the (un-authorized) clean-wipe + reimport.

---

## 2026-06-24 — Hardware Parser P4: evidence-based catalogue adds for still-raw known hardware (spec only)

- **Why:** after P1–P3, several still-raw COMPLETED fragments are genuinely-known hardware the
  catalogue couldn't match — either missing entries, or entries that carried only a brand-qualified
  alias (so P2's brand-strip produced a bare token with no matching alias). This slice teaches the
  curated catalogue about hardware that is actually present in the workbook / curated spec, without
  guessing or bloating.
- **What (`docs/parser_specs/hardware/hardware_parser_runtime_rules_v9_1.yaml` — the vendored
  catalogue source seeded by Stage 1):**
  - **NEW entry** `smile_m_bat_5p_vi` — Alpha ESS battery `SMILE-M-BAT-5P VI` (only iii/iv/v existed;
    VI appeared solely in source_examples). Evidence: ~8 raw rows + curated source_examples.
  - **New bare aliases on existing SolaX T-BAT batteries:** `T-BAT HS25.2` → `solax_t_bat_hs25_2`,
    `T-BAT HS32.4` → `solax_t_bat_hs32_4`. These entries previously held only the `SolaX T-BAT HSxx`
    alias, so a workbook `Solax Power T-BAT HS25.2` brand-stripped to `t-bat hs25.2` matched nothing.
    Evidence: 7 + 6 raw rows. (HS43.2 already resolves via the existing bare-alias entry `t_bat_hs43_2`.)
  - **New bare aliases on Neovolt `BW-BAT-10.1P`:** `BW-BAT-10.1`, `BW-BAT-10.1 P` (the entry had the
    `-10.1P` / space variants but not the bare hyphenated form). Evidence: ~11 raw rows.
  - **Tesla manufacturer correction:** the two `Tesla Powerwall 3` entries had manufacturer `Unknown`
    → set to `Tesla`. (Data-quality only; applies on a FRESH seed — the idempotent seed inserts-if-
    missing and never clobbers an already-seeded row, so an existing DB keeps the old value until a
    clean re-seed, e.g. the future clean-wipe + reimport.)
- **Conservative / evidence-based:** every addition is a model found in the current workbook AND/OR
  the curated source_examples — no industry "shopping". Ambiguous capacity-only / generic text
  (`Solis 5kw`, `Goodwe 10kw`, `15kw battery`, `inverter`) deliberately still stays raw. No catalogue
  model is guessed; resolution is exact-alias only. Source_examples are still never aliases.
- **No live-reference behaviour / no business-data mutation:** Jobs still store snapshots; the only
  DB action is the idempotent reference-data seed (verified `{hardware_created:0, alias_created:0}` on
  a second run). No runtime/parser code change, no seed-code change, no migration.
- **Vendored-spec note:** the `docs/parser_specs/hardware` package is treated as catalogue "law"; this
  is a DELIBERATE, evidence-based extension. The Stage-0 spec validator (unique IDs, no alias
  collisions, source_examples-not-aliases, confidence vocab, version pin) still passes unchanged.
- **Audit delta over COMPLETED (confidence metric):** fully-clean rows **1,149 → 1,171 (+22)**; raw
  rows **534 → 512**. (Cumulative P1→P4: ~645 → ~1,171 fully-clean.)
- **Scope:** catalogue spec + tests + docs only. No frontend, Settings UI, import review UI, import
  commit/reverse, NAS/proposal, scheduling, Job UI, migration, live data files, or runtime parser code.
- **Tests:** `tests/test_hardware_runtime.py` adds a P4 section (T-BAT HS25.2/HS32.4, Neovolt
  BW-BAT-10.1, SMILE-M-BAT-5P VI all resolve as matched batteries; Tesla manufacturer = Tesla in the
  spec; **seed idempotency** = 0/0 on re-seed; ambiguous capacity-only stays raw). **641 backend tests
  pass**; spec-validation green; `alembic check` clean.
- **Files:** `docs/parser_specs/hardware/hardware_parser_runtime_rules_v9_1.yaml`,
  `backend/tests/test_hardware_runtime.py`; docs (CHANGES, DEVELOPER_HANDOFF). Permanent.
- **Deferred (next slices):** **Swatten All-In-One 19.2/25.6** (needs promoting v9.1-demoted
  source_examples back to aliases — a larger policy change for its own pass); the `13.3p` /
  `extension 13.3p` Alpha extension shorthand (~60 rows, ambiguous aliasing); reversed-order / suffix
  variants (`10.1 neovolt`, `neovolt bw-bat-10.1kwh`, `vast 10kw`, `smile m5`); capacity-only battery
  descriptions (correctly raw); leading-`1`+model (`1 SBR128 battery`); metering vocab expansion;
  in-fragment capacity-in-noun extraction; and the (un-authorized) clean-wipe + reimport.

---

## 2026-06-24 — Hardware Parser P3: route unmatched battery/metering evidence to the right bucket (runtime only)

- **Why:** the remaining structural-correctness gap from the audit — an UNMATCHED fragment always fell
  into the `inverters` bucket, so a Job's System display showed battery/metering evidence (`12.8kw
  batt`, `1 SBR096 battery`, `export meter`) as an *inverter*. The audit estimated ~265 affected rows.
- **What (`app/hardware/runtime.py` only):** after all catalogue matching (direct / P1 split / P2
  normalization) fails, the unmatched fragment is now bucketed by `_hardware_signal(frag)` —
  `batteries` for a `batt`-prefixed word or a Sungrow `SBR<digit>` shorthand (`_BATTERY_HINT_RE`),
  `metering` for a `meter`-prefixed word or `current transformer` (`_METERING_HINT_RE`) — defaulting
  to `inverters` when there is no strong signal. The same signal also guards the site-note step: a
  fragment that is metering/battery *hardware* (e.g. `smart meter 5kw export`) is no longer swallowed
  into a NON-CT site bucket (`export_limit`/`underground`/`comms`); **bare CT still routes to
  `site_notes.ct` unchanged**.
- **Conservative by construction:**
  - **Raw only** — routed items keep `confidence = unconfirmed_raw_text` and **no
    `canonical_hardware_id`** is ever invented (no model is guessed); only the bucket changes.
  - **Inverter stays the default** — ambiguous inverter capacity (`Solis 5kw`, `Goodwe 10kw`, `10kw
    inverter`) has no battery/metering signal and stays a raw inverter item.
  - **Matching is untouched** — runs only on the unmatched path, so every direct/P1/P2 match (incl.
    `SBR128 BATT` → matched battery via P2) is unaffected; capacity-only text still routes to
    `site_notes.raw_misc`; `source_fragment` and quantity are preserved (`6 x 3.2 batt` → battery ×6).
  - **No CT regression**, no catalogue/alias/YAML change, source_examples still never resolve.
- **Behaviour, before → after (live):** `1 SBR096 battery` / `12.8kw batt` → **batteries** (were
  inverter); `1 export meter` / `smart meter 5kw export` → **metering** (were inverter / a buried
  export-limit note); `Sungrow 10kW SH10RT/SBR128 BATT` → inverter `SH10RT` + battery `SBR128`
  (unchanged); `Solis 5kw` → inverter raw (unchanged); canonical SAJ string → unchanged.
- **Audit delta over COMPLETED:** **130 raw evidence items moved out of the inverter bucket** — 112
  → batteries, 18 → metering. Fully-clean rows 1,153 → 1,149 and raw rows 530 → 534 (a small,
  intentional shift: ~4 rows' `smart meter 5kw export`-style evidence moved from a hidden
  `export_limit` site-note into a *visible, flagged* metering item — more honest, not a quality loss).
- **Scope:** backend parser runtime + tests only. No frontend, imports UI, import commit/reverse,
  Settings, NAS/proposal, scheduling, migration, data files, catalogue seed/aliases, or vendored
  `parser_specs` YAML.
- **Tests:** `tests/test_hardware_runtime.py` adds a P3 section (battery-word / capacity-batt → batteries;
  `SBR128 BATT` stays matched battery; export-meter / smart-meter-export → metering; quantity preserved
  when routing; ambiguous inverter capacity stays inverter; CT still → `site_notes.ct`). **634 backend
  tests pass**; spec-validation green; `alembic check` clean.
- **Files:** `backend/app/hardware/runtime.py`, `backend/tests/test_hardware_runtime.py`; docs
  (CHANGES, DEVELOPER_HANDOFF). Permanent.
- **Deferred (next slices):** P4 catalogue adds (T-BAT, X1-VAST, X3-ULT, Swatten all-in-one, Neovolt
  variants, Alpha extensions, missing brands), metering vocab expansion, in-fragment capacity-in-noun
  extraction (`16kw hrs battery` → split model + capacity note), leading-`1`+model resolution, and the
  (un-authorized) clean-wipe + reimport.

---

## 2026-06-24 — Hardware Parser P2: brand-prefix / noise normalization (runtime only)

- **Why:** the E2E audit's #1 *resolution* gap — the catalogue stores bare model aliases (`SH10RT`,
  `X1-SMT-10K-G2`), but the workbook writes them with a leading brand/manufacturer (and sometimes a
  leading power token), or with a trailing hardware-type noun, so known hardware stayed raw. The
  audit estimated ~551 raw rows would resolve once brand prefixes were handled.
- **What (`app/hardware/runtime.py` only):** when a fragment does NOT match directly (or via the
  existing quantity retries), a new `_normalized_hit` tries resolving it after conservatively
  stripping (a) a known **leading brand prefix** (`_BRAND_PREFIXES`: Sungrow, Solax / Solax Power,
  SAJ, Goodwe, Solis, Neovolt / Nevolt, Alpha ESS / Alpha-ESS — casefolded, longest-first) plus an
  **optional single leading power token** (`_LEADING_POWER_RE`, e.g. `10kW` — never `kWh`/`kw hrs`
  energy), and/or (b) a **trailing hardware-type noun** (`_TRAILING_NOISE_RE`: `… BATT`/`battery`/
  `inverter`/`inv`, space-anchored so a model ending `-INV` is untouched). A candidate is accepted
  **ONLY** when the transformed remainder is itself a catalogue alias.
- **Conservative by construction:**
  - **Purely additive** — `_normalized_hit` runs only when `hit is None`, so it can never change a
    previously-matched item; it can only turn a previously-raw fragment into a resolved one.
  - **Never guesses** — resolves only to an existing exact/loose alias; brand-only (`Sungrow`) and
    capacity-only (`Solis 5kw`, `Goodwe 10kw`) produce no resolving candidate and stay raw for review
    (decision log D-v9.1-002).
  - **No catalogue bloat** — the brand list is a small version-controlled CODE constant, NOT seeded
    as hundreds of brand-prefixed aliases and NOT added to the vendored v9.1 spec YAML.
  - **Provenance preserved** — `source_fragment` stays the original workbook fragment; `model_text`
    becomes the resolved canonical model; quantity and confidence follow the matched alias.
- **Behaviour, before → after (live):** `Solax Power X1-SMT-10K-G2` → `X1-SMT-10K-G2`; `Sungrow
  SH10RT` → `SH10RT`; `Sungrow 10kW SH10RT/SBR128 BATT` → inverter `SH10RT` + battery `SBR128` (P1
  split + P2 resolve); `2 x Sungrow SH10RT` → `SH10RT` ×2; `Solis 5kw` / `Sungrow` → stay raw;
  canonical `SAJ H2-10K-S3-A + 2 × SAJ B2-20.0-HV1 - 40kw hrs` → unchanged.
- **Audit delta over COMPLETED (1,686 inverter-text rows), confidence metric (same as the after-P1
  baseline):** fully-clean rows **654 → 1,153 (+499)**; rows with ≥1 raw item **1,029 → 530** (about
  halved). (Under a per-component "resolved to a catalogue entry" metric: 1,207 / 476.)
- **Scope:** backend parser runtime + tests only. No frontend, imports UI, import commit/reverse,
  Settings, NAS/proposal, scheduling, migration, data files, catalogue/alias seeding, or YAML-rule
  change.
- **Tests:** `tests/test_hardware_runtime.py` adds a P2 section (Solax Power / Sungrow / leading-power
  resolution, the P1+P2 slash bundle, quantity preservation, SAJ direct, Alpha ESS direct, brand-only
  non-resolution, capacity-only stays raw, source_example never resolves via strip). **625 backend
  tests pass**; spec-validation green; `alembic check` clean.
- **Files:** `backend/app/hardware/runtime.py`, `backend/tests/test_hardware_runtime.py`; docs
  (CHANGES, DEVELOPER_HANDOFF). Permanent.
- **Deferred (next slices):** P3 bucket routing (unmatched battery/metering text still lands in the
  inverter field), P4 catalogue adds (T-BAT, X1-VAST, X3-ULT, Swatten all-in-one, Neovolt variants,
  Alpha extensions, missing brands), metering vocab (`export meter`, `with meter`), in-fragment
  capacity-in-noun extraction, leading bare-`1`+trailing-noun forms (`1 SBR128 battery`), and the
  (un-authorized) clean-wipe + reimport.

---

## 2026-06-23 — Hardware Parser P1: separator splitting (runtime only)

- **Why:** the read-only E2E reimport-readiness audit found the #1 *separator* gap — the real
  workbook joins inverter/battery/metering/capacity fragments with `/`, `and`, `&`, `·`, `•`, and
  `with`, but the parser split only on `+` and a spaced `-`, so fully-catalogued bundles collapsed
  into a single raw blob (wrong buckets, lost quantities, capacity glued into model_text). 60 rows
  use `and`, 70 use `/`, 183 use `·`, 19 use `with` among the 1,036 raw rows.
- **What (`app/hardware/runtime.py` only):** extended the hardware-cell fragment splitter
  (`_split_fragments` / new `_FRAGMENT_SPLIT_RE`) to also split on `/`, `·`, `•`, `&`, and the
  whole words `and` / `with`, in addition to `+` and the spaced `-`. Each separator is chosen so it
  cannot occur inside a catalogue model: a model-internal hyphen is never space-padded (so
  `X1-BOOST-5K-G4` survives — only a spaced ` - ` splits), and `/`,`•`,`&`,`and`,`with` appear in no
  inverter/battery/metering model. (`·` is normally rewritten to `-` by the existing
  `_normalize_encoding` before the splitter runs, so a `MODEL · 25kWh` cell already splits via the
  spaced-hyphen rule; the `·` in the pattern is a harmless safety net.) Each fragment is then resolved
  independently, so quantities (`2 x` / `2 ×`) and capacity routing (`25kWh` / `40kw hrs` → `raw_misc`)
  work per-fragment. A pre-existing helper (the bucket-by-category map) was hoisted to a module
  constant `_BUCKET_BY_CATEGORY` (no behaviour change). Panel parsing is untouched (it never uses the
  splitter), and the whole-cell ignore/correction/guard checks still run first.
- **Behaviour, before → after (live, real audit strings):**
  - `1 x SAJ H2-10K-S3 and 2 x SAJ B2-15.0-HV1`: 1 raw blob → inverter `SAJ H2-10K-S3` + battery
    `SAJ B2-15.0-HV1` ×2 (both exact).
  - `1 x SAJ H2-25K-T3-AU and 2 × SAJ B2-25.0-HV1 · 25kWh`: 1 raw blob → inverter + battery ×2 +
    `25kWh` in `site_notes.raw_misc`.
  - `2 x Sungrow Hybrid 5kw/16kw hrs battery`: 1 raw blob (capacity glued) → inverter `SG5.0RS` ×2 +
    a separate `16kw hrs battery` fragment (capacity no longer contaminates the inverter text).
  - `Sungrow 10kW SH10RT/SBR128 BATT`: 1 raw blob → two separate fragments (`Sungrow 10kW SH10RT`,
    `SBR128 BATT`) — still raw pending the brand-prefix/noise-strip fix (P2/P3).
  - Canonical `SAJ H2-10K-S3-A + 2 × SAJ B2-20.0-HV1 - 40kw hrs`: unchanged (no regression).
- **Conservative guarantees preserved:** never guesses an unknown model; source_examples still never
  resolve (the curated `… AND …` example now splits into raw fragments, none of which map to a
  canonical model — the no-resolution invariant holds); ambiguous capacity-only text stays raw for
  review; output still validates against `JobHardwarePatch`; read-only against the catalogue.
- **Scope:** backend parser runtime + tests only. No frontend, imports UI, Settings, NAS/proposal,
  scheduling parser, migrations, data files, or live import/commit/reverse/reset. No catalogue/alias
  or YAML-rule change.
- **Tests:** `tests/test_hardware_runtime.py` adds a P1 section (`/`, `and`, `&`, `·`/`•`+capacity,
  `with`-meter, no-over-split of model-internal hyphens, mid-fragment quantity preserved, the
  `·`-capacity-suffix split); the two `source_examples_never_match` tests (runtime + import) were
  updated to assert the no-resolution invariant rather than whole-string preservation. **611 backend
  tests pass** (45 in the two hardware files); hardware spec-validation green; `alembic check` clean.
- **Files:** `backend/app/hardware/runtime.py`, `backend/tests/test_hardware_runtime.py`,
  `backend/tests/test_import_hardware.py`; docs (CHANGES, DEVELOPER_HANDOFF). Permanent.
- **Deferred (next audit slices):** P2 brand-prefix normalization (`Solax Power …`, `Sungrow …`,
  `Neovolt …` — ~551 raw rows resolve once handled), P3 bucket routing (unmatched battery/metering
  text currently lands in the inverter field, 265 rows), P4 catalogue adds (T-BAT, X1-VAST, X3-ULT,
  Swatten all-in-one, Neovolt variants, Alpha extensions, missing brands), in-fragment capacity
  extraction for `16kw hrs battery`-style nouns, P6 metering vocab (`export meter`, `with meter`),
  and the full clean-wipe + reimport (still NOT authorized).

---

## 2026-06-23 — Job Detail H5D: install-date autosave + autosave polish (frontend only)

- **Why:** finish the Job Detail autosave pass. Install date was the last ordinary field still on a
  small Edit / Save / Cancel flow; convert it to save-on-change autosave (under its own permission) so
  the page is consistent, and apply small presentation/accessibility polish. Workflow controls (status,
  approval, delete, internal notes) stay deliberate and separate — this polishes the live model, it
  does not redesign anything.
- **What:**
  - **Install date → field-level autosave** (`JobDetailPage`): the Edit/Save/Cancel control (and its
    `installDate`/`editingInstall` local state + the `useEffect([job])` that synced it) is removed.
    For a user with the install-date permission it now renders the shared **`AutosaveControl`**
    (`kind="date"`) — the date saves the moment it changes, as a single-field `PATCH { install_date }`
    via the same `useUpdateJob` path, **never batched** with the descriptive details. Non-editors see
    the read-only value ("Not scheduled" when empty). Unchanged → no PATCH; a failed save keeps the
    value with inline Retry; a refetch never clobbers an in-progress edit — all inherited from the
    shared `useFieldAutosave`. **Permission is unchanged and still separate**: gated on
    `canEditJobInstallDate` (admin / scheduling, INSTALL_ROLES), distinct from descriptive edit.
  - **Unified indicators:** because install date now uses `AutosaveControl`, it shows the **same**
    Unsaved / Saving… / Saved ✓ / Error+Retry chip as the descriptive, structured, and hardware fields
    — no new visual language was introduced. Its errors are now inline (not the page-level banner).
  - **Approval auto-collapse (optional, UX only):** `JobApprovalControl` gained an optional `onSaved`
    callback fired on a successful Set-approval; Job Detail passes `() => setEditingApproval(false)` so
    the approval editor collapses back to the read view after a save. The mutation, permission gating
    (`canSetJobApproval`), and "label is law" rules are **unchanged**; approval is NOT autosave.
  - **HardwareSearchInput keyboard + ARIA polish (additive):** Escape closes the dropdown; Arrow
    Up/Down move a highlighted suggestion (wrap-around) and Enter selects the highlighted one; combobox/
    listbox/option ARIA roles + `aria-activedescendant` were added. All strictly additive — Enter only
    acts when a suggestion is highlighted (a state reachable only via the Arrow keys), so free-text
    typing, mouse selection, and the blur-commit flow are unchanged. **Import review is preserved:** the
    Escape handler does NOT `stopPropagation`, so in the import-review modal (whose own document-level
    Escape closes it) a single Escape still closes the modal exactly as before — it merely also collapses
    any open suggestion list in the same press (same end state). In Job Detail (no surrounding modal)
    Escape simply closes the dropdown. Import-review DATA behaviour is untouched.
- **Kept deliberately unchanged:** lifecycle **status** (immediate-save dropdown), **delete**
  (confirm), **internal notes** (its own notes panel), **approval** business rules; `AutosaveControl` /
  `AutosaveField` / `useFieldAutosave` (reused as-is); the backend, the hardware snapshot stability, and
  import review.
- **Scope:** frontend only — no backend, migration, parser/import, Settings, NAS/proposal/scheduling,
  or data-file change. No new dependencies.
- **Files:** `pages/JobDetailPage.tsx`, `components/JobApprovalControl.tsx`,
  `components/HardwareSearchInput.tsx`; docs (CHANGES, DEVELOPER_HANDOFF, business_rules). Permanent.
- **Verification:** frontend typecheck + lint (`--max-warnings 0`) + build clean; an esbuild+Node
  harness re-proved the `canAdoptServerValue` no-clobber predicate and the single-field
  `{ install_date: value || null }` mapping (no headless React runner is installed, so the no-op /
  retain-on-failure behaviour is inherited unchanged from the already-shipped `useFieldAutosave`);
  static scope + grep checks (old install-date flow gone, single-field PATCH, status/approval/delete/
  notes still present, ImportRowModal untouched). Two adversarial reviewers → GATE: PASS.
- **Deferred:** none material — the no-global-Save-button Job Detail model is complete across
  descriptive + structured + hardware + install-date fields. (Possible future: full screen-reader
  announcement of the autosave status via an aria-live region; per-field activity-log batching.)

---

## 2026-06-23 — Job Detail H5C: hardware fields autosave + retire the temporary edit flow (frontend only)

- **Why:** remove the last hardware-specific Save button. Job Detail hardware System fields now behave
  like the rest of the page — editable in place, saved when the user finishes interacting — with the
  same catalogue autocomplete + safe-provenance rules. The temporary "Edit hardware & approval" batch
  flow is retired and approval is decoupled into its own explicit affordance.
- **What:**
  - **`components/AutosaveHardwareField.tsx`** (new): wraps `useFieldAutosave` + `HardwareSearchInput`
    for one hardware field — typing invalidates any prior pick and **saves on blur** (free text drops
    stale catalogue ids); **clicking a catalogue suggestion saves immediately**, stamping
    `canonical_hardware_id_at_parse_time` + `confidence = manual_correction` (`parser_owned = false`);
    quantity (`N × MODEL`) round-trips; inline Saving…/Saved ✓/Error+Retry chip.
  - **`StructuredDetailsView`** gained an opt-in `renderAutosaveExtra` prop: when provided (Job
    Detail), each editable System-hardware extra renders that self-contained autosave control instead
    of the batch input. Import review passes none → its hardware extras keep the H3 batch flow.
  - **`JobDetailPage.saveHardwareField(field, value, selection)`** → `applyHardwareSystemEdits` with a
    single field key → `PATCH { details: { hardware: <one sub-section> } }` (panel / inverters /
    batteries / metering); the backend replaces only that sub-section. An unchanged blur sends nothing.
  - **`HardwareSearchInput`** gained an optional `onBlur` (free-text commit) and, when `onBlur` is set,
    a suggestion-button `onMouseDown preventDefault` so a pick can't blur-commit the partial text
    first. **`useFieldAutosave.commit`** gained `{ force }` so a re-selection persists provenance even
    if the visible text is unchanged. `AutosaveControl` now exports the shared status chip + error
    helper (reused by `AutosaveHardwareField`).
- **Retired:** the temporary hardware **Save/Cancel** bar, the **"Edit hardware & approval"** button,
  and all hardware batch state (`editingDetails`, `hardwareEdits`, `hardwareSelections`, `buildPayload`,
  `pendingPayload`, `saveDetails`, the page-level `describeError`). **Approval is decoupled**: it has
  its own small **"Edit approval" / "Done editing approval"** toggle (`editingApproval`), gated on
  `mayEditDetails` exactly as the old coupled button was — so who can edit approval, the "label is law"
  behaviour, and its own Set-approval mutation are **unchanged**; approval is NOT turned into autosave.
- **Untouched:** status, install date, delete, and internal notes keep their own flows. `details=null`
  jobs get no hardware inputs / no silent init; the read-only CT/electrical row and **Hardware Notes**
  stay read-only; Settings > Hardware still never live-updates a Job snapshot. **Import review
  (`ImportRowModal`) is byte-equivalent** (no `renderAutosaveExtra`/`onBlur`).
- **Scope:** frontend only — no backend, no migration, no parser/import/Settings/NAS/scheduling change.
- **Verification:** frontend typecheck + lint (`--max-warnings 0`) + build clean; an esbuild+Node
  harness confirmed a one-field edit builds only that sub-section, free text drops the stale id, a
  selection stamps the id, quantity round-trips, and the no-clobber predicate holds; two adversarial
  reviewers (hardware-autosave correctness incl. the blur-vs-click race + scope/import-review/approval)
  → GATE: PASS. No frontend unit-test runner; component behaviour covered by manual steps.
- **Files:** frontend `components/AutosaveHardwareField.tsx` (new), `components/AutosaveControl.tsx`,
  `components/HardwareSearchInput.tsx`, `components/structured/StructuredDetailsView.tsx`,
  `hooks/useFieldAutosave.ts`, `pages/JobDetailPage.tsx`; docs (CHANGES, DEVELOPER_HANDOFF,
  business_rules). Permanent.
- **Deferred:** H5D polish only (install-date → save-on-change under its own permission; unify the
  autosave indicators; optional per-field activity-log batching/debounce; the approval "Done" toggle
  could auto-collapse after a Set-approval). The no-global-Save-button Job Detail model is now
  complete for descriptive + structured + hardware fields.

---

## 2026-06-23 — Job Detail H5B: structured registry fields autosave (frontend only)

- **Why:** continue the no-Save-button overhaul — the structured registry-driven Job Detail fields now
  autosave per-field (same no-clobber/retain-on-error principles as H5A). Hardware is intentionally
  left on the temporary Edit/Save flow (H5C) so structured-field autosave isn't mixed with the
  autocomplete/provenance behaviour in one slice.
- **What:**
  - **`components/AutosaveControl.tsx`** (new): the shared autosave input — text / textarea / number /
    date / select — wrapping `useFieldAutosave`, committing on **blur** (text/textarea/number) or
    **change** (date/select), with the inline state chip (Unsaved / Saving… / Saved ✓ / Error+Retry).
    The single source of autosave UI; **`AutosaveField`** (H5A) was refactored to delegate to it (DRY;
    behaviour preserved, chip now sits beneath the input).
  - **`StructuredDetailsView`** gained an **opt-in** `autosaveField?: (path, value) => Promise<void>`
    prop: when provided (Job Detail, editors), each registry value field renders as an `AutosaveControl`
    and saves a single `section.key` leaf; when absent (import review), the existing batch
    `edits`/`onChange` path is **unchanged**. Also a `recordKey` prop so the local reveal state
    (show-empty + picker-added) resets only when the **record** changes, not on every per-field-save
    refetch (import review, passing no `recordKey`, keeps its `details`-object reset — unchanged).
  - **`JobDetailPage`**: structured registry fields are always-editable autosave for `canEditJobDetails`
    users (read-only otherwise) via a new `saveStructuredField(path, value)` →
    `buildDetailsPatch({ "section.key": value }, …)` → `PATCH { details: { section: { key } } }`
    (single-leaf, coerced, path-whitelisted; a no-op build sends nothing). The batch `detailsEdits`
    state, `handleDetailsChange`, and the structured part of `buildPayload` are **removed**.
- **Temporary (H5B):** **hardware** fields keep the batch Edit/Save flow — the Edit button is relabelled
  **"Edit hardware & approval"** and now governs only hardware + the approval control's edit form;
  `buildPayload`/`saveDetails` cover only the hardware sub-patch. H5C converts hardware to autosave and
  retires this batch entirely. **Approval editing gating is unchanged** (still revealed by that button).
- **Untouched:** status, approval (own Set-approval control), install date, delete, and internal notes
  keep their own flows. `details=null` jobs get no structured inputs and no silent `details` init.
  Derived/read-only registry fields stay read-only (the existing `isValueField` whitelist). **Import
  review (`ImportRowModal`) behaviour is byte-equivalent** (it passes no `autosaveField`/`recordKey`).
- **Scope:** frontend only — no backend, no migration, no parser/import/Settings/NAS/scheduling change.
- **Verification:** frontend typecheck + lint (`--max-warnings 0`) + build clean; an esbuild+Node
  harness confirmed the single-leaf `buildDetailsPatch` shape + no-op→null + number coercion, and the
  no-clobber predicate intact; two adversarial reviewers (autosave correctness + scope/import-review)
  → GATE: PASS. No frontend unit-test runner; component behaviour covered by manual steps.
- **Files:** frontend `components/AutosaveControl.tsx` (new), `components/AutosaveField.tsx` (refactor),
  `components/structured/StructuredDetailsView.tsx`, `pages/JobDetailPage.tsx`; docs (CHANGES,
  DEVELOPER_HANDOFF, business_rules). Permanent.
- **Deferred:** H5C (hardware fields autosave — retire the Edit/Save batch + the approval coupling),
  H5D (install-date → save-on-change, unify indicators, polish). Known minor: a structured job with no
  hardware still shows a "No changes" hardware Save bar in the temporary Edit mode (pre-existing from
  H5A; retired in H5C). Per-field autosave writes one `JOB_UPDATED` activity per changed field.

---

## 2026-06-23 — Job Detail H5A: field-level autosave foundation + top-level descriptive fields (frontend only)

- **Why:** begin the no-Save-button Job Detail overhaul — fields that are editable should be editable
  by default and persist when the user finishes interacting (blur for text, change for date), with no
  global Edit wall and no Save/Cancel bar. H5A lands the safe autosave foundation on the simplest
  fields first; structured details + hardware stay on the old batch Edit/Save flow **temporarily**
  until H5B/H5C.
- **What:**
  - **`hooks/useFieldAutosave.ts`** (new): a per-field state machine — `draft` + `status`
    (`idle/dirty/saving/saved/error`) + reconcile. The **keystone safety rule** (`canAdoptServerValue`):
    a refetched/window-focus server value is adopted into the draft **only when idle/saved**, **never
    while dirty/saving/error** — so a background refetch can't wipe an in-progress edit. `commit()`
    is a no-op if unchanged vs the last-saved value (no needless PATCH / activity row). On save
    **failure the typed value is retained** and a **Retry** is offered (nothing is lost). Saves on
    blur (text) / change (date), never per keystroke.
  - **`components/AutosaveField.tsx`** (new): label + input/textarea using the hook, with a small
    per-field indicator (**Unsaved / Saving… / Saved ✓ / Error + Retry**). Non-editors see a read-only
    value only.
  - **`pages/JobDetailPage.tsx`**: the **top-level descriptive fields** (title, sale_date — and, for
    legacy `details=null` jobs, the descriptive column textareas) are now **always-editable autosave**,
    each a **single-field PATCH** via the existing job-update endpoint. The old batch `form` state, the
    global `useEffect([job])` reset, and the Edit/Save/Cancel flow for these fields are **removed**.
    The **global `error` banner is no longer used by these fields** (per-field inline errors instead).
- **Temporary (H5A-only):** **structured details + hardware keep the existing Edit/Save batch flow**
  (the Edit button now reads "Edit hardware & structured" and only governs that block); `buildPayload`
  now covers only `details` + `hardware`. H5B (structured) and H5C (hardware) convert these to autosave.
- **Untouched:** **status** (immediate-save dropdown), **approval** (label-is-law control), **install
  date** (own Edit/Save + INSTALL permission), **delete** (confirm), and the **internal-notes** panel
  — all keep their own flows. `details=null` jobs get **no silent `details` initialization** (the
  descriptive top-level columns autosave; structured/hardware editing is simply not offered). Derived
  blobs (system_details/install_details on structured jobs) stay non-editable.
- **Permissions:** all autosave descriptive fields share the DESCRIPTIVE permission, gated by
  `canEditJobDetails` (admin/sales_admin); non-editors render read-only. No field crosses into the
  INSTALL permission, so no mixed-permission PATCH.
- **Scope:** frontend only — no backend, no migration, no parser/import/Settings/NAS/scheduling change.
- **Verification:** frontend typecheck + lint (`--max-warnings 0`) + build clean; the autosave
  no-clobber predicate verified via an esbuild+Node harness; two adversarial reviewers (autosave
  safety + scope/regression) → GATE: PASS. No frontend unit-test runner; component behaviour covered
  by manual steps + reasoning.
- **Files:** frontend `hooks/useFieldAutosave.ts` (new), `components/AutosaveField.tsx` (new),
  `pages/JobDetailPage.tsx`; docs (CHANGES, DEVELOPER_HANDOFF, business_rules). Permanent.
- **Deferred:** H5B (structured details autosave), H5C (hardware autosave), H5D (install-date →
  save-on-change, unify indicators, remove the remaining Edit/Save, polish). Activity-log volume note:
  per-field autosave writes one `JOB_UPDATED` activity per changed field (acceptable; revisit batching
  in H5D if needed).

---

## 2026-06-23 — Hardware Parser lane, H4: Job Detail hardware autocomplete (frontend only)

- **Why:** bring the H3 hardware-correction workflow (free text + catalogue autocomplete) to
  already-committed Jobs, so a staff member editing a Job can search the catalogue and correct
  Inverter / Battery / Panel / Metering — saving stable `Job.details.hardware` snapshots only.
- **What:** the Job Detail System hardware fields now use the **same** `HardwareSearchInput`
  autocomplete as import review (in edit mode). `JobDetailPage` gained `hardwareSelections` state +
  `handleHardwareSelect`, passes `renderExtraInput` (the autocomplete) to the **edit-mode**
  `StructuredDetailsView`, threads `hardwareSelections` into `applyHardwareSystemEdits(hw, edits,
  selections)`, and clears a field's selection on typing (so a stale canonical id can't attach to
  hand-edited text). Read-mode stays read-only; `details=null` jobs stay inert (no hardware inputs,
  no silent init). Save still uses the existing single job PATCH and only touches `details.hardware`.
  - **Provenance is identical to H3** (the shared `lib/hardwareDisplay.ts` is **unchanged**): a
    catalogue **selection** stamps `canonical_hardware_id_at_parse_time` (provenance only, never a
    live reference) + `confidence = manual_correction` + `parser_owned = false`; **free-typed** text
    drops any stale canonical id / catalogue model / parser provenance. Quantity round-trips.
- **Component move:** `HardwareSearchInput` moved from `components/imports/` to the neutral
  `components/HardwareSearchInput.tsx` (it is now shared by import review AND Job Detail). The only
  change to import review is `ImportRowModal`'s import path — **import-review behaviour is unchanged**.
- **Scope:** frontend only — **no backend**, no migration, **no parser/ingest/commit/reverse change**,
  **no Settings>Hardware change**, no import-review behaviour change, no NAS/proposal/scheduling. This
  is NOT the always-editable Job Detail overhaul (H5) — the existing Edit-button / permission gate is
  unchanged. Settings>Hardware catalogue edits still never live-update Job snapshots.
- **Verification:** frontend typecheck + lint (`--max-warnings 0`) + build clean. `hardwareDisplay.ts`
  untouched, so the H3 provenance assertions still hold (free-text drops stale id; selection stamps
  it; quantity round-trips). Two adversarial reviewers (wiring + scope) → GATE: PASS. No frontend
  unit-test runner; component behaviour covered by manual steps.
- **Files:** frontend `components/HardwareSearchInput.tsx` (moved here),
  `components/imports/HardwareSearchInput.tsx` (deleted), `components/imports/ImportRowModal.tsx`
  (import path only), `pages/JobDetailPage.tsx` (autocomplete wiring); docs (CHANGES,
  DEVELOPER_HANDOFF, business_rules). Permanent.
- **Deferred:** the always-editable Job Detail overhaul (H5); dropdown keyboard navigation / ARIA
  (non-blocking polish).

---

## 2026-06-23 — Hardware Parser lane, H3: import-review editable hardware UI with catalogue autocomplete (frontend only)

- **Why:** make parsed hardware correctable DURING import review, before commit — using the H1 search
  feed and the H2 import-review hardware-edit path. No Job Detail or Settings change; this is the
  import-review screen only.
- **What:** in the import row modal the parsed hardware now renders as **editable System fields**
  (Panel type / Inverter / Battery / Metering) with **catalogue autocomplete**, not a separate box.
  - **`HardwareSearchInput`** (new, `components/imports/HardwareSearchInput.tsx`): a free-text input
    that queries `GET /api/v1/hardware/search` (debounced, ≥2 chars, cached per q+category via the new
    `useHardwareSearch` hook) and offers canonical suggestions. Typing free text is always allowed and
    saved as-is; clicking a suggestion autofills the canonical display/model text (preserving any
    leading `N ×` quantity prefix) and records provenance.
  - **`StructuredDetailsView`** gained an optional `renderExtraInput` prop (custom input for an
    editable System-hardware extra) + an unobtrusive **"review"** marker when a field is
    low-confidence/unconfirmed (`SystemHardwareField.lowConfidence`/`category`, set by
    `deriveSystemHardware`). The marker never hides the value or disables the textbox.
  - **`ImportRowModal`** holds `hardwareEdits` + `hardwareSelections` state (reset on row change),
    folds `applyHardwareSystemEdits(...)` into the SAME `ImportRowEdit.details` patch as the registry
    edits (`details.hardware`), saved via the existing import-row edit API. Editable only on unlocked
    rows; committed/reversed rows stay read-only. **Raw cells** + **Hardware notes** are unchanged.
  - **Provenance rule (textbox text is the source of truth):** a catalogue **selection** stamps
    `canonical_hardware_id_at_parse_time` (the DB id — provenance/debug ONLY, never a live reference),
    `confidence = manual_correction`, `parser_owned = false`. **Free-typed** text (no selection) is
    saved as a fresh **manual** item (`parser_owned = false`, `source_type = manual`,
    `confidence = manual_correction`) that **drops any stale canonical id / catalogue model / parser
    provenance** — only the single original `source_fragment` is kept as evidence (never invented). A
    panel free-text edit likewise keeps only the panel **count** + `source_fragment` and drops the old
    catalogue model / id / descriptors (brand / wattage / model_options / array_kw), so a field can
    never display one model while silently carrying another's id. Typing after a pick clears that
    field's selection. Quantity round-trips (e.g. `2 × SAJ B2-20.0-HV1`).
- **Scope:** frontend/import-review only — **no backend**, no migration, **Job Detail page untouched**
  (it still calls the shared `applyHardwareSystemEdits`/`StructuredDetailsView` via their original,
  backward-compatible signatures — the new params are optional), no Settings>Hardware UI change, no
  parser/ingest/commit/reverse change, no NAS/proposal/scheduling.
- **Verification:** frontend typecheck + lint (`--max-warnings 0`) + build clean. The pure
  `hardwareDisplay` logic (category/lowConfidence derivation, selection provenance stamping, free-text
  vs selection, quantity round-trip, panel selection) verified via an esbuild+Node harness over the
  public exports (16 assertions). Two adversarial reviewers (data-flow + UX/scope) → GATE: PASS after
  fixing one found bug (a stale catalogue selection surviving a later free-text edit — now cleared on
  type). No frontend unit-test runner exists; component behaviour is covered by manual steps.
- **Files:** frontend `components/imports/HardwareSearchInput.tsx` (new),
  `components/imports/ImportRowModal.tsx`, `components/structured/StructuredDetailsView.tsx`,
  `lib/hardwareDisplay.ts`, `lib/hardware.ts`, `hooks/useHardware.ts`, `types/index.ts`; docs
  (CHANGES, DEVELOPER_HANDOFF, business_rules). Permanent.
- **Deferred:** Job Detail hardware fields using the same component (H4); always-editable Job Detail
  overhaul (H5); keyboard navigation / ARIA for the dropdown (non-blocking polish).

---

## 2026-06-23 — Hardware Parser lane, H1+H2: staff hardware search endpoint + editable import-review hardware (backend only)

- **Why:** backend foundation for searchable hardware textboxes (autocomplete) and for editing parsed
  hardware during import review before commit. No UI is built in this slice — it makes both live Jobs
  and import review able to read/validate the SAME hardware-snapshot shape before screens get
  autocomplete.
- **H1 — lean staff search endpoint:** new `GET /api/v1/hardware/search` (`endpoints/hardware.py`),
  gated on `get_current_user` (**any authenticated staff, NOT admin-only**). Returns ONLY **active
  (`is_active`) + non-deleted** canonical hardware as a **lean** `HardwareSearchResult`
  (`schemas/hardware.py`): `id, spec_id, category, display_name, canonical_model, brand, phases,
  nominal_kw, capacity_kwh, wattage_w, model_options` — and deliberately **never** aliases,
  `alias_count`, `attributes`, `spec_source`, `is_active`, `created_by`, timestamps, or deleted rows.
  Supports `q` (ILIKE over canonical_model/display_name/brand/spec_id) + `category` filtering. Reuses
  the existing `list_hardware` service via a new `active_only` flag (default `False`, so the admin
  catalogue list is unchanged). **All existing `/api/v1/hardware` catalogue + alias CRUD routes stay
  admin-only** (regression-tested). The route is declared before `/{hardware_id}` so "search" never
  falls through to the int route.
- **H2 — editable import-review hardware:** `import_review.apply_details_patch` now splits the
  `hardware` key out of a details patch and merges it via the **same shared helper** the live
  `Job.details` patch uses. The private `_merge_hardware` in `services/details_patch.py` was promoted
  to public **`merge_hardware_subsections`** and is now called by BOTH `merge_details_patch` (live)
  and `apply_details_patch` (review) — **one validation/merge, no divergence**. So an `ImportRowEdit`
  may carry `details.hardware`; it is validated by `JobHardwarePatch` (`extra='forbid'`) exactly like
  live + commit (invalid shape → 422), whole sub-sections replace, explicit `null` clears, absent
  sub-sections are preserved. `original_parsed` is still deep-copied on first edit (audit), raw
  workbook cells are untouched, preview/review/commit read the same stored `parsed.details.hardware`,
  and commit persists it verbatim (the parser is **not** re-run). Approve/reject/skip/group flows are
  unchanged. No `ImportRowEdit` schema change was needed — `details` is already a free dict.
- **Scope:** backend only — **no frontend**, **no migration** (reuses existing tables + JSONB;
  `alembic check` clean), no Settings>Hardware UI / CRUD change, no Job Detail UI change, no parser
  runtime behaviour change (only shared validation/merge plumbing), no NAS/proposal/scheduling, no
  live data/import/commit-to-live/reverse actions.
- **Verification:** new `tests/test_hardware_search.py` (auth-required 401, non-admin 200, active+
  non-deleted only, lean-keys/no-alias-leak, q/category filter, admin routes still 403); H2 tests in
  `tests/test_import_structured_edit.py` (apply accepts/merges hardware, combines with registry
  fields, rejects 4 invalid shapes, edit_row preserves original_parsed + raw, endpoint 200/422) and
  `tests/test_import_hardware.py` (review edit → preview → commit persists exactly; an impossible
  manual value surviving commit proves no re-parse). Full backend suite **602 passed**; `alembic
  current/check` clean; `git diff --check` clean; static scope scan = all changes backend `.py`. Two
  adversarial reviewers (H1 security / H2 correctness) returned GATE: PASS.
- **Files:** `backend/app/api/v1/endpoints/hardware.py`, `backend/app/schemas/hardware.py`,
  `backend/app/services/hardware.py`, `backend/app/services/details_patch.py`,
  `backend/app/services/import_review.py`, `backend/tests/test_hardware_search.py` (new),
  `backend/tests/test_import_structured_edit.py`, `backend/tests/test_import_hardware.py`; docs
  (CHANGES, DEVELOPER_HANDOFF, business_rules). Permanent.
- **Deferred (next):** frontend `HardwareSearchInput` + ImportRowModal editable hardware UI (H3),
  Job Detail hardware fields using the same component (H4), and the always-editable Job Detail
  overhaul (H5). When a user selects a catalogue result, the intended snapshot confidence is
  `manual_correction` and `canonical_hardware_id_at_parse_time` records the DB id as provenance only
  (never a live reference) — to be wired in H3/H4.

---

## 2026-06-23 — Hardware Parser lane, parser fix: preserve item quantity, keep capacity evidence out of model_text (backend)

- **Why (owner blocker):** a hardware cell like `SAJ H2-10K-S3-A + 2 × SAJ B2-20.0-HV1 - 40kw hrs`
  parsed wrongly — the battery **quantity (2) was effectively lost** to the reader and the trailing
  battery-capacity text (`40kw hrs`) was dumped into the **inverters** bucket, contaminating the
  inverter field. Hardware quantity is core hardware truth; it must be preserved, and capacity /
  evidence fragments must never contaminate a model_text.
- **What (runtime `app/hardware/runtime.py`, READ-ONLY parser):**
  - **Broader explicit-quantity detection** — `_QTY_RE` now accepts `N x` / `N × ` / `N*` (an
    x / × / * separator with optional spacing), so e.g. `2*SAJ B2-20.0-HV1` is recognised as
    quantity 2, not raw text. The quantity is stored on the item's `quantity` field.
  - **Safe bare-number quantity** — a bare `N MODEL` (no separator) is split into a quantity ONLY
    when the stripped remainder resolves to a catalogue model (`_extract_bare_quantity`, gated on a
    hit). So real quantities like `2 SAJ B2-20.0-HV1` are captured, while unit / capacity / phase
    text (`40kw hrs`, `10kw 3 phase`) — which never resolves — is **never** mis-split.
  - **Capacity-evidence routing** — an unmatched fragment that is pure battery ENERGY capacity
    (`_CAPACITY_RE`: `40kw hrs` / `40kwh` / `30kw hr`, but NOT bare `10kw` power) is preserved as a
    hardware note in `site_notes.raw_misc` (surfaced read-only under "Hardware notes"), never as an
    inverter/battery item and never glued onto a model_text.
  - **No quantity duplication** — an UNMATCHED fragment carrying an explicit `N ×` prefix now stores
    the model **core** as `model_text` with the quantity held separately (so the UI renders the
    quantity once, paired with the display-side fix in the UX entry below).
- **Invariants preserved:** never guesses an unknown model (unmatched useful text stays
  `unconfirmed_raw_text` + a warning); never matches `source_examples`; output still validates against
  `JobHardwarePatch` (`extra='forbid'`); reads only, mutates nothing. The import bridge
  (`enrich_row_hardware`) is unchanged — it simply stores the improved snapshot (parsed once at
  ingest; preview = commit).
- **Scope:** backend parser runtime only — **no** catalogue / alias mutation, **no** Settings >
  Hardware change, **no** rules-config (YAML spec) change, **no** import-pipeline behaviour change
  beyond better parser output, **no** migration, **no** NAS/proposal/scheduling.
- **Deferred (documented follow-up):** middot-glued capacity suffixes (`MODEL · 20kWh` in one
  fragment) are not yet split — the existing `_split_fragments` only breaks on `+` and ` - `; the
  reported blocker (dash-separated `- 40kw hrs`) is covered. Per-item quantity editing via a
  dedicated field is also still deferred.
- **Verification:** new focused runtime tests (`test_hardware_runtime.py`) for the exact bundle +
  all separator variants (`×`, `x`, `*`, bare) + bare-number safety + bare-`kw`-not-capacity +
  unmatched-prefix-strips-core; import-path test (`test_import_hardware.py`) proving the stored
  snapshot has quantity 2 + capacity in `raw_misc`. Full backend suite **590 passed**. Three
  adversarial reviewers (parser / display / tests) returned GATE: PASS.
- **Files:** `backend/app/hardware/runtime.py`, `backend/tests/test_hardware_runtime.py`,
  `backend/tests/test_import_hardware.py`; docs (CHANGES, DEVELOPER_HANDOFF, business_rules).
  Permanent.

---

## 2026-06-23 — Hardware Parser lane, UX correction: parsed hardware shown + edited as normal System fields (frontend)

- **Why (owner correction):** parsed hardware must appear as **normal Job Detail System fields**
  (Panel type / Inverter / Battery / Metering·CT — alongside Number of panels / Storey / Phase / Roof
  type), with the key ones **editable as textboxes**, NOT a separate hardware box. The visible
  value shows **regardless of confidence** (low confidence does not hide it); only supplemental flags
  go to "Hardware notes". Raw workbook text is provenance (import-review Raw cells), not the
  job-facing value. Presentation/data-shape only — the Stage 3A/4A/4B backend is unchanged
  (Job.details.hardware is the durable snapshot; Settings > Hardware never live-updates Jobs).
- **What:** a shared `lib/hardwareDisplay.ts` derives from the snapshot: `deriveSystemHardware` →
  the System hardware fields (**Panel type, Inverter, Battery, Metering**, plus a read-only **CT /
  electrical** row from site-notes) showing ALL parsed values; `deriveHardwareNotes` →
  **supplemental** flags only (low-confidence/`manual_review` items, ambiguous `model_options`,
  `warnings`, `raw_misc`) — never the only place inverter/battery values appear;
  `applyHardwareSystemEdits` → maps an edited textbox back into a partial `details.hardware` patch.
- **Editable in System:** `StructuredDetailsView` gains opt-in `hideKeys` + `systemExtras` +
  `extraEdits`/`onExtraChange`. In Job Detail edit mode the System hardware fields render as
  **textboxes** (Panel type / Inverter / Battery / Metering) whose edits fold into the SAME job
  PATCH as `details.hardware` (alongside the registry field edits) — updating the Job snapshot only,
  never Settings > Hardware or the catalogue. The raw `panel`/`inverter` registry fields are hidden
  when a snapshot exists; Number-of-panels / Storey / Phase / Roof type stay registry fields.
- **Item quantity shown + round-tripped:** an item with `quantity > 1` renders inline as
  **"N × MODEL"** (e.g. `2 × SAJ B2-20.0-HV1`), and editing round-trips — a saved "N × MODEL" splits
  back into `quantity: N` + clean `model_text` (the prefix is never baked into the model text, so it
  is never doubled). Absent prefix on a single-item edit means quantity 1. So an explicit hardware
  quantity is **never lost in the UI** (paired with the parser-side fix; see the entry below).
- **No separate hardware box:** `JobHardwareSection.tsx` is **deleted**; the only separate area is a
  small read-only `HardwareNotes` (supplemental). When `details.hardware` is absent, the legacy
  System display is **unchanged**; `details=null` safety is intact.
- **Import review shows parsed hardware (read-only):** `ImportRowModal` passes `systemExtras` +
  `hideKeys` (no `onExtraChange`, so read-only there) and renders Hardware notes, so reviewers see the
  parsed hardware values that will commit. The **Raw cells** panel is untouched (raw provenance kept).
- **No backend change** (the 4B snapshot is the source; the existing `{ details: { hardware } }`
  PATCH persists edits). Scope: frontend only — **no migration**, no Settings > Hardware change, no
  parser matching-rule change, no NAS/proposal/scheduling, no catalogue dropdown/live lookup.
- **Deferred:** editing item quantity via a dedicated field (it is edited inline as the "N ×" prefix;
  a multi-item rebuild defaults un-prefixed entries to quantity 1) and site-note CT/export editing
  (read-only).
- **Verification:** frontend typecheck + lint (`--max-warnings 0`) + build clean; backend hardware/
  import/snapshot regression green (no backend change). No frontend unit-test runner.
- **Files:** frontend `lib/hardwareDisplay.ts` (new), `components/HardwareNotes.tsx` (new),
  `components/structured/StructuredDetailsView.tsx` (`hideKeys` + editable `systemExtras`),
  `pages/JobDetailPage.tsx` (editable System hardware fields + Hardware notes; remove the box),
  `components/imports/ImportRowModal.tsx` (review shows parsed hardware read-only),
  `components/JobHardwareSection.tsx` (**deleted**); docs (CHANGES, DEVELOPER_HANDOFF, business_rules).
  Permanent.

---

## 2026-06-22 — Hardware Parser lane, Stage 4B: import integration for parsed hardware snapshots (backend)

- **Why:** Stage 4A built the parser runtime in isolation; 4B is the first LIVE import integration —
  the catalogue starts influencing import results. The keystone is **no preview/commit divergence**:
  hardware is parsed ONCE at ingest and stored on the row, so preview/review and commit read the same
  value. Backend only — **no frontend review UI** (Stage 4C), no NAS/proposal, no scheduling parser,
  no Settings UI change, no migration.
- **What:** a new `services/import_hardware.py` bridge with `enrich_row_hardware(db, parsed)` and
  `validate_committed_hardware(details)`. **Ingest** (`import_ingest.ingest_worksheet`) now calls
  `enrich_row_hardware` per parsed row — DB-aware, where the session lives (the pure `import_parser`
  stays DB-free) — running the Stage-4A `parse_hardware` on the row's `inverter_raw` / `panel_raw` /
  `no_of_panels` and storing the result at **`ImportRow.parsed["details"]["hardware"]`**.
- **Single source (no divergence):** preview (`map_job_preview` → `out["details"] = parsed.details`)
  and review (`ImportRowRead.parsed`) already return `parsed.details`, so they surface the stored
  hardware with **zero preview/schema changes**. **Commit** (`import_commit.build_job_data`) already
  copies `parsed.get("details")` into `Job.details`, so the stored snapshot persists verbatim into
  `Job.details.hardware` — the parser is **NOT re-run at commit**. (If a legacy row has no stored
  `details`, commit falls back to `build_details`, which simply yields no hardware — never a re-parse.)
- **Commit-boundary validation:** `build_job_data` now runs `validate_committed_hardware` (a
  `JobHardwarePatch.model_validate`) before persisting, so a malformed stored snapshot raises and
  **fails that single row safely** (`_commit_one` rolls it back — no orphan, other rows unaffected).
- **Reverse:** unchanged. Tests prove a pristine imported hardware job reverses cleanly, and that a
  post-commit hardware edit trips the existing pristine guard (`job_modified` / `job_has_activity`),
  so reverse is blocked and the edit is preserved — **no hardware-specific reverse logic added**.
- **Hard rules preserved:** `parse_hardware` stays read-only (no catalogue/alias/job mutation — the
  only write is the row's `parsed` JSON); `source_examples` still never match through the import path;
  unknown/unmatched useful text is preserved, never guessed; legacy `details.system.panel/inverter`
  text **coexists** (untouched). Settings > Hardware edits still never mutate existing Job snapshots.
- **Scope:** backend only — **no migration** (alembic head `c3d4e5f6a7b8`), no frontend review UI,
  no Settings UI, no NAS/proposal, no scheduling parser. **Deferred:** Stage 4C (review display
  polish + uncertain/manual-review badges), and the Stage-4A follow-ups (full multi-fragment bundle
  parsing, panel system-size derivation). Per-row index rebuild in `parse_hardware` (one alias query
  per enriched row) is acceptable for a manual import; a shared-index optimisation is a follow-up.
- **Tests:** `tests/test_import_hardware.py` (10) — end-to-end ingest populates `parsed.details.hardware`
  (representative inverter/panel/metering), preview + commit use the same stored snapshot, commit
  writes exactly it, commit-boundary rejects malformed safely, pristine reverse works, reverse blocked
  after a post-commit hardware edit, source_examples don't match through import, legacy fields coexist,
  enrichment is read-only. Import commit/reverse/parse regression green; full backend suite passes;
  `alembic check` clean.
- **Files:** backend `services/import_hardware.py` (new), `services/import_ingest.py` (enrich),
  `services/import_commit.py` (commit-boundary validation), `tests/test_import_hardware.py` (new);
  docs (CHANGES, DEVELOPER_HANDOFF, business_rules). Permanent.

---

## 2026-06-22 — Hardware Parser lane, Stage 4A: standalone hardware parser runtime (the catalogue consumer)

- **Why:** Stages 1–3 built the catalogue, its admin UI, and the editable Job snapshot — but nothing
  yet *consumed* the catalogue. Stage 4A builds the **parser runtime in isolation** (the "brain")
  and proves it emits a valid, stable `JobHardwarePatch` snapshot BEFORE any import wiring — so we
  never wire preview/commit/reverse around an unproven parser. **No import/preview/commit/reverse/
  frontend-review/NAS/scheduling wiring** in this slice.
- **What:** a read-only `app/hardware/runtime.py` (`parse_hardware`) + a versioned-config loader
  `app/hardware/rules.py`. The runtime is **source-agnostic** (inputs = strings + `source_type`/
  `source_field`, not sheet columns): it reads the admin-editable **DB catalogue + aliases** and the
  **versioned policy** (normalization, ignore rules, specific corrections, guard phrases, site-note
  keyword buckets, panel brand/wattage routing, confidence vocab, pinned `parser_rule_version`) and
  produces inverters / batteries / metering / panel / site_notes / warnings. Output is **validated
  against `JobHardwarePatch`** (the adapter) before return.
- **Matching:** exact / loose / case_sensitive aliases (Jinko 440 ≠ JINKO 440 → different panels);
  loose → low confidence; metering first-class; `source_examples` can never match (not seeded as
  aliases); guard phrases suppress inference unless a specific correction overrides; ignore rules
  drop noise; unknown useful text is **preserved as editable raw text, never guessed**; panels keep
  **`model: null`** unless a real catalogue model is confidently identified, ambiguous → `model_options`,
  brand-only / wattage-only preserve text. **Mutates nothing** (catalogue/aliases/jobs/imports).
- **C1 resolved (owner decision):** `Job.details.hardware.site_notes` ct/export_limit/underground/
  comms are now **lists** (`list[str] | None`), faithful to the spec's array buckets — a JSON-shape
  change only, **no DB migration**. Backend `schemas/job_hardware.py` + frontend `types/imports.ts`
  + the Stage-3B editor (site-note fields → one-per-line textareas) + the Stage-3A snapshot test were
  updated together.
- **C2 resolved (owner decision):** `ignored` / `raw_evidence` stay **parser-internal** (not snapshot
  fields); review-facing parser messages go to `hardware.warnings`; each item keeps `source_fragment`.
  No new top-level snapshot fields. `parser_rule_version` kept pinned as-is (`hardware_parser_rules_v8`
  for hardware, `panel_rules_v1_1` for panel). `canonical_hardware_id_at_parse_time` is the DB id,
  provenance/debug only (never display truth).
- **Scope:** backend service + tests + the C1 schema/frontend-compat change only — **no import
  ingest/preview/commit/reverse change, no frontend review UI, no NAS/proposal, no completed-sheet
  runtime, no scheduling parser, no migration**. Legacy `details.system.panel/inverter` text coexists
  unchanged.
- **Deferred (documented follow-up):** full multi-fragment **bundle** parsing (nested quantities /
  capacity suffixes), panel **system-size derivation** (needs proposal/NAS evidence), and the import
  wiring (Stage 4B). The runtime handles single/simple cells today.
- **Tests:** `tests/test_hardware_runtime.py` (16) — exact/loose/case-sensitive matching,
  source_examples-never-match, guard suppression, correction override, ignore rules, unknown
  preserved, panel model-null + model_options, metering first-class, list site_notes, output
  validates against `JobHardwarePatch`, no catalogue mutation, + a panel-fixture model-null subset.
  Stage-0 spec validator still green; full backend suite **571 passed** (555 + 16); `alembic check`
  clean (no migration); frontend typecheck/lint/build clean.
- **Files:** backend `hardware/runtime.py` (new), `hardware/rules.py` (new),
  `tests/test_hardware_runtime.py` (new), `schemas/job_hardware.py` (site_notes lists),
  `tests/test_jobs_hardware_snapshot.py` (site_notes list); frontend `types/imports.ts` +
  `components/JobHardwareSection.tsx` (site_notes lists); docs (CHANGES, DEVELOPER_HANDOFF,
  business_rules, database_schema). Permanent.

---

## 2026-06-22 — Hardware Parser lane, Stage 3B: Job Detail hardware snapshot UI (frontend)

- **Why:** Stage 3A added backend storage + the safe `hardware` patch path; 3B makes the Job-owned
  hardware snapshot visible and editable on the Job Detail page. Completes Stage 3 (the place
  hardware lives on a Job). No parser runtime, import wiring, or catalogue dropdowns.
- **What:** a new compact **Hardware** section on Job Detail (`components/JobHardwareSection.tsx`),
  rendered as a full-width card below Details (the top "other jobs" panel + all existing sections
  are untouched). Read view lists inverters / batteries / metering (model text × qty + subtle,
  non-noisy provenance), the panel (display name / model / brand / wattage / array kW / options),
  site notes, and warning chips. Edit (Edit / Cancel / Save, gated by `canEditJobDetails`) gives
  textbox/number fields with **add / edit / remove rows** for each line-item list, panel fields, site
  notes, and warnings (textarea). A standing note reads "Editable job snapshot — does not update
  from Settings > Hardware."
- **Save:** the whole hardware object is sent through the **existing** Job details PATCH
  (`useUpdateJob` → `{ details: { hardware: ... } }`) — no new API/hook. Each sub-section is sent so
  the saved snapshot matches the editor (empty list / null panel clears it); unedited provenance
  fields (`confidence`, `source_fragment`, `parser_owned`, `source_type`,
  `canonical_hardware_id_at_parse_time`, …) are carried untouched, so they round-trip. Non-hardware
  Job details are preserved by the backend partial-merge. Frontend snapshot types
  (`JobHardwareSnapshot`/item/panel/site_notes, added to `types/imports.ts` + a typed `hardware?` on
  `ParsedDetails`) match the backend exactly, so a loaded snapshot re-saves without an
  `extra='forbid'` rejection.
- **details=null:** the backend rejects structured edits on a null-details job, so the section shows
  a clear read-only note — "Hardware editing is available once structured job details exist." — and
  does NOT attempt to initialise details (no backend support for that; left as a deferred decision).
- **Hard snapshot rule:** the section reads only `job.details.hardware`; it never reads
  `hardware_catalogue`, uses no catalogue dropdowns, and does not live-update from Settings > Hardware.
  `canonical_hardware_id_at_parse_time` is carried as data but never displayed as truth (display uses
  `model_text` / `display_name`). 403/404/422 are handled with clear copy.
- **Scope:** frontend only — **no backend change**, no migration, no parser runtime, no import/
  commit/preview/reverse wiring, no Settings > Hardware change, no NAS/proposal, no
  `HARDWARE_UNCERTAIN`, no catalogue dropdown / live lookup.
- **Verification:** frontend `typecheck` + `lint` (`--max-warnings 0`) + `build` all clean (163
  modules). No frontend unit-test runner in the project.
- **Files:** frontend `components/JobHardwareSection.tsx` (new), `pages/JobDetailPage.tsx` (render
  the section), `types/imports.ts` (snapshot types + `ParsedDetails.hardware`); docs (CHANGES,
  DEVELOPER_HANDOFF, business_rules). Permanent.

---

## 2026-06-22 — Hardware Parser lane, Stage 3A: Job.details.hardware editable snapshot (backend)

- **Why:** Stage 2B made the catalogue manageable; nothing yet *consumes* it. Stage 3 creates the
  PLACE hardware lives on a Job — an editable, durable SNAPSHOT, independent of the catalogue. The
  slice is split per the owner's pre-authorisation: **Stage 3A = backend snapshot storage + patch/
  schema support** (this), **Stage 3B = the Job Detail hardware UI** (next). No parser runtime,
  import wiring, or catalogue read in this stage.
- **What:** Job hardware is stored under `Job.details.hardware` (JSONB — **no new table, no
  migration**): `inverters` / `batteries` / `metering` line-item lists, a `panel` object,
  `site_notes`, and `warnings`. The existing path-restricted Job-details PATCH now accepts the
  `hardware` key, validated by a new strict schema `schemas/job_hardware.py` (`JobHardwarePatch`,
  every model `extra='forbid'`) — the schema is the safety boundary (unknown fields / wrong types →
  422), the analog of the flat `<section>.<key>` path whitelist used for the other sections. Each
  PROVIDED sub-section replaces that whole sub-section; absent ones are preserved; an explicit null
  clears one. All other details paths keep their exact existing behaviour.
- **Hard snapshot rule (enforced + tested):** Jobs store snapshots, not live references; Settings >
  Hardware catalogue edits, alias edits, and hardware soft-delete/restore NEVER mutate an existing
  Job snapshot; Job hardware stays staff-editable; `canonical_hardware_id_at_parse_time` is
  provenance/debug only (never display truth); display depends on stored snapshot text, not current
  catalogue state; parser/reparse refresh is out of scope.
- **Safety preserved:** the change is isolated to `merge_details_patch` (live-job details only —
  import rows use a separate path, untouched). The NULL-details guard still rejects structured edits
  on a `details=null` job (422). `system_details`/`install_details` re-derivation is unaffected
  (hardware is not a legacy blob). Existing jobs without `details.hardware` read/render safely.
- **Scope:** backend only — no frontend (that is 3B), no parser runtime, no import/commit/preview/
  reverse change, no completed-sheet/panel runtime, no NAS/proposal, no `HARDWARE_UNCERTAIN`, no
  catalogue-to-job refresh, **no migration** (alembic head stays `c3d4e5f6a7b8`).
- **Tests:** `tests/test_jobs_hardware_snapshot.py` (8) — set/read snapshot; partial sub-section
  patch preserves other sub-sections + non-hardware details; flat paths still patch alongside
  hardware; invalid shape (`extra='forbid'`/wrong type/non-object/null) → 422 + job unchanged;
  hardware edit does not touch `hardware_catalogue`; catalogue rename/soft-delete/restore does not
  mutate a Job snapshot; null-details job still 422; job without hardware serialises safely. Full
  backend suite **555 passed** (547 + 8); `alembic check` clean.
- **Files:** backend `schemas/job_hardware.py` (new), `services/details_patch.py` (hardware branch),
  `tests/test_jobs_hardware_snapshot.py` (new); docs (CHANGES, DEVELOPER_HANDOFF, business_rules,
  database_schema). Permanent.

---

## 2026-06-22 — Hardware Parser lane, Stage 2B-3: Settings > Hardware alias management UI

- **Why:** completes the Settings > Hardware admin surface. 2B-1 read the catalogue, 2B-2 added
  catalogue write actions; 2B-3 adds **alias management** for a selected hardware item so admins can
  curate the matchable aliases that drive FUTURE parser matching — without code changes.
- **What:** a per-row **Aliases** action (active hardware rows) opens a new `HardwareAliasModal` for
  that item. The modal clearly names the item (display/canonical name + `spec_id`), shows its
  aliases in a table (alias value, type, confidence override, decision_log_id, Active/Deleted
  state), with a **Show: All / Active / Deleted** filter, an inline **Add / Edit** form, per-alias
  **Delete** (recoverable soft-delete, `window.confirm`) and **Restore**. Alias type vocabulary is
  exactly **exact / loose / case_sensitive** — `source_examples` are never aliases and never appear.
- **Data layer:** `lib/hardware.ts` gains `listAliases` / `createAlias` / `updateAlias` /
  `deleteAlias` (soft) / `restoreAlias`; `hooks/useHardware.ts` gains `useHardwareAliases` +
  `useCreate/Update/Delete/RestoreAlias`. Every alias mutation invalidates the whole `['hardware']`
  key, which prefix-matches the catalogue list, the facet dropdowns AND each item's alias list — so
  `alias_count` on the list and the open alias panel both refetch. New `HardwareAlias` /
  `HardwareAliasListResponse` / `HardwareAliasCreateInput` / `HardwareAliasUpdateInput` types mirror
  the backend alias schemas.
- **Errors:** 409 → "An alias with that value and type already exists for this hardware" (the unique
  (hardware_id, alias, alias_type)); 400 → alias required; 403/404/422 handled inline.
- **Permissions:** unchanged — the gear + `/settings` route group are admin-only and the backend
  enforces `require_admin` on every alias route. Normal users have no UI path to aliases (the alias
  surface is only reachable from the admin-gated Settings > Hardware screen).
- **Snapshot stability:** the modal note and the delete confirm both state that removing an alias
  affects future parser matching only — existing Job hardware snapshots are unchanged (the catalogue
  has no link to/from Jobs). Soft-deleted aliases are restorable and travel with their hardware item
  (hardware restore keeps aliases, from Stage 2A).
- **Scope:** frontend only — **no backend change**, **no migration**, no parser runtime, no
  Job.details / Job hardware snapshot UI, no import wiring, no completed-sheet/panel runtime, no
  NAS/proposal, no `HARDWARE_UNCERTAIN`, no `source_example` alias type. This **completes Stage 2B**
  (the Settings > Hardware admin-management surface).
- **Verification:** frontend `typecheck` + `lint` (`--max-warnings 0`) + `build` all clean (162
  modules). Backend untouched, so backend tests were not re-run.
- **Files:** frontend `components/HardwareAliasModal.tsx` (new), `pages/SettingsHardwarePage.tsx`
  (Aliases action + modal), `lib/hardware.ts` (alias helpers), `hooks/useHardware.ts` (alias hooks),
  `types/index.ts` (alias types); docs (CHANGES, DEVELOPER_HANDOFF). Permanent.

---

## 2026-06-22 — Hardware Parser lane, Stage 2B-2: Settings > Hardware catalogue write UI (create/edit/delete/restore)

- **Why:** Stage 2B-1 made the catalogue *visible* (read-only). 2B-2 adds the catalogue **write**
  actions to the same admin screen so admins can add/edit/soft-delete/restore canonical hardware
  without code changes. Alias management is still **Stage 2B-3** (not in this slice).
- **What:** the existing `SettingsHardwarePage` gains a **New hardware** action, per-row **Edit** /
  **Delete** (active rows) and **Restore** (deleted rows), and a shared `HardwareFormModal`
  (create + edit). Fields are **category-aware** — category, spec_id, canonical_model, display_name,
  brand always; phase + nominal_kw for inverters; capacity_kwh for batteries; wattage_w +
  model_options for panels (metering has no size). `spec_id` is required on create and **read-only
  on edit** (immutable). Edit sends a **true partial PATCH** — only fields whose value actually
  changed — so an edit never rewrites or silently wipes a field the user did not touch (the backend
  `exclude_unset` drops omitted keys but not explicit nulls, so a blanket-null payload would clear
  untouched columns); switching an entry's category still nulls the now-invalid old-category fields
  (they differ). Delete uses a `window.confirm` (recoverable soft-delete) like the existing
  contact-variant archive; Restore is an explicit one-click action.
- **Data layer:** `lib/hardware.ts` gains `createHardware` / `updateHardware` / `deleteHardware`
  (soft) / `restoreHardware`; `hooks/useHardware.ts` gains `useCreateHardware` /
  `useUpdateHardware` / `useDeleteHardware` / `useRestoreHardware`, each invalidating the whole
  `['hardware']` key so the list **and** the brand/phase facet dropdowns refetch after any change.
  New `HardwareCreateInput` / `HardwareUpdateInput` types mirror `HardwareCatalogueCreate/Update`.
- **Errors:** 409 → "That spec id already exists" (duplicate spec_id), 400 → spec_id required,
  403 → permission, 404 → entry gone (refresh), 422 → invalid value. Modal shows them inline;
  row-action (delete/restore) failures show an inline banner above the table.
- **Permissions:** unchanged from 2B-1 — the gear + `/settings` route group are admin-only and the
  backend enforces `require_admin` on every write route. Non-admins have no UI path.
- **Snapshot stability:** the page note and a modal note both state catalogue changes affect future
  parser matching only; the delete confirm repeats it ("Existing Job hardware snapshots are not
  affected").
- **Scope:** frontend only — **no backend change**, **no migration**, no parser runtime, no
  Job.details / Job hardware snapshot UI, no import wiring, no completed-sheet/panel runtime, no
  NAS/proposal, no `HARDWARE_UNCERTAIN`, **no alias UI** (that is 2B-3). `is_active` and freeform
  `attributes` are intentionally not exposed (defaults preserved; PATCH leaves them untouched).
- **Verification:** frontend `typecheck` + `lint` (`--max-warnings 0`) + `build` all clean (161
  modules). Backend untouched, so backend tests were not re-run.
- **Files:** frontend `components/HardwareFormModal.tsx` (new), `pages/SettingsHardwarePage.tsx`
  (write actions), `lib/hardware.ts` (write helpers), `hooks/useHardware.ts` (mutations),
  `types/index.ts` (input types); docs (CHANGES, DEVELOPER_HANDOFF). Permanent.

---

## 2026-06-22 — Hardware Parser lane, Stage 2B-1: Settings > Hardware UI (read-only catalogue list)

- **Why:** Stage 2B (the Settings > Hardware admin UI) is broad — the app's first Settings area, a
  shell access point, the API/types/hooks layer, the catalogue list/filter/deleted view, hardware
  CRUD, and alias management. Per the owner's pre-authorised split it ships in slices: **2B-1 =
  Settings shell + read-only catalogue list** (this), **2B-2 = create/edit/soft-delete/restore**,
  **2B-3 = alias management**. 2B-1 makes the Stage-2A catalogue *visible* in the app.
- **What:** the app's **first Settings area** — an admin-only gear in the top bar
  (`canManageHardware`, admin-only) → `/settings/hardware`, a `SettingsLayout` shell (left sub-nav)
  nested in the app shell, and a **read-only** `SettingsHardwarePage`: debounced search (`q`),
  filters by category / brand / phase / category-aware size (kW · kWh · W), an Active / Deleted /
  All view, a scannable table (name, category, brand, phase, size, alias count, Active/Deleted
  state), and pagination. Brand + phase options are derived from the catalogue under the current
  category + deleted scope (one ≤200-row facet query; covers the whole ~167-row catalogue today).
- **Read API/types/hooks foundation:** `lib/hardware.ts` (`listHardware`), `hooks/useHardware.ts`
  (`useHardwareList`), and `types` (`HardwareCatalogueEntry` + `HardwareCategory` /
  `HardwareAliasType` / `HardwareDeletedMode`) mirroring `schemas/hardware.py`. Write helpers/hooks
  (create/edit/delete/restore, aliases) land with their UI in 2B-2 / 2B-3.
- **Permissions:** the gear is hidden for non-admins and the `/settings` route group is
  `ProtectedRoute allowedRoles={['admin']}`; the backend already enforces `require_admin` on every
  hardware route (defence-in-depth — the UI never relies on frontend gating alone). Normal users
  get no UI path to the catalogue or to aliases.
- **Snapshot stability surfaced, not changed:** a standing note on the page reads "Catalogue and
  alias changes affect future parser matching only. Existing Job hardware snapshots do not change."
- **Scope:** frontend only — **no backend change**, no parser runtime, no Job hardware snapshot UI,
  no import wiring, no completed-sheet/panel integration, no NAS/proposal, no `HARDWARE_UNCERTAIN`
  change, **no migration**. No create/edit/delete/restore or alias controls yet (2B-2 / 2B-3).
- **Verification:** frontend `typecheck` + `lint` (`--max-warnings 0`) + `build` all clean (the
  project has no frontend unit-test runner). Backend untouched, so backend tests were not re-run.
- **Files:** frontend `lib/hardware.ts` (new), `hooks/useHardware.ts` (new),
  `components/SettingsLayout.tsx` (new), `pages/SettingsHardwarePage.tsx` (new), `types/index.ts`
  (hardware read types), `auth/permissions.ts` (`canManageHardware`), `components/AppLayout.tsx`
  (gear), `App.tsx` (settings routes); docs (CHANGES, DEVELOPER_HANDOFF, PROJECT_OVERVIEW).
  Permanent.

---

## 2026-06-20 — Hardware Parser lane, Stage 2A: admin catalogue + alias API (backend only)

- **Why:** Stage 2 (Settings > Hardware) is large, so it is split per the owner's pre-authorised
  plan: **Stage 2A = backend admin API** (this), **Stage 2B = the Settings > Hardware UI** (next).
  2A gives admins a programmatic way to view/search/filter/manage the Stage-1 catalogue + aliases.
- **What:** new `/api/v1/hardware` router — **every route is admin-only** (`require_admin`, reads
  AND writes), so the catalogue management API and especially aliases are never reachable by a
  normal user. Catalogue: `GET` (search `q` + filters: category / brand / phase / nominal_kw /
  capacity_kwh / wattage_w + `deleted=exclude|only|include` + pagination), `POST` create,
  `GET/{id}`, `PATCH/{id}` (spec_id immutable), `DELETE/{id}` (**soft-delete**),
  `POST/{id}/restore`. Aliases (nested, admin-only): `GET/POST /{id}/aliases`,
  `PATCH/DELETE /{id}/aliases/{alias_id}`, `POST .../restore`. New `services/hardware.py` +
  `schemas/hardware.py`. List rows carry an active `alias_count`.
- **Behaviour:** soft-delete only — **never hard-deletes**; deleted entries leave the default list
  and appear under `deleted=only` (the DELETED section), restorable with aliases intact (soft-
  deleting hardware does not touch its aliases). Alias types are exactly exact / loose /
  case_sensitive (no source_example); the unique (hardware_id, alias, alias_type) is enforced —
  creating a same-key alias that was soft-deleted RESTORES it (no true duplicate); an active dup →
  409. `spec_id` is immutable + unique (admin-created entries get `spec_source='admin'`).
- **Snapshot-stability preserved + scope:** the catalogue still has NO link to/from Jobs; **no**
  parser runtime, Job snapshot, import wiring, completed-sheet/panel integration, NAS, Settings UI,
  or `HARDWARE_UNCERTAIN` change. **No migration** (uses the Stage-1 tables; alembic head stays
  `c3d4e5f6a7b8`). No frontend (that is Stage 2B).
- **Deferred to a later stage:** a NORMAL-user "view canonical hardware names" read endpoint (no
  consumer yet — every 2A route is admin-only; aliases stay admin-only forever).
- **Tests:** `tests/test_hardware_admin_api.py` (10) — admin lifecycle; non-admins 403 on EVERY
  route (incl. alias visibility); search + all filters; deleted exclude/only/include; restore
  keeps aliases; duplicate spec_id 409; alias create/update/delete/restore + dup/restore semantics;
  soft-delete is not a hard delete. Full backend suite **546 passed** (536 + 10).
- **Files:** backend `api/v1/endpoints/hardware.py` (new), `services/hardware.py` (new),
  `schemas/hardware.py` (new), `api/v1/router.py` (registration), `tests/test_hardware_admin_api.py`
  (new); docs (CHANGES, DEVELOPER_HANDOFF, business_rules). Permanent.

---

## 2026-06-20 — Hardware Parser lane, Stage 1: DB hardware catalogue + aliases + seed

- **Why:** the lane needs a DB-backed canonical hardware catalogue (the long-term source of
  truth admins will edit) before any parser runtime, Settings UI, or Job snapshot work. Stage 1
  creates the storage + seeds it from the Stage-0 spec — **storage + seed only**; nothing reads
  the catalogue yet, so Jobs/imports are unaffected.
- **What:** two soft-deletable tables (migration **`c3d4e5f6a7b8`**): `hardware_catalogue`
  (inverter/battery/panel/metering — `spec_id` stable key, `canonical_model`, `display_name`,
  `brand`, type-specific `phases`/`nominal_kw`/`capacity_kwh`/`wattage_w`, ambiguous-panel
  `model_options`, `attributes` JSON, `spec_source`, `is_active`) and `hardware_aliases`
  (matchable `exact`/`loose`/`case_sensitive` aliases, unique per (hardware_id, alias, alias_type),
  with `confidence_override`/`decision_log_id`). New enums `HardwareCategory`/`HardwareAliasType`.
  An **idempotent** seed (`app.hardware.seed.seed_hardware_catalogue`, wired into
  `python -m app.seed`) reads the tracked YAML and loads **167 catalogue rows** (95 inverter + 45
  battery + 20 panel + 7 metering) and **274 matchable aliases** (255 exact + 17 loose + 2
  case-sensitive). Re-running creates 0 (insert-if-missing — never duplicates, never clobbers
  later admin edits).
- **`source_examples` decision (the safer option):** they are **NOT inserted as aliases at all**
  — they are evidence/fixture strings, so leaving them out means a future matcher can never treat
  one as an alias. They remain in the spec YAML. Parser policy (ignore rules / specific corrections
  / guard phrases / normalization / brand-only & wattage-only panel routing) stays versioned
  config — **not** seeded into the DB.
- **Snapshot-stability preserved:** the catalogue holds NO reference to Jobs; Jobs hold no FK to
  it. It is reference/config data (like `job_label_definitions`/`roles`) — `dev_reset` was
  reviewed and needs **no change** (clearing live CRM/imports neither FK-violates nor should wipe
  the catalogue). A future Job snapshot may store `canonical_hardware_id_at_parse_time`
  (this table's `spec_id`/id) for DEBUGGING only, never as a live reference.
- **No Job/import/parser/UI behaviour change:** no `Job.details`, no import parser/commit/preview/
  reverse, no Settings UI, no parser runtime, no `HARDWARE_UNCERTAIN` change. The only DB writes
  are the additive migration + the (reference-data) seed. Migration round-trip verified;
  `alembic check` clean; head **`c3d4e5f6a7b8`**. Full backend suite **536 passed** (528 + 8 new).
- **Files:** backend `models/hardware.py` (new), `models/enums.py` (2 enums), `db/base.py`
  (registration), `alembic/versions/c3d4e5f6a7b8_*` (new), `app/hardware/__init__.py` +
  `app/hardware/seed.py` (new), `app/seed.py` (wire-in), `tests/test_hardware_catalogue_seed.py`
  (new); docs (CHANGES, DEVELOPER_HANDOFF, database_schema, business_rules). Permanent.
  **Deferred (later stages):** Settings > Hardware admin UI (CRUD + restore + search/filter),
  Job `details.hardware` snapshot read/edit, parser runtime, import integration, panel
  integration, clean-wipe reimport, NAS/proposal.

---

## 2026-06-20 — Hardware Parser lane, Stage 0: vendor curated parser spec as law + validation gates

- **Why:** the Hardware Parser / Hardware Database lane needs a stable, version-controlled
  contract BEFORE any catalogue table, seed, parser runtime, Settings UI, or import wiring is
  built. The curated parser package (the `v9.1` hardware + `v1.1` panel packages) was authored
  offline; Stage 0 turns it into tracked project law with automated validation, with **zero
  runtime/DB/parser behavior change**.
- **What:** vendored the 10 curated files verbatim into **`docs/parser_specs/hardware/`** (spec,
  runtime rules, fixtures, decision logs, validation notes — hardware + panel) plus an index
  `README.md`. Added `backend/tests/test_hardware_parser_spec_validation.py` (10 pure file/YAML
  gates, no app import, no DB): files load; unique catalogue IDs (140 hardware + 7 metering + 20
  panel); unique fixture IDs (27 hardware + 13 panel); `source_examples` are never aliases (880
  checked); exact/loose alias collisions detected (237 aliases; panel case-sensitive pairs like
  Jinko/JINKO allowed); confidence values from the approved vocabularies; the panel `model: null`
  rules (brand/wattage-only/ambiguous); and the known `parser_rule_version` drift
  (runtime says `v8`, package is `v9.1`) pinned/reported. The spec files are **documentation/law
  only** — runtime code will later read a DB-seeded catalogue, not these files directly.
- **Test infra:** the backend container only mounts `./backend`, so it can't see `docs/`. Added a
  read-only mount **`./docs/parser_specs:/app/parser_specs:ro`** to the backend service in
  `docker-compose.yml` so the validator can read the vendored spec; the test resolves either the
  container mount or a repo-relative path.
- **No DB/no migration/no runtime change:** no tables, no seed, no parser, no Settings UI, no
  import wiring; no data mutated; alembic head unchanged (`b2c3d4e5f6a7`). Full backend suite
  **528 passed** (518 + 10 new).
- **Dependencies:** `PyYAML==6.0.3` is now pinned explicitly in `backend/requirements.txt` so the
  spec-validation test declares its own dependency rather than relying on it being pulled in
  transitively (it was previously only incidentally present). The backend image was rebuilt so
  the declared deps are baked in (this also restored `openpyxl==3.1.5`, which had been
  live-installed in the old container but not baked into the image — a pre-existing drift the
  mount-recreate exposed).
- **Files:** new `docs/parser_specs/hardware/*` (10 curated + README), `docker-compose.yml`
  (read-only spec mount), `backend/requirements.txt` (explicit `PyYAML` pin),
  `backend/tests/test_hardware_parser_spec_validation.py`; docs (CHANGES, DEVELOPER_HANDOFF,
  business_rules). Permanent. **Deferred (later stages):** catalogue
  DB + seed, Settings > Hardware admin UI, Job `details.hardware` snapshot read/edit, parser
  runtime, import integration, panel integration, clean-wipe reimport, NAS/proposal.

---

## 2026-06-19 — Job-list source name also covers IMPORTED (attach/grouped) jobs

- **Why:** the previous slice only surfaced `source_customer_name` from B4 customer-merge metadata.
  The live case (Stuart White, job SCS-2022-00002 / 48 Barry Street) actually came from an IMPORT
  ATTACH — the original name ("Stephen Pipka") lives on the `ImportRow`, not in a `CUSTOMER_MERGED`
  activity — so it showed nothing. Imported jobs whose row name differs from the current customer
  should also show "Originally <name>".
- **What:** extended the read-model derivation only. New `import_source_names_for_jobs` reads
  `ImportRow.parsed['customer_name']` matched by `ImportRow.committed_job_id`, exposing it when it
  differs (whitespace/case-normalised) from the job's current customer name. A combined
  `source_customer_names_for_jobs` applies **MERGE precedence** (merge name if present, else the
  import-row name, else null) and is now wired into the jobs list + detail endpoints. The
  CustomerContactVariant is deliberately NOT used as the source (its capture is conditional/
  incomplete). Same-name suppression is now shared (`_norm_name` = collapse-whitespace + casefold)
  across BOTH the merge and import paths, so a same-name source differing only by case/spacing is
  consistently suppressed (the merge helper's suppression was tightened to this shared rule; its
  derivation — earliest-merge-wins from CUSTOMER_MERGED metadata — is otherwise unchanged).
- **No migration, no data mutation, no frontend change:** pure read-side derivation (a batch
  `ImportRow` query); nothing written to jobs, customers, import rows, activities, or variants; the
  job's real `customer` is untouched. `JobsTable` already renders `source_customer_name`, so the
  frontend was not touched. Verified live: Stuart White's 48 Barry Street job now resolves to
  "Stephen Pipka"; its three same-name import-group jobs stay null.
- **Files:** backend `services/jobs.py` (`import_source_names_for_jobs` + combined
  `source_customer_names_for_jobs`), `api/v1/endpoints/jobs.py` (list + detail call the combined
  helper), `tests/test_job_source_customer_name.py`; docs. Permanent.

---

## 2026-06-19 — Job lists show the original/source customer name for merged-in jobs

- **Why:** after a customer merge, every job points at the surviving (winner) customer, so a
  job that originally belonged to a differently-named customer (e.g. "Steven Pipka" merged into
  "Stuart White") showed no trace of its origin. The customer-specific job lists should make that
  origin visible — without changing the real customer source of truth or inventing stored data.
- **What:** `JobRead` gains an additive, **read-only computed** `source_customer_name`. The jobs
  list + detail endpoints populate it COMPUTE-ON-READ from existing `CUSTOMER_MERGED` activity
  metadata (`meta.loser_name` + `meta.moved.jobs.ids`): when a merge moved a job into its current
  customer under a DIFFERENT name, that original name is surfaced. For chained merges the EARLIEST
  merge that moved the job wins (its truly original source). Null for normal / same-name / unmerged
  jobs. The frontend shows it as a small secondary line ("Originally <name>") under the case number
  in the two customer-specific panels (Customer Detail Jobs panel + Job Detail other-jobs panel),
  where the Name column is hidden. The global Jobs page layout from `889b377` is unchanged.
- **No migration, no data mutation:** nothing is written to jobs, customers, activities, variants,
  or details JSON — it is pure read-side derivation (a batch query alongside the existing label
  batch-load). The job's real `customer` is untouched.
- **NOT in scope (deferred):** the imported-job source name (`ImportRow.parsed.customer_name`) —
  this slice is merge-provenance only.
- **Files:** backend `services/jobs.py` (`merge_source_names_for_jobs`), `schemas/job.py`
  (`JobRead.source_customer_name`), `api/v1/endpoints/jobs.py` (list + detail wiring),
  `tests/test_job_source_customer_name.py`; frontend `types/index.ts`,
  `components/JobsTable.tsx`. Permanent.

---

## 2026-06-19 — Known Customer Details: editable + source provenance + survive reversal

- **Why:** Known Customer Details preserved differing contact info, but the user still could not
  (a) tell WHICH import row/job contributed a given detail, nor (b) CORRECT it — and a source-
  derived detail vanished if its import row was later reversed. These are real customer records,
  so they need an edit path and clear provenance, and an edited detail must not be lost on reverse.
- **What (editable):** new admin-only **`PATCH /customers/{id}/contact-variants/{variant_id}`**
  edits a Known Customer Detail of ANY `source_type` (manual OR source-derived). It updates ONLY
  the variant row and stamps `edited_at`/`edited_by_id`; it NEVER changes the primary Customer
  fields, the job, the import row, merge history, or the variant's provenance (`source_type` +
  source FK ids are immutable and not accepted). An edit that would blank every detail field → 400.
  Backend enforces admin (`require_admin`) — frontend gating is not relied upon. Manual variants
  remain editable + archivable; archive stays manual-only.
- **What (provenance):** the read API now returns SAFE, computed source fields for `import_row`
  variants — `source_row_number` (the workbook row index, not a PK), `source_job_case_number`,
  `source_job_id`, and `source_reversed` — so the UI shows e.g. "Source row #23 · Job
  SCS-2023-00002". Raw internal `source_import_row_id`/`source_customer_id`/`source_document_id`
  stay DB-only (still not exposed). The Customer-Detail card shows a source line before each entry
  (job case links to the job), an "edited" marker, an "import reversed" marker, and an admin Edit
  action on every entry.
- **What (reverse preservation):** reversing an import row now archives the contributed
  `import_row` variant ONLY while it is unedited (`edited_at IS NULL`). An EDITED variant is
  preserved as curated customer detail; its provenance then shows the source row as reversed.
- **Migration:** **`b2c3d4e5f6a7`** adds two nullable columns (`edited_at`, `edited_by_id` FK
  users) to `customer_contact_variants`. Additive + reversible (round-trip verified); no data
  backfill (existing rows are NULL/unedited). Head moves a1b2c3d4e5f6 → **`b2c3d4e5f6a7`**.
- **dev_reset:** `clear_imports` now DETACHES (nulls) `customer_contact_variants.source_import_row_id`
  before deleting `import_rows` — closes a pre-existing latent FK gap (the prior pass began
  populating that link; deleting the staging row while a live variant referenced it FK-violated).
  The live variant is preserved; only the now-gone provenance link is cleared.
- **NOT in scope (still deferred):** promote-to-primary (a Known Customer Detail still never
  overwrites the primary Customer), backfill of existing variants, import/document/NAS capture,
  batch tooling.
- **Files:** backend `models/customer_contact_variant.py`, `alembic/versions/b2c3d4e5f6a7_*`,
  `schemas/customer.py` (`CustomerContactVariantUpdate` + Read provenance/`edited_at` fields),
  `services/customers.py` (`update_contact_variant` + `variant_provenance`),
  `api/v1/endpoints/customers.py` (PATCH + `_variant_read` enrichment),
  `services/import_reverse.py` (preserve edited), `services/dev_reset.py` (detach variant link),
  `tests/test_customer_contact_variants.py` + `tests/test_import_contact_variant_capture.py`;
  frontend `types/index.ts`, `lib/customers.ts`, `hooks/useCustomers.ts`,
  `components/EditContactVariantModal.tsx` (new), `components/AlternateContactDetailsCard.tsx`.
  Permanent.

---

## 2026-06-19 — Corrective pass: capture differing customer details on import commit + "Known customer details" UI

- **Why:** the Customer page is the source of truth for ALL known customer-level details, but
  when an import row was **attached to an existing customer** (B2) or was a **grouped DEPENDENT**,
  the row's customer-level contact identity (name/email/phone) was silently DISCARDED — the
  existing customer was used as-is and nothing was preserved. So "committing a different client
  into Stuart White" showed that other client's contact info nowhere. The UI also framed the
  variant card as lesser "alternate" details rather than as known customer details.
- **What (capture):** on commit, an attach / grouped-dependent row now preserves its DIFFERING
  customer-level CONTACT identity (name + any email/phone the customer doesn't already hold,
  extras folded into a note) as one `import_row` `CustomerContactVariant` on the target customer.
  Conservative + additive: captures only non-empty values that differ from the customer's primary
  field; creates NO variant when nothing differs or is empty; NEVER mutates the customer's primary
  fields. `source_import_row_id` is stored DB-side for provenance/cleanup (not exposed by the read
  API). Reversing the row archives the variant it contributed (soft-delete).
- **Address stays job-scoped:** a row's address is the JOB's site (`Job.details.site`) — it is
  deliberately NOT captured as a customer variant, so a multi-site customer doesn't accrue
  job-site "contact" variants. `Job.details.site` is unchanged.
- **What (UI):** the Customer-Detail card is reframed from "Alternate contact details" to
  **"Known customer details"** — additional names/phones/emails on record for this customer, shown
  as compact one-line summaries (collapsible past 4) with a neutral source label
  (Manual / From merged customer / From import row), part of the same customer-details area as the
  primary Details (which stays the source of truth). The manual-add modal copy now states these
  are customer-level details, not a job site.
- **dev_reset:** `clear_live_crm` now deletes `customer_contact_variants` BEFORE customers
  (the variant FKs `customers`). This closes a pre-existing latent gap (the table has existed
  since Stage 2; nothing exercised a variant-before-clear path until import capture did) — without
  it the customer hard-delete FK-violates.
- **Permissions unchanged:** capture is part of the existing admin-only import commit; reads stay
  open to any authenticated user; manual add/archive stay admin-only.
- **No migration:** reuses the Stage-2 table (`source_type='import_row'`, `source_import_row_id`
  already exist); head stays **`a1b2c3d4e5f6`**, `alembic check` clean.
- **NOT in scope (deferred):** promote-to-primary, edit-existing-variant, backfill of already-merged/
  already-imported customers, document/NAS-sourced capture.
- **Files:** backend `services/customers.py` (`capture_import_contact_variant`),
  `services/import_commit.py` (capture in the attach/group branch), `services/import_reverse.py`
  (archive contributed variant on reverse), `services/dev_reset.py` (clear variants before
  customers), `tests/test_import_contact_variant_capture.py`; frontend
  `components/AlternateContactDetailsCard.tsx` (reframed "Known customer details"),
  `components/AddContactVariantModal.tsx` (customer-level copy), `pages/CustomerDetailPage.tsx`
  (comment). Permanent.

---

## 2026-06-19 — Stage 4: manual add + archive of alternate customer contact details

- **What:** admins can now MANUALLY add and ARCHIVE alternate customer-level contact/address
  variants from Customer Detail. New admin-only endpoints:
  `POST /customers/{id}/contact-variants` (create a `manual` variant) and
  `DELETE /customers/{id}/contact-variants/{variant_id}` (soft-delete a manual variant). The
  read-only card gains an admin "Add alternate details" button + a per-manual-variant "Archive"
  control; reads stay open to any authenticated user.
- **Create rules:** `source_type` is forced to `manual` server-side; the source FK ids are NOT
  accepted from the client (and stay NULL); at least one DETAIL field (name/email/phone/
  address/suburb/state/postcode) must be non-blank — a label/note alone is rejected (400);
  values are trimmed; a missing / soft-deleted / merged-loser customer → 404.
- **Archive rules:** **manual variants only** — source-derived (`merged_customer`/import/document)
  variants are **immutable** and NOT archivable in Stage 4 (the safer choice: archiving a
  merge-provenance snapshot could hide audit evidence). Archive is a soft-delete (`deleted_at`),
  never a hard delete; an other-customer / already-archived / source-derived / missing variant →
  404 (idempotent-safe). Archived variants drop out of the read list.
- **Admin-only writes; reads unchanged:** both write endpoints require admin (`require_admin`);
  read access is unchanged (any authenticated user). The frontend gates the Add/Archive controls
  on `canManageCustomerVariants` (admin). Source FK ids remain DB-only (not in the read schema /
  frontend type).
- **No migration:** uses the Stage-2 table; head stays **`a1b2c3d4e5f6`**, `alembic check` clean.
- **Deferred:** edit-an-existing-variant, promote-to-primary, backfill of existing merged losers,
  import-grouping / document-NAS capture.
- **Files:** backend `schemas/customer.py` (`CustomerContactVariantCreate`), `services/customers.py`
  (`VariantError` + `create_contact_variant` + `archive_contact_variant`),
  `api/v1/endpoints/customers.py` (POST + DELETE), `tests/test_customer_contact_variants.py`;
  frontend `auth/permissions.ts` (`canManageCustomerVariants`), `types/index.ts`
  (`ContactVariantInput`), `lib/customers.ts`, `hooks/useCustomers.ts`,
  `components/AddContactVariantModal.tsx` (new), `components/AlternateContactDetailsCard.tsx`
  (+ docs).
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** none beyond the deferred stages; the card now always shows for admins
  (with an Add button) even when a customer has no variants yet.

## 2026-06-19 — Stage 3: capture alternate customer details on B4 merge (no migration)

- **What:** an explicit admin customer merge now PRESERVES the loser's meaningfully-different
  customer-level identity/contact/address fields as one `CustomerContactVariant` on the winner
  (`source_type=merged_customer`, `source_customer_id`=loser), instead of leaving them only on the
  soft-deleted loser row or in prose notes. The winner's primary fields stay authoritative.
- **Difference rule (conservative + deterministic):** per field (full_name→display_name, email,
  phone, address_line1/2, suburb, state, postcode), the loser value is captured only when it is
  non-empty (trimmed) AND differs from the winner's same field (trimmed) — identical/empty fields
  are skipped, and NO variant is created when nothing meaningfully differs (no redundant variants).
  A loser value where the winner is blank counts as a difference. Job notes / Job.details.site are
  never captured.
- **All B4 merge behavior unchanged:** FK repoints, the loser-notes append, the loser soft-delete,
  `merged_into_customer_id`/`merged_at`, the `CUSTOMER_MERGED` activity, and reverse-safety all
  remain intact; the capture is additive in the same transaction (rolled back atomically on any
  merge failure). `source_customer_id` is stored for audit but is **NOT** exposed by the read API
  (Stage 2 already kept source FK ids DB-only) — so the merged-loser id stays hidden.
- **No migration:** uses the Stage-2 `customer_contact_variants` table; head stays
  **`a1b2c3d4e5f6`**, `alembic check` clean.
- **Still deferred:** manual add/edit/archive, promote-to-primary, backfill of existing merged
  losers, import-grouping capture, document/NAS capture.
- **Files:** `backend/app/services/customers.py` (`_capture_merge_variant` + call in
  `merge_customers`), `backend/tests/test_customer_merge.py` (+ docs).
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** none beyond the deferred stages; capture only on a real difference avoids
  redundant variants.

## 2026-06-19 — Stage 2: CustomerContactVariant storage foundation + read-only display

- **What:** a new `customer_contact_variants` table stores an **alternate** set of
  customer-level identity/contact/address details for a LIVE customer (name/email/phone/
  address + provenance), for when the same real customer is known by different details
  (a merged-away duplicate, an import row, manual entry, or a document). A read-only endpoint
  `GET /customers/{id}/contact-variants` returns an active customer's active variants, and
  Customer Detail shows a read-only **"Alternate contact details (N)"** card (hidden when
  there are none). The primary `Customer` columns stay authoritative — variants never
  overwrite them and are NOT job notes / per-job sites.
- **Why:** a structured place to preserve and display differing customer-level details instead
  of burying them in notes or losing them on a soft-deleted merge loser.
- **Storage + read only:** nothing populates variants yet — **no** merge capture, **no**
  backfill, **no** manual add/edit/archive, **no** promote-to-primary (all later stages).
  Source-derived variants are immutable snapshots; archived via `deleted_at`.
- **Fields:** `customer_id` (FK, required, indexed), `label`, `display_name`, `email`, `phone`,
  `address_line1/2`, `suburb/state/postcode`, `source_type` (`CustomerContactVariantSource`:
  merged_customer / import_row / manual / document, indexed), `source_customer_id` /
  `source_import_row_id` / `source_document_id` (optional FKs), `note`, `created_by_id`,
  timestamps + `deleted_at`. FK-only (no ORM relationships — multi-customer-FK).
- **Read access:** any authenticated user; a missing / soft-deleted / merged-loser id returns a
  plain 404 (no variants exposed for a non-active customer).
- **Migration:** `a1b2c3d4e5f6` (revises `f0a1b2c3d4e5`) — additive: creates the new table +
  its indexes/FKs only, no backfill, reversible. New head **`a1b2c3d4e5f6`**; `alembic check` clean.
- **Files:** `backend/app/models/customer_contact_variant.py` (new), `app/models/enums.py`
  (`CustomerContactVariantSource`), `app/db/base.py` (register),
  `backend/alembic/versions/a1b2c3d4e5f6_add_customer_contact_variants.py` (new),
  `app/schemas/customer.py`, `app/services/customers.py`, `app/api/v1/endpoints/customers.py`,
  `backend/tests/test_customer_contact_variants.py` (new); frontend `types/index.ts`,
  `lib/customers.ts`, `hooks/useCustomers.ts`, `components/AlternateContactDetailsCard.tsx`
  (new), `pages/CustomerDetailPage.tsx` (+ docs).
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** none — additive, read-only. Stage 3 (B4-merge capture), manual
  add/edit/archive, and promote-to-primary remain deferred.

## 2026-06-19 — Jobs: "Other jobs for this customer" panel on Job Detail (frontend-only)

- **What:** the Job Detail page now shows a compact, display-only **"Other jobs for this customer
  (N)"** panel below the main details, listing the customer's other jobs (the current job
  excluded) so a sibling job can be opened without returning to the Customer page. Reuses the
  shared `JobsTable` + the existing `useJobs({ customer_id })` query; a "View all on customer →"
  link points at the Customer page.
- **Why:** smoother navigation for multi-job customers — Stage 1 of the customer-variants /
  multi-job diagnosis, and the smallest, schema-free slice.
- **Hidden when:** the customer has no other jobs (single-job customers see nothing — no clutter,
  and no loading/error flash).
- **Scope:** frontend only — **no** backend/API/migration/schema/model change, **no** new job
  workflow; display/navigation-only. The larger alternate-customer-details
  (`CustomerContactVariant`) system is **NOT** implemented — it remains a later staged design.
- **Files:** `frontend/src/components/CustomerOtherJobsPanel.tsx` (new),
  `frontend/src/pages/JobDetailPage.tsx` (mount) (+ docs).
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** none — reuses existing read-only job/customer data; the
  alternate-customer-details data model is the deferred Stage 2+.

## 2026-06-19 — Cleanup: reconcile job_label_definitions.key model↔DB drift (unique index)

- **What:** a pre-existing model↔DB drift on `job_label_definitions.key` that kept surfacing in
  `alembic check` / autogenerate (noted across the B4 audits) is resolved. The model declares the
  column `unique=True, index=True` (a single UNIQUE index), but the original Phase-L1 migration
  (`e3c4d5f6a7b8`) redundantly created **both** a unique constraint (`uq_job_label_definitions_key`)
  **and** a separate **non-unique** index (`ix_job_label_definitions_key`). New migration
  **`f0a1b2c3d4e5`** collapses that pair into the single UNIQUE index the model expects (drops the
  constraint + non-unique index, creates a unique index). `alembic check` is now clean for this table.
- **Why:** the persistent drift kept appearing in schema checks; reconciling it closes the B4 area.
- **Investigation (verified before applying):** uniqueness is **intended** (keys are stable
  identifiers; the label service looks up by `key` and treats keys as unique) and was **already
  enforced** (by the unique constraint), so this is a representational reconcile, **not** adding
  missing uniqueness; **zero duplicate keys** exist; nothing references the dropped object names
  (only the original migration did) and no FK targets `key` (FKs point at `id`).
- **No data change:** DDL only on the label catalogue; the seeded rows are untouched. Reversible
  (downgrade restores the original constraint + non-unique index). Head moves
  `e9f0a1b2c3d4` → **`f0a1b2c3d4e5`**.
- **Files:** `backend/alembic/versions/f0a1b2c3d4e5_unique_job_label_key.py` (new),
  `backend/tests/test_job_labels.py` (a focused duplicate-key-rejected test protecting the
  invariant), `docs/database_schema.md` (migration chain/head).
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** none — unrelated to B4 merge logic; merge/customer code untouched.

## 2026-06-19 — B4-4: existing-customer merge — merged-loser URL polish (no migration)

- **What:** a stale/bookmarked URL for a customer that was **merged away** no longer feels like
  a mystery 404. `GET /customers/{merged_loser_id}` **still returns 404** (deleted customers stay
  hidden), but when the loser resolves to a **live winner** the body is now an enriched detail
  `{ reason: "merged", merged_into_customer_id, merged_into_name }` — chain-walked to the final
  live winner via the (previously dormant) B4-1 `resolve_active_customer`. Customer Detail renders
  a clear **"This customer was merged into {name}"** notice with a button/link to the winner.
- **Why:** B4-2 already repointed every in-app reference to the winner, so the only rough edge was
  a direct/external loser URL landing on a generic "Customer not found."
- **Deliberate non-behaviors:** **no auto-navigation** (the user clicks the link); **no 3xx
  redirect** (a `fetch`-following SPA would silently swap identity); **no 200 with soft-deleted
  loser data** (the loser's own fields are never exposed — only the live winner's id + name).
- **Unchanged / fallback:** missing customers, normally soft-deleted **non-merged** customers,
  broken/dead-end chains, and cycles all keep the **plain** 404. `list`/search is unchanged
  (already excludes losers via `deleted_at`); import matching is unchanged (B4-2 repoint already
  makes it safe); merge execution is unchanged. **No** migration/model/schema change — schema head
  stays **`e9f0a1b2c3d4`**.
- **Files:** `backend/app/services/customers.py` (`merged_winner_for` helper),
  `backend/app/api/v1/endpoints/customers.py` (enriched-404 branch),
  `frontend/src/pages/CustomerDetailPage.tsx` (merged notice + strict guard),
  `frontend/src/types/index.ts` (`CustomerMergedDetail`),
  `backend/tests/test_customer_merge.py` (6 GET tests; a B4-2 activity test scoped to be robust
  against real dev-DB merge data) (+ docs).
- **Temporary or permanent:** Permanent.
- **Still deferred:** unmerge; batch merge; any search/import chain-follow (not needed).

## 2026-06-19 — B4-3: existing-customer merge — frontend admin UI (no backend change)

- **What:** an admin-only **"Merge into…"** action on the Customer Detail page that drives the
  existing B4-2 backend merge. The button (admin-gated, beside Edit/Delete) opens a modal to
  **search and select another live customer** (the winner); selecting one shows an explicit
  **confirmation/preview** with warnings — the winner's contact/address fields stay
  authoritative, the loser's notes/internal_notes are appended into the winner's internal notes,
  the loser's jobs/tasks/documents/activities/import links move to the winner, the loser is
  hidden (soft-deleted), and **unmerge is not built**. On confirm it `POST`s
  `/customers/{loser_id}/merge-into/{winner_id}`, invalidates the
  customer/jobs/tasks/activities/documents/imports caches, and **navigates to the winner**.
- **Why:** the B4-2 backend could already merge customers, but there was no app workflow to do
  it; this gives admins a safe, explicit UI.
- **Safety / UX:** the merge is hard to trigger accidentally — the endpoint is called ONLY from
  the explicit "Merge" confirm button (never on open/search/select), which stays disabled until
  a valid winner is selected; a customer can never be merged into itself (the loser is excluded
  from results and re-checked on confirm); the button is admin-only (`canMergeCustomers`), with
  the backend `require_admin` as the real boundary (403 surfaced in the modal).
- **Scope:** frontend only — the one non-frontend-typing addition is the `CustomerMergeResult`
  type (mirrors the backend schema). NO backend/migration/model change; schema head stays
  **`e9f0a1b2c3d4`**. Backend merge execution remains **B4-2**; B4-3 adds the UI only.
- **Files:** `frontend/src/components/MergeCustomerModal.tsx` (new),
  `frontend/src/pages/CustomerDetailPage.tsx` (gated button + modal),
  `frontend/src/hooks/useCustomers.ts` (`useMergeCustomer` + invalidation),
  `frontend/src/lib/customers.ts` (`mergeCustomer`),
  `frontend/src/auth/permissions.ts` (`canMergeCustomers`),
  `frontend/src/types/index.ts` (`CustomerMergeResult`) (+ docs).
- **Temporary or permanent:** Permanent.
- **Still deferred:** stale merged-loser URL redirect / search chain-follow; unmerge; batch
  merge; a browser-tested live merge flow (not run — it mutates live customer data).

## 2026-06-19 — B4-2: existing-customer merge — execution (admin-only, transactional, no migration)

- **What:** the explicit admin **customer merge** is now executable. Admin-only
  `POST /customers/{loser_id}/merge-into/{winner_id}` runs `merge_customers` in ONE
  transaction: under a `FOR UPDATE` lock on both customers (canonical id order) it repoints
  every customer FK loser→winner (`Job`/`Activity`/`Task`/`Document.customer_id` + the import
  links `ImportRow.committed_customer_id`, `ImportRow.resolved_customer_id`,
  `ImportCustomerGroup.committed_customer_id`), appends the loser's notes/internal_notes into
  `winner.internal_notes` with a provenance header, **soft-deletes** the loser and marks it
  `merged_into_customer_id` + `merged_at`, and emits one `CUSTOMER_MERGED` activity (on the
  winner) with moved/repointed ids + counts. Returns a `CustomerMergeResult` summary.
  Single-pair only; `merged_into` immutable; **nothing hard-deleted**.
- **Why:** consolidate duplicate live customers after the fact, losing nothing (jobs, tasks,
  documents, timeline, import provenance), with full auditability.
- **Guards (re-checked under the lock, before any mutation):** loser≠winner (400); both
  exist (404); neither already merged (409, immutable); both live (409); non-admin (403).
- **Winner authoritative:** the winner's contact/address/email/phone/notes are NEVER
  overwritten — only its `internal_notes` is appended-to.
- **Reverse safety (keystone):** `import_reverse.reversibility()` gains a
  `job_customer_mismatch` guard (blocks when `job.customer_id != committed_customer_id`), and
  the merge **bumps each moved `Job.updated_at`** so a post-merge reverse is blocked by the
  existing `job_modified` guard — a merged job can therefore **never** be reversed into
  soft-deleting the merge **winner**. Merged jobs are intentionally non-reversible;
  **Prepare recommit** remains the safe correction path. (The bump relies on merge running in
  its own transaction after commit — Postgres `now()` is transaction-stable; noted in-code.)
- **No migration (owner decision):** uses the B4-1 columns; `CUSTOMER_MERGED` is a
  string-enum value. Schema head remains **`e9f0a1b2c3d4`**.
- **Deferred:** no frontend merge UI; no `GET`/search chain-follow redirect for a merged
  loser id (`resolve_active_customer` resolves it in code); no unmerge.
- **Files:** `backend/app/services/customers.py` (`merge_customers` + `MergeError`),
  `backend/app/schemas/customer.py` (`CustomerMergeResult`),
  `backend/app/api/v1/endpoints/customers.py` (endpoint),
  `backend/app/services/import_reverse.py` (`job_customer_mismatch` guard),
  `backend/tests/test_customer_merge.py` (new), `backend/tests/test_import_reverse.py`
  (+ docs).
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** merged jobs become non-reversible (by design); a stale loser id is
  not yet redirected to the winner. Builds on B4-1 storage.

## 2026-06-18 — B4-1: existing-customer merge — storage foundation only (no execution)

- **What:** schema + helper scaffolding for a future explicit admin **customer merge**, with
  **no merge execution**. Adds `customers.merged_into_customer_id` (nullable, indexed,
  self-FK → `customers.id`, NO ACTION) and `customers.merged_at` (nullable timestamptz);
  `ActivityType.CUSTOMER_MERGED`; a pure-read `resolve_active_customer(db, id)` helper that
  walks the `merged_into` loser→winner chain to the live winner (cycle-guarded; returns
  `None` for missing / cycle / chain-ends-at-soft-deleted), **currently called by no
  execution path**; and `dev_reset.clear_live_crm` now **nulls `merged_into_customer_id`
  before deleting customers** so the self-FK can't block the reset.
- **Why:** lay a non-destructive, reversible storage/audit foundation so B4-2 merge execution
  can be built and verified against an existing schema, without risking live data now.
- **Scope (what this does NOT do):** no merge endpoint, no merge service/execution, **no
  reassignment** of Job/Task/Document/Activity `customer_id` or import links, **no
  soft-delete of any loser**, no frontend UI, and **no change** to search/get/list or import
  commit/preview/reverse behaviour. Merge execution is **deferred to B4-2**.
- **Owner decisions (recorded for B4-2):** winner contact/address fields remain
  **authoritative** (never auto-overwritten from the loser); loser `notes`/`internal_notes`
  will be **appended into the winner's internal_notes with a provenance header** at execution;
  `merged_into` is **immutable** for B4; **unmerge deferred**; **single-pair** merge only
  (one loser → one winner).
- **Migration:** `e9f0a1b2c3d4` (revises `d8e9f0a1b2c3`) — additive nullable columns + index
  + self-FK only, no data backfill, fully reversible. `CUSTOMER_MERGED` needs no DB type
  migration (`activity_type` is a varchar column). New Alembic head: **`e9f0a1b2c3d4`**.
- **Files:** `backend/app/models/customer.py`, `backend/app/models/enums.py`,
  `backend/app/services/customers.py` (helper), `backend/app/services/dev_reset.py`,
  `backend/alembic/versions/e9f0a1b2c3d4_add_customer_merge_columns.py` (new),
  `backend/tests/test_customer_merge_storage.py` (new), `backend/tests/test_dev_reset.py`
  (+ docs).
- **Temporary or permanent:** Permanent (foundation).
- **Risks / follow-up:** the new columns are inert until B4-2; `resolve_active_customer` has
  no callers by design (B4-2 will consume it). An unrelated pre-existing model↔DB drift on
  `job_label_definitions.key` (unique flag) was noted during the audit — separate follow-up.

## 2026-06-18 — D: reverse-then-recommit via an explicit "Prepare recommit" (no migration)

- **What:** a reversed import row is no longer permanently terminal. A new admin action
  **Prepare recommit** (`POST /imports/{batch}/rows/{row}/prepare-recommit`) returns a
  reversed row to **pending** so it can be committed again as a **brand-new** Customer/Job.
  It stamps the prior `committed_customer_id`/`committed_job_id` into a
  `RECORD_IMPORT_RECOMMIT_PREPARED` activity, then clears the committed links, detaches any
  group, and resets customer resolution. The old soft-deleted Job/Customer are **never**
  restored; a recommit creates new records (new case number) through the **unchanged**
  commit/preview engine, so preview == commit is preserved structurally.
- **Why:** recover a mistakenly-reversed row (or re-commit after a fix) without re-ingesting
  the whole workbook, while keeping the soft-delete-only / no-resurrection data model.
- **Guard model (owner-approved C+E):** the generic `/reopen` **still 409s** for
  committed/reversed rows — Prepare recommit is a separate, explicitly-audited path, and is
  rejected (409) on any non-reversed row. Grouped rows **detach by default**: prepare never
  dissolves a still-committed group or reclaims primary; the reviewer must explicitly
  re-resolve / re-group before approving. A stale resolution pointing at a since-deleted
  customer is still blocked by commit (`resolved_customer_deleted`), never silently created.
- **No migration (owner decision 3):** `review_status` is a string column and `committed_*`
  / `customer_group_id` are nullable, so the transition + link-clearing are plain updates;
  the prior-id lineage lives in the append-only activity (no first-class columns added).
- **Files:** `backend/app/models/enums.py` (new `RECORD_IMPORT_RECOMMIT_PREPARED`),
  `backend/app/services/import_review.py` (`prepare_recommit`),
  `backend/app/api/v1/endpoints/imports.py` (endpoint),
  `frontend/src/lib/imports.ts`, `frontend/src/hooks/useImports.ts`,
  `frontend/src/components/imports/PrepareRecommitModal.tsx` (new),
  `frontend/src/components/imports/CommitReverseSection.tsx` (+ tests + docs).
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** clearing the (previously immutable-after-reverse) committed links is
  sanctioned ONLY inside this dedicated action and the prior ids are preserved in audit.
  Recommit mints a new case number — the old one is permanently retired.

## 2026-06-18 — #5b fix: candidate engine no longer offers reversed / soft-deleted customers

- **What:** `find_candidates` (`import_matching.py`) no longer offers a **reversed** import
  sibling, or a `committed_customer_id` pointing to a **soft-deleted** Customer, as a
  usable "Use this customer" candidate. Two changes to the `batch_row` branch: (1) REVERSED
  sibling rows are excluded from candidate generation entirely (terminal — they offer no
  valid action); (2) a sibling's `committed_customer_id` is exposed only when that customer
  is still live (a since-soft-deleted link is dropped to `null`, mirroring the
  `live_customer` branch's existing `deleted_at` filter).
- **Why:** a manual-test bug (#5b) — after reversing customer #26749, sibling "Stuart
  White" rows still surfaced the soft-deleted #26749 as "Use this customer". The
  `live_customer` branch filtered deleted customers, but the `batch_row` branch used
  `r.committed_customer_id` blindly. (Clicking it was already safely blocked at
  resolve/commit — `resolved_customer_deleted` — so this is a misleading-UX fix, not a
  data-corruption fix.)
- **Preserved:** active committed siblings still collapse/dedupe to one live_customer
  candidate; pending grouped candidates still expose `customer_group_id` for "Join this
  group"; the `live_customer` search branch and the resolve/commit deleted-customer
  defenses are unchanged.
- **Files:** `backend/app/services/import_matching.py` (+ `test_import_matching.py`).
- **Temporary or permanent:** Permanent. No migration/model/schema/parser change.

## 2026-06-18 — H2: extend read-only Preview to staged batch-row candidates

- **What:** the "Possible same customer" Preview now also works for **`batch_row`
  candidates** (those with a `row_id` but no live customer yet — e.g. pending sibling
  rows). Previously Preview appeared only for live/committed-customer candidates. The
  button now shows whenever a candidate has a `row_id` **or** a `customer_id`; a
  `batch_row` opens a new **`CandidateRowPreviewModal`** showing that staged row's
  parsed/review data, a pure `live_customer` keeps the existing `CandidatePreviewModal`.
- **Why:** let reviewers inspect a staged candidate directly — name, source row #/ref,
  review status, parsed address + `details.site`, contact (emails/phones), dates/approval,
  group status, and a committed-customer link if it already committed — without leaving
  the current import row.
- **How (no backend change):** reuses the existing read-only `useImportRow(batchId,
  rowId)` hook (`GET /imports/{batch}/rows/{id}` → `ImportRowRead`), which already carries
  every needed field (`parsed`, `review_status`, `source_row_index`, `legacy_reference`,
  `committed_*`, `customer_group_id`, `internal_notes_override`, `context_text`).
- **Read-only by construction:** the modal holds NO action callbacks and performs NO
  mutation — no approve/reject/skip/group/join/use-customer; dismissal only (✕ / Escape /
  backdrop / Close). The optional committed-customer link opens in a new tab, so the
  current import row is never navigated away from. The H live-customer preview is
  unchanged.
- **Files:** `frontend/src/components/imports/CandidateRowPreviewModal.tsx` (new),
  `frontend/src/components/imports/MatchCandidatesPanel.tsx`.
- **Temporary or permanent:** Permanent.

## 2026-06-18 — H: read-only candidate customer preview in the import review modal

- **What:** In the "Possible same customer" panel (`MatchCandidatesPanel`), each candidate
  that resolves to an existing **committed** customer now shows a **Preview** button. It
  opens a **strictly read-only** modal (`CandidatePreviewModal`) so the reviewer can
  inspect that customer before deciding whether to *Use this customer* / *Join this group*
  / *Group as same customer*. The modal shows the customer's name, email/phone, headline
  address, and their jobs — each with the job's own site address (`details.site` from G),
  status, and labels — plus the total job count.
- **Why:** reviewers need to confirm "is this really the same customer?" without leaving
  the import review or mutating anything.
- **How (no parallel system, zero backend change):** the modal composes the two existing
  read-only GET hooks — `useCustomer(id)` (`GET /customers/{id}`) and
  `useJobs({customer_id})` (`GET /jobs?customer_id=…`). It holds **no** action callbacks
  and performs **no** mutation; its only controls are dismissal (✕ / Escape / backdrop).
  All decision actions stay on `MatchCandidatesPanel`.
- **Previewable scope:** only candidates with a committed `customer_id`
  (`kind='live_customer'`, or a `batch_row` already committed in a prior phase). Pending
  / group candidates (`customer_id` null) have no committed customer to inspect, so the
  Preview button does not render for them. **Deferred:** a preview of a pending batch
  row's *parsed* import data (name/address from the staged row) — out of scope for this
  first cut; the panel only carries `MatchCandidate` fields, not the full parsed row.
- **Files:** `frontend/src/components/imports/CandidatePreviewModal.tsx` (new),
  `frontend/src/components/imports/MatchCandidatesPanel.tsx`.
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** Read-only by construction (no action callbacks, two GETs only).
  Browser verification is currently not exercisable — with `customers=0` (batch 14150 is
  staged-only) no candidate is previewable yet; it becomes visible once live customers
  exist. Pre-G jobs have `details.site=null` and fall back to "—".

## 2026-06-18 — G (Stage 1): per-job site address in Job.details.site (no migration)

- **What:** `build_details` now emits a top-level `details.site`
  (line1/line2/suburb/state/postcode/note/structured/raw) from the parsed address for
  every job row, so a multi-job customer keeps **each** job's own site address. Commit
  persists it in `Job.details`; preview exposes the same per-job site (parity). The
  Customer headline address is unchanged (primary/new-customer address). **JSONB only —
  no Job columns, no migration**, and `details.site` is derived (not registry-editable).
  - **Grouped:** one Customer + N jobs, each job's `details.site` is its own address
    (dependents no longer lose their site).
  - **Attach-to-existing:** the new job records its own `details.site`; the existing
    Customer address is never mutated.
  - **Display:** Job detail prefers the job's own site over the customer headline
    address; the Customer page's jobs table shows each job's **Site** so multi-site jobs
    are distinguishable. The **global** Jobs list keeps the customer Suburb/State for now
    (deferred — a site column on the dense shared table is a separate low-risk follow-up;
    the customer page already covers the distinguishing need).
- **Why:** stop dropping non-primary grouped jobs' site addresses — display-first,
  without a schema change.
- **Files:** `backend/app/services/import_details.py`, `frontend/src/types/imports.ts`,
  `frontend/src/pages/JobDetailPage.tsx`, `frontend/src/components/JobsTable.tsx`,
  `frontend/src/components/CustomerJobsPanel.tsx` (+ tests).
- **Temporary or permanent:** Permanent (Stage 1).
- **Risks / follow-up:** **Stage 2 remains optional future work** — first-class queryable
  `Job` site-address columns + migration + backfill, only if site must be filter/
  searchable (Section D). Applies to FUTURE parses; existing committed jobs predate
  `details.site` and need a re-ingest + commit to populate it.

## 2026-06-17 — F: peel trailing non-address notes from the import Address cell

- **What:** `parse_address` now peels an obvious trailing non-address note that follows a
  valid AU "STATE POSTCODE" tail (e.g. `"17 Daalbata Rd, Leeton 2705 NSW - 405 for the
  bill"`) into a `note` field — so the structured address (line1/suburb/state/postcode)
  is clean, and the note is preserved as neutral imported review context (`build_details`
  → the "Uncategorised Data on Import" internal-notes summary). The raw Address cell still
  holds the full original verbatim, so no source evidence is lost.
- **Why:** a trailing billing/admin note broke the end-anchored address tail, so the whole
  cell fell through to `line1` unstructured and the note polluted the address fields.
- **Conservative:** only peels after a dash / semicolon / pipe delimiter that follows the
  AU tail — a hyphen inside a street (`"5-7 Smith St"`) or a Lot/DP legal descriptor is
  never split, and a normal address with no trailing note is unchanged.
- **Files:** `backend/app/services/import_parser.py`,
  `backend/app/services/import_details.py`, `backend/tests/test_import.py`. **No schema /
  migration** — parser/note rules apply to FUTURE parses; existing staged rows need a
  re-ingest to reflect this.
- **Temporary or permanent:** Permanent.
- **Follow-up:** **G (multi-job / per-site address) is design-only / queued** (see
  `DEVELOPER_HANDOFF.md`) — not implemented in this pass.

## 2026-06-17 — Grouped-customer read-model UI: candidate refetch + group status (follow-up to f67c1ec)

- **What:** Display / read-model-only fixes that closed the manual-UI failures found
  after `f67c1ec`:
  - **Candidate refetch:** every cached match-candidates panel (mounted or not) now
    refetches after a batch mutation (`refetchType: 'all'`), so a stale "Group as same
    customer" / "Join this group" action disappears once siblings are grouped / committed
    / reversed (they collapse to one "Use this customer").
  - **Group status:** committed/reversed grouped rows show a **read-only group-status
    block** — members with their primary / review state and the committed-customer link —
    so a re-promoted primary (after the original primary is reversed) is visible. The
    group member payload (`group_to_dict` / `CustomerGroupMember`) gained read-only
    `review_status` + `committed_customer_id`.
- **Why:** Manual browser testing after `f67c1ec` showed stale candidate actions and no
  way to see group status / re-promotion; both are now resolved (owner-verified).
- **Files:** `backend/app/services/import_review.py`,
  `backend/app/schemas/import_staging.py`, `frontend/src/hooks/useImports.ts`,
  `frontend/src/types/imports.ts`,
  `frontend/src/components/imports/CustomerResolutionSection.tsx` (+ group tests).
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** Display / read-model only — **no commit/reverse/approve logic and
  no parser/address/NAS/dev_reset/migration/model change**.

## 2026-06-17 — B2/B3 grouping-lifecycle stabilization: approval / reverse / steal / cache

- **What:** Import grouping-lifecycle fixes (no schema/parser/migration change):
  - **Candidate cache (C):** `invalidateBatch` now also invalidates the
    `match-candidates` query key, so an open row's "Possible same customer" panel
    refreshes after any batch change (e.g. once siblings commit they collapse into one
    deduped "Use this customer").
  - **Commit auto-detach (A):** commit and preview share `plan_group_commit`; at commit,
    unapproved/ineligible grouped members (rejected / skipped / unresolved-error) are
    **detached** from a group being committed into instead of being stranded in the
    now-locked committed group. **Only approved + eligible rows commit — grouped rows
    are never auto-approved.** The primary is re-promoted to the lowest-source-index
    eligible member when the stored primary is detached.
  - **Reverse continuity (D):** reversing a grouped **primary** re-promotes the
    lowest-source-index remaining **committed** sibling; reversing the **last** active
    grouped job **clears** the group's `committed_customer_id`. Committed/reversed rows
    can no longer be reopened to pending through the normal review-status flow, and the
    reversed-row UI copy no longer offers a non-existent "reopen".
  - **No silent stealing (B):** a row already in a group can no longer be silently
    stolen into another group (server hard-reject). Candidates expose their
    `customer_group_id`; the modal offers **"Join this group"** (adds this row to the
    candidate's existing group, preserving its primary) instead of "Group as same
    customer".
- **Why:** B2/B3 grouping-lifecycle bugs found in manual testing — unapproved grouped
  members stranded at commit, reversed rows confusingly terminal, group stealing, and a
  stale candidate panel after commit.
- **Files:** `backend/app/services/{import_review,import_reverse,import_commit,
  import_commit_preview,import_matching}.py`, `backend/app/schemas/import_staging.py`,
  `frontend/src/hooks/useImports.ts`, `frontend/src/types/imports.ts`,
  `frontend/src/components/imports/{ImportRowModal,CustomerResolutionSection,
  MatchCandidatesPanel}.tsx` (+ matching/group-commit tests).
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** Search API is **unchanged** (E was an empty-DB perception, not a
  bug). Browser verification of the grouping lifecycle requires a **manual/live test**
  because grouping / approve / commit / reverse are mutating flows; backend tests cover
  the scenarios rollback-isolated. Out of scope (separate slices): reverse-then-recommit,
  multi-address/contact (F/G), address parser.

## 2026-06-17 — B2/B3 stabilization (Phase 2): candidate dedup + status-aware modal

- **What:** Four import-review stabilization fixes (no schema change):
  - **Candidate dedup (B):** `import_matching.find_candidates` collapses candidates
    that resolve to the same live `customer_id` (the direct live-customer candidate +
    any committed batch rows pointing at it) into ONE canonical candidate — live
    identity preferred, strongest confidence kept, reasons merged/de-duped. Pending
    batch rows (no `customer_id`) are NOT collapsed. `score` / `build_signature` /
    `matching_core` untouched.
  - **Status-aware display (C):** committed rows show a final committed summary and
    reversed rows a historical summary instead of the active "Possible same customer"
    candidate/group controls; the candidate panel + active resolution/group controls
    render only on a **pending** row; approved/rejected/skipped show the chosen
    resolution read-only with a "reopen to change" hint. Display-only — no audit
    fields cleared/mutated.
  - **Status-aware review buttons (J):** a pending row shows Approve / Reject / Skip
    only (no Reopen); approved/rejected/skipped show the selected status + Reopen
    only; committed/reversed keep the commit/reverse UI.
  - **Search UX (G):** "Search existing customers" stays pending-only and non-grouped;
    it now fetches only at 2+ characters (no `q=""` fetch-and-discard), with a 2-char
    hint, a loading state, and a "No customers found" empty state.
- **Why:** B2/B3 manual-testing continuity issues — duplicate same-customer
  candidates, and stale pending-style controls on committed/reversed rows.
- **Files:** `backend/app/services/import_matching.py`,
  `backend/tests/test_import_matching.py`,
  `frontend/src/components/imports/CustomerResolutionSection.tsx`,
  `frontend/src/components/imports/ImportRowModal.tsx`,
  `frontend/src/hooks/useCustomers.ts`.
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** Browser verification was **blocked** — the owner-cleared dev
  DB has no import rows, so the review modal can't be opened; a **manual browser test
  is required after a re-import**. Backend dedup is covered by tests; frontend
  typecheck + build pass. Out of scope (separate slices): group approve/reopen,
  reversed-row recommit, multi-address/contact, parser fixes, read-only customer
  preview.

## 2026-06-17 — Section B4-0: extract shared matching core (no behaviour change)

- **What:** Moved the pure, DB-free scoring core out of `import_matching.py` into a
  new `backend/app/services/matching_core.py` so the SAME rules can back both import
  matching and the future B4 live-CRM duplicate detection. Symbols moved: `Signature`,
  `build_signature`, `score`, the confidence ranking `CONF_RANK`, the name/address
  normalization helpers, the company/trust entity rule, and the House/Unit address
  handling. `import_matching` imports + re-exports them (same objects), so existing
  callers/tests are unchanged; the import-specific row/customer signature builders, the
  candidate-list cap, and `find_candidates` stay in `import_matching`.
- **Why:** B4-0 foundation — one source of truth for matching before building duplicate
  detection (B4-A) and merge (B4-B). No scoring retune, no new endpoint, no DB/schema
  change.
- **Files:** `backend/app/services/matching_core.py` (new),
  `backend/app/services/import_matching.py`, `backend/tests/test_matching_core.py` (new).
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** None for matching — behaviour-identical; the import matching /
  resolution / grouping / commit suites pass unedited. (A **pre-existing** `dev_reset`
  FK gap surfaced while running the full suite — `clear_imports` / `clear_live_crm`
  did not handle the B2/B3 `import_customer_groups` customer links — independent of and
  predating B4-0; it was fixed separately in commit `e6c4eb0`,
  "fix(dev-reset): handle B2/B3 import grouping links during resets".)

## 2026-06-17 — Docs: reconcile schema / overview / README with the B2/B3 matching series

- **What:** Documentation-only reconciliation after the B2/B3 same-customer
  resolution + grouping work. **No code, schema, or behaviour change.**
  - `docs/database_schema.md`: corrected stale/false migration prose. It claimed the
    `job_label_*` tables were "the only schema migration since `legacy_reference`" and
    that the import work added "no migrations." It now lists the ordered import-migration
    chain including **`c7d8e9f0a1b2`** (B2-1 `import_rows` customer-resolution columns)
    and **`d8e9f0a1b2c3`** (B3-2 `import_customer_groups` + `import_rows.customer_group_id`),
    with the current Alembic **head = `d8e9f0a1b2c3`**.
  - `PROJECT_OVERVIEW.md`: §4 data models now name `import_customer_groups` and the
    per-row customer-resolution state (new / attach-existing / group-into-one).
  - `README.md`: "What's implemented" now lists same-customer matching — advisory
    candidates, manual attach-to-existing, and pending-row grouping (one customer + N jobs).
  - `docs/business_rules.md`: noted the B2/B3 resolution + grouping actions are
    **admin-only** and clarified the group lock is **backend-authoritative** (the modal
    controls follow the row's pending status; the server rejects locked-group changes
    with HTTP 422).
  - `DEVELOPER_HANDOFF.md`: fixed the matching stale "No migration beyond
    `legacy_reference`" line for consistency.
- **Why:** the repository must explain the current system on its own; the migration
  prose was factually false and the overview/README predated the matching series.
- **Files (docs only):** `docs/database_schema.md`, `PROJECT_OVERVIEW.md`, `README.md`,
  `docs/business_rules.md`, `DEVELOPER_HANDOFF.md`, `CHANGES.md`.
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** None — docs only; no migration, no code, no data touched.

## 2026-06-17 — Section B3-4: import-modal UI for pending-row grouping (frontend only)

- **What:** The import row modal now lets a reviewer group pending rows into one
  future customer (the B3-2/B3-3 backend made reachable).
  - The "Possible same customer" panel gives a **pending batch-row** candidate a
    **"Group as same customer"** action (indigo), distinct from B2's "Use this
    customer" (brand). Live-customer candidates still attach via B2; the B3-1
    ★ Recommended marker is unchanged.
  - Grouping a candidate **creates** a group (current row = primary) or, if the row
    is already grouped, **adds** the candidate to it. A **group banner** shows
    "Grouped as one future customer (N rows)", the member list with the **Primary**
    badge, and the commit explanation, plus **Set this row as primary** /
    **Remove this row from group** / **Dissolve group** controls. Candidates already
    in the group show "In group ✓".
  - Controls show only while the row is **pending**; locked rows render the group
    read-only. A row is shown in exactly one state (group banner vs B2 resolution
    banner); the Create-new / search controls are hidden when grouped.
- **Why:** make the B3 grouping decision reachable to reviewers so they can
  consolidate multi-job customers during import review — no auto-grouping.
- **Files (frontend only):** `frontend/src/components/imports/CustomerResolutionSection.tsx`,
  `MatchCandidatesPanel.tsx`, `hooks/useImports.ts`, `lib/imports.ts`, `types/imports.ts`.
- **Temporary or permanent:** Permanent. **No backend change** (uses the existing
  B3-2 group endpoints + B3-3 commit/preview/reverse). No migration.
- **Risks / follow-up:** Existing-customer **merge** (combining two live customers)
  remains out of scope (future B4).

## 2026-06-17 — Section B3-3: grouped preview / commit / reverse (one customer, N jobs)

- **What:** Pending-row groups (B3-2) now actually create **one customer + multiple
  jobs**.
  - **Commit:** the group's **primary** row creates the customer and records it on
    `import_customer_groups.committed_customer_id`; **dependent** rows create a Job
    that attaches to that customer. Ordering keeps each group **contiguous +
    primary-first** (shared `commit_sort_key`), so a dependent is always committed
    after its primary — even when `COMMIT_CAP` (25) splits the group across calls
    (dependents wait, then attach next call). If the primary fails / isn't committed
    yet, dependents are **skipped** (`group_primary_not_committed`) — never split into
    separate customers; if the group's customer is missing/deleted, dependents
    **fail** (`group_customer_deleted`/`group_customer_missing`). Per-row durability,
    labels, internal-notes override, legacy-ref de-dup, and `RECORD_IMPORTED` all
    still apply.
  - **Preview:** a group counts as **1 customer + N jobs**; per-row `customer_action`
    is `group_primary` / `group_dependent` (+ `group_id` / `primary_row_id`);
    `would_create.customers` counts each group once; invalid groups are excluded
    (`group_primary_unavailable` / `group_customer_invalid`). Still read-only.
  - **Reverse (unified rule):** always soft-delete the Job; soft-delete the
    **customer only if it was import-created AND, after this job, has zero remaining
    active jobs AND is pristine.** So a non-last grouped job reverse is **job-only**
    (shared customer kept); the **last** grouped job reverse soft-deletes the
    customer. **B2 attach and 'new' single-job reverse are byte-for-byte unchanged.**
- **Why:** make the reviewer's grouping decision consolidate multi-job customers at
  commit, safely and reversibly, with no auto-merge.
- **Files:** `backend/app/services/{import_commit,import_commit_preview,import_reverse}.py`,
  `backend/app/schemas/import_staging.py`, `backend/tests/test_import_groups_commit.py`
  (+ the B3-2 inert test updated to the new behaviour).
- **Temporary or permanent:** Permanent. **No migration** (uses the B3-2 columns).
- **Risks / follow-up:** Frontend grouping UI is **B3-4** (not in this pass).

## 2026-06-17 — Section B3-2: pending-row grouping storage + API (storage only)

- **What:** Foundation for grouping pending import rows into one **future** customer.
  - New table **`import_customer_groups`** (`batch_id`, `primary_row_id`,
    `committed_customer_id` [unused until B3-3], `created_by_id`, `reason`,
    timestamps) + **`import_rows.customer_group_id`** FK.
  - `customer_resolution_mode` gains a `'group'` value (a row is **exactly one** of:
    unresolved/new, `existing` [B2 attach], or `group` — `resolved_customer_id` and
    `customer_group_id` are never both set; the B2 setters now detach any group).
  - Admin-only API under `/imports/{batch}/customer-groups`: **create** (≥2 rows),
    **list/get**, **add row**, **remove row** (auto-dissolves below 2; auto-promotes a
    new primary — lowest `source_row_index` — if the primary is removed),
    **set primary**, **dissolve**.
  - Validations: same batch, job/ambiguous class, pending (locked once any member is
    approved/committed/reversed — reopen to change), primary ∈ members.
- **Why:** record the reviewer's "these rows are one customer" intent so B3-3 can
  create one customer + multiple jobs — without any auto-grouping/merge.
- **Files:** `backend/app/models/import_staging.py`, migration
  `d8e9f0a1b2c3_import_customer_groups.py`, `backend/app/schemas/import_staging.py`,
  `backend/app/services/import_review.py`, `backend/app/api/v1/endpoints/imports.py`,
  `backend/tests/test_import_groups.py`.
- **Temporary or permanent:** Permanent. **One additive migration** (new table +
  nullable column; no backfill). Mutual-exclusion invariant is service-enforced (no
  DB CHECK, matching B2-1 style).
- **Risks / follow-up:** **STORAGE ONLY — inert at commit/preview/reverse.** A
  grouped row still commits as its **own new customer** in B3-2 (proven by test);
  **B3-3** makes grouped rows create one customer + multiple jobs (primary creates /
  dependents attach), updates preview ("1 customer + N jobs"), and adds group-aware
  reverse. No frontend UI yet (B3-4).

## 2026-06-17 — Section B3-1: "Recommended" marker on strong same-customer candidates (frontend only)

- **What:** In the import modal's "Possible same customer" panel, **strong**
  candidates now show a subtle **★ Recommended** badge (derived from the existing
  B1 confidence band). Cosmetic only — it does **not** auto-select, write resolution,
  or change preview/commit/reverse/grouping; the reviewer still confirms explicitly
  via "Use this customer". Medium/weak candidates stay plain advisory; reasons remain
  visible; all B2-3 actions are unchanged.
- **Why:** guide reviewers to high-confidence matches without any silent/auto merge.
- **Files (frontend only):** `frontend/src/components/imports/MatchCandidatesPanel.tsx`.
- **Temporary or permanent:** Permanent. No backend/type change (uses the
  confidence already returned by the B1 match-candidates endpoint).

## 2026-06-17 — Section B2-3: import-modal UI for same-customer resolution (frontend only)

- **What:** The B1 "Possible same customer" panel in the import row modal is now
  actionable (on a pending row). A reviewer can:
  - **Use this customer** on a candidate that resolves to an existing live customer
    (live-customer candidates, and batch-row candidates whose sibling is already
    committed) → calls the B2-1 resolve endpoint with `mode=existing`;
  - **Create new customer** (`mode=new`) and **Clear resolution** (`mode=clear`);
  - **Search existing customers** (reuses `GET /customers?q=`) to attach to any live
    customer not surfaced as a candidate.
  A resolution **banner** shows the current state ("Will attach this job to existing
  customer: …" / "Will create a new customer."), with the reason and a customer link.
  Pending batch-row candidates (no live customer yet) stay **advisory only**
  ("pending — can't select yet"). Controls are shown only while the row is pending;
  locked rows (approved/committed/reversed) show the resolution read-only.
- **Why:** make the B2-1/B2-2 backend resolution reachable to reviewers, so they can
  consolidate multi-job customers during import review.
- **Files (frontend only):** `frontend/src/components/imports/CustomerResolutionSection.tsx`
  (new), `MatchCandidatesPanel.tsx`, `ImportRowModal.tsx`, `hooks/useImports.ts`,
  `lib/imports.ts`, `types/imports.ts`.
- **Temporary or permanent:** Permanent. **No backend change** (uses the existing
  B2-1 resolve endpoint + B2-2 commit/preview/reverse). No migration.
- **Risks / follow-up:** Resolving to a **pending** import row (a batch-row candidate
  without a live customer) is intentionally not selectable yet — that's future work.

## 2026-06-17 — Section B2-2: wire same-customer resolution into commit / preview / reverse

- **What:** The B2-1 resolution intent now has live effect.
  - **Commit-to-live:** a row with `customer_resolution_mode = "existing"` attaches
    a **new Job to the resolved existing customer** — no new customer is created and
    the existing one is **not** mutated. The `RECORD_IMPORTED` activity gains
    `attached_to_existing_customer` / `resolved_customer_id` / `resolved_by_id`
    metadata and an attach-specific description. Labels, internal-notes seeding /
    override, and legacy-reference de-duplication are all preserved. If the resolved
    customer is missing/soft-deleted at commit time the row **fails**
    (`resolved_customer_deleted` / `resolved_customer_missing`) — never a silent
    fallback to a new customer, and the stored resolution is left intact for a retry.
  - **Commit-preview:** per-row `customer_action` ("attach"/"create") +
    `resolved_customer_id`/`resolved_customer_name`; `would_create.customers`
    excludes attach rows; new top-level `would_attach_jobs`; a resolution to a
    missing/deleted customer is excluded as `resolved_customer_invalid` so preview
    and commit agree. Preview still writes nothing.
  - **Reverse (safety-critical):** reversing an attached row soft-deletes **only the
    imported Job — never the pre-existing customer**; the customer-pristineness
    guards (`customer_missing_or_deleted` / `customer_modified` /
    `customer_has_other_jobs`) are skipped for attach, while the job-pristineness
    guards still apply. A normal new-customer reverse is unchanged (soft-deletes both).
- **Why:** make the reviewer's explicit same-customer decision actually consolidate
  multi-job customers at commit, safely and reversibly, with no auto-merge.
- **Files:** `backend/app/services/{import_commit,import_commit_preview,import_reverse}.py`,
  `backend/app/schemas/import_staging.py`, `backend/tests/test_import_resolution_commit.py`.
- **Temporary or permanent:** Permanent. **No migration** (uses the B2-1 columns).
- **Risks / follow-up:** `resolved_customer_missing` is defensive-only — the B2-1 FK
  plus soft-delete-only model means a resolved target row always exists, so the
  reachable invalid case is `resolved_customer_deleted`. Frontend resolution actions
  are **Section B2-3** (not in this pass).

## 2026-06-17 — Section B2-1: persisted same-customer resolution state (storage/API only)

- **What:** Foundation for manual same-customer resolution. Adds five nullable
  columns to `import_rows` — `resolved_customer_id` (FK customers, indexed),
  `customer_resolution_mode` (null/`new`/`existing`), `customer_resolution_reason`,
  `resolved_by_id` (FK users), `resolved_at` — plus a review-service API to set the
  resolution to an **existing** live customer, set it to **new**, or **clear** it.
  New admin-only endpoint `POST /imports/{batch}/rows/{row}/resolve-customer`
  (`mode` = existing/new/clear). Editable only while the row is **pending**; locked
  once approved/committed (reopen to change). Validates the target customer exists
  and is not soft-deleted; never silently falls back from existing→new.
- **Why:** record an explicit, auditable reviewer decision so multi-job customers
  (e.g. two Phillip Schuman rows) can later be committed under one customer —
  without any auto-merge.
- **Files:** `backend/app/models/import_staging.py`, migration
  `c7d8e9f0a1b2_import_row_customer_resolution.py`,
  `backend/app/schemas/import_staging.py`, `backend/app/services/import_review.py`,
  `backend/app/api/v1/endpoints/imports.py`, `backend/tests/test_import_resolution.py`.
- **Temporary or permanent:** Permanent. **One additive migration** (all columns
  nullable; existing rows read as unresolved = current behaviour; no backfill).
- **Risks / follow-up:** **Storage only — does NOT affect commit-to-live, commit-
  preview, or reverse yet.** Honouring the resolution at commit (create-vs-attach,
  preview create-vs-attach counts, and a reverse that soft-deletes only the job for
  an attached row) is **Section B2-2**, which is required before resolution has any
  live effect. Frontend candidate actions are **Section B2-3**. The mode/customer
  invariant is service-enforced (no DB CHECK, matching existing migration style).

## 2026-06-16 — Section C: conservative NMI "Same" carry-forward

- **What:** At parse time, an NMI cell reading `Same` / `as above` / `ditto`
  carries the **previous related row's** real NMI forward **only** when the
  immediately previous job/ambiguous row has a plausible real NMI **and** both
  addresses normalize to the same base property (allowing one clear leading
  dwelling prefix — `House 2 -`, `Unit B -`, `Flat 1/`). Otherwise it stays
  "Same" and keeps its `nmi_unmatched` review warning. The carry resets at a
  divider (section boundary), not at blank rows. Conservative — **prefer false
  negatives over false positives**; never cross-link two properties' meters. The
  resolved value flows only through `parsed["nmi_raw"]` (→ `build_details` →
  commit); the raw cell keeps "Same" plus `nmi_same_carried` / `nmi_same_original`
  audit markers. Independent of customer/name matching.
- **Why:** the legacy workbook abbreviates a secondary dwelling's meter as
  "Same"; this fills the real NMI safely without guessing across properties.
- **Files:** `backend/app/services/import_parser.py`,
  `backend/tests/test_import_nmi_same.py`.
- **Temporary or permanent:** Permanent. **No migration.** Parse-time only — no
  commit-to-live change except via the parsed NMI value.
- **Risks / follow-up:** Affects **future** parses only; applying it to
  already-staged batches needs a fresh re-ingest/reparse. "Same" is preserved as
  context, not yet written into committed internal notes (optional follow-up).

## 2026-06-16 — Job labels, import parser/review refinements, dev reset tools (incl. commits 199cbf7, b5ad78e, 05bb381, 2255179)

- **What:**
  - **Job labels** — operational *workflow signals*, not decorative tags. A seeded
    catalogue (`job_label_definitions`) + per-job assignments
    (`job_label_assignments`). Approval state is "law": at most one **system**
    approval label (Needs approval / Pending approval / Approved) + a decommission
    preset, all auto-assigned at import commit and edited only via the structured
    controls (`/jobs/{id}/approval`, system labels are not manually add/removable).
    Operational labels (Admin work required, Battery only, Existing solar, Awaiting
    documents, Needs maintenance) are user-managed via `/jobs/{id}/labels`.
    (`warranty_issue` was rekeyed to `admin_work_required`.)
  - **Import parser/review refinements** (Section A + follow-ups): approval
    REFERENCE numbers are preserved into On Commit / Job Internal Notes;
    approval-ACTION phrases ("DO APPROVAL", "NEEDS APPROVAL", …) classify as
    **Needs approval** (not Approved); a numeric-panel + inverter job with no
    explicit approval evidence is derived as **Needs approval** at parse time
    (matching the commit-time auto-label, one shared predicate); benign name-cell
    suffixes (booked/prescreened dates, vm/on fb/pole/agreed, SV submitted, export,
    invoice-sent, free-form notes) are stripped from the customer name and kept
    verbatim in internal notes; the duplicate "Imported review/source notes" panels
    were removed and the customer file no longer shows an imported-source panel —
    preserved context lives only in On Commit / Job Internal Notes.
  - **Dev/system-admin reset tools** (`199cbf7`): admin-only **Clear imports** and
    **Clear live CRM** danger-zone actions — refused in production, requiring an
    exact typed confirmation phrase; deliberately no "clear everything".
- **Why:** make labels the operational filtering/workflow layer; keep imported
  context clean and non-duplicated (in one place, not scary panels); give admins a
  safe, gated way to reset dev data between import trials.
- **Files:** `backend/app/{models/job_label.py, services/{job_labels,import_parser,
  import_details,import_commit,dev_reset}.py, schemas/job_label.py,
  api/v1/endpoints/{job_labels,dev_reset}.py}` + matching frontend label/import
  components and the dev-reset panel; tests across import/label/reset.
- **Temporary or permanent:** Permanent. Migrations: the two `job_label_*` tables
  (+ catalogue seed). Parser/note refinements affect **future** parses only —
  applying them to already-staged/committed rows requires a re-ingest + recommit.
- **Risks / follow-up:** Reset tools are destructive (gated, dev/non-prod only).
  **Since landed:** Section D (Jobs list labels/filter/columns, `c2746a0`),
  Section B1 advisory same-customer match candidates (`5a80cdd`), and conservative
  NMI "Same" (C — see entry above). **Still proposed:** B2/B3 multi-client
  linking/merge and future NAS document classification.

## 2026-06-14 — Spreadsheet import pipeline: parse → review → commit → reverse (commits f938100 → a60fe83)

- **What:** Built the full legacy-workbook migration pipeline, admin-only, in
  small reviewed slices (each its own commit):
  - **A** (`f938100`) parse-only staging tables (`ImportBatch`/`ImportRow`/
    `ImportIssue`) + `POST /imports`; no live writes.
  - **B1** (`a979079`) review backend: typed whitelist edit, approve/reject/skip/
    reopen, resolve issues, bulk-approve-clean, audit columns.
  - **B2** (`5c23e3b`) admin review UI (`/imports`, `/imports/:id`): upload,
    filters/search, paginated table, row drawer.
  - **C0** (`6b248d2`) read-only commit-preview + `jobs.legacy_reference` column
    (the **only** import migration, `91a6e16b2a20`).
  - **pre-C1 refinement** (`6fce2a5`) made `address` a reviewable/editable field
    and added a read-only date-orientation audit that **confirmed DD/MM is
    correct** (so `date_day_mismatch` warnings reflect an unreliable Day column,
    not a date error, and are non-blocking).
  - **C1** (`2fa8aa3`) commit-to-live engine: create live Customer + Job from
    approved rows, **cap 25/call**, create-only, per-row durable, idempotent,
    one `RECORD_IMPORTED` activity/job.
  - **C2** (`90fd83c`) commit UI: preview/confirm/result modal.
  - **C3a** (`724a140`) scoped reverse engine: per-row, soft-delete-only undo of
    a **pristine** imported record; **C3b** (`7c55aaf`) the reverse UI.
  - **Case-year guard** (`a60fe83`): excludes rows whose derived case-number year
    is outside `2020 … current year + 1` (`invalid_case_year`).
- **Why:** Replace the messy ~2,500-row legacy spreadsheet with structured live
  records, **non-destructively** — staging + human review + explicit, capped,
  reversible commit, so a migration mistake can be caught (or undone) before it
  spreads.
- **Files:** `backend/app/{models,schemas,services,api/v1/endpoints}/import_*`
  and the live `customers`/`jobs`/`activity` services they reuse; one migration
  (`legacy_reference`); `frontend/src/{components/imports,pages,hooks,lib,types}`.
- **Temporary or permanent:** Permanent. **One migration** (`legacy_reference`);
  all status/activity additions are string enums (no migration).
- **Status / safety:** The real workbook is staged as **`ImportBatch` 388 (dev
  DB only; real PII — never committed to git)**, **2,561 rows**. A **supervised
  3-row trial** has now been committed to live (**3 committed / 2,558 pending**,
  3 `committed_*` links); the trial's imported Customers/Jobs are **pristine and
  reversible while unchanged**. Live totals after the trial: **19 customers /
  22 jobs / 131 activities**. No live write happens until a row is approved
  **and** a commit is explicitly confirmed.
- **Risks / follow-up:** Only the supervised 3-row trial has been committed; the
  remaining 2,558 rows are unmigrated. The next safe step is to continue the
  supervised migration in small approved batches (review/correct rows → approve a
  subset → **commit ≤25/call** → inspect). No NAS work has started. v1 maps one
  Customer per Job, keeps salesperson/
  installer as text, single-line address; no NAS/reference catalogs/StaffDirectory/
  status labels/CustomerContact, no batch/bulk reverse, no re-commit-after-reverse.
  Frontend `npm run lint` remains red from **pre-existing** unrelated errors
  (`JobDetailPage`, `SchedulePage`).

## 2026-06-13 — Spreadsheet dry-run parser + `ref/` ignore (commit 87c6475)

- **What:** Added `backend/scripts/import_dryrun.py`, a **read-only** analysis
  tool for the legacy jobs workbook (COMPLETED sheet): classifies rows and parses
  fields into a dry-run report. Ignored `ref/` (real customer PII workbook) in
  `.gitignore`. Added `openpyxl` to `requirements.txt`. Documented in
  DEVELOPER_HANDOFF §5a.
- **Why:** Smallest safe step toward migrating the legacy spreadsheet — surfaces
  real data patterns/issues before any schema or live import is built.
- **Files:** `backend/scripts/import_dryrun.py`, `.gitignore`,
  `backend/requirements.txt`, `DEVELOPER_HANDOFF.md`.
- **Temporary or permanent:** Permanent (analysis tool). **No DB writes, no
  migration.**
- **Risks / follow-up:** Not a live import. The real workbook must stay
  git-ignored (PII). Findings (e.g. ~39% date/day mismatches from Excel date
  coercion, staff-name aliasing, unmatched NMI prefixes) feed the future staged
  import pipeline.

## 2026-06-12 — Weekly Scheduling (commit f3ae1e6)

- **What:** A custom weekly schedule board at `/schedule` (expandable "Week of …"
  sections, "Needs scheduling" panel, reschedule modal). Backend: extended
  `GET /jobs` with `install_date_from` / `install_date_to` / `unscheduled=true`
  filters. *(An initial FullCalendar implementation was pivoted out before commit
  at the owner's request — no calendar-grid dependency remains.)*
- **Why:** Operational scheduling surface over existing `Job.install_date`; a
  weekly board fits the workflow better than a calendar grid.
- **Files:** `backend/app/services/jobs.py`, `backend/app/api/v1/endpoints/jobs.py`,
  `backend/tests/test_jobs.py`, frontend `pages/SchedulePage.tsx`,
  `components/ScheduleJobModal.tsx`, `lib/jobs.ts`, `App.tsx`, `AppLayout.tsx`.
- **Temporary or permanent:** Permanent. Query-only — **no migration**.
- **Risks / follow-up:** Calendar window caps at the jobs endpoint's 100-row
  limit (a 9-week span exceeding that is not expected in v1). No drag/drop or
  time-of-day scheduling.

## 2026-06-12 — Tasks (commit 709234f)

- **What:** Tasks feature end-to-end: schemas/service/endpoints
  (list/create/get/PATCH/complete/reopen/soft-delete), per-task permissions,
  dynamic `is_overdue` (computed, never stored), `TASK_CREATED/UPDATED/DELETED`
  activity types (existing `TASK_ASSIGNED/COMPLETED`), read-only
  `GET /users/selectable` for assignee pickers, multi-status labels deferred.
  Frontend: `/tasks` page, Customer/Job task panels, dashboard widget.
- **Why:** Accountability/ownership of recurring work, linkable to customers/jobs.
- **Files:** `backend/app/{models/task.py,models/enums.py,schemas/task.py,
  services/tasks.py,api/v1/endpoints/tasks.py,api/v1/endpoints/users.py,
  schemas/user.py,api/v1/router.py}`, `backend/tests/test_tasks.py`, +frontend
  task types/api/hooks/components/pages, dashboard, Customer/Job detail.
- **Temporary or permanent:** Permanent. New activity values are varchar +
  `is_overdue` is computed — **no migration**.
- **Risks / follow-up:** Completion notes via `window.prompt` (could become an
  inline modal). Shared-admin task clearing not yet built.

## 2026-06-12 — Activity Timeline (commit dfcdf76)

- **What:** Read-only `list_activities` service + `GET /activities?customer_id=&
  job_id=` (newest-first, actor, raw meta, paginated); dark Timeline component
  wired into Customer and Job detail (replacing placeholders). Also made the two
  job case-number tests independent of pre-existing soft-deleted jobs.
- **Why:** Surfaces the append-only audit trail already written by Customers/Jobs.
- **Files:** `backend/app/{schemas/activity.py,services/activity.py,
  api/v1/endpoints/activities.py,api/v1/router.py}`, `backend/tests/test_activities.py`,
  `backend/tests/test_jobs.py`, +frontend `components/Timeline.tsx`,
  `hooks/useActivities.ts`, `lib/activities.ts`, Customer/Job detail, `types`.
- **Temporary or permanent:** Permanent. Read-only — **no migration**.
- **Risks / follow-up:** Standalone tasks (no customer/job link) won't appear in
  any timeline until a global activity feed exists.

## 2026-06-12 — SunCentral dark theme (commit bd1970f)

- **What:** Full dark brand theme: Tailwind semantic tokens (charcoal surfaces,
  SunCentral orange accent, muted text) + reusable button/input/card/badge
  classes; restyled shell, login, dashboard, Customers/Jobs pages, modals,
  tables, status badges; mobile table overflow fixed (horizontal scroll).
- **Why:** Brand alignment with the SunCentral flyer; usable internal-ops feel.
- **Files:** `frontend/tailwind.config.js`, `frontend/src/index.css`, and the
  shell/login/dashboard/Customers/Jobs components/pages (visual/CSS only).
- **Temporary or permanent:** Permanent (brand direction). Visual/CSS only — no
  backend/DB/logic change.
- **Risks / follow-up:** Single dark theme (no light/dark toggle). A real logo
  asset is deferred (text wordmark used).

---

## 2026-06-12 — Jobs phase

Priority #4 built end-to-end on the existing `Job` model. Notable changes:

### 1. `Job` child cascades changed to non-destructive
- **What:** `Job.tasks` / `Job.activities` / `Job.documents` cascades changed
  from `all, delete-orphan` to `save-update, merge`.
- **Why:** Jobs are soft-deleted, never hard-deleted; activities are append-only.
  Consistent with the Customer decision. Scoped to Job relationships only.
- **Files:** `backend/app/models/job.py`.
- **Temporary or permanent:** Permanent. ORM-only, **no migration**.

### 2. New `JOB_DELETED` activity type
- **What:** Added `ActivityType.JOB_DELETED`. Jobs log
  `JOB_CREATED` / `JOB_UPDATED` (incl. initial install-date set) /
  `JOB_STATUS_CHANGED` / `INSTALL_RESCHEDULED` / `JOB_DELETED`, each linked to
  both `customer_id` and `job_id`.
- **Files:** `backend/app/models/enums.py`, `backend/app/api/v1/endpoints/jobs.py`.
- **Temporary or permanent:** Permanent. `activity_type` is varchar — no migration.

### 3. Jobs feature
- **What:** Schemas (`schemas/job.py`), service (`services/jobs.py`) with
  case-number generation + `IntegrityError` retry, endpoints (`endpoints/jobs.py`):
  list/filter/search, create (from customer), get, PATCH (descriptive + install,
  conditional per-field permissions), dedicated `POST /jobs/{id}/status`, soft
  delete. Frontend: types/api/hooks, status badges, global `/jobs` page + nav,
  `/jobs/:id` detail shell with status/edit/reschedule/delete controls, and a
  Jobs panel on the Customer detail page.
- **Permission matrix:** view = all; create/edit-descriptive = admin+sales_admin;
  install date = admin+scheduling; status = admin+sales_admin+scheduling+approvals;
  delete = admin; support read-only. A PATCH touching both descriptive fields and
  install_date enforces both requirements.
- **Files:** `backend/app/schemas/job.py`, `backend/app/services/jobs.py`,
  `backend/app/api/v1/endpoints/jobs.py`, `backend/app/api/v1/router.py`,
  `backend/tests/{conftest.py,test_jobs.py}`, and frontend `lib/jobs.ts`,
  `hooks/useJobs.ts`, `auth/permissions.ts`, `components/{JobStatusBadge,JobCreateModal,JobsTable,CustomerJobsPanel}.tsx`,
  `pages/{JobsListPage,JobDetailPage}.tsx`, `pages/CustomerDetailPage.tsx`,
  `components/AppLayout.tsx`, `App.tsx`, `types/index.ts`.
- **Database:** No migration — `jobs` table + `JobStatus` already exist in the
  baseline migration; the two changes above are ORM/enum-only.

---

## 2026-06-12 — Customers phase

First full feature built end-to-end on the foundation. Notable decisions/changes:

### 1. `Customer.jobs` cascade changed to non-destructive
- **What:** `relationship(... cascade="all, delete-orphan")` →
  `cascade="save-update, merge"` on `Customer.jobs`.
- **Why:** Customers are soft-deleted (`deleted_at`), never hard-deleted. The
  original cascade would hard-delete child jobs on an (accidental) ORM delete.
  The new cascade persists relationship changes without delete/orphan-removal.
  (Approved; scoped to Customer only — Job child cascades are left for the
  Jobs/soft-delete review.)
- **Files:** `backend/app/models/customer.py`.
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** ORM-only, no migration. Other models still use
  `all, delete-orphan`; revisit per-entity as soft-delete patterns land.

### 2. New `CUSTOMER_DELETED` activity type
- **What:** Added `ActivityType.CUSTOMER_DELETED`. Create/update/delete log
  `CUSTOMER_CREATED` / `CUSTOMER_UPDATED` (with changed field names in `meta`) /
  `CUSTOMER_DELETED`.
- **Why:** Distinct, queryable audit category for soft deletes.
- **Files:** `backend/app/models/enums.py`, `backend/app/api/v1/endpoints/customers.py`.
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** `activity_type` is `varchar` — no migration.

### 3. Database-backed test fixtures added
- **What:** `tests/conftest.py` gained a rollback-isolated `db_session`
  (SQLAlchemy "create_savepoint" mode) + a `client_for(user)` TestClient factory
  that overrides `get_db` and `get_current_user`. Tests never persist data.
- **Why:** Needed to test create/list/search/update/soft-delete/permissions
  against a real database without polluting it.
- **Files:** `backend/tests/conftest.py`, `backend/tests/test_customers.py`.
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** Tests run against the configured DB inside a rolled-back
  transaction; a reachable Postgres is required (already the case in CI/compose).

### 4. Tooling: `.claude/launch.json` for preview verification
- **What:** Added a minimal launch config so the browser-preview tool can drive
  the running frontend. Dev tooling only — not application code.
- **Files:** `.claude/launch.json`.
- **Temporary or permanent:** Permanent (tooling).
- **Risks / follow-up:** None.

> **Windows/Docker note (not a code change):** the Vite dev server in the
> container does not see host file edits (inotify doesn't cross the Windows bind
> mount), so a `docker compose restart frontend` is needed to pick up new
> files during development. Production builds (`npm run build`) read files
> fresh and are unaffected.

---

## 2026-06-12 — Runtime verification fixes (post-foundation)

After a Docker runtime verification pass, the following minimal fixes were made
to make the foundation actually boot, authenticate, and build. None change the
architecture; they correct foundation defects surfaced only at runtime.

### 1. Model registration at startup (auth login 500 → fixed)
- **What:** `backend/app/main.py` now imports the aggregated model registry
  (`from app.db import base as _model_registry  # noqa: F401`), with a comment
  marking it load-bearing.
- **Why:** SQLAlchemy could not resolve string-based relationships (e.g.
  `relationship("Customer")`) because not all models were registered before the
  first query, causing `/auth/login` to return 500.
- **Files:** `backend/app/main.py`.
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** The import must not be "cleaned up" as unused — comment
  added to prevent that.

### 2. 204 No Content routes (route registration crash → fixed)
- **What:** Added `response_model=None` to the password-reset and deactivate-user
  routes.
- **Why:** FastAPI asserts a 204 response must not declare a body; the `-> None`
  return annotation otherwise made it infer one (`AssertionError` at startup).
- **Files:** `backend/app/api/v1/endpoints/users.py`.
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** None.

### 3. First-admin email must use a valid domain
- **What:** Replaced `admin@helios.local` with `admin@example.com` in both
  committed env templates.
- **Why:** `email-validator` rejects reserved domains like `.local`, so the
  backend failed to import settings. (The local `.env` was already adjusted
  during verification; this propagates the fix to the committed examples so
  fresh setups don't hit the same wall.)
- **Files:** `.env.example`, `backend/.env.example`.
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** Operators must set a real admin address in their `.env`.

### 4. Initial Alembic migration committed as the baseline
- **What:** `backend/alembic/versions/b9a0ae06a010_init_core_schema.py` is kept
  and treated as the reviewed baseline. README and DEVELOPER_HANDOFF now tell
  first-run users to `alembic upgrade head` (not autogenerate).
- **Why:** A committed, reviewed baseline migration is reproducible across
  environments — supersedes the original "generate on first run" approach (see
  foundation item 4 below).
- **Files:** `backend/alembic/versions/b9a0ae06a010_init_core_schema.py`,
  `README.md`, `DEVELOPER_HANDOFF.md`.
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** Regenerate only on deliberate model changes (new
  migration, never editing this baseline).

### 5. Frontend build/typecheck unblocked
- **What:** (a) `frontend/tsconfig.node.json` no longer sets `noEmit` (which
  caused `TS6310` for a referenced composite project); emit is redirected to a
  gitignored temp dir. (b) Added `@types/node` so `vite.config.ts` (which uses
  `node:path` and `__dirname`) type-checks.
- **Why:** `npm run typecheck` and `npm run build` both failed; the scaffold was
  only verified via Python `compileall`, missing these TS config defects.
- **Files:** `frontend/tsconfig.node.json`, `frontend/package.json`.
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** `@types/node` is now visible to app code too; not a
  build risk. The non-standard single-root tsconfig could later be migrated to
  the conventional `tsconfig.app.json` / `tsconfig.node.json` split if desired
  (not required now).

---

## 2026-06-12 — Project foundation established

### 1. Authentication: JWT chosen (over server-side sessions)
- **What:** The foundation implements stateless JWT auth (short-lived access
  token + longer refresh token), not server-side sessions.
- **Why:** The spec explicitly permits *either* session-based or JWT auth. JWT
  fits the decoupled React SPA + FastAPI REST split with no session store, and
  keeps the backend horizontally scalable. Confirmed with the project owner.
- **Files:** `backend/app/core/security.py`, `backend/app/api/deps.py`,
  `backend/app/api/v1/endpoints/auth.py`, `frontend/src/lib/api.ts`,
  `frontend/src/auth/AuthContext.tsx`.
- **Temporary or permanent:** Permanent (revisit token storage if exposed
  beyond the VPN — see risk below).
- **Risks / follow-up:** Tokens are stored in browser `localStorage`, which is
  acceptable for a LAN-first internal tool but susceptible to XSS. If the app is
  exposed more broadly, migrate to httpOnly refresh cookies + in-memory access
  tokens, and add token revocation/blacklist. No logout-side token invalidation
  yet (stateless tokens remain valid until expiry).

### 2. Password hashing library: `argon2-cffi` directly
- **What:** Argon2id hashing via `argon2-cffi`'s `PasswordHasher` (not via
  passlib).
- **Why:** Spec prefers Argon2. Using `argon2-cffi` directly avoids passlib's
  current maintenance/compatibility friction and gives first-class Argon2 with
  `check_needs_rehash` support.
- **Files:** `backend/app/core/security.py`, `backend/requirements.txt`.
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** None significant. Cost parameters use library defaults;
  tune for the deployment hardware if needed.

### 3. DB driver: `psycopg` (v3)
- **What:** PostgreSQL accessed via `psycopg` v3 (`postgresql+psycopg://`).
- **Why:** Modern, actively maintained successor to psycopg2; works cleanly with
  SQLAlchemy 2.0.
- **Files:** `backend/requirements.txt`, `backend/app/core/config.py`.
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** None.

### 4. Schema managed by Alembic migrations, not `create_all`
- **What:** Tables are created/evolved through Alembic migrations. The app does
  not call `Base.metadata.create_all()` at startup.
  > **Updated 2026-06-12 (see "Runtime verification fixes" §4 above):** the
  > initial migration is now committed as the reviewed baseline. First run is
  > just `alembic upgrade head` — it is no longer generated by the developer, and
  > `versions/` is no longer empty.
- **Why:** Reproducible, reviewable schema history shared across dev/test/prod —
  required by the spec's database-first and environment-separation principles.
- **Files:** `backend/alembic/*`, `backend/alembic.ini`, `README.md`.
- **Temporary or permanent:** Permanent.
- **Risks / follow-up:** None for first run (`alembic upgrade head` applies the
  committed baseline). New model changes still require a new autogenerated
  migration.

### 5. Compose runs the Vite dev server for the frontend
- **What:** The `frontend` service in `docker-compose.yml` runs `vite` (dev
  server) rather than building static assets behind a production web server.
- **Why:** Optimizes for the current development phase and hot reload.
- **Files:** `docker-compose.yml`, `frontend/Dockerfile`.
- **Temporary or permanent:** Temporary (development convenience).
- **Risks / follow-up:** For production, build static assets (`npm run build`)
  and serve via a reverse proxy (e.g. Caddy/Nginx) that also fronts the API and
  terminates TLS. Tracked in DEVELOPER_HANDOFF.md.

### 6. Case number generation strategy (count-based, not a DB sequence)
- **What:** `SCS-<year>-<00001>` numbers are derived by counting existing jobs
  for the year, relying on the unique constraint + caller retry for races.
- **Why:** Simple and adequate for the expected low write concurrency on job
  creation; avoids per-year sequence management for now.
- **Files:** `backend/app/services/case_number.py`, `backend/app/models/job.py`.
- **Temporary or permanent:** Temporary-ish — revisit if job-creation
  concurrency rises.
- **Risks / follow-up:** Under high concurrent inserts, two requests could
  compute the same number; the unique constraint rejects the loser and the
  caller must retry. Consider a dedicated PostgreSQL sequence per year if needed.

---

> When you change anything structural (stack, schema strategy, auth, deployment,
> NAS approach, core workflow), add a dated entry above **before or with** the
> change — never silently.
