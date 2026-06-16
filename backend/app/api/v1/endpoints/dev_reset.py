"""Dev / test-only reset endpoints.

DESTRUCTIVE, HARD-delete tools for a clean testing loop. Triple-gated:
  1. environment guard — refused when ENVIRONMENT == "production";
  2. system-admin (ADMIN role) required;
  3. an exact typed confirmation phrase per action.

Two scoped actions only (no "clear everything"):
  * POST /dev/reset/imports   — confirm "DELETE ALL IMPORTS"
  * POST /dev/reset/live-crm  — confirm "DELETE ALL LIVE CRM DATA"
  * GET  /dev/reset/counts    — preview affected row counts (read-only)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db
from app.models.user import User
from app.schemas.dev_reset import ResetConfirm, ResetCountsRead, ResetResult
from app.services import dev_reset

router = APIRouter()
log = get_logger("dev_reset")

CONFIRM_CLEAR_IMPORTS = "DELETE ALL IMPORTS"
CONFIRM_CLEAR_LIVE_CRM = "DELETE ALL LIVE CRM DATA"


def _guard_environment() -> None:
    """Refuse the destructive tools entirely in production."""
    if settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reset tools are disabled in production.",
        )


def _require_phrase(given: str, expected: str) -> None:
    if given != expected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'Confirmation phrase must be exactly "{expected}".',
        )


@router.get("/counts", response_model=ResetCountsRead, tags=["dev-reset"])
def reset_counts(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ResetCountsRead:
    """Read-only preview of what each reset would delete/detach."""
    _guard_environment()
    return ResetCountsRead(**dev_reset.reset_counts(db))


@router.post("/imports", response_model=ResetResult, tags=["dev-reset"])
def clear_imports(
    payload: ResetConfirm,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ResetResult:
    """HARD-delete ALL import batches/rows/issues. Live CRM is left untouched."""
    _guard_environment()
    _require_phrase(payload.confirm, CONFIRM_CLEAR_IMPORTS)
    deleted = dev_reset.clear_imports(db)
    db.commit()
    log.warning("dev_reset.clear_imports", actor_id=admin.id, deleted=deleted)
    return ResetResult(action="clear_imports", deleted=deleted)


@router.post("/live-crm", response_model=ResetResult, tags=["dev-reset"])
def clear_live_crm(
    payload: ResetConfirm,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ResetResult:
    """HARD-delete ALL live CRM data (customers/jobs/tasks/activities/label
    assignments/documents) and DETACH committed import rows (links nulled, reverted
    to Approved). Import batches/rows/issues content is preserved."""
    _guard_environment()
    _require_phrase(payload.confirm, CONFIRM_CLEAR_LIVE_CRM)
    deleted = dev_reset.clear_live_crm(db)
    db.commit()
    log.warning("dev_reset.clear_live_crm", actor_id=admin.id, deleted=deleted)
    return ResetResult(action="clear_live_crm", deleted=deleted)
