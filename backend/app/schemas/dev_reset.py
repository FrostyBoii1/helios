"""Schemas for the dev/test-only reset tools."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ResetCountsRead(BaseModel):
    """Preview of what each reset action would affect (read-only)."""

    imports: dict[str, int]
    live_crm: dict[str, int]


class ResetConfirm(BaseModel):
    """Body for a reset action — the exact typed confirmation phrase."""

    confirm: str = Field(..., min_length=1, max_length=64)


class ResetResult(BaseModel):
    """Result of a reset action: which action ran + per-table affected counts."""

    action: str
    deleted: dict[str, int]
