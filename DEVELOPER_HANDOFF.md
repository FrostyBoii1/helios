# Developer Handoff

Onboarding for anyone picking up Helios Core. Read this together with
`PROJECT_OVERVIEW.md`, `docs/`, and `CHANGES.md`. The repository — not chat
history — is the source of truth.

## 1. What exists today

The foundation, the core workflow (Customers → Jobs → Activity Timeline →
Tasks → Weekly Scheduling), the SunCentral dark theme, the **spreadsheet import
pipeline**, an operational **job-labels** system, and successive **import
parser/review refinements** are implemented and pushed on `main` (HEAD
`2255179`). Implemented:

- Repository structure + Docker Compose (db, backend, frontend).
- FastAPI backend skeleton: config, structured logging, CORS, versioned router.
- PostgreSQL connection, SQLAlchemy 2.0, Alembic migration environment.
- Core models: Users, Roles, Customers, Jobs, Activities, Tasks, Documents
  (with timestamps, soft-delete, enums, case-number support).
- JWT auth (login / refresh / me), Argon2 hashing, RBAC dependencies.
- Admin user-management API with activity logging.
- Services: append-only activity logger, case-number generator, user logic.
- Seed script: roles + first admin (idempotent).
- React/TS frontend skeleton: login, protected routes, role-aware dashboard
  shell, token-refreshing API client, TanStack Query setup.
- **Customers** (priority #3) — full stack: schemas, service (ILIKE search,
  soft-delete-aware), endpoints (list/create/get/update/soft-delete) with the
  approved role matrix + activity logging; `Customer.jobs` cascade made
  non-destructive; React list (search/pagination), create modal, detail shell
  (with Jobs/Timeline placeholders), edit, delete.
- **Jobs** (priority #4) — full stack: schemas, service (case numbers with
  retry, search/filter), endpoints (list/create/get/PATCH/status/soft-delete)
  with the approved per-field role matrix + activity logging; `Job` child
  cascades made non-destructive; React global `/jobs` page, `/jobs/:id` detail
  shell (status/edit/reschedule/delete), a Jobs panel on Customer detail, and a
  compact display-only "Other jobs for this customer" panel on Job detail (sibling
  jobs, current excluded, hidden when none) for multi-job navigation.
- **Activity Timeline** (priority #5) — read-only `list_activities` service +
  `GET /activities?customer_id=&job_id=` (newest-first, actor, raw meta); dark
  Timeline component wired into Customer and Job detail. Surfaces the existing
  audit trail; no new write paths.
- **Tasks** (priority #6) — schemas, service, endpoints
  (list/create/get/PATCH/complete/reopen/soft-delete) with per-task permissions
  (admin-or-creator edit/reassign/reopen; assignee-or-admin complete; admin
  delete); dynamic `is_overdue`; `TASK_CREATED/UPDATED/ASSIGNED/COMPLETED/DELETED`
  activities; read-only `GET /users/selectable` for assignee pickers; React
  global `/tasks` page, Customer/Job task panels, dashboard "My open tasks".
- **Weekly Scheduling** (priority #7) — a custom weekly board (`/schedule`):
  expandable "Week of …" sections (current week + next 8) with per-week counts,
  a "Needs scheduling" panel, and a reschedule modal (admin/scheduling). Backed
  by `GET /jobs` `install_date_from/to` + `unscheduled=true` filters. No
  calendar-grid dependency.
- **SunCentral dark theme** — Tailwind tokens + reusable button/input/card/badge
  classes; restyled shell, login, dashboard, all feature pages, mobile-friendly.
- **Spreadsheet import pipeline** (§5a) — parse-only staging, review backend +
  UI, commit-preview, commit-to-live (+ UI), scoped reverse (+ UI), and a
  case-year guard.
- **Job labels** (workflow signals, not decorative tags) — a seeded catalogue
  (`job_label_definitions`) + per-job `job_label_assignments`. Approval state is
  represented by at most one **system** approval label (Needs approval / Pending /
  Approved) + a decommission preset, auto-assigned at commit and edited only via
  the structured approval control; **operational** labels (Admin work required,
  Battery only, Existing solar, Awaiting documents, Needs maintenance) are
  user-managed. APIs: `GET /job-labels`, `GET/POST/DELETE /jobs/{id}/labels`,
  `PUT /jobs/{id}/approval`.
- **Import parser/review refinements** (Section A + follow-ups) — approval
  references kept in Job Internal Notes; approval-action phrases and numeric-panel
  + inverter jobs derive **Needs approval**; benign name-cell suffixes cleaned and
  preserved verbatim in internal notes; duplicate imported review/source panels
  removed (preserved context lives only in On Commit / Job Internal Notes). **(F —
  built)** `parse_address` peels an obvious trailing non-address note after a valid AU
  "STATE POSTCODE" tail (e.g. "… Leeton 2705 NSW - 405 for the bill" → clean
  line1/suburb/state/postcode + a `note`), surfaced as neutral imported review context;
  the raw cell keeps the full original. Conservative — only a dash/semicolon/pipe
  delimiter AFTER the tail, so a hyphenated street ("5-7 Smith St") is never split.
  **(G Stage 1 — built)** per-job / site address for multi-job customers: `build_details`
  writes a display-only `details.site` (line1/line2/suburb/state/postcode/note/structured/
  raw) on every job from the parsed address, persisted in `Job.details` (JSONB, NO
  migration). Each grouped/attached job keeps its OWN site while the Customer headline
  address stays the primary/new-customer address. Job detail prefers the job's site; the
  customer page's jobs table shows per-job **Site**; the global Jobs list (since `889b377`)
  is `Case # | Site | Name | Status | Labels | Install date`. **Source/original-name provenance
  (read-model):** `JobRead.source_customer_name` is an additive COMPUTE-ON-READ field (no migration,
  no writes) for when a job belongs to its current customer under a DIFFERENT name. Two sources,
  MERGE first (`services/jobs.py source_customer_names_for_jobs`): (1) `CUSTOMER_MERGED` activity
  metadata (`merge_source_names_for_jobs` — earliest merge wins for chains); else (2) the IMPORT row
  the job was committed/attached from (`import_source_names_for_jobs` reads
  `ImportRow.parsed['customer_name']` via `committed_job_id`, normalised same-name suppression). The
  CustomerContactVariant is NOT used (its capture is conditional/incomplete). The two customer-
  specific job panels (Customer Detail + Job Detail other-jobs, which hide the Name column) render it
  as a small "Originally <name>" line under the case number; null for normal/same-name jobs.
  **Stage 2** (first-class queryable `Job` site columns + migration/backfill, only if site must be
  filter/searchable in Section D) remains optional future work — **not built**.
- **Dev/system-admin reset tools** — admin-only, non-production **Clear imports** /
  **Clear live CRM** with an exact typed confirmation phrase (`/dev/reset/*`).
- Tests: backend smoke (no DB) + database-backed integration tests
  (rollback-isolated) across Customers/Jobs/Tasks/Activity, the import pipeline,
  labels, and reset tools. **~300 backend tests** at HEAD (Section D adds more,
  in progress). Verify before staging with the full backend suite + frontend
  typecheck/build.

## 2. What is NOT built yet

These are stubbed/absent and represent the next phases:

- **In progress — Section D (Jobs list labels/filter/columns):** the Jobs list
  now embeds Suburb/State + label chips and a single-label filter, with the
  customer-embedded jobs table widened (no scrollbar on desktop). Status-column
  cleanup is deliberately deferred (no `JobStatus` changes yet).
- **Import matching:** **(B1 — built, advisory only)** a read-only same-customer
  candidate engine surfaces possible same-customer rows/customers (with reasons +
  a confidence band) in the import row drawer; no merge/link/auto-action.
  **(B4-0 — built, refactor)** the pure scoring core (`Signature` / `build_signature`
  / `score` + the entity / address / normalization rules) now lives in
  `app/services/matching_core.py`, shared verbatim by import matching and the future
  B4 live-CRM duplicate detection — no behaviour change; `import_matching` re-exports it.
  **(C — built)** a conservative NMI **"Same"** rule carries a previous real NMI
  forward only on a strong adjacent-row + same-base-property match, else keeps the
  review issue. **Section C is parse-time only** — existing staged batches need a
  **fresh re-ingest/reparse** to pick it up. **(B2-1 — built, storage/API only)**
  an import row can store an explicit manual same-customer resolution (attach to an
  existing live customer, or new), editable while pending and locked at approval —
  **(B2-2 — built)** the resolution is now honoured live: commit attaches a
  resolved row's job to the existing customer (no new customer; a missing/deleted
  target **fails** the row, never a silent fallback); commit-preview shows
  attach-vs-create + `would_attach_jobs` and excludes an invalid resolution; and
  **reverse of an attached row soft-deletes only the imported Job, never the
  pre-existing customer**. **(B2-3 — built)** the import row modal now exposes the
  resolution UI: a pending row's "Possible same customer" candidates get a "Use this
  customer" action (live customers only), plus Create-new / Clear / existing-customer
  search and a resolution banner; locked rows show it read-only. **(B3-1 — built)**
  strong candidates show a cosmetic **★ Recommended** badge (from the B1 confidence
  band) — advisory only, never auto-selected. **(B3-2 — built, storage only)** an
  admin API groups ≥2 pending rows into one future customer (`import_customer_groups`
  + `import_rows.customer_group_id`, `mode='group'`). **(B3-3 — built)** grouped rows
  now commit as **one customer + N jobs** (primary creates / dependents attach,
  contiguous primary-first ordering with cap-split deferral); preview shows
  "1 customer + N jobs" (`group_primary`/`group_dependent`); reverse soft-deletes the
  shared customer only on its **last** active job (non-last = job-only). B2 attach +
  'new' reverse unchanged. **(B3-4 — built)** the import modal exposes the grouping
  UI: a pending batch-row candidate gets "Group as same customer", a group banner
  (members + Primary + commit note) with set-primary / remove / dissolve, and an
  "In group ✓" state — distinct from B2's "Use this customer". **(Phase 2
  stabilization — built)** same-customer candidates dedupe by live `customer_id` (one
  candidate per customer, reasons merged); committed/reversed rows show a
  final/historical summary instead of active candidate/group controls. **(#5b fix —
  built)** `find_candidates` excludes REVERSED sibling rows entirely and only exposes a
  sibling's `committed_customer_id` when that customer is still live — so a reversed /
  soft-deleted customer is never offered as a "Use this customer" candidate (the
  live_customer branch already filtered `deleted_at`; this closes the same gap in the
  batch_row branch). Pending grouped candidates still expose `customer_group_id`. Review
  buttons
  are status-aware (pending → Approve/Reject/Skip; finalized → status + Reopen);
  "Search existing customers" is pending-only, 2+ chars, with loading / no-results
  guidance. **(Grouping-lifecycle stabilization — built)** commit & preview share
  `plan_group_commit`: unapproved/ineligible grouped members are auto-detached at commit
  (only approved + eligible rows commit — grouped rows are never auto-approved), with the
  primary re-promoted to the lowest-index eligible member; reverse re-promotes a grouped
  primary and clears the group's committed link when the last grouped job is reversed;
  committed/reversed rows can't be reopened via the generic review-status flow (a reversed
  row uses Section D "Prepare recommit" instead — see §5a); a grouped
  candidate can't be silently stolen (server hard-reject) — the modal offers "Join this
  group" using the candidate's `customer_group_id`; the match-candidates cache is
  invalidated on any batch change. **(Group read-model UI — built)** every cached
  match-candidates panel refetches after a batch mutation (`refetchType: 'all'`, so a
  stale "Group as same customer" disappears once siblings group/commit/reverse and
  collapse to one "Use this customer"), and committed/reversed grouped rows show a
  read-only group-status block (members + per-member primary/review state + the
  committed-customer link) so a re-promoted primary is visible. **(H — built)** each
  "Possible same customer" candidate that resolves to a committed customer gets a
  **Preview** button opening a strictly read-only modal (`CandidatePreviewModal`):
  it composes the existing read-only GETs `useCustomer(id)` + `useJobs({customer_id})`
  to show the customer's name/contact/headline address and their jobs (each with the
  job's own `details.site`, status, labels) — no new endpoint, no action callbacks, no
  mutation; dismissal only. **(H2 — built)** Preview now ALSO works for staged
  `batch_row` candidates (those with a `row_id`, e.g. pending sibling rows that have no
  live customer yet): the button opens `CandidateRowPreviewModal`, which composes the
  existing read-only `useImportRow(batchId, rowId)` (`GET /rows/{id}`) to show that
  candidate row's parsed/review data — name, source row #/ref, review status, parsed
  address + `details.site`, contact (emails/phones), dates/approval, group status, and a
  committed-customer link (new tab) if it already committed — read-only, dismiss-only, no
  navigation away. A `batch_row` always previews the staged row; a pure `live_customer`
  candidate previews the customer. **(B4-1 — built, storage foundation only)** schema +
  helper scaffolding for a future explicit admin **existing-customer merge**, with **no
  execution**: `customers.merged_into_customer_id` (nullable, indexed, self-FK, NO ACTION) +
  `customers.merged_at`, `ActivityType.CUSTOMER_MERGED`, a pure-read cycle-guarded
  `resolve_active_customer(db, id)` chain-walk helper (loser→winner; no callers yet), and
  `dev_reset.clear_live_crm` nulling `merged_into_customer_id` before deleting customers.
  **(B4-2 — built)** the merge now EXECUTES: admin-only `POST
  /customers/{loser_id}/merge-into/{winner_id}` runs `merge_customers` in one transaction —
  repoints every customer FK loser→winner (Job/Activity/Task/Document + the import links
  committed/resolved/group customer ids), appends loser notes into `winner.internal_notes`
  with a provenance header (winner contact/address authoritative, untouched), soft-deletes
  the loser + sets `merged_into_customer_id`/`merged_at` (never hard-deletes), and emits a
  `CUSTOMER_MERGED` activity on the winner. Single-pair, `merged_into` immutable, NO migration
  (head stays `e9f0a1b2c3d4`). **Reverse safety:** `reversibility()` gains a
  `job_customer_mismatch` guard and the merge bumps moved `Job.updated_at` so a post-merge
  reverse is blocked by `job_modified` — a merged job can never be reversed into deleting the
  winner (Prepare recommit is the correction path). **(B4-3 — built)** an admin-only
  **"Merge into…"** action on Customer Detail drives this: a modal searches/selects another
  live customer (the winner), shows an explicit confirmation/preview (winner fields stay
  authoritative; loser notes appended; jobs/tasks/documents/activities/import links move; loser
  hidden; no unmerge), then `POST`s the merge, invalidates caches, and navigates to the winner.
  Frontend-only (+ a `CustomerMergeResult` type). **(B4-4 — built)** a stale/bookmarked
  merged-loser URL no longer feels like a mystery 404: `GET /customers/{merged_loser_id}` still
  returns 404 (deleted stays hidden) but with an enriched detail `{reason:"merged",
  merged_into_customer_id, merged_into_name}` resolved to the final live winner via
  `resolve_active_customer`; Customer Detail shows a "merged into {name}" notice + link to the
  winner (no auto-navigation, no 3xx redirect, no soft-deleted loser data). Missing /
  normally-deleted / broken-chain / cyclic ids keep the plain 404; list/search and import
  matching are unchanged. Still deferred: unmerge and batch merge. **(Customer variants —
  Stage 2 built)** a new `customer_contact_variants` table + read-only
  `GET /customers/{id}/contact-variants` + a Customer-Detail "Alternate contact details" card
  preserve/display alternate customer-level name/email/phone/address sets (provenance-linked,
  soft-deletable) without overwriting the primary fields or stuffing them into notes. **(Stage 3
  built)** a B4 merge now CAPTURES the loser's meaningfully-different customer-level fields as a
  `merged_customer` variant on the winner (only when something differs; winner primary fields
  unchanged; `source_customer_id` stored but never exposed by the read API). **(Stage 4 built)**
  admins can manually ADD a variant (`POST /customers/{id}/contact-variants`, forced
  `source_type=manual`, rejects an all-blank entry) and ARCHIVE manual variants
  (`DELETE …/{variant_id}`, soft-delete only) from the Customer-Detail card — source-derived
  (merged) variants are immutable and NOT archivable; admin-only writes, reads unchanged.
  **(Corrective pass built)** import COMMIT now captures customer-level CONTACT identity too:
  when a row attaches to an existing customer (B2) or is a grouped DEPENDENT, the row's DIFFERING
  name/email/phone (+ extras in a note) are preserved as an `import_row` variant on the target
  customer (`capture_import_contact_variant`) — additive, never mutating the customer's primary
  fields; nothing captured when nothing differs. The row ADDRESS is NOT captured (it is the job's
  `details.site`, kept job-scoped). Reversing the row archives the variant it contributed.
  `dev_reset.clear_live_crm` now clears `customer_contact_variants` before customers. The
  Customer-Detail card is reframed as **"Known customer details"** (compact one-line sets, neutral
  source labels, primary Details stays the source of truth). **(Editable + provenance pass built,
  migration `b2c3d4e5f6a7`)** Known Customer Details are now EDITABLE customer-level records: admin
  `PATCH /customers/{id}/contact-variants/{variant_id}` edits ANY source_type (manual OR source-
  derived) — updating only the variant + stamping `edited_at`/`edited_by_id`, NEVER the primary
  Customer, the job, the import row, or the variant's provenance (`source_type`/source ids stay
  immutable). The read API adds SAFE computed provenance (`source_row_number` = workbook row index,
  `source_job_case_number`, `source_job_id`, `source_reversed`) so the card shows which import
  row/job contributed each detail (raw source FK ids still DB-only). Reverse now archives a
  contributed `import_row` variant ONLY while unedited — an EDITED detail SURVIVES reversal (its
  provenance then shows the source row as reversed). `dev_reset.clear_imports` detaches
  `source_import_row_id` from live variants before deleting import rows (FK-gap fix). **Promote-to-
  primary remains deferred** (an edit never touches the primary Customer), as do backfill and
  document/NAS capture. **(B4 — proposed)** auto-link/merge for identical names.
- **Hardware Parser / Hardware Database** lane: **(Stage 0 built)** the curated parser package
  (v9.1 hardware + v1.1 panel) is vendored as LAW under **`docs/parser_specs/hardware/`** (see its
  `README.md`) and gated by `backend/tests/test_hardware_parser_spec_validation.py` (unique
  catalogue/fixture IDs, no alias collisions, `source_examples`≠aliases, confidence vocabularies,
  panel `model: null` rules, version-drift pin). The backend reads the spec via a read-only mount
  (`./docs/parser_specs:/app/parser_specs:ro`). **(Stage 1 built, migration `c3d4e5f6a7b8`)**
  DB-backed `hardware_catalogue` + `hardware_aliases` (soft-deletable) now exist, seeded
  idempotently from the YAML by `app.hardware.seed.seed_hardware_catalogue` (wired into
  `python -m app.seed`): **167 catalogue rows** (95 inverter + 45 battery + 20 panel + 7 metering)
  + **274 matchable aliases** (exact/loose/case-sensitive). `source_examples` are NOT seeded
  (evidence only, never matchable); ignore/correction/guard/normalization rules stay versioned
  config. The catalogue is reference data with no FK to/from Jobs, so `dev_reset` is unchanged.
  **(Stage 2A built — backend admin API)** `/api/v1/hardware` (`services/hardware.py` +
  `schemas/hardware.py` + `endpoints/hardware.py`) — **every route admin-only** (`require_admin`):
  catalogue list (search `q` + filters category/brand/phase/nominal_kw/capacity_kwh/wattage_w +
  `deleted=exclude|only|include`), create/get/update (spec_id immutable)/**soft-delete**/restore,
  and nested admin-only alias CRUD + soft-delete/restore (`/{id}/aliases…`). Never hard-deletes;
  deleted entries move to the DELETED section (`deleted=only`) and restore with aliases intact;
  same-key alias re-create restores a soft-deleted row; aliases are never exposed to non-admins.
  No migration (uses the Stage-1 tables). **(Stage 2B-1 built — frontend read-only Settings UI)**
  the app's first **Settings** area: an admin-only gear in the top bar (`canManageHardware`) →
  **`/settings/hardware`** (`components/SettingsLayout.tsx` + `pages/SettingsHardwarePage.tsx`, with
  a `lib/hardware.ts` + `hooks/useHardware.ts` READ layer + `types` mirroring `schemas/hardware.py`).
  It lists the catalogue with debounced search, filters (category/brand/phase/category-aware size),
  an Active/Deleted/All view, per-row alias counts, and pagination. The `/settings` route group is
  `ProtectedRoute allowedRoles={['admin']}` and the gear is hidden for non-admins (the backend still
  enforces `require_admin` — the UI never gates on its own). **(Stage 2B-2 built — catalogue write
  UI)** the same screen now has a **New hardware** action, per-row **Edit** / **Delete** (active) /
  **Restore** (deleted), and a shared `components/HardwareFormModal.tsx` (create + edit) with
  category-aware fields; `spec_id` is required on create and read-only on edit (immutable). The
  `lib/hardware.ts` + `hooks/useHardware.ts` WRITE layer (`create`/`update`/`delete`(soft)/`restore`
  + `useCreate/Update/Delete/RestoreHardware`) invalidates the whole `['hardware']` key so the list
  + facet dropdowns refetch; delete is a `window.confirm` soft-delete, restore is explicit; 409 →
  duplicate-spec_id copy, 403/404/422 handled. Edit sends a **true partial PATCH** (only changed
  fields) so it never wipes untouched columns. **(Stage 2B-3 built — alias management UI, COMPLETES
  Stage 2B)** a per-row **Aliases** action (active rows) opens `components/HardwareAliasModal.tsx`
  for that item: it names the item (`spec_id`), lists its aliases (value, type
  exact/loose/case_sensitive, confidence override, decision_log_id, Active/Deleted state) with a
  Show All/Active/Deleted filter, an inline Add/Edit form, soft-delete (`window.confirm`) + restore;
  409 → duplicate (hardware_id, alias, alias_type) copy. The `lib/hardware.ts` + `hooks/useHardware.ts`
  alias layer (`listAliases`/`create`/`update`/`delete`(soft)/`restore` +
  `useHardwareAliases`/`useCreate/Update/Delete/RestoreAlias`) invalidates `['hardware']` so the alias
  list AND the catalogue `alias_count` refetch. Aliases are never exposed to non-admins.
  Still **no backend change**, no parser runtime, and no Job/import wiring. **Stage 2B is now
  complete** — the whole admin Settings > Hardware management surface (catalogue + aliases) exists.
  **(Stage 3A built — Job hardware snapshot, backend)** the PLACE hardware lives on a Job now
  exists: `Job.details.hardware` JSONB (inverters/batteries/metering lists, a panel object,
  site_notes, warnings) — **no new table, no migration**. The existing path-restricted Job-details
  PATCH (`services/details_patch.merge_details_patch`, live jobs only) now accepts the `hardware`
  key, validated by a strict shape schema `schemas/job_hardware.py` (`JobHardwarePatch`,
  `extra='forbid'` — the schema-level whitelist; unknown fields/wrong types → 422); each provided
  sub-section replaces that whole sub-section, absent ones preserved, all else unchanged. **Hard
  snapshot rule enforced + tested** (`tests/test_jobs_hardware_snapshot.py`, 8): catalogue/alias
  edits + soft-delete/restore never mutate a Job snapshot; a hardware edit never touches the
  catalogue; `canonical_hardware_id_at_parse_time` is debug-only; the NULL-details guard still holds;
  jobs without `details.hardware` read safely. **(Stage 3B built — Job Detail hardware UI, frontend)**
  a compact **Hardware** section on Job Detail (`components/JobHardwareSection.tsx`, rendered below
  Details; top "other jobs" panel + existing sections untouched) reads + edits the snapshot:
  add/edit/remove inverter/battery/metering rows, edit the panel + site notes + warnings, Edit/Cancel/
  Save (gated by `canEditJobDetails`) saving the whole hardware object through the existing
  `useUpdateJob` PATCH (`{ details: { hardware } }`) — NO new API/hook, NO backend change. It reads
  ONLY `job.details.hardware` (no catalogue read/dropdown, no live update from Settings > Hardware;
  shows a snapshot note), renders safely when details/hardware are absent, and on a `details=null`
  job is read-only ("available once structured job details exist" — never auto-initialises details).
  Provenance shown subtly; `canonical_hardware_id_at_parse_time` carried but never display truth.
  Frontend snapshot types live in `types/imports.ts` (+ `ParsedDetails.hardware`) and match the
  backend exactly. **Stage 3 is now complete.** **(Stage 4A built — parser runtime, the catalogue
  consumer)** a standalone read-only `app/hardware/runtime.py` (`parse_hardware`) + versioned-config
  loader `app/hardware/rules.py`: source-agnostic (strings + `source_type`/`source_field`), it reads
  the DB catalogue/aliases + versioned policy (normalization / ignore / corrections / guard phrases /
  site-note keywords / panel brand+wattage routing / confidence vocab / pinned `parser_rule_version`)
  and emits a `JobHardwarePatch`-valid snapshot (validated via the adapter). Matching: exact/loose/
  case_sensitive (Jinko≠JINKO), metering first-class, `source_examples` never match, guard suppression,
  correction override, ignore rules, unknown preserved (never guessed), panel `model:null` unless
  confident + `model_options`. **Mutates nothing.** **C1 resolved**: `site_notes` ct/export_limit/
  underground/comms are now **lists** (schema + frontend + Stage-3B editor textareas; JSON-shape only,
  no migration). **C2 resolved**: `ignored`/`raw_evidence` stay parser-internal; messages → `warnings`.
  Tests `tests/test_hardware_runtime.py`. **(Quantity fix — `runtime.py`)** explicit quantity is
  preserved: `_QTY_RE` reads `N x` / `N × ` / `N*` (x/×/* separator, optional spacing) into the item's
  `quantity`; `_extract_bare_quantity` splits a bare `N MODEL` ONLY when the remainder resolves to a
  catalogue hit (so `40kw hrs` / `10kw 3 phase` are never mis-split); pure battery ENERGY capacity
  (`_CAPACITY_RE`: `40kw hrs` / `40kwh`, NOT bare `10kw` power) routes to `site_notes.raw_misc` instead
  of contaminating the inverters bucket / any `model_text`; an unmatched explicit-`N ×` fragment stores
  the model **core** with the quantity held separately (no duplication). Still never guesses, never
  matches `source_examples`, validates against `JobHardwarePatch`, mutates nothing. The display side
  renders `quantity > 1` as "N × MODEL" and round-trips it (`lib/hardwareDisplay.ts`).
  **(Hardware Parser P1 — separator splitting, runtime)** `_split_fragments` (new module regex
  `_FRAGMENT_SPLIT_RE`) now also breaks a hardware cell on `/`, `·`, `•`, `&`, and the whole words
  `and` / `with` (was only `+` and a spaced ` - `) — the joiners the E2E audit found the real workbook
  uses for inverter/battery/metering/capacity bundles. Model-safe: only a SPACED ` - ` splits (never a
  model-internal hyphen like `X1-BOOST-5K-G4`), and `/`,`•`,`&`,`and`,`with` occur in no
  inverter/battery/metering model; `·` is normally rewritten to `-` by `_normalize_encoding` first, so
  `MODEL · 25kWh` already split via the hyphen rule (the `·` in the pattern is a safety net). Panel
  parsing never uses the splitter. Result: `1 x SAJ H2-10K-S3 and 2 x SAJ B2-15.0-HV1` now resolves to
  inverter + qty-2 battery; `… · 25kWh` routes capacity to `site_notes.raw_misc`; source_examples still
  never resolve (the `… AND …` example splits into raw fragments — invariant preserved). 611 backend
  tests pass.
  **(Hardware Parser P2 — brand-prefix / noise normalization, runtime)** when a fragment does not
  match directly (or via the quantity retries), `_normalized_hit` retries resolving it after stripping
  a known leading brand prefix (`_BRAND_PREFIXES`: Sungrow, Solax/Solax Power, SAJ, Goodwe, Solis,
  Neovolt/Nevolt, Alpha ESS/Alpha-ESS) + an optional single leading power token (`_LEADING_POWER_RE`,
  e.g. `10kW`, never energy `kWh`) and/or a trailing hardware-type noun (`_TRAILING_NOISE_RE`,
  `… BATT`/`battery`/`inverter`, space-anchored so a `-INV` model is safe). Accepted ONLY when the
  transformed remainder is itself a catalogue alias. **Purely additive** (runs only when `hit is None`,
  so it never changes a previously-matched item); **never guesses** (brand-only `Sungrow` / capacity-
  only `Solis 5kw` stay raw); **no catalogue bloat** (the brand list is a small version-controlled CODE
  constant, NOT seeded aliases and NOT in the vendored v9.1 YAML); provenance preserved (`source_fragment`
  stays original, `model_text` becomes the resolved canonical). Result: `Solax Power X1-SMT-10K-G2` ->
  `X1-SMT-10K-G2`, `Sungrow SH10RT` -> `SH10RT`, `Sungrow 10kW SH10RT/SBR128 BATT` -> inverter `SH10RT`
  + battery `SBR128`. Audit delta over COMPLETED (confidence metric): fully-clean rows **654 -> 1,153**,
  raw rows **1,029 -> 530** (~halved). 625 backend tests pass.
  **(Hardware Parser P3 — unmatched battery/metering bucket routing, runtime)** after all catalogue
  matching fails, an unmatched fragment is bucketed by `_hardware_signal(frag)` — `batteries` for a
  `batt`-word or Sungrow `SBR<digit>` (`_BATTERY_HINT_RE`), `metering` for a `meter`-word /
  `current transformer` (`_METERING_HINT_RE`), else `inverters` — so a Job never shows battery/meter
  evidence as an inverter. The same signal guards the site-note step: a metering/battery HARDWARE
  fragment (`smart meter 5kw export`) is not swallowed into a non-CT site bucket; bare CT still ->
  `site_notes.ct` (unchanged). Raw only (no canonical id invented, no model guessed); inverter stays
  the default for ambiguous capacity (`Solis 5kw`); quantity + source_fragment preserved
  (`6 x 3.2 batt` -> battery ×6); matching untouched (`SBR128 BATT` still resolves to a matched battery
  via P2). Audit delta: **130 raw items re-bucketed out of inverters** (112 batteries, 18 metering);
  fully-clean 1,153 -> 1,149 / raw 530 -> 534 (a ~4-row honesty shift: `smart meter 5kw export`
  surfaced from a hidden export-limit note into a flagged metering item). 634 backend tests pass.
  Deferred to later audit slices: **P4 catalogue adds**, metering vocab expansion, in-fragment
  capacity-in-noun extraction (`16kw hrs battery`), leading-`1`+model resolution (`1 SBR128 battery`),
  and the (un-authorized) clean-wipe + reimport.
  **(Stage 4B built — import integration, backend)** the
  runtime is now wired into the completed-sheet import via `services/import_hardware.py`
  (`enrich_row_hardware` + `validate_committed_hardware`): **ingest** (`import_ingest`) parses hardware
  ONCE, DB-aware, into `ImportRow.parsed['details']['hardware']` (the pure `import_parser` stays
  DB-free); **preview** (`map_job_preview` returns `parsed.details`) and **review** (`ImportRowRead.parsed`)
  surface that SAME stored value with NO preview/schema change; **commit** (`build_job_data` copies
  `parsed.details`) persists it verbatim into `Job.details.hardware` with a commit-boundary
  `JobHardwarePatch` validation (malformed → that row fails safely, no orphan) — the parser is NOT
  re-run at commit (no divergence). **Reverse** unchanged: a pristine imported hardware job reverses;
  a post-commit hardware edit trips the existing pristine guard (blocked, edit preserved) — no
  hardware-specific reverse logic. Read-only against the catalogue; `source_examples` never match;
  legacy `details.system.panel/inverter` text coexists. Tests `tests/test_import_hardware.py` (10).
  **(UX correction — parsed hardware as EDITABLE normal System fields)** there is NO separate hardware
  box. `lib/hardwareDisplay.ts`: `deriveSystemHardware` shows ALL parsed hardware (regardless of
  confidence) as normal System fields — **Panel type / Inverter / Battery / Metering** (+ a read-only
  **CT / electrical** row from site-notes); `deriveHardwareNotes` is SUPPLEMENTAL only (low-confidence/
  manual_review flags, ambiguous model_options, warnings, raw_misc) → small read-only
  `components/HardwareNotes.tsx`; `applyHardwareSystemEdits` maps an edited textbox back to a partial
  `details.hardware` patch. An item `quantity > 1` renders inline as **"N × MODEL"** and round-trips
  on edit (`splitQtyModel` parses the "N ×" prefix back into `quantity` + clean `model_text`, never
  baking the quantity into the text). `StructuredDetailsView` gained opt-in `hideKeys` + `systemExtras`
  + `extraEdits`/`onExtraChange`: the live Job page hides the raw `panel`/`inverter` registry fields and
  appends the hardware rows inside the System section — **editable as textboxes in edit mode** (Panel
  type/Inverter/Battery/Metering), folded into the SAME job PATCH as `details.hardware` (registry
  Number-of-panels/Storey/Phase/Roof stay registry fields). The former editor
  `components/JobHardwareSection.tsx` was **DELETED**. `components/imports/ImportRowModal.tsx` passes
  `systemExtras`+`hideKeys` (no `onExtraChange` → read-only there) so import review SHOWS the parsed
  hardware values that will commit; the Raw cells panel is untouched (raw provenance preserved). Absent
  snapshot → legacy System unchanged. Frontend-only — no backend change (the 4B snapshot is the
  source; the existing `{ details: { hardware } }` PATCH persists edits). Deferred: quantity + CT/export
  editing.
  **(H1 — staff hardware SEARCH endpoint, backend)** `GET /api/v1/hardware/search` (`endpoints/hardware.py`),
  gated on `get_current_user` (ANY authenticated staff, not admin), returns ONLY active + non-deleted
  canonical hardware as a LEAN `HardwareSearchResult` (`schemas/hardware.py`: id/spec_id/category/
  display_name/canonical_model/brand/phases/nominal_kw/capacity_kwh/wattage_w/model_options) — never
  aliases/alias_count/attributes/spec_source/is_active/created_by/timestamps/deleted rows. `q`+`category`
  filtering; reuses `list_hardware(..., active_only=True, deleted='exclude')` (new `active_only` flag,
  default False keeps the admin list unchanged); declared before `/{hardware_id}`. All admin catalogue+
  alias routes stay `require_admin`. Tests `tests/test_hardware_search.py`. **(H2 — editable import-review
  hardware, backend)** `import_review.apply_details_patch` now splits the `hardware` key out and merges it
  via the SHARED `details_patch.merge_hardware_subsections` (the renamed-public former `_merge_hardware`)
  used by BOTH live `Job.details` edits and review — one `JobHardwarePatch`-validated merge, no divergence.
  So an `ImportRowEdit.details` may carry `hardware`; invalid shape → 422; whole sub-sections replace,
  null clears, absent preserved; `original_parsed` deep-copied (audit), raw cells untouched; preview/
  commit read the same stored snapshot and commit persists it verbatim (no re-parse); approve/reject/skip/
  group unchanged. No `ImportRowEdit` schema change (its `details` is already a free dict). H2 tests in
  `tests/test_import_structured_edit.py` + `tests/test_import_hardware.py`. Both backend-only, no migration.
  **(H3 — import-review editable hardware UI, frontend)** the import row modal now renders parsed
  hardware as EDITABLE System fields with catalogue autocomplete. New `components/imports/
  HardwareSearchInput.tsx` (debounced free-text input → `GET /hardware/search` via `useHardwareSearch`;
  click a suggestion to autofill canonical text, preserving any `N ×` prefix). `StructuredDetailsView`
  gained an optional `renderExtraInput` prop + a low-confidence "review" marker
  (`SystemHardwareField.category`/`lowConfidence` from `deriveSystemHardware`). `ImportRowModal` keeps
  `hardwareEdits`+`hardwareSelections` (reset on row change; typing clears a field's stale selection)
  and folds `applyHardwareSystemEdits(hw, edits, selections)` into the SAME `ImportRowEdit.details`
  patch (`details.hardware`) saved via the existing edit API; editable only on unlocked rows; Raw
  cells + Hardware notes unchanged. **Provenance rule:** a catalogue pick stamps
  `canonical_hardware_id_at_parse_time` (provenance only), `confidence='manual_correction'`,
  `parser_owned=false`; **free-typed text drops ALL stale catalogue/parser provenance** (no carried
  canonical id / model / descriptors) and is saved as a fresh manual item (`source_type='manual'`,
  `confidence='manual_correction'`, single original `source_fragment` kept as evidence) — so a field
  never displays one model while carrying another's id. `applyHardwareSystemEdits`
  gained an optional 3rd `selections` arg and `SystemHardwareField` gained optional fields — all
  backward-compatible, so **Job Detail (which still calls the 2-arg form + no `renderExtraInput`) is
  unchanged**. Frontend-only, no backend/migration. Verified via typecheck/lint/build + an esbuild+Node
  harness over the pure `hardwareDisplay` exports.
  **(H4 — Job Detail hardware autocomplete, frontend)** committed Jobs now use the SAME
  `HardwareSearchInput` on the System hardware fields (edit mode). `HardwareSearchInput` was MOVED to
  the neutral `components/HardwareSearchInput.tsx` (shared by import review + Job Detail; ImportRowModal's
  import path updated, behaviour unchanged). `JobDetailPage` adds `hardwareSelections` + `handleHardwareSelect`,
  passes `renderExtraInput` to the edit-mode `StructuredDetailsView`, and threads selections into
  `applyHardwareSystemEdits(hw, edits, selections)` (clears a field's selection on type). Read-mode +
  `details=null` jobs stay inert; save uses the existing single job PATCH (`details.hardware` only).
  `hardwareDisplay.ts`/`StructuredDetailsView.tsx` are UNCHANGED, so provenance is identical to H3
  (selection stamps id+manual_correction; free-text drops stale id). Frontend-only, no backend/migration,
  no Settings/import-review behaviour change. NOT the always-editable overhaul (H5) — the Edit-button/
  permission gate is unchanged.
  **(H5A — Job Detail field-level autosave foundation, frontend)** the no-Save-button Job Detail
  overhaul begins. New `hooks/useFieldAutosave.ts` (per-field `draft` + `status`
  idle/dirty/saving/saved/error; the exported `canAdoptServerValue` guard adopts a refetched server
  value ONLY when idle/saved, so a window-focus/invalidate refetch never clobbers a dirty draft; no-op
  if unchanged; **retains the typed value on failure** + Retry; saves on blur for text, change for
  date — never per keystroke) + `components/AutosaveField.tsx` (input + Unsaved/Saving…/Saved ✓/Error
  indicator; read-only for non-editors). `JobDetailPage`: top-level descriptive fields (title,
  sale_date; for legacy details=null jobs the descriptive columns) are now always-editable autosave,
  each a SINGLE-field PATCH via `useUpdateJob`; the old batch `form` + global `useEffect([job])` reset
  + Edit/Save/Cancel for these fields are REMOVED (per-field reconcile replaces the global reset).
  **Temporary H5A:** structured details + hardware KEEP the Edit/Save batch flow (the Edit button now
  reads "Edit hardware & structured"; `buildPayload` covers only details+hardware) until H5B/H5C.
  Status/approval/install-date/delete/internal-notes are untouched; details=null jobs get no silent
  details init; derived blobs stay non-editable; autosave errors are per-field (not the global banner).
  Frontend-only, no backend/migration. Deferred: H5B (structured autosave), H5C (hardware autosave),
  H5D (install-date save-on-change + remove the remaining Edit/Save + polish).
  **(H5B — structured registry fields autosave, frontend)** structured Job Detail registry fields now
  autosave per-field. New `components/AutosaveControl.tsx` (the shared autosave input — text/textarea/
  number/date/select — wrapping `useFieldAutosave`; blur-commit for text/number, change-commit for
  date/select; inline state chip). `AutosaveField` (H5A) refactored to delegate to it (DRY). The shared
  `StructuredDetailsView` gained an **opt-in** `autosaveField?: (path,value)=>Promise<void>` prop
  (Job Detail passes it → registry value fields render as `AutosaveControl` saving one `section.key`
  leaf; import review passes none → batch `edits`/`onChange` path unchanged) + a `recordKey` prop so
  reveal state (show-empty/picker) resets on the record id, not every per-save refetch (import review
  without `recordKey` keeps the `details`-object reset). `JobDetailPage.saveStructuredField(path,value)`
  → `buildDetailsPatch({"section.key":value})` → `PATCH {details:{section:{key}}}` (no-op build sends
  nothing); the batch `detailsEdits`/`handleDetailsChange` + the structured part of `buildPayload` are
  REMOVED. **Temporary H5B:** hardware keeps the batch flow (Edit button relabelled "Edit hardware &
  approval"; `buildPayload`/`saveDetails` cover only hardware); approval editing gating unchanged.
  details=null → no structured inputs/init; derived fields read-only; **ImportRowModal byte-equivalent**.
  Frontend-only, no backend/migration. Deferred: H5C (hardware autosave + retire the batch/approval
  coupling), H5D (install-date save-on-change + polish).
  **(H5C — hardware fields autosave + retire the temporary batch, frontend)** Job Detail hardware
  System fields now autosave per-field. New `components/AutosaveHardwareField.tsx` (wraps
  `useFieldAutosave` + `HardwareSearchInput`: typing clears any pick + saves on blur (free text drops
  stale catalogue ids); a suggestion pick saves immediately, stamping provenance). `StructuredDetailsView`
  gained opt-in `renderAutosaveExtra` (Job Detail → autosave hardware extra; import review omits it →
  batch H3 path). `JobDetailPage.saveHardwareField(field,value,selection)` → `applyHardwareSystemEdits`
  with ONE key → `PATCH {details:{hardware:<one sub-section>}}`. `HardwareSearchInput` gained optional
  `onBlur` + (when set) suggestion `onMouseDown preventDefault` so a pick can't blur-commit first;
  `useFieldAutosave.commit` gained `{force}` (re-selection persists provenance even if text unchanged);
  `AutosaveControl` exports the shared status chip + error helper. RETIRED: the hardware Save/Cancel
  bar, the "Edit hardware & approval" button, and all hardware batch state (`editingDetails`/
  `hardwareEdits`/`hardwareSelections`/`buildPayload`/`pendingPayload`/`saveDetails`/page `describeError`).
  Approval DECOUPLED: its own "Edit approval"/"Done editing approval" toggle (`editingApproval`) gated on
  `mayEditDetails` exactly as the old button — same who-can-edit, same "label is law", own Set-approval
  mutation; NOT autosave. Status/install-date/delete/internal-notes untouched; details=null → no hardware
  inputs/init; CT/electrical + Hardware Notes read-only; **ImportRowModal byte-equivalent**. Frontend-only,
  no backend/migration. **The no-Save-button Job Detail model is now complete (descriptive + structured +
  hardware).** Deferred: H5D polish (install-date save-on-change; unify indicators; activity-log batching).
  **(H5D — install-date autosave + polish, frontend)** Install date converted from its Edit/Save/Cancel
  control to save-on-change autosave: `JobDetailPage` now renders the shared `AutosaveControl`
  (`kind="date"`) when `canEditJobInstallDate` (admin/scheduling — INSTALL_ROLES, SEPARATE from
  descriptive edit), else a read-only value; `saveInstallDate(value)` is a single-field
  `PATCH {install_date: value||null}` via the same `useUpdateJob`, never batched. Removed the
  `installDate`/`editingInstall` state and the `useEffect([job])` sync (each autosave control reconciles
  its own draft). No-op/retain-on-failure/no-clobber are inherited from `useFieldAutosave`; install-date
  errors are now the inline chip, not the page banner — so descriptive/structured/hardware/install-date
  all share ONE indicator (no new visual language). `JobApprovalControl` gained an optional `onSaved`
  (fired on a successful Set-approval) and Job Detail passes `()=>setEditingApproval(false)` to collapse
  the editor after a save — UX only, approval mutation/gating/"label is law" unchanged; still NOT
  autosave. `HardwareSearchInput` got additive keyboard + ARIA polish (Escape closes; Arrow Up/Down +
  Enter select a highlighted suggestion; combobox/listbox/option roles + `aria-activedescendant`) —
  Enter acts ONLY on an Arrow-highlighted item, so free-text/mouse/blur are unchanged. Import review is
  preserved: the Escape branch deliberately does NOT `stopPropagation`, so the import-review modal's own
  document-level Escape still closes it on a single press (the handler just also collapses an open list
  in that press — same end state); in Job Detail Escape merely closes the dropdown. Import-review DATA
  behaviour is untouched. Status (immediate-save dropdown), delete (confirm), internal-notes panel untouched.
  Frontend-only, no backend/migration, no new deps. **The no-Save-button Job Detail model is complete
  across descriptive + structured + hardware + install-date.** No headless React runner is installed, so
  the hook-level no-op/error behaviour is covered by reuse + an esbuild harness on the pure predicate +
  payload mapping (not a live render test). Deferred (minor): aria-live status announcement; activity-log
  batching.
  **Stage 4C (next)** = frontend import-review display + uncertain/manual-review badges. Deferred:
  full multi-fragment bundle parsing + panel system-size derivation; a shared-alias-index optimisation
  (today `parse_hardware` rebuilds its index per enriched row). Then the remaining lane stages still
  consume this API: panel integration; clean
  wipe + reimport; NAS/proposal later. **Keystone law:** Job hardware is a stored editable snapshot
  — catalogue renames/alias edits/deletes/restores must NOT change already-parsed Job hardware (see
  `docs/business_rules.md`). The existing `HARDWARE_UNCERTAIN` auto-label is legacy/temporary,
  to be reconciled once the parser lands (the parser itself must not create workflow labels).
- **NAS file** integration: browse/link a job/customer's NAS folder, uploads,
  in-browser PDF/image preview, permission-gated serving (the `documents` table
  exists; no service/endpoints/UI). Job detail shows a Documents placeholder.
  Future scope: **NAS document classification** (detect approval docs/case numbers
  and feed approval state) — the label/approval model is designed so an external
  source can later upgrade approval state through the same path.
- **Reporting/analytics** and **reminders/notifications**.
- **Frontend user-management** screens (the API exists; UI does not).
- Import pipeline scope **not** in v1: reference catalogs (Distributor/Retailer/
  HardwareCatalog/StaffDirectory), status-label tables, a CustomerContact table,
  batch/bulk reverse, and re-commit-after-reverse. (The **staged import/review/
  commit/reverse pipeline itself is built** — see §5a.)
- **Future task-backed labels:** some operational labels should become real
  assignable tasks (owner + due date) rather than passive flags — not yet modelled.
- **Shared-admin task clearing**; production deployment (static frontend build +
  reverse proxy + TLS).

## 3. First-run checklist

```bash
cp .env.example .env                 # set SECRET_KEY + passwords
docker compose up -d --build
docker compose exec backend alembic upgrade head   # applies the committed baseline migration
docker compose exec backend python -m app.seed
```

> The initial schema migration
> (`backend/alembic/versions/b9a0ae06a010_init_core_schema.py`) is committed as
> the reviewed baseline — do **not** regenerate it on first run. Generate new
> migrations only when you change models (step 2 in §4).

Verify:
- `http://localhost:8000/api/v1/health` → `{"status":"ok",...}`
- `http://localhost:8000/docs` → Swagger UI
- `http://localhost:5173` → login screen; sign in with the seeded admin.

## 4. How to add a feature (the standard pattern)

Follow the spec's "Feature Completion Requirements". A feature isn't done until
all of these exist:

1. **Model** — add/adjust SQLAlchemy model in `app/models/`, import it in
   `app/db/base.py`.
2. **Migration** — `alembic revision --autogenerate -m "..."`, review, then
   `alembic upgrade head`.
3. **Schemas** — request/response Pydantic models in `app/schemas/`.
4. **Service** — domain logic in `app/services/` (reusable, testable).
5. **Endpoint** — thin router in `app/api/v1/endpoints/`, wired in `router.py`.
   Order: validate → permission check → transaction → `log_activity(...)` →
   typed response.
6. **Permissions** — guard with `require_admin` / `require_roles(...)`.
7. **Activity logging** — record auditable actions.
8. **Frontend** — types in `src/types`, data hooks via TanStack Query + the
   `apiFetch` client, page/components, route in `App.tsx`.
9. **Docs** — update `docs/` and, if you deviate from `BASE.txt`, `CHANGES.md`.

Reference implementation: `app/api/v1/endpoints/users.py` shows the full pattern
end-to-end.

## 5. Recommended next task

The core workflow, dark theme, import pipeline (§5a), job labels, and the import
parser/review refinements are done. Reasonable next steps, in order:

1. **Finish Section D** (Jobs list labels/filter/columns) — in progress; then run
   the pre-staging audit → stage → commit → push (see §7).
2. **Import matching — Section B4 (next, proposed)** — B1 advisory candidates, the
   NMI **"Same"** rule (C), B2 (resolution storage/commit/preview/reverse + UI), and
   the full B3 stack (B3-1 Recommended, B3-2 grouping storage/API, B3-3 grouped
   commit/preview/reverse, B3-4 grouping UI) have all landed. The remaining proposed
   work is **B4: existing-customer merge** (combining two live customers) and/or
   auto-link for identical names. Still **no silent merges**.
3. **NAS file integration** (baseline priority #8) — link each job/customer to its
   NAS folder, list/upload/preview with permission gating; later, **document
   classification** feeding approval state. Heavier (storage mounts, path safety) —
   plan-first.
4. **Reporting/analytics** (#9), then **notifications** (#10).

> **The dev DB is volatile.** The legacy workbook is re-imported / reset
> frequently during trials, so batch ids and live customer/job/row counts change
> between sessions. Treat any live count as a snapshot, never a fixture, and never
> assume a specific batch id. A live import commit and the NAS work each warrant
> care (live writes / storage + permission complexity).

## 5a. Spreadsheet import pipeline (parse → review → commit → reverse)

The legacy-workbook migration is built end to end, admin-only. Phases (each its
own commit; see CHANGES.md):

- **A — staging**: `POST /imports` parses an `.xlsx` (in memory, never written
  to disk) into `ImportBatch`/`ImportRow`/`ImportIssue`. No live writes.
- **B1/B2 — review**: edit the parsed candidate (whitelisted `ImportRowEdit`
  fields incl. address), approve/reject/skip/reopen, resolve issues,
  bulk-approve-clean; admin review UI (`/imports`, `/imports/:id`) with
  filters/search, paginated table, and a row drawer.
- **C0 — commit-preview**: `GET /imports/{id}/commit-preview` (read-only)
  reports eligibility, excluded reasons, and **predicted (estimated)** case
  numbers. Added `jobs.legacy_reference` (nullable, indexed).
- **C1/C2 — commit-to-live**: `POST /imports/{id}/commit` creates live
  Customer + Job from approved rows, **capped at 25 rows/call**, create-only,
  idempotent (skips already-committed + duplicate `legacy_reference`), one
  `RECORD_IMPORTED` activity per job; UI preview/confirm/result modal.
- **C3a/C3b — scoped reverse**: `GET …/reverse-check` + `POST …/reverse`
  (per-row) soft-delete the created Customer + Job **only** while pristine
  (re-checked server-side), set the row `reversed`, log `RECORD_IMPORT_REVERSED`;
  UI confirm modal + "Reversed" state with a **Prepare recommit** action.
- **D — reverse-then-recommit (built)**: `POST …/rows/{id}/prepare-recommit`
  (admin; 409 unless the row is `reversed`) is the ONLY sanctioned exit from the
  terminal `reversed` state — the generic `/reopen` still 409s for committed/reversed
  rows. `prepare_recommit` stamps the prior `committed_*` ids into a
  `RECORD_IMPORT_RECOMMIT_PREPARED` activity, clears the committed links, detaches any
  group (without dissolving a still-committed group or reclaiming primary), resets
  resolution, and returns the row to `pending`. It never approves, commits, or touches
  the soft-deleted Job/Customer; a recommit then flows through the **unchanged**
  commit/preview engine and creates **brand-new** records (no migration — `details`
  live in the existing string-enum/activity columns). UI: a "Prepare recommit" button +
  confirm modal on the reversed row banner (extra group-detach warning for grouped rows).
- **Case-year guard**: a row whose derived case-number year is outside
  `2020 … current year + 1` is excluded (`invalid_case_year`) from both preview
  and commit — protects against malformed source dates minting `SCS-202-…`.

**Safety model:** no live record is created until a row is `approved` **and** a
commit is explicitly confirmed; commit is capped at 25/call; reverse is
soft-delete-only and never touches a record that's been edited/used; the
case-year guard blocks implausible years. Beyond `legacy_reference` the import
schema added the B2-1 resolution columns (`c7d8e9f0a1b2`) and the B3-2
`import_customer_groups` table (`d8e9f0a1b2c3`, current Alembic head); the
commit/reverse/case-year work itself added none (status/activity additions are
string enums). v1 maps one Customer per Job,
keeps salesperson/installer as text, and uses a single-line address — no NAS
matching, reference catalogs, StaffDirectory, status-label tables, or
CustomerContact.

The dry-run parser below shares the same parser and remains useful for offline
analysis.

### Dry-run parser (read-only, analysis only)

`backend/scripts/import_dryrun.py` is a **read-only analysis tool** for the
legacy jobs workbook. It is **NOT** a live import system:

- It reads an `.xlsx` path **passed on the command line** (never hardcoded) and
  analyses the `COMPLETED` sheet.
- It **never writes to the database**, never creates customers/jobs, and never
  modifies the workbook.
- It classifies rows (blank / divider / job / ambiguous) and attempts to parse
  legacy reference, salesperson + sale date, customer name vs extracted notes,
  approval state, phones/emails, MSB tri-state, NMI→distributor inference,
  hardware (with a confidence placeholder), dates, payment/compliance fields —
  then prints a dry-run report (counts, distributions, issues, sample rows).

Run it (the workbook lives under the git-ignored `ref/`, which holds real
customer PII and must never be committed):

```bash
python backend/scripts/import_dryrun.py "/path/to/workbook.xlsx"
python backend/scripts/import_dryrun.py "/path/to/workbook.xlsx" --samples 5
# Optional full JSON (contains PII — save only to a git-ignored dir):
python backend/scripts/import_dryrun.py "/path/to/workbook.xlsx" --json-output ref/dryrun.json
```

In the backend container the workbook is not mounted by default; copy it in
(`docker cp`) or run the script on a machine that can see the file. The only
dependency is `openpyxl` (in `requirements.txt`). The same parser backs the live
staging ingest, so the dry-run and the staged import classify identically.

## 6. Gotchas / conventions

- **Never** call `Base.metadata.create_all()` — schema is Alembic-only.
- **Always** import new models in `app/db/base.py` or autogenerate misses them.
- Keep endpoints thin; put logic in services.
- The backend is the permission authority; never trust the client.
- Files: store **relative** paths + metadata only; validate paths and check
  permissions before serving. Never run destructive NAS operations.
- Keep `CHANGES.md` current — propose structural changes before making them.

## 7. Working rules (process)

- **Order of authority** (when deciding intended behaviour):
  1. Explicit owner instructions and approved decisions.
  2. `BASE.txt` and established business rules.
  3. Current implementation, migrations, schemas, and tests (evidence of existing
     behaviour).
  4. Documentation and handoff files.
  5. Conversation history.

  If these disagree, **name the conflict — don't silently pick one.** Existing code
  is **not** automatically correct when the owner has called it a bug; stale docs
  are **not** authoritative when the implementation has clearly moved on. Reconcile
  before proceeding, and **protect important explicit decisions with tests**, not
  documentation alone.
- **After any compaction / context loss / drift, re-read first:** `BASE.txt`, the
  relevant docs (`PROJECT_OVERVIEW.md`, `docs/`, `CHANGES.md`, this file), the
  **git state** (`git status` / `log` / `diff`), **and the relevant source files**
  before giving implementation guidance. Chat memory is not the source of truth —
  the repo is.
- **Change pipeline (per change):** implement → run automated checks (full backend
  suite if backend changed; frontend typecheck + build if frontend changed) →
  **manual/browser check for any visible parser or UI change** → **pre-staging
  audit** (git status = exactly the intended files, scope check, `git diff --check`,
  DB unchanged) → **stage explicit paths** → commit → push. Each gate is owner-
  confirmed; don't skip ahead.
- **Parser/note changes affect future parses only.** Existing staged/committed rows
  need a re-ingest + recommit to reflect them — call this out, never silently
  assume live data updated.
- **Keep local notes out of commits.** `ADMIN NOTES/` (and any untracked working
  notes / PII workbooks under `ref/`) are **never staged** unless explicitly
  requested. Stage with explicit file paths, never `git add -A`.
- **Dev reset tools are destructive and admin/non-prod only** — they exist to reset
  trial data, not for routine use.
