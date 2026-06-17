"""Section B2-2: persisted same-customer resolution wired into preview / commit /
reverse.

Synthetic data only. A row resolved to an EXISTING customer attaches its job to
that customer at commit (no new customer); preview agrees (attach vs create); and
reverse of an attached row soft-deletes only the imported Job, never the
pre-existing customer. A resolution to a missing/deleted customer FAILS the row.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.customer import Customer
from app.models.enums import (
    ActivityType,
    ImportBatchStatus,
    ImportRowClass,
    ImportRowReviewStatus,
)
from app.models.import_staging import ImportBatch, ImportRow
from app.models.job import Job
from app.services import import_commit, import_commit_preview as preview_svc, import_reverse
from app.services import job_labels as job_labels_service


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _customer(db: Session, *, name: str = "Existing Person", deleted: bool = False) -> Customer:
    c = Customer(full_name=name, suburb="Testville")
    if deleted:
        c.deleted_at = datetime.now(timezone.utc)
    db.add(c)
    db.flush()
    return c


def _seed(db: Session, *, ref: str, mode: str | None = None, customer_id: int | None = None,
          parsed: dict | None = None, resolved_by_id: int | None = None) -> tuple[ImportBatch, ImportRow]:
    b = ImportBatch(source_filename="syn.xlsx", sheet_name="COMPLETED",
                    status=ImportBatchStatus.REVIEWING.value)
    db.add(b)
    db.flush()
    row = ImportRow(
        batch_id=b.id, source_row_index=2, row_class=ImportRowClass.JOB.value,
        legacy_reference=ref, raw={"address": "1 Test St"},
        parsed=parsed or {"customer_name": "Imported Person", "sale_date": "01/06/2025", "address": "1 Test St"},
        review_status=ImportRowReviewStatus.APPROVED.value,
        customer_resolution_mode=mode, resolved_customer_id=customer_id,
        resolved_by_id=resolved_by_id,
    )
    db.add(row)
    db.flush()
    return b, row


def _counts(db: Session) -> tuple[int, int]:
    return (
        db.scalar(select(func.count()).select_from(Customer)) or 0,
        db.scalar(select(func.count()).select_from(Job).where(Job.deleted_at.is_(None))) or 0,
    )


def _label_keys(db: Session, job: Job) -> list[str]:
    return [a.label.key for a in job_labels_service.list_job_labels(db, job.id)]


# --------------------------------------------------------------------------- #
# A. Commit-to-live
# --------------------------------------------------------------------------- #
def test_commit_resolved_existing_attaches_job(users, db_session: Session):
    cust = _customer(db_session, name="Phillip Schuman")
    c_before, j_before = _counts(db_session)
    b, _row = _seed(db_session, ref="ATT0001", mode="existing", customer_id=cust.id,
                    resolved_by_id=users["admin"].id)

    res = import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    assert res["committed"] == 1 and res["failed"] == 0

    c_after, j_after = _counts(db_session)
    assert c_after == c_before          # NO new customer
    assert j_after == j_before + 1      # exactly one new job

    row = db_session.scalars(select(ImportRow).where(ImportRow.batch_id == b.id)).one()
    assert row.committed_customer_id == cust.id
    assert row.committed_job_id is not None
    assert row.review_status == ImportRowReviewStatus.COMMITTED.value
    job = db_session.get(Job, row.committed_job_id)
    assert job.customer_id == cust.id
    # The existing customer is NOT mutated by the attach.
    assert cust.notes is None and cust.full_name == "Phillip Schuman"
    # Activity records the attach for audit.
    act = db_session.scalars(
        select(Activity).where(Activity.job_id == job.id, Activity.activity_type == ActivityType.RECORD_IMPORTED)
    ).one()
    assert act.meta["attached_to_existing_customer"] is True
    assert act.meta["resolved_customer_id"] == cust.id
    assert act.meta["resolved_by_id"] == users["admin"].id
    assert "attached to an existing customer" in act.description


def test_attached_job_keeps_labels_and_override(users, db_session: Session):
    cust = _customer(db_session)
    parsed = {"customer_name": "Imported Person", "sale_date": "01/06/2025", "address": "1 Test St",
              "approval_state": "approved"}
    b, _row = _seed(db_session, ref="ATT0002", mode="existing", customer_id=cust.id, parsed=parsed)
    row = db_session.scalars(select(ImportRow).where(ImportRow.batch_id == b.id)).one()
    row.internal_notes_override = "Ring before 9am"
    db_session.flush()

    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    row = db_session.scalars(select(ImportRow).where(ImportRow.batch_id == b.id)).one()
    job = db_session.get(Job, row.committed_job_id)
    assert "approval_approved" in _label_keys(db_session, job)   # labels still auto-assign
    assert job.internal_notes == "Ring before 9am"               # override still honoured


def test_commit_unresolved_creates_new_customer_unchanged(users, db_session: Session):
    c_before, _ = _counts(db_session)
    b, _row = _seed(db_session, ref="NEW0001", mode=None)  # unresolved
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    c_after, _ = _counts(db_session)
    assert c_after == c_before + 1  # new customer created (existing behaviour)
    row = db_session.scalars(select(ImportRow).where(ImportRow.batch_id == b.id)).one()
    cust = db_session.get(Customer, row.committed_customer_id)
    assert cust.full_name == "Imported Person"


def test_commit_mode_new_creates_new_customer(users, db_session: Session):
    c_before, _ = _counts(db_session)
    b, _row = _seed(db_session, ref="NEW0002", mode="new")
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    assert _counts(db_session)[0] == c_before + 1


def test_commit_resolved_deleted_before_commit_fails(users, db_session: Session):
    # Resolved while the customer was valid; the customer is soft-deleted before
    # the commit runs. The row FAILS (no fallback), resolution is preserved.
    cust = _customer(db_session)
    b, _row = _seed(db_session, ref="DEL0001", mode="existing", customer_id=cust.id)
    cust.deleted_at = datetime.now(timezone.utc)
    db_session.flush()
    c_before, j_before = _counts(db_session)

    res = import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    assert res["committed"] == 0 and res["failed"] == 1
    assert res["results"][0]["status"] == "failed"
    assert res["results"][0]["reason"] == "resolved_customer_deleted"
    assert _counts(db_session) == (c_before, j_before)  # nothing created, no fallback
    # Resolution preserved (NOT cleared); row stays approved for a retry.
    row = db_session.scalars(select(ImportRow).where(ImportRow.batch_id == b.id)).one()
    assert row.customer_resolution_mode == "existing" and row.resolved_customer_id == cust.id
    assert row.committed_customer_id is None and row.review_status == ImportRowReviewStatus.APPROVED.value


def test_commit_resolved_already_deleted_customer_fails(users, db_session: Session):
    # A row referencing an already-soft-deleted customer (FK still satisfied —
    # rows are never hard-deleted) fails at commit.
    deleted = _customer(db_session, name="Gone", deleted=True)
    c_before, j_before = _counts(db_session)
    b, _row = _seed(db_session, ref="DEL0002", mode="existing", customer_id=deleted.id)
    res = import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    assert res["committed"] == 0 and res["failed"] == 1
    assert res["results"][0]["reason"] == "resolved_customer_deleted"
    assert _counts(db_session) == (c_before, j_before)


def test_attach_duplicate_legacy_reference_skipped(users, db_session: Session):
    # First a normal commit creates a live job with legacy ref DUP0001.
    b1, _r1 = _seed(db_session, ref="DUP0001", mode=None)
    import_commit.commit_batch(db_session, b1, actor_id=users["admin"].id)
    j_before = _counts(db_session)[1]
    # An attach row reusing the SAME legacy ref is skipped (no duplicate job).
    cust = _customer(db_session)
    b2, _r2 = _seed(db_session, ref="DUP0001", mode="existing", customer_id=cust.id)
    res = import_commit.commit_batch(db_session, b2, actor_id=users["admin"].id)
    assert res["committed"] == 0
    assert res["results"][0]["reason"] == "duplicate_legacy_reference"
    assert _counts(db_session)[1] == j_before


def test_multiple_rows_same_customer_different_refs(users, db_session: Session):
    cust = _customer(db_session)
    c_before, j_before = _counts(db_session)
    b = ImportBatch(source_filename="syn.xlsx", sheet_name="COMPLETED",
                    status=ImportBatchStatus.REVIEWING.value)
    db_session.add(b)
    db_session.flush()
    for i, ref in enumerate(["MULTI01", "MULTI02"]):
        db_session.add(ImportRow(
            batch_id=b.id, source_row_index=i + 2, row_class=ImportRowClass.JOB.value,
            legacy_reference=ref, raw={"address": "1 Test St"},
            parsed={"customer_name": "Imported Person", "sale_date": "01/06/2025", "address": "1 Test St"},
            review_status=ImportRowReviewStatus.APPROVED.value,
            customer_resolution_mode="existing", resolved_customer_id=cust.id,
        ))
    db_session.flush()
    res = import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    assert res["committed"] == 2
    c_after, j_after = _counts(db_session)
    assert c_after == c_before          # no new customers
    assert j_after == j_before + 2      # two jobs under the same existing customer
    jobs = db_session.scalars(select(Job).where(Job.customer_id == cust.id)).all()
    assert len(jobs) == 2


# --------------------------------------------------------------------------- #
# B. Preview
# --------------------------------------------------------------------------- #
def test_preview_resolved_existing_attach(db_session: Session):
    cust = _customer(db_session, name="Preview Target")
    b, row = _seed(db_session, ref="PREV0001", mode="existing", customer_id=cust.id)
    p = preview_svc.preview(db_session, b)
    assert p["eligible_count"] == 1
    assert p["would_create"]["customers"] == 0   # attach creates no customer
    assert p["would_create"]["jobs"] == 1
    assert p["would_attach_jobs"] == 1
    sample = next(s for s in p["samples"] if s["row_id"] == row.id)
    assert sample["customer_action"] == "attach"
    assert sample["resolved_customer_id"] == cust.id
    assert sample["resolved_customer_name"] == "Preview Target"


def test_preview_resolved_invalid_excluded(db_session: Session):
    # Target customer soft-deleted -> the attach is invalid, excluded from preview.
    deleted = _customer(db_session, name="Gone", deleted=True)
    b, _row = _seed(db_session, ref="PREV0002", mode="existing", customer_id=deleted.id)
    p = preview_svc.preview(db_session, b)
    assert p["excluded"]["resolved_customer_invalid"] == 1
    assert p["eligible_count"] == 0
    assert p["would_create"]["customers"] == 0 and p["would_attach_jobs"] == 0
    assert p["samples"] == []


def test_preview_mixed_create_and_attach(db_session: Session):
    cust = _customer(db_session)
    b = ImportBatch(source_filename="syn.xlsx", sheet_name="COMPLETED",
                    status=ImportBatchStatus.REVIEWING.value)
    db_session.add(b)
    db_session.flush()
    db_session.add(ImportRow(
        batch_id=b.id, source_row_index=2, row_class=ImportRowClass.JOB.value,
        legacy_reference="MIX01", raw={}, parsed={"customer_name": "New One", "sale_date": "01/06/2025"},
        review_status=ImportRowReviewStatus.APPROVED.value,
    ))
    db_session.add(ImportRow(
        batch_id=b.id, source_row_index=3, row_class=ImportRowClass.JOB.value,
        legacy_reference="MIX02", raw={}, parsed={"customer_name": "Attach One", "sale_date": "01/06/2025"},
        review_status=ImportRowReviewStatus.APPROVED.value,
        customer_resolution_mode="existing", resolved_customer_id=cust.id,
    ))
    db_session.flush()
    p = preview_svc.preview(db_session, b)
    assert p["eligible_count"] == 2
    assert p["would_create"]["customers"] == 1   # only the unresolved row
    assert p["would_create"]["jobs"] == 2
    assert p["would_attach_jobs"] == 1


def test_preview_makes_no_writes(db_session: Session):
    cust = _customer(db_session)
    b, _row = _seed(db_session, ref="PREV0003", mode="existing", customer_id=cust.id)
    c_before, j_before = _counts(db_session)
    preview_svc.preview(db_session, b)
    preview_svc.preview(db_session, b)
    assert _counts(db_session) == (c_before, j_before)
    row = db_session.scalars(select(ImportRow).where(ImportRow.batch_id == b.id)).one()
    assert row.committed_customer_id is None  # preview did not commit


# --------------------------------------------------------------------------- #
# C. Reverse
# --------------------------------------------------------------------------- #
def _commit_attached(db: Session, admin_id: int, *, ref: str, with_other_job: bool = False):
    cust = _customer(db)
    if with_other_job:
        db.add(Job(case_number=f"SCS-1990-{ref[-4:]}", customer_id=cust.id, status="installed"))
        db.flush()
    b, _row = _seed(db, ref=ref, mode="existing", customer_id=cust.id)
    import_commit.commit_batch(db, b, actor_id=admin_id)
    row = db.scalars(select(ImportRow).where(ImportRow.batch_id == b.id)).one()
    return cust, row


def test_reverse_attached_soft_deletes_only_job(users, db_session: Session):
    admin_id = users["admin"].id
    # The existing customer already has another job -> proves the attach reverse
    # is NOT blocked by customer_has_other_jobs and never touches the customer.
    cust, row = _commit_attached(db_session, admin_id, ref="REVA0001", with_other_job=True)
    job_id = row.committed_job_id

    assert import_reverse.reversibility(db_session, row)["reversible"] is True
    res = import_reverse.reverse_row(db_session, row, actor_id=admin_id)
    assert res["status"] == "reversed"

    job = db_session.get(Job, job_id)
    cust = db_session.get(Customer, cust.id)
    assert job.deleted_at is not None          # imported job soft-deleted
    assert cust.deleted_at is None             # existing customer KEPT
    # The customer's other job is untouched.
    other = db_session.scalars(
        select(Job).where(Job.customer_id == cust.id, Job.id != job_id)
    ).all()
    assert len(other) == 1 and other[0].deleted_at is None

    db_session.refresh(row)
    assert row.review_status == ImportRowReviewStatus.REVERSED.value
    rev = db_session.scalars(
        select(Activity).where(Activity.job_id == job_id,
                               Activity.activity_type == ActivityType.RECORD_IMPORT_REVERSED)
    ).one()
    assert rev.meta["attached_to_existing_customer"] is True


def test_reverse_attached_still_blocks_on_job_modified(users, db_session: Session):
    admin_id = users["admin"].id
    _cust, row = _commit_attached(db_session, admin_id, ref="REVA0002")
    job = db_session.get(Job, row.committed_job_id)
    # Simulate a real later edit to the job.
    db_session.execute(
        update(Job).where(Job.id == job.id).values(updated_at=job.created_at + timedelta(seconds=10))
    )
    db_session.expire(job)
    assert import_reverse.reverse_row(db_session, row, actor_id=admin_id)["reason"] == "job_modified"
    # Nothing was deleted.
    assert db_session.get(Job, row.committed_job_id).deleted_at is None


def test_reverse_normal_row_soft_deletes_both(users, db_session: Session):
    admin_id = users["admin"].id
    b, _row = _seed(db_session, ref="REVN0001", mode=None)  # new-customer commit
    import_commit.commit_batch(db_session, b, actor_id=admin_id)
    row = db_session.scalars(select(ImportRow).where(ImportRow.batch_id == b.id)).one()
    cust_id, job_id = row.committed_customer_id, row.committed_job_id
    res = import_reverse.reverse_row(db_session, row, actor_id=admin_id)
    assert res["status"] == "reversed"
    # Existing (unchanged) behaviour: BOTH the created customer and job are soft-deleted.
    assert db_session.get(Job, job_id).deleted_at is not None
    assert db_session.get(Customer, cust_id).deleted_at is not None
