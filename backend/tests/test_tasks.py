"""Database-backed integration tests for the Tasks API.

Covers create (links/created_by), list defaults + filters, get, update/reassign,
complete, reopen, soft delete, overdue computation, the permission matrix,
activity logging + timeline linkage, and the selectable-users endpoint.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.enums import ActivityType
from app.models.task import Task

PAST = "2020-01-01T00:00:00Z"
FUTURE = "2099-01-01T00:00:00Z"


def _activities(db: Session, task_id: int, activity_type: ActivityType) -> list[Activity]:
    rows = db.scalars(select(Activity).where(Activity.activity_type == activity_type)).all()
    return [a for a in rows if (a.meta or {}).get("task_id") == task_id]


def _new_job(client, customer_id: int) -> int:
    return client.post("/api/v1/jobs", json={"customer_id": customer_id, "title": "J"}).json()["id"]


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
def test_create_standalone_task_sets_creator(client_for, users, db_session):
    admin = client_for(users["admin"])
    resp = admin.post("/api/v1/tasks", json={"title": "Call back customer"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "open"
    assert body["priority"] == "normal"
    assert body["created_by"]["id"] == users["admin"].id
    assert body["is_overdue"] is False
    assert len(_activities(db_session, body["id"], ActivityType.TASK_CREATED)) == 1


def test_create_customer_and_job_linked_tasks(client_for, users, customer):
    admin = client_for(users["admin"])
    jid = _new_job(admin, customer.id)

    c_task = admin.post(
        "/api/v1/tasks", json={"title": "Welcome call", "customer_id": customer.id}
    ).json()
    assert c_task["customer_id"] == customer.id

    # Job-linked task inherits the job's customer.
    j_task = admin.post("/api/v1/tasks", json={"title": "Site check", "job_id": jid}).json()
    assert j_task["job_id"] == jid
    assert j_task["customer_id"] == customer.id


def test_any_role_can_create_task(client_for, users):
    resp = client_for(users["support"]).post("/api/v1/tasks", json={"title": "Support task"})
    assert resp.status_code == 201


# --------------------------------------------------------------------------- #
# List defaults + filters
# --------------------------------------------------------------------------- #
def test_default_list_excludes_completed_and_cancelled(client_for, users):
    admin = client_for(users["admin"])
    t = admin.post("/api/v1/tasks", json={"title": "Finish me"}).json()
    admin.post(f"/api/v1/tasks/{t['id']}/complete", json={})
    listed = admin.get("/api/v1/tasks").json()
    assert all(item["id"] != t["id"] for item in listed["items"])
    # ...but an explicit status filter finds it.
    done = admin.get("/api/v1/tasks", params={"status": "completed"}).json()
    assert any(item["id"] == t["id"] for item in done["items"])


def test_filters(client_for, users, customer):
    admin = client_for(users["admin"])
    jid = _new_job(admin, customer.id)
    admin.post(
        "/api/v1/tasks",
        json={
            "title": "Urgent panel fix",
            "priority": "urgent",
            "assigned_to_id": users["support"].id,
            "job_id": jid,
        },
    )
    admin.post("/api/v1/tasks", json={"title": "Low note", "priority": "low"})

    assert admin.get("/api/v1/tasks", params={"priority": "urgent"}).json()["total"] >= 1
    by_assignee = admin.get("/api/v1/tasks", params={"assigned_to_id": users["support"].id}).json()
    assert all(i["assigned_to_id"] == users["support"].id for i in by_assignee["items"])
    assert admin.get("/api/v1/tasks", params={"customer_id": customer.id}).json()["total"] >= 1
    assert admin.get("/api/v1/tasks", params={"job_id": jid}).json()["total"] >= 1
    assert any(
        i["title"] == "Urgent panel fix"
        for i in admin.get("/api/v1/tasks", params={"q": "panel"}).json()["items"]
    )


def test_overdue_filter_and_flag(client_for, users):
    admin = client_for(users["admin"])
    overdue = admin.post("/api/v1/tasks", json={"title": "Past due", "due_date": PAST}).json()
    admin.post("/api/v1/tasks", json={"title": "Future", "due_date": FUTURE})

    assert overdue["is_overdue"] is True
    ids = [i["id"] for i in admin.get("/api/v1/tasks", params={"overdue": "true"}).json()["items"]]
    assert overdue["id"] in ids

    # Completing clears overdue.
    admin.post(f"/api/v1/tasks/{overdue['id']}/complete", json={})
    refetched = admin.get("/api/v1/tasks", params={"status": "completed"}).json()
    done = next(i for i in refetched["items"] if i["id"] == overdue["id"])
    assert done["is_overdue"] is False


# --------------------------------------------------------------------------- #
# Get / update / reassign
# --------------------------------------------------------------------------- #
def test_get_and_404(client_for, users):
    admin = client_for(users["admin"])
    t = admin.post("/api/v1/tasks", json={"title": "X"}).json()
    assert admin.get(f"/api/v1/tasks/{t['id']}").status_code == 200
    assert admin.get("/api/v1/tasks/999999").status_code == 404


def test_update_and_reassign_logs(client_for, users, customer, db_session):
    admin = client_for(users["admin"])
    t = admin.post("/api/v1/tasks", json={"title": "Edit me", "customer_id": customer.id}).json()
    resp = admin.patch(
        f"/api/v1/tasks/{t['id']}",
        json={"title": "Edited", "assigned_to_id": users["sales"].id},
    )
    assert resp.status_code == 200
    assert resp.json()["assigned_to_id"] == users["sales"].id
    assert len(_activities(db_session, t["id"], ActivityType.TASK_ASSIGNED)) == 1
    assert len(_activities(db_session, t["id"], ActivityType.TASK_UPDATED)) == 1


def test_creator_can_edit_but_other_non_admin_cannot(client_for, users):
    # NOTE: client_for overrides the current user globally on the app, so each
    # action acquires a fresh client to assert under the right identity.
    own = client_for(users["support"]).post("/api/v1/tasks", json={"title": "Mine"}).json()
    # Support edits its OWN task -> allowed.
    assert (
        client_for(users["support"])
        .patch(f"/api/v1/tasks/{own['id']}", json={"title": "Mine v2"})
        .status_code
        == 200
    )

    # Admin-created task -> support (not creator, not admin) cannot edit.
    admin_task = client_for(users["admin"]).post("/api/v1/tasks", json={"title": "Boss"}).json()
    assert (
        client_for(users["support"])
        .patch(f"/api/v1/tasks/{admin_task['id']}", json={"title": "no"})
        .status_code
        == 403
    )


# --------------------------------------------------------------------------- #
# Complete / reopen
# --------------------------------------------------------------------------- #
def test_assignee_can_complete_with_notes(client_for, users, db_session):
    admin = client_for(users["admin"])
    t = admin.post(
        "/api/v1/tasks", json={"title": "Do it", "assigned_to_id": users["support"].id}
    ).json()

    support = client_for(users["support"])
    resp = support.post(f"/api/v1/tasks/{t['id']}/complete", json={"notes": "done on site"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["completed_by"]["id"] == users["support"].id
    assert body["completed_at"] is not None
    logged = _activities(db_session, t["id"], ActivityType.TASK_COMPLETED)
    assert logged[0].meta["notes"] == "done on site"


def test_non_assignee_non_admin_cannot_complete(client_for, users):
    admin = client_for(users["admin"])
    t = admin.post(
        "/api/v1/tasks", json={"title": "Not yours", "assigned_to_id": users["sales"].id}
    ).json()
    assert client_for(users["support"]).post(f"/api/v1/tasks/{t['id']}/complete", json={}).status_code == 403


def test_reopen_clears_completion(client_for, users, db_session):
    admin = client_for(users["admin"])
    t = admin.post("/api/v1/tasks", json={"title": "Reopen me"}).json()
    admin.post(f"/api/v1/tasks/{t['id']}/complete", json={})
    resp = admin.post(f"/api/v1/tasks/{t['id']}/reopen")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "open"
    assert body["completed_at"] is None
    assert body["completed_by"] is None
    reopen_logs = _activities(db_session, t["id"], ActivityType.TASK_UPDATED)
    assert any(a.meta.get("action") == "reopen" for a in reopen_logs)


# --------------------------------------------------------------------------- #
# Soft delete
# --------------------------------------------------------------------------- #
def test_admin_soft_delete_excludes_and_logs(client_for, users, db_session):
    admin = client_for(users["admin"])
    t = admin.post("/api/v1/tasks", json={"title": "Remove"}).json()
    assert admin.delete(f"/api/v1/tasks/{t['id']}").status_code == 204
    assert admin.get(f"/api/v1/tasks/{t['id']}").status_code == 404
    assert all(i["id"] != t["id"] for i in admin.get("/api/v1/tasks").json()["items"])
    row = db_session.get(Task, t["id"])
    assert row is not None and row.deleted_at is not None
    assert len(_activities(db_session, t["id"], ActivityType.TASK_DELETED)) == 1


def test_non_admin_cannot_delete(client_for, users):
    own = client_for(users["support"]).post("/api/v1/tasks", json={"title": "Mine"}).json()
    assert client_for(users["support"]).delete(f"/api/v1/tasks/{own['id']}").status_code == 403


# --------------------------------------------------------------------------- #
# Activity timeline linkage
# --------------------------------------------------------------------------- #
def test_task_activity_appears_in_timelines(client_for, users, customer):
    admin = client_for(users["admin"])
    jid = _new_job(admin, customer.id)
    admin.post("/api/v1/tasks", json={"title": "Timeline task", "job_id": jid})

    cust_tl = admin.get("/api/v1/activities", params={"customer_id": customer.id}).json()
    job_tl = admin.get("/api/v1/activities", params={"job_id": jid}).json()
    assert any(a["activity_type"] == "task_created" for a in cust_tl["items"])
    assert any(a["activity_type"] == "task_created" for a in job_tl["items"])


# --------------------------------------------------------------------------- #
# Selectable users
# --------------------------------------------------------------------------- #
def test_selectable_users_lightweight_and_readable_by_support(client_for, users):
    resp = client_for(users["support"]).get("/api/v1/users/selectable")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) >= 1
    sample = rows[0]
    assert set(sample.keys()) == {"id", "full_name", "role"}
    assert "email" not in sample
