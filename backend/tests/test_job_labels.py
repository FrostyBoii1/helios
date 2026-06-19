"""Phase L1 tests: Job label definitions + assignments foundation (read-only).

Covers the migration-seeded catalogue, uniqueness, stable-ordered read API, a
job's (empty) labels, soft-delete exclusion, an assignment round-trip, and that
reads require auth but are open to any authenticated role.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.main import app
from app.models.activity import Activity
from app.models.enums import ActivityType, JobLabelCategory, JobLabelSource, JobStatus
from app.models.job import Job
from app.models.job_label import JobLabelAssignment, JobLabelDefinition
from app.services import job_labels as svc

EXPECTED_KEYS = [
    "approval_required",
    "approval_approved",
    "approval_pending",
    "decommission_pre_existing",
    "needs_maintenance",
    "admin_work_required",
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
    # approval (incl. the new "Needs approval") + decommission presets are system
    # (locked) AND auto-assignable.
    for k in ("approval_required", "approval_approved", "approval_pending", "decommission_pre_existing"):
        assert by_key[k].is_system is True and by_key[k].is_auto is True, k
    assert by_key["approval_required"].name == "Needs approval"
    assert by_key["approval_required"].category == JobLabelCategory.APPROVAL
    assert by_key["approval_approved"].category == JobLabelCategory.APPROVAL
    assert by_key["decommission_pre_existing"].category == JobLabelCategory.SYSTEM
    # operational presets are user-manageable (not system / not auto). warranty_issue
    # was rekeyed to admin_work_required ("Admin work required").
    for k in ("needs_maintenance", "admin_work_required", "battery_only", "existing_solar", "awaiting_documents"):
        assert by_key[k].is_system is False and by_key[k].is_auto is False, k
        assert by_key[k].category == JobLabelCategory.OPERATIONAL, k
    assert by_key["admin_work_required"].name == "Admin work required"
    assert "warranty_issue" not in by_key  # rekeyed, not duplicated


def test_label_keys_unique(db_session: Session):
    keys = [d.key for d in svc.list_label_definitions(db_session)]
    assert len(keys) == len(set(keys))


def test_label_key_duplicate_rejected(db_session: Session):
    """The DB enforces unique label keys (a unique constraint before the drift
    reconcile, a single UNIQUE index after) — inserting a second definition with an
    existing key must fail. Protects the uniqueness invariant across the migration."""
    existing = svc.list_label_definitions(db_session)[0].key
    sp = db_session.begin_nested()  # contain the integrity failure to a savepoint
    db_session.add(JobLabelDefinition(key=existing, name="Dup", category=JobLabelCategory.CUSTOM))
    with pytest.raises(IntegrityError):
        db_session.flush()
    sp.rollback()


def test_get_definitions_returns_seeded_in_stable_order(client_for, users):
    resp = client_for(users["admin"]).get("/api/v1/job-labels")
    assert resp.status_code == 200
    data = resp.json()
    keys = [d["key"] for d in data]
    for k in EXPECTED_KEYS:
        assert k in keys
    # stable order: non-decreasing sort_order, and the approval + decommission
    # system presets first (Needs approval leads the approval lifecycle).
    sort_orders = [d["sort_order"] for d in data]
    assert sort_orders == sorted(sort_orders)
    assert keys[:4] == [
        "approval_required", "approval_approved", "approval_pending", "decommission_pre_existing",
    ]


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


# --------------------------------------------------------------------------- #
# Phase L2: add / remove (write endpoints, permissions, system-lock, activity)
# --------------------------------------------------------------------------- #
def _add(client, job_id: int, key: str):
    return client.post(f"/api/v1/jobs/{job_id}/labels", json={"key": key})


def _label_count(db, job_id, kind):
    return (
        db.query(Activity)
        .filter(Activity.job_id == job_id, Activity.activity_type == kind.value)
        .count()
    )


def test_add_operational_label(db_session, client_for, users, customer):
    job = _make_job(db_session, customer.id)
    resp = _add(client_for(users["admin"]), job.id, "needs_maintenance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["label"]["key"] == "needs_maintenance"
    assert body["source"] == "manual" and body["assigned_by_id"] == users["admin"].id
    assert [a.label.key for a in svc.list_job_labels(db_session, job.id)] == ["needs_maintenance"]
    assert _label_count(db_session, job.id, ActivityType.JOB_LABEL_ADDED) == 1


def test_add_label_idempotent_no_duplicate(db_session, client_for, users, customer):
    job = _make_job(db_session, customer.id)
    admin = client_for(users["admin"])
    assert _add(admin, job.id, "admin_work_required").status_code == 200
    assert _add(admin, job.id, "admin_work_required").status_code == 200  # no-op
    assert [a.label.key for a in svc.list_job_labels(db_session, job.id)] == ["admin_work_required"]
    # the idempotent re-add logs no second activity
    assert _label_count(db_session, job.id, ActivityType.JOB_LABEL_ADDED) == 1


def test_remove_operational_label(db_session, client_for, users, customer):
    job = _make_job(db_session, customer.id)
    admin = client_for(users["admin"])
    _add(admin, job.id, "battery_only")
    resp = admin.delete(f"/api/v1/jobs/{job.id}/labels/battery_only")
    assert resp.status_code == 204
    assert svc.list_job_labels(db_session, job.id) == []
    assert _label_count(db_session, job.id, ActivityType.JOB_LABEL_REMOVED) == 1


def test_remove_unassigned_label_404(db_session, client_for, users, customer):
    job = _make_job(db_session, customer.id)
    resp = client_for(users["admin"]).delete(f"/api/v1/jobs/{job.id}/labels/battery_only")
    assert resp.status_code == 404


def test_add_system_label_blocked(db_session, client_for, users, customer):
    job = _make_job(db_session, customer.id)
    resp = _add(client_for(users["admin"]), job.id, "approval_approved")
    assert resp.status_code == 403
    assert svc.list_job_labels(db_session, job.id) == []


def test_remove_system_label_blocked(db_session, client_for, users, customer):
    job = _make_job(db_session, customer.id)
    # simulate an import auto-assigned system label
    svc.assign_label_by_key(
        db_session, job_id=job.id, key="decommission_pre_existing", source=JobLabelSource.IMPORT_AUTO
    )
    db_session.flush()
    resp = client_for(users["admin"]).delete(f"/api/v1/jobs/{job.id}/labels/decommission_pre_existing")
    assert resp.status_code == 403
    assert "decommission_pre_existing" in [a.label.key for a in svc.list_job_labels(db_session, job.id)]


def test_label_manage_permission_enforced(db_session, client_for, users, customer):
    # support is in the manage set -> may add operational labels.
    job = _make_job(db_session, customer.id)
    assert _add(client_for(users["support"]), job.id, "awaiting_documents").status_code == 200
    # approvals is NOT in the manage set -> 403.
    job2 = _make_job(db_session, customer.id)
    assert _add(client_for(users["approvals"]), job2.id, "needs_maintenance").status_code == 403


# --------------------------------------------------------------------------- #
# Slice 2: dedicated approval control (PUT /jobs/{id}/approval) — label-is-law
# --------------------------------------------------------------------------- #
def _approval(client, job_id: int, state: str, pending_date=None):
    body: dict = {"state": state}
    if pending_date is not None:
        body["pending_date"] = pending_date
    return client.put(f"/api/v1/jobs/{job_id}/approval", json=body)


def _approval_keys(db, job_id: int) -> list[str]:
    return [a.label.key for a in svc.list_job_labels(db, job_id) if a.label.key.startswith("approval_")]


def test_approval_control_approved(db_session, client_for, users, customer):
    job = _make_job(db_session, customer.id)
    resp = _approval(client_for(users["approvals"]), job.id, "approved")
    assert resp.status_code == 200
    assert resp.json() == {"state": "approved", "pending_date": None}
    assert _approval_keys(db_session, job.id) == ["approval_approved"]


def test_approval_control_pending_with_date(db_session, client_for, users, customer):
    job = _make_job(db_session, customer.id)
    resp = _approval(client_for(users["admin"]), job.id, "pending", "19/08/2026")
    assert resp.status_code == 200
    assert resp.json() == {"state": "pending", "pending_date": "19/08/2026"}
    assert _approval_keys(db_session, job.id) == ["approval_pending"]
    fresh = db_session.get(Job, job.id)
    assert (fresh.details or {}).get("approval", {}).get("pending_date") == "19/08/2026"


def test_approval_control_none_clears_labels_and_date(db_session, client_for, users, customer):
    job = _make_job(db_session, customer.id)
    admin = client_for(users["admin"])
    _approval(admin, job.id, "pending", "01/01/2026")
    resp = _approval(admin, job.id, "none")
    assert resp.status_code == 200 and resp.json() == {"state": "none", "pending_date": None}
    assert _approval_keys(db_session, job.id) == []
    assert "approval" not in (db_session.get(Job, job.id).details or {})


def test_approval_control_switch_replaces_label_exactly_one(db_session, client_for, users, customer):
    job = _make_job(db_session, customer.id)
    admin = client_for(users["admin"])
    _approval(admin, job.id, "pending", "01/01/2026")
    assert _approval_keys(db_session, job.id) == ["approval_pending"]
    _approval(admin, job.id, "approved")
    # exactly one approval label (the new one); pending date cleared on approve.
    assert _approval_keys(db_session, job.id) == ["approval_approved"]
    assert "approval" not in (db_session.get(Job, job.id).details or {})


def test_approval_control_idempotent(db_session, client_for, users, customer):
    job = _make_job(db_session, customer.id)
    admin = client_for(users["admin"])
    _approval(admin, job.id, "approved")
    _approval(admin, job.id, "approved")  # no-op, still exactly one
    assert _approval_keys(db_session, job.id) == ["approval_approved"]


def test_approval_control_required(db_session, client_for, users, customer):
    # "required" -> exactly one approval label (approval_required), no pending date.
    job = _make_job(db_session, customer.id)
    resp = _approval(client_for(users["approvals"]), job.id, "required")
    assert resp.status_code == 200
    assert resp.json() == {"state": "required", "pending_date": None}
    assert _approval_keys(db_session, job.id) == ["approval_required"]
    assert "approval" not in (db_session.get(Job, job.id).details or {})  # no date stored


def test_approval_control_full_lifecycle_exactly_one(db_session, client_for, users, customer):
    # required -> pending -> approved -> none: ALWAYS exactly one approval label
    # (or zero), stale labels removed at each step; pending date only while pending.
    job = _make_job(db_session, customer.id)
    admin = client_for(users["admin"])
    _approval(admin, job.id, "required")
    assert _approval_keys(db_session, job.id) == ["approval_required"]
    _approval(admin, job.id, "pending", "19/08/2026")
    assert _approval_keys(db_session, job.id) == ["approval_pending"]  # required removed
    assert (db_session.get(Job, job.id).details or {}).get("approval", {}).get("pending_date") == "19/08/2026"
    _approval(admin, job.id, "approved")
    assert _approval_keys(db_session, job.id) == ["approval_approved"]  # pending removed + date cleared
    assert "approval" not in (db_session.get(Job, job.id).details or {})
    _approval(admin, job.id, "none")
    assert _approval_keys(db_session, job.id) == []


def test_get_job_approval_returns_required(db_session, customer):
    # The service derives "required" from the approval_required label.
    job = _make_job(db_session, customer.id)
    svc.set_job_approval(db_session, job=job, state="required", pending_date=None, assigned_by_id=None)
    assert svc.get_job_approval(db_session, job)["state"] == "required"


def test_approval_required_not_casually_removable(db_session, client_for, users, customer):
    # approval_required is system-locked: the casual chip DELETE refuses it.
    job = _make_job(db_session, customer.id)
    _approval(client_for(users["admin"]), job.id, "required")
    resp = client_for(users["admin"]).delete(f"/api/v1/jobs/{job.id}/labels/approval_required")
    assert resp.status_code == 403
    assert _approval_keys(db_session, job.id) == ["approval_required"]


def test_approval_control_permission(db_session, client_for, users, customer):
    job = _make_job(db_session, customer.id)
    assert _approval(client_for(users["scheduling"]), job.id, "approved").status_code == 403
    assert _approval(client_for(users["support"]), job.id, "approved").status_code == 403
    assert _approval(client_for(users["sales"]), job.id, "approved").status_code == 200


def test_approval_label_not_casually_removable(db_session, client_for, users, customer):
    # The approval label is set via the control, and the casual chip DELETE refuses
    # it (system lock) — so a job's approval state can't be silently dropped.
    job = _make_job(db_session, customer.id)
    _approval(client_for(users["admin"]), job.id, "approved")
    resp = client_for(users["admin"]).delete(f"/api/v1/jobs/{job.id}/labels/approval_approved")
    assert resp.status_code == 403
    assert _approval_keys(db_session, job.id) == ["approval_approved"]
