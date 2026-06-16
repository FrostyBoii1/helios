"""Section C: conservative "NMI = Same" carry-forward.

Pure, DB-free tests. A workbook NMI written as "Same"/"ditto" carries the
previous related row's meter forward ONLY when the address clearly normalises to
the same base property (allowing a leading House/Unit dwelling prefix).
Conservative by design: prefer leaving "Same" unresolved (a false negative) over
cross-linking two different properties' meters (a false positive).
"""

from __future__ import annotations

from io import BytesIO

import openpyxl

from app.services import import_parser
from app.services.import_parser import (
    _address_base,
    _is_nmi_same,
    _is_real_nmi,
    _same_base_property,
)

HEADERS = [
    "", "Sales Consultant", "Customer Name", "ADDRESS", "Phone", "Notes",
    "MSB/SB PICS IN FILE?", "Email", "Distributor", "Retailer", "NMI", "Meter No",
    "No of Panels", "Panel Brand/ Wattage", "Inverter Brand/Model", "Storey",
    "Phase", "Roof Type", "Date", "Day", "Time", "Installer",
]

# A real meter id whose 4204 prefix infers a distributor (NSW Essential), so a
# successful carry-forward clears the nmi_unmatched warning.
REAL_NMI = "42041234567"


def _job(ref: str, name: str, address: str, nmi: str) -> list[str]:
    """A workbook job row (SC#### ref -> classifies as 'job')."""
    cells = [""] * len(HEADERS)
    cells[0] = ref          # legacy reference
    cells[2] = name         # Customer Name
    cells[3] = address      # ADDRESS
    cells[4] = "0400000000"  # Phone
    cells[7] = "x@y.test"   # Email
    cells[10] = nmi         # NMI
    return cells


def _divider(text: str) -> list[str]:
    return [text] + [""] * (len(HEADERS) - 1)


def _parse(rows: list[list[str]]):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "COMPLETED"
    ws.append(HEADERS)
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    ws2 = openpyxl.load_workbook(BytesIO(buf.getvalue()), data_only=True)["COMPLETED"]
    return list(import_parser.parse_rows(ws2))


def _by_ref(rows, ref: str):
    return next(r for r in rows if r.legacy_reference == ref)


# --------------------------------------------------------------------------- #
# Parse-level behaviour
# --------------------------------------------------------------------------- #
def test_same_with_same_address_copies_nmi():
    rows = _parse([
        _job("SC9001", "Alex Roe", "10 Foo Street", REAL_NMI),
        _job("SC9002", "Alex Roe", "10 Foo Street", "Same"),
    ])
    src = _by_ref(rows, "SC9002")
    assert src.parsed["nmi_raw"] == REAL_NMI
    assert src.parsed["nmi_same_carried"] is True
    assert src.parsed["nmi_same_original"] == "Same"
    assert src.parsed["distributor_inferred"] == "NSW Essential"
    assert not any(i["kind"] == "nmi_unmatched" for i in src.issues)
    # The raw cell preserves the original "Same" token verbatim (non-scary context).
    assert src.raw["nmi"] == "Same"


def test_same_with_house_prefix_copies_nmi():
    rows = _parse([
        _job("SC9001", "Alex Roe", "10 Foo Street", REAL_NMI),
        _job("SC9002", "Bob Lee", "House 2 - 10 Foo Street", "Same"),
    ])
    src = _by_ref(rows, "SC9002")
    assert src.parsed["nmi_raw"] == REAL_NMI
    assert src.parsed["nmi_same_carried"] is True


def test_same_with_unit_prefix_copies_nmi():
    rows = _parse([
        _job("SC9001", "Alex Roe", "10 Foo Street", REAL_NMI),
        _job("SC9002", "Bob Lee", "Unit B - 10 Foo Street", "same"),
    ])
    assert _by_ref(rows, "SC9002").parsed["nmi_raw"] == REAL_NMI


def test_same_with_different_address_not_copied():
    rows = _parse([
        _job("SC9001", "Alex Roe", "10 Foo Street", REAL_NMI),
        _job("SC9002", "Alex Roe", "99 Bar Road", "Same"),
    ])
    src = _by_ref(rows, "SC9002")
    assert src.parsed["nmi_raw"] == "Same"          # unresolved
    assert src.parsed["nmi_same_carried"] is False
    assert any(i["kind"] == "nmi_unmatched" for i in src.issues)


def test_same_with_no_previous_nmi_not_copied():
    rows = _parse([
        _job("SC9001", "Alex Roe", "10 Foo Street", ""),     # no real previous NMI
        _job("SC9002", "Alex Roe", "10 Foo Street", "Same"),
    ])
    src = _by_ref(rows, "SC9002")
    assert src.parsed["nmi_raw"] == "Same"
    assert src.parsed["nmi_same_carried"] is False


def test_same_is_independent_of_customer_name():
    # Different names, same property -> still carries (no dependence on
    # same-customer / similar-name matching).
    carried = _parse([
        _job("SC9001", "Alex Roe", "10 Foo Street", REAL_NMI),
        _job("SC9002", "Zelda Quartz", "10 Foo Street", "Same"),
    ])
    assert _by_ref(carried, "SC9002").parsed["nmi_raw"] == REAL_NMI
    # Similar names but a DIFFERENT address -> not carried.
    not_carried = _parse([
        _job("SC9001", "Alex Roe", "10 Foo Street", REAL_NMI),
        _job("SC9002", "Alex Roe", "200 Other Avenue", "Same"),
    ])
    assert _by_ref(not_carried, "SC9002").parsed["nmi_raw"] == "Same"


def test_normal_nmi_is_unchanged():
    rows = _parse([_job("SC9001", "Alex Roe", "10 Foo Street", REAL_NMI)])
    src = _by_ref(rows, "SC9001")
    assert src.parsed["nmi_raw"] == REAL_NMI
    assert src.parsed["nmi_same_carried"] is False
    assert src.parsed["nmi_same_original"] is None
    assert src.parsed["distributor_inferred"] == "NSW Essential"
    assert not any(i["kind"] == "nmi_unmatched" for i in src.issues)


def test_unresolved_same_keeps_nmi_unmatched_issue():
    # A "Same" with no resolvable previous row behaves like any other unmatched
    # NMI: it keeps the existing review warning (issue behaviour stays stable).
    rows = _parse([_job("SC9001", "Alex Roe", "10 Foo Street", "Same")])
    src = _by_ref(rows, "SC9001")
    assert src.parsed["nmi_raw"] == "Same"
    assert any(i["kind"] == "nmi_unmatched" for i in src.issues)


def test_same_chains_across_secondary_dwellings():
    rows = _parse([
        _job("SC9001", "Alex Roe", "10 Foo Street", REAL_NMI),
        _job("SC9002", "Bob Lee", "House 2 - 10 Foo Street", "Same"),
        _job("SC9003", "Cara Fox", "House 3 - 10 Foo Street", "Same"),
    ])
    assert _by_ref(rows, "SC9002").parsed["nmi_raw"] == REAL_NMI
    assert _by_ref(rows, "SC9003").parsed["nmi_raw"] == REAL_NMI


def test_blank_row_does_not_reset_carry():
    rows = _parse([
        _job("SC9001", "Alex Roe", "10 Foo Street", REAL_NMI),
        [""] * len(HEADERS),  # incidental spacing
        _job("SC9002", "Alex Roe", "10 Foo Street", "Same"),
    ])
    assert _by_ref(rows, "SC9002").parsed["nmi_raw"] == REAL_NMI


def test_divider_resets_carry():
    rows = _parse([
        _job("SC9001", "Alex Roe", "10 Foo Street", REAL_NMI),
        _divider("FORTNIGHT 2"),
        _job("SC9002", "Alex Roe", "10 Foo Street", "Same"),
    ])
    src = _by_ref(rows, "SC9002")
    assert src.parsed["nmi_raw"] == "Same"            # carry context reset at divider
    assert src.parsed["nmi_same_carried"] is False


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_is_nmi_same_matches_only_same_markers():
    for v in ["Same", "same", "SAME", "  Same  ", "ditto", "as above",
              "same as above", '"Same"']:
        assert _is_nmi_same(v) is True, v
    for v in ["42041234567", "-", "", None, "same site", "sameish",
              "the same meter"]:
        assert _is_nmi_same(v) is False, v


def test_is_real_nmi():
    assert _is_real_nmi("42041234567") is True
    assert _is_real_nmi("QB051234") is True
    for v in [None, "", "-", "N/A", "n/a", "Same", "ABCDEF", "12345"]:
        assert _is_real_nmi(v) is False, v


def test_address_base_strips_only_leading_dwelling_prefix():
    assert _address_base("10 Foo Street") == "10 foo street"
    assert _address_base("  10   Foo   Street, ") == "10 foo street"
    assert _address_base("House 2 - 10 Foo Street") == "10 foo street"
    assert _address_base("Unit B - 10 Foo Street") == "10 foo street"
    assert _address_base("Flat 1/10 Foo Street") == "10 foo street"
    # A street that merely begins with a dwelling word is NOT stripped.
    assert _address_base("House Road") == "house road"
    assert _address_base(None) == ""


def test_same_base_property():
    assert _same_base_property("10 Foo Street", "House 2 - 10 Foo Street") is True
    assert _same_base_property("House 2 - 10 Foo St", "Unit 5 - 10 Foo St") is True
    assert _same_base_property("10 Foo Street", "99 Bar Road") is False
    assert _same_base_property("", "") is False
    assert _same_base_property(None, "10 Foo Street") is False
