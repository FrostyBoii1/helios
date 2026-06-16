# Project Overview

Helios Core is a full-stack operations platform that replaces spreadsheet-based
workflows with a structured, multi-user web application. This document explains
the current architecture, setup, folder structure, key workflows, data models,
API structure, and deployment.

> Authoritative documentation lives in this repository — not in any chat history.
> Read this, `docs/`, and `CHANGES.md` before starting new work.

## 1. Architecture at a glance

```
 Browser (React SPA)
   │  HTTPS/HTTP, JWT bearer tokens
   ▼
 FastAPI backend  ──►  PostgreSQL  (jobs, customers, users, activities, …)
   │
   └──►  NAS / storage filesystem  (documents & photos; metadata in Postgres)
```

- **Frontend** — React + TypeScript SPA (Vite). Talks to the backend over REST,
  caches/refreshes data with TanStack Query, routes with React Router.
- **Backend** — FastAPI exposes a versioned REST API (`/api/v1`). Pydantic
  validates I/O; SQLAlchemy 2.0 maps the relational model; services hold domain
  logic; an append-only activity log records auditable actions.
- **Database** — PostgreSQL is the system of record. Schema evolves via Alembic.
- **Files** — Documents/photos stay on the NAS or `storage/`; only **metadata**
  (path, type, links, uploader) is stored in PostgreSQL.

See [docs/architecture.md](docs/architecture.md) for detail.

## 2. Folder structure

```
backend/
  app/
    main.py              FastAPI app factory + router wiring
    seed.py              idempotent role + first-admin seeding
    core/
      config.py          env-based settings (pydantic-settings)
      security.py        Argon2 hashing + JWT create/verify
      logging.py         structlog configuration
    db/
      base_class.py      DeclarativeBase + naming conventions
      base.py            imports all models (Alembic autogenerate target)
      session.py         engine + get_db dependency
    models/              SQLAlchemy models (one file per entity) + mixins/enums
    schemas/             Pydantic request/response models
    services/            domain logic (users, activity, case_number)
    api/
      deps.py            DB/session, current-user, role guards
      v1/
        router.py        aggregates endpoint routers
        endpoints/       auth.py, users.py, health.py
  alembic/               migration environment + versions/
  tests/                 pytest smoke tests
frontend/
  src/
    main.tsx             providers (QueryClient, Auth) + render
    App.tsx              route table
    auth/AuthContext.tsx session + login/logout
    lib/api.ts           fetch client with token refresh
    lib/queryClient.ts   TanStack Query config
    components/          ProtectedRoute, AppLayout
    pages/               LoginPage, DashboardPage, NotFoundPage
    types/               shared TS types (mirror backend schemas)
docs/                    architecture, database_schema, business_rules
```

## 3. Key workflows (current)

### Authentication
1. User POSTs email/password to `/api/v1/auth/login`.
2. Backend verifies the Argon2 hash and returns an access + refresh token pair.
3. The SPA stores tokens, then calls `/auth/me` to load the user + role.
4. Protected API routes require a valid access token; the SPA guards routes via
   `ProtectedRoute`. On a 401 the client transparently refreshes once.

### Admin user management
- Admin-only endpoints under `/api/v1/users` create, list, update, reset
  passwords for, and deactivate accounts. Every action writes an activity entry.
- The first admin is bootstrapped by `python -m app.seed` from `FIRST_ADMIN_*`.

### Activity logging (foundation in place)
- `services/activity.log_activity(...)` appends an immutable timeline/audit row
  recording the action, actor, affected entity, and structured detail. Feature
  endpoints call it within their transaction.

## 4. Data models

Core entities: **User, Role, Customer, Job, Task, Activity, Document**, plus the
**job-label** catalogue/assignments and the **import staging** tables.

- A **Customer** has many **Jobs** (customers and jobs are separate entities).
- A **Job** has a unique `case_number` (e.g. `SCS-2026-00001`), a status, key
  dates, assigned staff, and many Tasks / Activities / Documents.
- **Tasks** carry an owner, status, priority, due date, and completion log.
- **Activities** are append-only (the timeline + audit log).
- **Documents** store file metadata only; bytes live on NAS/storage.
- **Job labels** are a seeded catalogue (`job_label_definitions`) + per-job
  `job_label_assignments`. They are operational workflow signals; approval state is
  represented by one **system** approval label, auto-assigned at import commit and
  edited via the structured approval control (operational labels are user-managed).
- **Import staging** (`import_batches` / `import_rows` / `import_issues`) holds the
  legacy-workbook migration; rows become live Customer/Job records only via an
  explicit, admin-confirmed commit (see `docs/business_rules.md`).
- Business records use timestamps + soft delete (`deleted_at`); activities are
  permanent.

Full detail and relationships: [docs/database_schema.md](docs/database_schema.md).

## 5. API structure

- Versioned under `/api/v1`.
- Current routers:
  - `GET /health`, `GET /health/db` — liveness/readiness.
  - `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me`.
  - `GET/POST /users`, `GET/PATCH/DELETE /users/{id}`,
    `POST /users/{id}/reset-password` (admin), `GET /users/selectable` (any auth).
  - `GET/POST /customers`, `GET/PATCH/DELETE /customers/{id}`.
  - `GET/POST /jobs`, `GET/PATCH/DELETE /jobs/{id}`, `POST /jobs/{id}/status`
    (jobs list also supports `install_date_from/to` + `unscheduled` for scheduling,
    a `label` filter, and embeds customer suburb/state + label chips per row).
  - `GET/POST /tasks`, `GET/PATCH/DELETE /tasks/{id}`,
    `POST /tasks/{id}/complete`, `POST /tasks/{id}/reopen`.
  - `GET /activities?customer_id=&job_id=` — read-only timeline.
  - **Imports** (admin-only): `POST /imports` (parse-only upload),
    `GET /imports[/{id}[/rows[/{rowId}]]]`, row review (`PATCH` edit,
    `approve`/`reject`/`skip`/`reopen`, `PATCH issues/{id}`,
    `bulk-approve-clean`), `GET …/summary`, `GET …/commit-preview`,
    `POST …/commit` (capped commit-to-live), and per-row reverse
    (`GET …/reverse-check`, `POST …/reverse`).
  - **Job labels:** `GET /job-labels` (catalogue), `GET/POST/DELETE
    /jobs/{id}/labels` (operational labels), `PUT /jobs/{id}/approval` (the
    structured approval control — sets the single system approval label).
  - **Dev reset** (admin, non-production): `GET /dev/reset/counts`,
    `POST /dev/reset/imports`, `POST /dev/reset/live-crm` (typed-phrase confirmed).
- Interactive docs at `/docs` (Swagger UI) when the backend runs.
- The standard feature pattern: **schema validation → permission check → DB
  transaction → activity log → typed response** (see `endpoints/users.py`).

## 6. Configuration

All configuration is environment-driven (`.env`, see `.env.example`). Key vars:
`SECRET_KEY`, `POSTGRES_*`, `BACKEND_CORS_ORIGINS`, `FIRST_ADMIN_*`, `NAS_ROOT`,
`STORAGE_ROOT`, and `VITE_API_BASE_URL` for the frontend.

## 7. Deployment

- `docker compose up -d --build` starts PostgreSQL, the backend, and the
  frontend dev server. Designed for local-network access first; remote access
  should be via VPN or another protected method.
- Migrations (`alembic upgrade head`) and seeding (`python -m app.seed`) are run
  as explicit steps (see README). For production, build the frontend to static
  assets and front everything with a TLS-terminating reverse proxy
  (see CHANGES.md item 5).

## 8. Conventions

- TypeScript strict mode; modular files; clear separation of layers.
- No business data hardcoded where a DB record belongs.
- Soft deletes for business-critical records; append-only activity history.
- Document any deviation from `BASE.txt` in `CHANGES.md` before/with the change.
