"""Tests for the import review layer (Phase B1).

Synthetic data only. Exercises edit/approve/reject/skip/reopen, issue
resolution, bulk approve-clean, summary, permissions — and asserts that NO live
Customer/Job records are created by any review action.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.enums import ImportBatchStatus, ImportRowClass, ImportRowReviewStatus
from app.models.import_staging import ImportBatch, ImportRow
from app.models.job import Job
from app.services import import_review
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
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")
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


def test_edit_address_merges_and_snapshots(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")
    assert row["parsed"]["address"] == "1 Test St"  # parsed from the workbook

    resp = admin.patch(
        f"/api/v1/imports/{bid}/rows/{row['id']}",
        json={"address": "42 New Road"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed"]["address"] == "42 New Road"          # edit applied
    assert body["original_parsed"]["address"] == "1 Test St"   # original preserved


def test_edit_rejects_unknown_field(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")
    resp = admin.patch(
        f"/api/v1/imports/{bid}/rows/{row['id']}", json={"evil_field": "x"}
    )
    assert resp.status_code == 422  # extra="forbid"


def test_row_read_includes_internal_notes_override(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")
    # The field is exposed and defaults to null (use the generated notes).
    assert "internal_notes_override" in row
    assert row["internal_notes_override"] is None


def test_edit_internal_notes_override_null_empty_text_semantics(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    rid = _by_ref(_rows(admin, bid), "TESTIMP0001")["id"]

    def patch(value):
        return admin.patch(f"/api/v1/imports/{bid}/rows/{rid}", json={"internal_notes_override": value})

    # text -> stored verbatim; persists on reload
    assert patch("Ring before 9am").json()["internal_notes_override"] == "Ring before 9am"
    assert admin.get(f"/api/v1/imports/{bid}/rows/{rid}").json()["internal_notes_override"] == "Ring before 9am"
    # "" -> stored as empty string (commit-blank semantics), NOT reset to null
    assert patch("").json()["internal_notes_override"] == ""
    # null -> explicit reset to the generated default
    assert patch(None).json()["internal_notes_override"] is None
    # omitting the key leaves it unchanged (set it, then patch an unrelated field)
    patch("keep me")
    admin.patch(f"/api/v1/imports/{bid}/rows/{rid}", json={"customer_name": "Alex Roe Jr"})
    assert admin.get(f"/api/v1/imports/{bid}/rows/{rid}").json()["internal_notes_override"] == "keep me"


def test_internal_notes_override_locked_after_approval_until_reopen(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    rid = _by_ref(_rows(admin, bid), "TESTIMP0001")["id"]
    # editable while pending
    assert admin.patch(f"/api/v1/imports/{bid}/rows/{rid}", json={"internal_notes_override": "pre"}).status_code == 200
    # approve -> override edits are blocked (422)
    assert admin.post(f"/api/v1/imports/{bid}/rows/{rid}/approve").json()["review_status"] == "approved"
    blocked = admin.patch(f"/api/v1/imports/{bid}/rows/{rid}", json={"internal_notes_override": "late"})
    assert blocked.status_code == 422
    # the value is unchanged by the rejected edit
    assert admin.get(f"/api/v1/imports/{bid}/rows/{rid}").json()["internal_notes_override"] == "pre"
    # reopen -> editable again
    assert admin.post(f"/api/v1/imports/{bid}/rows/{rid}/reopen").json()["review_status"] == "pending"
    ok = admin.patch(f"/api/v1/imports/{bid}/rows/{rid}", json={"internal_notes_override": "now allowed"})
    assert ok.status_code == 200 and ok.json()["internal_notes_override"] == "now allowed"


# --------------------------------------------------------------------------- #
# Approve gating + resolve
# --------------------------------------------------------------------------- #
def test_approve_blocked_until_error_resolved(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    # TESTIMP0003 has an ambiguous_name (error-severity) issue.
    row = _by_ref(_rows(admin, bid), "TESTIMP0003")
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
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")

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
    # 4 job rows; TESTIMP0003 carries an error -> not clean. Expect 3 approved of 4 examined.
    resp = admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")
    assert resp.status_code == 200
    body = resp.json()
    assert body["eligible_examined"] == 4
    assert body["approved"] == 3

    # TESTIMP0003 stays pending (had an error issue).
    row3 = _by_ref(_rows(admin, bid), "TESTIMP0003")
    assert row3["review_status"] == "pending"


def test_summary(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    s = admin.get(f"/api/v1/imports/{bid}/summary").json()
    assert s["by_row_class"].get("job") == 4
    assert s["unresolved_error_rows"] == 1  # TESTIMP0003
    # 4 pending job rows minus TESTIMP0003 (unresolved error) == 3 clean-eligible.
    assert s["eligible_clean_count"] == 3


# --------------------------------------------------------------------------- #
# B2-supporting reads: filters + audit fields (read-only additions)
# --------------------------------------------------------------------------- #
def test_filter_unresolved_only(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    items = admin.get(
        f"/api/v1/imports/{bid}/rows", params={"unresolved_only": "true", "limit": 200}
    ).json()["items"]
    # Only TESTIMP0003 carries an unresolved error issue.
    assert [r["legacy_reference"] for r in items] == ["TESTIMP0003"]


def test_search_by_reference_and_name(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    by_ref = admin.get(f"/api/v1/imports/{bid}/rows", params={"q": "TESTIMP0002"}).json()["items"]
    assert [r["legacy_reference"] for r in by_ref] == ["TESTIMP0002"]
    # Search also matches the parsed customer name.
    by_name = admin.get(f"/api/v1/imports/{bid}/rows", params={"q": "Alex Roe"}).json()["items"]
    assert any(r["legacy_reference"] == "TESTIMP0001" for r in by_name)


def test_read_exposes_audit_fields(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")
    # Before any edit: original_parsed is null, review fields empty.
    assert row["original_parsed"] is None
    assert row["review_notes"] is None
    assert row["reviewed_at"] is None

    admin.patch(
        f"/api/v1/imports/{bid}/rows/{row['id']}",
        json={"customer_name": "Alexander Roe", "review_notes": "fixed"},
    )
    edited = admin.get(f"/api/v1/imports/{bid}/rows/{row['id']}").json()
    # Original snapshot preserves the pre-edit value; audit fields populated.
    assert edited["original_parsed"]["customer_name"] == "Alex Roe"
    assert edited["parsed"]["customer_name"] == "Alexander Roe"
    assert edited["review_notes"] == "fixed"
    assert edited["reviewer_id"] is not None
    assert edited["reviewed_at"] is not None


def test_issue_read_exposes_resolution_audit(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "TESTIMP0003")
    err = next(i for i in row["issues"] if i["kind"] == "ambiguous_name")
    admin.patch(
        f"/api/v1/imports/{bid}/issues/{err['id']}", json={"resolution_note": "checked"}
    )
    fetched = _by_ref(_rows(admin, bid), "TESTIMP0003")
    resolved = next(i for i in fetched["issues"] if i["id"] == err["id"])
    assert resolved["resolved"] is True
    assert resolved["resolution_note"] == "checked"
    assert resolved["resolved_by_id"] is not None
    assert resolved["resolved_at"] is not None


# --------------------------------------------------------------------------- #
# Permissions + no live writes
# --------------------------------------------------------------------------- #
def test_non_admin_forbidden(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")
    support = client_for(users["support"])
    assert support.patch(f"/api/v1/imports/{bid}/rows/{row['id']}", json={"customer_name": "x"}).status_code == 403
    assert support.post(f"/api/v1/imports/{bid}/rows/{row['id']}/approve").status_code == 403
    assert support.post(f"/api/v1/imports/{bid}/bulk-approve-clean").status_code == 403


def test_review_actions_make_no_live_records(client_for, users, db_session: Session):
    cust_before = db_session.scalar(select(func.count()).select_from(Customer))
    job_before = db_session.scalar(select(func.count()).select_from(Job))

    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")
    admin.patch(f"/api/v1/imports/{bid}/rows/{row['id']}", json={"customer_name": "Edited"})
    admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")

    assert db_session.scalar(select(func.count()).select_from(Customer)) == cust_before
    assert db_session.scalar(select(func.count()).select_from(Job)) == job_before
    # All committed_* links remain null in Phase B.
    rows = db_session.scalars(select(ImportRow).where(ImportRow.batch_id == bid)).all()
    assert all(r.committed_customer_id is None and r.committed_job_id is None for r in rows)


# --------------------------------------------------------------------------- #
# legacy_reference editing (column-only, lockable) — staging source-ref correction
# --------------------------------------------------------------------------- #
def test_edit_legacy_reference_updates_column(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")
    resp = admin.patch(
        f"/api/v1/imports/{bid}/rows/{row['id']}", json={"legacy_reference": "TESTIMP0001-B"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["legacy_reference"] == "TESTIMP0001-B"
    fetched = admin.get(f"/api/v1/imports/{bid}/rows/{row['id']}").json()
    assert fetched["legacy_reference"] == "TESTIMP0001-B"


def test_edit_legacy_reference_not_written_into_parsed(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")
    # parsed carries the parser's ORIGINAL reference (provenance); the edit must update
    # only the COLUMN and leave parsed untouched (column is authoritative for commit).
    parsed_ref_before = (row.get("parsed") or {}).get("legacy_reference")
    resp = admin.patch(
        f"/api/v1/imports/{bid}/rows/{row['id']}", json={"legacy_reference": "TESTIMP0001-B"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["legacy_reference"] == "TESTIMP0001-B"                                  # column updated
    assert (body.get("parsed") or {}).get("legacy_reference") == parsed_ref_before      # parsed untouched
    assert (body.get("parsed") or {}).get("legacy_reference") != "TESTIMP0001-B"        # new value not in parsed
    fetched = admin.get(f"/api/v1/imports/{bid}/rows/{row['id']}").json()
    assert fetched["legacy_reference"] == "TESTIMP0001-B"
    assert (fetched.get("parsed") or {}).get("legacy_reference") == parsed_ref_before


def test_edit_legacy_reference_allowed_after_approve(client_for, users):
    # Unlike internal_notes_override / customer resolution, an APPROVED row's reference
    # stays editable so a duplicate source ref can be fixed right before commit.
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")
    admin.post(f"/api/v1/imports/{bid}/rows/{row['id']}/approve")
    resp = admin.patch(
        f"/api/v1/imports/{bid}/rows/{row['id']}", json={"legacy_reference": "TESTIMP0001-FIXED"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["legacy_reference"] == "TESTIMP0001-FIXED"


def test_edit_legacy_reference_empty_clears_to_none(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")
    resp = admin.patch(
        f"/api/v1/imports/{bid}/rows/{row['id']}", json={"legacy_reference": "   "}
    )
    assert resp.status_code == 200
    assert resp.json()["legacy_reference"] is None  # whitespace -> None (mirrors ingest)


def _locked_row(db: Session, status: str) -> tuple[ImportBatch, ImportRow]:
    b = ImportBatch(
        source_filename="syn.xlsx", sheet_name="COMPLETED",
        status=ImportBatchStatus.REVIEWING.value,
    )
    db.add(b)
    db.flush()
    r = ImportRow(
        batch_id=b.id, source_row_index=2, row_class=ImportRowClass.JOB.value,
        legacy_reference="LOCKED0001", raw={}, parsed={"customer_name": "X"},
        review_status=status,
    )
    db.add(r)
    db.flush()
    return b, r


@pytest.mark.parametrize(
    "status",
    [ImportRowReviewStatus.COMMITTED.value, ImportRowReviewStatus.REVERSED.value],
)
def test_edit_legacy_reference_rejected_when_committed_or_reversed(db_session: Session, status):
    b, r = _locked_row(db_session, status)
    with pytest.raises(ValueError):
        import_review.edit_row(db_session, b, r, {"legacy_reference": "NEW-REF"}, actor_id=1)
    assert r.legacy_reference == "LOCKED0001"  # unchanged on a locked row


def test_edit_legacy_reference_too_long_rejected(client_for, users):
    # The column is String(64); an over-long ref must be a clean 422 at the schema, not a 500.
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")
    resp = admin.patch(
        f"/api/v1/imports/{bid}/rows/{row['id']}", json={"legacy_reference": "X" * 65}
    )
    assert resp.status_code == 422
    # 64 chars is accepted (the boundary).
    ok = admin.patch(
        f"/api/v1/imports/{bid}/rows/{row['id']}", json={"legacy_reference": "Y" * 64}
    )
    assert ok.status_code == 200 and ok.json()["legacy_reference"] == "Y" * 64
