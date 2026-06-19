"""Dev / test-only reset utilities.

Two SCOPED, HARD-delete actions so the owner can run a clean parser/import/commit
testing loop — there is deliberately NO "clear everything" action. The endpoints
gate these to a non-production environment + the system-admin (ADMIN) role and
require an explicit typed confirmation phrase.

NEVER touches users, roles, permissions, config, label DEFINITIONS, or migrations.

  * clear_imports     — import_issues, then break the import_rows<->import_customer_groups
                        FK cycle (null customer_group_id, delete import_customer_groups),
                        then import_rows -> import_batches.
  * clear_live_crm    — job_label_assignments, activities, tasks, documents, jobs,
                        customers; FIRST detaches every import->customer/job link
                        (committed_* on rows + revert to approved; B2
                        resolved_customer_id; B3-3 group committed_customer_id) so the
                        customers can be deleted, preserving ALL import
                        batch/row/issue/group content.

Pure DB work; the caller (endpoint) owns the transaction/commit.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.customer import Customer
from app.models.customer_contact_variant import CustomerContactVariant
from app.models.document import Document
from app.models.enums import ImportRowReviewStatus
from app.models.import_staging import (
    ImportBatch,
    ImportCustomerGroup,
    ImportIssue,
    ImportRow,
)
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
            "import_customer_groups": _count(db, ImportCustomerGroup),
            "import_rows": _count(db, ImportRow),
            "import_batches": _count(db, ImportBatch),
        },
        "live_crm": {
            "job_label_assignments": _count(db, JobLabelAssignment),
            "activities": _count(db, Activity),
            "tasks": _count(db, Task),
            "documents": _count(db, Document),
            "jobs": _count(db, Job),
            "customer_contact_variants": _count(db, CustomerContactVariant),
            "customers": _count(db, Customer),
            # Committed import rows that will be DETACHED (links nulled + reverted to
            # approved) — NOT deleted; their parsed/raw/review content is preserved.
            "import_rows_detached": detached,
        },
    }


def clear_imports(db: Session) -> dict[str, int]:
    """HARD-delete import staging data ONLY, in FK-safe order. Touches no live CRM,
    users, roles, or label definitions. Caller commits.

    import_rows and import_customer_groups reference each OTHER (B3-2): a row points
    at its group via ``customer_group_id``, and the group points back at its primary
    row via ``primary_row_id``. Break the cycle before deleting: clear the rows'
    group pointer, delete the groups, then delete the rows (and their issues/batches).
    """
    issues = db.execute(delete(ImportIssue)).rowcount
    # Null the rows -> group FK so the groups can be deleted, then delete groups
    # before rows (groups.primary_row_id references rows).
    db.execute(update(ImportRow).values(customer_group_id=None))
    groups = db.execute(delete(ImportCustomerGroup)).rowcount
    rows = db.execute(delete(ImportRow)).rowcount
    batches = db.execute(delete(ImportBatch)).rowcount
    return {
        "import_issues": issues,
        "import_customer_groups": groups,
        "import_rows": rows,
        "import_batches": batches,
    }


def clear_live_crm(db: Session) -> dict[str, int]:
    """HARD-delete live CRM business data ONLY.

    Step 1 — DETACH every import->customer/job link (all are NO-ACTION FKs) so the
    live rows can be deleted while ALL import batch/row/issue/group CONTENT is
    preserved and stays re-committable:
      * committed import rows: null committed_customer_id/committed_job_id and revert
        review_status committed -> approved (B1/C);
      * manual same-customer resolutions: null import_rows.resolved_customer_id and
        clear the 'existing' mode back to unresolved (B2);
      * pending-row groups: null import_customer_groups.committed_customer_id (B3-3);
      * customer merge pointers: null customers.merged_into_customer_id so the
        self-referential FK never blocks the customer delete (B4-1; normally a
        no-op until merge execution exists).
    Step 2 — DELETE (child -> parent FK order): job_label_assignments, activities,
    tasks, documents, jobs, customer_contact_variants, customers.

    ``customer_contact_variants`` is deleted BEFORE customers: it carries FKs to
    ``customers`` (customer_id + source_customer_id), so the customer hard-delete would
    otherwise fail. It references ``import_rows`` (source_import_row_id) too, but those are
    DETACHED/preserved here, not deleted — deleting the child variant simply drops that link.

    Touches no import batches/rows/issues/groups CONTENT, users, roles, or label
    definitions. Caller commits.
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
    # B2: detach manual "existing customer" resolutions (the target customer is about
    # to be deleted) — revert the row to unresolved so it stays valid + re-committable.
    resolution_detached = db.execute(
        update(ImportRow)
        .where(ImportRow.resolved_customer_id.isnot(None))
        .values(resolved_customer_id=None, customer_resolution_mode=None)
    ).rowcount
    # B3-3: detach committed pending-row groups from their (to-be-deleted) customer;
    # the group content is preserved and re-committable.
    groups_detached = db.execute(
        update(ImportCustomerGroup)
        .where(ImportCustomerGroup.committed_customer_id.isnot(None))
        .values(committed_customer_id=None)
    ).rowcount
    # B4-1: null any customer -> customer merge pointer (merged_into_customer_id)
    # BEFORE deleting customers, so the self-referential FK can never block or
    # orphan the hard delete. No merge execution exists yet (B4-2+), so this is
    # normally a no-op (all NULL); it is forward-compatible defense-in-depth for
    # once a merge can set it.
    merge_pointers_detached = db.execute(
        update(Customer)
        .where(Customer.merged_into_customer_id.isnot(None))
        .values(merged_into_customer_id=None)
    ).rowcount
    return {
        "import_rows_detached": detached,
        "import_rows_resolution_detached": resolution_detached,
        "import_groups_detached": groups_detached,
        "customers_merge_detached": merge_pointers_detached,
        "job_label_assignments": db.execute(delete(JobLabelAssignment)).rowcount,
        "activities": db.execute(delete(Activity)).rowcount,
        "tasks": db.execute(delete(Task)).rowcount,
        "documents": db.execute(delete(Document)).rowcount,
        "jobs": db.execute(delete(Job)).rowcount,
        # Before customers — variants FK customers (customer_id + source_customer_id).
        "customer_contact_variants": db.execute(delete(CustomerContactVariant)).rowcount,
        "customers": db.execute(delete(Customer)).rowcount,
    }
