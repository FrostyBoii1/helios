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


def _print_plan(s: dict) -> None:
    print(f"=== Additive reparse DRY-RUN — batch {s['batch_id']} ===")
    print(f"rows total ................................ {s['rows_total']}")
    print(f"rows considered (pending/approved job rows) {s['rows_considered']}")
    print(f"rows would change ......................... {s['rows_would_change']}")
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Additive in-place reparse of a staged import batch.")
    ap.add_argument("--batch-id", type=int, required=True, help="ImportBatch id to reparse.")
    ap.add_argument("--apply", action="store_true", help="Write changes (default is dry-run).")
    ap.add_argument("--samples", type=int, default=10, help="Max sample source-row numbers to show.")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        plan = import_reparse.plan_reparse(db, args.batch_id, samples=args.samples)
        if plan["rows_total"] == 0:
            print(f"Batch {args.batch_id}: no rows found. Nothing to do.")
            return 1
        _print_plan(plan)

        if not args.apply:
            print("\nDRY-RUN only. Re-run with --apply to write the three additive fields.")
            return 0

        print("\nApplying (one transaction; writes only the three additive fields)…")
        counts = import_reparse.apply_reparse(db, args.batch_id)
        print(f"rows changed .............................. {counts['rows_changed']}")
        print(f"  customer_name_notes set ................. {counts['name_notes_gained']}")
        print(f"  removes_old_system set .................. {counts['removes_old_system_gained']}")
        print(f"  decommission_marker set ................. {counts['decommission_marker_gained']}")
        print(f"  original_parsed mirrored ................ {counts['original_parsed_mirrored']}")
        print("Done.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
