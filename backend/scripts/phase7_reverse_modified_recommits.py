#!/usr/bin/env python
"""Phase F — manual reversal of the 3 modified recommitted import records.

ONE-OFF, GATED, owner-approved. Three of the 28 currently-live recommitted
records cannot be reversed by the conservative ``import_reverse`` engine because
they were modified after import:

    batch 3230, row 27770, src 4   -> customer 5961, job 5655  (job_modified + customer_modified)
    batch 3230, row 27811, src 45  -> customer 5963, job 5657  (job_modified, extra job_updated)
    batch 3230, row 27986, src 220 -> customer 5964, job 5658  (customer_modified)

Per the owner decision (Phase F clean-slate restart), those post-import manual
edits are intentionally discarded so the records can be re-imported under the
structured model with the rest. This mirrors what ``import_reverse.reverse_row``
does, minus ONLY the modification blocks (job_modified / customer_modified /
extra job_updated activity) — every OTHER reverse-engine invariant is still
enforced. It NEVER hard-deletes and NEVER touches existing
``record_imported`` / ``job_updated`` activities (they stay as the audit trail).

SAFETY:
  * Default is DRY-RUN: validates everything, prints the plan, writes NOTHING.
    Pass ``--execute`` to perform the change.
  * ALL THREE rows are validated first; any drift on any row aborts the whole run
    with zero writes.
  * On ``--execute`` the three reversals happen in a SINGLE transaction — either
    all three reverse or none do.
  * IDs/counts only in output — no customer names/addresses/phones/emails/notes.

Usage (from the backend container; cwd /app is the backend root):
    docker exec -it helios-core-backend-1 python scripts/phase7_reverse_modified_recommits.py            # dry-run
    docker exec -it helios-core-backend-1 python scripts/phase7_reverse_modified_recommits.py --execute  # commit
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
from app.models.document import Document  # noqa: E402
from app.models.enums import ActivityType, ImportRowReviewStatus  # noqa: E402
from app.models.import_staging import ImportRow  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.task import Task  # noqa: E402
from app.services.activity import log_activity  # noqa: E402
from app.services.customers import soft_delete_customer  # noqa: E402
from app.services.jobs import soft_delete_job  # noqa: E402

INSTALLED = "installed"
ACTOR_ID = 1  # admin

# Exactly the 3 blocked, owner-approved targets (audited in the Phase F preflight).
TARGETS = [
    {"batch_id": 3230, "row_id": 27770, "source_row_index": 4,   "customer_id": 5961, "job_id": 5655},
    {"batch_id": 3230, "row_id": 27811, "source_row_index": 45,  "customer_id": 5963, "job_id": 5657},
    {"batch_id": 3230, "row_id": 27986, "source_row_index": 220, "customer_id": 5964, "job_id": 5658},
]

# The ONLY non-import job activity we deliberately allow is the manual edit
# (job_updated) — that modification is the reason this override exists. Any other
# activity type on the job (status change, task, reschedule, …) is unexpected
# drift and aborts the run.
ALLOWED_JOB_ACTIVITY_VALUES = {
    ActivityType.RECORD_IMPORTED.value,
    ActivityType.JOB_UPDATED.value,
}


def _val(x: object) -> str:
    return x.value if hasattr(x, "value") else str(x)


def _validate(db, t: dict) -> tuple:
    """Assert every identity/precondition for ONE target. Returns
    (t, row, job, cust, case_number); raises AssertionError on any drift.

    Deliberately does NOT assert ``updated_at == created_at`` (that modification is
    exactly what this override forgives). ALL other reverse-engine invariants —
    identity, links, status, legacy ref, no tasks/documents, single active job,
    and no UNEXPECTED activity types — are still enforced.
    """
    bid, rid, sidx = t["batch_id"], t["row_id"], t["source_row_index"]
    cid, jid = t["customer_id"], t["job_id"]

    row = db.get(ImportRow, rid)
    job = db.get(Job, jid)
    cust = db.get(Customer, cid)

    # Identity + existence.
    assert row is not None, f"import_row {rid} not found"
    assert job is not None, f"job {jid} not found"
    assert cust is not None, f"customer {cid} not found"
    assert row.batch_id == bid, f"row {rid} batch {row.batch_id} != expected {bid}"
    assert row.source_row_index == sidx, f"row {rid} src {row.source_row_index} != expected {sidx}"
    assert row.review_status == ImportRowReviewStatus.COMMITTED.value, (
        f"row {rid} review_status {row.review_status!r} != committed"
    )
    assert row.committed_customer_id == cid, f"row {rid} customer link {row.committed_customer_id} != {cid}"
    assert row.committed_job_id == jid, f"row {rid} job link {row.committed_job_id} != {jid}"

    # Live + linked correctly.
    assert job.deleted_at is None, f"job {jid} already soft-deleted"
    assert cust.deleted_at is None, f"customer {cid} already soft-deleted"
    assert job.customer_id == cid, f"job {jid}.customer_id {job.customer_id} != expected {cid}"
    if row.legacy_reference:
        assert job.legacy_reference == row.legacy_reference, (
            f"job {jid} legacy_reference {job.legacy_reference!r} != row {row.legacy_reference!r}"
        )

    # No drift other than the forgiven modification: status unchanged, no
    # tasks/documents, customer owns exactly this one active job.
    assert _val(job.status) == INSTALLED, f"job {jid} status {_val(job.status)!r} != installed (unexpected drift)"
    assert db.query(Task).filter(Task.job_id == jid).count() == 0, f"job {jid} has tasks (unexpected)"
    assert db.query(Document).filter(Document.job_id == jid).count() == 0, f"job {jid} has documents (unexpected)"
    active_jobs = db.query(Job).filter(Job.customer_id == cid, Job.deleted_at.is_(None)).count()
    assert active_jobs == 1, f"customer {cid} owns {active_jobs} active jobs (expected 1)"

    # Only record_imported + job_updated allowed on the job; anything else aborts.
    job_act_values = {_val(a[0]) for a in db.query(Activity.activity_type).filter(Activity.job_id == jid).all()}
    unexpected = job_act_values - ALLOWED_JOB_ACTIVITY_VALUES
    assert not unexpected, f"job {jid} has unexpected activity types {sorted(unexpected)}"

    return t, row, job, cust, job.case_number


def main(execute: bool) -> int:
    db = SessionLocal()
    try:
        # --- Phase 1: validate ALL targets first (any failure aborts, zero writes).
        validated = [_validate(db, t) for t in TARGETS]
        for t, _row, _job, _cust, case_number in validated:
            print(
                f"[plan] row {t['row_id']} (batch {t['batch_id']} src {t['source_row_index']}): "
                f"soft-delete job {t['job_id']} ({case_number}) + customer {t['customer_id']}; "
                f"mark row reversed; +1 RECORD_IMPORT_REVERSED activity "
                f"(existing record_imported/job_updated activities kept)."
            )
        print(f"[plan] total: reverse {len(validated)} modified records in ONE transaction (all-or-none).")

        if not execute:
            db.rollback()
            print("[dry-run] all preconditions OK; NO changes written. Re-run with --execute to commit.")
            return 0

        # --- Phase 2: single transaction — soft-delete + reversed + audit for all 3.
        for t, row, job, cust, case_number in validated:
            soft_delete_job(db, job)
            soft_delete_customer(db, cust)
            row.review_status = ImportRowReviewStatus.REVERSED.value
            log_activity(
                db,
                activity_type=ActivityType.RECORD_IMPORT_REVERSED,
                description=(
                    "Manual Phase F clean-slate reversal: modified-post-import override; "
                    "the manual edit was discarded with owner approval so this record can "
                    "be re-imported under the structured model."
                ),
                actor_id=ACTOR_ID,
                customer_id=cust.id,
                job_id=job.id,
                meta={
                    "batch_id": t["batch_id"],
                    "row_id": t["row_id"],
                    "source_row_index": t["source_row_index"],
                    "case_number": case_number,
                    "manual_reset": True,
                    "phase": "F_clean_slate",
                    "override": "modified_post_import",
                },
            )
        db.commit()  # atomic: all three or none

        # --- Post-write confirmation (IDs/counts only; no PII).
        job_ids = [job.id for _, _, job, _, _ in validated]
        cust_ids = [cust.id for _, _, _, cust, _ in validated]
        row_ids = [row.id for _, row, _, _, _ in validated]
        jobs_deleted = db.query(Job).filter(Job.id.in_(job_ids), Job.deleted_at.isnot(None)).count()
        custs_deleted = db.query(Customer).filter(Customer.id.in_(cust_ids), Customer.deleted_at.isnot(None)).count()
        rows_reversed = db.query(ImportRow).filter(
            ImportRow.id.in_(row_ids), ImportRow.review_status == ImportRowReviewStatus.REVERSED.value
        ).count()
        new_rev_acts = db.query(Activity).filter(
            Activity.activity_type == ActivityType.RECORD_IMPORT_REVERSED, Activity.job_id.in_(job_ids)
        ).count()
        print(
            f"[done] jobs soft-deleted: {jobs_deleted}/3; customers soft-deleted: {custs_deleted}/3; "
            f"rows reversed: {rows_reversed}/3; RECORD_IMPORT_REVERSED activities on these jobs: {new_rev_acts} "
            f"(expected 3)."
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
    ap = argparse.ArgumentParser(
        description="Phase F manual reversal of the 3 modified recommitted import records (owner-approved override)."
    )
    ap.add_argument("--execute", action="store_true", help="Apply the change (default is dry-run).")
    raise SystemExit(main(ap.parse_args().execute))
