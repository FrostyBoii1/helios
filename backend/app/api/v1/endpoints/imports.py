"""Spreadsheet import endpoints (Phase A — parse-only, admin-only).

POST ingests an uploaded .xlsx into staging tables; GET endpoints inspect the
created batch. NOTHING here creates or modifies Customer/Job/Task/Activity/
Document records — this is staging only. The uploaded file is processed in
memory and never persisted to disk.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.enums import ImportRowClass, ImportRowReviewStatus
from app.models.import_staging import ImportBatch, ImportIssue, ImportRow
from app.models.user import User
from app.schemas.import_staging import (
    ImportBatchList,
    ImportBatchRead,
    ImportRowList,
    ImportRowRead,
)
from app.services import import_ingest

router = APIRouter()

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB guard


def _get_batch(db: Session, batch_id: int) -> ImportBatch:
    batch = db.scalar(
        select(ImportBatch).where(
            ImportBatch.id == batch_id, ImportBatch.deleted_at.is_(None)
        )
    )
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found")
    return batch


@router.post("", response_model=ImportBatchRead, status_code=status.HTTP_201_CREATED)
def create_import(
    file: UploadFile = File(...),
    sheet: str = Query(default=import_ingest.DEFAULT_SHEET),
    allow_duplicate: bool = Query(default=False),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ImportBatchRead:
    """Parse an uploaded .xlsx into staging rows. Admin only. No live writes."""
    filename = file.filename or "upload.xlsx"
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Expected an .xlsx file"
        )
    data = file.file.read()  # in memory only — never written to disk
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large")

    digest = import_ingest.sha256_of(data)
    if not allow_duplicate:
        existing = import_ingest.find_duplicate_batch(db, digest)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A batch for this exact file already exists (id {existing.id}). "
                f"Pass allow_duplicate=true to ingest again.",
            )

    try:
        batch = import_ingest.ingest_bytes(
            db,
            file_bytes=data,
            source_filename=filename,  # filename only (UploadFile has no path)
            sheet_name=sheet,
            created_by_id=admin.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    db.commit()
    db.refresh(batch)
    return ImportBatchRead.model_validate(batch)


@router.get("", response_model=ImportBatchList)
def list_imports(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ImportBatchList:
    stmt = (
        select(ImportBatch)
        .where(ImportBatch.deleted_at.is_(None))
        .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc())
    )
    items = list(db.scalars(stmt).all())
    return ImportBatchList(
        items=[ImportBatchRead.model_validate(b) for b in items], total=len(items)
    )


@router.get("/{batch_id}", response_model=ImportBatchRead)
def get_import(
    batch_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ImportBatchRead:
    return ImportBatchRead.model_validate(_get_batch(db, batch_id))


@router.get("/{batch_id}/rows", response_model=ImportRowList)
def list_import_rows(
    batch_id: int,
    row_class: ImportRowClass | None = Query(default=None),
    review_status: ImportRowReviewStatus | None = Query(default=None),
    severity: str | None = Query(default=None, description="Only rows with an issue of this severity"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ImportRowList:
    _get_batch(db, batch_id)  # 404 if missing
    filters = [ImportRow.batch_id == batch_id]
    if row_class is not None:
        filters.append(ImportRow.row_class == row_class.value)
    if review_status is not None:
        filters.append(ImportRow.review_status == review_status.value)
    if severity is not None:
        filters.append(
            ImportRow.id.in_(
                select(ImportIssue.row_id).where(
                    ImportIssue.batch_id == batch_id, ImportIssue.severity == severity
                )
            )
        )

    total = db.scalar(select(func.count()).select_from(ImportRow).where(*filters)) or 0
    stmt = (
        select(ImportRow)
        .options(joinedload(ImportRow.issues))
        .where(*filters)
        .order_by(ImportRow.source_row_index)
        .limit(limit)
        .offset(offset)
    )
    rows = list(db.scalars(stmt).unique().all())
    return ImportRowList(
        items=[ImportRowRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
