"""Phase 4b tests: path-restricted live Job.details write + blob re-derivation.

Synthetic data only (rollback-isolated db_session). Covers: deep-merge + sibling
preservation, system_details/install_details re-rendering from details (D1),
disallowed-path / null / non-dict rejection (422), the NULL-details guard (D2),
legacy blob edits leaving details untouched, details winning over a direct blob
edit in the same payload (D5), and the descriptive permission gate (D3).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.enums import JobStatus
from app.models.job import Job
from app.services.import_details import render_structured_blobs


def _details() -> dict:
    return {
        "_v": 2,
        "sales": {"salesperson_text": "Jordan Avery"},
        "system": {"panel_count": 16, "panel": "JinkoSolar 440W", "phase": "single"},
        "electrical": {"nmi": "6203111234", "meter_no": "M12345"},
        "install": {"day": "Tuesday", "time": "9:00 AM"},
        "payment": {"total": "8500"},
        "compliance": {"msb_status": "yes"},
        "flags": {"removes_old_system": False},
        "provenance": "synthetic 4b",
    }


def _make_job(db: Session, customer: Customer, *, case_number: str, details: dict | None) -> Job:
    job = Job(
        case_number=case_number,
        customer_id=customer.id,
        status=JobStatus.INSTALLED,
        title="TEST 4b job",
        details=details,
        system_details="STALE system",
        install_details="STALE install",
        approval_details="Approval: approved",
        notes="legacy notes blob",
    )
    db.add(job)
    db.flush()
    return job


# --------------------------------------------------------------------------- #
# Merge + re-derivation
# --------------------------------------------------------------------------- #
def test_details_patch_merges_and_rederives_blobs(client_for, users, customer, db_session):
    job = _make_job(db_session, customer, case_number="TEST-4B-0001", details=_details())
    admin = client_for(users["admin"])

    r = admin.patch(
        f"/api/v1/jobs/{job.id}",
        json={"details": {"system": {"panel_count": 18}, "install": {"day": "Wednesday"}}},
    )
    assert r.status_code == 200, r.text

    db_session.refresh(job)
    # Patched leaves applied; siblings preserved.
    assert job.details["system"]["panel_count"] == 18
    assert job.details["system"]["panel"] == "JinkoSolar 440W"
    assert job.details["system"]["phase"] == "single"
    assert job.details["install"]["day"] == "Wednesday"
    assert job.details["install"]["time"] == "9:00 AM"
    assert job.details["sales"]["salesperson_text"] == "Jordan Avery"
    # system_details / install_details re-rendered from the merged details (not STALE).
    expect = render_structured_blobs(job.details)
    assert job.system_details == expect["system_details"]
    assert job.install_details == expect["install_details"]
    assert "Panels: 18" in job.system_details
    assert "Day: Wednesday" in job.install_details
    # approval_details + notes left untouched (D1).
    assert job.approval_details == "Approval: approved"
    assert job.notes == "legacy notes blob"


def test_disallowed_paths_reject_422_and_leave_job_unchanged(client_for, users, customer, db_session):
    job = _make_job(db_session, customer, case_number="TEST-4B-0002", details=_details())
    admin = client_for(users["admin"])
    before = dict(job.details)

    for patch in (
        {"system": {"evil": "x"}},          # unknown key
        {"nope": {"panel_count": 1}},        # unknown section
        {"flags": {"removes_old_system": True}},  # derived/read-only
        {"provenance": "tampered"},          # read-only
        {"notes": {"misfiled": [{"text": "x"}]}},  # read-only
    ):
        r = admin.patch(f"/api/v1/jobs/{job.id}", json={"details": patch})
        assert r.status_code == 422, (patch, r.text)

    db_session.refresh(job)
    assert job.details == before
    assert job.system_details == "STALE system"  # never re-rendered on rejection


def test_patch_on_null_details_job_rejected_422(client_for, users, customer, db_session):
    job = _make_job(db_session, customer, case_number="TEST-4B-0003", details=None)
    admin = client_for(users["admin"])

    r = admin.patch(f"/api/v1/jobs/{job.id}", json={"details": {"system": {"panel_count": 18}}})
    assert r.status_code == 422, r.text
    db_session.refresh(job)
    assert job.details is None
    assert job.system_details == "STALE system"


def test_null_or_nondict_details_rejected_422(client_for, users, customer, db_session):
    job = _make_job(db_session, customer, case_number="TEST-4B-0004", details=_details())
    admin = client_for(users["admin"])
    before = dict(job.details)

    # Explicit null details -> patch-not-replacement guard -> 422.
    assert admin.patch(f"/api/v1/jobs/{job.id}", json={"details": None}).status_code == 422
    # Non-dict details -> rejected (schema or service) -> 422.
    assert admin.patch(f"/api/v1/jobs/{job.id}", json={"details": "x"}).status_code == 422

    db_session.refresh(job)
    assert job.details == before


def test_legacy_blob_edit_preserves_details(client_for, users, customer, db_session):
    job = _make_job(db_session, customer, case_number="TEST-4B-0005", details=_details())
    admin = client_for(users["admin"])
    before = dict(job.details)

    r = admin.patch(
        f"/api/v1/jobs/{job.id}",
        json={"approval_details": "Approval: rejected", "notes": "updated note"},
    )
    assert r.status_code == 200, r.text

    db_session.refresh(job)
    assert job.approval_details == "Approval: rejected"
    assert job.notes == "updated note"
    # No details key in the payload -> details + re-derived blobs untouched.
    assert job.details == before
    assert job.system_details == "STALE system"
    assert job.install_details == "STALE install"


def test_details_rederive_wins_over_direct_blob_edit(client_for, users, customer, db_session):
    job = _make_job(db_session, customer, case_number="TEST-4B-0006", details=_details())
    admin = client_for(users["admin"])

    r = admin.patch(
        f"/api/v1/jobs/{job.id}",
        json={"system_details": "DIRECT OVERRIDE", "details": {"system": {"panel_count": 20}}},
    )
    assert r.status_code == 200, r.text

    db_session.refresh(job)
    # D5: re-derivation from the merged details wins over the direct edit.
    expect = render_structured_blobs(job.details)
    assert job.system_details == expect["system_details"]
    assert job.system_details != "DIRECT OVERRIDE"
    assert "Panels: 20" in job.system_details


# --------------------------------------------------------------------------- #
# Permissions (D3): a details patch is a descriptive change.
# --------------------------------------------------------------------------- #
def test_details_patch_permissions(client_for, users, customer, db_session):
    job = _make_job(db_session, customer, case_number="TEST-4B-0007", details=_details())
    patch = {"details": {"system": {"panel_count": 21}}}

    assert client_for(users["admin"]).patch(f"/api/v1/jobs/{job.id}", json=patch).status_code == 200
    assert client_for(users["sales"]).patch(f"/api/v1/jobs/{job.id}", json=patch).status_code == 200

    # support is read-only; scheduling may only touch install_date -> 403 for details.
    before = dict((db_session.refresh(job), job.details)[1])
    assert client_for(users["support"]).patch(f"/api/v1/jobs/{job.id}", json=patch).status_code == 403
    assert client_for(users["scheduling"]).patch(f"/api/v1/jobs/{job.id}", json=patch).status_code == 403
    db_session.refresh(job)
    assert job.details == before  # forbidden patches changed nothing
