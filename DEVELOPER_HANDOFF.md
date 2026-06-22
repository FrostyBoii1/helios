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
  Tests `tests/test_hardware_runtime.py` (16). **NOT wired into import yet** (Stage 4B); legacy
  `details.system.panel/inverter` text coexists. Deferred: full multi-fragment bundle parsing + panel
  system-size derivation. Then the remaining lane stages still consume this
  API: current-sheet import integration; panel integration; clean
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
