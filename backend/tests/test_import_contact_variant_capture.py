"""Corrective pass: import commit preserves a row's DIFFERING customer-level contact
identity as an ``import_row`` CustomerContactVariant on the target customer.

When an import row attaches to an EXISTING customer (B2) or is a grouped DEPENDENT, the
row's name/email/phone used to be discarded (the customer was used as-is). Now the
differing customer-level CONTACT details are captured as a variant on that customer —
additive, never mutating the customer's primary fields. The row's ADDRESS is NOT captured
(it is the job's site, kept job-scoped in Job.details.site). Reversing the row archives the
variant it contributed. Source FK ids stay DB-only (never exposed by the read API).

Synthetic data only; rollback-isolated db_session. No live writes outside the session.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.customer_contact_variant import CustomerContactVariant
from app.models.enums import (
    CustomerContactVariantSource,
    ImportBatchStatus,
    ImportRowClass,
    ImportRowReviewStatus,
)
from app.models.import_staging import ImportBatch, ImportRow
from app.models.job import Job
from app.services import customers as customers_service
from app.services import import_commit, import_review, import_reverse


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _customer(db: Session, **kw) -> Customer:
    c = Customer(**kw)
    db.add(c)
    db.flush()
    return c


def _attach_row(db: Session, *, customer_id: int, parsed: dict, ref: str) -> tuple[ImportBatch, ImportRow]:
    b = ImportBatch(
        source_filename="syn.xlsx", sheet_name="COMPLETED",
        status=ImportBatchStatus.REVIEWING.value,
    )
    db.add(b)
    db.flush()
    row = ImportRow(
        batch_id=b.id, source_row_index=2, row_class=ImportRowClass.JOB.value,
        legacy_reference=ref, raw={"address": parsed.get("address", "")}, parsed=parsed,
        review_status=ImportRowReviewStatus.APPROVED.value,
        customer_resolution_mode="existing", resolved_customer_id=customer_id,
    )
    db.add(row)
    db.flush()
    return b, row


def _grouped(db: Session, users, rows_parsed: list[dict], *, primary_idx: int = 0):
    b = ImportBatch(source_filename="syn.xlsx", sheet_name="COMPLETED", status="reviewing")
    db.add(b)
    db.flush()
    rows = [
        ImportRow(
            batch_id=b.id, source_row_index=i + 2, row_class="job",
            legacy_reference=f"GRPV{i:04d}", raw={"address": p.get("address", "")},
            parsed=p, review_status="pending",
        )
        for i, p in enumerate(rows_parsed)
    ]
    db.add_all(rows)
    db.flush()
    members = [r.id for j, r in enumerate(rows) if j != primary_idx]
    group = import_review.create_group(
        db, b, primary_row_id=rows[primary_idx].id, member_row_ids=members, actor_id=users["admin"].id
    )
    db.flush()
    for r in rows:
        r.review_status = "approved"
    db.flush()
    return b, rows, group


def _variants(db: Session, customer_id: int) -> list[CustomerContactVariant]:
    return list(
        db.scalars(
            select(CustomerContactVariant).where(
                CustomerContactVariant.customer_id == customer_id,
                CustomerContactVariant.deleted_at.is_(None),
            )
        ).all()
    )


# --------------------------------------------------------------------------- #
# Attach (B2 existing): capture differing contact, never mutate the customer
# --------------------------------------------------------------------------- #
def test_attach_different_contact_captures_variant(users, db_session: Session):
    cust = _customer(db_session, full_name="Stuart White", email="stuart@old.com", phone="0400 111 111")
    name_before, email_before, phone_before = cust.full_name, cust.email, cust.phone
    updated_before = cust.updated_at
    parsed = {
        "customer_name": "Stu White", "sale_date": "01/06/2025",
        "emails": ["different@new.com"], "phones": [{"number": "0411 222 333"}],
        "address": "5 Job Site Rd",
    }
    b, row = _attach_row(db_session, customer_id=cust.id, parsed=parsed, ref="ATTV0001")
    res = import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    assert res["committed"] == 1

    vs = _variants(db_session, cust.id)
    assert len(vs) == 1
    v = vs[0]
    assert v.source_type == CustomerContactVariantSource.IMPORT_ROW.value
    assert v.source_import_row_id == row.id          # DB-side provenance
    assert v.display_name == "Stu White"
    assert v.email == "different@new.com"
    assert v.phone == "0411 222 333"
    # Address is NOT captured — the import address is the job's site (job-scoped).
    assert v.address_line1 is None and v.suburb is None and v.postcode is None

    # The existing customer's primary fields are untouched (additive only).
    db_session.refresh(cust)
    assert cust.full_name == name_before == "Stuart White"
    assert cust.email == email_before == "stuart@old.com"
    assert cust.phone == phone_before == "0400 111 111"
    assert cust.updated_at == updated_before          # capture never mutates the customer


def test_attach_identical_contact_no_variant(users, db_session: Session):
    cust = _customer(db_session, full_name="Jane Roe", email="jane@x.com", phone="0400 000 000")
    parsed = {
        "customer_name": "Jane Roe", "sale_date": "01/06/2025",
        "emails": ["JANE@x.com"], "phones": [{"number": "0400 000 000"}], "address": "9 Job Rd",
    }
    b, _row = _attach_row(db_session, customer_id=cust.id, parsed=parsed, ref="ATTV0002")
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    # Name matches, email matches case-insensitively, phone matches -> no redundant variant.
    assert _variants(db_session, cust.id) == []


def test_attach_only_address_differs_no_variant(users, db_session: Session):
    # Same name/email/phone, only the address (= the job site) differs -> NO customer variant.
    cust = _customer(
        db_session, full_name="Same Name", email="same@x.com", phone="0400 1", address_line1="1 Old St"
    )
    parsed = {
        "customer_name": "Same Name", "sale_date": "01/06/2025",
        "emails": ["same@x.com"], "phones": [{"number": "0400 1"}],
        "address": "99 Totally Different Rd, Newtown NSW 2042",
    }
    b, _row = _attach_row(db_session, customer_id=cust.id, parsed=parsed, ref="ATTV0003")
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    assert _variants(db_session, cust.id) == []
    # And the customer's own address is unchanged (attach never mutates the customer).
    assert db_session.get(Customer, cust.id).address_line1 == "1 Old St"


def test_attach_extra_emails_phones_preserved(users, db_session: Session):
    # Name + primary email/phone match; the EXTRA email/phone the customer doesn't hold
    # are preserved (first new value in the column, further extras in the note).
    cust = _customer(db_session, full_name="Multi Contact", email="primary@x.com", phone="0400 1")
    parsed = {
        "customer_name": "Multi Contact", "sale_date": "01/06/2025",
        "emails": ["primary@x.com", "second@x.com", "third@x.com"],
        "phones": [{"number": "0400 1"}, {"number": "0400 2"}], "address": "1 Rd",
    }
    b, _row = _attach_row(db_session, customer_id=cust.id, parsed=parsed, ref="ATTV0006")
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    vs = _variants(db_session, cust.id)
    assert len(vs) == 1
    v = vs[0]
    assert v.display_name is None              # name matched -> not captured
    assert v.email == "second@x.com"           # first NEW email in the column
    assert v.phone == "0400 2"                 # the new phone
    assert "third@x.com" in (v.note or "")     # further extras folded into the note


# --------------------------------------------------------------------------- #
# Grouped: dependents capture; the primary creates the customer (no self-variant)
# --------------------------------------------------------------------------- #
def test_grouped_dependent_different_contact_captures_variant(users, db_session: Session):
    primary = {
        "customer_name": "Bob Smith", "sale_date": "01/06/2025",
        "phones": [{"number": "0400 111 111"}], "address": "1 Site St",
    }
    dependent = {
        "customer_name": "Robert Smith", "sale_date": "01/06/2025",
        "phones": [{"number": "0422 999 999"}], "address": "2 Site St",
    }
    b, rows, _group = _grouped(db_session, users, [primary, dependent])
    res = import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    assert res["committed"] == 2

    cust_id = db_session.get(ImportRow, rows[0].id).committed_customer_id
    cust = db_session.get(Customer, cust_id)
    assert cust.full_name == "Bob Smith"       # the primary created the customer
    vs = _variants(db_session, cust_id)
    assert len(vs) == 1                         # ONE variant, from the dependent only
    v = vs[0]
    assert v.source_import_row_id == rows[1].id
    assert v.display_name == "Robert Smith"
    assert v.phone == "0422 999 999"


def test_grouped_same_name_different_sites_no_variant(users, db_session: Session):
    # One customer, three jobs with three different SITES (same person). The differing
    # addresses are job sites (details.site) — they must NOT become customer variants.
    rows_parsed = [
        {"customer_name": "Site Owner", "sale_date": "01/06/2025", "address": "1 First St, A NSW 2000"},
        {"customer_name": "Site Owner", "sale_date": "01/06/2025", "address": "2 Second St, B NSW 2001"},
        {"customer_name": "Site Owner", "sale_date": "01/06/2025", "address": "3 Third St, C NSW 2002"},
    ]
    b, rows, _group = _grouped(db_session, users, rows_parsed)
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    cust_id = db_session.get(ImportRow, rows[0].id).committed_customer_id
    assert _variants(db_session, cust_id) == []


# --------------------------------------------------------------------------- #
# Read API: import_row variants expose source_type but NOT the source FK ids
# --------------------------------------------------------------------------- #
def test_import_variant_read_omits_source_ids(users, client_for, db_session: Session):
    cust = _customer(db_session, full_name="Read Test", email="r@x.com")
    parsed = {
        "customer_name": "Read Alt", "sale_date": "01/06/2025",
        "emails": ["alt@x.com"], "address": "1 Rd",
    }
    b, _row = _attach_row(db_session, customer_id=cust.id, parsed=parsed, ref="ATTV0007")
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)

    body = client_for(users["support"]).get(f"/api/v1/customers/{cust.id}/contact-variants").json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["source_type"] == "import_row"
    assert item["display_name"] == "Read Alt"
    assert item["email"] == "alt@x.com"
    # The DB-side source FK ids are never serialised.
    assert "source_import_row_id" not in item
    assert "source_customer_id" not in item
    assert "source_document_id" not in item


# --------------------------------------------------------------------------- #
# Reverse archives the variant the row contributed (additive cleanup)
# --------------------------------------------------------------------------- #
def test_reverse_archives_contributed_variant(users, db_session: Session):
    cust = _customer(db_session, full_name="Keep Me", email="keep@x.com", phone="0400 1")
    parsed = {
        "customer_name": "Alt Name", "sale_date": "01/06/2025",
        "phones": [{"number": "0499 9"}], "address": "1 Rd",
    }
    b, row = _attach_row(db_session, customer_id=cust.id, parsed=parsed, ref="ATTV0008")
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    vs = _variants(db_session, cust.id)
    assert len(vs) == 1
    vid = vs[0].id

    row = db_session.get(ImportRow, row.id)
    out = import_reverse.reverse_row(db_session, row, actor_id=users["admin"].id)
    assert out["status"] == "reversed"
    assert db_session.get(Customer, cust.id).deleted_at is None   # existing customer KEPT
    archived = db_session.get(CustomerContactVariant, vid)
    assert archived.deleted_at is not None                        # soft-deleted, not hard-deleted
    assert _variants(db_session, cust.id) == []                   # excluded from active reads


# --------------------------------------------------------------------------- #
# Source provenance is exposed safely (no raw internal FK ids)
# --------------------------------------------------------------------------- #
def test_import_variant_exposes_safe_provenance(users, client_for, db_session: Session):
    cust = _customer(db_session, full_name="Prov Cust", email="p@x.com")
    parsed = {
        "customer_name": "Prov Alt", "sale_date": "01/06/2025",
        "emails": ["prov-alt@x.com"], "address": "1 Rd",
    }
    b, row = _attach_row(db_session, customer_id=cust.id, parsed=parsed, ref="PROV0001")
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)

    row = db_session.get(ImportRow, row.id)
    job = db_session.get(Job, row.committed_job_id)
    item = client_for(users["support"]).get(
        f"/api/v1/customers/{cust.id}/contact-variants"
    ).json()["items"][0]
    # Safe, API-computed provenance — workbook row number + committed job, not raw FK ids.
    assert item["source_row_number"] == row.source_row_index
    assert item["source_job_case_number"] == job.case_number
    assert item["source_job_id"] == job.id
    assert item["source_reversed"] is False
    assert "source_import_row_id" not in item   # raw internal FK id stays hidden


def test_reverse_preserves_edited_import_variant(users, client_for, db_session: Session):
    # An EDITED import_row variant is curated customer info: reversing the source row must NOT
    # archive/hide it; its provenance then reports the source row as reversed.
    cust = _customer(db_session, full_name="Edit Keeper", email="ek@x.com", phone="0400 1")
    parsed = {
        "customer_name": "Edited Alt", "sale_date": "01/06/2025",
        "phones": [{"number": "0499 9"}], "address": "1 Rd",
    }
    b, row = _attach_row(db_session, customer_id=cust.id, parsed=parsed, ref="EDIT0001")
    import_commit.commit_batch(db_session, b, actor_id=users["admin"].id)
    vid = _variants(db_session, cust.id)[0].id

    # Admin edits the variant -> it becomes curated (edited_at set).
    edit = client_for(users["admin"]).patch(
        f"/api/v1/customers/{cust.id}/contact-variants/{vid}",
        json={"phone": "0488 8 (corrected)"},
    )
    assert edit.status_code == 200 and edit.json()["edited_at"] is not None

    # Reverse the source import row.
    row = db_session.get(ImportRow, row.id)
    out = import_reverse.reverse_row(db_session, row, actor_id=users["admin"].id)
    assert out["status"] == "reversed"

    # The edited variant SURVIVES (not archived) and now reports its source row as reversed.
    survivor = db_session.get(CustomerContactVariant, vid)
    assert survivor.deleted_at is None
    assert survivor.phone == "0488 8 (corrected)"
    prov = customers_service.variant_provenance(db_session, survivor)
    assert prov["source_reversed"] is True
    item = client_for(users["support"]).get(
        f"/api/v1/customers/{cust.id}/contact-variants"
    ).json()["items"][0]
    assert item["id"] == vid and item["source_reversed"] is True
