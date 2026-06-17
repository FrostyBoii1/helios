"""Spreadsheet import endpoints (admin-only).

Upload parses an .xlsx into staging tables (in memory, never persisted to disk);
GET endpoints inspect a batch; PATCH/POST review actions edit/approve staged
rows. All of the above are staging-only and create NO live records.

The one exception is POST /{id}/commit (Phase C1), which creates live Customer +
Job records from APPROVED rows via app.services.import_commit — create-only, it
never updates or deletes existing live records.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.enums import ImportRowClass, ImportRowReviewStatus
from app.models.import_staging import ImportBatch, ImportIssue, ImportRow
from app.models.user import User
from app.schemas.import_staging import (
    BulkApproveResult,
    CustomerGroupAddRowRequest,
    CustomerGroupCreateRequest,
    CustomerGroupMutationResult,
    CustomerGroupRead,
    CustomerGroupSetPrimaryRequest,
    CustomerResolutionRequest,
    FieldRegistryRead,
    ImportBatchList,
    ImportBatchRead,
    ImportBatchSummary,
    ImportCommitPreview,
    ImportCommitRequest,
    ImportCommitResult,
    ImportIssueRead,
    ImportRowEdit,
    ImportRowList,
    ImportRowRead,
    IssueResolveRequest,
    MatchCandidateRead,
    ReverseCheck,
    ReverseResult,
    ReviewActionRequest,
)
from app.services import (
    import_commit,
    import_commit_preview,
    import_field_registry,
    import_ingest,
    import_matching,
    import_review,
    import_reverse,
)

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


@router.get("/field-registry", response_model=FieldRegistryRead)
def get_field_registry(_: User = Depends(get_current_user)) -> FieldRegistryRead:
    """Read-only structured-field registry that drives the review + structured Job UI.

    Any authenticated user (Phase 4b): it is pure metadata (field labels/sections/
    input types/visibility) with no PII and no DB — sales_admin needs it for the
    structured Job detail UI. Edit permissions stay enforced on the jobs/import
    endpoints, not here. Declared before the dynamic /{batch_id} routes so it is
    matched as a static path.
    """
    return FieldRegistryRead(
        sections=[{"key": k, "label": label} for k, label in import_field_registry.SECTIONS],
        fields=import_field_registry.as_dicts(),
        editable_details_paths=sorted(import_field_registry.allowed_details_paths()),
    )


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


@router.post("/{batch_id}/commit", response_model=ImportCommitResult)
def commit_batch(
    batch_id: int,
    payload: ImportCommitRequest = ImportCommitRequest(),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ImportCommitResult:
    """Phase C1: commit eligible approved rows to live Customer + Job records.

    Admin only. Creates live records (capped per call); never updates/deletes
    existing live records. Idempotent: already-committed rows and rows whose
    legacy_reference already exists on a live job are skipped.
    """
    batch = _get_batch(db, batch_id)
    result = import_commit.commit_batch(db, batch, actor_id=admin.id, row_ids=payload.row_ids)
    return ImportCommitResult(**result)


@router.get("/{batch_id}/rows/{row_id}/reverse-check", response_model=ReverseCheck)
def reverse_check(
    batch_id: int,
    row_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ReverseCheck:
    """Phase C3: read-only check of whether a committed row can be reversed.

    Reverses NOTHING — evaluates the conservative reversibility predicate.
    """
    row = _row_or_404(db, batch_id, row_id)
    return ReverseCheck(**import_reverse.reversibility(db, row))


@router.post("/{batch_id}/rows/{row_id}/reverse", response_model=ReverseResult)
def reverse_row(
    batch_id: int,
    row_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ReverseResult:
    """Phase C3: per-row reverse — soft-delete the created Customer + Job if the
    row is still reversible. Admin only. Never hard-deletes; if blocked, nothing
    is changed and the reason is returned.
    """
    row = _row_or_404(db, batch_id, row_id)
    return ReverseResult(**import_reverse.reverse_row(db, row, actor_id=admin.id))


@router.get("/{batch_id}/rows/{row_id}", response_model=ImportRowRead)
def get_import_row(
    batch_id: int,
    row_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ImportRowRead:
    return ImportRowRead.model_validate(_row_or_404(db, batch_id, row_id))


@router.get(
    "/{batch_id}/rows/{row_id}/match-candidates",
    response_model=list[MatchCandidateRead],
)
def get_row_match_candidates(
    batch_id: int,
    row_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[MatchCandidateRead]:
    """ADVISORY, read-only (Section B1): possible same-customer candidates for this
    row — other rows in the batch and existing live customers — with reasons and a
    confidence band. Does NOT merge, link, resolve, or write anything."""
    row = _row_or_404(db, batch_id, row_id)
    return [MatchCandidateRead(**c) for c in import_matching.find_candidates(db, row)]


@router.post("/{batch_id}/rows/{row_id}/resolve-customer", response_model=ImportRowRead)
def resolve_row_customer(
    batch_id: int,
    row_id: int,
    payload: CustomerResolutionRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ImportRowRead:
    """Section B2-1 (storage only): set or clear this row's manual same-customer
    resolution intent.

    ``mode="existing"`` attaches the job to ``customer_id`` (must be an existing,
    non-deleted customer); ``mode="new"`` explicitly resolves to a new customer;
    ``mode="clear"`` clears it. Editable only while the row is pending (locked once
    approved/committed). Admin only. Does NOT affect commit-to-live, commit-preview,
    or reverse yet — that is Section B2-2.
    """
    batch = _get_batch(db, batch_id)
    row = _row_or_404(db, batch_id, row_id)
    try:
        if payload.mode == "existing":
            if payload.customer_id is None:
                raise ValueError("customer_id is required when mode is 'existing'.")
            import_review.set_resolution_existing(
                db, batch, row, customer_id=payload.customer_id,
                actor_id=admin.id, reason=payload.reason,
            )
        elif payload.mode == "new":
            import_review.set_resolution_new(db, batch, row, actor_id=admin.id, reason=payload.reason)
        else:  # "clear"
            import_review.clear_resolution(db, batch, row, actor_id=admin.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    db.commit()
    db.refresh(row)
    return ImportRowRead.model_validate(row)


# --------------------------------------------------------------------------- #
# Section B3-2: pending-row groups (admin-only, storage only — inert at commit)
# --------------------------------------------------------------------------- #
def _group_or_404(db: Session, batch_id: int, group_id: int):
    _get_batch(db, batch_id)
    group = import_review.get_group(db, batch_id, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import customer group not found")
    return group


def _group_read(db: Session, group) -> CustomerGroupRead:
    return CustomerGroupRead(**import_review.group_to_dict(db, group))


@router.post("/{batch_id}/customer-groups", response_model=CustomerGroupRead, status_code=status.HTTP_201_CREATED)
def create_customer_group(
    batch_id: int,
    payload: CustomerGroupCreateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> CustomerGroupRead:
    """B3-2 (storage only): group >= 2 pending rows into one future customer.

    Members are set to ``customer_resolution_mode = "group"``; a row's prior
    existing/new resolution is replaced. Admin only. Inert at commit/preview/reverse
    until B3-3.
    """
    batch = _get_batch(db, batch_id)
    try:
        group = import_review.create_group(
            db, batch,
            primary_row_id=payload.primary_row_id,
            member_row_ids=payload.member_row_ids,
            actor_id=admin.id,
            reason=payload.reason,
        )
        result = _group_read(db, group)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    db.commit()
    return result


@router.get("/{batch_id}/customer-groups", response_model=list[CustomerGroupRead])
def list_customer_groups(
    batch_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> list[CustomerGroupRead]:
    _get_batch(db, batch_id)
    return [_group_read(db, g) for g in import_review.list_groups(db, batch_id)]


@router.get("/{batch_id}/customer-groups/{group_id}", response_model=CustomerGroupRead)
def get_customer_group(
    batch_id: int, group_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> CustomerGroupRead:
    return _group_read(db, _group_or_404(db, batch_id, group_id))


@router.post("/{batch_id}/customer-groups/{group_id}/rows", response_model=CustomerGroupRead)
def add_group_row(
    batch_id: int,
    group_id: int,
    payload: CustomerGroupAddRowRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> CustomerGroupRead:
    batch = _get_batch(db, batch_id)
    group = _group_or_404(db, batch_id, group_id)
    try:
        import_review.add_to_group(db, batch, group, row_id=payload.row_id, actor_id=admin.id)
        result = _group_read(db, group)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    db.commit()
    return result


@router.delete("/{batch_id}/customer-groups/{group_id}/rows/{row_id}", response_model=CustomerGroupMutationResult)
def remove_group_row(
    batch_id: int,
    group_id: int,
    row_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> CustomerGroupMutationResult:
    """Remove a member. If the group drops below 2 members it auto-dissolves
    (``dissolved: true``, ``group: null``)."""
    batch = _get_batch(db, batch_id)
    group = _group_or_404(db, batch_id, group_id)
    try:
        survived = import_review.remove_from_group(db, batch, group, row_id=row_id, actor_id=admin.id)
        result = CustomerGroupMutationResult(
            dissolved=survived is None,
            group=_group_read(db, survived) if survived is not None else None,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    db.commit()
    return result


@router.patch("/{batch_id}/customer-groups/{group_id}", response_model=CustomerGroupRead)
def set_customer_group_primary(
    batch_id: int,
    group_id: int,
    payload: CustomerGroupSetPrimaryRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> CustomerGroupRead:
    batch = _get_batch(db, batch_id)
    group = _group_or_404(db, batch_id, group_id)
    try:
        import_review.set_group_primary(
            db, batch, group, primary_row_id=payload.primary_row_id, actor_id=admin.id
        )
        result = _group_read(db, group)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    db.commit()
    return result


@router.delete("/{batch_id}/customer-groups/{group_id}", response_model=CustomerGroupMutationResult)
def dissolve_customer_group(
    batch_id: int, group_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> CustomerGroupMutationResult:
    batch = _get_batch(db, batch_id)
    group = _group_or_404(db, batch_id, group_id)
    try:
        import_review.dissolve_group(db, batch, group, actor_id=admin.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    db.commit()
    return CustomerGroupMutationResult(dissolved=True, group=None)


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
    try:
        import_review.edit_row(db, batch, row, edits, actor_id=admin.id)
    except ValueError as exc:  # disallowed details path
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
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


@router.post("/{batch_id}/rows/{row_id}/prepare-recommit", response_model=ImportRowRead)
def prepare_recommit_row(
    batch_id: int, row_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> ImportRowRead:
    """Section D: prepare a REVERSED row to be committed again as a NEW Customer/Job.

    The ONLY sanctioned exit from the terminal REVERSED state — the generic /reopen
    stays a 409 for committed/reversed rows. Clears the committed links (stamping the
    prior ids into an audit Activity first), detaches any group, resets resolution, and
    returns the row to Pending. Admin only. Does NOT approve, commit, or touch the
    soft-deleted Job/Customer. 409 if the row is not reversed.
    """
    batch = _get_batch(db, batch_id)
    row = _row_or_404(db, batch_id, row_id)
    try:
        import_review.prepare_recommit(db, batch, row, actor_id=admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    db.commit()
    db.refresh(row)
    return ImportRowRead.model_validate(row)


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
