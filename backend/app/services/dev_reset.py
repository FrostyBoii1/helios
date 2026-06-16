"""Dev / test-only reset utilities.

Two SCOPED, HARD-delete actions so the owner can run a clean parser/import/commit
testing loop — there is deliberately NO "clear everything" action. The endpoints
gate these to a non-production environment + the system-admin (ADMIN) role and
require an explicit typed confirmation phrase.

NEVER touches users, roles, permissions, config, label DEFINITIONS, or migrations.

  * clear_imports     — import_issues -> import_rows -> import_batches only.
  * clear_live_crm    — job_label_assignments, activities, tasks, documents, jobs,
                        customers; FIRST detaches committed import rows (nulls the
                        committed_* links + reverts review_status committed ->
                        approved so they stay re-committable), preserving ALL import
                        batch/row/issue content.

Pure DB work; the caller (endpoint) owns the transaction/commit.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.customer import Customer
from app.models.document import Document
from app.models.enums import ImportRowReviewStatus
from app.models.import_staging import ImportBatch, ImportIssue, ImportRow
from app.models.job import Job
from app.models.job_label import JobLabelAssignment
from app.models.task import Task


def _count(db: Session, model: Any) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def reset_counts(db: Session) -> dict[str, Any]:
    """Read-only preview of exactly what each reset would affect. No writes."""
    detached = db.scalar(
        select(func.count())
        .select_from(ImportRow)
        .where(
            or_(
                ImportRow.committed_job_id.isnot(None),
                ImportRow.committed_customer_id.isnot(None),
            )
        )
    ) or 0
    return {
        "imports": {
            "import_issues": _count(db, ImportIssue),
            "import_rows": _count(db, ImportRow),
            "import_batches": _count(db, ImportBatch),
        },
        "live_crm": {
            "job_label_assignments": _count(db, JobLabelAssignment),
            "activities": _count(db, Activity),
            "tasks": _count(db, Task),
            "documents": _count(db, Document),
            "jobs": _count(db, Job),
            "customers": _count(db, Customer),
            # Committed import rows that will be DETACHED (links nulled + reverted to
            # approved) — NOT deleted; their parsed/raw/review content is preserved.
            "import_rows_detached": detached,
        },
    }


def clear_imports(db: Session) -> dict[str, int]:
    """HARD-delete import staging data ONLY (child -> parent FK order). Touches no
    live CRM, users, roles, or label definitions. Caller commits."""
    return {
        "import_issues": db.execute(delete(ImportIssue)).rowcount,
        "import_rows": db.execute(delete(ImportRow)).rowcount,
        "import_batches": db.execute(delete(ImportBatch)).rowcount,
    }


def clear_live_crm(db: Session) -> dict[str, int]:
    """HARD-delete live CRM business data ONLY.

    Step 1 — DETACH: committed import rows reference live jobs/customers via NO-ACTION
    FKs, so first null committed_customer_id/committed_job_id and revert review_status
    committed -> approved. This preserves ALL import batch/row/issue content and makes
    those rows re-committable; it never deletes import data.
    Step 2 — DELETE (child -> parent FK order): job_label_assignments, activities,
    tasks, documents, jobs, customers.

    Touches no import batches/rows/issues content, users, roles, or label definitions.
    Caller commits.
    """
    detached = db.execute(
        update(ImportRow)
        .where(
            or_(
                ImportRow.committed_job_id.isnot(None),
                ImportRow.committed_customer_id.isnot(None),
            )
        )
        .values(
            committed_customer_id=None,
            committed_job_id=None,
            review_status=ImportRowReviewStatus.APPROVED.value,
        )
    ).rowcount
    return {
        "import_rows_detached": detached,
        "job_label_assignments": db.execute(delete(JobLabelAssignment)).rowcount,
        "activities": db.execute(delete(Activity)).rowcount,
        "tasks": db.execute(delete(Task)).rowcount,
        "documents": db.execute(delete(Document)).rowcount,
        "jobs": db.execute(delete(Job)).rowcount,
        "customers": db.execute(delete(Customer)).rowcount,
    }
