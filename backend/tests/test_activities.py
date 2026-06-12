"""Database-backed integration tests for the read-only Activity timeline API.

Covers customer/job timelines, newest-first ordering, actor + meta inclusion,
pagination, permissions (all roles read), and the 400/401 contracts.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _seed_customer_with_job(client) -> tuple[int, int]:
    """Create a customer + job + a couple of actions, returning (cid, jid).

    This generates: customer_created, job_created, job_updated, job_status_changed.
    """
    cid = client.post("/api/v1/customers", json={"full_name": "Timeline Co"}).json()["id"]
    jid = client.post("/api/v1/jobs", json={"customer_id": cid, "title": "Install"}).json()["id"]
    client.patch(f"/api/v1/jobs/{jid}", json={"notes": "ring ahead"})
    client.post(f"/api/v1/jobs/{jid}/status", json={"status": "booked_for_install"})
    return cid, jid


# --------------------------------------------------------------------------- #
# Timelines
# --------------------------------------------------------------------------- #
def test_customer_timeline_includes_job_events(client_for, users):
    admin = client_for(users["admin"])
    cid, jid = _seed_customer_with_job(admin)

    data = admin.get("/api/v1/activities", params={"customer_id": cid}).json()
    types = [a["activity_type"] for a in data["items"]]
    assert "customer_created" in types
    assert "job_created" in types
    assert "job_updated" in types
    assert "job_status_changed" in types
    # Job events carry this customer_id, so they appear in the customer timeline.
    assert any(a["job_id"] == jid for a in data["items"])


def test_job_timeline_excludes_customer_only_events(client_for, users):
    admin = client_for(users["admin"])
    cid, jid = _seed_customer_with_job(admin)

    data = admin.get("/api/v1/activities", params={"job_id": jid}).json()
    assert all(a["job_id"] == jid for a in data["items"])
    # customer_created has job_id == null, so it must NOT be in the job timeline.
    assert all(a["activity_type"] != "customer_created" for a in data["items"])


def test_newest_first_order(client_for, users):
    admin = client_for(users["admin"])
    cid, _ = _seed_customer_with_job(admin)
    items = admin.get("/api/v1/activities", params={"customer_id": cid}).json()["items"]
    ids = [a["id"] for a in items]
    assert ids == sorted(ids, reverse=True)
    # The most recent action was the status change.
    assert items[0]["activity_type"] == "job_status_changed"


def test_actor_included(client_for, users):
    admin = client_for(users["admin"])
    cid, _ = _seed_customer_with_job(admin)
    items = admin.get("/api/v1/activities", params={"customer_id": cid}).json()["items"]
    assert items[0]["actor"]["id"] == users["admin"].id
    assert items[0]["actor"]["full_name"] == users["admin"].full_name


def test_meta_included(client_for, users):
    admin = client_for(users["admin"])
    cid, _ = _seed_customer_with_job(admin)
    items = admin.get("/api/v1/activities", params={"customer_id": cid}).json()["items"]
    status_event = next(a for a in items if a["activity_type"] == "job_status_changed")
    assert status_event["meta"] == {"from": "new", "to": "booked_for_install"}


def test_pagination(client_for, users):
    admin = client_for(users["admin"])
    cid, _ = _seed_customer_with_job(admin)
    page = admin.get("/api/v1/activities", params={"customer_id": cid, "limit": 1, "offset": 0}).json()
    assert len(page["items"]) == 1
    assert page["limit"] == 1 and page["offset"] == 0
    assert page["total"] >= 4
    # Second page returns a different (older) item.
    page2 = admin.get(
        "/api/v1/activities", params={"customer_id": cid, "limit": 1, "offset": 1}
    ).json()
    assert page2["items"][0]["id"] != page["items"][0]["id"]


# --------------------------------------------------------------------------- #
# Permissions / contracts
# --------------------------------------------------------------------------- #
def test_support_can_read_timeline(client_for, users):
    admin = client_for(users["admin"])
    cid, _ = _seed_customer_with_job(admin)
    support = client_for(users["support"])
    resp = support.get("/api/v1/activities", params={"customer_id": cid})
    assert resp.status_code == 200
    assert resp.json()["total"] >= 4


def test_missing_filters_returns_400(client_for, users):
    admin = client_for(users["admin"])
    assert admin.get("/api/v1/activities").status_code == 400


def test_unauthenticated_returns_401() -> None:
    # No dependency overrides here: real auth runs and rejects the request.
    client = TestClient(app)
    assert client.get("/api/v1/activities", params={"customer_id": 1}).status_code == 401
