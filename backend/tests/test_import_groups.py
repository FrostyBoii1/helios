"""Section B3-2: pending-row grouping storage + API.

Synthetic data only. Exercises create/add/remove/set-primary/dissolve, the
auto-dissolve (<2 members) + auto-promote-primary rules, the invariants
(same-batch / class / lock / mutual-exclusion with B2 resolution), admin-only
access, and the INERT proof — grouping a row does NOT change commit behaviour in
B3-2 (each grouped row still commits as its own new customer; B3-3 changes that).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.import_staging import ImportBatch, ImportCustomerGroup, ImportRow
from app.models.job import Job
from app.services import import_commit, import_review
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


def _ids(client, bid: int, *refs: str) -> list[int]:
    rows = _rows(client, bid)
    return [_by_ref(rows, r)["id"] for r in refs]


def _create_group(client, bid: int, primary: int, members: list[int], reason: str | None = None):
    return client.post(
        f"/api/v1/imports/{bid}/customer-groups",
        json={"primary_row_id": primary, "member_row_ids": members, "reason": reason},
    )


def _get_row(client, bid: int, rid: int) -> dict:
    return client.get(f"/api/v1/imports/{bid}/rows/{rid}").json()


def _make_customer(db: Session, *, name: str = "Existing One") -> Customer:
    c = Customer(full_name=name, suburb="Testville")
    db.add(c)
    db.flush()
    return c


# --------------------------------------------------------------------------- #
# Create / read
# --------------------------------------------------------------------------- #
def test_create_group_sets_members(client_for, users, db_session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    a, b = _ids(admin, bid, "TESTIMP0001", "TESTIMP0002")

    resp = _create_group(admin, bid, primary=a, members=[b], reason="same person")
    assert resp.status_code == 201
    g = resp.json()
    assert g["primary_row_id"] == a
    assert sorted(g["member_row_ids"]) == sorted([a, b])
    assert g["reason"] == "same person" and g["committed_customer_id"] is None
    assert {m["row_id"]: m["is_primary"] for m in g["members"]} == {a: True, b: False}
    # Each member row now reads mode='group' + customer_group_id, resolved_customer_id null.
    for rid in (a, b):
        row = _get_row(admin, bid, rid)
        assert row["customer_resolution_mode"] == "group"
        assert row["customer_group_id"] == g["id"]
        assert row["resolved_customer_id"] is None


def test_read_group_and_list(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    a, b = _ids(admin, bid, "TESTIMP0001", "TESTIMP0002")
    gid = _create_group(admin, bid, a, [b]).json()["id"]
    got = admin.get(f"/api/v1/imports/{bid}/customer-groups/{gid}")
    assert got.status_code == 200 and got.json()["id"] == gid
    lst = admin.get(f"/api/v1/imports/{bid}/customer-groups").json()
    assert [g["id"] for g in lst] == [gid]


def test_create_group_needs_two_rows(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    (a,) = _ids(admin, bid, "TESTIMP0001")
    assert _create_group(admin, bid, a, []).status_code == 422


# --------------------------------------------------------------------------- #
# Add / remove / set-primary / dissolve
# --------------------------------------------------------------------------- #
def test_add_and_remove_member(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    a, b, d = _ids(admin, bid, "TESTIMP0001", "TESTIMP0002", "TESTIMP0004")
    gid = _create_group(admin, bid, a, [b]).json()["id"]
    # add d
    g = admin.post(f"/api/v1/imports/{bid}/customer-groups/{gid}/rows", json={"row_id": d}).json()
    assert sorted(g["member_row_ids"]) == sorted([a, b, d])
    # remove d (still >=2 -> survives)
    res = admin.delete(f"/api/v1/imports/{bid}/customer-groups/{gid}/rows/{d}").json()
    assert res["dissolved"] is False
    assert sorted(res["group"]["member_row_ids"]) == sorted([a, b])
    assert _get_row(admin, bid, d)["customer_group_id"] is None


def test_remove_to_one_auto_dissolves(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    a, b = _ids(admin, bid, "TESTIMP0001", "TESTIMP0002")
    gid = _create_group(admin, bid, a, [b]).json()["id"]
    res = admin.delete(f"/api/v1/imports/{bid}/customer-groups/{gid}/rows/{b}").json()
    assert res["dissolved"] is True and res["group"] is None
    # Both rows revert to unresolved; the group is gone.
    assert _get_row(admin, bid, a)["customer_group_id"] is None
    assert _get_row(admin, bid, a)["customer_resolution_mode"] is None
    assert admin.get(f"/api/v1/imports/{bid}/customer-groups/{gid}").status_code == 404


def test_remove_primary_auto_promotes_lowest_source_index(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    a, b, d = _ids(admin, bid, "TESTIMP0001", "TESTIMP0002", "TESTIMP0004")  # src 2 < 4 < 6
    gid = _create_group(admin, bid, d, [a, b]).json()["id"]  # primary = highest-index d
    res = admin.delete(f"/api/v1/imports/{bid}/customer-groups/{gid}/rows/{d}").json()
    # d removed; remaining a (src 2), b (src 4) -> new primary = a (lowest).
    assert res["dissolved"] is False
    assert res["group"]["primary_row_id"] == a


def test_set_primary(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    a, b = _ids(admin, bid, "TESTIMP0001", "TESTIMP0002")
    gid = _create_group(admin, bid, a, [b]).json()["id"]
    g = admin.patch(f"/api/v1/imports/{bid}/customer-groups/{gid}", json={"primary_row_id": b}).json()
    assert g["primary_row_id"] == b
    # a non-member can't be primary
    (d,) = _ids(admin, bid, "TESTIMP0004")
    assert admin.patch(f"/api/v1/imports/{bid}/customer-groups/{gid}", json={"primary_row_id": d}).status_code == 422


def test_dissolve_group(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    a, b = _ids(admin, bid, "TESTIMP0001", "TESTIMP0002")
    gid = _create_group(admin, bid, a, [b]).json()["id"]
    diss = admin.delete(f"/api/v1/imports/{bid}/customer-groups/{gid}")
    assert diss.status_code == 200 and diss.json()["dissolved"] is True
    for rid in (a, b):
        assert _get_row(admin, bid, rid)["customer_group_id"] is None
        assert _get_row(admin, bid, rid)["customer_resolution_mode"] is None
    assert admin.get(f"/api/v1/imports/{bid}/customer-groups/{gid}").status_code == 404


# --------------------------------------------------------------------------- #
# Invariants / rejections
# --------------------------------------------------------------------------- #
def test_reject_cross_batch_rows(client_for, users):
    admin = client_for(users["admin"])
    bid1 = _ingest(admin)
    bid2 = admin.post(
        "/api/v1/imports?allow_duplicate=true",
        files={"file": ("synthetic.xlsx", _synthetic_bytes(), "application/vnd.ms-excel")},
    ).json()["id"]
    (a1,) = _ids(admin, bid1, "TESTIMP0001")
    (a2,) = _ids(admin, bid2, "TESTIMP0001")
    # primary from batch1, member from batch2 -> rejected
    assert _create_group(admin, bid1, a1, [a2]).status_code == 422


def test_reject_blank_or_divider_rows(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    rows = _rows(admin, bid)
    (a,) = _ids(admin, bid, "TESTIMP0001")
    divider = next(r for r in rows if r["row_class"] == "divider")
    assert _create_group(admin, bid, a, [divider["id"]]).status_code == 422


def test_reject_committed_or_reversed_rows(client_for, users, db_session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    a, b = _ids(admin, bid, "TESTIMP0001", "TESTIMP0002")
    # Simulate a committed row (set the link directly).
    cust = _make_customer(db_session)
    row_b = db_session.get(ImportRow, b)
    row_b.committed_customer_id = cust.id
    db_session.flush()
    assert _create_group(admin, bid, a, [b]).status_code == 422


def test_reject_approved_locked_member(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    a, b, d = _ids(admin, bid, "TESTIMP0001", "TESTIMP0002", "TESTIMP0004")
    gid = _create_group(admin, bid, a, [b]).json()["id"]
    # approve a grouped member -> the group is now locked.
    assert admin.post(f"/api/v1/imports/{bid}/rows/{a}/approve").json()["review_status"] == "approved"
    assert admin.post(f"/api/v1/imports/{bid}/customer-groups/{gid}/rows", json={"row_id": d}).status_code == 422
    # reopen the member -> group editable again.
    assert admin.post(f"/api/v1/imports/{bid}/rows/{a}/reopen").json()["review_status"] == "pending"
    assert admin.post(f"/api/v1/imports/{bid}/customer-groups/{gid}/rows", json={"row_id": d}).status_code == 200


# --------------------------------------------------------------------------- #
# Mutual exclusion with B2 resolution
# --------------------------------------------------------------------------- #
def test_grouping_clears_existing_resolution(client_for, users, db_session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    a, b = _ids(admin, bid, "TESTIMP0001", "TESTIMP0002")
    cust = _make_customer(db_session)
    # First resolve a to an existing customer (B2), then group it.
    assert admin.post(
        f"/api/v1/imports/{bid}/rows/{a}/resolve-customer",
        json={"mode": "existing", "customer_id": cust.id},
    ).status_code == 200
    _create_group(admin, bid, a, [b])
    row_a = _get_row(admin, bid, a)
    assert row_a["customer_resolution_mode"] == "group"
    assert row_a["resolved_customer_id"] is None  # B2 resolution replaced


def test_b2_resolution_detaches_from_group(client_for, users, db_session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    a, b = _ids(admin, bid, "TESTIMP0001", "TESTIMP0002")
    gid = _create_group(admin, bid, a, [b]).json()["id"]
    cust = _make_customer(db_session)
    # Resolving a to existing leaves the group -> group drops to 1 -> auto-dissolves.
    assert admin.post(
        f"/api/v1/imports/{bid}/rows/{a}/resolve-customer",
        json={"mode": "existing", "customer_id": cust.id},
    ).status_code == 200
    assert _get_row(admin, bid, a)["customer_resolution_mode"] == "existing"
    assert _get_row(admin, bid, a)["customer_group_id"] is None
    assert _get_row(admin, bid, b)["customer_resolution_mode"] is None  # lone member reverted
    assert admin.get(f"/api/v1/imports/{bid}/customer-groups/{gid}").status_code == 404


# --------------------------------------------------------------------------- #
# Permissions + serialization + model round-trip
# --------------------------------------------------------------------------- #
def test_group_endpoints_admin_only(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    a, b = _ids(admin, bid, "TESTIMP0001", "TESTIMP0002")
    sales = client_for(users["sales"])
    assert _create_group(sales, bid, a, [b]).status_code == 403
    assert sales.get(f"/api/v1/imports/{bid}/customer-groups").status_code == 403


def test_row_read_serializes_customer_group_id(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    a, b = _ids(admin, bid, "TESTIMP0001", "TESTIMP0002")
    assert _get_row(admin, bid, a)["customer_group_id"] is None  # default
    gid = _create_group(admin, bid, a, [b]).json()["id"]
    assert _get_row(admin, bid, a)["customer_group_id"] == gid


def test_group_reconcile_works_under_autoflush_false(db_session):
    # Production get_db()/SessionLocal uses autoflush=False; the group reconcile
    # logic must still see PENDING membership writes (the service flushes
    # explicitly). Reproduce the production session config on the same rolled-back
    # connection. Without the explicit flush, group_member_rows() would return
    # stale membership and auto-promote/auto-dissolve would misbehave.
    from sqlalchemy.orm import Session as SASession

    s = SASession(
        bind=db_session.connection(),
        join_transaction_mode="create_savepoint",
        autoflush=False,
    )
    try:
        b = ImportBatch(source_filename="x.xlsx", sheet_name="COMPLETED", status="reviewing")
        s.add(b)
        s.flush()
        rows = [
            ImportRow(batch_id=b.id, source_row_index=i, row_class="job",
                      review_status="pending", parsed={"customer_name": "P"})
            for i in (2, 4, 6)
        ]
        s.add_all(rows)
        s.flush()
        a, bb, d = rows  # source indices 2, 4, 6
        g = import_review.create_group(
            s, b, primary_row_id=d.id, member_row_ids=[a.id, bb.id], actor_id=1
        )
        # group_to_dict must see all 3 members even under autoflush=False.
        assert sorted(import_review.group_to_dict(s, g)["member_row_ids"]) == sorted([a.id, bb.id, d.id])
        # Remove the primary (d) -> auto-promote lowest source_row_index (a).
        survived = import_review.remove_from_group(s, b, g, row_id=d.id, actor_id=1)
        assert survived is not None and survived.primary_row_id == a.id
        members = import_review.group_member_rows(s, g.id)
        assert sorted(m.id for m in members) == sorted([a.id, bb.id])
    finally:
        s.close()


def test_group_model_roundtrip(db_session):
    b = ImportBatch(source_filename="syn.xlsx", sheet_name="COMPLETED", status="reviewing")
    db_session.add(b)
    db_session.flush()
    r1 = ImportRow(batch_id=b.id, source_row_index=2, row_class="job", review_status="pending",
                   parsed={"customer_name": "P"})
    r2 = ImportRow(batch_id=b.id, source_row_index=3, row_class="job", review_status="pending",
                   parsed={"customer_name": "P"})
    db_session.add_all([r1, r2])
    db_session.flush()
    g = ImportCustomerGroup(batch_id=b.id, primary_row_id=r1.id, reason="rt")
    db_session.add(g)
    db_session.flush()
    r1.customer_group_id = g.id
    r2.customer_group_id = g.id
    db_session.flush()
    db_session.expire_all()
    reloaded = db_session.get(ImportCustomerGroup, g.id)
    assert reloaded.primary_row_id == r1.id and reloaded.reason == "rt"
    assert reloaded.committed_customer_id is None
    members = import_review.group_member_rows(db_session, g.id)
    assert sorted(m.id for m in members) == sorted([r1.id, r2.id])


# --------------------------------------------------------------------------- #
# B3-3 superseded this: grouped rows now commit into ONE shared customer.
# (Detailed grouped commit/preview/reverse tests live in test_import_groups_commit.)
# --------------------------------------------------------------------------- #
def test_grouped_rows_commit_into_one_customer_b3_3(client_for, users, db_session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    a, b = _ids(admin, bid, "TESTIMP0001", "TESTIMP0002")
    gid = _create_group(admin, bid, a, [b]).json()["id"]  # primary = a

    cust_before = db_session.scalar(select(func.count()).select_from(Customer))
    admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")
    res = admin.post(f"/api/v1/imports/{bid}/commit", json={}).json()
    assert res["committed"] == 3  # TESTIMP0001/0002/0004

    row_a = db_session.get(ImportRow, a)
    row_b = db_session.get(ImportRow, b)
    # a (primary) + b (dependent) share ONE customer; TESTIMP0004 makes its own.
    assert row_a.committed_customer_id == row_b.committed_customer_id
    assert db_session.scalar(select(func.count()).select_from(Customer)) == cust_before + 2
    # The group records its created customer for audit/hand-off.
    assert db_session.get(ImportCustomerGroup, gid).committed_customer_id == row_a.committed_customer_id
