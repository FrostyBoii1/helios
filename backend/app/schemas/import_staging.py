"""Read schemas for import staging (Phase A — inspect a parsed batch)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import ImportBatchStatus, ImportRowClass, ImportRowReviewStatus


class ImportBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_filename: str
    sheet_name: str
    file_sha256: str | None = None
    status: ImportBatchStatus
    total_rows: int
    job_rows: int
    divider_rows: int
    blank_rows: int
    ambiguous_rows: int
    issue_count: int
    notes: str | None = None
    created_by_id: int | None = None
    created_at: datetime


class ImportBatchList(BaseModel):
    items: list[ImportBatchRead]
    total: int


class ImportIssueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    severity: str
    field: str | None = None
    message: str
    resolved: bool


class ImportRowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_row_index: int
    row_class: ImportRowClass
    legacy_reference: str | None = None
    raw: dict[str, Any] | None = None
    parsed: dict[str, Any] | None = None
    context_text: str | None = None
    review_status: ImportRowReviewStatus
    committed_customer_id: int | None = None
    committed_job_id: int | None = None
    issues: list[ImportIssueRead] = []


class ImportRowList(BaseModel):
    items: list[ImportRowRead]
    total: int
    limit: int
    offset: int
