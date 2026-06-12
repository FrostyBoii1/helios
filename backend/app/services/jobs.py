"""Job domain logic: lookup, search/list/filter, create, update, status, soft delete.

All reads exclude soft-deleted rows. Delete is soft (sets `deleted_at`);
`session.delete()` is never used on jobs. Case numbers are generated with a small
retry loop guarded by the unique constraint on `jobs.case_number`.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models.customer import Customer
from app.models.enums import JobStatus
from app.models.job import Job
from app.services.case_number import next_case_number

MAX_CASE_NUMBER_RETRIES = 5


def get_job(db: Session, job_id: int) -> Job | None:
    stmt = (
        select(Job)
        .options(joinedload(Job.customer))
        .where(Job.id == job_id, Job.deleted_at.is_(None))
    )
    return db.scalar(stmt)


# Jobs in these statuses are no longer candidates for scheduling.
_UNSCHEDULABLE_STATUSES = (JobStatus.COMPLETED.value, JobStatus.CANCELLED.value)


def list_jobs(
    db: Session,
    *,
    q: str | None = None,
    customer_id: int | None = None,
    status: JobStatus | None = None,
    install_date_from: date | None = None,
    install_date_to: date | None = None,
    unscheduled: bool = False,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[Job], int]:
    """Return (page of active jobs, total matching count).

    `q` is a case-insensitive ILIKE across case_number and title.
    `install_date_from`/`install_date_to` bound the install date (inclusive) for
    the scheduling calendar. `unscheduled` selects jobs with no install date that
    still need scheduling (status not completed/cancelled).
    """
    filters = [Job.deleted_at.is_(None)]
    if customer_id is not None:
        filters.append(Job.customer_id == customer_id)
    if status is not None:
        filters.append(Job.status == status.value)
    if unscheduled:
        filters.append(Job.install_date.is_(None))
        filters.append(Job.status.not_in(_UNSCHEDULABLE_STATUSES))
    if install_date_from is not None:
        filters.append(Job.install_date >= install_date_from)
    if install_date_to is not None:
        filters.append(Job.install_date <= install_date_to)
    if q:
        like = f"%{q.strip()}%"
        filters.append(or_(Job.case_number.ilike(like), Job.title.ilike(like)))

    total = db.scalar(select(func.count()).select_from(Job).where(*filters)) or 0

    stmt = (
        select(Job)
        .options(joinedload(Job.customer))
        .where(*filters)
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = list(db.scalars(stmt).all())
    return items, total


def customer_is_active(db: Session, customer_id: int) -> bool:
    return (
        db.scalar(
            select(Customer.id).where(
                Customer.id == customer_id, Customer.deleted_at.is_(None)
            )
        )
        is not None
    )


def create_job(db: Session, *, customer_id: int, data: dict) -> Job:
    """Create a job for an active customer with a unique generated case number.

    Retries case-number allocation on a unique-constraint collision (the final
    guard against the rare concurrent-insert race). Adds + flushes; the caller
    owns the commit. Raises ValueError if the customer is missing/soft-deleted,
    RuntimeError if a unique case number could not be allocated.
    """
    if not customer_is_active(db, customer_id):
        raise ValueError("Customer not found")

    year = datetime.now(timezone.utc).year
    last_error: IntegrityError | None = None
    for _ in range(MAX_CASE_NUMBER_RETRIES):
        case_number = next_case_number(db, year)
        job = Job(
            case_number=case_number,
            customer_id=customer_id,
            status=JobStatus.NEW,
            **data,
        )
        db.add(job)
        try:
            with db.begin_nested():
                db.flush()
            return job
        except IntegrityError as exc:  # case_number collided — retry
            last_error = exc
            db.expunge(job)
    raise RuntimeError("Could not allocate a unique case number") from last_error


def apply_job_update(db: Session, job: Job, data: dict) -> list[str]:
    """Apply a partial update in place. Returns the list of changed field names."""
    changed: list[str] = []
    for field, value in data.items():
        if getattr(job, field) != value:
            setattr(job, field, value)
            changed.append(field)
    return changed


def change_status(db: Session, job: Job, new_status: JobStatus) -> tuple[str, str]:
    """Set the job status. Returns (old, new) as string values."""
    old = job.status.value if isinstance(job.status, JobStatus) else str(job.status)
    job.status = new_status
    return old, new_status.value


def soft_delete_job(db: Session, job: Job) -> None:
    job.deleted_at = datetime.now(timezone.utc)


def is_reschedule(old: date | None, new: date | None) -> bool:
    """True when an install_date change is a reschedule (date -> different date)."""
    return old is not None and new is not None and old != new
