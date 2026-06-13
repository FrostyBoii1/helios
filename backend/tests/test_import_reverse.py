"""Tests for the Phase C3a per-row reverse/undo engine.

Synthetic data only. Verifies the happy-path reverse (soft-delete + audit), the
full conservative block predicate, idempotency, no-collateral isolation,
read-only reverse-check, and admin-only access.

Note on timestamps: Postgres now() is constant within a transaction, so an
in-test ORM edit will NOT bump updated_at. The "modified" blocks are simulated
by setting updated_at explicitly via a Core UPDATE (which mirrors what a real,
separate-transaction edit produces: updated_at > created_at).
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.customer import Customer
from app.models.document import Document
from app.models.enums import (
    ActivityType,
    ImportBatchStatus,
    ImportRowClass,
    ImportRowReviewStatus,
)
from app.models.import_staging import ImportBatch, ImportRow
from app.models.job import Job
from app.models.task import Task
from app.services import import_commit, import_reverse
from app.services.activity import log_activity
from tests.test_import import _synthetic_bytes


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _seed(db: Session, n: int, *, prefix: str = "REV", approved: bool = True) -> ImportBatch:
    b = ImportBatch(
        source_filename="syn.xlsx", sheet_name="COMPLETED", status=ImportBatchStatus.REVIEWING.value
    )
    db.add(b)
    db.flush()
    status = ImportRowReviewStatus.APPROVED.value if approved else ImportRowReviewStatus.PENDING.value
    for i in range(n):
        db.add(
            ImportRow(
                batch_id=b.id,
                source_row_index=i + 2,
                row_class=ImportRowClass.JOB.value,
                legacy_reference=f"{prefix}{i:04d}",
                raw={"address": f"{i} Rev St"},
                parsed={"customer_name": f"Person {i}", "sale_date": "01/06/2025", "address": f"{i} Rev St"},
                review_status=status,
            )
        )
    db.flush()
    return b


def _seed_and_commit(db: Session, n: int, admin_id: int, *, prefix: str = "REV") -> list[ImportRow]:
    b = _seed(db, n, prefix=prefix)
    import_commit.commit_batch(db, b, actor_id=admin_id)
    return list(
        db.scalars(
            select(ImportRow).where(ImportRow.batch_id == b.id).order_by(ImportRow.source_row_index)
        ).all()
    )


def _touch_updated_at(db: Session, model, obj_id: int) -> None:
    """Simulate a real later edit: updated_at > created_at."""
    obj = db.get(model, obj_id)
    db.execute(
        update(model).where(model.id == obj_id).values(updated_at=obj.created_at + timedelta(seconds=10))
    )
    db.expire(obj)


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_reverse_happy_path(users, db_session: Session):
    admin_id = users["admin"].id
    rows = _seed_and_commit(db_session, 2, admin_id)
    r = rows[0]
    job_id, cust_id = r.committed_job_id, r.committed_customer_id

    assert import_reverse.reversibility(db_session, r)["reversible"] is True
    res = import_reverse.reverse_row(db_session, r, actor_id=admin_id)
    assert res["status"] == "reversed" and res["case_number"]

    job = db_session.get(Job, job_id)
    cust = db_session.get(Customer, cust_id)
    assert job.deleted_at is not None and cust.deleted_at is not None  # soft-deleted

    db_session.refresh(r)
    assert r.review_status == ImportRowReviewStatus.REVERSED.value
    assert r.committed_job_id == job_id and r.committed_customer_id == cust_id  # links preserved

    imported = db_session.scalar(
        select(func.count()).select_from(Activity).where(
            Activity.job_id == job_id, Activity.activity_type == ActivityType.RECORD_IMPORTED
        )
    )
    reversed_ct = db_session.scalar(
        select(func.count()).select_from(Activity).where(
            Activity.job_id == job_id, Activity.activity_type == ActivityType.RECORD_IMPORT_REVERSED
        )
    )
    assert imported == 1 and reversed_ct == 1  # original preserved + one reversal


def test_no_collateral_to_other_rows(users, db_session: Session):
    admin_id = users["admin"].id
    rows = _seed_and_commit(db_session, 2, admin_id)
    import_reverse.reverse_row(db_session, rows[0], actor_id=admin_id)

    other = db_session.get(ImportRow, rows[1].id)
    assert other.review_status == ImportRowReviewStatus.COMMITTED.value
    assert db_session.get(Job, other.committed_job_id).deleted_at is None
    assert db_session.get(Customer, other.committed_customer_id).deleted_at is None


# --------------------------------------------------------------------------- #
# Block predicate (one per condition)
# --------------------------------------------------------------------------- #
def _reason(db, r) -> str | None:
    return import_reverse.reverse_row(db, r, actor_id=1)["reason"]


def test_block_not_committed(db_session: Session):
    b = _seed(db_session, 1, prefix="NC")
    r = db_session.scalar(select(ImportRow).where(ImportRow.batch_id == b.id))
    res = import_reverse.reverse_row(db_session, r, actor_id=1)
    assert res["status"] == "blocked" and res["reason"] == "not_committed"


def test_block_job_modified(users, db_session: Session):
    r = _seed_and_commit(db_session, 1, users["admin"].id, prefix="JM")[0]
    _touch_updated_at(db_session, Job, r.committed_job_id)
    assert _reason(db_session, r) == "job_modified"


def test_block_customer_modified(users, db_session: Session):
    r = _seed_and_commit(db_session, 1, users["admin"].id, prefix="CM")[0]
    _touch_updated_at(db_session, Customer, r.committed_customer_id)
    assert _reason(db_session, r) == "customer_modified"


def test_block_job_has_tasks(users, db_session: Session):
    r = _seed_and_commit(db_session, 1, users["admin"].id, prefix="TK")[0]
    db_session.add(Task(title="follow up", job_id=r.committed_job_id))
    db_session.flush()
    assert _reason(db_session, r) == "job_has_tasks"


def test_block_job_has_documents(users, db_session: Session):
    r = _seed_and_commit(db_session, 1, users["admin"].id, prefix="DOC")[0]
    db_session.add(Document(original_filename="x.pdf", relative_path="a/x.pdf", job_id=r.committed_job_id))
    db_session.flush()
    assert _reason(db_session, r) == "job_has_documents"


def test_block_non_import_activity(users, db_session: Session):
    r = _seed_and_commit(db_session, 1, users["admin"].id, prefix="ACT")[0]
    log_activity(db_session, activity_type=ActivityType.NOTE_ADDED, description="note", job_id=r.committed_job_id)
    db_session.flush()
    assert _reason(db_session, r) == "job_has_activity"


def test_block_status_changed(users, db_session: Session):
    r = _seed_and_commit(db_session, 1, users["admin"].id, prefix="ST")[0]
    db_session.execute(update(Job).where(Job.id == r.committed_job_id).values(status="ready_to_schedule"))
    db_session.flush()
    assert _reason(db_session, r) == "status_changed"


def test_block_customer_has_other_jobs(users, db_session: Session):
    r = _seed_and_commit(db_session, 1, users["admin"].id, prefix="OJ")[0]
    db_session.add(Job(case_number="SCS-1990-00001", customer_id=r.committed_customer_id, status="installed"))
    db_session.flush()
    assert _reason(db_session, r) == "customer_has_other_jobs"


def test_block_legacy_reference_mismatch(users, db_session: Session):
    r = _seed_and_commit(db_session, 1, users["admin"].id, prefix="LR")[0]
    db_session.execute(update(Job).where(Job.id == r.committed_job_id).values(legacy_reference="DIFFERENT"))
    db_session.flush()
    assert _reason(db_session, r) == "legacy_reference_mismatch"


def test_block_already_reversed(users, db_session: Session):
    admin_id = users["admin"].id
    r = _seed_and_commit(db_session, 1, admin_id, prefix="AR")[0]
    assert import_reverse.reverse_row(db_session, r, actor_id=admin_id)["status"] == "reversed"
    db_session.refresh(r)
    res = import_reverse.reverse_row(db_session, r, actor_id=admin_id)
    assert res["status"] == "blocked" and res["reason"] == "already_reversed"


# --------------------------------------------------------------------------- #
# reverse-check is read-only
# --------------------------------------------------------------------------- #
def test_reverse_check_is_read_only(users, db_session: Session):
    admin_id = users["admin"].id
    r = _seed_and_commit(db_session, 1, admin_id, prefix="RO")[0]
    act_before = db_session.scalar(select(func.count()).select_from(Activity))
    chk = import_reverse.reversibility(db_session, r)
    assert chk["reversible"] is True
    # nothing soft-deleted, no activity added
    assert db_session.get(Job, r.committed_job_id).deleted_at is None
    assert db_session.get(Customer, r.committed_customer_id).deleted_at is None
    assert db_session.scalar(select(func.count()).select_from(Activity)) == act_before
    db_session.refresh(r)
    assert r.review_status == ImportRowReviewStatus.COMMITTED.value


# --------------------------------------------------------------------------- #
# Endpoints: admin-only
# --------------------------------------------------------------------------- #
def test_reverse_admin_only(client_for, users):
    admin = client_for(users["admin"])
    bid = admin.post(
        "/api/v1/imports",
        files={"file": ("synthetic.xlsx", _synthetic_bytes(), "application/vnd.ms-excel")},
    ).json()["id"]
    row = admin.get(f"/api/v1/imports/{bid}/rows", params={"limit": 200}).json()["items"][0]
    support = client_for(users["support"])
    assert support.get(f"/api/v1/imports/{bid}/rows/{row['id']}/reverse-check").status_code == 403
    assert support.post(f"/api/v1/imports/{bid}/rows/{row['id']}/reverse").status_code == 403
