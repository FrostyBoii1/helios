"""Tests for the spreadsheet import staging pipeline (Phase A — parse-only).

Uses a SYNTHETIC in-memory workbook with fabricated names only — no real
customer data, no real workbook, no local paths. Proves: the parser classifies
and flags rows correctly; ingest creates staging rows/issues; and ingest creates
ZERO live Customer/Job records. Also checks admin-only permissions.
"""

from __future__ import annotations

from io import BytesIO

import openpyxl
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.import_staging import ImportBatch, ImportIssue, ImportRow
from app.models.job import Job
from app.services import import_ingest, import_parser

HEADERS = [
    "", "Sales Consultant", "Customer Name", "ADDRESS", "Phone", "Notes",
    "MSB/SB PICS IN FILE?", "Email", "Distributor", "Retailer", "NMI", "Meter No",
    "No of Panels", "Panel Brand/ Wattage", "Inverter Brand/Model", "Storey",
    "Phase", "Roof Type", "Date", "Day", "Time", "Installer",
]


def _synthetic_bytes() -> bytes:
    """A small COMPLETED sheet with fabricated rows covering key parse cases."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "COMPLETED"
    ws.append(HEADERS)  # row 1 = headers

    # row 2 — clean job (known brands -> confident hardware; no Day -> no mismatch)
    ws.append(["SCS0001", "Jane Smith 10/10/2025", "Alex Roe", "1 Test St", "0400000000",
               "", "Yes", "alex@example.test", "Essential", "Origin", "42041234567",
               "M1", "10", "Longi 440", "Goodwe 5kw", "1", "1", "Tin", "", "", "", "Installer One"])
    # row 3 — divider
    ws.append(["FORTNIGHT 1ST-14TH JULY"] + [""] * 21)
    # row 4 — job under divider: multi phone (labelled), multi email, pending approval,
    #         unmatched NMI, uncertain hardware
    ws.append(["SCS0002", "Sales Rep - 30/06/2025", "Pat Lee - PENDING 19/08/2026", "2 Test Rd",
               "0411111111/0422222222 Chris", "", "Yes?", "a@x.test/b@x.test", "Powercor", "AGL",
               "99999999999", "M2", "5", "Brand 415", "mystery unit", "1", "1", "Tile",
               "", "", "", "Installer Two"])
    # row 5 — clean ref but non-name customer cell -> ambiguous_name + approved
    ws.append(["SCS0003", "Jane Smith", "ESSENTIAL APPROVED", "3 Test Ave", "0433333333",
               "", "", "c@x.test", "Essential", "Red Energy", "40011234567", "M3", "8",
               "Brand 415", "Inverter 5kw", "1", "1", "Tin", "", "", "", "Installer One"])
    # row 6 — date/day mismatch (2026-01-01 is Thursday, not Monday)
    ws.append(["SCS0004", "Jane Smith", "Dana Fox", "4 Test Cl", "0444444444", "", "Yes",
               "d@x.test", "Essential", "Origin", "42049999999", "M4", "10", "Brand 440",
               "Inverter 5kw", "1", "1", "Tin", "01/01/2026", "Monday", "08:00", "Installer One"])
    # row 7 — blank
    ws.append([""] * 22)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _ws_from_bytes(data: bytes):
    return openpyxl.load_workbook(BytesIO(data), data_only=True)["COMPLETED"]


# --------------------------------------------------------------------------- #
# Parser unit tests (pure, DB-free)
# --------------------------------------------------------------------------- #
def test_parser_classifies_and_parses():
    rows = list(import_parser.parse_rows(_ws_from_bytes(_synthetic_bytes())))
    by_class: dict[str, list] = {}
    for r in rows:
        by_class.setdefault(r.row_class, []).append(r)

    assert len(by_class["job"]) == 4
    assert len(by_class["divider"]) == 1
    assert len(by_class["blank"]) == 1

    clean = next(r for r in rows if r.legacy_reference == "SCS0001")
    assert clean.parsed["customer_name"] == "Alex Roe"
    assert clean.parsed["address"] == "1 Test St"  # address now in parsed candidate
    assert clean.parsed["salesperson"] == "Jane Smith"
    assert clean.parsed["sale_date"] == "10/10/2025"
    assert clean.parsed["distributor_inferred"] == "NSW Essential"  # NMI 4204
    assert clean.parsed["msb_state"] == "yes"
    assert clean.issues == []


def test_parser_flags_issues():
    rows = list(import_parser.parse_rows(_ws_from_bytes(_synthetic_bytes())))

    r2 = next(r for r in rows if r.legacy_reference == "SCS0002")
    kinds2 = {i["kind"] for i in r2.issues}
    assert {"multi_phone", "multi_email", "nmi_unmatched"} <= kinds2
    assert r2.parsed["customer_name"] == "Pat Lee"
    assert r2.parsed["approval_state"] == "pending"  # "PENDING 19/08/2026"
    assert r2.parsed["approval_pending_date"] == "19/08/2026"
    assert r2.context_text == "FORTNIGHT 1ST-14TH JULY"  # carried from the divider
    # phone label kept only because it was explicit
    assert any(p["label"] == "Chris" for p in r2.parsed["phones"])

    r3 = next(r for r in rows if r.legacy_reference == "SCS0003")
    assert any(i["kind"] == "ambiguous_name" for i in r3.issues)
    assert r3.parsed["approval_state"] == "approved"

    r4 = next(r for r in rows if r.legacy_reference == "SCS0004")
    assert any(i["kind"] == "date_day_mismatch" for i in r4.issues)


# --------------------------------------------------------------------------- #
# Name-cell trailing notes + decommission detection (pure helpers)
# --------------------------------------------------------------------------- #
def test_clean_name_cell_notes_strips_approval_keeps_meaning():
    # Meaningful operational text is preserved verbatim.
    assert import_parser.clean_name_cell_notes("includes hot water timer") == "includes hot water timer"
    assert (
        import_parser.clean_name_cell_notes("undersold Brighte fees, check after install")
        == "undersold Brighte fees, check after install"
    )
    # Pure approval status leaves nothing meaningful behind.
    assert import_parser.clean_name_cell_notes("APPROVED") == ""
    assert import_parser.clean_name_cell_notes("PENDING 19/08/2026") == ""
    # Approval mixed with a real note keeps only the real note.
    assert (
        import_parser.clean_name_cell_notes("APPROVED includes hot water timer")
        == "includes hot water timer"
    )
    assert import_parser.clean_name_cell_notes("") == ""


def test_clean_name_cell_notes_strips_network_approval_residue():
    cn = import_parser.clean_name_cell_notes

    # The three documented examples: approval phrase (incl. network label) gone,
    # meaningful notes before/after preserved, no bare network residue.
    r1 = cn("includes hot water timer - ESSENTIAL APPROVED - Report Ref # - 96004-Y")
    assert "ESSENTIAL" not in r1.upper()
    assert "includes hot water timer" in r1 and "Report Ref" in r1 and "96004-Y" in r1

    r2 = cn("undersold Brighte fees, check after install - ESSENTIAL APPROVED")
    assert "ESSENTIAL" not in r2.upper()
    assert r2 == "undersold Brighte fees, check after install"

    r3 = cn("ESSENTIAL APPROVED - prescreened wk24/2 - REMOVE OLD SYSTEM")
    assert "ESSENTIAL" not in r3.upper()
    assert "prescreened wk24/2" in r3 and "REMOVE OLD SYSTEM" in r3

    # Other network labels are stripped as part of an APPROVED phrase.
    for net in ("ENERGEX", "ERGON", "ENDEAVOUR", "AUSGRID", "AUSNET",
                "POWERCOR", "UNITED", "JEMENA", "SAPN"):
        out = cn(f"keep this - {net} APPROVED")
        assert net not in out.upper(), net
        assert out == "keep this"

    # PENDING-with-date phrases (incl. a network label) are removed; note kept.
    assert cn("JEMENA PENDING 19/08/2026 - call customer") == "call customer"
    assert cn("ERGON PENDING 01/02/2025") == ""

    # Case-insensitive.
    assert "ESSENTIAL" not in cn("note - essential approved").upper()

    # Decommission content is preserved.
    assert "REMOVE OLD SYSTEM" in cn("ENDEAVOUR APPROVED - REMOVE OLD SYSTEM")

    # A network word that is NOT part of an approval status is meaningful content
    # and must be kept.
    assert cn("ESSENTIAL repairs needed") == "ESSENTIAL repairs needed"
    assert cn("needs ENERGEX meter upgrade") == "needs ENERGEX meter upgrade"


def test_detect_decommission_variants():
    for text in (
        "REMOVE OLD SYSTEM",
        "remove old system",
        "DECOM",
        "decommission",
        "decommision",   # missing one 's'
        "decomission",   # missing one 'm'
        "needs DECOM before install",
        "Customer wants to remove old system first",
    ):
        assert import_parser.detect_decommission(text) is not None, text
    # No false positives on ordinary text.
    assert import_parser.detect_decommission("Alex Roe", "includes hot water timer") is None
    assert import_parser.detect_decommission("") is None
    # Returns the matched marker text for reviewer visibility.
    assert import_parser.detect_decommission("Jane DECOM").upper() == "DECOM"


def _one_job_row_bytes(*, name_cell: str, notes_cell: str = "") -> bytes:
    """A minimal COMPLETED sheet: header + one clean job row, with the Customer
    Name + Notes cells controllable. Fabricated data only."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "COMPLETED"
    ws.append(HEADERS)
    ws.append(["SCS0009", "Rep 10/10/2025", name_cell, "9 Test St", "0400000000",
               notes_cell, "Yes", "x@example.test", "Essential", "Origin", "42041234567",
               "M9", "10", "Longi 440", "Goodwe 5kw", "1", "1", "Tin", "", "", "", "Installer One"])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_rows_preserves_name_cell_notes():
    rows = list(import_parser.parse_rows(_ws_from_bytes(
        _one_job_row_bytes(name_cell="Pat Lee - includes hot water timer")
    )))
    row = next(r for r in rows if r.legacy_reference == "SCS0009")
    assert row.parsed["customer_name"] == "Pat Lee"
    assert row.parsed["customer_name_notes"] == "includes hot water timer"
    assert row.parsed["removes_old_system"] is False
    assert row.parsed["decommission_marker"] is None


def test_parse_rows_flags_decommission_from_name_or_notes():
    # Marker in the name cell (no stop-marker preceding it).
    rows = list(import_parser.parse_rows(_ws_from_bytes(
        _one_job_row_bytes(name_cell="Sam Roe DECOM")
    )))
    row = next(r for r in rows if r.legacy_reference == "SCS0009")
    assert row.parsed["removes_old_system"] is True
    assert row.parsed["decommission_marker"].upper() == "DECOM"

    # Marker in the Notes column.
    rows2 = list(import_parser.parse_rows(_ws_from_bytes(
        _one_job_row_bytes(name_cell="Dana Fox", notes_cell="REMOVE OLD SYSTEM before install")
    )))
    row2 = next(r for r in rows2 if r.legacy_reference == "SCS0009")
    assert row2.parsed["removes_old_system"] is True
    assert "remove old system" in row2.parsed["decommission_marker"].lower()


# --------------------------------------------------------------------------- #
# Ingest tests (staging writes only — NO live Customer/Job writes)
# --------------------------------------------------------------------------- #
def test_ingest_creates_staging_and_no_live_records(db_session: Session, users):
    cust_before = db_session.scalar(select(func.count()).select_from(Customer))
    job_before = db_session.scalar(select(func.count()).select_from(Job))

    batch = import_ingest.ingest_bytes(
        db_session,
        file_bytes=_synthetic_bytes(),
        source_filename="synthetic.xlsx",
        created_by_id=users["admin"].id,
    )
    db_session.flush()

    assert batch.status.value == "parsed"
    assert batch.job_rows == 4
    assert batch.divider_rows == 1
    assert batch.blank_rows == 1
    assert batch.total_rows == 6  # rows after the header
    assert batch.file_sha256 and len(batch.file_sha256) == 64
    assert "/" not in batch.source_filename and "\\" not in batch.source_filename

    n_rows = db_session.scalar(
        select(func.count()).select_from(ImportRow).where(ImportRow.batch_id == batch.id)
    )
    n_issues = db_session.scalar(
        select(func.count()).select_from(ImportIssue).where(ImportIssue.batch_id == batch.id)
    )
    assert n_rows == 6
    assert n_issues >= 4
    # All staged rows are un-committed (no live link).
    committed = db_session.scalars(
        select(ImportRow).where(ImportRow.batch_id == batch.id)
    ).all()
    assert all(r.committed_customer_id is None and r.committed_job_id is None for r in committed)

    # Critical: ingest created ZERO live customers/jobs.
    assert db_session.scalar(select(func.count()).select_from(Customer)) == cust_before
    assert db_session.scalar(select(func.count()).select_from(Job)) == job_before


# --------------------------------------------------------------------------- #
# Endpoint tests (admin-only)
# --------------------------------------------------------------------------- #
def _upload(client, data: bytes, name: str = "synthetic.xlsx"):
    return client.post(
        "/api/v1/imports",
        files={"file": (name, data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )


def test_admin_can_ingest_and_inspect(client_for, users):
    admin = client_for(users["admin"])
    resp = _upload(admin, _synthetic_bytes())
    assert resp.status_code == 201
    batch = resp.json()
    assert batch["status"] == "parsed"
    assert batch["job_rows"] == 4

    # inspect rows
    rows = admin.get(f"/api/v1/imports/{batch['id']}/rows", params={"row_class": "job"}).json()
    assert rows["total"] == 4
    sample = rows["items"][0]
    assert "raw" in sample and "parsed" in sample  # raw preserved verbatim
    assert admin.get(f"/api/v1/imports/{batch['id']}").status_code == 200
    assert admin.get("/api/v1/imports").json()["total"] >= 1


def test_duplicate_file_conflicts(client_for, users):
    admin = client_for(users["admin"])
    data = _synthetic_bytes()
    assert _upload(admin, data).status_code == 201
    dup = client_for(users["admin"])
    assert _upload(dup, data).status_code == 409  # same sha256


def test_non_admin_cannot_ingest_or_inspect(client_for, users):
    support = client_for(users["support"])
    assert _upload(support, _synthetic_bytes()).status_code == 403
    assert support.get("/api/v1/imports").status_code == 403


def test_non_xlsx_rejected(client_for, users):
    admin = client_for(users["admin"])
    resp = admin.post(
        "/api/v1/imports",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400
