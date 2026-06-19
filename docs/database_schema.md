# Database Schema

The relational model is the foundation of the application (database-first). This
document describes the current core entities and their relationships. The
authoritative definitions are the SQLAlchemy models in `backend/app/models/`;
the physical schema is produced by Alembic migrations.

## Conventions

- **Surrogate keys:** integer `id` primary key on every table.
- **Timestamps:** `created_at` / `updated_at` (server clock) on business tables.
- **Soft delete:** `deleted_at` (NULL = active) on business-critical tables.
  Activities are an exception — history is permanent and never soft-deleted.
- **Enums** are stored as strings (readable + searchable). See
  `backend/app/models/enums.py`.

## Entities

### roles
| column | type | notes |
|--------|------|-------|
| id | int PK | |
| name | varchar(50) unique | one of `admin`, `scheduling`, `approvals`, `support`, `sales_admin` |
| description | varchar(255) | |
| created_at / updated_at | timestamptz | |

### users
| column | type | notes |
|--------|------|-------|
| id | int PK | |
| full_name | varchar(120) | |
| email | varchar(255) unique, indexed | login identifier |
| hashed_password | varchar(255) | Argon2 hash — never plaintext |
| is_active | bool | admin can deactivate |
| role_id | int FK → roles.id | each user has exactly one role |
| created_at / updated_at | timestamptz | |
| deleted_at | timestamptz null | soft delete |

### customers
| column | type | notes |
|--------|------|-------|
| id | int PK | |
| full_name | varchar(160) indexed | |
| email / phone | varchar, indexed | searchable |
| address_line1/2, suburb, state, postcode | varchar | suburb/postcode indexed |
| notes | text | |
| merged_into_customer_id | int FK → customers.id null, indexed | **B4-1 (storage only):** set when this customer is the **loser** of an explicit admin merge → the winner it was merged into. NULL = live / never merged; immutable once set; NO ACTION self-FK. No execution reads/writes it yet (deferred to B4-2). |
| merged_at | timestamptz null | **B4-1:** when the merge happened |
| timestamps + deleted_at | | |

### jobs
| column | type | notes |
|--------|------|-------|
| id | int PK | |
| case_number | varchar(32) unique, indexed | `SCS-YYYY-00001` |
| legacy_reference | varchar(64) indexed, nullable | legacy spreadsheet/invoice ref on imported jobs; set only by the import commit; null for natively-created jobs |
| customer_id | int FK → customers.id | required |
| status | varchar(40) indexed | `JobStatus` enum |
| title | varchar(200) | |
| system_details / install_details / approval_details / notes | text | |
| nas_folder_path | varchar(500) | relative to `NAS_ROOT` |
| sale_date | date | |
| install_date | date indexed | |
| salesperson_id | int FK → users.id | |
| assigned_user_id | int FK → users.id | |
| timestamps + deleted_at | | |

### tasks
| column | type | notes |
|--------|------|-------|
| id | int PK | |
| title | varchar(200) | |
| description | text | |
| status | varchar(20) indexed | `TaskStatus` enum |
| priority | varchar(20) indexed | `TaskPriority` enum |
| due_date | timestamptz indexed | |
| customer_id | int FK → customers.id null | linkable to customer |
| job_id | int FK → jobs.id null | linkable to job |
| assigned_to_id | int FK → users.id null | owner/accountability |
| created_by_id | int FK → users.id null | |
| completed_at | timestamptz null | completion log |
| completed_by_id | int FK → users.id null | |
| timestamps + deleted_at | | |

### activities  (append-only)
| column | type | notes |
|--------|------|-------|
| id | int PK | |
| activity_type | varchar(40) indexed | `ActivityType` enum |
| description | text | human-readable summary |
| meta | jsonb null | structured before/after / context |
| actor_id | int FK → users.id null | who acted (null = system) |
| customer_id | int FK → customers.id null | subject |
| job_id | int FK → jobs.id null | subject |
| created_at / updated_at | timestamptz | (no soft delete) |

### documents  (metadata only — bytes live on NAS/storage)
| column | type | notes |
|--------|------|-------|
| id | int PK | |
| original_filename | varchar(255) | |
| relative_path | varchar(700) | relative to a storage root |
| storage_root | varchar(20) | `nas` or `storage` |
| content_type | varchar(120) | |
| size_bytes | bigint | |
| category | varchar(60) indexed | e.g. contract, invoice, msb_photo |
| customer_id | int FK → customers.id null | |
| job_id | int FK → jobs.id null | |
| uploaded_by_id | int FK → users.id null | |
| timestamps + deleted_at | | |

### customer_contact_variants  (Stage 2 — alternate customer details, read-only)

Alternate customer-level identity/contact/address sets for a LIVE customer (when the
same real customer is known by a different name/email/phone/address). The primary
`customers` columns stay authoritative; variants are additive read-only context — never
job notes or per-job sites, and never a parse of free-text notes. Soft-deletable (archive).
**Populated by B4 merge capture (Stage 3)** — a merge writes a `merged_customer` variant from the
loser's differing fields; import / manual / document capture and promote-to-primary are later
stages. `source_customer_id` / `source_import_row_id` / `source_document_id` are stored for audit
but are NOT exposed by the read API.

| column | type | notes |
|--------|------|-------|
| id | int PK | |
| customer_id | int FK → customers.id, indexed | the live customer this set belongs to |
| label | varchar(120) null | optional human label |
| display_name | varchar(160) null | name variation |
| email / phone | varchar null | contact variation |
| address_line1/2, suburb, state, postcode | varchar null | address variation |
| source_type | varchar(20) indexed | `CustomerContactVariantSource`: merged_customer / import_row / manual / document |
| source_customer_id | int FK → customers.id null | the merged loser (merged_customer source) |
| source_import_row_id | int FK → import_rows.id null | |
| source_document_id | int FK → documents.id null | |
| note | text null | short provenance/context |
| created_by_id | int FK → users.id null | |
| timestamps + deleted_at | | soft-delete = archive |

### import staging (parse → review → commit pipeline)

Staging tables hold the legacy-workbook import. They are **separate** from the
live tables; rows become live Customer/Job records only via an explicit,
admin-confirmed commit. Raw cells + the parsed candidate are stored as JSONB.

**import_batches** — one per uploaded `.xlsx`. Columns: `id`, `source_filename`,
`sheet_name`, `file_sha256` (dup-detect), `status` (`ImportBatchStatus`:
parsing/parsed/reviewing/committing/committed/committed_partial/failed), counts
(`total/job/divider/blank/ambiguous_rows`, `issue_count`), `created_by_id`,
timestamps + `deleted_at`.

**import_rows** — one per spreadsheet row. Columns: `id`, `batch_id` FK,
`source_row_index`, `row_class` (`ImportRowClass`: blank/divider/job/ambiguous),
`legacy_reference`, `raw` JSONB, `parsed` JSONB, `original_parsed` JSONB
(pre-edit snapshot), `context_text`, `review_status` (`ImportRowReviewStatus`:
pending/approved/rejected/skipped/committed/reversed), `review_notes`,
`reviewer_id`, `reviewed_at`, **`committed_customer_id` / `committed_job_id`**
(set by commit; preserved as audit after reverse), timestamps. **B2-1 manual
same-customer resolution (storage only):** `resolved_customer_id` FK →
customers.id (indexed), `customer_resolution_mode` (null = unresolved → new
customer at commit / `new` = explicit new / `existing` = attach to
`resolved_customer_id`), `customer_resolution_reason`, `resolved_by_id` FK →
users.id, `resolved_at`. The mode/customer invariant is enforced in
the review service. **Section B2-2 wires these into commit/preview/reverse:** an
`existing` row attaches its job to `resolved_customer_id` (no new customer); a
missing/soft-deleted target fails the row; reverse of an attached row soft-deletes
only the Job, never the resolved customer. **B3-2 adds `customer_group_id` FK →
import_customer_groups.id (indexed)** — membership in a pending-row group
(`customer_resolution_mode='group'`); mutually exclusive with `resolved_customer_id`.

**import_customer_groups** (B3-2) — a reviewer-defined group of pending rows that
should become **one future customer**. Columns: `id`, `batch_id` FK, `primary_row_id`
FK → import_rows.id (the row that creates the customer in B3-3), `committed_customer_id`
FK → customers.id (**set by B3-3 when the primary commits — the group's shared
customer**), `created_by_id` FK → users.id, `reason`,
timestamps. **B3-3 reads it at commit/preview/reverse:** the primary creates the
customer (and sets `committed_customer_id`), dependents attach jobs to it, and reverse
soft-deletes the shared customer only on its last active job. The review service
enforces same-batch / job-ambiguous / pending-lock / primary∈members and the
≥2-member (auto-dissolve) + auto-promote-primary rules.

**import_issues** — first-class data-quality flags per row. Columns: `id`,
`row_id` FK, `batch_id` FK, `kind`, `severity` (`ImportIssueSeverity`:
info/warning/error), `field`, `message`, `resolved` + `resolution_note` /
`resolved_by_id` / `resolved_at`.

### job labels (operational workflow signals)

**job_label_definitions** — the seeded label catalogue (migration-seeded).
Columns: `id`, `key` (unique slug), `name`, `category` (`JobLabelCategory`:
approval/operational/system/custom), `color`, `description`, `is_system` (approval
+ decommission presets — not manually add/removable), `is_auto` (auto-assignable
at import commit), `sort_order`, timestamps + `deleted_at` (soft-deleted
definitions are excluded from the catalogue).

**job_label_assignments** — a label on a job. Columns: `id`, `job_id` FK,
`label_id` FK, `source` (`JobLabelSource`: import_auto/manual/system),
`assigned_by_id` FK → users.id null, `note`, `created_at`. A job has **at most one**
approval label (the structured approval control enforces this).

> **Columns added since the foundation table (no separate doc row yet):**
> `jobs.internal_notes` (manual staff notes, distinct from the read-only imported
> `notes` blob) and `jobs.details` (JSONB, registry-shaped structured import
> attributes); `customers.internal_notes`; `import_rows.internal_notes_override`
> (the reviewer's editable On-Commit notes). Several additive migrations have
> followed `legacy_reference` (the column additions above, the two `job_label_*`
> tables + approval-label renames, the B2-1 customer-resolution columns, the
> B3-2 `import_customer_groups` table, and the B4-1 `customers.merged_into_customer_id`
> / `merged_at` merge-pointer columns) — see **Migrations** for the ordered chain
> and current head.

## Relationships

```
roles 1 ───< users
customers 1 ───< jobs
jobs 1 ───< tasks
jobs 1 ───< activities
jobs 1 ───< documents
customers 1 ───< tasks / activities / documents   (optional links)
users 1 ───< jobs (salesperson, assigned_user)
users 1 ───< tasks (assigned_to, created_by, completed_by)
users 1 ───< activities (actor), documents (uploaded_by)
```

- A customer may have **many** jobs over time (installs, maintenance, upgrades,
  support). The model never assumes one job per customer.
- Tasks, activities, and documents can attach to a customer and/or a job.
- **B4-1 (storage only):** `customers.merged_into_customer_id` is a **self-reference**
  (merge loser → winner). It is inert until B4-2 merge execution; the pure-read
  `resolve_active_customer()` helper walks the chain to the live winner.

## Indexing (initial)

Indexed for search/filtering: `users.email`, `customers.full_name/email/phone/
suburb/postcode` (+ `merged_into_customer_id`, B4-1), `jobs.case_number/status/install_date/salesperson_id/
assigned_user_id`, `tasks.status/priority/due_date/assigned_to_id`,
`activities.activity_type/actor_id/customer_id/job_id`, `documents.category/
customer_id/job_id`. Add composite/full-text indexes as query patterns emerge.

## Migrations

- The **initial baseline migration is committed**
  (`backend/alembic/versions/b9a0ae06a010_init_core_schema.py`). First run just
  applies it:
  ```
  alembic upgrade head
  ```
  Do **not** regenerate it. (See CHANGES.md, "Runtime verification fixes".)
- Adding/changing a model? Import it in `backend/app/db/base.py`, then generate a
  **new** migration: `alembic revision --autogenerate -m "..."`, review, and
  `alembic upgrade head`.
- **Enum values** (`JobStatus`, `TaskStatus`, `TaskPriority`, `ActivityType`,
  and the import enums `ImportBatchStatus`/`ImportRowClass`/
  `ImportRowReviewStatus`/`ImportIssueSeverity`) are stored as strings, so adding
  a value needs **no migration**. The current set lives in
  `backend/app/models/enums.py` (the authoritative source).
- **Import migrations (ordered):** `3a7c8dea1004` staging tables (Phase A) →
  `7e512cf78bf7` review-audit columns → `91a6e16b2a20` `jobs.legacy_reference`
  (Phase C0) → `b6c7d8e9f0a1` `import_rows.internal_notes_override` →
  **`c7d8e9f0a1b2` `import_rows` customer-resolution columns** (B2-1:
  `resolved_customer_id`, `customer_resolution_mode`, `customer_resolution_reason`,
  `resolved_by_id`, `resolved_at`) → **`d8e9f0a1b2c3` `import_customer_groups` table
  + `import_rows.customer_group_id`** (B3-2) → **`e9f0a1b2c3d4` `customers.merged_into_customer_id`
  + `customers.merged_at`** (B4-1: customer-merge storage foundation — additive nullable
  columns + index + self-FK, no backfill, reversible; no execution) → **`f0a1b2c3d4e5`**
  (cleanup: reconcile the `job_label_definitions.key` model↔DB drift — collapse the redundant
  unique-constraint + non-unique-index into the single UNIQUE index the model declares; no data
  change, reversible) → **`a1b2c3d4e5f6`** (Stage 2: the new `customer_contact_variants` table
  — additive, creates the table + its FKs/indexes only, no backfill, reversible). The current
  Alembic **head is `a1b2c3d4e5f6`**. The commit-to-live,
  reverse, and case-year-guard work (and the later B2-2/B2-3, B3-3/B3-4 wiring) added **no**
  further migrations — they read the existing columns at commit/preview/reverse and in the UI
  (string-enum values only). **B4-2/B4-3/B4-4 (customer-merge execution, UI, merged-loser URL
  polish) likewise add NO migration** — they reuse the B4-1 `customers.merged_into_customer_id` /
  `merged_at` columns and the `CUSTOMER_MERGED` string-enum value; the later migrations are the
  `f0a1b2c3d4e5` job-label-key drift reconcile and the `a1b2c3d4e5f6` `customer_contact_variants`
  table above.
