"""Job endpoints.

Permissions (per approved matrix):
  * List / search / view   : any authenticated user
  * Create                 : admin, sales_admin
  * Update descriptive     : admin, sales_admin
  * Update install_date    : admin, scheduling
  * Change status          : admin, sales_admin, scheduling, approvals
  * Soft delete            : admin only
  * support                : read-only

A PATCH that touches both descriptive fields and install_date must satisfy BOTH
permission requirements.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin, require_roles
from app.db.session import get_db
from app.models.enums import ActivityType, JobStatus, RoleName
from app.models.user import User
from app.schemas.job import (
    JobCreate,
    JobList,
    JobRead,
    JobStatusUpdate,
    JobUpdate,
)
from app.services import jobs as jobs_service
from app.services.activity import log_activity

router = APIRouter()

# Descriptive fields (everything editable except the scheduling field install_date).
DESCRIPTIVE_FIELDS = {
    "title",
    "system_details",
    "install_details",
    "approval_details",
    "notes",
    "internal_notes",
    "sale_date",
    "salesperson_id",
    "assigned_user_id",
}

DESCRIPTIVE_ROLES = {RoleName.ADMIN.value, RoleName.SALES_ADMIN.value}
INSTALL_ROLES = {RoleName.ADMIN.value, RoleName.SCHEDULING.value}

can_create = require_roles(RoleName.ADMIN, RoleName.SALES_ADMIN)
can_change_status = require_roles(
    RoleName.ADMIN, RoleName.SALES_ADMIN, RoleName.SCHEDULING, RoleName.APPROVALS
)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=detail)


@router.get("", response_model=JobList)
def list_jobs(
    q: str | None = Query(default=None, description="Search case number / title"),
    customer_id: int | None = Query(default=None),
    status: JobStatus | None = Query(default=None),
    install_date_from: date | None = Query(
        default=None, description="Install date on/after (scheduling calendar)"
    ),
    install_date_to: date | None = Query(
        default=None, description="Install date on/before (scheduling calendar)"
    ),
    unscheduled: bool = Query(
        default=False, description="Active jobs with no install date"
    ),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> JobList:
    items, total = jobs_service.list_jobs(
        db,
        q=q,
        customer_id=customer_id,
        status=status,
        install_date_from=install_date_from,
        install_date_to=install_date_to,
        unscheduled=unscheduled,
        limit=limit,
        offset=offset,
    )
    return JobList(
        items=[JobRead.model_validate(j) for j in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=JobRead, status_code=http_status.HTTP_201_CREATED)
def create_job(
    payload: JobCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(can_create),
) -> JobRead:
    body = payload.model_dump()
    customer_id = body.pop("customer_id")
    try:
        job = jobs_service.create_job(db, customer_id=customer_id, data=body)
    except ValueError:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Customer not found or inactive",
        )
    except RuntimeError:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not allocate a case number, please retry",
        )

    log_activity(
        db,
        activity_type=ActivityType.JOB_CREATED,
        description=f"Created job {job.case_number}",
        actor_id=actor.id,
        customer_id=customer_id,
        job_id=job.id,
        meta={"case_number": job.case_number},
    )
    db.commit()
    db.refresh(job)
    return JobRead.model_validate(job)


@router.get("/{job_id}", response_model=JobRead)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> JobRead:
    job = jobs_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobRead.model_validate(job)


@router.patch("/{job_id}", response_model=JobRead)
def update_job(
    job_id: int,
    payload: JobUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> JobRead:
    job = jobs_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Job not found")

    data = payload.model_dump(exclude_unset=True)
    # `details` is a path-restricted partial patch (Phase 4b), not a flat field —
    # pull it out so the generic update never clobbers it as a full replacement.
    details_provided = "details" in data
    details_patch = data.pop("details", None)
    # A structured details edit counts as a descriptive change for permissions.
    has_descriptive = details_provided or any(field in data for field in DESCRIPTIVE_FIELDS)
    has_install = "install_date" in data

    # Conditional permission checks based on what the payload changes.
    role = actor.role.name
    if has_descriptive and role not in DESCRIPTIVE_ROLES:
        raise _forbidden("You do not have permission to edit job details")
    if has_install and role not in INSTALL_ROLES:
        raise _forbidden("You do not have permission to change the install date")
    if not data and not details_provided:
        return JobRead.model_validate(job)

    old_install = job.install_date
    changed = jobs_service.apply_job_update(db, job, data)
    # Apply the structured details patch AFTER the generic update so re-rendered
    # system_details/install_details win over any direct edit in the same payload.
    if details_provided:
        try:
            changed += jobs_service.apply_job_details_patch(job, details_patch)
        except ValueError as exc:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            )
    changed = list(dict.fromkeys(changed))  # de-dup (details patch may re-touch a blob)

    reschedule = "install_date" in changed and jobs_service.is_reschedule(
        old_install, job.install_date
    )
    if reschedule:
        log_activity(
            db,
            activity_type=ActivityType.INSTALL_RESCHEDULED,
            description=f"Rescheduled install for {job.case_number}",
            actor_id=actor.id,
            customer_id=job.customer_id,
            job_id=job.id,
            meta={"from": str(old_install), "to": str(job.install_date)},
        )

    # Everything else (descriptive changes + an initial install set) is JOB_UPDATED.
    job_updated_fields = [c for c in changed if not (reschedule and c == "install_date")]
    if job_updated_fields:
        log_activity(
            db,
            activity_type=ActivityType.JOB_UPDATED,
            description=f"Updated job {job.case_number}",
            actor_id=actor.id,
            customer_id=job.customer_id,
            job_id=job.id,
            meta={"changes": job_updated_fields},
        )

    db.commit()
    db.refresh(job)
    return JobRead.model_validate(job)


@router.post("/{job_id}/status", response_model=JobRead)
def change_job_status(
    job_id: int,
    payload: JobStatusUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(can_change_status),
) -> JobRead:
    job = jobs_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Job not found")

    old, new = jobs_service.change_status(db, job, payload.status)
    if old != new:
        log_activity(
            db,
            activity_type=ActivityType.JOB_STATUS_CHANGED,
            description=f"Status of {job.case_number}: {old} -> {new}",
            actor_id=actor.id,
            customer_id=job.customer_id,
            job_id=job.id,
            meta={"from": old, "to": new},
        )
    db.commit()
    db.refresh(job)
    return JobRead.model_validate(job)


@router.delete("/{job_id}", status_code=http_status.HTTP_204_NO_CONTENT, response_model=None)
def delete_job(
    job_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
) -> None:
    job = jobs_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Job not found")
    jobs_service.soft_delete_job(db, job)
    log_activity(
        db,
        activity_type=ActivityType.JOB_DELETED,
        description=f"Deleted job {job.case_number}",
        actor_id=actor.id,
        customer_id=job.customer_id,
        job_id=job.id,
    )
    db.commit()
