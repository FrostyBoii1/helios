"""Stage 2 tests: CustomerContactVariant storage + read-only API.

Synthetic data inside the rolled-back db_session — nothing persists. Verifies the
table/model exists, the read endpoint returns a LIVE customer's ACTIVE variants,
soft-deleted variants are excluded, and missing / soft-deleted / merged-loser
customers expose no variants (plain 404). Stage 2 has NO create/update/delete API,
no merge capture, no backfill, no promote — storage + read only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.customer_contact_variant import CustomerContactVariant
from app.models.enums import CustomerContactVariantSource
from app.services import customers as customers_service


def _variant(
    db: Session,
    customer_id: int,
    *,
    source_type: str = CustomerContactVariantSource.MANUAL.value,
    **kw,
) -> CustomerContactVariant:
    v = CustomerContactVariant(customer_id=customer_id, source_type=source_type, **kw)
    db.add(v)
    db.flush()
    return v


def test_model_table_insert_and_read(customer, db_session: Session):
    v = _variant(
        db_session, customer.id, display_name="Stuart W.", email="alt@example.com", phone="0400 000 000"
    )
    got = db_session.get(CustomerContactVariant, v.id)
    assert got is not None
    assert got.customer_id == customer.id
    assert got.display_name == "Stuart W."
    assert got.source_type == "manual"
    assert got.deleted_at is None


def test_list_contact_variants_service_active_only(customer, db_session: Session):
    active = _variant(db_session, customer.id, email="a@example.com")
    archived = _variant(db_session, customer.id, email="old@example.com")
    archived.deleted_at = datetime.now(timezone.utc)  # archived via soft-delete
    db_session.flush()
    items = customers_service.list_contact_variants(db_session, customer)
    ids = [v.id for v in items]
    assert active.id in ids
    assert archived.id not in ids


def test_endpoint_returns_active_variants(customer, client_for, users, db_session: Session):
    _variant(
        db_session, customer.id, label="From merge", email="alt@example.com",
        source_type=CustomerContactVariantSource.MERGED_CUSTOMER.value,
    )
    db_session.flush()
    resp = client_for(users["support"]).get(f"/api/v1/customers/{customer.id}/contact-variants")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["customer_id"] == customer.id
    assert item["email"] == "alt@example.com"
    assert item["source_type"] == "merged_customer"
    assert item["label"] == "From merge"


def test_endpoint_excludes_soft_deleted(customer, client_for, users, db_session: Session):
    _variant(db_session, customer.id, email="keep@example.com")
    gone = _variant(db_session, customer.id, email="gone@example.com")
    gone.deleted_at = datetime.now(timezone.utc)
    db_session.flush()
    resp = client_for(users["support"]).get(f"/api/v1/customers/{customer.id}/contact-variants")
    assert resp.status_code == 200
    emails = [v["email"] for v in resp.json()["items"]]
    assert "keep@example.com" in emails
    assert "gone@example.com" not in emails


def test_endpoint_empty_when_none(customer, client_for, users):
    resp = client_for(users["support"]).get(f"/api/v1/customers/{customer.id}/contact-variants")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    assert resp.json()["items"] == []


def test_endpoint_missing_customer_404(client_for, users):
    resp = client_for(users["support"]).get("/api/v1/customers/999999/contact-variants")
    assert resp.status_code == 404


def test_endpoint_soft_deleted_customer_404_no_variants(client_for, users, db_session: Session):
    c = Customer(full_name="Deleted Cust CV")
    db_session.add(c)
    db_session.flush()
    _variant(db_session, c.id, email="hidden@example.com")  # a variant exists...
    c.deleted_at = datetime.now(timezone.utc)  # ...but the customer is soft-deleted
    db_session.flush()
    resp = client_for(users["support"]).get(f"/api/v1/customers/{c.id}/contact-variants")
    assert resp.status_code == 404  # no variants exposed for a non-active customer


def test_endpoint_merged_loser_404_no_variants(client_for, users, db_session: Session):
    loser = Customer(full_name="Merge Loser CV")
    winner = Customer(full_name="Merge Winner CV")
    db_session.add_all([loser, winner])
    db_session.flush()
    _variant(db_session, loser.id, email="loser-alt@example.com")
    loser.merged_into_customer_id = winner.id
    loser.merged_at = datetime.now(timezone.utc)
    loser.deleted_at = datetime.now(timezone.utc)
    db_session.flush()
    resp = client_for(users["support"]).get(f"/api/v1/customers/{loser.id}/contact-variants")
    assert resp.status_code == 404  # a merged-loser id exposes no variants
