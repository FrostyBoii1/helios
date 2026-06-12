"""Health/readiness endpoints (unauthenticated)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import settings
from app.db.session import get_db

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check — process is up."""
    return {"status": "ok", "version": __version__, "environment": settings.ENVIRONMENT}


@router.get("/health/db")
def health_db(db: Session = Depends(get_db)) -> dict[str, str]:
    """Readiness check — database is reachable."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}
