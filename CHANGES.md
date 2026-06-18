# CHANGES.md

This file records every meaningful deviation from the baseline specification
(`BASE.txt`). The baseline is the source of truth; anything that departs from it
must be justified here, per project governance.

Each entry records: **what** changed, **why**, **files affected**, whether it is
**temporary or permanent**, and any **risks / follow-up**.

---

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
