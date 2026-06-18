"""Tests for the dev/test-only reset tools (Clear imports / Clear live CRM).

Synthetic data only, inside the rolled-back db_session transaction — nothing here
persists to the real DB. Proves each reset affects ONLY its intended tables and
leaves users/roles/label definitions intact (and, for clear_imports, live CRM;
for clear_live_crm, all import batch/row/issue CONTENT).
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.customer import Customer
from app.models.document import Document
from app.models.enums import (
    ActivityType,
    ImportBatchStatus,
    ImportRowClass,
    ImportRowReviewStatus,
    JobLabelSource,
    JobStatus,
)
from app.models.import_staging import (
    ImportBatch,
    ImportCustomerGroup,
    ImportIssue,
    ImportRow,
)
from app.models.job import Job
from app.models.job_label import JobLabelAssignment, JobLabelDefinition
from app.models.role import Role
from app.models.task import Task
from app.models.user import User
from app.services import dev_reset

_SEQ = iter(range(1, 100_000))


def _count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def _seed(db: Session) -> dict:
    """One fully-linked scenario: a committed import row pointing at a live
    customer+job that also has a task/activity/document/label-assignment/issue."""
    cust = Customer(full_name="Reset Test Customer")
    db.add(cust)
    db.flush()
    job = Job(case_number=f"SCS-RESET-{next(_SEQ):05d}", customer_id=cust.id, status=JobStatus.INSTALLED)
    db.add(job)
    db.flush()
    db.add(Task(title="Reset test task", customer_id=cust.id, job_id=job.id))
    db.add(Activity(activity_type=ActivityType.JOB_CREATED, description="seed", customer_id=cust.id, job_id=job.id))
    db.add(Document(original_filename="x.pdf", relative_path="x/x.pdf", customer_id=cust.id, job_id=job.id))
    label = db.scalar(select(JobLabelDefinition).limit(1))
    db.add(JobLabelAssignment(job_id=job.id, label_id=label.id, source=JobLabelSource.MANUAL))
    batch = ImportBatch(source_filename="x.xlsx", sheet_name="COMPLETED", status=ImportBatchStatus.PARSED.value)
    db.add(batch)
    db.flush()
    row = ImportRow(
        batch_id=batch.id,
        source_row_index=2,
        row_class=ImportRowClass.JOB.value,
        parsed={"customer_name": "X"},
        review_status=ImportRowReviewStatus.COMMITTED.value,
        committed_customer_id=cust.id,
        committed_job_id=job.id,
    )
    db.add(row)
    db.flush()
    db.add(ImportIssue(row_id=row.id, batch_id=batch.id, kind="x", severity="info", message="m"))
    db.flush()
    return {"customer_id": cust.id, "job_id": job.id, "batch_id": batch.id, "row_id": row.id}


_CRM = (Customer, Job, Task, Activity, Document, JobLabelAssignment)
_IMPORT = (ImportBatch, ImportRow, ImportIssue, ImportCustomerGroup)
_PROTECTED = (User, Role, JobLabelDefinition)


def test_clear_imports_deletes_only_import_tables(db_session: Session):
    ids = _seed(db_session)
    crm_before = {m.__name__: _count(db_session, m) for m in _CRM}
    prot_before = {m.__name__: _count(db_session, m) for m in _PROTECTED}

    deleted = dev_reset.clear_imports(db_session)
    db_session.flush()

    # import tables emptied
    for m in _IMPORT:
        assert _count(db_session, m) == 0, m.__name__
    assert deleted["import_rows"] >= 1 and deleted["import_batches"] >= 1

    # live CRM + protected tables UNCHANGED
    assert {m.__name__: _count(db_session, m) for m in _CRM} == crm_before
    assert {m.__name__: _count(db_session, m) for m in _PROTECTED} == prot_before
    # the live job/customer still exist
    assert db_session.get(Job, ids["job_id"]) is not None
    assert db_session.get(Customer, ids["customer_id"]) is not None


def test_clear_imports_handles_grouped_rows(db_session: Session):
    """clear_imports must break the import_rows <-> import_customer_groups FK cycle
    (B3-2): a row points at its group (customer_group_id) and the group points back
    at its primary row (primary_row_id). Without ordering this raises a
    ForeignKeyViolation; clear_imports nulls the link + deletes groups before rows."""
    cust = Customer(full_name="Reset Group Customer")
    db_session.add(cust)
    db_session.flush()
    batch = ImportBatch(
        source_filename="grp.xlsx", sheet_name="COMPLETED",
        status=ImportBatchStatus.REVIEWING.value,
    )
    db_session.add(batch)
    db_session.flush()
    r1 = ImportRow(batch_id=batch.id, source_row_index=2, row_class=ImportRowClass.JOB.value,
                   parsed={"customer_name": "A"}, review_status=ImportRowReviewStatus.PENDING.value)
    r2 = ImportRow(batch_id=batch.id, source_row_index=3, row_class=ImportRowClass.JOB.value,
                   parsed={"customer_name": "B"}, review_status=ImportRowReviewStatus.PENDING.value)
    db_session.add_all([r1, r2])
    db_session.flush()
    grp = ImportCustomerGroup(batch_id=batch.id, primary_row_id=r1.id)
    db_session.add(grp)
    db_session.flush()
    r1.customer_group_id = grp.id  # the mutual FK cycle: rows <-> group
    r2.customer_group_id = grp.id
    db_session.flush()

    customers_before = _count(db_session, Customer)

    deleted = dev_reset.clear_imports(db_session)
    db_session.flush()

    # the FK cycle was broken: groups + rows + batches all cleared, no FK violation
    assert _count(db_session, ImportCustomerGroup) == 0
    assert _count(db_session, ImportRow) == 0
    assert _count(db_session, ImportBatch) == 0
    assert deleted["import_customer_groups"] >= 1
    # live CRM untouched by the imports reset
    assert _count(db_session, Customer) == customers_before
    assert db_session.get(Customer, cust.id) is not None


def test_clear_live_crm_deletes_crm_and_detaches_imports(db_session: Session):
    ids = _seed(db_session)
    imp_before = {m.__name__: _count(db_session, m) for m in _IMPORT}
    prot_before = {m.__name__: _count(db_session, m) for m in _PROTECTED}

    deleted = dev_reset.clear_live_crm(db_session)
    db_session.flush()

    # CRM tables emptied
    for m in _CRM:
        assert _count(db_session, m) == 0, m.__name__
    assert deleted["jobs"] >= 1 and deleted["customers"] >= 1

    # import batch/row/issue CONTENT preserved (counts unchanged)
    assert {m.__name__: _count(db_session, m) for m in _IMPORT} == imp_before

    # the committed import row is DETACHED + reverted to approved, content intact
    row = db_session.get(ImportRow, ids["row_id"])
    assert row is not None
    assert row.committed_customer_id is None and row.committed_job_id is None
    assert row.review_status == ImportRowReviewStatus.APPROVED.value
    assert row.parsed == {"customer_name": "X"}
    assert deleted["import_rows_detached"] >= 1
    # NO committed links remain anywhere
    assert db_session.scalar(
        select(func.count()).select_from(ImportRow).where(ImportRow.committed_job_id.isnot(None))
    ) == 0

    # protected tables UNCHANGED
    assert {m.__name__: _count(db_session, m) for m in _PROTECTED} == prot_before


def test_clear_live_crm_detaches_grouped_committed_customer(db_session: Session):
    """clear_live_crm must detach a committed pending-row group (B3-3) and an
    'existing'-resolved row (B2) from a customer BEFORE deleting it — else
    DELETE customers FK-violates and import content would be lost."""
    cust = Customer(full_name="Grouped Committed Customer")
    db_session.add(cust)
    db_session.flush()
    batch = ImportBatch(
        source_filename="lc.xlsx", sheet_name="COMPLETED",
        status=ImportBatchStatus.REVIEWING.value,
    )
    db_session.add(batch)
    db_session.flush()
    primary = ImportRow(batch_id=batch.id, source_row_index=2, row_class=ImportRowClass.JOB.value,
                        parsed={"customer_name": "A"}, review_status=ImportRowReviewStatus.PENDING.value)
    resolved = ImportRow(batch_id=batch.id, source_row_index=3, row_class=ImportRowClass.JOB.value,
                         parsed={"customer_name": "B"}, review_status=ImportRowReviewStatus.PENDING.value,
                         customer_resolution_mode="existing", resolved_customer_id=cust.id)
    db_session.add_all([primary, resolved])
    db_session.flush()
    # a committed group pointing at the customer (B3-3)
    grp = ImportCustomerGroup(batch_id=batch.id, primary_row_id=primary.id, committed_customer_id=cust.id)
    db_session.add(grp)
    db_session.flush()
    primary.customer_group_id = grp.id
    db_session.flush()

    deleted = dev_reset.clear_live_crm(db_session)
    db_session.flush()

    # the customer was DELETABLE (no FK violation) and is gone
    assert db_session.get(Customer, cust.id) is None
    assert _count(db_session, Customer) == 0
    # import CONTENT preserved — group + row survive, just detached from the customer
    grp_after = db_session.get(ImportCustomerGroup, grp.id)
    assert grp_after is not None and grp_after.committed_customer_id is None
    row_after = db_session.get(ImportRow, resolved.id)
    assert row_after is not None
    assert row_after.resolved_customer_id is None
    assert row_after.customer_resolution_mode is None
    assert deleted["import_groups_detached"] >= 1
    assert deleted["import_rows_resolution_detached"] >= 1


def test_clear_live_crm_detaches_customer_merge_pointer(db_session: Session):
    """clear_live_crm must null customers.merged_into_customer_id (B4-1) BEFORE
    deleting customers, so the self-referential FK never blocks the hard delete.
    No merge execution exists yet, so the post-merge state is simulated by setting
    the storage columns directly: a soft-deleted loser pointing at a live winner."""
    winner = Customer(full_name="Merge Winner")
    loser = Customer(full_name="Merge Loser")
    db_session.add_all([winner, loser])
    db_session.flush()
    now = datetime.now(timezone.utc)
    loser.merged_into_customer_id = winner.id
    loser.merged_at = now
    loser.deleted_at = now
    db_session.flush()

    deleted = dev_reset.clear_live_crm(db_session)
    db_session.flush()

    # the merge pointer was nulled + counted, and BOTH customers hard-deleted with
    # no self-referential FK violation
    assert deleted["customers_merge_detached"] >= 1
    assert _count(db_session, Customer) == 0
    assert db_session.get(Customer, winner.id) is None
    assert db_session.get(Customer, loser.id) is None


# --------------------------------------------------------------------------- #
# Endpoint gates
# --------------------------------------------------------------------------- #
def test_counts_requires_admin(client_for, users):
    assert client_for(users["support"]).get("/api/v1/dev/reset/counts").status_code == 403
    resp = client_for(users["admin"]).get("/api/v1/dev/reset/counts")
    assert resp.status_code == 200
    body = resp.json()
    assert "imports" in body and "live_crm" in body
    assert "import_rows_detached" in body["live_crm"]


def test_reset_requires_exact_confirmation_phrase(client_for, users):
    admin = client_for(users["admin"])
    assert admin.post("/api/v1/dev/reset/imports", json={"confirm": "nope"}).status_code == 400
    assert admin.post("/api/v1/dev/reset/live-crm", json={"confirm": "delete all imports"}).status_code == 400
    # non-admin blocked regardless of phrase
    assert client_for(users["support"]).post(
        "/api/v1/dev/reset/imports", json={"confirm": "DELETE ALL IMPORTS"}
    ).status_code == 403


def test_reset_refused_in_production(client_for, users, monkeypatch):
    monkeypatch.setattr("app.api.v1.endpoints.dev_reset.settings", SimpleNamespace(is_production=True))
    admin = client_for(users["admin"])
    assert admin.get("/api/v1/dev/reset/counts").status_code == 403
    assert admin.post(
        "/api/v1/dev/reset/imports", json={"confirm": "DELETE ALL IMPORTS"}
    ).status_code == 403


def test_clear_imports_endpoint_runs_with_correct_phrase(client_for, users, db_session):
    _seed(db_session)
    resp = client_for(users["admin"]).post(
        "/api/v1/dev/reset/imports", json={"confirm": "DELETE ALL IMPORTS"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "clear_imports"
    assert _count(db_session, ImportRow) == 0
    # live CRM untouched by the imports reset
    assert _count(db_session, Job) >= 1
