# Architecture

This document describes the intended system design for Helios Core. It should
remain understandable as the project evolves; record deviations in `CHANGES.md`.

## Goals

- Replace spreadsheets with a structured, multi-user, role-aware operations
  system that is the single source of truth.
- LAN-first deployment (e.g. on a NAS), with future secure remote access via VPN.
- Data integrity, auditability, and maintainability over flashy visuals.

## System components

```
┌──────────────┐     REST / JWT      ┌──────────────┐     SQL      ┌────────────┐
│  React SPA   │  ───────────────►   │   FastAPI    │  ─────────►  │ PostgreSQL │
│ (Vite/TS)    │  ◄───────────────   │   backend    │  ◄─────────  │            │
└──────────────┘                     └──────┬───────┘              └────────────┘
                                            │ filesystem (paths, not blobs)
                                            ▼
                                   ┌──────────────────┐
                                   │  NAS / storage   │
                                   │  documents/photos│
                                   └──────────────────┘
```

### Frontend (React + TypeScript + Vite)
- SPA served by Vite in development; built to static assets for production.
- **React Router** for routing and route guards.
- **TanStack Query** for server-state caching and periodic refresh (keeps staff
  off stale data without WebSockets for now).
- **TailwindCSS** for styling.
- A small `fetch` wrapper (`lib/api.ts`) attaches JWTs and performs a single
  transparent token refresh on 401.

### Backend (FastAPI + Python)
- REST API under `/api/v1`, OpenAPI docs at `/docs`.
- **Pydantic** models validate all request/response bodies.
- **SQLAlchemy 2.0** ORM with typed `Mapped[...]` columns.
- Layered design:
  - `api/` — routing, dependencies, permission guards (thin).
  - `services/` — domain logic, reusable and unit-testable.
  - `models/` — persistence.
  - `schemas/` — API contracts.
  - `core/` — config, security, logging (cross-cutting).
- **structlog** emits readable logs in dev and JSON in production.

### Database (PostgreSQL)
- System of record. Schema evolves only through **Alembic** migrations so all
  environments share one history.
- Constraint naming conventions (`db/base_class.py`) keep migrations stable.

### File storage (NAS / storage)
- Files are never stored as blobs in the database. The `documents` table stores
  metadata + a path **relative** to a configured root (`NAS_ROOT` or
  `STORAGE_ROOT`). The backend validates paths and enforces permissions before
  serving, and surfaces a broken-link state if a file is missing.

## Authentication & authorization

- **JWT** access tokens (short-lived) + refresh tokens (longer), signed HS256
  with `SECRET_KEY`. Refresh tokens carry a `type` claim so they cannot be used
  as access tokens.
- **Argon2id** password hashing; plaintext is never stored.
- **Role-based access control**: each user has one role (`admin`, `scheduling`,
  `approvals`, `support`, `sales_admin`). Backend guards (`require_admin`,
  `require_roles(...)`) protect routes; the frontend mirrors this with
  `ProtectedRoute`. The backend is always the authority — frontend checks are UX
  only.

## Auditability

- The append-only `activities` table records who did what, to which entity, and
  when, plus structured `meta` (e.g. before/after). Feature endpoints call
  `log_activity(...)` within the same transaction as the change.

## Concurrency & integrity

- Foreign keys and constraints enforce relational integrity.
- Important multi-step changes run inside a single transaction.
- Optimistic locking / simple versioning may be added to high-contention records
  as those features land (noted per-feature; not global yet).

## Environments

- `ENVIRONMENT` ∈ {development, testing, production} drives logging and
  behavior. Development is never run against production data.

## Deployment topology (target)

```
            ┌────────────── reverse proxy (TLS) ──────────────┐
 LAN/VPN ─► │  /            -> static frontend assets          │
            │  /api/v1/...  -> FastAPI (uvicorn)               │
            └──────────────────────┬──────────────────────────┘
                                   ▼
                       PostgreSQL  +  NAS mount
```

The current `docker-compose.yml` runs db + backend + frontend dev server for
development. The production proxy/static-serving setup is tracked in
`DEVELOPER_HANDOFF.md` and `CHANGES.md` (item 5).

## Explicitly deferred (do not build yet)

- WebSockets / real-time push (start with polling).
- Full-text search (start with PostgreSQL `ILIKE` + structured filters).
- Document detail extraction (OCR / field parsing).
These are future scope per the spec; the core data model and workflow come first.
