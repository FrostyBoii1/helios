# Helios Core

A centralized, browser-based operations platform to replace the company's
spreadsheet-based workflow. Staff log in, see the work relevant to their role,
manage customers and jobs, schedule installs, track tasks, store documents
against jobs (including NAS files), and keep the business aligned around one
source of truth.

> This repository currently contains the **project foundation only** (scaffold +
> authentication). See [What's implemented](#whats-implemented) and the
> [DEVELOPER_HANDOFF.md](DEVELOPER_HANDOFF.md) for the build order.

## Tech stack

| Layer      | Technology |
|------------|------------|
| Frontend   | React, TypeScript, Vite, React Router, TanStack Query, TailwindCSS |
| Backend    | FastAPI (Python), Pydantic, REST |
| Database   | PostgreSQL |
| ORM        | SQLAlchemy 2.0 + Alembic migrations |
| Auth       | JWT (access + refresh), Argon2 password hashing, role-based permissions |
| Deployment | Docker + Docker Compose, env-var config |

The stack is fixed by the project specification (`BASE.txt`). Do not change it
without an approved entry in [CHANGES.md](CHANGES.md).

## Repository layout

```
helios-core/
├── backend/            FastAPI app, models, schemas, services, Alembic
├── frontend/           React + TypeScript (Vite) app
├── docs/               architecture, database schema, business rules
├── nas_mount/          local stand-in for the NAS share (dev)
├── storage/            app-managed upload storage
├── backups/            database backup output
├── docker-compose.yml  db + backend + frontend
├── .env.example        root environment template
├── README.md
├── PROJECT_OVERVIEW.md
├── CHANGES.md
└── DEVELOPER_HANDOFF.md
```

See [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) for a deeper tour.

## Quick start (Docker)

Prerequisites: Docker + Docker Compose.

```bash
# 1. Create your environment file and set a real SECRET_KEY + passwords.
cp .env.example .env
#   Generate a SECRET_KEY:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"

# 2. Start the stack (db + backend + frontend).
docker compose up -d --build

# 3. Apply database migrations. The initial schema migration is committed as the
#    baseline, so first run is just `upgrade head` (no autogenerate needed).
docker compose exec backend alembic upgrade head

# 4. Seed roles + the first admin account (from FIRST_ADMIN_* in .env).
docker compose exec backend python -m app.seed
```

Then open:

- Frontend: <http://localhost:5173>
- API docs (Swagger): <http://localhost:8000/docs>
- Health check: <http://localhost:8000/api/v1/health>

Log in with the `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` you set in `.env`,
then change the password and create real user accounts from the Admin area
(coming with the user-management UI).

## Quick start (without Docker)

Backend:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # set SECRET_KEY and POSTGRES_* (host = localhost)
alembic upgrade head            # initial migration is committed; just apply it
python -m app.seed
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
cp .env.example .env            # set VITE_API_BASE_URL if needed
npm install
npm run dev
```

## Tests

```bash
cd backend && pytest            # smoke tests (no DB required)
cd frontend && npm run typecheck
```

## Backups

PostgreSQL data lives in the `postgres_data` Docker volume. Uploaded/NAS files
live on the NAS or `storage/` — these are durable data and are **never** deleted
by the application.

Database backup (logical dump):

```bash
docker compose exec db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
  > backups/helios_$(date +%Y%m%d_%H%M%S).sql
```

Restore:

```bash
cat backups/<file>.sql | docker compose exec -T db psql -U "$POSTGRES_USER" "$POSTGRES_DB"
```

## What's implemented

- ✅ Repository structure, Docker Compose, env-based config
- ✅ FastAPI backend skeleton with structured logging + CORS
- ✅ PostgreSQL connection, SQLAlchemy 2.0, Alembic (initial schema migration committed as the baseline)
- ✅ Core models: Users, Roles, Customers, Jobs, Activities, Tasks, Documents
- ✅ JWT authentication (login / refresh / me), Argon2 hashing, RBAC dependencies
- ✅ Admin user-management API (create / list / update / reset password / deactivate)
- ✅ Append-only activity logging service + case-number generator
- ✅ React/TS frontend skeleton: login, protected routes, role-aware dashboard shell
- ✅ **Customers**: searchable/paginated list, create modal, detail shell, edit, soft delete; role-gated API + activity logging; DB-backed tests

See [CHANGES.md](CHANGES.md) for decisions/deviations and
[DEVELOPER_HANDOFF.md](DEVELOPER_HANDOFF.md) for what's next.

## Documentation

- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) — architecture, structure, workflows
- [docs/architecture.md](docs/architecture.md) — system design
- [docs/database_schema.md](docs/database_schema.md) — entities & relationships
- [docs/business_rules.md](docs/business_rules.md) — rules the system enforces
- [CHANGES.md](CHANGES.md) — deviations from the baseline spec
- [DEVELOPER_HANDOFF.md](DEVELOPER_HANDOFF.md) — onboarding & next steps
