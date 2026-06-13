"""Tests for the read-only date-orientation audit (pre-C1 diagnostic).

Synthetic dates only. Day names are derived from the constructed dates so the
assertions don't hardcode a calendar.
"""

from __future__ import annotations

from datetime import date

from app.services import import_date_audit as audit


def test_swapped_date_validity():
    # 02/03/2026 read as MM/DD -> 3 Feb 2026.
    assert audit.swapped_date("02/03/2026") == date(2026, 2, 3)
    # 25/12/2026 cannot be MM/DD (month 25) -> no valid swap.
    assert audit.swapped_date("25/12/2026") is None
    assert audit.swapped_date("not a date") is None


def test_existing_match():
    # 02/03/2026 (DD/MM) = 2 Mar 2026; Day column agrees with the DD/MM reading.
    existing = date(2026, 3, 2)
    swapped = date(2026, 2, 3)
    assert existing.weekday() != swapped.weekday()  # the two readings differ
    a = audit.analyze_row("02/03/2026", existing.strftime("%A"))
    assert a["category"] == "existing_match"
    assert a["existing_matches"] and not a["swapped_matches"]


def test_swapped_match_signals_coercion():
    # Day column agrees with the SWAPPED (MM/DD) reading -> likely US coercion.
    swapped = date(2026, 2, 3)
    a = audit.analyze_row("02/03/2026", swapped.strftime("%A"))
    assert a["category"] == "swapped_match"
    assert a["swapped_matches"] and not a["existing_matches"]


def test_both_match_when_day_equals_month():
    # 01/01/2026 reads the same both ways -> ambiguous.
    d = date(2026, 1, 1)
    a = audit.analyze_row("01/01/2026", d.strftime("%A"))
    assert a["category"] == "both_match"


def test_neither_match():
    # A deliberately wrong Day for 01/01/2026 (Thursday) -> neither reading fits.
    a = audit.analyze_row("01/01/2026", "Monday")  # 2026-01-01 is Thursday
    assert a["category"] == "neither_match"


def test_swap_invalid_branch():
    # 25/12/2026: only DD/MM is a valid date; wrong Day -> mismatch w/ invalid swap.
    a = audit.analyze_row("25/12/2026", "Sunday")  # 2026-12-25 is Friday
    assert a["category"] == "neither_match"
    assert a["swap_valid"] is False


def test_no_date_or_day():
    assert audit.analyze_row("", "Monday")["category"] == "no_date_or_day"
    assert audit.analyze_row("02/03/2026", "")["category"] == "no_date_or_day"
    assert audit.analyze_row("02/03/2026", "garbage")["category"] == "no_date_or_day"


def test_day_abbreviation_tolerated():
    existing = date(2026, 3, 2)
    assert audit.analyze_row("02/03/2026", existing.strftime("%a"))["existing_matches"]  # "Mon"
    assert audit.analyze_row("02/03/2026", "MONDAY ")["existing_matches"]


def test_summarize_aggregates():
    existing = date(2026, 3, 2)   # DD/MM reading
    swapped = date(2026, 2, 3)    # MM/DD reading
    rows = [
        {"install_date": "02/03/2026", "install_day": existing.strftime("%A")},  # existing_match
        {"install_date": "02/03/2026", "install_day": swapped.strftime("%A")},   # swapped_match
        {"install_date": "01/01/2026", "install_day": "Monday"},                 # neither (Thu)
        {"install_date": "", "install_day": "Monday"},                           # no_date_or_day
        None,                                                                     # ignored
    ]
    s = audit.summarize(rows)
    assert s["rows_with_date_and_day"] == 3
    assert s["by_category"]["existing_match"] == 1
    assert s["by_category"]["swapped_match"] == 1
    assert s["by_category"]["neither_match"] == 1
    assert s["existing_mismatch_total"] == 2          # swapped_match + neither_match
    assert s["mismatch_swap_fixes"] == 1              # the swapped_match row
