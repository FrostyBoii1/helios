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
- **Customer merge is explicit, admin-only, and non-destructive (B4 — storage in
  B4-1, execution built in B4-2).** Duplicates are never
  auto-merged or silently combined. A merge moves the **loser's** records to the
  **winner** and soft-deletes the loser (`merged_into_customer_id` → winner; never
  hard-deleted). The **winner's** contact/address fields stay **authoritative**
  (never overwritten from the loser); the loser's notes/internal_notes are
  **appended to the winner's internal notes with a provenance header**. `merged_into`
  is **immutable**; there is **no unmerge**; merges are **single-pair** (one loser →
  one winner). B4-2 executes the merge via admin-only
  `POST /customers/{loser_id}/merge-into/{winner_id}`: in one transaction it repoints
  jobs/tasks/documents/activities and the import customer links loser→winner, appends the
  loser notes, soft-deletes the loser, and logs a `CUSTOMER_MERGED` activity on the winner —
  no migration. A merged job is then **non-reversible** (the reverse engine's `job_modified`
  / `job_customer_mismatch` guards protect the winner); use **Prepare recommit** to correct.
  **Source/original-name provenance is visible on job lists:** when a job belongs to its current
  customer under a DIFFERENT name, that original/source name shows ("Originally <name>") in the
  customer's job panels — a read-only field (`JobRead.source_customer_name`). It is derived (MERGE
  first) from `CUSTOMER_MERGED` activity metadata (earliest merge wins for chains), else from the
  IMPORT row the job was committed/attached from (`ImportRow.parsed['customer_name']`, e.g. a job
  attached to an existing customer under a differently-named legacy row); null for normal/same-name
  jobs. It does NOT change the job's real customer (the current customer stays the source of truth).
- **The Customer page is the source of truth for ALL known customer-level details.** Every
  customer-level identity/contact detail on record for a customer — the primary record PLUS any
  additional known sets — is shown on the Customer page. When the same real customer is known by a
  different name/email/phone/address (a merged-away duplicate, an import row, manual entry, or a
  document), those additional details are preserved as structured `customer_contact_variants` with
  explicit provenance — NOT parsed out of or buried in the customer's free-text notes, and NOT in
  job-specific notes/sites (those stay on Jobs). The **primary** customer fields stay authoritative
  and are never overwritten by a variant; variants are additive, NOT "lesser alternates". The
  Customer-Detail **"Known customer details"** card displays them beside the primary Details
  (hidden for non-admins when none). **(Stage 3)** a B4 **merge** CAPTURES the loser's
  meaningfully-different customer-level fields as a `merged_customer` variant on the winner — only
  when something differs (no redundant variants), winner primary fields unchanged, the loser's id
  stored as provenance but never exposed by the read API. **(Stage 4)** admins can manually ADD a
  variant and ARCHIVE **manual** variants (soft-delete); source-derived variants are immutable and
  not archivable, the primary fields are never touched, and a manual add needs at least one detail
  field. **(Corrective pass)** when an import row is COMMITTED into an existing customer (B2 attach)
  or as a grouped DEPENDENT, its DIFFERING customer-level CONTACT identity (name + any email/phone
  the customer doesn't already hold) is captured as an `import_row` variant on that customer — only
  when something differs, never mutating the primary fields; reversing the row archives the variant
  it contributed. A row's ADDRESS is the JOB's site (`Job.details.site`, job-scoped) and is NOT
  captured as a customer variant — so a multi-site customer does not accrue job-site "contact"
  variants. **(Editable + provenance)** Known Customer Details are EDITABLE customer-level records:
  an admin can edit any one (manual OR source-derived) via the Customer page. **Editing a Known
  Customer Detail changes only that record — it never changes the primary Customer (the source of
  truth), the job, the import row, merge history, or the detail's own provenance** (`source_type`
  and the source links are immutable; an edit is stamped `edited_at`/`edited_by_id`). Each detail
  shows **source provenance** so a user can tell which import row/job contributed it (e.g. "Source
  row #23 · Job SCS-2023-00002"); the raw internal source ids are never exposed — only safe
  computed fields (workbook row number, job case number/id, whether the source row was reversed).
  **An edited source-derived detail survives reversal of its source import row** (an UNEDITED
  import detail is still archived when its row is reversed; an EDITED one is kept as curated
  customer information and its provenance then shows the source as reversed). Document/NAS capture,
  backfill of already-merged/imported customers, and **promoting a variant to the primary Customer
  (promote-to-primary) remain deferred** — editing a detail never promotes it.
- **Every job has a unique case number** in the form `SCS-YYYY-00001`, generated
  automatically at creation, searchable across the system. The sequence resets
  per calendar year.
- **Jobs move through clear statuses** (`JobStatus`): new → awaiting approval →
  ready to schedule → booked for install → installed → post-install call /
  review / maintenance / support → completed (or cancelled). Statuses are
  visible and filterable.
- **Changing the install date** updates the job (and, in the UI, its calendar
  placement) and is recorded on the timeline.
- **Parsed Job hardware is a stored, editable SNAPSHOT — never a live catalogue reference**
  (Hardware Parser lane; Stage 0 records the law, runtime is later stages). Each job's parsed
  hardware (inverters/batteries/metering/panel) is stored on the job (`Job.details.hardware`) as
  editable text-style items — `model_text, quantity, confidence, parser_owned, source_fragment`,
  optional `canonical_hardware_id_at_parse_time` for debugging only. The displayed hardware uses
  the snapshot's own `model_text`, **never** the canonical id. The admin **Settings > Hardware**
  catalogue (canonical hardware + aliases) may evolve — renames, alias add/remove, soft-delete,
  restore — but **none of that changes a Job that already has parsed hardware**: catalogue/alias
  edits affect only FUTURE parser matching, and deleted hardware is soft-deleted/restorable with
  aliases intact. The parser preserves unknown/ambiguous hardware as raw text (never guesses the
  closest model), seeds blank fields and refreshes only parser-owned values, and **never
  overwrites manual staff edits without explicit confirmation**. The hardware parser extracts
  hardware only and **does not create workflow labels or tasks**. The curated rules
  (`docs/parser_specs/hardware/`) are the version-controlled contract. **(Stage 1)** the canonical
  catalogue now exists as DB-backed **reference data** (`hardware_catalogue` + `hardware_aliases`,
  seeded from the spec) — it has no link to/from Jobs and is NOT cleared by the dev reset tools, so
  it can evolve independently while Job snapshots stay stable. Ignore rules, specific corrections,
  guard phrases, and normalization remain versioned config (not DB-editable yet); `source_examples`
  are evidence only and are never stored as matchable aliases. **(Stage 2A)** the catalogue and its
  aliases are managed through an **admin-only** API (`/api/v1/hardware`) — editing catalogue entries
  and viewing/editing aliases require admin; normal users cannot see aliases. Hardware is
  **soft-deleted, never hard-deleted**, and is restorable (with its aliases intact) from a DELETED
  view; the stable `spec_id` is immutable. None of these admin actions (rename, alias add/remove,
  soft-delete, restore) touch Jobs — the catalogue is still not wired into Jobs/imports/parser.
  **(Stage 3A)** the snapshot now physically EXISTS and is editable: `Job.details.hardware`
  (`inverters` / `batteries` / `metering` lists, a `panel` object, `site_notes`, `warnings`) is
  written through the path-restricted Job-details PATCH, validated by a strict shape schema
  (`schemas/job_hardware.py`, `extra='forbid'` — unknown fields/wrong types are rejected, 422).
  Each provided sub-section replaces that whole sub-section; absent ones are preserved. **Hard
  snapshot rule (enforced + tested):** (1) Jobs store snapshots, not live references; (2) catalogue
  edits, (3) alias edits and (4) hardware soft-delete/restore must NEVER mutate an existing Job
  snapshot; (5) Job hardware stays staff-editable; (6) `canonical_hardware_id_at_parse_time` is
  provenance/debug only, never display truth; (7) display depends on the stored snapshot text, not
  current catalogue state; (8) parser/reparse refresh is NOT part of this stage. No catalogue read
  populates the snapshot yet, and no migration was needed (JSONB). Jobs without `details.hardware`
  (or with `details=null`) read/render safely and are unaffected. **(Stage 3B)** the snapshot is
  shown + edited on the Job Detail **Hardware** section (`components/JobHardwareSection.tsx`):
  staff add/edit/remove inverter/battery/metering rows, edit the panel and site notes, all saved
  through the existing Job-details PATCH (`{ details: { hardware } }`). The section reads ONLY the
  stored snapshot (no catalogue read, no dropdowns, no live update from Settings > Hardware), shows
  a "does not update from Settings > Hardware" note, and on a `details=null` job is read-only with
  "Hardware editing is available once structured job details exist" (it never silently initialises
  details). Provenance (`confidence`/`source_fragment`/`parser_owned`) is shown subtly, never as
  display truth. **(Stage 4A)** the parser RUNTIME now exists in isolation (`app/hardware/runtime.py`,
  read-only): given hardware text + source metadata it reads the DB catalogue/aliases + the versioned
  policy config and emits a `JobHardwarePatch`-valid snapshot — `source_examples` can never match,
  unknown hardware is preserved as raw text (never guessed), panels keep `model: null` unless a real
  catalogue model is confidently identified (ambiguous → `model_options`), and it mutates nothing. It
  is NOT wired into the import pipeline yet (Stage 4B). The snapshot's `site_notes` buckets
  (ct/export_limit/underground/comms/raw_misc) are now **lists**, faithful to the spec. Parser policy
  (normalization, ignore rules, specific corrections, guard phrases, confidence mapping, panel
  brand/wattage routing) stays in the **versioned config**, not admin-editable catalogue fields.
  **(Stage 4B)** the runtime is now wired into the completed-sheet import: hardware is parsed ONCE at
  **ingest** into `ImportRow.parsed.details.hardware`, so import preview/review and commit read the
  SAME stored snapshot (no preview/commit divergence — the parser is never re-run at commit). Commit
  persists it verbatim into `Job.details.hardware` after a `JobHardwarePatch` validation (a malformed
  snapshot fails that one row safely). Reverse is unchanged — a pristine imported hardware job
  reverses, but any post-commit hardware edit trips the existing pristine guard (reverse blocked, the
  edit preserved). Enrichment is read-only against the catalogue; `source_examples` still never match;
  legacy `details.system.panel/inverter` text coexists. No frontend review UI yet (Stage 4C).
  **(Quantity rule)** explicit hardware quantity is core truth and must be preserved. The parser reads
  a `N x` / `N × ` / `N*` prefix into the item's `quantity`; a bare `N MODEL` is treated as a quantity
  ONLY when the remainder resolves to a catalogue model (so unit/capacity/phase text is never
  mis-split). Capacity / evidence fragments (battery ENERGY like `40kw hrs` / `40kwh`, but NOT bare
  `10kw` inverter power) are preserved as a hardware note (`site_notes.raw_misc`) and must NEVER be
  appended to an inverter/battery `model_text` or dumped into the inverters bucket. The UI shows a
  quantity > 1 inline as "N × MODEL" and round-trips it on edit, so the quantity is never lost.
  **(UX rule)** parsed hardware is shown as **normal Job Detail System fields** (Panel type / Inverter
  / Battery / Metering — alongside Number of panels / Storey / Phase / Roof type, plus a read-only
  **CT / electrical** row), NOT a separate hardware card. The current parsed VALUE always shows
  **regardless of confidence** — low confidence does NOT hide inverter/battery/etc.; it only adds a
  supplemental flag. Panel type / Inverter / Battery / Metering are **editable as textboxes with
  catalogue autocomplete** (the same free-text + search/select as import review) in Job Detail edit
  mode; the edit folds into the existing Job-details PATCH (`{ details: { hardware } }`), updating the
  Job snapshot ONLY — never Settings > Hardware or the catalogue. A catalogue selection records
  provenance (`canonical_hardware_id_at_parse_time` + `manual_correction`); free-typed text is saved
  as a manual correction with no stale catalogue id. An item with a recorded
  quantity > 1 is shown inline as **"N × MODEL"** and round-trips on edit (the quantity is never lost
  in the UI). A small read-only
  **"Hardware notes"** area is **supplemental only** (low-confidence/`manual_review` flags, ambiguous
  `model_options`, warnings, `raw_misc`) and is never the only place a value appears. Once a structured
  `details.hardware` snapshot exists, the cleaned snapshot is the job-facing System value and the legacy
  raw `system.panel`/`system.inverter` workbook text is hidden on the Job page (still stored as
  provenance; still shown as raw source-cell data in import review's Raw cells). Import review shows the
  same parsed hardware values read-only (what will commit). When no structured snapshot exists, the
  legacy System display is unchanged. Deferred: editing item quantity and CT/export site-notes.
  **(Hardware search + import-review edit — backend foundation)** a lean staff search endpoint
  (`GET /api/v1/hardware/search`) lets ANY authenticated staff (not only admins) look up **active,
  non-deleted** canonical hardware for autocomplete; it returns display/disambiguation fields ONLY and
  **never exposes aliases or admin-only internals** (aliases remain admin-only). It is read-only and
  changes no snapshot — a selection only influences a future user edit, never an existing Job. Import
  review may now edit `parsed.details.hardware` before commit, validated and merged by the **same**
  `JobHardwarePatch` shape rule as a live Job edit (one shared merge — review and live cannot diverge);
  `original_parsed` and the raw workbook cells are preserved, and commit persists the edited snapshot
  verbatim (the parser is not re-run). The import-review screen exposes these as **editable hardware
  textboxes with catalogue autocomplete** (Panel type / Inverter / Battery / Metering): typing free
  text is always allowed and saved as-is; picking a catalogue result autofills the canonical text and
  records confidence `manual_correction`, `parser_owned=false`, and `canonical_hardware_id_at_parse_time`
  as provenance only — **never a live catalogue reference**. **The textbox text is the source of truth:
  free-typed hardware (no selection) is saved as a manual correction that drops any stale catalogue id /
  model / parser provenance — hidden catalogue provenance exists ONLY when the reviewer actually picks a
  result**, so a field can never show one model while silently carrying another's id. Low-confidence/unconfirmed items carry an
  unobtrusive "review" marker but stay editable (uncertainty is shown, not hidden). Quantity (`N ×
  MODEL`) round-trips. Locked (committed/reversed) rows are read-only.
- **The spreadsheet is the first-pass import source of truth; NAS parsing is future SUPPORTING
  evidence and fallback, never a mandatory dependency of every import.** The hardware parser resolves
  the workbook cell on its own — separator splitting, brand-prefix normalization, bucket routing,
  catalogue coverage, leading-quantity handling, and owner-confirmed shorthand/bundle interpretation —
  and where its confidence is high enough an import does **not** require NAS file parsing. NAS parsing
  is heavier and may not always map files to a customer/job, so it is reserved for later supporting
  evidence (e.g. confirming an ambiguous model) and as a fallback — not a per-import requirement.
  Genuinely ambiguous hardware (capacity-only text, uncertain models) stays raw / `manual_review` for a
  reviewer rather than being guessed or blocked on NAS.

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

## Job Detail editing (autosave model)

- **Ordinary editable Job Detail fields autosave — no global Save button, no Edit wall.** A change to
  a descriptive field persists when the user finishes interacting with it (blur for text, change for a
  date), as a single-field update. A background refresh never wipes an in-progress edit, and a failed
  save keeps the typed value (with a retry) — edits are never silently lost. *(Rollout: H5A converted
  the top-level descriptive fields, H5B the structured registry fields, H5C the hardware System fields,
  H5D the install date — the model is now complete for every ordinary Job Detail field.)*
- **Hardware System fields (panel / inverter / battery / metering) autosave the same way, with
  catalogue autocomplete.** Free text saves on blur and drops any stale catalogue id; picking a
  catalogue suggestion saves immediately and stamps provenance (the selected canonical id +
  `manual_correction`, `parser_owned = false`). Each edit persists only its own hardware sub-section.
  This is the same safe-provenance rule as import review — it records text + provenance into the Job
  snapshot, never a live catalogue reference, so a later catalogue change still never live-updates a Job.
- **Install date autosaves on change, but under its OWN permission.** It saves the moment the date is
  picked, as a single-field update — never batched with the descriptive details — and uses the same
  no-clobber / retain-on-failure indicator as every other field. The crucial difference is the
  **separate permission**: editing the install date requires the scheduling permission (admin or
  scheduling), distinct from the descriptive-edit permission, and the backend re-checks it
  independently. A user without that permission sees the install date read-only.
- **Workflow controls stay EXPLICIT and separate — they are never swept into field autosave.**
  Approval (label-is-law structured state) keeps its own deliberate **"Edit approval"** affordance and
  its own Set-approval action (after a successful set the editor collapses back to the read view — a UX
  convenience that changes none of the approval rules); lifecycle **status** (an immediate-save
  dropdown) and **delete** (confirmation) each keep their own deliberate control too. Backend-derived
  blobs (`system_details`/`install_details`) and the hardware **Notes** remain non-editable.

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
  `RECORD_IMPORT_REVERSED` activity. **A reversed row is re-committable only via an
  explicit "Prepare recommit" (Section D)** — it stamps the prior committed ids into a
  `RECORD_IMPORT_RECOMMIT_PREPARED` activity, clears the committed links, detaches any
  group, resets resolution, and returns the row to **pending**, so a later commit creates
  **brand-new** Customer/Job records (the old soft-deleted records are never restored).
  The **generic reopen stays blocked** for reversed rows — Prepare recommit is the only
  path out.
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
- **Same-customer resolution is explicit, manual, and recorded before commit
  (Section B2-1/B2-2/B2-3).** An **admin** reviewer may store an intent on an import row to
  either create a new customer or attach the job to an **existing live customer** —
  never an auto-merge, never a silent combine, and never another pending import row.
  The intent is editable only while the row is **pending** and locked once approved
  (reopen to change). The reviewer makes this choice **in the import row modal**
  (Section B2-3): the "Possible same customer" candidate suggestions are **advisory**
  — they remain read-only hints, and a customer is attached only by an explicit
  "Use this customer" / search selection or "Create new customer".
- **A resolved "existing" row attaches its job to that customer at commit
  (Section B2-2).** Commit creates a **new Job under the resolved existing
  customer** and does **not** create or mutate a customer; the provenance activity
  records `attached_to_existing_customer`. If the resolved customer is missing or
  soft-deleted at commit time the row **fails** (`resolved_customer_deleted` /
  `resolved_customer_missing`) — never a silent fallback to a new customer, and the
  resolution is preserved for a retry. Commit-preview shows the row as **attach**
  vs **create** (and excludes an invalid resolution). **Reverse of an attached row
  soft-deletes only the imported Job — never the pre-existing customer** — and is
  not blocked by that customer having other jobs or being modified. Legacy-reference
  de-duplication still applies; two rows may attach to the same customer if their
  legacy references differ.
- **Pending rows may be grouped into one future customer (Section B3-2/B3-3/B3-4).**
  An **admin** reviewer may mark **≥2 pending rows in the same batch** as one group
  (`customer_resolution_mode='group'`) with one **primary** row, **in the import row
  modal** (Section B3-4): a pending "Possible same customer" candidate gets a
  "Group as same customer" action, and a group banner exposes the members, the
  primary, and set-primary / remove / dissolve. Grouping is explicit and manual —
  never auto-grouped. A row is exactly one of: unresolved/new, resolved
  to an existing customer, or grouped. Group structure is editable only while **all**
  members are pending (locked once any is approved/committed/reversed); removing a
  member below 2 auto-dissolves the group, and removing the primary auto-promotes the
  lowest-index member. The **backend is authoritative**: the import-modal grouping
  controls follow the current row's pending status, but the server re-validates the
  **whole** group and rejects the change (HTTP 422) once any member is approved/
  committed/reversed — the UI never decides the lock.
- **A group commits to one customer + multiple jobs (Section B3-3).** At commit the
  **primary creates the customer** (recorded on the group); **dependents attach jobs
  to it** — never a new customer. Commit keeps each group contiguous + primary-first
  (so a dependent commits after its primary, even across a `COMMIT_CAP` split); if the
  primary isn't committed the dependents are **skipped** (`group_primary_not_committed`),
  and if the group's customer is missing/deleted they **fail** — never a silent split.
  Preview shows a group as **1 customer + N jobs** (`group_primary` / `group_dependent`).
  **Reverse:** soft-delete the Job always; the **shared customer is soft-deleted only
  when reversing its last active job** (and only if pristine) — a non-last grouped job
  reverse is job-only. B2 attach and 'new' single-job reverse are unchanged.
- **Preserved import context appears once.** It lives in On Commit / Job Internal
  Notes — there are no duplicate "Imported review/source" panels, and the customer
  file does not show an imported-source panel. Raw workbook cells stay inspectable
  in the import review only.
- Parser/note rules apply to **future** parses; existing staged/committed rows need
  a re-ingest to reflect a parser change.
- **v1 scope:** one Customer per Job (no **auto**-dedup/merge — *multi-client matching
  is proposed, not built*; an **explicit admin merge** is now built in B4-1/B4-2),
  salesperson/installer kept as text, single-line
  address.
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
