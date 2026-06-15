"""Database-backed integration tests for the Customers API.

Covers create/list/search/get/update/soft-delete, activity logging, and the
role-based permission matrix. Each test runs in a rolled-back transaction.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.customer import Customer
from app.models.enums import ActivityType


def _activities(db: Session, customer_id: int, activity_type: ActivityType) -> list[Activity]:
    stmt = select(Activity).where(
        Activity.customer_id == customer_id,
        Activity.activity_type == activity_type,
    )
    return list(db.scalars(stmt).all())


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
def test_admin_can_create_customer_and_logs_activity(client_for, users, db_session):
    client = client_for(users["admin"])
    resp = client.post("/api/v1/customers", json={"full_name": "Ada Lovelace", "suburb": "Carlton"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] > 0
    assert body["full_name"] == "Ada Lovelace"

    logged = _activities(db_session, body["id"], ActivityType.CUSTOMER_CREATED)
    assert len(logged) == 1
    assert logged[0].actor_id == users["admin"].id


def test_sales_admin_can_create_customer(client_for, users):
    client = client_for(users["sales"])
    resp = client.post("/api/v1/customers", json={"full_name": "Grace Hopper"})
    assert resp.status_code == 201


def test_support_cannot_create_customer(client_for, users):
    client = client_for(users["support"])
    resp = client.post("/api/v1/customers", json={"full_name": "Denied User"})
    assert resp.status_code == 403


def test_create_requires_full_name(client_for, users):
    client = client_for(users["admin"])
    resp = client.post("/api/v1/customers", json={"suburb": "Nowhere"})
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# List / search
# --------------------------------------------------------------------------- #
def test_list_and_search(client_for, users):
    admin = client_for(users["admin"])
    admin.post("/api/v1/customers", json={"full_name": "Alan Turing", "suburb": "Maida Vale"})
    admin.post("/api/v1/customers", json={"full_name": "Katherine Johnson", "postcode": "3000"})

    # Support (read-only) can list.
    support = client_for(users["support"])
    listed = support.get("/api/v1/customers").json()
    assert listed["total"] >= 2
    assert listed["limit"] == 25 and listed["offset"] == 0

    # Search by name fragment.
    found = support.get("/api/v1/customers", params={"q": "turing"}).json()
    names = {c["full_name"] for c in found["items"]}
    assert "Alan Turing" in names
    assert "Katherine Johnson" not in names

    # Search by postcode.
    by_postcode = support.get("/api/v1/customers", params={"q": "3000"}).json()
    assert any(c["full_name"] == "Katherine Johnson" for c in by_postcode["items"])


# --------------------------------------------------------------------------- #
# Get detail
# --------------------------------------------------------------------------- #
def test_get_detail_and_404(client_for, users):
    client = client_for(users["admin"])
    created = client.post("/api/v1/customers", json={"full_name": "Edsger Dijkstra"}).json()

    ok = client.get(f"/api/v1/customers/{created['id']}")
    assert ok.status_code == 200
    assert ok.json()["full_name"] == "Edsger Dijkstra"

    missing = client.get("/api/v1/customers/999999")
    assert missing.status_code == 404


# --------------------------------------------------------------------------- #
# Update
# --------------------------------------------------------------------------- #
def test_update_logs_changed_fields(client_for, users, db_session):
    admin = client_for(users["admin"])
    created = admin.post("/api/v1/customers", json={"full_name": "Margaret Hamilton"}).json()

    sales = client_for(users["sales"])
    resp = sales.patch(
        f"/api/v1/customers/{created['id']}",
        json={"phone": "0400000000", "suburb": "Fitzroy"},
    )
    assert resp.status_code == 200
    assert resp.json()["phone"] == "0400000000"

    logged = _activities(db_session, created["id"], ActivityType.CUSTOMER_UPDATED)
    assert len(logged) == 1
    assert set(logged[0].meta["changes"]) == {"phone", "suburb"}


def test_support_cannot_update_customer(client_for, users):
    admin = client_for(users["admin"])
    created = admin.post("/api/v1/customers", json={"full_name": "Barbara Liskov"}).json()

    support = client_for(users["support"])
    resp = support.patch(f"/api/v1/customers/{created['id']}", json={"suburb": "Blocked"})
    assert resp.status_code == 403


def test_internal_notes_round_trip_and_separate_from_notes(client_for, users):
    """Phase A: manual internal_notes round-trips and stays independent of the
    legacy/imported `notes` field — the two never overwrite each other."""
    admin = client_for(users["admin"])
    created = admin.post(
        "/api/v1/customers",
        json={"full_name": "Karen Sparck Jones", "notes": "imported source text"},
    ).json()
    assert created["internal_notes"] is None  # exposed on read, blank by default

    resp = admin.patch(
        f"/api/v1/customers/{created['id']}",
        json={"internal_notes": "call back Tuesday"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["internal_notes"] == "call back Tuesday"
    assert body["notes"] == "imported source text"  # imported field untouched


# --------------------------------------------------------------------------- #
# Soft delete
# --------------------------------------------------------------------------- #
def test_admin_soft_delete_excludes_from_reads_and_logs(client_for, users, db_session):
    admin = client_for(users["admin"])
    created = admin.post("/api/v1/customers", json={"full_name": "John von Neumann"}).json()
    cid = created["id"]

    resp = admin.delete(f"/api/v1/customers/{cid}")
    assert resp.status_code == 204

    # Excluded from normal reads.
    assert admin.get(f"/api/v1/customers/{cid}").status_code == 404
    listed = admin.get("/api/v1/customers", params={"q": "von Neumann"}).json()
    assert all(c["id"] != cid for c in listed["items"])

    # Row still exists with deleted_at set (recoverable).
    row = db_session.get(Customer, cid)
    assert row is not None and row.deleted_at is not None

    # Activity logged.
    assert len(_activities(db_session, cid, ActivityType.CUSTOMER_DELETED)) == 1


def test_sales_admin_cannot_delete_customer(client_for, users):
    admin = client_for(users["admin"])
    created = admin.post("/api/v1/customers", json={"full_name": "Tim Berners-Lee"}).json()

    sales = client_for(users["sales"])
    resp = sales.delete(f"/api/v1/customers/{created['id']}")
    assert resp.status_code == 403
