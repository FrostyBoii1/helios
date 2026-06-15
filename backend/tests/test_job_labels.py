"""Phase L1 tests: Job label definitions + assignments foundation (read-only).

Covers the migration-seeded catalogue, uniqueness, stable-ordered read API, a
job's (empty) labels, soft-delete exclusion, an assignment round-trip, and that
reads require auth but are open to any authenticated role.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.main import app
from app.models.enums import JobLabelCategory, JobLabelSource, JobStatus
from app.models.job import Job
from app.models.job_label import JobLabelAssignment, JobLabelDefinition
from app.services import job_labels as svc

EXPECTED_KEYS = [
    "approval_approved",
    "approval_pending",
    "decommission_pre_existing",
    "needs_maintenance",
    "warranty_issue",
    "battery_only",
    "existing_solar",
    "awaiting_documents",
]

_JOB_SEQ = iter(range(1, 10_000))


def _make_job(db: Session, customer_id: int) -> Job:
    job = Job(
        case_number=f"SCS-TEST-L1-{next(_JOB_SEQ):04d}",
        customer_id=customer_id,
        status=JobStatus.INSTALLED,
    )
    db.add(job)
    db.flush()
    return job


# --------------------------------------------------------------------------- #
# Migration seed + catalogue
# --------------------------------------------------------------------------- #
def test_migration_seeded_default_labels_exist(db_session: Session):
    defs = svc.list_label_definitions(db_session)
    by_key = {d.key: d for d in defs}
    for k in EXPECTED_KEYS:
        assert k in by_key, k
    # approval + decommission presets are system (locked) AND auto-assignable.
    for k in ("approval_approved", "approval_pending", "decommission_pre_existing"):
        assert by_key[k].is_system is True and by_key[k].is_auto is True, k
    assert by_key["approval_approved"].category == JobLabelCategory.APPROVAL
    assert by_key["decommission_pre_existing"].category == JobLabelCategory.SYSTEM
    # operational presets are user-manageable (not system / not auto).
    for k in ("needs_maintenance", "warranty_issue", "battery_only", "existing_solar", "awaiting_documents"):
        assert by_key[k].is_system is False and by_key[k].is_auto is False, k
        assert by_key[k].category == JobLabelCategory.OPERATIONAL, k


def test_label_keys_unique(db_session: Session):
    keys = [d.key for d in svc.list_label_definitions(db_session)]
    assert len(keys) == len(set(keys))


def test_get_definitions_returns_seeded_in_stable_order(client_for, users):
    resp = client_for(users["admin"]).get("/api/v1/job-labels")
    assert resp.status_code == 200
    data = resp.json()
    keys = [d["key"] for d in data]
    for k in EXPECTED_KEYS:
        assert k in keys
    # stable order: non-decreasing sort_order, and the three system presets first.
    sort_orders = [d["sort_order"] for d in data]
    assert sort_orders == sorted(sort_orders)
    assert keys[:3] == ["approval_approved", "approval_pending", "decommission_pre_existing"]


# --------------------------------------------------------------------------- #
# Per-job labels
# --------------------------------------------------------------------------- #
def test_get_job_labels_empty_for_unlabeled_job(db_session, client_for, users, customer):
    job = _make_job(db_session, customer.id)
    resp = client_for(users["admin"]).get(f"/api/v1/jobs/{job.id}/labels")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_job_labels_404_for_missing_job(client_for, users):
    resp = client_for(users["admin"]).get("/api/v1/jobs/999999999/labels")
    assert resp.status_code == 404


def test_assignment_appears_in_job_labels(db_session, customer):
    job = _make_job(db_session, customer.id)
    label = svc.get_label_by_key(db_session, "decommission_pre_existing")
    assert label is not None
    db_session.add(
        JobLabelAssignment(
            job_id=job.id, label_id=label.id,
            source=JobLabelSource.IMPORT_AUTO, note="REMOVE OLD SYSTEM",
        )
    )
    db_session.flush()
    labels = svc.list_job_labels(db_session, job.id)
    assert len(labels) == 1
    assert labels[0].label.key == "decommission_pre_existing"
    assert labels[0].source == JobLabelSource.IMPORT_AUTO
    assert labels[0].note == "REMOVE OLD SYSTEM"


# --------------------------------------------------------------------------- #
# Soft delete
# --------------------------------------------------------------------------- #
def test_soft_deleted_label_excluded(db_session: Session):
    label = JobLabelDefinition(
        key="temp_l1_test_label", name="Temp", category=JobLabelCategory.CUSTOM,
        color="slate", is_system=False, is_auto=False, sort_order=999,
    )
    db_session.add(label)
    db_session.flush()
    assert any(d.key == "temp_l1_test_label" for d in svc.list_label_definitions(db_session))
    # soft-delete -> excluded from the default listing, still visible when asked.
    label.deleted_at = datetime.now(timezone.utc)
    db_session.flush()
    assert not any(d.key == "temp_l1_test_label" for d in svc.list_label_definitions(db_session))
    assert any(
        d.key == "temp_l1_test_label"
        for d in svc.list_label_definitions(db_session, include_deleted=True)
    )
    assert svc.get_label_by_key(db_session, "temp_l1_test_label") is None


# --------------------------------------------------------------------------- #
# Auth / permissions (read = any authenticated user; auth required)
# --------------------------------------------------------------------------- #
def test_any_authenticated_role_can_read(db_session, client_for, users, customer):
    support = client_for(users["support"])  # lowest-privilege role
    assert support.get("/api/v1/job-labels").status_code == 200
    job = _make_job(db_session, customer.id)
    assert support.get(f"/api/v1/jobs/{job.id}/labels").status_code == 200


def test_read_requires_authentication(db_session: Session):
    # A client WITHOUT the get_current_user override hits the real auth guard.
    app.dependency_overrides[get_db] = lambda: iter([db_session])
    try:
        client = TestClient(app)
        assert client.get("/api/v1/job-labels").status_code == 401
    finally:
        app.dependency_overrides.clear()
