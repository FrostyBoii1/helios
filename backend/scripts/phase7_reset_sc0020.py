#!/usr/bin/env python
"""Phase 7 — manual reset of the single non-engine-reversible imported record.

ONE-OFF, GATED, owner-approved (Option B). SC0020 / job 3350 cannot be reversed
by the conservative reverse engine because it was manually edited post-import
(``job_modified`` + 6 ``job_updated`` activities, all on ``system_details``). Per
the owner decision, that legacy edit is intentionally discarded so the record can
be re-imported under the structured model with the other 35.

This mirrors what ``import_reverse.reverse_row`` does, minus the modification
block: soft-delete the created Customer + Job, mark the import row ``reversed``,
and log ONE ``RECORD_IMPORT_REVERSED`` activity (manual-reset flavour). It NEVER
hard-deletes and NEVER touches the existing ``record_imported`` / ``job_updated``
activities — they stay as the audit trail.

SAFETY:
  * Default is DRY-RUN: it validates everything and prints the plan, but writes
    NOTHING. Pass ``--execute`` to perform the change in a single transaction.
  * Every identity/precondition is asserted first; any drift aborts with no writes.

Usage (from the backend container):
    docker exec -it helios-core-backend-1 python backend/scripts/phase7_reset_sc0020.py            # dry-run
    docker exec -it helios-core-backend-1 python backend/scripts/phase7_reset_sc0020.py --execute  # commit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the backend root importable regardless of the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.db.base  # noqa: E402, F401  (registers ALL ORM models so mappers resolve)
from app.db.session import SessionLocal  # noqa: E402
from app.models.activity import Activity  # noqa: E402
from app.models.customer import Customer  # noqa: E402
from app.models.enums import ActivityType, ImportRowReviewStatus  # noqa: E402
from app.models.import_staging import ImportRow  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.services.activity import log_activity  # noqa: E402
from app.services.customers import soft_delete_customer  # noqa: E402
from app.services.jobs import soft_delete_job  # noqa: E402

# --- Hard-coded target (audited in Gate A / Gate C preflight) ----------------- #
BATCH_ID = 388
ROW_ID = 4891
JOB_ID = 3350
CUSTOMER_ID = 3579
LEGACY_REF = "SC0020"
ACTOR_ID = 1  # admin


def main(execute: bool) -> int:
    db = SessionLocal()
    try:
        row = db.get(ImportRow, ROW_ID)
        job = db.get(Job, JOB_ID)
        cust = db.get(Customer, CUSTOMER_ID)

        # --- Preconditions: any mismatch aborts with zero writes --------------- #
        assert row is not None, f"import_row {ROW_ID} not found"
        assert job is not None, f"job {JOB_ID} not found"
        assert cust is not None, f"customer {CUSTOMER_ID} not found"
        assert row.batch_id == BATCH_ID, f"row {ROW_ID} not in batch {BATCH_ID}"
        assert row.committed_job_id == JOB_ID, "row→job link mismatch"
        assert row.committed_customer_id == CUSTOMER_ID, "row→customer link mismatch"
        assert row.legacy_reference == LEGACY_REF, "row legacy_reference mismatch"
        assert job.legacy_reference == LEGACY_REF, "job legacy_reference mismatch"
        assert job.deleted_at is None, "job already soft-deleted"
        assert cust.deleted_at is None, "customer already soft-deleted"
        assert row.review_status != ImportRowReviewStatus.REVERSED.value, "row already reversed"
        # The customer must own exactly this one active job (same invariant the
        # engine enforces) so soft-deleting the pair is clean.
        active_jobs = (
            db.query(Job).filter(Job.customer_id == CUSTOMER_ID, Job.deleted_at.is_(None)).count()
        )
        assert active_jobs == 1, f"customer {CUSTOMER_ID} owns {active_jobs} active jobs (expected 1)"

        case_number = job.case_number
        print(
            f"[plan] soft-delete job {JOB_ID} ({case_number}, ref {LEGACY_REF}) + "
            f"customer {CUSTOMER_ID}; mark row {ROW_ID} reversed; "
            f"write 1 RECORD_IMPORT_REVERSED activity. "
            f"(existing record_imported + job_updated activities are left intact)"
        )

        if not execute:
            db.rollback()
            print("[dry-run] preconditions OK; NO changes written. Re-run with --execute to commit.")
            return 0

        # --- Single transaction: soft-delete pair + mark reversed + audit ------ #
        soft_delete_job(db, job)
        soft_delete_customer(db, cust)
        row.review_status = ImportRowReviewStatus.REVERSED.value
        log_activity(
            db,
            activity_type=ActivityType.RECORD_IMPORT_REVERSED,
            description=(
                "Manual Phase 7 reset (Option B): job_modified override; the legacy "
                "system_details edit was discarded with owner approval so this record "
                "can be re-imported under the structured model."
            ),
            actor_id=ACTOR_ID,
            customer_id=CUSTOMER_ID,
            job_id=JOB_ID,
            meta={
                "batch_id": BATCH_ID,
                "row_id": ROW_ID,
                "case_number": case_number,
                "manual_reset": True,
                "override": "job_modified",
                "discarded": "system_details_manual_edit",
            },
        )
        db.commit()

        # --- Post-write confirmation ------------------------------------------ #
        db.refresh(row)
        job_after = db.get(Job, JOB_ID)
        cust_after = db.get(Customer, CUSTOMER_ID)
        reverse_acts = (
            db.query(Activity)
            .filter(Activity.job_id == JOB_ID, Activity.activity_type == ActivityType.RECORD_IMPORT_REVERSED)
            .count()
        )
        kept = (
            db.query(Activity)
            .filter(
                Activity.job_id == JOB_ID,
                Activity.activity_type.in_([ActivityType.RECORD_IMPORTED, ActivityType.JOB_UPDATED]),
            )
            .count()
        )
        print(
            f"[done] job.deleted_at set: {job_after.deleted_at is not None}; "
            f"customer.deleted_at set: {cust_after.deleted_at is not None}; "
            f"row.review_status: {row.review_status}; "
            f"RECORD_IMPORT_REVERSED activities: {reverse_acts}; "
            f"preserved record_imported+job_updated activities: {kept} (expected 7)"
        )
        return 0
    except AssertionError as exc:
        db.rollback()
        print(f"[abort] precondition failed: {exc}  — NO changes written.", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - report + roll back; never leave partial state
        db.rollback()
        print(f"[error] unexpected failure: {exc!r}  — rolled back, NO changes written.", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Phase 7 manual reset of SC0020 / job 3350 (Option B).")
    ap.add_argument("--execute", action="store_true", help="Apply the change (default is dry-run).")
    raise SystemExit(main(ap.parse_args().execute))
