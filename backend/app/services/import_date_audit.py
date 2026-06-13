"""Read-only date-orientation audit for imported install dates.

The legacy workbook's install dates are paired with a free-text "Day" column
(e.g. "Monday"). When Excel coerces a DD/MM date into MM/DD (US) order, the
parsed weekday stops matching the Day column. This module is a PURE, read-only
analysis that, per row, compares the existing (DD/MM) parse and the swapped
(MM/DD) parse against the Day column, so we can tell whether the workbook should
be read DD/MM, MM/DD, or whether only some rows are ambiguous/mis-coerced.

It does NOT change how dates are parsed and writes nothing. It is purely
diagnostic — the actual parsing rule (if any) is a separate, owner-gated change.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from datetime import date

from app.services.import_parser import parse_date_maybe

_DMY = re.compile(r"^\s*([0-3]?\d)[/\-]([0-1]?\d)[/\-](\d{2,4})\s*$")
_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def _day_index(day_str: str | None) -> int | None:
    """Map a free-text day cell to a weekday index (0=Mon), prefix-tolerant.

    Accepts 'Monday', 'Mon', 'MONDAY ', etc. Returns None if unrecognised.
    """
    s = (day_str or "").strip().lower()
    if not s:
        return None
    for i, name in enumerate(_WEEKDAYS):
        if s.startswith(name[:3]):
            return i
    return None


def swapped_date(date_str: str | None) -> date | None:
    """Read a d/m/y string as m/d/y (US) instead. None if not d/m/y or invalid."""
    m = _DMY.match(date_str or "")
    if not m:
        return None
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y += 2000 if y < 100 else 0
    try:
        return date(y, a, b)  # a treated as month, b as day (the swap)
    except ValueError:
        return None


def analyze_row(install_date_str: str | None, install_day_str: str | None) -> dict:
    """Classify one row's date/day relationship. Pure; no DB, no mutation."""
    existing = parse_date_maybe((install_date_str or "").strip())
    swapped = swapped_date(install_date_str)
    day_idx = _day_index(install_day_str)

    if existing is None or day_idx is None:
        return {
            "category": "no_date_or_day",
            "existing_matches": False,
            "swapped_matches": False,
            "swap_valid": swapped is not None,
            "swap_distinct": swapped is not None and swapped != existing,
        }

    ex_match = existing.weekday() == day_idx
    sw_match = swapped is not None and swapped.weekday() == day_idx
    if ex_match and sw_match:
        category = "both_match"      # ambiguous (e.g. day==month)
    elif ex_match:
        category = "existing_match"  # current DD/MM reading is consistent
    elif sw_match:
        category = "swapped_match"   # MM/DD reading is consistent → likely coerced
    else:
        category = "neither_match"   # genuine inconsistency / bad data
    return {
        "category": category,
        "existing_matches": ex_match,
        "swapped_matches": sw_match,
        "swap_valid": swapped is not None,
        "swap_distinct": swapped is not None and swapped != existing,
    }


def summarize(parsed_rows: Iterable[dict | None]) -> dict:
    """Aggregate analyze_row over many parsed candidates. Read-only.

    `parsed_rows` are the `parsed` dicts (uses install_date + install_day).
    Returns aggregate counts only — no per-row PII.
    """
    cats: Counter[str] = Counter()
    rows_with_date_and_day = 0
    existing_mismatch = 0
    mismatch_swap_fixes = 0
    mismatch_swap_invalid = 0
    mismatch_swap_also_wrong = 0

    for p in parsed_rows:
        if not p:
            continue
        a = analyze_row(p.get("install_date"), p.get("install_day"))
        cats[a["category"]] += 1
        if a["category"] == "no_date_or_day":
            continue
        rows_with_date_and_day += 1
        if not a["existing_matches"]:
            existing_mismatch += 1
            if a["swapped_matches"]:
                mismatch_swap_fixes += 1
            elif not a["swap_valid"]:
                mismatch_swap_invalid += 1
            else:
                mismatch_swap_also_wrong += 1

    return {
        "rows_with_date_and_day": rows_with_date_and_day,
        "by_category": dict(cats),
        # Of rows where the current DD/MM parse does NOT match the Day column:
        "existing_mismatch_total": existing_mismatch,
        "mismatch_swap_fixes": mismatch_swap_fixes,        # swap to MM/DD would match
        "mismatch_swap_also_wrong": mismatch_swap_also_wrong,  # neither reading matches
        "mismatch_swap_invalid": mismatch_swap_invalid,    # only DD/MM is a valid date
    }
