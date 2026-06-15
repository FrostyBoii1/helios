"""Job label endpoints.

Permissions:
  * list / view (GET)         : any authenticated user (mirrors the tasks reads).
  * add / remove (POST/DELETE): admin, sales_admin, scheduling, support.
  * System labels (is_system — approval + decommission presets) are NOT
    add/removable through this API; they are assigned automatically by the import
    commit. Attempting to add/remove one returns 403. (Admin-only override for
    system labels can be added later.)

Routes are declared with full paths (router mounted without a prefix) so both the
catalogue and the per-job collection live in one module:
  * GET    /job-labels            — the label catalogue (definitions)
  * GET    /jobs/{job_id}/labels  — a job's assigned labels
  * POST   /jobs/{job_id}/labels  — add an operational/custom label (idempotent)
  * DELETE /jobs/{job_id}/labels/{key} — remove an operational/custom label
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models.enums import ActivityType, JobLabelSource, RoleName
from app.models.job import Job
from app.models.user import User
from app.schemas.job_label import (
    JobApprovalRead,
    JobApprovalRequest,
    JobLabelAssignmentRead,
    JobLabelAssignRequest,
    JobLabelDefinitionRead,
)
from app.services import job_labels as job_labels_service
from app.services.activity import log_activity

router = APIRouter()

# Who may manually add/remove (operational/custom) labels.
can_manage_labels = require_roles(
    RoleName.ADMIN, RoleName.SALES_ADMIN, RoleName.SCHEDULING, RoleName.SUPPORT
)
# Who may set a job's approval state (the structured approval control).
can_set_approval = require_roles(RoleName.ADMIN, RoleName.SALES_ADMIN, RoleName.APPROVALS)


def _get_live_job_or_404(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None or job.deleted_at is not None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.get("/job-labels", response_model=list[JobLabelDefinitionRead], tags=["job-labels"])
def list_job_label_definitions(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[JobLabelDefinitionRead]:
    """The label catalogue, in stable display order. Excludes soft-deleted labels."""
    return job_labels_service.list_label_definitions(db)


@router.get(
    "/jobs/{job_id}/labels",
    response_model=list[JobLabelAssignmentRead],
    tags=["job-labels"],
)
def list_job_labels(
    job_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[JobLabelAssignmentRead]:
    """A job's assigned labels (empty for an unlabeled job). 404 if the job is
    missing or soft-deleted."""
    _get_live_job_or_404(db, job_id)
    return job_labels_service.list_job_labels(db, job_id)


@router.post(
    "/jobs/{job_id}/labels",
    response_model=JobLabelAssignmentRead,
    tags=["job-labels"],
)
def add_job_label(
    job_id: int,
    payload: JobLabelAssignRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(can_manage_labels),
) -> JobLabelAssignmentRead:
    """Add an operational/custom label to a job (idempotent). 403 for a system
    label (approval/decommission are auto-assigned). 404 for an unknown label."""
    job = _get_live_job_or_404(db, job_id)
    label = job_labels_service.get_label_by_key(db, payload.key)
    if label is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Label not found")
    if label.is_system:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="This label is managed automatically and cannot be added manually",
        )
    # Only log the timeline event on a genuinely new assignment (idempotent add).
    already = any(
        a.label.key == payload.key for a in job_labels_service.list_job_labels(db, job_id)
    )
    assignment = job_labels_service.assign_label_by_key(
        db, job_id=job_id, key=payload.key, source=JobLabelSource.MANUAL, assigned_by_id=actor.id
    )
    if not already:
        log_activity(
            db,
            activity_type=ActivityType.JOB_LABEL_ADDED,
            description=f"Added label '{label.name}' to {job.case_number}",
            actor_id=actor.id,
            customer_id=job.customer_id,
            job_id=job.id,
            meta={"label_key": label.key},
        )
    db.commit()
    db.refresh(assignment)
    return JobLabelAssignmentRead.model_validate(assignment)


@router.delete(
    "/jobs/{job_id}/labels/{key}",
    status_code=http_status.HTTP_204_NO_CONTENT,
    response_model=None,
    tags=["job-labels"],
)
def remove_job_label(
    job_id: int,
    key: str,
    db: Session = Depends(get_db),
    actor: User = Depends(can_manage_labels),
) -> None:
    """Remove an operational/custom label from a job (assignment only — the
    definition is untouched). 403 for a system label, 404 if not assigned."""
    job = _get_live_job_or_404(db, job_id)
    label = job_labels_service.get_label_by_key(db, key)
    if label is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Label not found")
    if label.is_system:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="This label is managed automatically and cannot be removed manually",
        )
    removed = job_labels_service.remove_label_by_key(db, job_id=job_id, key=key)
    if not removed:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Label not assigned to this job"
        )
    log_activity(
        db,
        activity_type=ActivityType.JOB_LABEL_REMOVED,
        description=f"Removed label '{label.name}' from {job.case_number}",
        actor_id=actor.id,
        customer_id=job.customer_id,
        job_id=job.id,
        meta={"label_key": label.key},
    )
    db.commit()


@router.put("/jobs/{job_id}/approval", response_model=JobApprovalRead, tags=["job-labels"])
def update_job_approval(
    job_id: int,
    payload: JobApprovalRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(can_set_approval),
) -> JobApprovalRead:
    """Authoritative approval-state control: sync the (at most one) approval label
    and details.approval.pending_date. Idempotent; bypasses the casual system-lock
    because this IS the structured approval control."""
    job = _get_live_job_or_404(db, job_id)
    result = job_labels_service.set_job_approval(
        db, job=job, state=payload.state, pending_date=payload.pending_date, assigned_by_id=actor.id
    )
    for key in result["changes"]["added"]:
        log_activity(
            db, activity_type=ActivityType.JOB_LABEL_ADDED,
            description=f"Approval set to '{payload.state}' on {job.case_number}",
            actor_id=actor.id, customer_id=job.customer_id, job_id=job.id,
            meta={"label_key": key, "approval_state": payload.state},
        )
    for key in result["changes"]["removed"]:
        log_activity(
            db, activity_type=ActivityType.JOB_LABEL_REMOVED,
            description=f"Approval changed to '{payload.state}' on {job.case_number}",
            actor_id=actor.id, customer_id=job.customer_id, job_id=job.id,
            meta={"label_key": key, "approval_state": payload.state},
        )
    db.commit()
    return JobApprovalRead(state=result["state"], pending_date=result["pending_date"])
