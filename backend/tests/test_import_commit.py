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
    JobLabelSource,
)
from app.models.import_staging import ImportBatch, ImportRow
from app.models.job import Job
from app.services import import_commit
from app.services import job_labels as job_labels_service
from app.services.import_details import render_legacy_blobs
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
    # "1 Test St" has no state+postcode anchor -> conservatively unstructured, so
    # suburb/state/postcode are NOT guessed.
    assert cust1.suburb is None and cust1.state is None and cust1.postcode is None
    assert j1.case_number.startswith("SCS-2025-")        # sale_date 10/10/2025
    assert j4.case_number.startswith("SCS-2026-")        # install_date 01/01/2026


def test_address_parts_populate_customer_columns(users, db_session: Session):
    """When parse_address structured the cell, the committed Customer gets
    address_line1 / suburb / state / postcode populated (Phase-7 cleanup wiring)."""
    admin_id = users["admin"].id
    b = ImportBatch(
        source_filename="syn.xlsx", sheet_name="COMPLETED",
        status=ImportBatchStatus.REVIEWING.value,
    )
    db_session.add(b)
    db_session.flush()
    db_session.add(
        ImportRow(
            batch_id=b.id, source_row_index=2, row_class=ImportRowClass.JOB.value,
            legacy_reference="ADDR0001",
            raw={"address": "39 Example St, Cooma NSW 2866"},
            parsed={
                "customer_name": "Pat Lee", "sale_date": "01/06/2025",
                "address": "39 Example St, Cooma NSW 2866",
                "address_parts": {
                    "line1": "39 Example St", "suburb": "Cooma",
                    "state": "NSW", "postcode": "2866", "structured": True,
                },
            },
            review_status=ImportRowReviewStatus.APPROVED.value,
        )
    )
    db_session.flush()
    res = import_commit.commit_batch(db_session, b, actor_id=admin_id)
    assert res["committed"] == 1
    row = db_session.scalars(select(ImportRow).where(ImportRow.batch_id == b.id)).one()
    cust = db_session.get(Customer, row.committed_customer_id)
    assert cust.address_line1 == "39 Example St"
    assert cust.suburb == "Cooma"
    assert cust.state == "NSW"
    assert cust.postcode == "2866"


def test_address_fallback_when_address_parts_absent(users, db_session: Session):
    """A row staged before the cleanup (no address_parts) keeps the raw address in
    address_line1, and suburb/state/postcode stay blank — back-compat preserved."""
    admin_id = users["admin"].id
    b = _seed_batch(db_session, 1, prefix="ADDRB")  # parsed has no address_parts
    res = import_commit.commit_batch(db_session, b, actor_id=admin_id)
    assert res["committed"] == 1
    row = db_session.scalars(select(ImportRow).where(ImportRow.batch_id == b.id)).one()
    cust = db_session.get(Customer, row.committed_customer_id)
    assert cust.address_line1 == "0 Seed St"  # raw single-line preserved
    assert cust.suburb is None and cust.state is None and cust.postcode is None


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


# --------------------------------------------------------------------------- #
# Phase 2b: commit writes Job.details + derived legacy blobs
# --------------------------------------------------------------------------- #
def _details_parsed(**extra):
    parsed = {
        "customer_name": "Pat Lee", "sale_date": "01/06/2025", "address": "1 Test St",
        "approval_state": "approved", "notes_raw": "call first",
        "details": {
            "_v": 2,
            "sales": {"salesperson_text": "Rep"},
            "system": {"panel_count": 16, "panel": "Longi 440", "phase": "three"},
            "payment": {"total": "5000"},
            "flags": {"removes_old_system": True, "decommission_marker": "REMOVE OLD SYSTEM"},
            "notes": {
                "customer_name_notes": "includes hot water timer",
                "misfiled": [{"source_column": "MSB/SB PICS IN FILE?", "text": "DONT CALL PLEASE"}],
            },
            "legacy": {"solar_vic": "100"},
        },
    }
    parsed.update(extra)
    return parsed


def _commit_one_seeded(db, users, parsed, ref):
    b = _seed_one(db, parsed, ref=ref)
    res = import_commit.commit_batch(db, b, actor_id=users["admin"].id)
    assert res["committed"] == 1
    row = db.scalars(select(ImportRow).where(ImportRow.batch_id == b.id)).one()
    return b, row, db.get(Job, row.committed_job_id)


def test_commit_writes_job_details(users, db_session: Session):
    parsed = _details_parsed()
    _b, _row, job = _commit_one_seeded(db_session, users, parsed, "TESTIMP2B01")
    assert job.details is not None
    assert job.details["_v"] == 2
    assert job.details["system"]["panel_count"] == 16
    assert job.details == parsed["details"]  # written verbatim from the staged details


def test_commit_blobs_match_renderer(users, db_session: Session):
    parsed = _details_parsed()
    b, row, job = _commit_one_seeded(db_session, users, parsed, "TESTIMP2B02")
    expected = render_legacy_blobs(
        job.details, parsed,
        batch_id=b.id, source_row_index=row.source_row_index, legacy_reference="TESTIMP2B02",
    )
    assert job.system_details == expected["system_details"]
    assert job.install_details == expected["install_details"]
    assert job.approval_details == expected["approval_details"]
    assert job.notes == expected["notes"]
    # And the derived blobs are populated (back-compat).
    assert job.system_details and "Panels: 16" in job.system_details
    assert job.notes.splitlines()[0].startswith("REMOVE OLD SYSTEM")


def test_commit_misfiled_and_legacy_in_notes(users, db_session: Session):
    parsed = _details_parsed()
    # A neutral imported review note rides alongside the misfiled source note; both
    # must commit through to Job.details (structured) AND the legacy notes blob.
    parsed["details"]["notes"]["review_notes"] = [
        {"source_column": "Customer Name", "text": "Jemena Approval # 000413493"}
    ]
    _b, _row, job = _commit_one_seeded(db_session, users, parsed, "TESTIMP2B03")
    # Neutral, non-scary labels in the notes blob (no "Misfiled" wording).
    assert "Imported source note — MSB/SB PICS IN FILE?: DONT CALL PLEASE" in job.notes
    assert "Imported review note — Customer Name: Jemena Approval # 000413493" in job.notes
    assert "Misfiled" not in job.notes
    # Review notes carried through to structured Job.details verbatim.
    assert job.details["notes"]["review_notes"][0]["text"] == "Jemena Approval # 000413493"
    assert "Legacy — solar_vic: 100" in job.notes
    # Without a populated legacy section, no Legacy line appears.
    p2 = _details_parsed()
    p2["details"] = dict(p2["details"]); p2["details"].pop("legacy")
    _b2, _r2, job2 = _commit_one_seeded(db_session, users, p2, "TESTIMP2B04")
    assert "Legacy —" not in (job2.notes or "")


def test_commit_fallback_builds_details_when_absent(users, db_session: Session):
    # Staged before Phase 2a -> parsed has no "details"; commit must still write it.
    parsed = {
        "customer_name": "Pat Lee", "sale_date": "01/06/2025", "address": "1 Test St",
        "no_of_panels": "16", "panel_raw": "Longi 440",
    }
    _b, _row, job = _commit_one_seeded(db_session, users, parsed, "TESTIMP2B05")
    assert job.details is not None and job.details["_v"] == 2
    assert job.details["system"]["panel_count"] == 16
    assert job.system_details and "Panels: 16" in job.system_details


# --------------------------------------------------------------------------- #
# Phase L3: import auto-label assignment on commit
# --------------------------------------------------------------------------- #
def _label_keys(db, job) -> list[str]:
    return [a.label.key for a in job_labels_service.list_job_labels(db, job.id)]


def test_commit_auto_assigns_approval_approved_label(users, db_session: Session):
    # _details_parsed defaults to approval_state="approved".
    _b, _row, job = _commit_one_seeded(db_session, users, _details_parsed(), "TESTIMPL3A")
    assigns = job_labels_service.list_job_labels(db_session, job.id)
    keys = [a.label.key for a in assigns]
    assert "approval_approved" in keys
    # source is import_auto, attributed to the commit operator (admin).
    appr = next(a for a in assigns if a.label.key == "approval_approved")
    assert appr.source == JobLabelSource.IMPORT_AUTO
    assert appr.assigned_by_id == users["admin"].id


def test_commit_auto_assigns_approval_pending_label(users, db_session: Session):
    parsed = _details_parsed(approval_state="pending", approval_pending_date="01/07/2025")
    parsed["details"] = {**parsed["details"], "flags": {}}  # isolate the approval label
    _b, _row, job = _commit_one_seeded(db_session, users, parsed, "TESTIMPL3B")
    assigns = job_labels_service.list_job_labels(db_session, job.id)
    keys = [a.label.key for a in assigns]
    assert keys == ["approval_pending"]
    assert assigns[0].note == "pending 01/07/2025"  # pending date carried as a note


def test_commit_auto_assigns_decommission_label(users, db_session: Session):
    # _details_parsed defaults to details.flags.removes_old_system = True.
    parsed = _details_parsed(approval_state="none")
    _b, _row, job = _commit_one_seeded(db_session, users, parsed, "TESTIMPL3C")
    assigns = job_labels_service.list_job_labels(db_session, job.id)
    keys = [a.label.key for a in assigns]
    assert keys == ["decommission_pre_existing"]
    # decommission marker carried as the note.
    assert assigns[0].note == "REMOVE OLD SYSTEM"


def test_commit_assigns_no_labels_when_no_states(users, db_session: Session):
    parsed = _details_parsed(approval_state="none")
    parsed["details"] = dict(parsed["details"])
    parsed["details"].pop("flags", None)
    _b, _row, job = _commit_one_seeded(db_session, users, parsed, "TESTIMPL3D")
    assert job_labels_service.list_job_labels(db_session, job.id) == []


# --------------------------------------------------------------------------- #
# Phase L4: "Needs approval" auto-label (numeric panels + inverter + no approval)
# --------------------------------------------------------------------------- #
def test_auto_label_keys_approval_required_rule():
    # Pure unit contract for the new rule + its exclusions.
    from app.services.job_labels import auto_label_keys
    none = {"approval_state": "none"}
    sysd = lambda **s: {"_v": 2, "system": s}
    # numeric panels > 0 AND inverter present -> approval_required.
    assert ("approval_required", None) in auto_label_keys(none, sysd(panel_count=10, inverter="Goodwe 5kw"))
    # no inverter -> NOT required.
    assert auto_label_keys(none, sysd(panel_count=10)) == []
    # battery-only / inverter-only (no numeric panel_count) + inverter -> NOT required.
    assert auto_label_keys(none, sysd(inverter="Goodwe 5kw")) == []
    # zero / non-numeric panels -> NOT required.
    assert auto_label_keys(none, sysd(panel_count=0, inverter="Goodwe 5kw")) == []
    assert auto_label_keys(none, sysd(panel_count="existing", inverter="Goodwe 5kw")) == []
    # already approved / pending WIN — never downgraded to required.
    assert auto_label_keys({"approval_state": "approved"}, sysd(panel_count=10, inverter="x")) == [("approval_approved", None)]
    assert auto_label_keys({"approval_state": "pending"}, sysd(panel_count=10, inverter="x")) == [("approval_pending", None)]


def _system_only_parsed(*, panel_count, inverter, approval_state="none"):
    """A committable row isolated to the approval-required rule: no decommission
    flag, no approval evidence, only the system fields under test."""
    p = _details_parsed(approval_state=approval_state)
    system: dict = {}
    if panel_count is not None:
        system["panel_count"] = panel_count
    if inverter is not None:
        system["inverter"] = inverter
    p["details"] = {**p["details"], "system": system, "flags": {}}
    return p


def test_commit_auto_assigns_approval_required(users, db_session: Session):
    # numeric panels > 0 + inverter present + no approval -> approval_required.
    parsed = _system_only_parsed(panel_count=16, inverter="Goodwe 5kw")
    _b, _row, job = _commit_one_seeded(db_session, users, parsed, "TESTIMPL4A")
    keys = _label_keys(db_session, job)
    assert keys == ["approval_required"]
    appr = next(a for a in job_labels_service.list_job_labels(db_session, job.id) if a.label.key == "approval_required")
    assert appr.source == JobLabelSource.IMPORT_AUTO


def test_commit_no_required_without_inverter(users, db_session: Session):
    parsed = _system_only_parsed(panel_count=16, inverter=None)
    _b, _row, job = _commit_one_seeded(db_session, users, parsed, "TESTIMPL4B")
    assert _label_keys(db_session, job) == []


def test_commit_no_required_battery_or_inverter_only(users, db_session: Session):
    # No numeric panel_count (battery-only / inverter-only) -> never required.
    parsed = _system_only_parsed(panel_count=None, inverter="Goodwe 5kw")
    _b, _row, job = _commit_one_seeded(db_session, users, parsed, "TESTIMPL4C")
    assert _label_keys(db_session, job) == []


def test_commit_no_required_zero_panels(users, db_session: Session):
    parsed = _system_only_parsed(panel_count=0, inverter="Goodwe 5kw")
    _b, _row, job = _commit_one_seeded(db_session, users, parsed, "TESTIMPL4D")
    assert _label_keys(db_session, job) == []


def test_commit_approved_pending_win_over_required(users, db_session: Session):
    # An already approved / pending job keeps that state, never approval_required.
    p_app = _system_only_parsed(panel_count=16, inverter="Goodwe 5kw", approval_state="approved")
    _b, _r, job = _commit_one_seeded(db_session, users, p_app, "TESTIMPL4E")
    assert _label_keys(db_session, job) == ["approval_approved"]
    p_pend = _system_only_parsed(panel_count=16, inverter="Goodwe 5kw", approval_state="pending")
    p_pend["approval_pending_date"] = "01/07/2025"
    _b2, _r2, job2 = _commit_one_seeded(db_session, users, p_pend, "TESTIMPL4F")
    assert _label_keys(db_session, job2) == ["approval_pending"]


def test_commit_seeds_internal_notes_from_all_preserved_context(users, db_session: Session):
    # P2 safety net: USEFUL preserved context (name-cell note + stripped Lot/DP
    # descriptor) seeds Job.internal_notes on commit under the new heading and with
    # NO source-column labels; the stripped approval reference is EXCLUDED.
    parsed = _details_parsed()
    parsed["details"] = dict(parsed["details"])
    parsed["details"]["notes"] = {
        "customer_name_notes": "includes hot water timer",
        "review_notes": [{"source_column": "Customer Name", "text": "Jemena Approval # 000413493"}],
        "misfiled": [{"source_column": "Customer Name", "text": "Lot 4 DP 588479"}],
    }
    _b, _row, job = _commit_one_seeded(db_session, users, parsed, "TESTIMPSN1")
    assert job.internal_notes.startswith("Uncategorised Data on Import")
    assert "- includes hot water timer" in job.internal_notes     # name-cell note, no label
    assert "- Lot 4 DP 588479" in job.internal_notes              # stripped Lot/DP, no label
    assert "Jemena Approval # 000413493" not in job.internal_notes  # approval reference EXCLUDED
    assert "Customer Name:" not in job.internal_notes              # source labels dropped


def test_commit_leaves_internal_notes_blank_when_no_preserved_context(users, db_session: Session):
    parsed = _details_parsed()
    parsed["details"] = dict(parsed["details"])
    parsed["details"]["notes"] = {}  # nothing stripped/diverted -> nothing to seed
    _b, _row, job = _commit_one_seeded(db_session, users, parsed, "TESTIMPSN2")
    assert not (job.internal_notes or "").strip()


def test_seed_internal_notes_only_when_blank_never_overwrites_manual(db_session: Session):
    from types import SimpleNamespace

    # Useful (non-approval) preserved context so seeding actually produces a note.
    details = {"_v": 2, "notes": {
        "misfiled": [{"source_column": "Customer Name", "text": "Lot 4 DP 588479"}],
    }}
    # blank -> seeded
    j = SimpleNamespace(internal_notes=None, details=details)
    import_commit.seed_internal_notes(j)
    assert j.internal_notes and "Lot 4 DP 588479" in j.internal_notes
    # a manual note is NEVER overwritten
    j2 = SimpleNamespace(internal_notes="MANUAL: call before 9am", details=details)
    import_commit.seed_internal_notes(j2)
    assert j2.internal_notes == "MANUAL: call before 9am"
    # blank but nothing useful preserved (only an excluded approval reference) -> stays None
    j3 = SimpleNamespace(internal_notes=None, details={"_v": 2, "notes": {
        "review_notes": [{"source_column": "Customer Name", "text": "Jemena Approval # 000413493"}],
    }})
    import_commit.seed_internal_notes(j3)
    assert j3.internal_notes is None


def test_commit_auto_label_idempotent(users, db_session: Session):
    # The default row yields approval_approved + decommission_pre_existing, each once.
    _b, _row, job = _commit_one_seeded(db_session, users, _details_parsed(), "TESTIMPL3E")
    keys = _label_keys(db_session, job)
    assert sorted(keys) == ["approval_approved", "decommission_pre_existing"]
    assert len(keys) == len(set(keys))  # no duplicates
    # re-assigning an already-present label is a no-op (returns the existing row).
    before = len(job_labels_service.list_job_labels(db_session, job.id))
    job_labels_service.assign_label_by_key(
        db_session, job_id=job.id, key="approval_approved", source=JobLabelSource.IMPORT_AUTO
    )
    after = len(job_labels_service.list_job_labels(db_session, job.id))
    assert before == after == 2
