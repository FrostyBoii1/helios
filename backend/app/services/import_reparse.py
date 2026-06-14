"""In-place additive reparse of staged import rows (one-off maintenance).

Backfills the *additive, parser-owned* fields that were introduced after a batch
was staged — `customer_name_notes`, `removes_old_system`, `decommission_marker`
— from each row's immutable `raw` cells, WITHOUT touching reviewer-owned parsed
fields, review state, committed links, issues, `raw`, batch status, or any live
record.

Design:
  * `compute_additive_patch` is a pure, DB-free helper (unit-testable): given a
    row's `raw` and a target dict (its `parsed` or `original_parsed`), it returns
    the <=3-key patch that should be merged in — and ONLY keys whose value would
    actually change (so an up-to-date row yields `{}` → idempotent).
  * Write policy:
      - `removes_old_system` / `decommission_marker` are parser-owned (not in the
        reviewer edit whitelist) → derived and set, but only as a POSITIVE signal
        (we never write `False`/`None`; absence already reads as "no removal").
      - `customer_name_notes` is reviewer-editable → fill ONLY when empty, so a
        reviewer's curated note is never clobbered.
  * `original_parsed` mirroring: when a row was edited (snapshot present), the
    same additive keys are mirrored into `original_parsed` so the review UI's
    "Edited" badge does not falsely flag these parser-owned fields. We never
    create `original_parsed` where it is currently null.

No schema migration: the three fields are additive JSONB keys on existing
columns. The thin CLI lives in
`backend/scripts/reparse_additive_import_fields.py`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.import_staging import ImportRow
from app.services.import_parser import (
    clean_name_cell_notes,
    detect_decommission,
    parse_customer_name,
)

# Scope: pending + approved only (rejected/skipped intentionally excluded).
ELIGIBLE_STATUSES: tuple[str, ...] = ("pending", "approved")
ELIGIBLE_CLASSES: tuple[str, ...] = ("job", "ambiguous")
# The only keys this maintenance ever writes.
ADDITIVE_KEYS: tuple[str, ...] = (
    "customer_name_notes",
    "removes_old_system",
    "decommission_marker",
)


def _s(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def compute_additive_patch(
    raw: dict | None,
    parsed: dict | None,
    original_parsed: dict | None = None,
) -> dict[str, Any]:
    """Return the additive patch (<=3 keys) to merge into `parsed`.

    Derives the fields from the immutable `raw` name + notes cells, so the result
    is independent of any reviewer edit to `parsed`. Only keys whose value would
    change are returned (an already-current row yields `{}`).

    `original_parsed` is accepted for signature symmetry; the patch for a target
    dict is derived purely from `raw`, so mirroring into `original_parsed` is done
    by the caller invoking this with `original_parsed` passed as `parsed`.
    """
    raw = raw or {}
    parsed = parsed or {}

    name_cell = _s(raw.get("customer_name"))
    notes_cell = _s(raw.get("notes"))
    info = parse_customer_name(name_cell)
    note = clean_name_cell_notes(info["extracted"])
    marker = detect_decommission(name_cell, info["extracted"], notes_cell)

    patch: dict[str, Any] = {}
    # Parser-owned positive signal only (never write False/None).
    if marker is not None:
        if parsed.get("removes_old_system") is not True:
            patch["removes_old_system"] = True
        if parsed.get("decommission_marker") != marker:
            patch["decommission_marker"] = marker
    # Reviewer-editable: fill only when currently empty.
    if note and not _s(parsed.get("customer_name_notes")).strip():
        patch["customer_name_notes"] = note
    return patch


def compute_note_refresh(
    raw: dict | None,
    parsed: dict | None,
    original_parsed: dict | None,
) -> tuple[str | None, str]:
    """Refresh decision for an EXISTING ``customer_name_notes`` (refresh mode).

    Returns ``(new_value, category)``:
      * ``(<note>, "change")``  -> safe to overwrite with the freshly-cleaned note
      * ``(None, "original_parsed_exists")`` -> reviewer-edited, never overwrite
      * ``(None, "empty_new")`` -> new note cleans to empty; keep existing (conservative)
      * ``(None, "same")`` -> already matches the current parser; nothing to do

    Only meaningful for a row that already holds a non-empty note; callers gate
    the "candidate" universe on that. Priority order matches the dry-run report:
    reviewer-edit guard first, then empty-new, then same, else change.
    """
    cur = _s((parsed or {}).get("customer_name_notes"))
    info = parse_customer_name(_s((raw or {}).get("customer_name")))
    new = clean_name_cell_notes(info["extracted"])
    if original_parsed is not None:
        return None, "original_parsed_exists"
    if not new.strip():
        return None, "empty_new"
    if new == cur:
        return None, "same"
    return new, "change"


# --------------------------------------------------------------------------- #
# Row selection + classification (for the dry-run report)
# --------------------------------------------------------------------------- #
def _candidates_stmt(batch_id: int):
    """Rows in scope: pending/approved, job/ambiguous, no committed link."""
    return select(ImportRow).where(
        ImportRow.batch_id == batch_id,
        ImportRow.review_status.in_(ELIGIBLE_STATUSES),
        ImportRow.row_class.in_(ELIGIBLE_CLASSES),
        ImportRow.committed_customer_id.is_(None),
        ImportRow.committed_job_id.is_(None),
    )


def _is_committed_reversed_or_linked(row: ImportRow) -> bool:
    return (
        row.review_status in ("committed", "reversed")
        or row.committed_customer_id is not None
        or row.committed_job_id is not None
    )


def plan_reparse(db: Session, batch_id: int, *, samples: int = 10, refresh_notes: bool = False) -> dict:
    """Read-only dry-run. Returns a summary dict and writes NOTHING.

    With ``refresh_notes=True`` the report additionally classifies, for gated
    rows that already hold a non-empty ``customer_name_notes``, whether a
    parser-note refresh would overwrite it (see ``compute_note_refresh``). The
    fill-only additive counters are unchanged.
    """
    rows = db.scalars(
        select(ImportRow).where(ImportRow.batch_id == batch_id).order_by(ImportRow.source_row_index)
    ).all()

    s = {
        "batch_id": batch_id,
        "refresh_notes": refresh_notes,
        "rows_total": len(rows),
        "rows_considered": 0,
        "rows_would_change": 0,
        "name_notes_gained": 0,
        "removes_old_system_gained": 0,
        "decommission_marker_gained": 0,
        "considered_no_change": 0,
        "of_which_already_set": 0,
        "of_which_no_signal": 0,
        "skipped_committed_reversed_linked": 0,
        "skipped_wrong_status": 0,
        "skipped_blank_divider_nonjob": 0,
        "sample_name_notes_src": [],
        "sample_decom_src": [],
        # Refresh-mode counters (populated only when refresh_notes=True).
        "refresh_candidates": 0,
        "refresh_would_change": 0,
        "skipped_original_parsed_exists": 0,
        "skipped_empty_new_note": 0,
        "skipped_same_note": 0,
        "sample_refresh_src": [],
    }

    for r in rows:
        if _is_committed_reversed_or_linked(r):
            s["skipped_committed_reversed_linked"] += 1
            continue
        if r.row_class not in ELIGIBLE_CLASSES:
            s["skipped_blank_divider_nonjob"] += 1
            continue
        if r.review_status not in ELIGIBLE_STATUSES:
            s["skipped_wrong_status"] += 1
            continue

        s["rows_considered"] += 1

        # Refresh-mode classification: only rows that already hold a note.
        if refresh_notes and _s((r.parsed or {}).get("customer_name_notes")).strip():
            s["refresh_candidates"] += 1
            _val, cat = compute_note_refresh(r.raw, r.parsed, r.original_parsed)
            if cat == "change":
                s["refresh_would_change"] += 1
                if len(s["sample_refresh_src"]) < samples:
                    s["sample_refresh_src"].append(r.source_row_index)
            elif cat == "original_parsed_exists":
                s["skipped_original_parsed_exists"] += 1
            elif cat == "empty_new":
                s["skipped_empty_new_note"] += 1
            elif cat == "same":
                s["skipped_same_note"] += 1

        p_patch = compute_additive_patch(r.raw, r.parsed)
        op_patch = (
            compute_additive_patch(r.raw, r.original_parsed)
            if r.original_parsed is not None
            else {}
        )
        if not p_patch and not op_patch:
            s["considered_no_change"] += 1
            # Distinguish "already set" (a signal exists but is present) from
            # "no signal" (nothing derivable from raw).
            name_cell = _s((r.raw or {}).get("customer_name"))
            info = parse_customer_name(name_cell)
            has_signal = bool(clean_name_cell_notes(info["extracted"])) or (
                detect_decommission(name_cell, info["extracted"], _s((r.raw or {}).get("notes")))
                is not None
            )
            s["of_which_already_set" if has_signal else "of_which_no_signal"] += 1
            continue

        s["rows_would_change"] += 1
        if "customer_name_notes" in p_patch:
            s["name_notes_gained"] += 1
            if len(s["sample_name_notes_src"]) < samples:
                s["sample_name_notes_src"].append(r.source_row_index)
        if "removes_old_system" in p_patch:
            s["removes_old_system_gained"] += 1
            if len(s["sample_decom_src"]) < samples:
                s["sample_decom_src"].append(r.source_row_index)
        if "decommission_marker" in p_patch:
            s["decommission_marker_gained"] += 1

    return s


def apply_reparse(db: Session, batch_id: int, *, refresh_notes: bool = False) -> dict:
    """Apply the additive patch to in-scope rows in one transaction.

    Writes ONLY `parsed` (and `original_parsed` when it already exists). Leaves
    `raw`, issues, `review_status`, `reviewer_id`, `reviewed_at`, committed links,
    and batch status untouched. Idempotent.

    With ``refresh_notes=True`` it additionally overwrites a row's existing,
    non-empty ``customer_name_notes`` with the freshly-cleaned parser output when
    ``compute_note_refresh`` returns ``"change"`` (reviewer-edited rows, empty-new
    notes, and unchanged notes are left alone). With ``refresh_notes=False`` the
    behaviour is exactly the original fill-only path.
    """
    rows = db.scalars(_candidates_stmt(batch_id)).all()
    counts = {
        "batch_id": batch_id,
        "refresh_notes": refresh_notes,
        "rows_changed": 0,
        "name_notes_gained": 0,
        "removes_old_system_gained": 0,
        "decommission_marker_gained": 0,
        "original_parsed_mirrored": 0,
        "notes_refreshed": 0,
    }

    for r in rows:
        p_patch = compute_additive_patch(r.raw, r.parsed)
        op_patch = (
            compute_additive_patch(r.raw, r.original_parsed)
            if r.original_parsed is not None
            else {}
        )
        # Refresh overwrite (refresh mode only): disjoint from the fill-only note
        # in p_patch — that only fires on an EMPTY note, this only on a non-empty one.
        new_note: str | None = None
        if refresh_notes and _s((r.parsed or {}).get("customer_name_notes")).strip():
            val, cat = compute_note_refresh(r.raw, r.parsed, r.original_parsed)
            if cat == "change":
                new_note = val

        if not p_patch and not op_patch and new_note is None:
            continue

        if p_patch:
            # Reassign a new dict so SQLAlchemy tracks the JSONB change.
            r.parsed = {**(r.parsed or {}), **p_patch}
        if new_note is not None:
            r.parsed = {**(r.parsed or {}), "customer_name_notes": new_note}
        if op_patch:
            r.original_parsed = {**(r.original_parsed or {}), **op_patch}
            counts["original_parsed_mirrored"] += 1

        counts["rows_changed"] += 1
        counts["name_notes_gained"] += int("customer_name_notes" in p_patch)
        counts["removes_old_system_gained"] += int("removes_old_system" in p_patch)
        counts["decommission_marker_gained"] += int("decommission_marker" in p_patch)
        counts["notes_refreshed"] += int(new_note is not None)

    db.commit()
    return counts
