# Developer Handoff

Onboarding for anyone picking up Helios Core. Read this together with
`PROJECT_OVERVIEW.md`, `docs/`, and `CHANGES.md`. The repository — not chat
history — is the source of truth.

## 1. What exists today (the foundation)

The project foundation is complete and aligns with the spec's "Initial
Implementation Task". Implemented:

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
- Tests: backend smoke (no DB) + database-backed Customers (10) and Jobs (17)
  integration tests (rollback-isolated).

## 2. What is NOT built yet

These are stubbed/absent and represent the next phases:

- **Activity timeline** endpoint + UI (logging is written for customers and jobs;
  the Customer and Job detail pages show Timeline placeholders) — recommended next.
- **Tasks** workflow (model exists; no service/endpoints/UI).
- **Scheduling** calendar view (FullCalendar).
- Job **tags/flags** UI beyond status.
- **Tasks** UI + shared-admin clearing + overdue surfacing.
- **NAS file** browsing/linking + uploads + previews + permission gating.
- **Reporting/analytics**, **reminders/notifications**.
- **Frontend user-management** screens (the API exists; UI does not).
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

Per the spec's development priority order (schema → auth → customers → jobs →
activity → tasks → …), the foundation, auth, **Customers**, and **Jobs** are
done. The next task is the **Activity timeline** (priority #5 surface):

1. `schemas/activity.py` — `ActivityRead` (type, description, actor, meta,
   created_at).
2. `services/activity.py` — add a read/list helper (by `customer_id` and/or
   `job_id`, newest-first, paginated). Logging already exists.
3. `endpoints/activities.py` — `GET /activities?customer_id=&job_id=` (read-only;
   all authenticated roles).
4. Frontend: a Timeline component wired into the Customer detail and Job detail
   placeholder panels.

This surfaces the audit trail already being written by Customers and Jobs — low
risk, high value, no new write paths. After that: **Tasks** (priority #6).

## 6. Gotchas / conventions

- **Never** call `Base.metadata.create_all()` — schema is Alembic-only.
- **Always** import new models in `app/db/base.py` or autogenerate misses them.
- Keep endpoints thin; put logic in services.
- The backend is the permission authority; never trust the client.
- Files: store **relative** paths + metadata only; validate paths and check
  permissions before serving. Never run destructive NAS operations.
- Keep `CHANGES.md` current — propose structural changes before making them.
