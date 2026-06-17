"""Section B3-3: grouped preview, grouped commit, and group-aware reverse.

Synthetic data only; rollback-isolated db_session (no live commit-path probes).
A pending-row group becomes ONE customer with N jobs at commit (primary creates,
dependents attach to group.committed_customer_id); preview agrees ("1 customer +
N jobs"); reverse deletes the shared customer only on its LAST active job. B2
existing-attach and 'new' single-job behaviour are unchanged.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.import_staging import ImportBatch, ImportCustomerGroup, ImportRow
from app.models.job import Job
from app.services import import_commit, import_commit_preview as preview_svc, import_reverse, import_review
from app.services import job_labels as job_labels_service


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _row(b_id, i, *, ref=None, extra=None):
    p = {"customer_name": f"Person {i}", "sale_date": "01/06/2025", "address": f"{i} Grp St"}
    if extra:
        p.update(extra)
    return ImportRow(
        batch_id=b_id, source_row_index=i + 2, row_class="job",
        legacy_reference=ref if ref is not None else f"GRP{i:04d}",
        raw={"address": f"{i} Grp St"}, parsed=p, review_status="pending",
    )


def _grouped_batch(db: Session, users, *, n=2, primary_idx=0, approve=True, extra=None, refs=None):
    """Seed a batch of n job rows + a group over all of them. Returns (batch, rows, group)."""
    actor = users["admin"].id
    b = ImportBatch(source_filename="syn.xlsx", sheet_name="COMPLETED", status="reviewing")
    db.add(b)
    db.flush()
    rows = []
    for i in range(n):
        rows.append(_row(b.id, i, ref=(refs or {}).get(i), extra=(extra or {}).get(i)))
    db.add_all(rows)
    db.flush()
    members = [r.id for j, r in enumerate(rows) if j != primary_idx]
    group = import_review.create_group(
        db, b, primary_row_id=rows[primary_idx].id, member_row_ids=members, actor_id=actor
    )
    db.flush()
    if approve:
        for r in rows:
            r.review_status = "approved"  # group already created while pending
        db.flush()
    return b, rows, group


def _ncust(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Customer)) or 0


def _active_jobs(db: Session, customer_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(Job).where(
            Job.customer_id == customer_id, Job.deleted_at.is_(None)
        )
    ) or 0


def _cust_of(db: Session, row: ImportRow) -> int | None:
    return db.get(ImportRow, row.id).committed_customer_id


# --------------------------------------------------------------------------- #
# A. Commit
# --------------------------------------------------------------------------- #
def test_grouped_commit_one_customer_n_jobs(users, db_session):
    b, rows, group = _grouped_batch(db_session, users, n=3, primary_idx=0)
    c_before = _ncust(db_session)
    res = import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    assert res["committed"] == 3 and res["failed"] == 0
    assert _ncust(db_session) == c_before + 1          # ONE customer
    cids = {_cust_of(db_session, r) for r in rows}
    assert len(cids) == 1                              # all 3 jobs share it
    cust_id = cids.pop()
    assert _active_jobs(db_session, cust_id) == 3
    # primary creates the customer + records it on the group; customer is the primary's.
    assert db_session.get(ImportCustomerGroup, group.id).committed_customer_id == cust_id
    assert db_session.get(Customer, cust_id).full_name == "Person 0"


def test_dependent_attaches_in_a_later_call(users, db_session):
    b, rows, group = _grouped_batch(db_session, users, n=2, primary_idx=0)
    # Commit only the primary first.
    res1 = import_commit.commit_batch(db_session, b, actor_id=users["admin"].id, row_ids=[rows[0].id])
    assert res1["committed"] == 1
    cust_id = _cust_of(db_session, rows[0])
    assert db_session.get(ImportCustomerGroup, group.id).committed_customer_id == cust_id
    c_after_primary = _ncust(db_session)
    # Now commit the dependent -> attaches to the group's customer (no new customer).
    res2 = import_commit.commit_batch(db_session, b, actor_id=users["admin"].id, row_ids=[rows[1].id])
    assert res2["committed"] == 1
    assert _cust_of(db_session, rows[1]) == cust_id
    assert _ncust(db_session) == c_after_primary


def test_primary_failure_prevents_dependent_customers(users, db_session):
    b, rows, group = _grouped_batch(db_session, users, n=2, primary_idx=0)
    rows[0].parsed = {**rows[0].parsed, "customer_name": "X" * 200}  # too long -> DB error
    db_session.flush()
    c_before = _ncust(db_session)
    res = import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    st = {r["row_id"]: r for r in res["results"]}
    assert st[rows[0].id]["status"] == "failed"
    assert st[rows[1].id]["status"] == "skipped"
    assert st[rows[1].id]["reason"] == "group_primary_not_committed"
    assert _ncust(db_session) == c_before  # NO customers created — no silent split
    assert db_session.get(ImportCustomerGroup, group.id).committed_customer_id is None


def test_dependent_failure_isolated(users, db_session, monkeypatch):
    # A dependent attaches to the group's customer, so its own customer_name is
    # never used — inject a JOB-level failure to fail exactly one dependent and
    # prove per-row durability (primary + other dependent still commit).
    b, rows, group = _grouped_batch(db_session, users, n=3, primary_idx=0)
    orig_create_job = import_commit.jobs_service.create_job

    def flaky(db, *, customer_id, data, **kw):
        if data.get("legacy_reference") == rows[1].legacy_reference:
            raise RuntimeError("boom")  # fail only dep1's job
        return orig_create_job(db, customer_id=customer_id, data=data, **kw)

    monkeypatch.setattr(import_commit.jobs_service, "create_job", flaky)
    res = import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    st = {r["row_id"]: r for r in res["results"]}
    assert st[rows[0].id]["status"] == "committed"   # primary ok (durable)
    assert st[rows[1].id]["status"] == "failed"       # dep1 failed (no orphan)
    assert st[rows[2].id]["status"] == "committed"   # dep2 still attached
    cust_id = _cust_of(db_session, rows[0])
    assert _cust_of(db_session, rows[2]) == cust_id
    assert _cust_of(db_session, rows[1]) is None
    assert _active_jobs(db_session, cust_id) == 2


def test_cap_split_keeps_primary_first(users, db_session, monkeypatch):
    monkeypatch.setattr(import_commit, "COMMIT_CAP", 1)
    b, rows, group = _grouped_batch(db_session, users, n=2, primary_idx=0)
    res1 = import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    assert res1["committed"] == 1 and res1["capped_out"] == 1
    # The PRIMARY committed first; the dependent waits.
    cust_id = _cust_of(db_session, rows[0])
    assert cust_id is not None and _cust_of(db_session, rows[1]) is None
    assert db_session.get(ImportCustomerGroup, group.id).committed_customer_id == cust_id
    res2 = import_commit.commit_batch(db_session, db_session.get(ImportBatch, b.id), actor_id=users["admin"].id)
    assert res2["committed"] == 1
    assert _cust_of(db_session, rows[1]) == cust_id  # dependent attaches in the next call


def test_grouped_dependent_duplicate_legacy_ref_skipped(users, db_session):
    # A live job already carries legacy ref "DUP1".
    b0 = ImportBatch(source_filename="x.xlsx", sheet_name="COMPLETED", status="reviewing")
    db_session.add(b0)
    db_session.flush()
    pre = _row(b0.id, 9, ref="DUP1")
    pre.review_status = "approved"
    db_session.add(pre)
    db_session.flush()
    import_commit.commit_batch(db_session, b0, actor_id=users["admin"].id)
    # A group whose DEPENDENT reuses "DUP1" -> dependent skipped (dedup runs before group logic).
    b, rows, group = _grouped_batch(db_session, users, n=2, primary_idx=0, refs={1: "DUP1"})
    res = import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    st = {r["row_id"]: r for r in res["results"]}
    assert st[rows[0].id]["status"] == "committed"
    assert st[rows[1].id]["status"] == "skipped"
    assert st[rows[1].id]["reason"] == "duplicate_legacy_reference"


def test_grouped_jobs_get_labels(users, db_session):
    b, rows, group = _grouped_batch(
        db_session, users, n=2, primary_idx=0,
        extra={0: {"approval_state": "approved"}, 1: {"approval_state": "approved"}},
    )
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    for r in rows:
        job = db_session.get(Job, db_session.get(ImportRow, r.id).committed_job_id)
        keys = [a.label.key for a in job_labels_service.list_job_labels(db_session, job.id)]
        assert "approval_approved" in keys


def test_grouped_jobs_internal_notes_override(users, db_session):
    b, rows, group = _grouped_batch(db_session, users, n=2, primary_idx=0)
    db_session.get(ImportRow, rows[1].id).internal_notes_override = "Ring before 9am"
    db_session.flush()
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    dep_job = db_session.get(Job, db_session.get(ImportRow, rows[1].id).committed_job_id)
    assert dep_job.internal_notes == "Ring before 9am"


# --------------------------------------------------------------------------- #
# B. Preview
# --------------------------------------------------------------------------- #
def test_grouped_preview_counts_and_actions(users, db_session):
    b, rows, group = _grouped_batch(db_session, users, n=3, primary_idx=0)
    p = preview_svc.preview(db_session, b)
    assert p["eligible_count"] == 3
    assert p["would_create"]["customers"] == 1   # the group = ONE customer
    assert p["would_create"]["jobs"] == 3
    actions = {s["row_id"]: s["customer_action"] for s in p["samples"]}
    assert actions[rows[0].id] == "group_primary"
    assert actions[rows[1].id] == "group_dependent"
    assert actions[rows[2].id] == "group_dependent"
    s0 = next(s for s in p["samples"] if s["row_id"] == rows[0].id)
    assert s0["group_id"] == group.id and s0["primary_row_id"] == rows[0].id


def test_invalid_group_preview_excludes_dependents(users, db_session):
    b, rows, group = _grouped_batch(db_session, users, n=2, primary_idx=0, approve=False)
    rows[1].review_status = "approved"  # dependent approved, primary still pending
    db_session.flush()
    p = preview_svc.preview(db_session, b)
    assert p["excluded"]["group_primary_unavailable"] == 1
    assert rows[1].id not in {s["row_id"] for s in p["samples"]}


def test_committed_group_previews_dependents_as_attach(users, db_session):
    b, rows, group = _grouped_batch(db_session, users, n=2, primary_idx=0)
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id, row_ids=[rows[0].id])
    cust_id = db_session.get(ImportCustomerGroup, group.id).committed_customer_id
    p = preview_svc.preview(db_session, b)
    assert p["would_create"]["customers"] == 0   # dependent attaches; no new customer
    dep = next(s for s in p["samples"] if s["row_id"] == rows[1].id)
    assert dep["customer_action"] == "group_dependent"
    assert dep["resolved_customer_id"] == cust_id


# --------------------------------------------------------------------------- #
# C. Reverse (highest-risk)
# --------------------------------------------------------------------------- #
def test_reverse_non_last_grouped_job_keeps_customer(users, db_session):
    b, rows, group = _grouped_batch(db_session, users, n=3, primary_idx=0)
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    cust_id = _cust_of(db_session, rows[0])
    r1 = db_session.get(ImportRow, rows[1].id)
    res = import_reverse.reverse_row(db_session, r1, actor_id=users["admin"].id)
    assert res["status"] == "reversed"
    assert db_session.get(Job, r1.committed_job_id).deleted_at is not None   # job soft-deleted
    assert db_session.get(Customer, cust_id).deleted_at is None              # shared customer KEPT
    assert _active_jobs(db_session, cust_id) == 2                            # siblings remain


def test_reverse_last_grouped_job_deletes_customer(users, db_session):
    b, rows, group = _grouped_batch(db_session, users, n=2, primary_idx=0)
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    cust_id = _cust_of(db_session, rows[0])
    # Reverse the dependent first (non-last) -> job only, customer stays.
    import_reverse.reverse_row(db_session, db_session.get(ImportRow, rows[1].id), actor_id=users["admin"].id)
    assert db_session.get(Customer, cust_id).deleted_at is None
    # Reverse the primary's job (now the LAST active) -> customer soft-deleted.
    res = import_reverse.reverse_row(db_session, db_session.get(ImportRow, rows[0].id), actor_id=users["admin"].id)
    assert res["status"] == "reversed"
    assert db_session.get(Customer, cust_id).deleted_at is not None


def test_normal_new_reverse_unchanged(users, db_session):
    # A single ungrouped 'new' row: reverse soft-deletes BOTH (unchanged).
    b = ImportBatch(source_filename="x.xlsx", sheet_name="COMPLETED", status="reviewing")
    db_session.add(b)
    db_session.flush()
    r = _row(b.id, 1, ref="NEW1")
    r.review_status = "approved"
    db_session.add(r)
    db_session.flush()
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    row = db_session.get(ImportRow, r.id)
    res = import_reverse.reverse_row(db_session, row, actor_id=users["admin"].id)
    assert res["status"] == "reversed"
    assert db_session.get(Job, row.committed_job_id).deleted_at is not None
    assert db_session.get(Customer, row.committed_customer_id).deleted_at is not None


def test_b2_attached_reverse_unchanged(users, db_session):
    # A B2 'existing' attach: reverse soft-deletes only the job, never the customer.
    existing = Customer(full_name="Existing", suburb="T")
    db_session.add(existing)
    db_session.flush()
    b = ImportBatch(source_filename="x.xlsx", sheet_name="COMPLETED", status="reviewing")
    db_session.add(b)
    db_session.flush()
    r = _row(b.id, 1, ref="ATT1")
    r.review_status = "pending"
    db_session.add(r)
    db_session.flush()
    import_review.set_resolution_existing(db_session, b, r, customer_id=existing.id, actor_id=users["admin"].id)
    r.review_status = "approved"
    db_session.flush()
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    row = db_session.get(ImportRow, r.id)
    res = import_reverse.reverse_row(db_session, row, actor_id=users["admin"].id)
    assert res["status"] == "reversed"
    assert db_session.get(Job, row.committed_job_id).deleted_at is not None
    assert db_session.get(Customer, existing.id).deleted_at is None  # pre-existing customer kept


# --------------------------------------------------------------------------- #
# D. No auto-merge
# --------------------------------------------------------------------------- #
def test_no_auto_merge_identical_names(users, db_session):
    # Two UNGROUPED rows with identical names commit as SEPARATE customers.
    b = ImportBatch(source_filename="x.xlsx", sheet_name="COMPLETED", status="reviewing")
    db_session.add(b)
    db_session.flush()
    rows = [_row(b.id, i, ref=f"NM{i}", extra={"customer_name": "Same Name"}) for i in (1, 2)]
    for r in rows:
        r.review_status = "approved"
    db_session.add_all(rows)
    db_session.flush()
    c_before = _ncust(db_session)
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    assert _ncust(db_session) == c_before + 2  # no auto-merge
    assert _cust_of(db_session, rows[0]) != _cust_of(db_session, rows[1])
