"""Task endpoints.

Permissions (per approved matrix):
  * List / search / view : any authenticated user
  * Create               : any authenticated user (created_by = actor)
  * Update / reassign     : admin or the task's creator
  * Complete             : the assignee or admin
  * Reopen               : admin or the task's creator
  * Soft delete          : admin only
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.enums import ActivityType, RoleName, TaskPriority, TaskStatus
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskComplete, TaskCreate, TaskList, TaskRead, TaskUpdate
from app.services import tasks as tasks_service
from app.services.activity import log_activity

router = APIRouter()


def _is_admin(user: User) -> bool:
    return user.role.name == RoleName.ADMIN.value


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=detail)


def _get_or_404(db: Session, task_id: int) -> Task:
    task = tasks_service.get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.get("", response_model=TaskList)
def list_tasks(
    q: str | None = Query(default=None, description="Search task title"),
    status: TaskStatus | None = Query(default=None),
    priority: TaskPriority | None = Query(default=None),
    assigned_to_id: int | None = Query(default=None),
    customer_id: int | None = Query(default=None),
    job_id: int | None = Query(default=None),
    overdue: bool = Query(default=False),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TaskList:
    items, total = tasks_service.list_tasks(
        db,
        q=q,
        status=status,
        priority=priority,
        assigned_to_id=assigned_to_id,
        customer_id=customer_id,
        job_id=job_id,
        overdue=overdue,
        limit=limit,
        offset=offset,
    )
    return TaskList(
        items=[TaskRead.model_validate(t) for t in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=TaskRead, status_code=http_status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> TaskRead:
    try:
        task = tasks_service.create_task(
            db, data=payload.model_dump(exclude_unset=True), created_by_id=actor.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))

    db.flush()
    log_activity(
        db,
        activity_type=ActivityType.TASK_CREATED,
        description=f"Created task “{task.title}”",
        actor_id=actor.id,
        customer_id=task.customer_id,
        job_id=task.job_id,
        meta={"task_id": task.id},
    )
    if task.assigned_to_id is not None:
        log_activity(
            db,
            activity_type=ActivityType.TASK_ASSIGNED,
            description=f"Assigned task “{task.title}”",
            actor_id=actor.id,
            customer_id=task.customer_id,
            job_id=task.job_id,
            meta={"task_id": task.id, "to": task.assigned_to_id},
        )
    db.commit()
    db.refresh(task)
    return TaskRead.model_validate(task)


@router.get("/{task_id}", response_model=TaskRead)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TaskRead:
    return TaskRead.model_validate(_get_or_404(db, task_id))


@router.patch("/{task_id}", response_model=TaskRead)
def update_task(
    task_id: int,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> TaskRead:
    task = _get_or_404(db, task_id)
    if not (_is_admin(actor) or task.created_by_id == actor.id):
        raise _forbidden("Only an admin or the task creator can edit this task")

    data = payload.model_dump(exclude_unset=True)
    if not data:
        return TaskRead.model_validate(task)

    old_assignee = task.assigned_to_id
    try:
        changed = tasks_service.update_task(db, task, data)
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if "assigned_to_id" in changed:
        log_activity(
            db,
            activity_type=ActivityType.TASK_ASSIGNED,
            description=f"Reassigned task “{task.title}”",
            actor_id=actor.id,
            customer_id=task.customer_id,
            job_id=task.job_id,
            meta={"task_id": task.id, "from": old_assignee, "to": task.assigned_to_id},
        )
    other = [c for c in changed if c != "assigned_to_id"]
    if other:
        log_activity(
            db,
            activity_type=ActivityType.TASK_UPDATED,
            description=f"Updated task “{task.title}”",
            actor_id=actor.id,
            customer_id=task.customer_id,
            job_id=task.job_id,
            meta={"task_id": task.id, "changes": other},
        )
    db.commit()
    db.refresh(task)
    return TaskRead.model_validate(task)


@router.post("/{task_id}/complete", response_model=TaskRead)
def complete_task(
    task_id: int,
    payload: TaskComplete,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> TaskRead:
    task = _get_or_404(db, task_id)
    if not (_is_admin(actor) or task.assigned_to_id == actor.id):
        raise _forbidden("Only the assignee or an admin can complete this task")

    tasks_service.complete_task(db, task, actor_id=actor.id)
    meta: dict = {"task_id": task.id}
    if payload.notes:
        meta["notes"] = payload.notes
    log_activity(
        db,
        activity_type=ActivityType.TASK_COMPLETED,
        description=f"Completed task “{task.title}”",
        actor_id=actor.id,
        customer_id=task.customer_id,
        job_id=task.job_id,
        meta=meta,
    )
    db.commit()
    db.refresh(task)
    return TaskRead.model_validate(task)


@router.post("/{task_id}/reopen", response_model=TaskRead)
def reopen_task(
    task_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> TaskRead:
    task = _get_or_404(db, task_id)
    if not (_is_admin(actor) or task.created_by_id == actor.id):
        raise _forbidden("Only an admin or the task creator can reopen this task")

    tasks_service.reopen_task(db, task)
    log_activity(
        db,
        activity_type=ActivityType.TASK_UPDATED,
        description=f"Reopened task “{task.title}”",
        actor_id=actor.id,
        customer_id=task.customer_id,
        job_id=task.job_id,
        meta={"task_id": task.id, "action": "reopen"},
    )
    db.commit()
    db.refresh(task)
    return TaskRead.model_validate(task)


@router.delete("/{task_id}", status_code=http_status.HTTP_204_NO_CONTENT, response_model=None)
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
) -> None:
    task = _get_or_404(db, task_id)
    tasks_service.soft_delete_task(db, task)
    log_activity(
        db,
        activity_type=ActivityType.TASK_DELETED,
        description=f"Deleted task “{task.title}”",
        actor_id=actor.id,
        customer_id=task.customer_id,
        job_id=task.job_id,
        meta={"task_id": task.id},
    )
    db.commit()
