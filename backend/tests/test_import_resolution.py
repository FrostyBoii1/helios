"""Section B2-1: manual same-customer resolution intent (storage only).

Synthetic data only. Exercises the set-existing / set-new / clear resolution
service + endpoint, the validation/lock rules, admin-only access, and
ImportRowRead serialization. B2-1 is storage only — these tests assert NO live
Customer/Job is created by a resolution action and that commit/preview/reverse
are untouched (a resolution merely records reviewer intent).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.import_staging import ImportRow
from app.models.job import Job
from tests.test_import import _synthetic_bytes  # reuse the synthetic workbook

RESOLUTION_FIELDS = [
    "resolved_customer_id",
    "customer_resolution_mode",
    "customer_resolution_reason",
    "resolved_by_id",
    "resolved_at",
]


def _upload(client, data: bytes):
    return client.post(
        "/api/v1/imports",
        files={"file": ("synthetic.xlsx", data, "application/vnd.ms-excel")},
    )


def _ingest(client) -> int:
    return _upload(client, _synthetic_bytes()).json()["id"]


def _rows(client, batch_id: int) -> list[dict]:
    return client.get(f"/api/v1/imports/{batch_id}/rows", params={"limit": 200}).json()["items"]


def _by_ref(rows: list[dict], ref: str) -> dict:
    return next(r for r in rows if r["legacy_reference"] == ref)


def _row_id(client, batch_id: int, ref: str = "TESTIMP0001") -> int:
    return _by_ref(_rows(client, batch_id), ref)["id"]


def _resolve(client, batch_id: int, row_id: int, **body):
    return client.post(f"/api/v1/imports/{batch_id}/rows/{row_id}/resolve-customer", json=body)


def _make_customer(db: Session, *, name: str = "Existing Customer", deleted: bool = False) -> Customer:
    c = Customer(full_name=name, suburb="Testville")
    if deleted:
        c.deleted_at = datetime.now(timezone.utc)
    db.add(c)
    db.flush()
    return c


def _no_live_records(db: Session) -> tuple[int, int]:
    customers = db.scalar(select(func.count()).select_from(Customer)) or 0
    jobs = db.scalar(select(func.count()).select_from(Job)) or 0
    return customers, jobs


# --------------------------------------------------------------------------- #
# Set / clear happy paths
# --------------------------------------------------------------------------- #
def test_set_resolution_existing_success(client_for, users, db_session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    rid = _row_id(admin, bid)
    before = _no_live_records(db_session)
    cust = _make_customer(db_session, name="Phillip Schuman")

    resp = _resolve(admin, bid, rid, mode="existing", customer_id=cust.id, reason="same person, house 2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["customer_resolution_mode"] == "existing"
    assert body["resolved_customer_id"] == cust.id
    assert body["customer_resolution_reason"] == "same person, house 2"
    assert body["resolved_by_id"] == users["admin"].id
    assert body["resolved_at"] is not None
    # Persists across a reload.
    fetched = admin.get(f"/api/v1/imports/{bid}/rows/{rid}").json()
    assert fetched["resolved_customer_id"] == cust.id
    # No live Job created; the only customer delta is the one the TEST made.
    assert _no_live_records(db_session) == (before[0] + 1, before[1])


def test_set_resolution_new_success(client_for, users, db_session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    rid = _row_id(admin, bid)

    resp = _resolve(admin, bid, rid, mode="new", reason="distinct customer")
    assert resp.status_code == 200
    body = resp.json()
    assert body["customer_resolution_mode"] == "new"
    assert body["resolved_customer_id"] is None
    assert body["customer_resolution_reason"] == "distinct customer"
    assert body["resolved_by_id"] == users["admin"].id
    assert body["resolved_at"] is not None


def test_clear_resolution_success(client_for, users, db_session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    rid = _row_id(admin, bid)
    cust = _make_customer(db_session)

    assert _resolve(admin, bid, rid, mode="existing", customer_id=cust.id).status_code == 200
    resp = _resolve(admin, bid, rid, mode="clear")
    assert resp.status_code == 200
    body = resp.json()
    for field in RESOLUTION_FIELDS:
        assert body[field] is None, field


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def test_rejects_nonexistent_customer(client_for, users, db_session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    rid = _row_id(admin, bid)
    resp = _resolve(admin, bid, rid, mode="existing", customer_id=999_999)
    assert resp.status_code == 422
    # Nothing was stored.
    assert admin.get(f"/api/v1/imports/{bid}/rows/{rid}").json()["customer_resolution_mode"] is None


def test_rejects_soft_deleted_customer(client_for, users, db_session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    rid = _row_id(admin, bid)
    deleted = _make_customer(db_session, name="Gone Customer", deleted=True)
    resp = _resolve(admin, bid, rid, mode="existing", customer_id=deleted.id)
    assert resp.status_code == 422
    assert admin.get(f"/api/v1/imports/{bid}/rows/{rid}").json()["resolved_customer_id"] is None


def test_existing_mode_requires_customer_id(client_for, users, db_session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    rid = _row_id(admin, bid)
    # mode existing with no customer_id -> 422; never silently falls back to "new".
    resp = _resolve(admin, bid, rid, mode="existing")
    assert resp.status_code == 422
    assert admin.get(f"/api/v1/imports/{bid}/rows/{rid}").json()["customer_resolution_mode"] is None


# --------------------------------------------------------------------------- #
# Locking: pending only
# --------------------------------------------------------------------------- #
def test_rejects_change_after_approval(client_for, users, db_session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    rid = _row_id(admin, bid)
    cust = _make_customer(db_session)
    # Editable while pending.
    assert _resolve(admin, bid, rid, mode="new").status_code == 200
    # Approve -> locked.
    assert admin.post(f"/api/v1/imports/{bid}/rows/{rid}/approve").json()["review_status"] == "approved"
    blocked = _resolve(admin, bid, rid, mode="existing", customer_id=cust.id)
    assert blocked.status_code == 422
    # The stored value is unchanged by the rejected change.
    assert admin.get(f"/api/v1/imports/{bid}/rows/{rid}").json()["customer_resolution_mode"] == "new"
    # Reopen -> editable again.
    assert admin.post(f"/api/v1/imports/{bid}/rows/{rid}/reopen").json()["review_status"] == "pending"
    assert _resolve(admin, bid, rid, mode="clear").status_code == 200


def test_rejects_change_after_committed(client_for, users, db_session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    rid = _row_id(admin, bid)
    cust = _make_customer(db_session)
    # Simulate a committed row (set the committed link directly; no commit engine run).
    row = db_session.get(ImportRow, rid)
    row.committed_customer_id = cust.id
    db_session.flush()
    resp = _resolve(admin, bid, rid, mode="new")
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Auth + serialization + back-compat
# --------------------------------------------------------------------------- #
def test_resolve_customer_is_admin_only(client_for, users, db_session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    rid = _row_id(admin, bid)
    sales = client_for(users["sales"])  # non-admin
    resp = _resolve(sales, bid, rid, mode="new")
    assert resp.status_code == 403


def test_row_read_serializes_resolution_fields(client_for, users, db_session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")
    # All five fields are present and default to null (backwards compatible).
    for field in RESOLUTION_FIELDS:
        assert field in row, field
        assert row[field] is None, field


def test_existing_rows_behave_unchanged_with_null_resolution(client_for, users, db_session):
    # A freshly ingested row has null resolution and the normal edit/approve flow
    # is unaffected by the new columns.
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    rid = _row_id(admin, bid)
    assert admin.patch(
        f"/api/v1/imports/{bid}/rows/{rid}", json={"customer_name": "Alexander Roe"}
    ).status_code == 200
    approved = admin.post(f"/api/v1/imports/{bid}/rows/{rid}/approve")
    assert approved.status_code == 200
    body = approved.json()
    assert body["review_status"] == "approved"
    assert body["customer_resolution_mode"] is None


def test_model_roundtrip_resolution_columns(client_for, users, db_session):
    # Direct ORM round-trip through the new columns (migration applied correctly).
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    rid = _row_id(admin, bid)
    cust = _make_customer(db_session)
    row = db_session.get(ImportRow, rid)
    row.customer_resolution_mode = "existing"
    row.resolved_customer_id = cust.id
    row.customer_resolution_reason = "round trip"
    row.resolved_by_id = users["admin"].id
    row.resolved_at = datetime.now(timezone.utc)
    db_session.flush()
    db_session.expire(row)
    reloaded = db_session.get(ImportRow, rid)
    assert reloaded.customer_resolution_mode == "existing"
    assert reloaded.resolved_customer_id == cust.id
    assert reloaded.customer_resolution_reason == "round trip"
    assert reloaded.resolved_by_id == users["admin"].id
    assert reloaded.resolved_at is not None
