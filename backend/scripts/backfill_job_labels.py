#!/usr/bin/env python
"""Phase L3 — backfill import-derived Job labels onto the 5 existing live trial jobs.

ONE-OFF, GATED, audited. The 5 jobs committed from batch 4399 predate the
commit-time auto-labeling, so they carry no labels. This assigns exactly the
labels that auto-labeling WOULD have produced at commit time — derived from each
row's parsed approval_state and details.flags.removes_old_system — and nothing
else. Source is ``import_auto`` so the backfilled labels are indistinguishable
from commit-time auto-labels.

SAFETY:
  * Default is DRY-RUN: validates everything, prints the plan, writes NOTHING.
    Pass ``--execute`` to perform the change.
  * ALL FIVE targets are validated first (identity: row committed to the expected
    customer/job in batch 4399, job + customer live). Any drift aborts the whole
    run with zero writes.
  * Idempotent: a label already present on a job is left as-is (never duplicated).
  * On ``--execute`` all assignments happen in a SINGLE transaction (all-or-none).
  * IDs / label keys / counts only in output — no customer names/addresses/etc.

Usage (from the backend container; cwd /app is the backend root):
    docker exec -it helios-core-backend-1 python scripts/backfill_job_labels.py            # dry-run
    docker exec -it helios-core-backend-1 python scripts/backfill_job_labels.py --execute  # commit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the backend root importable regardless of the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.db.base  # noqa: E402, F401  (registers ALL ORM models so mappers resolve)
from app.db.session import SessionLocal  # noqa: E402
from app.models.customer import Customer  # noqa: E402
from app.models.enums import ImportRowReviewStatus, JobLabelSource  # noqa: E402
from app.models.import_staging import ImportRow  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.services import job_labels as job_labels_service  # noqa: E402

BATCH_ID = 4399
ACTOR_ID = 1  # admin — the operator who committed the trial set (provenance)

# Exactly the 5 committed trial rows (row_id, source_row_index, customer_id, job_id).
TARGETS = [
    {"row_id": 41317, "source_row_index": 88, "customer_id": 8220, "job_id": 7822},
    {"row_id": 41290, "source_row_index": 61, "customer_id": 8221, "job_id": 7823},
    {"row_id": 42203, "source_row_index": 974, "customer_id": 8222, "job_id": 7824},
    {"row_id": 43219, "source_row_index": 1990, "customer_id": 8224, "job_id": 7826},
    {"row_id": 43241, "source_row_index": 2012, "customer_id": 8223, "job_id": 7825},
]


def _validate(db, t: dict) -> tuple:
    """Assert identity for ONE target; returns (t, row, job). Raises on drift."""
    rid, sidx = t["row_id"], t["source_row_index"]
    cid, jid = t["customer_id"], t["job_id"]

    row = db.get(ImportRow, rid)
    job = db.get(Job, jid)
    cust = db.get(Customer, cid)

    assert row is not None, f"import_row {rid} not found"
    assert job is not None, f"job {jid} not found"
    assert cust is not None, f"customer {cid} not found"
    assert row.batch_id == BATCH_ID, f"row {rid} batch {row.batch_id} != {BATCH_ID}"
    assert row.source_row_index == sidx, f"row {rid} src {row.source_row_index} != {sidx}"
    assert row.review_status == ImportRowReviewStatus.COMMITTED.value, (
        f"row {rid} review_status {row.review_status!r} != committed"
    )
    assert row.committed_customer_id == cid, f"row {rid} customer link {row.committed_customer_id} != {cid}"
    assert row.committed_job_id == jid, f"row {rid} job link {row.committed_job_id} != {jid}"
    assert job.deleted_at is None, f"job {jid} is soft-deleted"
    assert cust.deleted_at is None, f"customer {cid} is soft-deleted"
    assert job.customer_id == cid, f"job {jid}.customer_id {job.customer_id} != {cid}"
    return t, row, job


def _planned(db, row: ImportRow, job: Job) -> tuple[list[tuple[str, str | None]], list[str]]:
    """(to_add, already_present) label keys for one job. Idempotency-aware."""
    derived = job_labels_service.auto_label_keys(row.parsed or {}, job.details or {})
    present = {a.label.key for a in job_labels_service.list_job_labels(db, job.id)}
    to_add = [(k, note) for (k, note) in derived if k not in present]
    already = [k for (k, _n) in derived if k in present]
    return to_add, already


def main(execute: bool) -> int:
    db = SessionLocal()
    try:
        validated = [_validate(db, t) for t in TARGETS]

        total_to_add = 0
        plan: list[tuple[dict, ImportRow, Job, list, list]] = []
        for t, row, job in validated:
            to_add, already = _planned(db, row, job)
            plan.append((t, row, job, to_add, already))
            total_to_add += len(to_add)
            add_keys = [k for (k, _n) in to_add]
            print(
                f"[plan] row {t['row_id']} job {t['job_id']} (src {t['source_row_index']}): "
                f"add={add_keys or '-'} already_present={already or '-'}"
            )
        print(f"[plan] total label assignments to create: {total_to_add} across {len(validated)} jobs.")

        if not execute:
            db.rollback()
            print("[dry-run] all preconditions OK; NO changes written. Re-run with --execute to apply.")
            return 0

        created = 0
        for _t, _row, job, to_add, _already in plan:
            for key, note in to_add:
                a = job_labels_service.assign_label_by_key(
                    db, job_id=job.id, key=key,
                    source=JobLabelSource.IMPORT_AUTO, assigned_by_id=ACTOR_ID, note=note,
                )
                if a is not None:
                    created += 1
        db.commit()  # atomic: all assignments or none

        # Post-write confirmation (counts only).
        final = {t["job_id"]: len(job_labels_service.list_job_labels(db, t["job_id"])) for t in TARGETS}
        print(f"[done] created {created} assignment(s). Labels-per-job now: {final}")
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
        description="Backfill import-derived Job labels onto the 5 live trial jobs (Phase L3)."
    )
    ap.add_argument("--execute", action="store_true", help="Apply the change (default is dry-run).")
    raise SystemExit(main(ap.parse_args().execute))
