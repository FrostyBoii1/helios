"""Spreadsheet import endpoints (Phase A — parse-only, admin-only).

POST ingests an uploaded .xlsx into staging tables; GET endpoints inspect the
created batch. NOTHING here creates or modifies Customer/Job/Task/Activity/
Document records — this is staging only. The uploaded file is processed in
memory and never persisted to disk.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.enums import ImportRowClass, ImportRowReviewStatus
from app.models.import_staging import ImportBatch, ImportIssue, ImportRow
from app.models.user import User
from app.schemas.import_staging import (
    BulkApproveResult,
    ImportBatchList,
    ImportBatchRead,
    ImportBatchSummary,
    ImportCommitPreview,
    ImportIssueRead,
    ImportRowEdit,
    ImportRowList,
    ImportRowRead,
    IssueResolveRequest,
    ReviewActionRequest,
)
from app.services import import_commit_preview, import_ingest, import_review

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
    unresolved_only: bool = Query(default=False, description="Only rows with an unresolved error-severity issue"),
    q: str | None = Query(default=None, description="Search legacy reference or parsed customer name"),
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
    if unresolved_only:
        filters.append(
            ImportRow.id.in_(
                select(ImportIssue.row_id).where(
                    ImportIssue.batch_id == batch_id,
                    ImportIssue.severity == "error",
                    ImportIssue.resolved.is_(False),
                )
            )
        )
    if q:
        term = f"%{q.strip()}%"
        filters.append(
            or_(
                ImportRow.legacy_reference.ilike(term),
                ImportRow.parsed["customer_name"].astext.ilike(term),
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


# --------------------------------------------------------------------------- #
# Phase B review actions (admin-only, staging-only — no live writes)
# --------------------------------------------------------------------------- #
def _row_or_404(db: Session, batch_id: int, row_id: int) -> ImportRow:
    _get_batch(db, batch_id)
    row = import_review.get_row(db, batch_id, row_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import row not found")
    return row


@router.get("/{batch_id}/summary", response_model=ImportBatchSummary)
def import_summary(
    batch_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ImportBatchSummary:
    batch = _get_batch(db, batch_id)
    return ImportBatchSummary(**import_review.summary(db, batch))


@router.get("/{batch_id}/commit-preview", response_model=ImportCommitPreview)
def commit_preview(
    batch_id: int,
    sample_limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ImportCommitPreview:
    """Phase C0: read-only preview of what a future commit-to-live WOULD create.

    Creates/modifies NOTHING — no Customer/Job/Activity records, no changes to
    the batch or its rows, no reserved case numbers.
    """
    batch = _get_batch(db, batch_id)
    return ImportCommitPreview(**import_commit_preview.preview(db, batch, sample_limit=sample_limit))


@router.get("/{batch_id}/rows/{row_id}", response_model=ImportRowRead)
def get_import_row(
    batch_id: int,
    row_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ImportRowRead:
    return ImportRowRead.model_validate(_row_or_404(db, batch_id, row_id))


@router.patch("/{batch_id}/rows/{row_id}", response_model=ImportRowRead)
def edit_import_row(
    batch_id: int,
    row_id: int,
    payload: ImportRowEdit,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ImportRowRead:
    batch = _get_batch(db, batch_id)
    row = _row_or_404(db, batch_id, row_id)
    edits = payload.model_dump(exclude_unset=True)
    import_review.edit_row(db, batch, row, edits, actor_id=admin.id)
    db.commit()
    db.refresh(row)
    return ImportRowRead.model_validate(row)


def _action(
    batch_id: int,
    row_id: int,
    new_status: ImportRowReviewStatus,
    notes: str | None,
    db: Session,
    admin: User,
) -> ImportRowRead:
    batch = _get_batch(db, batch_id)
    row = _row_or_404(db, batch_id, row_id)
    try:
        import_review.set_review_status(db, batch, row, new_status, actor_id=admin.id, notes=notes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    db.commit()
    db.refresh(row)
    return ImportRowRead.model_validate(row)


@router.post("/{batch_id}/rows/{row_id}/approve", response_model=ImportRowRead)
def approve_row(
    batch_id: int, row_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> ImportRowRead:
    return _action(batch_id, row_id, ImportRowReviewStatus.APPROVED, None, db, admin)


@router.post("/{batch_id}/rows/{row_id}/reject", response_model=ImportRowRead)
def reject_row(
    batch_id: int,
    row_id: int,
    payload: ReviewActionRequest = ReviewActionRequest(),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ImportRowRead:
    return _action(batch_id, row_id, ImportRowReviewStatus.REJECTED, payload.notes, db, admin)


@router.post("/{batch_id}/rows/{row_id}/skip", response_model=ImportRowRead)
def skip_row(
    batch_id: int,
    row_id: int,
    payload: ReviewActionRequest = ReviewActionRequest(),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ImportRowRead:
    return _action(batch_id, row_id, ImportRowReviewStatus.SKIPPED, payload.notes, db, admin)


@router.post("/{batch_id}/rows/{row_id}/reopen", response_model=ImportRowRead)
def reopen_row(
    batch_id: int, row_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> ImportRowRead:
    return _action(batch_id, row_id, ImportRowReviewStatus.PENDING, None, db, admin)


@router.patch("/{batch_id}/issues/{issue_id}", response_model=ImportIssueRead)
def resolve_issue(
    batch_id: int,
    issue_id: int,
    payload: IssueResolveRequest = IssueResolveRequest(),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ImportIssueRead:
    _get_batch(db, batch_id)
    issue = import_review.get_issue(db, batch_id, issue_id)
    if issue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import issue not found")
    import_review.resolve_issue(db, issue, actor_id=admin.id, note=payload.resolution_note)
    db.commit()
    db.refresh(issue)
    return ImportIssueRead.model_validate(issue)


@router.post("/{batch_id}/bulk-approve-clean", response_model=BulkApproveResult)
def bulk_approve_clean(
    batch_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> BulkApproveResult:
    batch = _get_batch(db, batch_id)
    approved, examined = import_review.bulk_approve_clean(db, batch, actor_id=admin.id)
    db.commit()
    return BulkApproveResult(approved=approved, eligible_examined=examined)
