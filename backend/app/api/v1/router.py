"""Aggregate v1 API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    activities,
    auth,
    customers,
    dev_reset,
    health,
    imports,
    job_labels,
    jobs,
    tasks,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(customers.router, prefix="/customers", tags=["customers"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(activities.router, prefix="/activities", tags=["activities"])
api_router.include_router(imports.router, prefix="/imports", tags=["imports"])
# Job labels declare full paths (/job-labels and /jobs/{id}/labels) — no prefix.
api_router.include_router(job_labels.router)
# Dev/test-only reset tools (env + system-admin + confirmation-phrase gated).
api_router.include_router(dev_reset.router, prefix="/dev/reset", tags=["dev-reset"])
