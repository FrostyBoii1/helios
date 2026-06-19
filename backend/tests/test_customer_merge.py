"""Tests for B4-2 explicit admin customer merge (loser -> winner).

Synthetic data inside the rolled-back db_session — nothing persists. Covers
conservation/repoint, loser soft-delete + merge pointer, winner-authoritative
notes append, import-link per-column repoint, the CUSTOMER_MERGED activity meta,
the guard matrix + admin gating, idempotency, and single-transaction rollback.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.customer import Customer
from app.models.customer_contact_variant import CustomerContactVariant
from app.models.document import Document
from app.models.enums import (
    ActivityType,
    ImportBatchStatus,
    ImportRowClass,
    ImportRowReviewStatus,
    JobStatus,
)
from app.models.import_staging import ImportBatch, ImportCustomerGroup, ImportRow
from app.models.job import Job
from app.models.task import Task
from app.services import customers as customers_service

_SEQ = iter(range(1, 1_000_000))


def _customer(db: Session, name: str, **kw) -> Customer:
    c = Customer(full_name=name, **kw)
    db.add(c)
    db.flush()
    return c


def _job(db: Session, customer_id: int) -> Job:
    j = Job(case_number=f"SCS-MERGE-{next(_SEQ):06d}", customer_id=customer_id, status=JobStatus.INSTALLED)
    db.add(j)
    db.flush()
    return j


def _count_where(db: Session, model, **eq) -> int:
    stmt = select(func.count()).select_from(model)
    for col, val in eq.items():
        stmt = stmt.where(getattr(model, col) == val)
    return db.scalar(stmt) or 0


# --------------------------------------------------------------------------- #
# Service: conservation / repoint / soft-delete / notes / activity
# --------------------------------------------------------------------------- #
def test_merge_conserves_and_repoints(users, db_session: Session):
    admin_id = users["admin"].id
    loser = _customer(db_session, "Loser", notes="loser imported notes", internal_notes="loser internal")
    winner = _customer(db_session, "Winner", internal_notes="winner original")
    lj = _job(db_session, loser.id)
    db_session.add(Task(title="t", customer_id=loser.id, job_id=lj.id))
    db_session.add(Document(original_filename="d.pdf", relative_path="d/d.pdf", customer_id=loser.id, job_id=lj.id))
    db_session.add(Activity(activity_type=ActivityType.JOB_CREATED, description="seed", customer_id=loser.id, job_id=lj.id))
    _job(db_session, winner.id)  # winner already owns a job
    db_session.flush()

    res = customers_service.merge_customers(db_session, loser_id=loser.id, winner_id=winner.id, actor_id=admin_id)
    db_session.flush()

    # loser's children now under the winner; none left on the loser; none lost
    assert _count_where(db_session, Job, customer_id=loser.id) == 0
    assert _count_where(db_session, Task, customer_id=loser.id) == 0
    assert _count_where(db_session, Document, customer_id=loser.id) == 0
    assert _count_where(db_session, Activity, customer_id=loser.id) == 0
    assert _count_where(db_session, Job, customer_id=winner.id) == 2
    assert _count_where(db_session, Task, customer_id=winner.id) == 1
    assert _count_where(db_session, Document, customer_id=winner.id) == 1

    # loser soft-deleted + immutable merge pointer, NOT hard-deleted
    lo = db_session.get(Customer, loser.id)
    assert lo is not None
    assert lo.deleted_at is not None
    assert lo.merged_into_customer_id == winner.id
    assert lo.merged_at is not None

    # winner authoritative: own fields intact, loser notes appended with provenance
    wi = db_session.get(Customer, winner.id)
    assert wi.deleted_at is None
    assert "winner original" in wi.internal_notes
    assert "Merged from Loser" in wi.internal_notes
    assert "loser imported notes" in wi.internal_notes
    assert "loser internal" in wi.internal_notes

    # result summary + resolve_active_customer now follows loser -> winner
    assert res["moved"]["jobs"]["count"] == 1
    assert lj.id in res["moved"]["jobs"]["ids"]
    assert res["moved"]["activities"]["count"] == 1
    assert res["notes_appended"] is True
    assert customers_service.resolve_active_customer(db_session, loser.id).id == winner.id


def test_merge_repoints_import_links_per_column(users, db_session: Session):
    admin_id = users["admin"].id
    loser = _customer(db_session, "L2")
    winner = _customer(db_session, "W2")
    other = _customer(db_session, "Other")
    batch = ImportBatch(source_filename="x.xlsx", sheet_name="COMPLETED", status=ImportBatchStatus.PARSED.value)
    db_session.add(batch)
    db_session.flush()
    row_a = ImportRow(
        batch_id=batch.id, source_row_index=2, row_class=ImportRowClass.JOB.value,
        parsed={"customer_name": "A"}, review_status=ImportRowReviewStatus.COMMITTED.value,
        committed_customer_id=loser.id,
    )
    # committed to OTHER but resolved to LOSER: only resolved_customer_id should move.
    row_b = ImportRow(
        batch_id=batch.id, source_row_index=3, row_class=ImportRowClass.JOB.value,
        parsed={"customer_name": "B"}, review_status=ImportRowReviewStatus.PENDING.value,
        committed_customer_id=other.id, resolved_customer_id=loser.id, customer_resolution_mode="existing",
    )
    db_session.add_all([row_a, row_b])
    db_session.flush()
    grp = ImportCustomerGroup(batch_id=batch.id, primary_row_id=row_a.id, committed_customer_id=loser.id)
    db_session.add(grp)
    db_session.flush()

    res = customers_service.merge_customers(db_session, loser_id=loser.id, winner_id=winner.id, actor_id=admin_id)
    db_session.flush()
    db_session.refresh(row_a)
    db_session.refresh(row_b)
    db_session.refresh(grp)

    assert row_a.committed_customer_id == winner.id
    assert row_b.resolved_customer_id == winner.id
    assert row_b.committed_customer_id == other.id  # NOT clobbered (per-column WHERE/SET)
    assert grp.committed_customer_id == winner.id
    assert res["repointed_import"]["rows_committed"]["count"] == 1
    assert res["repointed_import"]["rows_resolved"]["count"] == 1
    assert res["repointed_import"]["groups_committed"]["count"] == 1


def test_merge_notes_nullsafe_no_loser_notes(users, db_session: Session):
    loser = _customer(db_session, "LN")  # no notes / internal_notes
    winner = _customer(db_session, "WN")  # internal_notes None
    db_session.flush()
    res = customers_service.merge_customers(db_session, loser_id=loser.id, winner_id=winner.id, actor_id=users["admin"].id)
    db_session.flush()
    assert res["notes_appended"] is False
    assert db_session.get(Customer, winner.id).internal_notes is None


def test_merge_notes_into_empty_winner(users, db_session: Session):
    loser = _customer(db_session, "LN2", notes="keep me")
    winner = _customer(db_session, "WN2")  # internal_notes None
    db_session.flush()
    customers_service.merge_customers(db_session, loser_id=loser.id, winner_id=winner.id, actor_id=users["admin"].id)
    db_session.flush()
    wi = db_session.get(Customer, winner.id)
    assert wi.internal_notes.startswith("--- Merged from LN2")
    assert "keep me" in wi.internal_notes


def test_merge_logs_activity_with_meta(users, db_session: Session):
    admin_id = users["admin"].id
    loser = _customer(db_session, "LM")
    winner = _customer(db_session, "WM")
    lj = _job(db_session, loser.id)
    db_session.flush()
    customers_service.merge_customers(db_session, loser_id=loser.id, winner_id=winner.id, actor_id=admin_id)
    db_session.flush()

    # Scope to THIS winner — the shared dev DB may already hold other CUSTOMER_MERGED
    # activities (e.g. a real manual merge), so a type-only query is not unique.
    act = db_session.scalar(
        select(Activity).where(
            Activity.activity_type == ActivityType.CUSTOMER_MERGED,
            Activity.customer_id == winner.id,
        )
    )
    assert act is not None
    assert act.customer_id == winner.id  # attached to the surviving winner
    assert act.actor_id == admin_id
    assert act.meta["loser_customer_id"] == loser.id
    assert act.meta["winner_customer_id"] == winner.id
    assert act.meta["moved"]["jobs"]["ids"] == [lj.id]
    assert "ids" not in act.meta["moved"]["activities"]  # count-only for activities (decision 3)


# --------------------------------------------------------------------------- #
# Guards (service-level)
# --------------------------------------------------------------------------- #
def test_merge_guard_self(users, db_session: Session):
    c = _customer(db_session, "Self")
    db_session.flush()
    with pytest.raises(customers_service.MergeError) as exc:
        customers_service.merge_customers(db_session, loser_id=c.id, winner_id=c.id, actor_id=users["admin"].id)
    assert exc.value.reason == "same_customer"
    assert exc.value.http_status == 400


def test_merge_guard_already_merged(users, db_session: Session):
    admin_id = users["admin"].id
    loser = _customer(db_session, "AM-L")
    winner = _customer(db_session, "AM-W")
    third = _customer(db_session, "AM-3")
    db_session.flush()
    customers_service.merge_customers(db_session, loser_id=loser.id, winner_id=winner.id, actor_id=admin_id)
    db_session.flush()
    # the (now merged) loser cannot be merged again -> immutable
    with pytest.raises(customers_service.MergeError) as exc:
        customers_service.merge_customers(db_session, loser_id=loser.id, winner_id=third.id, actor_id=admin_id)
    assert exc.value.reason == "loser_already_merged"
    assert exc.value.http_status == 409


# --------------------------------------------------------------------------- #
# Endpoint: admin-only + guard status mapping
# --------------------------------------------------------------------------- #
def _post_merge(client, loser_id: int, winner_id: int):
    return client.post(f"/api/v1/customers/{loser_id}/merge-into/{winner_id}")


def test_merge_endpoint_admin_happy(client_for, users, db_session: Session):
    loser = _customer(db_session, "EL")
    winner = _customer(db_session, "EW")
    db_session.flush()
    admin = client_for(users["admin"])
    resp = _post_merge(admin, loser.id, winner.id)
    assert resp.status_code == 200
    body = resp.json()
    assert body["winner"]["id"] == winner.id
    assert body["loser_id"] == loser.id
    assert "moved" in body and "repointed_import" in body
    # loser now hidden (soft-deleted)
    assert admin.get(f"/api/v1/customers/{loser.id}").status_code == 404


def test_merge_endpoint_non_admin_forbidden(client_for, users, db_session: Session):
    loser = _customer(db_session, "NL")
    winner = _customer(db_session, "NW")
    db_session.flush()
    assert _post_merge(client_for(users["support"]), loser.id, winner.id).status_code == 403
    assert _post_merge(client_for(users["sales"]), loser.id, winner.id).status_code == 403
    assert db_session.get(Customer, loser.id).deleted_at is None  # unchanged


def test_merge_endpoint_self_400(client_for, users, db_session: Session):
    c = _customer(db_session, "ESelf")
    db_session.flush()
    assert _post_merge(client_for(users["admin"]), c.id, c.id).status_code == 400


def test_merge_endpoint_missing_404(client_for, users, db_session: Session):
    c = _customer(db_session, "EMiss")
    db_session.flush()
    admin = client_for(users["admin"])
    assert _post_merge(admin, 999_999, c.id).status_code == 404
    assert _post_merge(admin, c.id, 999_999).status_code == 404


def test_merge_endpoint_not_live_409(client_for, users, db_session: Session):
    loser = _customer(db_session, "DL")
    winner = _customer(db_session, "DW")
    winner.deleted_at = datetime.now(timezone.utc)
    db_session.flush()
    assert _post_merge(client_for(users["admin"]), loser.id, winner.id).status_code == 409


def test_merge_endpoint_idempotent_409(client_for, users, db_session: Session):
    loser = _customer(db_session, "IL")
    winner = _customer(db_session, "IW")
    db_session.flush()
    admin = client_for(users["admin"])
    assert _post_merge(admin, loser.id, winner.id).status_code == 200
    assert _post_merge(admin, loser.id, winner.id).status_code == 409  # already merged


# --------------------------------------------------------------------------- #
# Single-transaction rollback safety
# --------------------------------------------------------------------------- #
def test_merge_rolls_back_on_error(users, db_session: Session, monkeypatch):
    admin_id = users["admin"].id
    loser = _customer(db_session, "RB-L", notes="n")
    winner = _customer(db_session, "RB-W")
    _job(db_session, loser.id)
    db_session.flush()

    # Force the LAST step (activity log) to raise, after every repoint/mutation staged.
    def boom(*args, **kwargs):
        raise RuntimeError("injected")

    monkeypatch.setattr(customers_service, "log_activity", boom)

    sp = db_session.begin_nested()  # isolate the merge so we can undo just it
    with pytest.raises(RuntimeError):
        customers_service.merge_customers(db_session, loser_id=loser.id, winner_id=winner.id, actor_id=admin_id)
    sp.rollback()
    db_session.expire_all()

    # everything restored: loser live, no merge pointer, its job still under the loser
    lo = db_session.get(Customer, loser.id)
    assert lo.deleted_at is None
    assert lo.merged_into_customer_id is None
    assert _count_where(db_session, Job, customer_id=loser.id) == 1
    assert _count_where(db_session, Job, customer_id=winner.id) == 0


# --------------------------------------------------------------------------- #
# B4-4: GET /customers/{id} merged-loser notice (enriched 404; deleted stay hidden)
# --------------------------------------------------------------------------- #
def test_get_active_customer_still_200(client_for, users, db_session: Session):
    c = _customer(db_session, "Active GET")
    db_session.flush()
    resp = client_for(users["support"]).get(f"/api/v1/customers/{c.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == c.id


def test_get_missing_customer_plain_404(client_for, users):
    resp = client_for(users["support"]).get("/api/v1/customers/999999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Customer not found"


def test_get_soft_deleted_non_merged_plain_404(client_for, users, db_session: Session):
    c = _customer(db_session, "Deleted Not Merged")
    c.deleted_at = datetime.now(timezone.utc)  # deleted but NOT merged
    db_session.flush()
    resp = client_for(users["support"]).get(f"/api/v1/customers/{c.id}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Customer not found"


def test_get_merged_loser_enriched_404(client_for, users, db_session: Session):
    admin_id = users["admin"].id
    loser = _customer(db_session, "Merged Loser GET")
    winner = _customer(db_session, "Merge Winner GET")
    db_session.flush()
    customers_service.merge_customers(db_session, loser_id=loser.id, winner_id=winner.id, actor_id=admin_id)
    db_session.flush()
    resp = client_for(users["support"]).get(f"/api/v1/customers/{loser.id}")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["reason"] == "merged"
    assert detail["merged_into_customer_id"] == winner.id
    assert detail["merged_into_name"] == winner.full_name


def test_get_merged_loser_multi_hop_resolves_to_final_winner(client_for, users, db_session: Session):
    admin_id = users["admin"].id
    loser = _customer(db_session, "Chain L")
    mid = _customer(db_session, "Chain M")
    winner = _customer(db_session, "Chain W")
    db_session.flush()
    customers_service.merge_customers(db_session, loser_id=loser.id, winner_id=mid.id, actor_id=admin_id)
    customers_service.merge_customers(db_session, loser_id=mid.id, winner_id=winner.id, actor_id=admin_id)
    db_session.flush()
    resp = client_for(users["support"]).get(f"/api/v1/customers/{loser.id}")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["reason"] == "merged"
    assert detail["merged_into_customer_id"] == winner.id  # the FINAL winner, not the mid hop


def test_get_merged_loser_deadend_winner_deleted_plain_404(client_for, users, db_session: Session):
    admin_id = users["admin"].id
    loser = _customer(db_session, "Deadend L")
    winner = _customer(db_session, "Deadend W")
    db_session.flush()
    customers_service.merge_customers(db_session, loser_id=loser.id, winner_id=winner.id, actor_id=admin_id)
    winner.deleted_at = datetime.now(timezone.utc)  # winner later soft-deleted -> chain dead-ends
    db_session.flush()
    resp = client_for(users["support"]).get(f"/api/v1/customers/{loser.id}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Customer not found"  # falls back to plain 404


# --------------------------------------------------------------------------- #
# Stage 3: capture the loser's differing customer-level fields as a variant
# --------------------------------------------------------------------------- #
def _variants_for(db: Session, customer_id: int) -> list[CustomerContactVariant]:
    return list(
        db.scalars(
            select(CustomerContactVariant).where(
                CustomerContactVariant.customer_id == customer_id,
                CustomerContactVariant.deleted_at.is_(None),
            )
        ).all()
    )


def test_merge_captures_variant_when_loser_differs(users, db_session: Session):
    admin_id = users["admin"].id
    loser = _customer(
        db_session, "Stuart White", email="stuart.old@example.com", phone="0400 111 222", suburb="Sunbury"
    )
    winner = _customer(
        db_session, "Stuart W", email="stuart@example.com", phone="0400 111 222", suburb="Sunbury"
    )
    db_session.flush()
    customers_service.merge_customers(db_session, loser_id=loser.id, winner_id=winner.id, actor_id=admin_id)
    db_session.flush()

    variants = _variants_for(db_session, winner.id)
    assert len(variants) == 1
    v = variants[0]
    assert v.source_type == "merged_customer"
    assert v.source_customer_id == loser.id           # stored in DB (not exposed via API)
    assert v.display_name == "Stuart White"           # name differs -> captured
    assert v.email == "stuart.old@example.com"        # email differs -> captured
    assert v.phone is None                            # phone identical -> NOT captured
    assert v.suburb is None                           # suburb identical -> NOT captured
    assert v.label == "Merged customer details"


def test_merge_captures_when_winner_field_blank(users, db_session: Session):
    admin_id = users["admin"].id
    loser = _customer(db_session, "Jane Doe", phone="0411 000 000")
    winner = _customer(db_session, "Jane Doe")  # same name, no phone on the winner
    db_session.flush()
    customers_service.merge_customers(db_session, loser_id=loser.id, winner_id=winner.id, actor_id=admin_id)
    db_session.flush()

    variants = _variants_for(db_session, winner.id)
    assert len(variants) == 1
    assert variants[0].phone == "0411 000 000"  # loser has it, winner blank -> meaningful difference
    assert variants[0].display_name is None     # identical name -> NOT captured


def test_merge_no_variant_when_identical(users, db_session: Session):
    admin_id = users["admin"].id
    loser = _customer(db_session, "Same Person", email="same@example.com", phone="0400 999 888")
    winner = _customer(db_session, "Same Person", email="same@example.com", phone="0400 999 888")
    db_session.flush()
    customers_service.merge_customers(db_session, loser_id=loser.id, winner_id=winner.id, actor_id=admin_id)
    db_session.flush()
    assert _variants_for(db_session, winner.id) == []  # nothing differs -> no variant


def test_merge_no_variant_when_loser_fields_empty(users, db_session: Session):
    admin_id = users["admin"].id
    loser = _customer(db_session, "Winner Co")  # same name, no contact fields
    winner = _customer(db_session, "Winner Co", email="contact@winner.example", phone="0400 1")
    db_session.flush()
    customers_service.merge_customers(db_session, loser_id=loser.id, winner_id=winner.id, actor_id=admin_id)
    db_session.flush()
    assert _variants_for(db_session, winner.id) == []


def test_merge_winner_primary_fields_unchanged(users, db_session: Session):
    admin_id = users["admin"].id
    loser = _customer(
        db_session, "Loser Name", email="loser@example.com", phone="0400 000 111", suburb="Oldtown"
    )
    winner = _customer(
        db_session, "Winner Name", email="winner@example.com", phone="0400 222 333", suburb="Newtown"
    )
    db_session.flush()
    customers_service.merge_customers(db_session, loser_id=loser.id, winner_id=winner.id, actor_id=admin_id)
    db_session.flush()

    wi = db_session.get(Customer, winner.id)
    assert wi.full_name == "Winner Name"
    assert wi.email == "winner@example.com"
    assert wi.phone == "0400 222 333"
    assert wi.suburb == "Newtown"  # winner's primary fields are never overwritten by the variant


def test_merge_variant_source_id_not_exposed_by_endpoint(users, client_for, db_session: Session):
    admin_id = users["admin"].id
    loser = _customer(db_session, "Hidden Loser", email="hidden@example.com")
    winner = _customer(db_session, "Visible Winner", email="visible@example.com")
    db_session.flush()
    customers_service.merge_customers(db_session, loser_id=loser.id, winner_id=winner.id, actor_id=admin_id)
    db_session.flush()

    resp = client_for(users["support"]).get(f"/api/v1/customers/{winner.id}/contact-variants")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["source_type"] == "merged_customer"
    assert item["display_name"] == "Hidden Loser"
    # the merged-loser id stays hidden: source FK ids are never returned by the API
    assert "source_customer_id" not in item
    assert "source_import_row_id" not in item
    assert "source_document_id" not in item
