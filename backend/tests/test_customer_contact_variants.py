"""Stage 2 tests: CustomerContactVariant storage + read-only API.

Synthetic data inside the rolled-back db_session — nothing persists. Verifies the
table/model exists, the read endpoint returns a LIVE customer's ACTIVE variants,
soft-deleted variants are excluded, and missing / soft-deleted / merged-loser
customers expose no variants (plain 404). Stage 2 has NO create/update/delete API,
no merge capture, no backfill, no promote — storage + read only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
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


# --------------------------------------------------------------------------- #
# Stage 4: admin-only manual ADD + ARCHIVE
# --------------------------------------------------------------------------- #
def test_admin_can_create_manual_variant(customer, client_for, users):
    resp = client_for(users["admin"]).post(
        f"/api/v1/customers/{customer.id}/contact-variants",
        json={"label": "Old address", "display_name": "J. Doe", "phone": "0400 1", "suburb": "Sunbury"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["source_type"] == "manual"
    assert body["display_name"] == "J. Doe"
    assert body["phone"] == "0400 1"
    assert body["label"] == "Old address"
    assert "source_customer_id" not in body
    assert "source_import_row_id" not in body
    assert "source_document_id" not in body


def test_create_variant_non_admin_forbidden(customer, client_for, users):
    for role in ("support", "sales", "scheduling", "approvals"):
        resp = client_for(users[role]).post(
            f"/api/v1/customers/{customer.id}/contact-variants", json={"email": "x@example.com"}
        )
        assert resp.status_code == 403, role


def test_create_rejects_empty_variant(customer, client_for, users):
    admin = client_for(users["admin"])
    # label/note only -> no detail field -> rejected
    assert admin.post(
        f"/api/v1/customers/{customer.id}/contact-variants",
        json={"label": "Just a label", "note": "and a note"},
    ).status_code == 400
    # whitespace-only detail is also empty
    assert admin.post(
        f"/api/v1/customers/{customer.id}/contact-variants", json={"email": "   "}
    ).status_code == 400


def test_create_rejects_missing_customer(client_for, users):
    resp = client_for(users["admin"]).post(
        "/api/v1/customers/999999/contact-variants", json={"email": "x@example.com"}
    )
    assert resp.status_code == 404


def test_create_rejects_soft_deleted_customer(client_for, users, db_session: Session):
    c = Customer(full_name="Deleted Create CV")
    c.deleted_at = datetime.now(timezone.utc)
    db_session.add(c)
    db_session.flush()
    resp = client_for(users["admin"]).post(
        f"/api/v1/customers/{c.id}/contact-variants", json={"email": "x@example.com"}
    )
    assert resp.status_code == 404


def test_create_rejects_merged_loser(client_for, users, db_session: Session):
    loser = Customer(full_name="ML create")
    winner = Customer(full_name="MW create")
    db_session.add_all([loser, winner])
    db_session.flush()
    loser.merged_into_customer_id = winner.id
    loser.merged_at = datetime.now(timezone.utc)
    loser.deleted_at = datetime.now(timezone.utc)
    db_session.flush()
    resp = client_for(users["admin"]).post(
        f"/api/v1/customers/{loser.id}/contact-variants", json={"email": "x@example.com"}
    )
    assert resp.status_code == 404


def test_create_forces_manual_and_ignores_source_ids(customer, client_for, users, db_session: Session):
    # the client tries to inject source_type + source FK ids; they must be ignored
    resp = client_for(users["admin"]).post(
        f"/api/v1/customers/{customer.id}/contact-variants",
        json={
            "email": "alt@example.com",
            "source_type": "merged_customer",
            "source_customer_id": 12345,
            "source_import_row_id": 678,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["source_type"] == "manual"
    v = db_session.scalar(
        select(CustomerContactVariant).where(
            CustomerContactVariant.customer_id == customer.id,
            CustomerContactVariant.email == "alt@example.com",
        )
    )
    assert v is not None
    assert v.source_type == "manual"
    assert v.source_customer_id is None       # injected source ids dropped
    assert v.source_import_row_id is None


def test_archive_soft_deletes_and_excluded_from_read(customer, client_for, users, db_session: Session):
    admin = client_for(users["admin"])
    vid = admin.post(
        f"/api/v1/customers/{customer.id}/contact-variants", json={"email": "archive-me@example.com"}
    ).json()["id"]
    listed = admin.get(f"/api/v1/customers/{customer.id}/contact-variants").json()["items"]
    assert any(v["id"] == vid for v in listed)  # present before archive

    resp = admin.delete(f"/api/v1/customers/{customer.id}/contact-variants/{vid}")
    assert resp.status_code == 200

    after = admin.get(f"/api/v1/customers/{customer.id}/contact-variants").json()["items"]
    assert not any(v["id"] == vid for v in after)  # excluded after archive
    row = db_session.get(CustomerContactVariant, vid)
    assert row is not None and row.deleted_at is not None  # soft-deleted, NOT hard-deleted


def test_archive_non_admin_forbidden(customer, client_for, users, db_session: Session):
    v = _variant(db_session, customer.id, email="x@example.com")
    db_session.flush()
    resp = client_for(users["support"]).delete(
        f"/api/v1/customers/{customer.id}/contact-variants/{v.id}"
    )
    assert resp.status_code == 403
    assert db_session.get(CustomerContactVariant, v.id).deleted_at is None  # unchanged


def test_archive_other_customers_variant_404(customer, client_for, users, db_session: Session):
    other = Customer(full_name="Other Cust CV")
    db_session.add(other)
    db_session.flush()
    v = _variant(db_session, other.id, email="other@example.com")  # belongs to `other`
    db_session.flush()
    # archiving via the WRONG customer path must not touch it
    resp = client_for(users["admin"]).delete(
        f"/api/v1/customers/{customer.id}/contact-variants/{v.id}"
    )
    assert resp.status_code == 404
    assert db_session.get(CustomerContactVariant, v.id).deleted_at is None


def test_archive_source_derived_variant_404(customer, client_for, users, db_session: Session):
    # a merged_customer (source-derived) variant is immutable -> NOT archivable in Stage 4
    v = _variant(
        db_session, customer.id, email="merged@example.com",
        source_type=CustomerContactVariantSource.MERGED_CUSTOMER.value,
    )
    db_session.flush()
    resp = client_for(users["admin"]).delete(
        f"/api/v1/customers/{customer.id}/contact-variants/{v.id}"
    )
    assert resp.status_code == 404
    assert db_session.get(CustomerContactVariant, v.id).deleted_at is None  # not archived


def test_archive_already_archived_404(customer, client_for, users, db_session: Session):
    v = _variant(db_session, customer.id, email="gone@example.com")
    v.deleted_at = datetime.now(timezone.utc)  # already archived
    db_session.flush()
    resp = client_for(users["admin"]).delete(
        f"/api/v1/customers/{customer.id}/contact-variants/{v.id}"
    )
    assert resp.status_code == 404  # idempotent-safe


# --------------------------------------------------------------------------- #
# Edit (PATCH) — Known Customer Details are editable customer-level records
# --------------------------------------------------------------------------- #
def test_admin_can_edit_manual_variant(customer, client_for, users, db_session: Session):
    v = _variant(db_session, customer.id, display_name="Old Name", phone="0400 1")
    db_session.flush()
    resp = client_for(users["admin"]).patch(
        f"/api/v1/customers/{customer.id}/contact-variants/{v.id}",
        json={"display_name": "New Name", "email": "new@example.com"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "New Name"
    assert body["email"] == "new@example.com"
    assert body["phone"] == "0400 1"            # untouched field preserved
    assert body["edited_at"] is not None        # edit marker stamped
    assert body["source_type"] == "manual"      # provenance unchanged
    db_session.refresh(v)
    assert v.display_name == "New Name" and v.edited_by_id == users["admin"].id


def test_edit_variant_non_admin_forbidden(customer, client_for, users, db_session: Session):
    v = _variant(db_session, customer.id, display_name="Keep", phone="0400 1")
    db_session.flush()
    for role in ("support", "sales", "scheduling", "approvals"):
        resp = client_for(users[role]).patch(
            f"/api/v1/customers/{customer.id}/contact-variants/{v.id}",
            json={"display_name": "Hacked"},
        )
        assert resp.status_code == 403, role
    db_session.refresh(v)
    assert v.display_name == "Keep" and v.edited_at is None  # unchanged


def test_edit_changes_only_variant_not_customer(customer, client_for, users, db_session: Session):
    name_before, email_before = customer.full_name, customer.email
    v = _variant(db_session, customer.id, display_name="Alt", email="alt@example.com")
    db_session.flush()
    resp = client_for(users["admin"]).patch(
        f"/api/v1/customers/{customer.id}/contact-variants/{v.id}",
        json={"display_name": "Alt Edited", "email": "alt-edited@example.com"},
    )
    assert resp.status_code == 200
    db_session.refresh(customer)
    assert customer.full_name == name_before    # primary customer NOT mutated
    assert customer.email == email_before


def test_edit_source_derived_variant_preserves_provenance(customer, client_for, users, db_session: Session):
    # A merged_customer (source-derived) variant is now EDITABLE; the edit must keep its
    # source_type + source FK id (immutable provenance) while stamping the edit marker.
    other = Customer(full_name="Merge Source Cust")
    db_session.add(other)
    db_session.flush()
    v = _variant(
        db_session, customer.id, display_name="Merged Alt", email="merged@example.com",
        source_type=CustomerContactVariantSource.MERGED_CUSTOMER.value, source_customer_id=other.id,
    )
    db_session.flush()
    resp = client_for(users["admin"]).patch(
        f"/api/v1/customers/{customer.id}/contact-variants/{v.id}",
        json={"phone": "0411 222 333"},
    )
    assert resp.status_code == 200
    assert resp.json()["source_type"] == "merged_customer"   # provenance label preserved
    assert resp.json()["edited_at"] is not None
    assert "source_customer_id" not in resp.json()           # still DB-only
    db_session.refresh(v)
    assert v.source_type == "merged_customer"
    assert v.source_customer_id == other.id                  # source link untouched
    assert v.phone == "0411 222 333"


def test_edit_rejects_emptying_all_detail_fields(customer, client_for, users, db_session: Session):
    v = _variant(db_session, customer.id, display_name="Only Field")
    db_session.flush()
    # Clearing the only detail field would leave an empty variant -> 400, nothing changed.
    resp = client_for(users["admin"]).patch(
        f"/api/v1/customers/{customer.id}/contact-variants/{v.id}",
        json={"display_name": ""},
    )
    assert resp.status_code == 400
    db_session.refresh(v)
    assert v.display_name == "Only Field" and v.edited_at is None


def test_edit_missing_or_other_customer_variant_404(customer, client_for, users, db_session: Session):
    # missing variant
    assert client_for(users["admin"]).patch(
        f"/api/v1/customers/{customer.id}/contact-variants/999999", json={"phone": "1"}
    ).status_code == 404
    # variant that belongs to ANOTHER customer
    other = Customer(full_name="Other Edit Cust")
    db_session.add(other)
    db_session.flush()
    v = _variant(db_session, other.id, phone="0400 1")
    db_session.flush()
    resp = client_for(users["admin"]).patch(
        f"/api/v1/customers/{customer.id}/contact-variants/{v.id}", json={"phone": "2"}
    )
    assert resp.status_code == 404
    assert db_session.get(CustomerContactVariant, v.id).phone == "0400 1"  # untouched
