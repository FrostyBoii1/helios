"""Import reverse/undo engine (Phase C3a — per-row, soft-delete only).

Reverses the live Customer + Job that the commit phase (C1) created from one
ImportRow, but ONLY while those records are still pristine (created by the
import and never touched since). Reverse = soft-delete the Customer + Job, mark
the ImportRow `reversed`, and log one RECORD_IMPORT_REVERSED activity.

NOTHING here hard-deletes. It never touches records not created by the row's
import, and it re-checks the full reversibility predicate in the same
transaction as the soft-delete (TOCTOU-safe). If any condition fails it blocks
with a reason and changes nothing.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.customer import Customer
from app.models.document import Document
from app.models.enums import ActivityType, ImportRowReviewStatus
from app.models.import_staging import ImportRow
from app.models.job import Job
from app.models.task import Task
from app.services.activity import log_activity
from app.services.customers import soft_delete_customer
from app.services.jobs import soft_delete_job

INSTALLED = "installed"


def _status_value(status: object) -> str:
    return status.value if hasattr(status, "value") else str(status)


def _count(db: Session, model, **eq) -> int:
    stmt = select(func.count()).select_from(model)
    for col, val in eq.items():
        stmt = stmt.where(getattr(model, col) == val)
    return db.scalar(stmt) or 0


def reversibility(db: Session, row: ImportRow) -> dict:
    """Evaluate the conservative reverse predicate (D6). Pure read; no writes.

    Returns {row_id, reversible, reason, customer_id, job_id, case_number}.
    `reason` is None when reversible, else the first failing condition.
    """
    cust_id = row.committed_customer_id
    job_id = row.committed_job_id
    base = {
        "row_id": row.id,
        "customer_id": cust_id,
        "job_id": job_id,
        "case_number": None,
    }

    def blocked(reason: str, **extra) -> dict:
        return {**base, **extra, "reversible": False, "reason": reason}

    # Unified reverse rule by how the row's customer came to be:
    #   * 'existing' (B2 attach): the pre-existing customer is NEVER soft-deleted —
    #     only the imported Job is. The customer-pristine guards don't apply.
    #   * 'group' (B3): the group's SHARED customer is soft-deleted ONLY when this is
    #     its LAST active job AND it is pristine; a non-last grouped job reverse is
    #     job-only.
    #   * otherwise ('new'): the created single-job customer is soft-deleted with the
    #     full original predicate (unchanged).
    # In all cases the job-pristine guards protect the imported Job.
    attach = row.customer_resolution_mode == "existing"
    grouped = row.customer_resolution_mode == "group"
    deletes_customer = not attach  # 'new' always; 'group' only on its last job

    if row.review_status == ImportRowReviewStatus.REVERSED.value:
        return blocked("already_reversed")
    if cust_id is None or job_id is None:
        return blocked("not_committed")

    job = db.get(Job, job_id)
    customer = db.get(Customer, cust_id)
    if job is None or job.deleted_at is not None:
        return blocked("job_missing_or_deleted")
    base["case_number"] = job.case_number
    # A 'new' reverse ALWAYS soft-deletes the customer, so it must still exist
    # (unchanged). A grouped reverse defers this to the last-job decision below.
    if deletes_customer and not grouped and (customer is None or customer.deleted_at is not None):
        return blocked("customer_missing_or_deleted")

    # Job-pristineness guards (ALL modes — protect the imported job).
    if job.legacy_reference != row.legacy_reference:
        return blocked("legacy_reference_mismatch")
    if _status_value(job.status) != INSTALLED:
        return blocked("status_changed")
    if job.updated_at != job.created_at:
        return blocked("job_modified")
    # Customer-modified guard for a 'new' reverse (unchanged).
    if deletes_customer and not grouped and customer.updated_at != customer.created_at:
        return blocked("customer_modified")

    # Any task/document linked to the job means it has been used.
    if _count(db, Task, job_id=job_id) > 0:
        return blocked("job_has_tasks")
    if _count(db, Document, job_id=job_id) > 0:
        return blocked("job_has_documents")
    # Any activity other than the single import provenance entry => touched.
    non_import_activities = db.scalar(
        select(func.count())
        .select_from(Activity)
        .where(Activity.job_id == job_id, Activity.activity_type != ActivityType.RECORD_IMPORTED)
    ) or 0
    if non_import_activities > 0:
        return blocked("job_has_activity")

    # Customer-deletion decision.
    delete_customer = False
    if deletes_customer:
        active_jobs = db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.customer_id == cust_id, Job.deleted_at.is_(None))
        ) or 0
        if grouped:
            # The shared group customer dies ONLY when reversing its last active job,
            # and only if pristine. A non-last grouped job reverse is job-only.
            if active_jobs <= 1:
                if customer is None or customer.deleted_at is not None:
                    return blocked("customer_missing_or_deleted")
                if customer.updated_at != customer.created_at:
                    return blocked("customer_modified")
                delete_customer = True
        else:  # 'new' (unchanged): the customer must own exactly this one job.
            if active_jobs != 1:
                return blocked("customer_has_other_jobs")
            delete_customer = True

    return {**base, "reversible": True, "reason": None, "delete_customer": delete_customer}


def reverse_row(db: Session, row: ImportRow, *, actor_id: int) -> dict:
    """Reverse one committed row if (re-checked) reversible. Per-row, transactional.

    Returns {row_id, status: 'reversed'|'blocked', reason, customer_id, job_id,
    case_number}. On 'blocked' nothing is changed.
    """
    check = reversibility(db, row)  # re-check inside the reverse transaction
    if not check["reversible"]:
        return {
            "row_id": row.id,
            "status": "blocked",
            "reason": check["reason"],
            "customer_id": check["customer_id"],
            "job_id": check["job_id"],
            "case_number": check["case_number"],
        }

    attach = row.customer_resolution_mode == "existing"
    grouped = row.customer_resolution_mode == "group"
    # The reversibility check (re-run above) decides whether the customer is also
    # soft-deleted: 'new' always; 'group' only on its last active job; 'attach' never.
    delete_customer = bool(check.get("delete_customer"))
    job = db.get(Job, row.committed_job_id)
    customer = db.get(Customer, row.committed_customer_id)
    case_number = job.case_number

    # Soft-delete only — never hard-delete (D1). Links preserved as audit (D2).
    soft_delete_job(db, job)
    if delete_customer:
        soft_delete_customer(db, customer)
    row.review_status = ImportRowReviewStatus.REVERSED.value
    if attach:
        description = "Import reversed; the imported Job was soft-deleted (existing customer kept)."
    elif grouped:
        description = (
            "Import reversed; the last grouped Job and its shared customer were soft-deleted."
            if delete_customer
            else "Import reversed; the grouped Job was soft-deleted (shared customer kept)."
        )
    else:
        description = "Import reversed; the created Customer and Job were soft-deleted."
    meta: dict = {
        "batch_id": row.batch_id, "row_id": row.id, "case_number": case_number,
        "attached_to_existing_customer": attach,
    }
    if grouped:
        meta["customer_group_id"] = row.customer_group_id
        meta["customer_soft_deleted"] = delete_customer
    log_activity(
        db,
        activity_type=ActivityType.RECORD_IMPORT_REVERSED,
        description=description,
        actor_id=actor_id,
        customer_id=customer.id,
        job_id=job.id,
        meta=meta,
    )
    db.commit()
    return {
        "row_id": row.id,
        "status": "reversed",
        "reason": None,
        "customer_id": customer.id,
        "job_id": job.id,
        "case_number": case_number,
    }
