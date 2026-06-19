"""Read-model provenance: JobRead.source_customer_name.

When a customer MERGE moves a job into a surviving customer that has a DIFFERENT name, the
job's list/detail read exposes the original/source customer name (compute-on-read from the
CUSTOMER_MERGED activity metadata) — so a merged customer's job list can show that a job
originally came from a differently-named customer. Nothing is written; the job's real
customer source of truth is unchanged.

Synthetic data only; rollback-isolated db_session. The merge is run through the real
merge_customers service (which produces the activity metadata the helper reads), inside the
test transaction — no live/business action is performed.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.customer import Customer
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
