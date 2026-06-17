# CHANGES.md

This file records every meaningful deviation from the baseline specification
(`BASE.txt`). The baseline is the source of truth; anything that departs from it
must be justified here, per project governance.

Each entry records: **what** changed, **why**, **files affected**, whether it is
**temporary or permanent**, and any **risks / follow-up**.

---

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
