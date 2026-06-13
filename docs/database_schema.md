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
| timestamps + deleted_at | | |

### jobs
| column | type | notes |
|--------|------|-------|
| id | int PK | |
| case_number | varchar(32) unique, indexed | `SCS-YYYY-00001` |
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

## Indexing (initial)

Indexed for search/filtering: `users.email`, `customers.full_name/email/phone/
suburb/postcode`, `jobs.case_number/status/install_date/salesperson_id/
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
- **Enum values** (`JobStatus`, `TaskStatus`, `TaskPriority`, `ActivityType`)
  are stored as strings, so adding a value needs **no migration**. The current
  set lives in `backend/app/models/enums.py` (the authoritative source).
