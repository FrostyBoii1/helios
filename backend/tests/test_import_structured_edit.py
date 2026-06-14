"""Phase 3a tests: read-only field-registry endpoint + structured details edit.

Synthetic data only. Covers the registry endpoint (admin-only), the path-
restricted details patch (accept allowed paths, reject unknown / derived /
read-only paths, no arbitrary JSON mutation), deep original_parsed snapshot
isolation, deep-merge sibling preservation, flat-edit back-compat, and the
guarantee that a staging edit makes no live Customer/Job/Activity writes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.customer import Customer
from app.models.enums import ImportBatchStatus, ImportRowClass, ImportRowReviewStatus
from app.models.import_staging import ImportBatch, ImportRow
from app.models.job import Job
from app.services import import_review


def _ingest(client) -> int:
    from tests.test_import import _synthetic_bytes
    return client.post(
        "/api/v1/imports",
        files={"file": ("syn.xlsx", _synthetic_bytes(), "application/vnd.ms-excel")},
    ).json()["id"]


def _rows(client, bid):
    return client.get(f"/api/v1/imports/{bid}/rows", params={"limit": 200}).json()["items"]


def _by_ref(rows, ref):
    return next(r for r in rows if r["legacy_reference"] == ref)


# --------------------------------------------------------------------------- #
# Field-registry endpoint
# --------------------------------------------------------------------------- #
def test_field_registry_endpoint(client_for, users):
    admin = client_for(users["admin"])
    r = admin.get("/api/v1/imports/field-registry")
    assert r.status_code == 200
    body = r.json()
    assert any(s["key"] == "system" for s in body["sections"])
    keys = {f["key"] for f in body["fields"]}
    assert {"panel_count", "msb_status", "solar_vic"} <= keys
    paths = set(body["editable_details_paths"])
    assert {"system.panel_count", "compliance.msb_status", "legacy.solar_vic"} <= paths
    # derived / read-only paths are NOT writable
    assert "flags.removes_old_system" not in paths
    assert "provenance" not in paths
    assert "notes.misfiled" not in paths


def test_field_registry_authenticated_access(client_for, users):
    # Phase 4b: relaxed from admin-only to any authenticated user (PII-free metadata
    # the structured Job UI needs). A non-admin (support) and sales_admin can read it.
    assert client_for(users["support"]).get("/api/v1/imports/field-registry").status_code == 200
    assert client_for(users["sales"]).get("/api/v1/imports/field-registry").status_code == 200


def test_field_registry_unauthenticated_rejected():
    # No get_current_user override here (must not use client_for) -> real auth -> 401.
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get("/api/v1/imports/field-registry").status_code == 401


# --------------------------------------------------------------------------- #
# Pure apply_details_patch
# --------------------------------------------------------------------------- #
def test_apply_details_patch_merges_and_preserves_siblings():
    parsed = {"customer_name": "X", "details": {"_v": 2, "system": {"panel_count": 16, "panel": "Longi"}}}
    out = import_review.apply_details_patch(parsed, {"system": {"panel_count": 99}, "compliance": {"msb_status": "no"}})
    assert out["details"]["system"]["panel_count"] == 99
    assert out["details"]["system"]["panel"] == "Longi"          # sibling preserved
    assert out["details"]["compliance"]["msb_status"] == "no"    # new section added
    assert out["customer_name"] == "X"
    # Input is NOT mutated in place.
    assert parsed["details"]["system"]["panel_count"] == 16
    assert "compliance" not in parsed["details"]


def test_apply_details_patch_rejects_disallowed_paths():
    parsed = {"details": {"_v": 2}}
    for patch in (
        {"system": {"evil": "x"}},                  # unknown key
        {"unknown_section": {"k": "v"}},            # unknown section
        {"flags": {"removes_old_system": False}},   # derived
        {"provenance": {"x": 1}},                   # read-only
        {"notes": {"misfiled": []}},                # read-only list
    ):
        with pytest.raises(ValueError):
            import_review.apply_details_patch(parsed, patch)


# --------------------------------------------------------------------------- #
# edit_row: deep snapshot + flat back-compat (service level, seeded row)
# --------------------------------------------------------------------------- #
def _seed_row(db: Session) -> tuple[ImportBatch, ImportRow]:
    b = ImportBatch(source_filename="syn.xlsx", sheet_name="COMPLETED",
                    status=ImportBatchStatus.PARSED.value)
    db.add(b)
    db.flush()
    r = ImportRow(
        batch_id=b.id, source_row_index=2, row_class=ImportRowClass.JOB.value,
        legacy_reference="TESTIMP3A01", raw={"address": "1 Test St"},
        parsed={"customer_name": "Pat Lee",
                "details": {"_v": 2, "system": {"panel_count": 16, "panel": "Longi"}}},
        review_status=ImportRowReviewStatus.PENDING.value,
    )
    db.add(r)
    db.flush()
    return b, r


def test_edit_row_deep_snapshot_is_independent(db_session: Session, users):
    b, r = _seed_row(db_session)
    import_review.edit_row(db_session, b, r, {"details": {"system": {"panel_count": 99}}}, actor_id=users["admin"].id)
    db_session.flush()
    # parsed updated, original_parsed snapshot unchanged (deep copy).
    assert r.parsed["details"]["system"]["panel_count"] == 99
    assert r.original_parsed["details"]["system"]["panel_count"] == 16
    assert r.original_parsed["details"]["system"]["panel"] == "Longi"


def test_edit_row_flat_edits_still_work(db_session: Session, users):
    b, r = _seed_row(db_session)
    import_review.edit_row(db_session, b, r, {"customer_name": "New Name"}, actor_id=users["admin"].id)
    db_session.flush()
    assert r.parsed["customer_name"] == "New Name"
    assert r.original_parsed["customer_name"] == "Pat Lee"


# --------------------------------------------------------------------------- #
# API end-to-end + no live writes
# --------------------------------------------------------------------------- #
def test_details_patch_endpoint_accepts_and_rejects(client_for, users, db_session: Session):
    c0 = db_session.scalar(select(func.count()).select_from(Customer))
    j0 = db_session.scalar(select(func.count()).select_from(Job))
    a0 = db_session.scalar(select(func.count()).select_from(Activity))

    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")

    ok = admin.patch(
        f"/api/v1/imports/{bid}/rows/{row['id']}",
        json={"details": {"system": {"panel_count": 42}, "compliance": {"msb_status": "no"}}},
    )
    assert ok.status_code == 200
    d = ok.json()["parsed"]["details"]
    assert d["system"]["panel_count"] == 42 and d["compliance"]["msb_status"] == "no"

    # Unknown + read-only paths -> 422.
    assert admin.patch(f"/api/v1/imports/{bid}/rows/{row['id']}",
                       json={"details": {"system": {"evil": "x"}}}).status_code == 422
    assert admin.patch(f"/api/v1/imports/{bid}/rows/{row['id']}",
                       json={"details": {"flags": {"removes_old_system": False}}}).status_code == 422

    # Staging edit creates ZERO live records.
    assert db_session.scalar(select(func.count()).select_from(Customer)) == c0
    assert db_session.scalar(select(func.count()).select_from(Job)) == j0
    assert db_session.scalar(select(func.count()).select_from(Activity)) == a0
