"""Tests for the import review layer (Phase B1).

Synthetic data only. Exercises edit/approve/reject/skip/reopen, issue
resolution, bulk approve-clean, summary, permissions — and asserts that NO live
Customer/Job records are created by any review action.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.import_staging import ImportRow
from app.models.job import Job
from tests.test_import import _synthetic_bytes  # reuse the synthetic workbook


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


# --------------------------------------------------------------------------- #
# Edit
# --------------------------------------------------------------------------- #
def test_edit_snapshots_original_and_merges(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "SCS0001")
    assert row["parsed"]["customer_name"] == "Alex Roe"

    resp = admin.patch(
        f"/api/v1/imports/{bid}/rows/{row['id']}",
        json={"customer_name": "Alexander Roe", "review_notes": "fixed name"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed"]["customer_name"] == "Alexander Roe"  # edited
    # original parser output preserved
    fetched = admin.get(f"/api/v1/imports/{bid}/rows/{row['id']}").json()
    assert fetched["parsed"]["customer_name"] == "Alexander Roe"


def test_edit_rejects_unknown_field(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "SCS0001")
    resp = admin.patch(
        f"/api/v1/imports/{bid}/rows/{row['id']}", json={"evil_field": "x"}
    )
    assert resp.status_code == 422  # extra="forbid"


# --------------------------------------------------------------------------- #
# Approve gating + resolve
# --------------------------------------------------------------------------- #
def test_approve_blocked_until_error_resolved(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    # SCS0003 has an ambiguous_name (error-severity) issue.
    row = _by_ref(_rows(admin, bid), "SCS0003")
    err = next(i for i in row["issues"] if i["kind"] == "ambiguous_name")
    assert err["severity"] == "error"

    blocked = admin.post(f"/api/v1/imports/{bid}/rows/{row['id']}/approve")
    assert blocked.status_code == 409  # unresolved error

    resolved = admin.patch(
        f"/api/v1/imports/{bid}/issues/{err['id']}", json={"resolution_note": "name is correct"}
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolved"] is True

    ok = admin.post(f"/api/v1/imports/{bid}/rows/{row['id']}/approve")
    assert ok.status_code == 200
    assert ok.json()["review_status"] == "approved"


def test_blank_and_divider_not_approvable(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    rows = _rows(admin, bid)
    divider = next(r for r in rows if r["row_class"] == "divider")
    assert admin.post(f"/api/v1/imports/{bid}/rows/{divider['id']}/approve").status_code == 409


def test_reject_skip_reopen(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "SCS0001")

    r = admin.post(f"/api/v1/imports/{bid}/rows/{row['id']}/reject", json={"notes": "dupe"})
    assert r.status_code == 200 and r.json()["review_status"] == "rejected"
    assert admin.post(f"/api/v1/imports/{bid}/rows/{row['id']}/skip").json()["review_status"] == "skipped"
    assert admin.post(f"/api/v1/imports/{bid}/rows/{row['id']}/reopen").json()["review_status"] == "pending"


# --------------------------------------------------------------------------- #
# Bulk approve clean + summary
# --------------------------------------------------------------------------- #
def test_bulk_approve_clean(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    # 4 job rows; SCS0003 carries an error -> not clean. Expect 3 approved of 4 examined.
    resp = admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")
    assert resp.status_code == 200
    body = resp.json()
    assert body["eligible_examined"] == 4
    assert body["approved"] == 3

    # SCS0003 stays pending (had an error issue).
    row3 = _by_ref(_rows(admin, bid), "SCS0003")
    assert row3["review_status"] == "pending"


def test_summary(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    s = admin.get(f"/api/v1/imports/{bid}/summary").json()
    assert s["by_row_class"].get("job") == 4
    assert s["unresolved_error_rows"] == 1  # SCS0003


# --------------------------------------------------------------------------- #
# Permissions + no live writes
# --------------------------------------------------------------------------- #
def test_non_admin_forbidden(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "SCS0001")
    support = client_for(users["support"])
    assert support.patch(f"/api/v1/imports/{bid}/rows/{row['id']}", json={"customer_name": "x"}).status_code == 403
    assert support.post(f"/api/v1/imports/{bid}/rows/{row['id']}/approve").status_code == 403
    assert support.post(f"/api/v1/imports/{bid}/bulk-approve-clean").status_code == 403


def test_review_actions_make_no_live_records(client_for, users, db_session: Session):
    cust_before = db_session.scalar(select(func.count()).select_from(Customer))
    job_before = db_session.scalar(select(func.count()).select_from(Job))

    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "SCS0001")
    admin.patch(f"/api/v1/imports/{bid}/rows/{row['id']}", json={"customer_name": "Edited"})
    admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")

    assert db_session.scalar(select(func.count()).select_from(Customer)) == cust_before
    assert db_session.scalar(select(func.count()).select_from(Job)) == job_before
    # All committed_* links remain null in Phase B.
    rows = db_session.scalars(select(ImportRow).where(ImportRow.batch_id == bid)).all()
    assert all(r.committed_customer_id is None and r.committed_job_id is None for r in rows)
