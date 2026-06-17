"""Section D: reverse-then-recommit via the explicit 'Prepare recommit' action.

Synthetic data only; rollback-isolated db_session (no live commit-path probes).

A REVERSED row is normally terminal. `prepare_recommit` is the ONLY sanctioned exit:
it stamps the prior committed ids into an audit Activity, clears the committed links,
detaches any group (without touching the group's structure), resets resolution, and
returns the row to PENDING. The generic reopen stays blocked. A prepared row then flows
through the UNCHANGED commit/preview engine and creates BRAND-NEW live records; the old
soft-deleted Job/Customer are never restored.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.customer import Customer
from app.models.enums import (
    ActivityType,
    ImportBatchStatus,
    ImportRowClass,
    ImportRowReviewStatus,
)
from app.models.import_staging import ImportBatch, ImportCustomerGroup, ImportRow
from app.models.job import Job
from app.services import (
    import_commit,
    import_commit_preview as preview_svc,
    import_reverse,
    import_review,
)

PENDING = ImportRowReviewStatus.PENDING.value
APPROVED = ImportRowReviewStatus.APPROVED.value
COMMITTED = ImportRowReviewStatus.COMMITTED.value
REVERSED = ImportRowReviewStatus.REVERSED.value


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _batch(db: Session) -> ImportBatch:
    b = ImportBatch(
        source_filename="syn.xlsx", sheet_name="COMPLETED",
        status=ImportBatchStatus.REVIEWING.value,
    )
    db.add(b)
    db.flush()
    return b


def _job_row(db: Session, b: ImportBatch, i: int, *, ref: str, parsed: dict | None = None,
             status: str = PENDING) -> ImportRow:
    p = parsed or {"customer_name": f"Person {i}", "sale_date": "01/06/2025", "address": f"{i} Recommit St"}
    row = ImportRow(
        batch_id=b.id, source_row_index=i + 2, row_class=ImportRowClass.JOB.value,
        legacy_reference=ref, raw={"address": p.get("address", "")}, parsed=p, review_status=status,
    )
    db.add(row)
    db.flush()
    return row


def _commit_new(db: Session, admin_id: int, *, ref: str = "RC0001") -> tuple[ImportBatch, ImportRow]:
    """Seed + commit one approved unresolved ('new') row. Returns (batch, committed row)."""
    b = _batch(db)
    row = _job_row(db, b, 0, ref=ref, status=APPROVED)
    import_commit.commit_batch(db, b, actor_id=admin_id)
    return b, db.get(ImportRow, row.id)


def _prepare(db: Session, b: ImportBatch, row_id: int, admin_id: int) -> ImportRow:
    batch = import_review.get_batch(db, b.id)
    import_review.prepare_recommit(db, batch, db.get(ImportRow, row_id), actor_id=admin_id)
    db.flush()
    return db.get(ImportRow, row_id)


def _approve(db: Session, b: ImportBatch, row_id: int, admin_id: int) -> None:
    batch = import_review.get_batch(db, b.id)
    import_review.set_review_status(
        db, batch, db.get(ImportRow, row_id), ImportRowReviewStatus.APPROVED, actor_id=admin_id
    )
    db.flush()


def _standalone_customer(db: Session, *, name: str = "Keep Me", line1: str = "99 Original St") -> Customer:
    c = Customer(full_name=name, address_line1=line1, suburb="Oldtown", state="VIC", postcode="3000")
    db.add(c)
    db.flush()
    return c


def _grouped_commit(db: Session, users, *, n: int = 2, primary_idx: int = 0,
                    refs: dict | None = None) -> tuple[ImportBatch, list[ImportRow], ImportCustomerGroup]:
    """Seed n pending rows + a group over them, approve, and commit. Returns (batch, rows, group)."""
    admin = users["admin"].id
    b = _batch(db)
    rows = [
        _job_row(db, b, i, ref=(refs or {}).get(i, f"GRC{i:04d}"), status=PENDING)
        for i in range(n)
    ]
    members = [r.id for j, r in enumerate(rows) if j != primary_idx]
    group = import_review.create_group(
        db, b, primary_row_id=rows[primary_idx].id, member_row_ids=members, actor_id=admin
    )
    db.flush()
    for r in rows:
        r.review_status = APPROVED
    db.flush()
    import_commit.commit_batch(db, b, actor_id=admin)
    return b, [db.get(ImportRow, r.id) for r in rows], db.get(ImportCustomerGroup, group.id)


# --------------------------------------------------------------------------- #
# 1. Prepare returns a reversed row to a clean PENDING state
# --------------------------------------------------------------------------- #
def test_prepare_nongrouped_returns_to_pending_links_cleared(users, db_session: Session):
    admin = users["admin"].id
    b, row = _commit_new(db_session, admin)
    old_job, old_cust = row.committed_job_id, row.committed_customer_id
    import_reverse.reverse_row(db_session, db_session.get(ImportRow, row.id), actor_id=admin)
    assert db_session.get(ImportRow, row.id).review_status == REVERSED

    r = _prepare(db_session, b, row.id, admin)
    assert r.review_status == PENDING
    assert r.committed_job_id is None and r.committed_customer_id is None
    assert r.customer_resolution_mode is None and r.resolved_customer_id is None
    assert r.customer_group_id is None
    # The old soft-deleted records are NEVER restored.
    assert db_session.get(Job, old_job).deleted_at is not None
    assert db_session.get(Customer, old_cust).deleted_at is not None


# --------------------------------------------------------------------------- #
# 2. Generic reopen on a reversed row is still blocked
# --------------------------------------------------------------------------- #
def test_generic_reopen_on_reversed_still_blocked(users, db_session: Session):
    admin = users["admin"].id
    b, row = _commit_new(db_session, admin)
    import_reverse.reverse_row(db_session, db_session.get(ImportRow, row.id), actor_id=admin)
    batch = import_review.get_batch(db_session, b.id)
    with pytest.raises(ValueError, match="final and cannot be reopened"):
        import_review.set_review_status(
            db_session, batch, db_session.get(ImportRow, row.id),
            ImportRowReviewStatus.PENDING, actor_id=admin,
        )


# --------------------------------------------------------------------------- #
# 3. Prepare is rejected unless the row is reversed
# --------------------------------------------------------------------------- #
def test_prepare_on_non_reversed_rejected(users, db_session: Session):
    admin = users["admin"].id
    b, committed = _commit_new(db_session, admin)  # committed, not reversed
    batch = import_review.get_batch(db_session, b.id)
    with pytest.raises(ValueError, match="Only reversed rows"):
        import_review.prepare_recommit(db_session, batch, db_session.get(ImportRow, committed.id), actor_id=admin)
    # A pending row is rejected too.
    pending = _job_row(db_session, b, 5, ref="RC9999", status=PENDING)
    with pytest.raises(ValueError, match="Only reversed rows"):
        import_review.prepare_recommit(db_session, batch, pending, actor_id=admin)


# --------------------------------------------------------------------------- #
# 4. Recommit after prepare creates brand-new records / new case
# --------------------------------------------------------------------------- #
def test_recommit_creates_new_records_old_stay_deleted(users, db_session: Session):
    admin = users["admin"].id
    b, row = _commit_new(db_session, admin)
    old_job, old_cust = row.committed_job_id, row.committed_customer_id
    old_case = db_session.get(Job, old_job).case_number
    import_reverse.reverse_row(db_session, db_session.get(ImportRow, row.id), actor_id=admin)

    _prepare(db_session, b, row.id, admin)
    _approve(db_session, b, row.id, admin)
    import_commit.commit_batch(db_session, b, actor_id=admin)

    r = db_session.get(ImportRow, row.id)
    assert r.review_status == COMMITTED
    assert r.committed_job_id != old_job and r.committed_customer_id != old_cust
    new_job = db_session.get(Job, r.committed_job_id)
    assert new_job.deleted_at is None
    assert new_job.case_number != old_case
    # Old soft-deleted records untouched.
    assert db_session.get(Job, old_job).deleted_at is not None
    assert db_session.get(Customer, old_cust).deleted_at is not None


# --------------------------------------------------------------------------- #
# 5. Attach-to-existing recommit reuses the live customer, never mutates it
# --------------------------------------------------------------------------- #
def test_attach_recommit_keeps_customer_unmutated(users, db_session: Session):
    admin = users["admin"].id
    cust = _standalone_customer(db_session)
    addr_before = cust.address_line1
    b = _batch(db_session)
    row = _job_row(db_session, b, 0, ref="RCATT01", status=PENDING)
    batch = import_review.get_batch(db_session, b.id)
    import_review.set_resolution_existing(db_session, batch, row, customer_id=cust.id, actor_id=admin)
    db_session.get(ImportRow, row.id).review_status = APPROVED
    db_session.flush()
    import_commit.commit_batch(db_session, b, actor_id=admin)
    # Reverse: attach mode soft-deletes only the job, never the pre-existing customer.
    import_reverse.reverse_row(db_session, db_session.get(ImportRow, row.id), actor_id=admin)
    assert db_session.get(Customer, cust.id).deleted_at is None

    r = _prepare(db_session, b, row.id, admin)
    assert r.customer_resolution_mode is None  # resolution reset, must re-resolve
    # Re-resolve to the SAME live customer, approve, commit.
    import_review.set_resolution_existing(db_session, batch, r, customer_id=cust.id, actor_id=admin)
    _approve(db_session, b, row.id, admin)
    import_commit.commit_batch(db_session, b, actor_id=admin)

    r = db_session.get(ImportRow, row.id)
    new_job = db_session.get(Job, r.committed_job_id)
    assert new_job.customer_id == cust.id  # attached to the existing customer
    assert db_session.get(Customer, cust.id).address_line1 == addr_before  # NOT mutated


# --------------------------------------------------------------------------- #
# 6. Grouped reversed PRIMARY: prepare detaches, never reclaims primary
# --------------------------------------------------------------------------- #
def test_prepare_grouped_primary_detaches_no_reclaim(users, db_session: Session):
    admin = users["admin"].id
    b, rows, group = _grouped_commit(db_session, users, n=2, primary_idx=0)
    shared_cust = db_session.get(ImportCustomerGroup, group.id).committed_customer_id
    # Reverse the primary (non-last: dependent still committed) -> sibling re-promoted.
    import_reverse.reverse_row(db_session, db_session.get(ImportRow, rows[0].id), actor_id=admin)
    g = db_session.get(ImportCustomerGroup, group.id)
    assert g.primary_row_id == rows[1].id  # re-promoted at reverse
    assert g.committed_customer_id == shared_cust

    r0 = _prepare(db_session, b, rows[0].id, admin)
    assert r0.customer_group_id is None and r0.customer_resolution_mode is None
    assert r0.review_status == PENDING
    g = db_session.get(ImportCustomerGroup, group.id)
    assert g.primary_row_id == rows[1].id  # prepared row did NOT reclaim primary
    assert g.committed_customer_id == shared_cust  # group's shared customer untouched


# --------------------------------------------------------------------------- #
# 7. Grouped reversed DEPENDENT: prepare detaches, primary/customer untouched
# --------------------------------------------------------------------------- #
def test_prepare_grouped_dependent_detaches(users, db_session: Session):
    admin = users["admin"].id
    b, rows, group = _grouped_commit(db_session, users, n=2, primary_idx=0)
    shared_cust = db_session.get(ImportCustomerGroup, group.id).committed_customer_id
    import_reverse.reverse_row(db_session, db_session.get(ImportRow, rows[1].id), actor_id=admin)

    r1 = _prepare(db_session, b, rows[1].id, admin)
    assert r1.customer_group_id is None and r1.customer_resolution_mode is None
    assert r1.review_status == PENDING
    g = db_session.get(ImportCustomerGroup, group.id)
    assert g.primary_row_id == rows[0].id  # primary unchanged
    assert g.committed_customer_id == shared_cust  # still set (primary's customer alive)


# --------------------------------------------------------------------------- #
# 8. Last-member-reversed: prepare cannot silently rejoin a null-customer group
# --------------------------------------------------------------------------- #
def test_last_group_member_prepare_no_silent_rejoin(users, db_session: Session):
    admin = users["admin"].id
    b, rows, group = _grouped_commit(db_session, users, n=2, primary_idx=0)
    # Reverse dependent then primary (last active job -> shared customer soft-deleted).
    import_reverse.reverse_row(db_session, db_session.get(ImportRow, rows[1].id), actor_id=admin)
    import_reverse.reverse_row(db_session, db_session.get(ImportRow, rows[0].id), actor_id=admin)
    g = db_session.get(ImportCustomerGroup, group.id)
    assert g.committed_customer_id is None  # cleared at last-member reverse
    old_shared = rows[0].committed_customer_id

    r0 = _prepare(db_session, b, rows[0].id, admin)
    assert r0.customer_group_id is None and r0.customer_resolution_mode is None
    _approve(db_session, b, rows[0].id, admin)
    res = import_commit.commit_batch(db_session, b, actor_id=admin)

    r0 = db_session.get(ImportRow, rows[0].id)
    assert r0.review_status == COMMITTED  # committed as a fresh standalone row
    new_cust = db_session.get(Customer, r0.committed_customer_id)
    assert new_cust.deleted_at is None
    assert r0.committed_customer_id != old_shared  # brand-new, not the deleted shared one
    # It did NOT skip with a group reason.
    row_res = next((x for x in res["results"] if x["row_id"] == r0.id), None)
    assert row_res is None or row_res.get("reason") not in ("group_customer_missing", "group_primary_not_committed")


# --------------------------------------------------------------------------- #
# 9. A re-resolved customer deleted before commit still blocks (never silent create)
# --------------------------------------------------------------------------- #
def test_recommit_blocks_on_since_deleted_resolved_customer(users, db_session: Session):
    admin = users["admin"].id
    cust = _standalone_customer(db_session, name="Will Delete", line1="1 Gone St")
    b = _batch(db_session)
    row = _job_row(db_session, b, 0, ref="RCDEL01", status=PENDING)
    batch = import_review.get_batch(db_session, b.id)
    import_review.set_resolution_existing(db_session, batch, row, customer_id=cust.id, actor_id=admin)
    db_session.get(ImportRow, row.id).review_status = APPROVED
    db_session.flush()
    import_commit.commit_batch(db_session, b, actor_id=admin)
    import_reverse.reverse_row(db_session, db_session.get(ImportRow, row.id), actor_id=admin)

    r = _prepare(db_session, b, row.id, admin)
    import_review.set_resolution_existing(db_session, batch, r, customer_id=cust.id, actor_id=admin)
    _approve(db_session, b, row.id, admin)
    # Customer soft-deleted AFTER resolution, BEFORE commit.
    db_session.get(Customer, cust.id).deleted_at = datetime.now(timezone.utc)
    db_session.flush()
    res = import_commit.commit_batch(db_session, b, actor_id=admin)

    r = db_session.get(ImportRow, row.id)
    assert r.review_status != COMMITTED  # blocked, not silently created
    row_res = next(x for x in res["results"] if x["row_id"] == r.id)
    assert row_res["status"] == "failed" and row_res["reason"] == "resolved_customer_deleted"


# --------------------------------------------------------------------------- #
# 10. Preview == commit parity after prepare
# --------------------------------------------------------------------------- #
def test_preview_commit_parity_after_prepare(users, db_session: Session):
    admin = users["admin"].id
    b, row = _commit_new(db_session, admin)
    import_reverse.reverse_row(db_session, db_session.get(ImportRow, row.id), actor_id=admin)
    _prepare(db_session, b, row.id, admin)
    _approve(db_session, b, row.id, admin)

    p = preview_svc.preview(db_session, b)
    assert p["eligible_count"] == 1
    assert p["would_create"]["customers"] == 1 and p["would_create"]["jobs"] == 1
    sample = next(s for s in p["samples"] if s["row_id"] == row.id)
    assert sample["customer_action"] == "create"

    res = import_commit.commit_batch(db_session, b, actor_id=admin)
    assert res["committed"] == 1  # commit matches the preview prediction exactly


# --------------------------------------------------------------------------- #
# 11. Audit: the prepare Activity captures the prior committed ids
# --------------------------------------------------------------------------- #
def test_prepare_audit_captures_prior_ids(users, db_session: Session):
    admin = users["admin"].id
    b, row = _commit_new(db_session, admin)
    old_job, old_cust = row.committed_job_id, row.committed_customer_id
    import_reverse.reverse_row(db_session, db_session.get(ImportRow, row.id), actor_id=admin)
    _prepare(db_session, b, row.id, admin)

    act = db_session.scalar(
        select(Activity)
        .where(Activity.activity_type == ActivityType.RECORD_IMPORT_RECOMMIT_PREPARED)
        .order_by(Activity.id.desc())
    )
    assert act is not None
    assert act.meta["prior_committed_job_id"] == old_job
    assert act.meta["prior_committed_customer_id"] == old_cust
    assert act.job_id == old_job and act.customer_id == old_cust
    # The original provenance + reversal activities are preserved (append-only).
    kinds = set(
        db_session.scalars(
            select(Activity.activity_type).where(Activity.job_id == old_job)
        ).all()
    )
    assert ActivityType.RECORD_IMPORTED in kinds
    assert ActivityType.RECORD_IMPORT_REVERSED in kinds


# --------------------------------------------------------------------------- #
# 12. Endpoint: reopen reversed -> 409; prepare-recommit reversed -> 200; non-reversed -> 409
# --------------------------------------------------------------------------- #
def test_endpoint_prepare_recommit_and_reopen_guards(users, db_session: Session, client_for):
    admin = users["admin"]
    b, row = _commit_new(db_session, admin.id, ref="RCAPI01")
    import_reverse.reverse_row(db_session, db_session.get(ImportRow, row.id), actor_id=admin.id)
    client = client_for(admin)

    # Generic reopen on a reversed row is a hard 409.
    rr = client.post(f"/api/v1/imports/{b.id}/rows/{row.id}/reopen")
    assert rr.status_code == 409

    # Prepare-recommit on the reversed row succeeds and returns it to pending.
    pr = client.post(f"/api/v1/imports/{b.id}/rows/{row.id}/prepare-recommit")
    assert pr.status_code == 200
    body = pr.json()
    assert body["review_status"] == PENDING
    assert body["committed_job_id"] is None and body["committed_customer_id"] is None

    # Prepare-recommit again (now pending, not reversed) -> 409.
    pr2 = client.post(f"/api/v1/imports/{b.id}/rows/{row.id}/prepare-recommit")
    assert pr2.status_code == 409
