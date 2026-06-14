"""Tests for the Phase C0 commit PREVIEW (read-only).

Synthetic data only. Verifies eligibility filtering, exclusion reason counts,
chronological case-number prediction + year derivation, legacy_reference
mapping, admin-only access — and asserts the preview writes NOTHING (no
Customer/Job/Task/Activity/Document records, no batch/row mutations).
"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.customer import Customer
from app.models.import_staging import ImportRow
from app.models.job import Job
from app.services import import_commit_preview as preview_svc
from tests.test_import import _synthetic_bytes


def _ingest(client) -> int:
    return client.post(
        "/api/v1/imports",
        files={"file": ("synthetic.xlsx", _synthetic_bytes(), "application/vnd.ms-excel")},
    ).json()["id"]


def _rows(client, bid: int) -> list[dict]:
    return client.get(f"/api/v1/imports/{bid}/rows", params={"limit": 200}).json()["items"]


def _by_ref(rows: list[dict], ref: str) -> dict:
    return next(r for r in rows if r["legacy_reference"] == ref)


def _preview(client, bid: int) -> dict:
    resp = client.get(f"/api/v1/imports/{bid}/commit-preview")
    assert resp.status_code == 200
    return resp.json()


# --------------------------------------------------------------------------- #
# Eligibility + exclusions
# --------------------------------------------------------------------------- #
def test_eligibility_and_excluded_counts(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    # Approve the 3 clean job rows; TESTIMP0003 (error) stays pending.
    admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")

    p = _preview(admin, bid)
    assert p["total_rows"] == 6
    assert p["eligible_count"] == 3
    assert p["would_create"] == {"customers": 3, "jobs": 3}
    ex = p["excluded"]
    assert ex["blank_or_divider"] == 2          # 1 divider + 1 blank
    assert ex["not_approved"] == 1              # TESTIMP0003 still pending
    assert ex["already_committed"] == 0
    assert ex["missing_customer_name"] == 0
    # Buckets + eligible sum to the total row count (disjoint partition).
    assert p["eligible_count"] + sum(ex.values()) == p["total_rows"]


def test_nothing_eligible_before_approval(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    p = _preview(admin, bid)
    assert p["eligible_count"] == 0
    assert p["excluded"]["not_approved"] == 4   # all 4 job rows pending
    assert p["excluded"]["blank_or_divider"] == 2


# --------------------------------------------------------------------------- #
# Case-number chronological prediction + year derivation
# --------------------------------------------------------------------------- #
def test_case_number_chronological_and_year(client_for, users, db_session: Session):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")
    p = _preview(admin, bid)

    # Chronological order: TESTIMP0002 (sale 30/06/2025) < TESTIMP0001 (sale 10/10/2025)
    # < TESTIMP0004 (no sale; install 01/01/2026).
    order = [s["legacy_reference"] for s in p["samples"]]
    assert order == ["TESTIMP0002", "TESTIMP0001", "TESTIMP0004"]

    # Predicted numbers continue from the CURRENT live count per year (prediction,
    # not reservation) — compute the expected base so the test is DB-state robust.
    def base(year: int) -> int:
        return db_session.scalar(
            select(func.count()).select_from(Job).where(Job.case_number.like(f"SCS-{year}-%"))
        )

    b2025, b2026 = base(2025), base(2026)
    predicted = {s["legacy_reference"]: s["predicted_case_number"] for s in p["samples"]}
    assert predicted["TESTIMP0002"] == f"SCS-2025-{b2025 + 1:05d}"   # earliest 2025 sale
    assert predicted["TESTIMP0001"] == f"SCS-2025-{b2025 + 2:05d}"   # next 2025 sale
    assert predicted["TESTIMP0004"] == f"SCS-2026-{b2026 + 1:05d}"   # year from install_date
    assert p["predicted_case_numbers_by_year"] == {"2025": 2, "2026": 1}


# --------------------------------------------------------------------------- #
# Mapping
# --------------------------------------------------------------------------- #
def test_mapping_and_legacy_reference(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")
    p = _preview(admin, bid)

    s1 = next(s for s in p["samples"] if s["legacy_reference"] == "TESTIMP0001")
    # Customer mapping (synthetic data).
    assert s1["customer"]["full_name"] == "Alex Roe"
    assert s1["customer"]["address_line1"] == "1 Test St"
    # Job preview: legacy_reference carried through, status installed, case number.
    assert s1["job"]["legacy_reference"] == "TESTIMP0001"
    assert s1["job"]["status"] == "installed"
    assert s1["job"]["predicted_case_number"].startswith("SCS-2025-")  # 2025 sale year
    assert s1["job"]["predicted_case_number"] == s1["predicted_case_number"]
    assert s1["job"]["salesperson_text"] == "Jane Smith"  # text only, no user link
    # Phase 2a: structured details exposed read-only in the preview.
    details = s1["job"]["details"]
    assert details is not None and details["_v"] == 2
    assert "system" in details  # panels/inverter/nmi captured into the System section


def test_address_prefers_parsed_then_raw():
    # Parsed (reviewer-editable) address wins.
    m = preview_svc.map_customer_preview(
        {"customer_name": "X", "address": "42 New Road"}, {"address": "1 Old St"}
    )
    assert m["address_line1"] == "42 New Road"
    # Falls back to the raw cell when parsed address is missing/blank.
    m2 = preview_svc.map_customer_preview({"customer_name": "X", "address": ""}, {"address": "1 Old St"})
    assert m2["address_line1"] == "1 Old St"
    m3 = preview_svc.map_customer_preview({"customer_name": "X"}, {"address": "1 Old St"})
    assert m3["address_line1"] == "1 Old St"


def test_invalid_case_year_excluded(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")
    # Malformed sale date -> derived case-year 2002 (outside the sane range).
    admin.patch(f"/api/v1/imports/{bid}/rows/{row['id']}", json={"sale_date": "01/06/2002"})
    admin.post(f"/api/v1/imports/{bid}/rows/{row['id']}/approve")
    admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")  # approve the rest (TESTIMP0002/0004)

    p = _preview(admin, bid)
    assert p["excluded"]["invalid_case_year"] == 1
    refs = [s["legacy_reference"] for s in p["samples"]]
    assert "TESTIMP0001" not in refs  # not previewed / no predicted case number
    assert p["eligible_count"] == 2  # TESTIMP0002 + TESTIMP0004 still eligible


def test_classify_row_invalid_case_year_unit():
    base = dict(
        committed_customer_id=None,
        committed_job_id=None,
        row_class="job",
        review_status="approved",
        issues=[],
    )
    bad = SimpleNamespace(**base, parsed={"customer_name": "X", "sale_date": "01/06/2002"})
    assert preview_svc.classify_row(bad, current_year=2026) == "invalid_case_year"
    ok = SimpleNamespace(**base, parsed={"customer_name": "X", "sale_date": "01/06/2025"})
    assert preview_svc.classify_row(ok, current_year=2026) is None
    # No date -> falls back to current year -> valid.
    nodate = SimpleNamespace(**base, parsed={"customer_name": "X"})
    assert preview_svc.classify_row(nodate, current_year=2026) is None


def test_missing_customer_name_excluded(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    row = _by_ref(_rows(admin, bid), "TESTIMP0001")
    # Blank out the customer name, then approve -> must be excluded from commit.
    admin.patch(f"/api/v1/imports/{bid}/rows/{row['id']}", json={"customer_name": ""})
    admin.post(f"/api/v1/imports/{bid}/rows/{row['id']}/approve")
    admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")  # approve the rest

    p = _preview(admin, bid)
    refs = [s["legacy_reference"] for s in p["samples"]]
    assert "TESTIMP0001" not in refs
    assert p["excluded"]["missing_customer_name"] == 1


# --------------------------------------------------------------------------- #
# classify_row unit coverage (incl. the defensive unresolved_error path)
# --------------------------------------------------------------------------- #
def test_classify_row_unit():
    def fake(**kw):
        base = dict(
            committed_customer_id=None,
            committed_job_id=None,
            row_class="job",
            review_status="approved",
            issues=[],
            parsed={"customer_name": "Someone"},
        )
        base.update(kw)
        return SimpleNamespace(**base)

    assert preview_svc.classify_row(fake()) is None  # eligible
    assert preview_svc.classify_row(fake(committed_job_id=5)) == "already_committed"
    assert preview_svc.classify_row(fake(row_class="divider")) == "blank_or_divider"
    assert preview_svc.classify_row(fake(review_status="pending")) == "not_approved"
    err = SimpleNamespace(severity="error", resolved=False)
    assert preview_svc.classify_row(fake(issues=[err])) == "unresolved_error"
    assert preview_svc.classify_row(fake(parsed={"customer_name": "  "})) == "missing_customer_name"


# --------------------------------------------------------------------------- #
# Decommission + name-cell notes surfaced in the job preview
# --------------------------------------------------------------------------- #
def test_map_job_preview_surfaces_decommission_and_name_notes():
    m = preview_svc.map_job_preview(
        {
            "removes_old_system": True,
            "decommission_marker": "DECOM",
            "customer_name_notes": "includes hot water timer",
        },
        predicted_case_number="SCS-2025-00001",
        legacy_reference="REF1",
    )
    assert m["removes_old_system"] is True
    assert m["customer_name_notes"] == "includes hot water timer"

    plain = preview_svc.map_job_preview(
        {"customer_name": "Dana Fox"}, predicted_case_number="SCS-2025-00002", legacy_reference=None
    )
    assert plain["removes_old_system"] is False
    assert plain["customer_name_notes"] is None


def test_preview_blobs_match_commit_renderer():
    # Phase 2b: with raw, the preview renders blobs via the SAME render_legacy_blobs
    # the commit uses -> preview blobs are byte-identical to the committed job's.
    from app.services.import_details import render_legacy_blobs

    parsed = {
        "approval_state": "approved", "notes_raw": "call first",
        "details": {
            "_v": 2,
            "system": {"panel_count": 16, "phase": "three"},
            "payment": {"total": "5000"},
            "flags": {"removes_old_system": True, "decommission_marker": "REMOVE OLD SYSTEM"},
            "notes": {"misfiled": [{"source_column": "Phase", "text": "ask sparky"}]},
        },
    }
    m = preview_svc.map_job_preview(
        parsed, predicted_case_number="SCS-2025-00001", legacy_reference="R1",
        raw={}, batch_id=5, source_row_index=7,
    )
    expected = render_legacy_blobs(
        parsed["details"], parsed, batch_id=5, source_row_index=7, legacy_reference="R1"
    )
    assert m["details"] == parsed["details"]
    assert m["system_details"] == expected["system_details"]
    assert m["install_details"] == expected["install_details"]
    assert m["approval_details"] == expected["approval_details"]
    assert m["notes"] == expected["notes"]


# --------------------------------------------------------------------------- #
# Permissions
# --------------------------------------------------------------------------- #
def test_commit_preview_admin_only(client_for, users):
    admin = client_for(users["admin"])
    bid = _ingest(admin)
    support = client_for(users["support"])
    assert support.get(f"/api/v1/imports/{bid}/commit-preview").status_code == 403


# --------------------------------------------------------------------------- #
# Zero live writes
# --------------------------------------------------------------------------- #
def test_preview_makes_no_live_records(client_for, users, db_session: Session):
    cust_before = db_session.scalar(select(func.count()).select_from(Customer))
    job_before = db_session.scalar(select(func.count()).select_from(Job))
    act_before = db_session.scalar(select(func.count()).select_from(Activity))

    admin = client_for(users["admin"])
    bid = _ingest(admin)
    admin.post(f"/api/v1/imports/{bid}/bulk-approve-clean")
    admin.get(f"/api/v1/imports/{bid}/commit-preview")
    admin.get(f"/api/v1/imports/{bid}/commit-preview")  # idempotent — call twice

    # No live records created.
    assert db_session.scalar(select(func.count()).select_from(Customer)) == cust_before
    assert db_session.scalar(select(func.count()).select_from(Job)) == job_before
    assert db_session.scalar(select(func.count()).select_from(Activity)) == act_before
    # Preview did not commit/link any rows.
    rows = db_session.scalars(select(ImportRow).where(ImportRow.batch_id == bid)).all()
    assert all(r.committed_customer_id is None and r.committed_job_id is None for r in rows)
