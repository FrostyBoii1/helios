# CHANGES.md

This file records every meaningful deviation from the baseline specification
(`BASE.txt`). The baseline is the source of truth; anything that departs from it
must be justified here, per project governance.

Each entry records: **what** changed, **why**, **files affected**, whether it is
**temporary or permanent**, and any **risks / follow-up**.

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
