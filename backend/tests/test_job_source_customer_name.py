"""Read-model provenance: JobRead.source_customer_name.

A job's list/detail read exposes the ORIGINAL/source customer name (compute-on-read) when the
job belongs to its current customer under a DIFFERENT name — so a customer's job list can show
that a job originally came from a differently-named customer. Two sources, MERGE first:
  * a customer MERGE (from CUSTOMER_MERGED activity metadata); else
  * the IMPORT row the job was committed/attached from (ImportRow.parsed['customer_name']).
Nothing is written; the job's real customer source of truth is unchanged.

Synthetic data only; rollback-isolated db_session. The merge path runs the real merge_customers
service (which produces the metadata the helper reads); the import path constructs the committed
ImportRow state directly — no live/business action is performed.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.customer import Customer
from app.models.enums import ActivityType
from app.models.import_staging import ImportBatch, ImportRow
from app.models.job import Job
from app.services import customers as customers_service
from app.services import jobs as jobs_service


def _customer(db: Session, name: str) -> Customer:
    c = Customer(full_name=name)
    db.add(c)
    db.flush()
    return c


def _job(db: Session, customer_id: int, case_number: str) -> Job:
    j = Job(case_number=case_number, customer_id=customer_id, status="installed")
    db.add(j)
    db.flush()
    return j


def _import_row(db: Session, *, job: Job, customer_name: str, mode: str = "existing") -> ImportRow:
    """A COMMITTED import row linked to ``job`` (committed_job_id), carrying a parsed customer
    name. Constructs the post-commit state directly — no import pipeline is run."""
    b = ImportBatch(source_filename="x.xlsx", sheet_name="COMPLETED", status="committed")
    db.add(b)
    db.flush()
    r = ImportRow(
        batch_id=b.id, source_row_index=2, row_class="job",
        parsed={"customer_name": customer_name}, review_status="committed",
        customer_resolution_mode=mode, committed_job_id=job.id,
    )
    db.add(r)
    db.flush()
    return r


def _merge(db: Session, *, loser: Customer, winner: Customer, actor_id: int) -> None:
    customers_service.merge_customers(db, loser_id=loser.id, winner_id=winner.id, actor_id=actor_id)
    db.flush()
    # merge_customers repoints via bulk UPDATE (synchronize_session=False), so in-session
    # objects are stale until expired — in production the endpoint's commit does this.
    db.expire_all()


def test_merged_job_exposes_source_customer_name(users, client_for, db_session: Session):
    winner = _customer(db_session, "Stuart White")
    loser = _customer(db_session, "Steven Pipka")
    job = _job(db_session, loser.id, "SCS-2099-90001")
    _merge(db_session, loser=loser, winner=winner, actor_id=users["admin"].id)

    moved = db_session.get(Job, job.id)
    assert moved.customer_id == winner.id  # job now lives under the winner (source of truth)

    # service helper
    src = jobs_service.merge_source_names_for_jobs(db_session, [moved])
    assert src.get(job.id) == "Steven Pipka"

    # list endpoint exposes it
    body = client_for(users["admin"]).get(f"/api/v1/jobs?customer_id={winner.id}").json()
    item = next(i for i in body["items"] if i["id"] == job.id)
    assert item["source_customer_name"] == "Steven Pipka"
    assert item["customer"]["full_name"] == "Stuart White"  # current customer unchanged

    # detail endpoint exposes it too
    detail = client_for(users["admin"]).get(f"/api/v1/jobs/{job.id}").json()
    assert detail["source_customer_name"] == "Steven Pipka"


def test_non_merged_job_exposes_null(users, client_for, db_session: Session):
    cust = _customer(db_session, "Normal Customer")
    job = _job(db_session, cust.id, "SCS-2099-90002")

    assert job.id not in jobs_service.merge_source_names_for_jobs(db_session, [job])

    body = client_for(users["admin"]).get(f"/api/v1/jobs?customer_id={cust.id}").json()
    item = next(i for i in body["items"] if i["id"] == job.id)
    assert item["source_customer_name"] is None


def test_same_name_loser_exposes_null(users, db_session: Session):
    # Two customers with the SAME name merged -> the source name is not meaningful to show.
    winner = _customer(db_session, "John Smith")
    loser = _customer(db_session, "John Smith")
    job = _job(db_session, loser.id, "SCS-2099-90003")
    _merge(db_session, loser=loser, winner=winner, actor_id=users["admin"].id)

    moved = db_session.get(Job, job.id)
    assert moved.customer_id == winner.id
    assert job.id not in jobs_service.merge_source_names_for_jobs(db_session, [moved])


def test_merge_same_name_case_or_space_variant_exposes_null(users, db_session: Session):
    # Same-name suppression is NORMALISED (case + whitespace) for the MERGE path too, so it is
    # consistent with the import path — a loser that differs only by case/spacing is suppressed.
    winner = _customer(db_session, "John Smith")
    loser = _customer(db_session, "  john   smith ")
    job = _job(db_session, loser.id, "SCS-2099-90010")
    _merge(db_session, loser=loser, winner=winner, actor_id=users["admin"].id)

    moved = db_session.get(Job, job.id)
    assert moved.customer_id == winner.id
    assert job.id not in jobs_service.merge_source_names_for_jobs(db_session, [moved])
    assert job.id not in jobs_service.source_customer_names_for_jobs(db_session, [moved])


def test_chained_merge_uses_earliest_source_name(users, db_session: Session):
    # Steven Pipka -> Intermediate -> Final Winner: the job's ORIGINAL source is Steven Pipka,
    # NOT the intermediate name.
    original = _customer(db_session, "Steven Pipka")
    intermediate = _customer(db_session, "Intermediate Co")
    final = _customer(db_session, "Final Winner")
    job = _job(db_session, original.id, "SCS-2099-90004")
    _merge(db_session, loser=original, winner=intermediate, actor_id=users["admin"].id)
    _merge(db_session, loser=intermediate, winner=final, actor_id=users["admin"].id)

    moved = db_session.get(Job, job.id)
    assert moved.customer_id == final.id
    src = jobs_service.merge_source_names_for_jobs(db_session, [moved])
    assert src.get(job.id) == "Steven Pipka"  # earliest/original, not "Intermediate Co"


def test_compute_does_not_mutate_job_or_customer(users, db_session: Session):
    winner = _customer(db_session, "Winner Co")
    loser = _customer(db_session, "Source Co")
    job = _job(db_session, loser.id, "SCS-2099-90005")
    _merge(db_session, loser=loser, winner=winner, actor_id=users["admin"].id)

    moved = db_session.get(Job, job.id)
    job_updated_before = moved.updated_at
    win_updated_before = db_session.get(Customer, winner.id).updated_at

    # Computing the source name twice must perform NO writes.
    jobs_service.merge_source_names_for_jobs(db_session, [moved])
    jobs_service.merge_source_names_for_jobs(db_session, [moved])
    db_session.flush()

    assert db_session.get(Job, job.id).updated_at == job_updated_before
    assert db_session.get(Customer, winner.id).updated_at == win_updated_before
    # The job's customer FK is untouched (still the winner — real source of truth preserved).
    assert db_session.get(Job, job.id).customer_id == winner.id
    # No stray contact variant or job mutation was introduced by the read.
    assert db_session.scalar(
        select(Job.customer_id).where(Job.id == job.id)
    ) == winner.id


# --------------------------------------------------------------------------- #
# Import-row source provenance (attach/grouped jobs) — the deferred case now built
# --------------------------------------------------------------------------- #
def test_imported_attach_differing_name_exposes_source(users, client_for, db_session: Session):
    # The live Stuart White / Stephen Pipka case: a job attached to an existing customer whose
    # import row carried a DIFFERENT name shows that original name.
    cust = _customer(db_session, "Stuart White")
    job = _job(db_session, cust.id, "SCS-2099-91001")
    _import_row(db_session, job=job, customer_name="Stephen Pipka", mode="existing")

    assert jobs_service.import_source_names_for_jobs(db_session, [job]).get(job.id) == "Stephen Pipka"
    assert jobs_service.source_customer_names_for_jobs(db_session, [job]).get(job.id) == "Stephen Pipka"

    body = client_for(users["admin"]).get(f"/api/v1/jobs?customer_id={cust.id}").json()
    item = next(i for i in body["items"] if i["id"] == job.id)
    assert item["source_customer_name"] == "Stephen Pipka"
    assert item["customer"]["full_name"] == "Stuart White"  # real customer unchanged
    detail = client_for(users["admin"]).get(f"/api/v1/jobs/{job.id}").json()
    assert detail["source_customer_name"] == "Stephen Pipka"


def test_imported_same_name_exposes_null(users, db_session: Session):
    # A grouped/attached job whose import row name MATCHES the current customer (case/space
    # insensitive) is not meaningful to show.
    cust = _customer(db_session, "Stuart White")
    job = _job(db_session, cust.id, "SCS-2099-91002")
    _import_row(db_session, job=job, customer_name="  stuart   white ", mode="group")
    assert job.id not in jobs_service.import_source_names_for_jobs(db_session, [job])
    assert job.id not in jobs_service.source_customer_names_for_jobs(db_session, [job])


def test_native_job_no_import_row_exposes_null(users, db_session: Session):
    # A job with no import row (native) has no import source.
    cust = _customer(db_session, "Native Cust")
    job = _job(db_session, cust.id, "SCS-2099-91003")
    assert job.id not in jobs_service.import_source_names_for_jobs(db_session, [job])
    assert job.id not in jobs_service.source_customer_names_for_jobs(db_session, [job])


def test_imported_blank_name_exposes_null(users, db_session: Session):
    # An import row with a blank/whitespace parsed customer_name contributes no source name.
    cust = _customer(db_session, "Blank Co")
    job = _job(db_session, cust.id, "SCS-2099-91006")
    _import_row(db_session, job=job, customer_name="   ", mode="existing")
    assert job.id not in jobs_service.import_source_names_for_jobs(db_session, [job])
    assert job.id not in jobs_service.source_customer_names_for_jobs(db_session, [job])


def test_merge_source_wins_over_import(users, db_session: Session):
    # If a job somehow has BOTH a merge record and an import row, MERGE provenance wins.
    winner = _customer(db_session, "Winner Co")
    job = _job(db_session, winner.id, "SCS-2099-91004")
    _import_row(db_session, job=job, customer_name="Import Source Co", mode="existing")
    db_session.add(
        Activity(
            activity_type=ActivityType.CUSTOMER_MERGED, description="merged",
            customer_id=winner.id, job_id=None,
            meta={"loser_name": "Merge Source Co", "moved": {"jobs": {"ids": [job.id]}}},
        )
    )
    db_session.flush()
    assert jobs_service.source_customer_names_for_jobs(db_session, [job]).get(job.id) == "Merge Source Co"


def test_import_compute_does_not_mutate(users, db_session: Session):
    cust = _customer(db_session, "Current Co")
    job = _job(db_session, cust.id, "SCS-2099-91005")
    row = _import_row(db_session, job=job, customer_name="Other Co", mode="existing")
    db_session.flush()
    job_u = db_session.get(Job, job.id).updated_at
    cust_u = db_session.get(Customer, cust.id).updated_at
    row_u = db_session.get(ImportRow, row.id).updated_at

    jobs_service.import_source_names_for_jobs(db_session, [job])
    jobs_service.source_customer_names_for_jobs(db_session, [job])
    db_session.flush()

    assert db_session.get(Job, job.id).updated_at == job_u          # Job untouched
    assert db_session.get(Customer, cust.id).updated_at == cust_u    # Customer untouched
    assert db_session.get(ImportRow, row.id).updated_at == row_u     # ImportRow untouched
    assert db_session.get(ImportRow, row.id).parsed == {"customer_name": "Other Co"}
    assert db_session.get(Job, job.id).customer_id == cust.id        # real source of truth kept
