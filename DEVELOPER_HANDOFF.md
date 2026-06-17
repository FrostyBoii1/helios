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
  shell (status/edit/reschedule/delete), and a Jobs panel on Customer detail.
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
  customer page's jobs table shows per-job **Site** (the global Jobs list keeps the
  customer Suburb/State for now — deferred). **Stage 2** (first-class queryable `Job`
  site columns + migration/backfill, only if site must be filter/searchable in Section D)
  remains optional future work — **not built**.
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
  final/historical summary instead of active candidate/group controls; review buttons
  are status-aware (pending → Approve/Reject/Skip; finalized → status + Reopen);
  "Search existing customers" is pending-only, 2+ chars, with loading / no-results
  guidance. **(Grouping-lifecycle stabilization — built)** commit & preview share
  `plan_group_commit`: unapproved/ineligible grouped members are auto-detached at commit
  (only approved + eligible rows commit — grouped rows are never auto-approved), with the
  primary re-promoted to the lowest-index eligible member; reverse re-promotes a grouped
  primary and clears the group's committed link when the last grouped job is reversed;
  committed/reversed rows can't be reopened via the review-status flow; a grouped
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
  mutation; dismissal only. Pending/group candidates (`customer_id` null) show no
  Preview button; previewing a pending row's parsed import data is deferred. **(B4 —
  proposed)** auto-link/merge for identical names; existing-customer merge.
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
  UI confirm modal + read-only "Reversed" state.
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
