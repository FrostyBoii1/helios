"""Tests for the Phase C1 commit-to-live engine.

Synthetic data only. Exercises eligibility, subset row_ids, the per-call cap,
idempotent re-run, duplicate-legacy_reference skip, per-row partial-failure
safety (no orphans), committed_* linkage, batch-status transitions,
case-number year derivation, one RECORD_IMPORTED activity per job, no mutation
of pre-existing live records, and admin-only access.
"""

from __future__ import annotations

from sqlalchemy import func, select
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
from app.services import import_commit
from tests.test_import import _synthetic_bytes


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _ingest(client) -> int:
    return client.post(
        "/api/v1/imports",
        files={"file": ("synthetic.xlsx", _synthetic_bytes(), "application/vnd.ms-excel")},
    ).json()["id"]


def _rows(client, bid: int) -> list[dict]:
    return client.get(f"/api/v1/imports/{bid}/rows", params={"limit": 200}).json()["items"]


def _by_ref(rows: list[dict], ref: str) -> dict:
    return next(r for r in rows if r["legacy_reference"] == ref)


def _status(job: Job) -> str:
    # Job.status is stored in a String column; loads as a plain string.
    return job.status.value if hasattr(job.status, "value") else str(job.status)


def _commit(client, bid: int, row_ids: list[int] | None = None) -> dict:
    body = {"row_ids": row_ids} if row_ids is not None else {}
    resp = client.post(f"/api/v1/imports/{bid}/commit", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _seed_batch(db: Session, n: int, *, prefix: str, approved: bool = True) -> ImportBatch:
    b = ImportBatch(
        source_filename="syn.xlsx",
        sheet_name="COMPLETED",
        status=ImportBatchStatus.REVIEWING.value,
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
                raw={"address": f"{i} Seed St"},
                parsed={"customer_name": f"Person {i}", "sale_date": "01/06/2025", "address": f"{i} Seed St"},
                review_status=status,
            )
        )
    db.flush()
    return b


# --------------------------------------------------------------------------- #
# Core: creates records + linkage + status + activity
# --------------------------------------------------------------------------- #
def test_commit_creates_customer_and_job(client_for, users, db_session: Session):
    cust_before = db_session.scalar(select(func.count()).select_from(Customer))
    job_before = db_session.scalar(select(func.count()).select_from(Job))

    admin = client_for(users["admin"])
    bid = _ingest(admin)
    admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")  # approves TESTIMP0001/0002/0004
    res = _commit(admin, bid)

    assert res["committed"] == 3 and res["attempted"] == 3 and res["failed"] == 0
    assert res["remaining_eligible"] == 0
    assert res["batch_status"] == ImportBatchStatus.COMMITTED.value

    assert db_session.scalar(select(func.count()).select_from(Customer)) == cust_before + 3
    assert db_session.scalar(select(func.count()).select_from(Job)) == job_before + 3

    # Linkage + mapping on the committed rows.
    rows = db_session.scalars(select(ImportRow).where(ImportRow.batch_id == bid)).all()
    committed = [r for r in rows if r.review_status == ImportRowReviewStatus.COMMITTED.value]
    assert len(committed) == 3
    for r in committed:
        assert r.committed_customer_id and r.committed_job_id
        job = db_session.get(Job, r.committed_job_id)
        assert job.legacy_reference == r.legacy_reference
        assert _status(job) == "installed"

    # One RECORD_IMPORTED activity per committed job.
    job_ids = [r.committed_job_id for r in committed]
    imp = db_session.scalars(
        select(Activity).where(Activity.activity_type == ActivityType.RECORD_IMPORTED, Activity.job_id.in_(job_ids))
    ).all()
    assert len(imp) == 3
    assert sorted(a.job_id for a in imp) == sorted(job_ids)


def test_address_and_case_year_mapping(client_for, users, db_session: Session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")
    _commit(admin, bid)

    rows = {r.legacy_reference: r for r in db_session.scalars(select(ImportRow).where(ImportRow.batch_id == bid)).all()}
    j1 = db_session.get(Job, rows["TESTIMP0001"].committed_job_id)
    j4 = db_session.get(Job, rows["TESTIMP0004"].committed_job_id)
    cust1 = db_session.get(Customer, rows["TESTIMP0001"].committed_customer_id)
    assert cust1.address_line1 == "1 Test St"            # parsed address mapped
    assert j1.case_number.startswith("SCS-2025-")        # sale_date 10/10/2025
    assert j4.case_number.startswith("SCS-2026-")        # install_date 01/01/2026


# --------------------------------------------------------------------------- #
# Eligibility + subset
# --------------------------------------------------------------------------- #
def test_only_approved_eligible(client_for, users, db_session: Session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    # Approve only TESTIMP0001.
    row1 = _by_ref(_rows(admin, bid), "TESTIMP0001")
    admin.post(f"/api/v1/imports/{bid}/rows/{row1['id']}/approve")
    res = _commit(admin, bid)
    assert res["committed"] == 1
    # The committed one is TESTIMP0001; pending/error rows were not created.
    assert res["results"][0]["legacy_reference"] == "TESTIMP0001"


def test_subset_row_ids(client_for, users, db_session: Session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")
    rows = _rows(admin, bid)
    only = _by_ref(rows, "TESTIMP0002")["id"]
    # TESTIMP0003 carries an unresolved error, so bulk-approve left it pending ->
    # it is ineligible (caught as not_approved before the error check).
    err = _by_ref(rows, "TESTIMP0003")["id"]
    res = _commit(admin, bid, row_ids=[only, err])
    assert res["committed"] == 1
    statuses = {r["row_id"]: r for r in res["results"]}
    assert statuses[only]["status"] == "committed"
    assert statuses[err]["status"] == "skipped" and statuses[err]["reason"] == "not_approved"
    assert res["remaining_eligible"] == 2  # TESTIMP0001 + TESTIMP0004 still eligible


# --------------------------------------------------------------------------- #
# Cap + partial status (direct-seeded rows)
# --------------------------------------------------------------------------- #
def test_per_call_cap_25(users, db_session: Session):
    admin_id = users["admin"].id
    b = _seed_batch(db_session, 30, prefix="CAP")
    res = import_commit.commit_batch(db_session, b, actor_id=admin_id)
    assert res["committed"] == 25
    assert res["cap"] == 25 and res["capped_out"] == 5
    assert res["remaining_eligible"] == 5
    assert res["batch_status"] == ImportBatchStatus.COMMITTED_PARTIAL.value
    # A follow-up call commits the rest and flips the batch to COMMITTED.
    res2 = import_commit.commit_batch(db_session, db_session.get(ImportBatch, b.id), actor_id=admin_id)
    assert res2["committed"] == 5 and res2["remaining_eligible"] == 0
    assert res2["batch_status"] == ImportBatchStatus.COMMITTED.value


# --------------------------------------------------------------------------- #
# Idempotency + duplicate legacy_reference
# --------------------------------------------------------------------------- #
def test_invalid_case_year_not_committed(client_for, users, db_session: Session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")
    # Malformed sale date -> derived case-year 2002 -> must be blocked.
    admin.patch(f"/api/v1/imports/{bid}/rows/{row['id']}", json={"sale_date": "01/06/2002"})
    admin.post(f"/api/v1/imports/{bid}/rows/{row['id']}/approve")
    admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")

    cust_before = db_session.scalar(select(func.count()).select_from(Customer))

    # Targeting the bad row explicitly -> skipped with the reason, nothing created.
    res = _commit(admin, bid, row_ids=[row["id"]])
    assert res["committed"] == 0
    assert res["results"][0]["reason"] == "invalid_case_year"
    assert db_session.scalar(select(func.count()).select_from(Customer)) == cust_before

    # Committing everything still commits the 2 valid rows but never the bad one.
    res2 = _commit(admin, bid)
    assert res2["committed"] == 2
    bad = db_session.get(ImportRow, row["id"])
    assert bad.committed_job_id is None
    assert bad.review_status == ImportRowReviewStatus.APPROVED.value  # still approved, not committed


def test_idempotent_rerun(client_for, users, db_session: Session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")
    _commit(admin, bid)
    cust_after_first = db_session.scalar(select(func.count()).select_from(Customer))
    res2 = _commit(admin, bid)
    assert res2["committed"] == 0 and res2["attempted"] == 0
    assert db_session.scalar(select(func.count()).select_from(Customer)) == cust_after_first


def test_duplicate_legacy_reference_skipped(client_for, users, db_session: Session):
    admin = client_for(users["admin"])
    bid1 = _ingest(admin)
    admin.post(f"/api/v1/imports/{bid1}/bulk-approve-clean")
    _commit(admin, bid1)  # creates jobs with legacy_reference TESTIMP0001/0002/0004

    # Re-ingest the same workbook; same legacy refs now exist live.
    bid2 = admin.post(
        "/api/v1/imports?allow_duplicate=true",
        files={"file": ("synthetic.xlsx", _synthetic_bytes(), "application/vnd.ms-excel")},
    ).json()["id"]
    admin.post(f"/api/v1/imports/{bid2}/bulk-approve-clean")
    job_before = db_session.scalar(select(func.count()).select_from(Job))
    res = _commit(admin, bid2)
    assert res["committed"] == 0
    assert all(r["reason"] == "duplicate_legacy_reference" for r in res["results"] if r["status"] == "skipped")
    assert db_session.scalar(select(func.count()).select_from(Job)) == job_before  # no duplicates


# --------------------------------------------------------------------------- #
# Partial-failure safety (no orphan, no blocking)
# --------------------------------------------------------------------------- #
def test_row_failure_creates_no_orphan(users, db_session: Session):
    admin_id = users["admin"].id
    b = _seed_batch(db_session, 3, prefix="FAIL")
    # Make the middle row's name exceed Customer.full_name (String(160)) -> DB error.
    rows = db_session.scalars(select(ImportRow).where(ImportRow.batch_id == b.id).order_by(ImportRow.source_row_index)).all()
    rows[1].parsed = {**rows[1].parsed, "customer_name": "X" * 200}
    db_session.flush()

    cust_before = db_session.scalar(select(func.count()).select_from(Customer))
    res = import_commit.commit_batch(db_session, b, actor_id=admin_id)
    assert res["committed"] == 2 and res["failed"] == 1
    # Exactly 2 customers created — the failed row left no orphan.
    assert db_session.scalar(select(func.count()).select_from(Customer)) == cust_before + 2
    bad = db_session.get(ImportRow, rows[1].id)
    assert bad.committed_customer_id is None and bad.committed_job_id is None
    assert bad.review_status == ImportRowReviewStatus.APPROVED.value  # unchanged


# --------------------------------------------------------------------------- #
# No mutation of pre-existing live records
# --------------------------------------------------------------------------- #
def test_no_mutation_of_existing_records(client_for, users, db_session: Session):
    # A control customer + job created before the import commit.
    control_cust = Customer(full_name="Control Person")
    db_session.add(control_cust)
    db_session.flush()
    control_job = Job(case_number="SCS-1999-99999", customer_id=control_cust.id, status="installed")
    db_session.add(control_job)
    db_session.commit()
    cust_updated_before = control_cust.updated_at
    job_updated_before = control_job.updated_at

    admin = client_for(users["admin"])
    bid = _ingest(admin)
    admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")
    _commit(admin, bid)

    db_session.refresh(control_cust)
    db_session.refresh(control_job)
    assert control_cust.updated_at == cust_updated_before
    assert control_job.updated_at == job_updated_before
    assert control_job.legacy_reference is None


# --------------------------------------------------------------------------- #
# Permissions
# --------------------------------------------------------------------------- #
def test_commit_admin_only(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")
    support = client_for(users["support"])
    assert support.post(f"/api/v1/imports/{bid}/commit", json={}).status_code == 403


# --------------------------------------------------------------------------- #
# Name-cell notes + decommission carried into the committed Job notes
# --------------------------------------------------------------------------- #
def _seed_one(db: Session, parsed: dict, *, ref: str) -> ImportBatch:
    b = ImportBatch(source_filename="syn.xlsx", sheet_name="COMPLETED",
                    status=ImportBatchStatus.REVIEWING.value)
    db.add(b)
    db.flush()
    db.add(ImportRow(
        batch_id=b.id, source_row_index=2, row_class=ImportRowClass.JOB.value,
        legacy_reference=ref, raw={"address": "1 Test St"}, parsed=parsed,
        review_status=ImportRowReviewStatus.APPROVED.value,
    ))
    db.flush()
    return b


def test_decommission_and_name_notes_in_job_notes(users, db_session: Session):
    parsed = {
        "customer_name": "Pat Lee",
        "customer_name_notes": "includes hot water timer",
        "removes_old_system": True,
        "decommission_marker": "REMOVE OLD SYSTEM",
        "sale_date": "01/06/2025",
        "address": "1 Test St",
    }
    b = _seed_one(db_session, parsed, ref="DECOM01")
    res = import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    assert res["committed"] == 1

    row = db_session.scalars(select(ImportRow).where(ImportRow.batch_id == b.id)).one()
    job = db_session.get(Job, row.committed_job_id)
    notes = job.notes or ""
    # Decommission is surfaced prominently (first line) in the Job notes.
    assert notes.splitlines()[0].startswith("REMOVE OLD SYSTEM")
    assert "REMOVE OLD SYSTEM" in notes
    # Preserved name-cell text reaches the Job notes where staff will see it.
    assert "From name cell: includes hot water timer" in notes
    # And the meaningful note also reaches the Customer notes.
    cust = db_session.get(Customer, row.committed_customer_id)
    assert "includes hot water timer" in (cust.notes or "")


def test_no_decommission_means_no_marker_line(users, db_session: Session):
    parsed = {"customer_name": "Dana Fox", "sale_date": "01/06/2025", "address": "2 Test St"}
    b = _seed_one(db_session, parsed, ref="PLAIN01")
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    row = db_session.scalars(select(ImportRow).where(ImportRow.batch_id == b.id)).one()
    job = db_session.get(Job, row.committed_job_id)
    assert "REMOVE OLD SYSTEM" not in (job.notes or "")
