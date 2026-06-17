"""Phase 2a tests: registry-shaped parsed.details + widened/full raw capture.

Synthetic data only. Covers the pure build_details (validate-or-divert, sections,
coercion, legacy-omit, MSB/Phase misfiling) and the parser's full-column capture
(widened WANTED_HEADERS + unmapped passthrough + parsed['details']).
"""

from __future__ import annotations

from io import BytesIO

import openpyxl

from app.services import import_parser
from app.services.import_details import (
    build_details,
    build_imported_notes,
    is_approval_context_note,
    is_empty_panel_placeholder,
    needs_approval_from_panels,
    render_legacy_blobs,
)


# --------------------------------------------------------------------------- #
# G (Stage 1): per-job site address in details.site
# --------------------------------------------------------------------------- #
def test_build_details_emits_site_from_parsed_address():
    parsed = {"address_parts": import_parser.parse_address("39 Example St, Cooma NSW 2866")}
    site = build_details(parsed, {"address": "39 Example St, Cooma NSW 2866"})["site"]
    assert site["line1"] == "39 Example St"
    assert site["suburb"] == "Cooma" and site["state"] == "NSW" and site["postcode"] == "2866"
    assert site["note"] is None and site["structured"] is True and site["line2"] is None
    assert site["raw"] == "39 Example St, Cooma NSW 2866"   # full original retained


def test_build_details_site_includes_peeled_note():
    raw_addr = "17 Daalbata Rd, Leeton 2705 NSW - 405 for the bill"
    parsed = {"address_parts": import_parser.parse_address(raw_addr)}
    site = build_details(parsed, {"address": raw_addr})["site"]
    assert site["line1"] == "17 Daalbata Rd" and site["suburb"] == "Leeton"
    assert site["note"] == "405 for the bill"               # F peeled note carried into site
    assert site["raw"] == raw_addr


def test_build_details_omits_site_when_no_address():
    assert "site" not in build_details({"address_parts": {}}, {})
    assert "site" not in build_details({}, {})


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


def test_approval_pending_date_in_structured_details():
    # Pending approval -> structured approval.pending_date (the live control reads it).
    d = build_details({"approval_state": "pending", "approval_pending_date": "19/08/2026"}, {})
    assert d["approval"]["pending_date"] == "19/08/2026"
    # Approved / none -> no approval section (state lives on the label, not here).
    assert "approval" not in build_details({"approval_state": "approved"}, {})
    assert "approval" not in build_details({"approval_state": "none"}, {})
    # Pending with no parsed date -> no section (nothing to store).
    assert "approval" not in build_details({"approval_state": "pending"}, {})


def test_build_imported_notes_p2_mapping():
    # P2 owner mapping: heading "Uncategorised Data on Import"; source-column
    # labels OMITTED; approval/reference context EXCLUDED; bare no-panel
    # placeholder EXCLUDED; useful context (name-cell, DOB, Lot/DP) KEPT verbatim.
    details = {
        "_v": 2,
        "notes": {
            "customer_name_notes": "HOUSE",
            "review_notes": [
                {"source_column": "Customer Name", "text": "Jemena Approval number 000410056"},
                {"source_column": "Sales Consultant", "text": "dob 23/11/55"},
                {"source_column": "No of Panels", "text": "-"},
            ],
            "misfiled": [{"source_column": "Customer Name", "text": "Lot 4 DP 588479"}],
        },
    }
    block = build_imported_notes(details)
    # 1. New heading, no trailing colon.
    assert block.startswith("Uncategorised Data on Import")
    assert "Imported notes:" not in block
    # 2. Source-column labels are gone (text only).
    for label in ("Customer Name:", "Name cell:", "No of Panels:", "Sales Consultant:"):
        assert label not in block
    # 3. Useful context kept, verbatim, as bare bullets.
    assert "- HOUSE" in block                  # name-cell note
    assert "- dob 23/11/55" in block           # DOB-like leftover
    assert "- Lot 4 DP 588479" in block        # Lot/DP descriptor
    # 4. Approval REFERENCE NUMBER kept (owner R2: useful operational context).
    assert "- Jemena Approval number 000410056" in block
    assert "000410056" in block
    # 5. Bare no-panel placeholder excluded.
    assert "- -" not in block


def test_build_imported_notes_excludes_bare_approval_keeps_reference():
    # Bare approval/status phrasing (no reference number) is kept OUT of internal notes.
    for txt in ("ERGON APPROVED", "pending approval", "Energex approved"):
        d = {"_v": 2, "notes": {"misfiled": [{"source_column": "X", "text": txt}]}}
        assert build_imported_notes(d) is None
    # But an approval REFERENCE NUMBER is preserved verbatim (owner R2).
    for txt in ("Jemena Approval number 000410056", "ENERGEX APPROVAL #000413493",
                "Approval ID# 000416253"):
        d = {"_v": 2, "notes": {"misfiled": [{"source_column": "X", "text": txt}]}}
        block = build_imported_notes(d)
        assert block is not None and txt in block


def test_build_imported_notes_dedupes_identical_lines():
    # Identical TEXT (regardless of source column) collapses to one bullet.
    dupe = {"_v": 2, "notes": {
        "review_notes": [{"source_column": "A", "text": "same"}],
        "misfiled": [{"source_column": "B", "text": "same"}],
    }}
    assert build_imported_notes(dupe).count("- same") == 1


def test_build_imported_notes_none_when_nothing_useful():
    # Nothing preserved, or only excluded junk -> None (internal_notes left blank).
    assert build_imported_notes({"_v": 2, "notes": {}}) is None
    assert build_imported_notes(None) is None
    only_junk = {"_v": 2, "notes": {
        "review_notes": [
            {"source_column": "No of Panels", "text": "-"},
            {"source_column": "Customer Name", "text": "Energex approved"},
        ],
    }}
    assert build_imported_notes(only_junk) is None


def test_p2_note_predicates():
    # is_approval_context_note: a BARE approval/status marker (no reference number)
    # is excludable context.
    assert is_approval_context_note("ERGON APPROVED")
    assert is_approval_context_note("approval pending")
    # R2: an approval REFERENCE NUMBER is NOT excludable — it is useful context.
    assert not is_approval_context_note("Jemena Approval number 000410056")
    assert not is_approval_context_note("ENERGEX APPROVAL #000413493")
    assert not is_approval_context_note("Approval ID# 000416253")
    # Useful, non-approval context is NOT treated as approval.
    for keep in ("HOUSE", "dob 23/11/55", "Lot 4 DP 588479", "FINALISE TO AGL",
                 "export limited", "pillar 111178023"):
        assert not is_approval_context_note(keep)
    # is_empty_panel_placeholder: bare dashes / blanks / no-value markers only.
    for junk in ("-", "--", "—", "", "   ", "n/a", "N/A", "nil", "No panels"):
        assert is_empty_panel_placeholder(junk)
    # Substantive panel/context text is NOT a placeholder.
    for keep in ("existing system - battery only", "6.6kw", "HOUSE", "Lot 4 DP 588479"):
        assert not is_empty_panel_placeholder(keep)


def test_suffix_notes_flow_into_generated_internal_notes():
    # R2: a stripped operational/source suffix is preserved verbatim and appears in
    # the generated On Commit / Job internal notes (not lost, not a scary panel).
    for raw, frag in [
        ("Kathleen Jones -8kw export", "8kw export"),
        ("Paul Neilsen and Carly Sorenson -booked 28/8", "booked 28/8"),
        ("Peter and Lesley Wenselowski -Jason check wiring to shed- hot water timer",
         "Jason check wiring to shed- hot water timer"),
        ("The Leeton Heritage Motor Inn- Wayne Bond- 2 invoices sent", "2 invoices sent"),
    ]:
        r = import_parser.parse_customer_name(raw)
        note = import_parser.clean_name_cell_notes(r["extracted"])
        details = build_details({"customer_name_notes": note}, {})
        block = build_imported_notes(details)
        assert block is not None and frag in block, (raw, block)


def test_needs_approval_from_panels_predicate():
    # The shared "Needs approval" heuristic: numeric panel_count > 0 AND inverter.
    def sysd(**s):
        return {"_v": 2, "system": s}
    # Qualifies: numeric panels > 0 + inverter present.
    assert needs_approval_from_panels(sysd(panel_count=10, inverter="Goodwe 5kw")) is True
    assert needs_approval_from_panels(sysd(panel_count=1, inverter="Solis 5kw")) is True
    # Excluded: no inverter / inverter-only / no numeric panels / zero / non-numeric.
    assert needs_approval_from_panels(sysd(panel_count=10)) is False          # no inverter
    assert needs_approval_from_panels(sysd(inverter="Goodwe 5kw")) is False    # inverter only
    assert needs_approval_from_panels(sysd(panel_count=0, inverter="x")) is False  # zero panels
    assert needs_approval_from_panels(sysd(inverter="x")) is False             # battery-only style
    assert needs_approval_from_panels(sysd()) is False                         # empty system
    assert needs_approval_from_panels({"_v": 2}) is False                      # no system section
    assert needs_approval_from_panels(None) is False
    # A non-numeric panel_count (build_details never coerces "-"/"existing") -> False.
    assert needs_approval_from_panels(sysd(panel_count="existing", inverter="x")) is False


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
