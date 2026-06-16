# Business Rules

Rules the system enforces (or will enforce). These derive from `BASE.txt`. Code,
migrations, schemas, and tests are **evidence of existing behaviour** — but when
sources disagree, follow the **order of authority** in `DEVELOPER_HANDOFF.md` §7
(owner decisions › BASE/business rules › implementation › docs › chat) and
**reconcile the conflict** rather than silently choosing one. This document
explains intent; protect important explicit decisions with tests, not docs alone.

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

## Labels & approval (workflow signals)

- **Labels are operational workflow signals, not decorative tags.** They drive
  filtering and "what needs doing" — they are visible on the job and (Section D)
  filterable in the Jobs list.
- **Approval state is "law" — system workflow state, not a casual tag.** A job has
  at most **one** approval label: **Needs approval** / **Pending approval** /
  **Approved**. It is set only through the dedicated approval control (and
  auto-assigned at import commit); the system approval/decommission labels are
  **not** manually add/removable. Operational labels (Admin work required, Battery
  only, Existing solar, Awaiting documents, Needs maintenance) **are** user-managed.
- **Approval evidence has precedence** (so a later, stronger source — e.g. future
  NAS approval-document detection — can upgrade state without re-plumbing):
  explicit "approved"/reference number or "pending" wins; an approval-action phrase
  ("DO APPROVAL", "NEEDS APPROVAL") or a numeric-panel + inverter job with no
  approval evidence derives **Needs approval**; otherwise none.
- **Future direction:** some operational labels should become real assignable
  **tasks** (owner + due date), not passive flags.

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
- **Parsed customer name is clean; nothing is lost.** Operational/source suffixes
  in the name cell — booked/prescreened dates, vm / on fb / pole / agreed, SV
  submitted, export/system notes, invoice-sent notes, free-form admin notes, a
  trailing bare delimiter — are stripped from the name and preserved **verbatim**
  in On Commit / Job Internal Notes (never discarded, never inferred as a DOB).
  Real business/trust names, hotel entities, and hyphenated surnames are **not**
  rewritten unless a confident delimiter+keyword pattern applies; an entity's
  contact appositive ("The Leeton Heritage Motor Inn- Wayne Bond") is kept, and an
  ambiguous entity name ("C &J Horton PTY as Trustees …") is left for **manual
  resolution**, not auto-rewritten.
- **Approval references** ("Jemena Approval number 000410056") are preserved into
  Job Internal Notes; a bare approval **status** marker is not (its state lives on
  the approval label — see *Labels & approval*).
- **NMI "Same" carries forward only when the site is clearly identical.** An NMI
  written as `Same` / `as above` / `ditto` may copy the previous **real** NMI
  forward **only** when the immediately previous job/ambiguous row has a plausible
  real NMI **and** the two addresses normalize to the **same base property** —
  allowing only clear leading dwelling prefixes like `House` / `Unit` / `Flat`.
  Otherwise it stays "Same" and keeps its `nmi_unmatched` review warning. **Prefer
  false negatives over false positives** — never cross-link two properties' meters.
- **Preserved import context appears once.** It lives in On Commit / Job Internal
  Notes — there are no duplicate "Imported review/source" panels, and the customer
  file does not show an imported-source panel. Raw workbook cells stay inspectable
  in the import review only.
- Parser/note rules apply to **future** parses; existing staged/committed rows need
  a re-ingest to reflect a parser change.
- **v1 scope:** one Customer per Job (no dedup/merge — *multi-client matching is
  proposed, not built*), salesperson/installer kept as text, single-line address.
  No NAS matching, reference catalogs, StaffDirectory, status-label tables, or
  CustomerContact.

## Environments

- Development, testing, and production are separated. Development is never run
  against production data.
- **Dev reset tools** (Clear imports / Clear live CRM) are **admin-only**, **refused
  in production**, and require an **exact typed confirmation phrase**; there is
  deliberately no "clear everything". They exist to reset trial data during the
  supervised migration — not for routine use. "Clear live CRM" detaches (does not
  delete) committed import rows so they can be re-committed.

## Deferred by design (do not pre-build)

- Real-time push (use polling/refresh first).
- Document field extraction / OCR.
- Profitability analytics (basic reporting first).
