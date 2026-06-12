"""Task domain logic: lookup, search/list/filter, create, update, lifecycle.

All reads exclude soft-deleted rows. Delete is soft (sets `deleted_at`). Overdue
is computed dynamically (Task.is_overdue / a SQL predicate), never stored.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session, joinedload

from app.models.customer import Customer
from app.models.enums import TaskPriority, TaskStatus
from app.models.job import Job
from app.models.task import Task
from app.models.user import User

ACTIVE_STATUSES = (TaskStatus.OPEN.value, TaskStatus.IN_PROGRESS.value)

# Higher number = more severe; used for ordering.
_PRIORITY_RANK = case(
    {
        TaskPriority.URGENT.value: 4,
        TaskPriority.HIGH.value: 3,
        TaskPriority.NORMAL.value: 2,
        TaskPriority.LOW.value: 1,
    },
    value=Task.priority,
    else_=0,
)

_RELATIONS = (
    joinedload(Task.assigned_to),
    joinedload(Task.created_by),
    joinedload(Task.completed_by),
    joinedload(Task.customer),
    joinedload(Task.job),
)


def get_task(db: Session, task_id: int) -> Task | None:
    stmt = (
        select(Task)
        .options(*_RELATIONS)
        .where(Task.id == task_id, Task.deleted_at.is_(None))
    )
    return db.scalar(stmt)


def list_tasks(
    db: Session,
    *,
    q: str | None = None,
    status: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    assigned_to_id: int | None = None,
    customer_id: int | None = None,
    job_id: int | None = None,
    overdue: bool = False,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[Task], int]:
    """Return (page of active tasks, total).

    Defaults to open + in_progress when no explicit status filter is given.
    Sorted by due_date asc (nulls last), then priority severity, then newest.
    """
    filters = [Task.deleted_at.is_(None)]
    if status is not None:
        filters.append(Task.status == status.value)
    else:
        filters.append(Task.status.in_(ACTIVE_STATUSES))
    if priority is not None:
        filters.append(Task.priority == priority.value)
    if assigned_to_id is not None:
        filters.append(Task.assigned_to_id == assigned_to_id)
    if customer_id is not None:
        filters.append(Task.customer_id == customer_id)
    if job_id is not None:
        filters.append(Task.job_id == job_id)
    if overdue:
        filters.append(
            and_(
                Task.due_date.is_not(None),
                Task.due_date < func.now(),
                Task.status.in_(ACTIVE_STATUSES),
            )
        )
    if q:
        filters.append(Task.title.ilike(f"%{q.strip()}%"))

    total = db.scalar(select(func.count()).select_from(Task).where(*filters)) or 0

    stmt = (
        select(Task)
        .options(*_RELATIONS)
        .where(*filters)
        .order_by(
            Task.due_date.asc().nullslast(),
            _PRIORITY_RANK.desc(),
            Task.created_at.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    items = list(db.scalars(stmt).unique().all())
    return items, total


def _active_id(db: Session, model, entity_id: int) -> bool:
    return (
        db.scalar(select(model.id).where(model.id == entity_id, model.deleted_at.is_(None)))
        is not None
    )


def create_task(db: Session, *, data: dict, created_by_id: int) -> Task:
    """Create a task, validating referenced customer/job/assignee.

    A job-linked task inherits the job's customer when none is given (so it
    surfaces on the customer timeline); a provided customer must match the job's.
    Raises ValueError on an invalid reference.
    """
    customer_id = data.get("customer_id")
    job_id = data.get("job_id")
    assigned_to_id = data.get("assigned_to_id")

    if job_id is not None:
        job = db.scalar(select(Job).where(Job.id == job_id, Job.deleted_at.is_(None)))
        if job is None:
            raise ValueError("Job not found")
        if customer_id is None:
            data["customer_id"] = job.customer_id
        elif customer_id != job.customer_id:
            raise ValueError("Customer does not match the job's customer")
    elif customer_id is not None and not _active_id(db, Customer, customer_id):
        raise ValueError("Customer not found")

    if assigned_to_id is not None and not _active_id(db, User, assigned_to_id):
        raise ValueError("Assigned user not found")

    task = Task(**data, created_by_id=created_by_id)
    db.add(task)
    return task


def update_task(db: Session, task: Task, data: dict) -> list[str]:
    """Apply a partial update in place. Returns the list of changed field names.

    Validates a newly-referenced job/customer/assignee if those fields change.
    """
    if "job_id" in data and data["job_id"] is not None:
        job = db.scalar(select(Job).where(Job.id == data["job_id"], Job.deleted_at.is_(None)))
        if job is None:
            raise ValueError("Job not found")
    if "customer_id" in data and data["customer_id"] is not None:
        if not _active_id(db, Customer, data["customer_id"]):
            raise ValueError("Customer not found")
    if "assigned_to_id" in data and data["assigned_to_id"] is not None:
        if not _active_id(db, User, data["assigned_to_id"]):
            raise ValueError("Assigned user not found")

    changed: list[str] = []
    for field, value in data.items():
        if getattr(task, field) != value:
            setattr(task, field, value)
            changed.append(field)
    return changed


def complete_task(db: Session, task: Task, *, actor_id: int) -> None:
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc)
    task.completed_by_id = actor_id


def reopen_task(db: Session, task: Task) -> None:
    task.status = TaskStatus.OPEN
    task.completed_at = None
    task.completed_by_id = None


def soft_delete_task(db: Session, task: Task) -> None:
    task.deleted_at = datetime.now(timezone.utc)
