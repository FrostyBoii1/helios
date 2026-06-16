"""Database-backed integration tests for the Jobs API.

Covers create (case numbers), list/filter/search, get, update, install-date
behavior, status change, soft delete, activity logging, and the permission
matrix. Each test runs in a rolled-back transaction.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.enums import ActivityType
from app.models.job import Job

# SCS-YYYY-NNNNN, e.g. SCS-2026-00001
CASE_NUMBER_RE = re.compile(r"^SCS-\d{4}-\d{5}$")


def _case_suffix(case_number: str) -> int:
    """Parse the numeric sequence suffix from a case number."""
    return int(case_number.rsplit("-", 1)[1])


def _activities(db: Session, job_id: int, activity_type: ActivityType) -> list[Activity]:
    stmt = select(Activity).where(
        Activity.job_id == job_id, Activity.activity_type == activity_type
    )
    return list(db.scalars(stmt).all())


def _create(client, customer_id, **fields):
    return client.post("/api/v1/jobs", json={"customer_id": customer_id, **fields})


# --------------------------------------------------------------------------- #
# Create + case numbers
# --------------------------------------------------------------------------- #
def test_admin_creates_job_with_case_number(client_for, users, customer, db_session):
    client = client_for(users["admin"])
    resp = _create(client, customer.id, title="Solar install")
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "new"
    # Format only — the absolute sequence depends on pre-existing jobs in the DB.
    assert CASE_NUMBER_RE.match(body["case_number"])
    assert body["customer"]["id"] == customer.id

    logged = _activities(db_session, body["id"], ActivityType.JOB_CREATED)
    assert len(logged) == 1
    assert logged[0].customer_id == customer.id


def test_case_numbers_increment(client_for, users, customer):
    client = client_for(users["admin"])
    first = _create(client, customer.id).json()["case_number"]
    second = _create(client, customer.id).json()["case_number"]
    # Both well-formed; the second increments the first by 1 (no absolute value).
    assert CASE_NUMBER_RE.match(first)
    assert CASE_NUMBER_RE.match(second)
    assert _case_suffix(second) == _case_suffix(first) + 1


def test_sales_admin_can_create_job(client_for, users, customer):
    resp = _create(client_for(users["sales"]), customer.id)
    assert resp.status_code == 201


def test_support_cannot_create_job(client_for, users, customer):
    resp = _create(client_for(users["support"]), customer.id)
    assert resp.status_code == 403


def test_create_rejects_missing_customer(client_for, users):
    resp = _create(client_for(users["admin"]), 999999)
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# List / filter / search
# --------------------------------------------------------------------------- #
def test_list_filter_and_search(client_for, users, customer, db_session):
    admin = client_for(users["admin"])
    j1 = _create(admin, customer.id, title="Battery upgrade").json()
    _create(admin, customer.id, title="Panel clean")

    # Another customer with a job, to test customer_id filtering.
    from app.models.customer import Customer

    other = Customer(full_name="Other Co")
    db_session.add(other)
    db_session.flush()
    _create(admin, other.id, title="Other job")

    support = client_for(users["support"])  # read-only role can list
    all_jobs = support.get("/api/v1/jobs").json()
    assert all_jobs["total"] >= 3

    by_customer = support.get("/api/v1/jobs", params={"customer_id": customer.id}).json()
    assert by_customer["total"] == 2
    assert all(j["customer_id"] == customer.id for j in by_customer["items"])

    by_case = support.get("/api/v1/jobs", params={"q": j1["case_number"]}).json()
    assert any(j["id"] == j1["id"] for j in by_case["items"])

    by_title = support.get("/api/v1/jobs", params={"q": "battery"}).json()
    assert any(j["title"] == "Battery upgrade" for j in by_title["items"])


def test_filter_by_status(client_for, users, customer):
    admin = client_for(users["admin"])
    job = _create(admin, customer.id).json()
    admin.post(f"/api/v1/jobs/{job['id']}/status", json={"status": "booked_for_install"})

    booked = admin.get("/api/v1/jobs", params={"status": "booked_for_install"}).json()
    assert any(j["id"] == job["id"] for j in booked["items"])
    new_only = admin.get("/api/v1/jobs", params={"status": "new"}).json()
    assert all(j["id"] != job["id"] for j in new_only["items"])


# --------------------------------------------------------------------------- #
# Section D: Jobs list carries Suburb/State + label chips, and a label filter.
# --------------------------------------------------------------------------- #
def test_list_includes_suburb_state_and_label_chips(client_for, users, customer, db_session):
    admin = client_for(users["admin"])
    customer.state = "VIC"  # fixture has suburb="Testville"; give it a state too
    db_session.flush()
    job = _create(admin, customer.id, title="Roof job").json()
    r = admin.post(f"/api/v1/jobs/{job['id']}/labels", json={"key": "admin_work_required"})
    assert r.status_code == 200, r.text

    row = next(it for it in admin.get("/api/v1/jobs").json()["items"] if it["id"] == job["id"])
    # Suburb/State on the embedded customer ref (the Jobs list column).
    assert row["customer"]["suburb"] == "Testville"
    assert row["customer"]["state"] == "VIC"
    # Lightweight label chips embedded per job (no per-row round-trip).
    chips = {lab["key"]: lab for lab in row["labels"]}
    assert "admin_work_required" in chips
    chip = chips["admin_work_required"]
    assert chip["name"] == "Admin work required"
    assert chip["category"] == "operational"
    assert chip["is_system"] is False
    assert chip.get("color")  # a colour token for chip styling


def test_list_label_filter_single_and_ands_with_status(client_for, users, customer):
    admin = client_for(users["admin"])
    a = _create(admin, customer.id, title="A").json()
    b = _create(admin, customer.id, title="B").json()
    admin.post(f"/api/v1/jobs/{a['id']}/labels", json={"key": "admin_work_required"})
    admin.post(f"/api/v1/jobs/{b['id']}/labels", json={"key": "battery_only"})

    ids = {it["id"] for it in admin.get("/api/v1/jobs", params={"label": "admin_work_required"}).json()["items"]}
    assert a["id"] in ids and b["id"] not in ids
    # Label filter ANDs with status (both jobs are 'new', so completed -> none).
    assert admin.get(
        "/api/v1/jobs", params={"label": "admin_work_required", "status": "completed"}
    ).json()["total"] == 0
    # An unknown label key matches nothing.
    assert admin.get("/api/v1/jobs", params={"label": "no_such_label"}).json()["total"] == 0


# --------------------------------------------------------------------------- #
# Scheduling filters (install-date range + unscheduled)
# --------------------------------------------------------------------------- #
def test_install_date_range_filter(client_for, users, customer):
    admin = client_for(users["admin"])
    july = _create(admin, customer.id).json()
    august = _create(admin, customer.id).json()
    admin.patch(f"/api/v1/jobs/{july['id']}", json={"install_date": "2026-07-10"})
    admin.patch(f"/api/v1/jobs/{august['id']}", json={"install_date": "2026-08-10"})

    in_july = admin.get(
        "/api/v1/jobs",
        params={"install_date_from": "2026-07-01", "install_date_to": "2026-07-31"},
    ).json()
    ids = [j["id"] for j in in_july["items"]]
    assert july["id"] in ids
    assert august["id"] not in ids


def test_unscheduled_filter_excludes_scheduled(client_for, users, customer):
    admin = client_for(users["admin"])
    scheduled = _create(admin, customer.id).json()
    admin.patch(f"/api/v1/jobs/{scheduled['id']}", json={"install_date": "2026-07-10"})
    pending = _create(admin, customer.id).json()  # no install date

    res = admin.get("/api/v1/jobs", params={"unscheduled": "true"}).json()
    ids = [j["id"] for j in res["items"]]
    assert pending["id"] in ids
    assert scheduled["id"] not in ids
    assert all(j["install_date"] is None for j in res["items"])


def test_unscheduled_excludes_completed_and_cancelled(client_for, users, customer):
    admin = client_for(users["admin"])
    done = _create(admin, customer.id).json()
    admin.post(f"/api/v1/jobs/{done['id']}/status", json={"status": "completed"})
    cancelled = _create(admin, customer.id).json()
    admin.post(f"/api/v1/jobs/{cancelled['id']}/status", json={"status": "cancelled"})

    ids = [j["id"] for j in admin.get("/api/v1/jobs", params={"unscheduled": "true"}).json()["items"]]
    assert done["id"] not in ids
    assert cancelled["id"] not in ids


# --------------------------------------------------------------------------- #
# Get
# --------------------------------------------------------------------------- #
def test_get_detail_and_404(client_for, users, customer):
    admin = client_for(users["admin"])
    job = _create(admin, customer.id, title="Detail job").json()
    assert admin.get(f"/api/v1/jobs/{job['id']}").status_code == 200
    assert admin.get("/api/v1/jobs/999999").status_code == 404


# --------------------------------------------------------------------------- #
# Update + install-date behavior
# --------------------------------------------------------------------------- #
def test_descriptive_update_logs_job_updated(client_for, users, customer, db_session):
    admin = client_for(users["admin"])
    job = _create(admin, customer.id).json()
    resp = admin.patch(f"/api/v1/jobs/{job['id']}", json={"title": "Renamed", "notes": "hi"})
    assert resp.status_code == 200
    logged = _activities(db_session, job["id"], ActivityType.JOB_UPDATED)
    assert len(logged) == 1
    assert set(logged[0].meta["changes"]) == {"title", "notes"}


def test_job_internal_notes_round_trip_and_separate_from_notes(client_for, users, customer):
    """Phase A: a job's manual internal_notes round-trips, is permission-gated like
    other descriptive fields, and is independent of the imported `notes` blob."""
    admin = client_for(users["admin"])
    job = _create(admin, customer.id).json()
    assert job["internal_notes"] is None

    resp = admin.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"notes": "imported blob", "internal_notes": "spoke to installer"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["internal_notes"] == "spoke to installer"
    assert body["notes"] == "imported blob"

    # Support role cannot edit descriptive fields (internal_notes included).
    support = client_for(users["support"])
    blocked = support.patch(
        f"/api/v1/jobs/{job['id']}", json={"internal_notes": "nope"}
    )
    assert blocked.status_code == 403


def test_initial_install_date_logs_job_updated(client_for, users, customer, db_session):
    admin = client_for(users["admin"])
    job = _create(admin, customer.id).json()
    resp = admin.patch(f"/api/v1/jobs/{job['id']}", json={"install_date": "2026-07-01"})
    assert resp.status_code == 200
    updated = _activities(db_session, job["id"], ActivityType.JOB_UPDATED)
    assert len(updated) == 1
    assert "install_date" in updated[0].meta["changes"]
    assert _activities(db_session, job["id"], ActivityType.INSTALL_RESCHEDULED) == []


def test_reschedule_logs_install_rescheduled(client_for, users, customer, db_session):
    admin = client_for(users["admin"])
    job = _create(admin, customer.id).json()
    admin.patch(f"/api/v1/jobs/{job['id']}", json={"install_date": "2026-07-01"})
    resp = admin.patch(f"/api/v1/jobs/{job['id']}", json={"install_date": "2026-07-15"})
    assert resp.status_code == 200
    resched = _activities(db_session, job["id"], ActivityType.INSTALL_RESCHEDULED)
    assert len(resched) == 1
    assert resched[0].meta == {"from": "2026-07-01", "to": "2026-07-15"}


def test_scheduling_can_set_install_but_not_descriptive(client_for, users, customer):
    admin = client_for(users["admin"])
    job = _create(admin, customer.id).json()
    sched = client_for(users["scheduling"])
    assert sched.patch(f"/api/v1/jobs/{job['id']}", json={"install_date": "2026-08-01"}).status_code == 200
    assert sched.patch(f"/api/v1/jobs/{job['id']}", json={"title": "Nope"}).status_code == 403


def test_sales_admin_cannot_set_install_date(client_for, users, customer):
    admin = client_for(users["admin"])
    job = _create(admin, customer.id).json()
    sales = client_for(users["sales"])
    # descriptive allowed
    assert sales.patch(f"/api/v1/jobs/{job['id']}", json={"title": "OK"}).status_code == 200
    # install_date forbidden for sales_admin
    assert sales.patch(f"/api/v1/jobs/{job['id']}", json={"install_date": "2026-09-01"}).status_code == 403


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #
def test_status_change_logs_and_approvals_allowed(client_for, users, customer, db_session):
    admin = client_for(users["admin"])
    job = _create(admin, customer.id).json()
    approvals = client_for(users["approvals"])
    resp = approvals.post(f"/api/v1/jobs/{job['id']}/status", json={"status": "awaiting_approval"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "awaiting_approval"
    logged = _activities(db_session, job["id"], ActivityType.JOB_STATUS_CHANGED)
    assert len(logged) == 1
    assert logged[0].meta == {"from": "new", "to": "awaiting_approval"}


def test_support_cannot_change_status(client_for, users, customer):
    admin = client_for(users["admin"])
    job = _create(admin, customer.id).json()
    support = client_for(users["support"])
    resp = support.post(f"/api/v1/jobs/{job['id']}/status", json={"status": "completed"})
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Soft delete
# --------------------------------------------------------------------------- #
def test_admin_soft_delete_excludes_and_logs(client_for, users, customer, db_session):
    admin = client_for(users["admin"])
    job = _create(admin, customer.id).json()
    jid = job["id"]

    assert admin.delete(f"/api/v1/jobs/{jid}").status_code == 204
    assert admin.get(f"/api/v1/jobs/{jid}").status_code == 404
    listed = admin.get("/api/v1/jobs", params={"customer_id": customer.id}).json()
    assert all(j["id"] != jid for j in listed["items"])

    row = db_session.get(Job, jid)
    assert row is not None and row.deleted_at is not None
    assert len(_activities(db_session, jid, ActivityType.JOB_DELETED)) == 1


def test_non_admin_cannot_delete_job(client_for, users, customer):
    admin = client_for(users["admin"])
    job = _create(admin, customer.id).json()
    assert client_for(users["sales"]).delete(f"/api/v1/jobs/{job['id']}").status_code == 403
    assert client_for(users["scheduling"]).delete(f"/api/v1/jobs/{job['id']}").status_code == 403
