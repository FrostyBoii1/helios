"""Job label endpoints (Phase L1, read-only).

Permissions: list/view = any authenticated user (mirrors the tasks read routes).
Write endpoints (assign/remove, manage definitions) are deferred to L2/L3.

Routes are declared with full paths (router mounted without a prefix) so both the
catalogue and the per-job collection live in one module:
  * GET /job-labels             — the label catalogue (definitions)
  * GET /jobs/{job_id}/labels   — a job's assigned labels
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.job import Job
from app.models.user import User
from app.schemas.job_label import JobLabelAssignmentRead, JobLabelDefinitionRead
from app.services import job_labels as job_labels_service

router = APIRouter()


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
    job = db.get(Job, job_id)
    if job is None or job.deleted_at is not None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job_labels_service.list_job_labels(db, job_id)
