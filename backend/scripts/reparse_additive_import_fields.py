#!/usr/bin/env python
"""In-place additive reparse of a staged import batch (one-off maintenance CLI).

Backfills the additive, parser-owned fields that were added after a batch was
staged — customer_name_notes, removes_old_system, decommission_marker — from
each row's immutable raw cells, using the current parser logic. It NEVER touches
committed/reversed rows, rows with a live link, reviewer-owned parsed fields,
review state, issues, raw, batch status, or any live Customer/Job/Activity.

The logic lives in the shared, testable service `app.services.import_reparse`;
this is a thin CLI wrapper.

Usage:
    # Dry-run (default — writes nothing):
    python backend/scripts/reparse_additive_import_fields.py --batch-id 388

    # Apply (explicit; writes only the three additive fields, one transaction):
    python backend/scripts/reparse_additive_import_fields.py --batch-id 388 --apply

The batch id is always supplied as an argument — never hardcoded.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the backend root importable regardless of the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Load-bearing: registers all ORM models so string-based relationships (e.g.
# ImportBatch -> User) resolve before the first query.
from app.db import base as _model_registry  # noqa: E402,F401
from app.db.session import SessionLocal  # noqa: E402
from app.services import import_reparse  # noqa: E402


def _mode_label(refresh: bool) -> str:
    return "REFRESH-PARSER-NOTES" if refresh else "FILL-ONLY"


def _print_plan(s: dict) -> None:
    print(f"=== Additive reparse DRY-RUN — batch {s['batch_id']} — {_mode_label(s['refresh_notes'])} mode ===")
    print(f"rows total ................................ {s['rows_total']}")
    print(f"rows considered (pending/approved job rows) {s['rows_considered']}")
    print(f"rows would change (fill-only additive) .... {s['rows_would_change']}")
    print(f"  customer_name_notes gained .............. {s['name_notes_gained']}")
    print(f"  removes_old_system gained ............... {s['removes_old_system_gained']}")
    print(f"  decommission_marker gained .............. {s['decommission_marker_gained']}")
    print(f"considered, no change ..................... {s['considered_no_change']}")
    print(f"  of which already set/preserved .......... {s['of_which_already_set']}")
    print(f"  of which no signal in raw ............... {s['of_which_no_signal']}")
    print(f"skipped committed/reversed/linked ......... {s['skipped_committed_reversed_linked']}")
    print(f"skipped wrong status (rejected/skipped) ... {s['skipped_wrong_status']}")
    print(f"skipped blank/divider/non-job ............. {s['skipped_blank_divider_nonjob']}")
    print(f"sample src rows w/ name-notes ............. {s['sample_name_notes_src']}")
    print(f"sample src rows w/ decommission ........... {s['sample_decom_src']}")
    if s["refresh_notes"]:
        print("--- REFRESH-PARSER-NOTES (overwrite of existing parser-derived notes) ---")
        print(f"refresh candidates (rows with a note) ..... {s['refresh_candidates']}")
        print(f"  refresh would change .................... {s['refresh_would_change']}")
        print(f"  skipped original_parsed exists ......... {s['skipped_original_parsed_exists']}")
        print(f"  skipped empty new note ................. {s['skipped_empty_new_note']}")
        print(f"  skipped same note ...................... {s['skipped_same_note']}")
        print(f"  sample src rows (refresh) .............. {s['sample_refresh_src']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Additive in-place reparse of a staged import batch.")
    ap.add_argument("--batch-id", type=int, required=True, help="ImportBatch id to reparse.")
    ap.add_argument("--apply", action="store_true", help="Write changes (default is dry-run).")
    ap.add_argument(
        "--refresh-parser-notes",
        action="store_true",
        help="Also OVERWRITE an existing parser-derived customer_name_notes with the "
        "freshly-cleaned output (only when never reviewer-edited, new note non-empty, "
        "and it differs). Default is fill-only (never overwrite).",
    )
    ap.add_argument("--samples", type=int, default=10, help="Max sample source-row numbers to show.")
    args = ap.parse_args()
    refresh = args.refresh_parser_notes

    db = SessionLocal()
    try:
        plan = import_reparse.plan_reparse(db, args.batch_id, samples=args.samples, refresh_notes=refresh)
        if plan["rows_total"] == 0:
            print(f"Batch {args.batch_id}: no rows found. Nothing to do.")
            return 1
        _print_plan(plan)

        if not args.apply:
            print(f"\nDRY-RUN only ({_mode_label(refresh)} mode). Re-run with --apply to write.")
            return 0

        print(f"\nApplying ({_mode_label(refresh)} mode; one transaction)…")
        counts = import_reparse.apply_reparse(db, args.batch_id, refresh_notes=refresh)
        print(f"rows changed .............................. {counts['rows_changed']}")
        print(f"  customer_name_notes set (fill) ......... {counts['name_notes_gained']}")
        print(f"  removes_old_system set .................. {counts['removes_old_system_gained']}")
        print(f"  decommission_marker set ................. {counts['decommission_marker_gained']}")
        print(f"  original_parsed mirrored ................ {counts['original_parsed_mirrored']}")
        if refresh:
            print(f"  customer_name_notes refreshed .......... {counts['notes_refreshed']}")
        print("Done.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
