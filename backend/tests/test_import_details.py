"""Phase 2a tests: registry-shaped parsed.details + widened/full raw capture.

Synthetic data only. Covers the pure build_details (validate-or-divert, sections,
coercion, legacy-omit, MSB/Phase misfiling) and the parser's full-column capture
(widened WANTED_HEADERS + unmapped passthrough + parsed['details']).
"""

from __future__ import annotations

from io import BytesIO

import openpyxl

from app.services import import_parser
from app.services.import_details import build_details, render_legacy_blobs


# --------------------------------------------------------------------------- #
# Pure build_details
# --------------------------------------------------------------------------- #
def test_details_has_version_and_expected_sections():
    parsed = {
        "salesperson": "Rep", "no_of_panels": "16", "panel_raw": "Longi 440",
        "inverter_raw": "Goodwe 5kw", "nmi_raw": "42041234567", "meter_no": "M1",
        "distributor_inferred": "NSW Essential", "retailer_raw": "Origin",
        "install_day": "Mon", "installer_raw": "Installer One",
        "payment": {"total": "5000", "result": "paid"},
        "compliance": {"accreditation_code": "ACC1"},
        "msb_raw": "Yes",
    }
    raw = {"storey": "1", "phase": "3", "roof_type": "Tin"}
    d = build_details(parsed, raw)
    assert d["_v"] == 2
    assert d["system"]["panel_count"] == 16
    assert d["system"]["phase"] == "three"
    assert d["system"]["storey"] == "1"
    assert d["electrical"]["distributor"] == "NSW Essential"
    assert d["payment"]["total"] == "5000"
    assert d["compliance"]["msb_status"] == "yes"
    # legacy/flags/contacts/notes omitted when empty
    assert "legacy" not in d and "flags" not in d


def test_msb_free_text_becomes_blank_status_and_misfiled():
    d = build_details({"msb_raw": "DONT CALL PLEASE"}, {})
    assert "compliance" not in d or "msb_status" not in d.get("compliance", {})
    misfiled = d["notes"]["misfiled"]
    assert any(m["source_column"] == "MSB/SB PICS IN FILE?" for m in misfiled)
    # Recognized value still maps cleanly with no misfiling.
    d2 = build_details({"msb_raw": "No"}, {})
    assert d2["compliance"]["msb_status"] == "no"
    assert "notes" not in d2


def test_phase_invalid_free_text_diverted():
    d = build_details({}, {"phase": "check with sparky"})
    assert "system" not in d or "phase" not in d.get("system", {})
    assert any(m["source_column"] == "Phase" for m in d["notes"]["misfiled"])
    # Valid phase maps and is normalized.
    assert build_details({}, {"phase": "1"})["system"]["phase"] == "single"


def test_phase_two_normalizes_and_is_not_misfiled():
    # Two-phase is valid (owner decision): TWO/two/2/2 phase/two phase/2ph -> "two".
    for val in ("TWO", "two", "2", "2 phase", "two phase", "2ph"):
        d = build_details({}, {"phase": val})
        assert d["system"]["phase"] == "two", val
        assert not any(m["source_column"] == "Phase" for m in d.get("notes", {}).get("misfiled", [])), val


def test_post_install_status_and_date_captured_not_misfiled():
    # Pure date -> review_date only.
    d = build_details({}, {"post_install_review": "8/3/2023"})
    assert d["post_install"]["review_date"] == "2023-03-08"
    assert "review_status" not in d["post_install"]
    # Status only -> review_status, no misfile.
    d2 = build_details({}, {"post_install_review": "DONE"})
    assert d2["post_install"]["review_status"] == "DONE"
    assert "review_date" not in d2["post_install"]
    assert not any(
        m["source_column"].startswith("Date of Post") for m in d2.get("notes", {}).get("misfiled", [])
    )
    # Status + date -> both captured, no misfile.
    d3 = build_details({}, {"post_install_review": "Done 8/3/2023"})
    assert d3["post_install"]["review_status"] == "Done"
    assert d3["post_install"]["review_date"] == "2023-03-08"
    assert not any(
        m["source_column"].startswith("Date of Post") for m in d3.get("notes", {}).get("misfiled", [])
    )


def test_post_install_status_columns_captured_as_text_and_blank_omitted():
    # Warranty Rego Completed + Post Installation Email Sent -> post_install (text).
    d = build_details({}, {"warranty_rego_completed": "Yes", "post_install_email_sent": "Sent 10/2/2023"})
    assert d["post_install"]["warranty_rego_completed"] == "Yes"
    # Preserved verbatim — NOT coerced to a date.
    assert d["post_install"]["post_install_email_sent"] == "Sent 10/2/2023"
    # Blank values are omitted.
    d2 = build_details({}, {"warranty_rego_completed": "", "post_install_email_sent": "  "})
    assert "warranty_rego_completed" not in d2.get("post_install", {})
    assert "post_install_email_sent" not in d2.get("post_install", {})


def test_currency_and_int_coercion_with_divert():
    # Pure number coerces; trailing text is preserved as misfiled, value kept.
    d = build_details({"payment": {"total": "$12,345.67", "deposit": "5000 deposit paid"}}, {})
    assert d["payment"]["total"] == "12345.67"
    assert d["payment"]["deposit"] == "5000"
    assert any(m["source_column"] == "Deposit" for m in d["notes"]["misfiled"])
    # Non-numeric -> blank field + misfiled, nothing coerced.
    d2 = build_details({"payment": {"balance": "paid cash"}}, {})
    assert "payment" not in d2 or "balance" not in d2.get("payment", {})
    assert any(m["source_column"] == "Balance" for m in d2["notes"]["misfiled"])
    # int
    assert build_details({"no_of_panels": "16"}, {})["system"]["panel_count"] == 16


def test_approval_phrase_routes_to_review_notes_not_misfiled():
    # A distributor approval / reference phrase lifted off the name cell is NEUTRAL
    # review context, not a misfiled warning. (The status it implies is captured
    # separately in parsed.approval_state by the parser — unchanged.)
    d = build_details({"name_cell_approval_phrase": "Jemena Approval # 000413493"}, {})
    review = [m["text"] for m in d["notes"]["review_notes"]]
    assert "Jemena Approval # 000413493" in review
    assert not any(m["source_column"] == "Customer Name" for m in d["notes"].get("misfiled", []))
    # A land/legal descriptor still goes to the misfiled SOURCE-note bucket.
    d2 = build_details({"name_cell_land_descriptor": "Lot 7 DP 123"}, {})
    assert any(m["text"] == "Lot 7 DP 123" for m in d2["notes"]["misfiled"])
    assert "review_notes" not in d2.get("notes", {})


def test_sales_consultant_remainder_is_review_note_not_misfiled():
    # The leftover after a sales-cell sale date (a DOB / free-note) is neutral
    # review context, never a misfiled warning, never coerced into the salesperson.
    d = build_details({"salesperson": "Robert W", "sales_consultant_misfiled": "dob 23/11/55"}, {})
    assert any(
        m["source_column"] == "Sales Consultant" and m["text"] == "dob 23/11/55"
        for m in d["notes"]["review_notes"]
    )
    assert not any(m["source_column"] == "Sales Consultant" for m in d["notes"].get("misfiled", []))


def test_nonnumeric_panel_text_routes_to_review_notes_and_does_not_misfile():
    # Battery / inverter-only jobs have non-numeric panel cells — neutral review
    # note, never a misfiled warning, and never an error (the parser raises no panel
    # issue at all, so a non-numeric panel count cannot block a commit).
    d = build_details({"no_of_panels": "existing system - battery only"}, {})
    assert "panel_count" not in d.get("system", {})
    assert any(
        m["source_column"] == "No of Panels" and "battery only" in m["text"]
        for m in d["notes"]["review_notes"]
    )
    assert not any(m["source_column"] == "No of Panels" for m in d["notes"].get("misfiled", []))
    # A clean numeric count still coerces with no note at all.
    d2 = build_details({"no_of_panels": "16"}, {})
    assert d2["system"]["panel_count"] == 16
    assert "notes" not in d2


def test_legacy_present_only_when_populated():
    d = build_details({}, {"solar_vic": "100", "ces_submission": "done"})
    assert d["legacy"]["solar_vic"] == "100"
    assert d["legacy"]["ces_submission"] == "done"


def test_flags_and_contacts_carried():
    parsed = {
        "removes_old_system": True, "decommission_marker": "REMOVE OLD SYSTEM",
        "phones": [{"number": "0400000000", "label": ""}, {"number": "0411111111", "label": "Mum"}],
        "emails": ["a@example.test", "b@example.test"],
        "customer_name_notes": "includes hot water timer",
    }
    d = build_details(parsed, {})
    assert d["flags"]["removes_old_system"] is True
    assert len(d["contacts"]["extra_phones"]) == 1
    assert len(d["contacts"]["extra_emails"]) == 1
    assert d["notes"]["customer_name_notes"] == "includes hot water timer"


# --------------------------------------------------------------------------- #
# Parser full-column capture (widened WANTED_HEADERS + unmapped passthrough)
# --------------------------------------------------------------------------- #
_HEADERS = [
    "", "Sales Consultant", "Customer Name", "ADDRESS", "Phone", "Notes",
    "MSB/SB PICS IN FILE?", "Email", "Distributor", "Retailer", "NMI", "Meter No",
    "No of Panels", "Panel Brand/ Wattage", "Inverter Brand/Model", "Storey",
    "Phase", "Roof Type", "Date", "Day", "Time", "Installer", "Welcome Call",
    "Total", "Deposit", "Balance", "Result of payment", "Notes on payment",
    "Accreditation Code", "STC Amount", "Solar Vic Payment",
    "Date of Post Installation Call/Review Request",
    "CES/ECOC/CCEW to Retailer Email - All other distributors",
    "CES Submission to Distributor Ausnet/Powercor/United/Jemena",
    "Warranty Rego Completed", "Post Installation Email Sent",  # now structured post_install
    "Some Unknown Column",  # genuinely not in registry -> _unmapped passthrough
]


def _one_row_ws():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "COMPLETED"
    ws.append(_HEADERS)
    ws.append([
        "TESTIMP0001", "Rep 10/10/2025", "Alex Roe", "1 Test St", "0400000000", "",
        "Yes", "a@example.test", "Essential", "Origin", "42041234567", "M1",
        "10", "Longi 440", "Goodwe 5kw", "1", "3", "Tin", "", "", "", "Installer One",
        "", "$5000", "1000", "4000", "paid", "", "ACC1", "$2000", "", "", "", "",
        "Yes", "Done", "junk-extra",
    ])
    buf = BytesIO()
    wb.save(buf)
    return openpyxl.load_workbook(BytesIO(buf.getvalue()), data_only=True)["COMPLETED"]


def test_parser_captures_widened_headers_and_unmapped_passthrough():
    rows = list(import_parser.parse_rows(_one_row_ws()))
    row = next(r for r in rows if r.legacy_reference == "TESTIMP0001")
    # Widened headers now captured into raw under canonical keys.
    assert "stc_amount" in row.raw and row.raw["stc_amount"] == "$2000"
    assert "solar_vic" in row.raw and "post_install_review" in row.raw
    assert "ces_ecoc_email" in row.raw and "ces_submission" in row.raw
    # Post-install status columns are now KNOWN headers (not _unmapped).
    assert row.raw["warranty_rego_completed"] == "Yes"
    assert row.raw["post_install_email_sent"] == "Done"
    assert "Warranty Rego Completed" not in row.raw["_unmapped"]
    assert "Post Installation Email Sent" not in row.raw["_unmapped"]
    # A genuinely unmapped column is still preserved verbatim, never dropped.
    assert row.raw["_unmapped"]["Some Unknown Column"] == "junk-extra"
    # Structured details stamped onto parsed.
    d = row.parsed["details"]
    assert d["_v"] == 2
    assert d["system"]["phase"] == "three" and d["system"]["storey"] == "1"
    assert d["payment"]["total"] == "5000" and d["payment"]["stc_amount"] == "2000"
    assert d["compliance"]["msb_status"] == "yes"
    # Post-install status columns land in details.post_install as text.
    assert d["post_install"]["warranty_rego_completed"] == "Yes"
    assert d["post_install"]["post_install_email_sent"] == "Done"
    assert "legacy" not in d  # solar_vic / ces_submission blank in this row
    # Flat parsed keys still present (back-compat).
    assert row.parsed["customer_name"] == "Alex Roe"
    assert row.parsed["msb_state"] == "yes"


# --------------------------------------------------------------------------- #
# render_legacy_blobs (Phase 2b) — derived legacy text blobs
# --------------------------------------------------------------------------- #
def _full_details():
    return {
        "_v": 2,
        "sales": {"salesperson_text": "Rep"},
        "system": {"panel_count": 16, "panel": "Longi 440", "phase": "three"},
        "electrical": {"nmi": "42041234567", "distributor": "NSW Essential"},
        "install": {"day": "Mon", "installer": "Installer One"},
        "payment": {"total": "5000", "stc_amount": "2000"},
        "compliance": {"msb_status": "yes", "accreditation": "ACC1"},
        "flags": {"removes_old_system": True, "decommission_marker": "REMOVE OLD SYSTEM"},
        "legacy": {"solar_vic": "100"},
        "notes": {
            "customer_name_notes": "includes hot water timer",
            "misfiled": [{"source_column": "Phase", "text": "ask sparky"}],
            "review_notes": [{"source_column": "Customer Name", "text": "Jemena Approval # 000413"}],
        },
    }


def test_render_blobs_from_details():
    parsed = {"approval_state": "approved", "notes_raw": "call first"}
    b = render_legacy_blobs(_full_details(), parsed, batch_id=9, source_row_index=42, legacy_reference="R1")
    # system_details from system+electrical+MSB; install_details from install.
    assert "Panels: 16" in b["system_details"] and "Phase: three" in b["system_details"]
    assert "MSB: yes" in b["system_details"]
    assert "Installer: Installer One" in b["install_details"]
    assert b["approval_details"] == "Approval: approved"  # approval preserved from parsed
    notes = b["notes"]
    # Order: decommission first, then name-cell, salesperson, payment, compliance,
    # free-text notes, misfiled, legacy, provenance (last).
    assert notes.splitlines()[0].startswith("REMOVE OLD SYSTEM")
    assert "From name cell: includes hot water timer" in notes
    assert "Salesperson: Rep" in notes
    assert "Payment — " in notes and "stc_amount: 2000" in notes
    assert "Notes: call first" in notes
    # Source/review notes use neutral, non-scary labels (no "Misfiled").
    assert "Imported review note — Customer Name: Jemena Approval # 000413" in notes
    assert "Imported source note — Phase: ask sparky" in notes
    assert "Misfiled" not in notes
    assert "Legacy — solar_vic: 100" in notes
    assert notes.splitlines()[-1] == "Imported from legacy workbook (batch 9, row 42, ref R1)."


def test_render_blobs_omit_blank_and_legacy_only_when_populated():
    b = render_legacy_blobs({"_v": 2}, {}, batch_id=1, source_row_index=2, legacy_reference=None)
    assert b["system_details"] is None and b["install_details"] is None
    assert b["approval_details"] is None
    # Only the provenance line remains; no Legacy line when legacy is empty.
    assert b["notes"] == "Imported from legacy workbook (batch 1, row 2)."
    assert "Legacy" not in b["notes"]
