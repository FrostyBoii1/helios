# Business Rules

Rules the system enforces (or will enforce). These derive from `BASE.txt`. When
a rule is implemented, the code is the authority; this document explains intent.

## Identity & access

- **Every staff member has their own account.** No shared logins. Accounts are
  created by an Admin (self-signup is not part of the workflow).
- **Passwords are hashed with Argon2**, never stored in plaintext, and never
  returned by the API.
- **One role per user.** Roles: `admin`, `scheduling`, `approvals`, `support`,
  `sales_admin`. The role determines what a user sees and can do.
- **The backend is the authority on permissions.** Frontend role checks are for
  UX only; every protected action is re-checked server-side.
- **Admins cannot deactivate their own account** (prevents lockout).
- **Deactivated users cannot authenticate.** Deactivation is reversible (soft),
  not a hard delete.

## Customers & jobs

- **Customers and jobs are separate entities.** A customer may have many jobs
  over time. Never model one-customer-one-job.
- **Every job has a unique case number** in the form `SCS-YYYY-00001`, generated
  automatically at creation, searchable across the system. The sequence resets
  per calendar year.
- **Jobs move through clear statuses** (`JobStatus`): new → awaiting approval →
  ready to schedule → booked for install → installed → post-install call /
  review / maintenance / support → completed (or cancelled). Statuses are
  visible and filterable.
- **Changing the install date** updates the job (and, in the UI, its calendar
  placement) and is recorded on the timeline.

## Tasks & accountability

- **Every task has an owner** (assignee) so work is never invisible or assumed.
- **Tasks link to a customer and/or a job.**
- **Completion is logged**: who completed it and when. Completed tasks move to a
  historical log; overdue tasks are clearly surfaced.
- **Shared admin work clears for everyone** once one admin completes it (moves to
  the historical log) — prevents double handling. *(To be implemented with the
  tasks feature.)*

## Activity timeline & audit

- **The activity log is append-only.** Important actions create a new entry and
  never overwrite history.
- **Audited actions** record user, timestamp, action, and affected entity.
  Examples: job creation, status change, install reschedule, task assignment,
  task completion, file upload, file deletion, customer update, user-management
  actions.

## Files & NAS

- **Files are not stored in the database** — only metadata + a relative path.
- **Permissions gate file access.** Not every role may delete/modify NAS files;
  Admins have full access, other roles view/upload/attach per their function.
- **The app never performs risky NAS operations** that could damage the folder
  structure. Uploaded/NAS files are durable data, not disposable app data.
- **Broken links are surfaced, not hidden.** If a referenced file is missing on
  disk, the app shows a missing/broken state rather than failing silently.

## Data integrity

- **Business-critical records use soft delete** (`deleted_at`) and remain
  recoverable unless explicitly, administratively purged.
- **Important multi-step changes are transactional.**
- **Structured over loose text:** data that should be searchable/structured is
  modeled as columns/relations, not free text.

## Search (initial)

- Start with PostgreSQL `ILIKE` + structured filters (customer name, address,
  phone, email, case number, install date, salesperson, status, assigned staff).
  Full-text search is future scope.

## Spreadsheet import (legacy migration)

- The legacy workbook is migrated through staging, **never** by writing live
  records directly. Upload parses an `.xlsx` into staging tables only.
- **No live Customer/Job is created until a row is `approved` AND a commit is
  explicitly confirmed.** Eligibility (re-checked server-side at commit) requires
  an approved job/ambiguous row with no unresolved error, a non-empty customer
  name, a plausible case-number year, and no existing commit link.
- **Commit is capped at 25 rows per call** (conservative first release) and is
  **create-only** — it never updates or deletes an existing live record. It is
  idempotent: already-committed rows and rows whose `legacy_reference` already
  exists on a live job are skipped.
- **Case-year guard:** a row whose derived case-number year (sale_date →
  install_date → current year) is outside `2020 … current year + 1` is excluded
  (`invalid_case_year`). Such rows must have their dates corrected in review (or
  be excluded) before they can commit — this prevents nonsensical numbers like
  `SCS-202-00001`.
- **Reverse** is per-row and **soft-delete only**, allowed **only while the
  imported Customer/Job is pristine** (unedited since import, no tasks/documents/
  non-import activity, status unchanged, customer owns only that one job). It
  sets the row `reversed`, preserves the commit links as audit, and logs one
  `RECORD_IMPORT_REVERSED` activity. Reversed rows are terminal (no re-open /
  re-commit yet).
- **v1 scope:** one Customer per Job (no dedup/merge), salesperson/installer kept
  as text, single-line address. No NAS matching, reference catalogs,
  StaffDirectory, status-label tables, or CustomerContact.

## Environments

- Development, testing, and production are separated. Development is never run
  against production data.

## Deferred by design (do not pre-build)

- Real-time push (use polling/refresh first).
- Document field extraction / OCR.
- Profitability analytics (basic reporting first).
