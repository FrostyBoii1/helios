# Developer Handoff

Onboarding for anyone picking up Helios Core. Read this together with
`PROJECT_OVERVIEW.md`, `docs/`, and `CHANGES.md`. The repository — not chat
history — is the source of truth.

## 1. What exists today

The foundation plus the core workflow (Customers → Jobs → Activity Timeline →
Tasks → Weekly Scheduling) and the SunCentral dark theme are implemented at
HEAD `87c6475`. Implemented:

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
- Tests: backend smoke (no DB) + database-backed Customers (10), Jobs (17 +3
  scheduling filters), Tasks (16), Activity (9) integration tests
  (rollback-isolated). 58 backend tests total.

## 2. What is NOT built yet

These are stubbed/absent and represent the next phases:

- **NAS file** integration: browse/link a job/customer's NAS folder, uploads,
  in-browser PDF/image preview, permission-gated serving (the `documents` table
  exists; no service/endpoints/UI). Job detail shows a Documents placeholder.
- **Staged spreadsheet import/review pipeline** — only the read-only dry-run
  parser exists today (§5a); no `ImportBatch`/`ImportRow`/`ImportIssue` tables,
  no live customer/job creation, no reference catalogs (Distributor/Retailer/
  HardwareCatalog/StaffDirectory) or status labels.
- **Reporting/analytics** and **reminders/notifications**.
- **Frontend user-management** screens (the API exists; UI does not).
- Job **tags/flags** UI beyond status; **shared-admin task clearing**.
- Production deployment (static frontend build + reverse proxy + TLS).

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

The core workflow (Customers → Jobs → Activity Timeline → Tasks → Weekly
Scheduling) and the dark theme are done. Reasonable next choices, in order of
recommendation:

1. **Staged spreadsheet import/review pipeline** — build on the dry-run parser
   (§5a): `ImportBatch`/`ImportRow`/`ImportIssue` staging tables, a persisted
   dry-run report, and a human review queue **before** any live customer/job
   creation. This is the safe foundation for migrating the legacy workbook
   (≈1,672 completed jobs) and would need the first import-related migration, so
   plan it first. Reference catalogs (Distributor/Retailer/HardwareCatalog/
   StaffDirectory) and status labels are built incrementally against its output.
2. **NAS file integration** (baseline priority #8) — link each job/customer to
   its NAS folder, list/upload/preview files with permission gating. Heavier
   (storage mounts, path safety), so plan-first.
3. **Reporting/analytics** (#9), then **notifications** (#10).

Either path warrants a plan-first pass given the schema/migration and
storage/permission complexity.

## 5a. Spreadsheet import — dry-run parser (read-only, analysis only)

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
dependency is `openpyxl` (in `requirements.txt`). This dry-run informs the
design of the future staging/review import pipeline; no schema or migration
exists for import yet.

## 6. Gotchas / conventions

- **Never** call `Base.metadata.create_all()` — schema is Alembic-only.
- **Always** import new models in `app/db/base.py` or autogenerate misses them.
- Keep endpoints thin; put logic in services.
- The backend is the permission authority; never trust the client.
- Files: store **relative** paths + metadata only; validate paths and check
  permissions before serving. Never run destructive NAS operations.
- Keep `CHANGES.md` current — propose structural changes before making them.
