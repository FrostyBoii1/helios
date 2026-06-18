"""Section B1 — advisory customer-match candidate engine (read-only).

Pure scoring-rule unit tests + a read-only endpoint test. Nothing here commits,
merges, or links — the engine is advisory only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.enums import ImportBatchStatus, ImportRowClass, ImportRowReviewStatus
from app.models.import_staging import ImportBatch, ImportCustomerGroup, ImportRow
from app.services.import_matching import build_signature as sig, find_candidates, score


# --------------------------------------------------------------------------- #
# Pure scoring rules
# --------------------------------------------------------------------------- #
def test_exact_name_plus_corroborators_is_strong():
    a = sig(name="Phillip Schuman", phones=["0427327608"], emails=["p@x.com"],
            legacy_ref="SC0542", address="37 Schumans Road, Tingha NSW 2369")
    b = sig(name="Phillip Schuman", phones=["0427327608"], emails=["p@x.com"],
            legacy_ref="SC0542", address="House 2 - 37 Schumans Road, Tingha NSW 2369")
    reasons, conf = score(a, b)
    assert conf == "strong"
    assert "exact name" in reasons
    assert "shared phone" in reasons and "shared email" in reasons
    assert "shared legacy reference" in reasons
    assert "address differs only by House/Unit prefix" in reasons


def test_exact_name_without_corroborator_is_weak():
    # Two unrelated namesakes (different phone + address) -> weak, manual.
    a = sig(name="James Harris", phones=["0411111111"], address="1 A St, X")
    b = sig(name="James Harris", phones=["0422222222"], address="9 Z Rd, Y")
    reasons, conf = score(a, b)
    assert reasons == ["exact name"] and conf == "weak"


def test_spouse_order_variation():
    corr = score(sig(name="Trevor and Wendy Allen", phones=["0400000001"]),
                 sig(name="Wendy and Trevor Allen", phones=["0400000001"]))
    assert "possible spouse/order variation" in corr[0] and corr[1] == "medium"
    bare = score(sig(name="Trevor and Wendy Allen"), sig(name="Wendy and Trevor Allen"))
    assert "possible spouse/order variation" in bare[0] and bare[1] == "weak"


def test_ampersand_normalizes_like_and():
    reasons, _ = score(sig(name="Heidi Johnston & Bruce Bodycott"),
                       sig(name="Heidi Johnston and Bruce Bodycott"))
    assert "possible spouse/order variation" in reasons


def test_subset_same_surname():
    reasons, conf = score(sig(name="Fiona Judson", phones=["0400000002"]),
                          sig(name="Fiona and Mark Judson", phones=["0400000002"]))
    assert "subset same-surname match" in reasons and conf == "medium"
    # different surname -> not a subset candidate
    assert score(sig(name="Fiona Smith"), sig(name="Fiona and Mark Judson")) == ([], None)


def test_company_trust_names_are_conservative():
    # Different forms of an entity name must NOT fuzzy-merge.
    a = sig(name="C &J Horton PTY as Trustees for Horton Family Superannuation Fund")
    b = sig(name="Horton Family Trust")
    assert score(a, b) == ([], None)
    # An exact entity-string match still surfaces (as a weak exact-name candidate).
    reasons, conf = score(sig(name="Grow Nuts Pty Ltd"), sig(name="Grow Nuts Pty Ltd"))
    assert reasons == ["exact name"] and conf == "weak"


def test_shared_legacy_reference_is_surfaced():
    # Same ref, different name -> surfaced as a reason (the source's own grouping).
    reasons, conf = score(sig(name="Alice Brown", legacy_ref="SC9001"),
                          sig(name="Bob Green", legacy_ref="SC9001"))
    assert reasons == ["shared legacy reference"] and conf == "medium"
    # Same ref + exact name -> strong.
    r2, c2 = score(sig(name="Alice Brown", legacy_ref="SC9001"),
                   sig(name="Alice Brown", legacy_ref="SC9001"))
    assert "shared legacy reference" in r2 and c2 == "strong"


def test_address_house_prefix_is_a_corroborator():
    reasons, conf = score(
        sig(name="Pat Q", address="37 Schumans Road, Tingha NSW 2369"),
        sig(name="Pat Q", address="House 2 - 37 Schumans Road, Tingha NSW 2369"),
    )
    assert "address differs only by House/Unit prefix" in reasons and conf == "strong"


def test_no_signal_no_candidate():
    assert score(sig(name="Alice Brown", phones=["0411111111"]),
                 sig(name="Zoe White", phones=["0499999999"])) == ([], None)


# --------------------------------------------------------------------------- #
# Read-only endpoint
# --------------------------------------------------------------------------- #
def _seed_rows(db: Session) -> tuple[ImportBatch, list[ImportRow]]:
    b = ImportBatch(source_filename="syn.xlsx", sheet_name="COMPLETED",
                    status=ImportBatchStatus.REVIEWING.value)
    db.add(b)
    db.flush()
    rows = []
    def row(idx, name, phone, ref):
        r = ImportRow(
            batch_id=b.id, source_row_index=idx, row_class=ImportRowClass.JOB.value,
            legacy_reference=ref, raw={},
            parsed={"customer_name": name, "phones": [{"number": phone}], "emails": [], "address": "1 Test St"},
            review_status=ImportRowReviewStatus.PENDING.value,
        )
        db.add(r); db.flush(); rows.append(r); return r
    row(2, "Dana Fox", "0400123123", "SC1")
    row(3, "Dana Fox", "0400123123", "SC2")        # same name + phone -> strong candidate
    row(4, "Unrelated Person", "0499999999", "SC3")  # not a candidate
    return b, rows


def test_match_candidates_endpoint(client_for, users, db_session: Session):
    b, rows = _seed_rows(db_session)
    admin = client_for(users["admin"])
    res = admin.get(f"/api/v1/imports/{b.id}/rows/{rows[0].id}/match-candidates")
    assert res.status_code == 200, res.text
    cands = res.json()
    match = [c for c in cands if c["kind"] == "batch_row" and c["source_row_index"] == 3]
    assert len(match) == 1
    assert match[0]["confidence"] == "strong"
    assert "exact name" in match[0]["reasons"] and "shared phone" in match[0]["reasons"]
    # the unrelated row is NOT surfaced
    assert all(c["source_row_index"] != 4 for c in cands)


def test_match_candidates_admin_only(client_for, users, db_session: Session):
    b, rows = _seed_rows(db_session)
    res = client_for(users["support"]).get(
        f"/api/v1/imports/{b.id}/rows/{rows[0].id}/match-candidates"
    )
    assert res.status_code == 403


def test_find_candidates_is_read_only(db_session: Session):
    b, rows = _seed_rows(db_session)
    find_candidates(db_session, rows[0])
    # no pending writes were introduced by the advisory query
    assert not db_session.new and not db_session.dirty and not db_session.deleted


# --------------------------------------------------------------------------- #
# B (stabilization): duplicate same-customer candidates collapse to one
# --------------------------------------------------------------------------- #
def test_committed_duplicates_collapse_to_one_live_customer(db_session: Session):
    """A live customer plus its committed import rows surface as ONE candidate;
    reasons merge across the duplicates; a pending sibling (no committed customer)
    stays its own candidate."""
    cust = Customer(full_name="Stuart White", address_line1="1 Test St")
    db_session.add(cust)
    db_session.flush()
    b = ImportBatch(
        source_filename="dup.xlsx", sheet_name="COMPLETED",
        status=ImportBatchStatus.REVIEWING.value,
    )
    db_session.add(b)
    db_session.flush()

    def _row(idx, status, committed_cid):
        r = ImportRow(
            batch_id=b.id, source_row_index=idx, row_class=ImportRowClass.JOB.value,
            legacy_reference=f"SC{idx}", raw={},
            parsed={
                "customer_name": "Stuart White",
                "phones": [{"number": "0400555111"}],
                "emails": [],
                "address": "1 Test St",
            },
            review_status=status, committed_customer_id=committed_cid,
        )
        db_session.add(r)
        db_session.flush()
        return r

    # Two COMMITTED rows both resolve to the live customer (match target on phone).
    _row(2, ImportRowReviewStatus.COMMITTED.value, cust.id)
    _row(3, ImportRowReviewStatus.COMMITTED.value, cust.id)
    # A PENDING sibling (no committed_customer_id) — must remain a separate candidate.
    pending = _row(4, ImportRowReviewStatus.PENDING.value, None)
    # The row we surface candidates for.
    target = _row(5, ImportRowReviewStatus.PENDING.value, None)

    cands = find_candidates(db_session, target)

    # Every candidate pointing at the live customer collapses to exactly one.
    for_cust = [c for c in cands if c["customer_id"] == cust.id]
    assert len(for_cust) == 1
    assert for_cust[0]["kind"] == "live_customer"  # live identity preferred
    # Reasons merged across the committed rows (shared phone) and the live customer
    # (address match), de-duplicated.
    reasons = for_cust[0]["reasons"]
    assert "exact name" in reasons
    # "shared phone" can ONLY come from the committed batch rows (the live customer has
    # no phone), yet the canonical candidate is the live_customer — proving the merge.
    assert "shared phone" in reasons
    assert "address match" in reasons         # shared by the committed rows and the live customer
    assert len(reasons) == len(set(reasons))  # no duplicate reasons
    # The pending sibling (customer_id None) is NOT collapsed.
    pend = [c for c in cands if c["customer_id"] is None and c["row_id"] == pending.id]
    assert len(pend) == 1


def test_pending_duplicates_are_not_collapsed(db_session: Session):
    """Two PENDING rows for the same person stay as two candidates (no customer_id
    to collapse on) — collapsing only applies to committed/live customers."""
    b = ImportBatch(
        source_filename="pend.xlsx", sheet_name="COMPLETED",
        status=ImportBatchStatus.REVIEWING.value,
    )
    db_session.add(b)
    db_session.flush()

    def _row(idx):
        r = ImportRow(
            batch_id=b.id, source_row_index=idx, row_class=ImportRowClass.JOB.value,
            legacy_reference=f"PC{idx}", raw={},
            parsed={"customer_name": "Jamie Green", "phones": [{"number": "0400777222"}],
                    "emails": [], "address": "2 Pend St"},
            review_status=ImportRowReviewStatus.PENDING.value, committed_customer_id=None,
        )
        db_session.add(r)
        db_session.flush()
        return r

    r2 = _row(2)
    r3 = _row(3)
    target = _row(4)

    cands = find_candidates(db_session, target)
    pending_ids = {c["row_id"] for c in cands if c["customer_id"] is None}
    assert r2.id in pending_ids and r3.id in pending_ids  # both kept, not collapsed


def test_candidate_exposes_group_id(db_session: Session):
    """B (stabilization): a batch-row candidate that is already in a group surfaces its
    customer_group_id so the UI can offer "Join this group" rather than steal it."""
    b = ImportBatch(source_filename="grp.xlsx", sheet_name="COMPLETED",
                    status=ImportBatchStatus.REVIEWING.value)
    db_session.add(b)
    db_session.flush()

    def _mk(idx):
        r = ImportRow(
            batch_id=b.id, source_row_index=idx, row_class=ImportRowClass.JOB.value,
            legacy_reference=f"G{idx}", raw={},
            parsed={"customer_name": "Pat Lin", "phones": [{"number": "0400888999"}],
                    "emails": [], "address": "1 G St"},
            review_status=ImportRowReviewStatus.PENDING.value,
        )
        db_session.add(r)
        db_session.flush()
        return r

    grouped_row = _mk(2)
    grp = ImportCustomerGroup(batch_id=b.id, primary_row_id=grouped_row.id)
    db_session.add(grp)
    db_session.flush()
    grouped_row.customer_group_id = grp.id
    target = _mk(3)
    db_session.flush()

    cands = find_candidates(db_session, target)
    grouped_cand = [c for c in cands if c["row_id"] == grouped_row.id]
    assert len(grouped_cand) == 1
    assert grouped_cand[0]["customer_group_id"] == grp.id
    # an ungrouped candidate carries no group id
    assert all(c["customer_group_id"] is None for c in cands if c["row_id"] != grouped_row.id)


# --------------------------------------------------------------------------- #
# #5b: a reversed sibling / soft-deleted committed customer is not offered
# --------------------------------------------------------------------------- #
def _white_row(db: Session, b: ImportBatch, idx: int, *, status: str, committed_cid):
    r = ImportRow(
        batch_id=b.id, source_row_index=idx, row_class=ImportRowClass.JOB.value,
        legacy_reference=f"W{idx}", raw={},
        parsed={"customer_name": "Stuart White", "phones": [{"number": "0400555111"}],
                "emails": [], "address": "1 Test St"},
        review_status=status, committed_customer_id=committed_cid,
    )
    db.add(r)
    db.flush()
    return r


def test_reversed_sibling_with_deleted_customer_not_offered(db_session: Session):
    """#5b: a REVERSED sibling whose committed_customer_id points at a now soft-deleted
    customer must NOT surface that customer as a "Use this customer" candidate, and the
    reversed row itself produces no candidate."""
    cust = Customer(full_name="Stuart White", address_line1="1 Test St")
    db_session.add(cust)
    db_session.flush()
    cust.deleted_at = datetime.now(timezone.utc)  # reversed -> soft-deleted
    db_session.flush()
    b = ImportBatch(source_filename="rev.xlsx", sheet_name="COMPLETED",
                    status=ImportBatchStatus.REVIEWING.value)
    db_session.add(b)
    db_session.flush()

    reversed_row = _white_row(db_session, b, 2, status=ImportRowReviewStatus.REVERSED.value, committed_cid=cust.id)
    target = _white_row(db_session, b, 3, status=ImportRowReviewStatus.PENDING.value, committed_cid=None)

    cands = find_candidates(db_session, target)
    # The soft-deleted customer is never offered (neither via the reversed batch_row nor
    # the live_customer branch, which filters deleted_at).
    assert all(c["customer_id"] != cust.id for c in cands)
    # The reversed sibling produces no candidate at all (terminal, excluded).
    assert all(c["row_id"] != reversed_row.id for c in cands)


def test_active_committed_sibling_offers_one_customer(db_session: Session):
    """A single ACTIVE committed sibling still surfaces exactly one usable
    existing-customer candidate (collapsed to the live customer)."""
    cust = Customer(full_name="Stuart White", address_line1="1 Test St")
    db_session.add(cust)
    db_session.flush()
    b = ImportBatch(source_filename="act.xlsx", sheet_name="COMPLETED",
                    status=ImportBatchStatus.REVIEWING.value)
    db_session.add(b)
    db_session.flush()

    _white_row(db_session, b, 2, status=ImportRowReviewStatus.COMMITTED.value, committed_cid=cust.id)
    target = _white_row(db_session, b, 3, status=ImportRowReviewStatus.PENDING.value, committed_cid=None)

    cands = find_candidates(db_session, target)
    for_cust = [c for c in cands if c["customer_id"] == cust.id]
    assert len(for_cust) == 1
    assert for_cust[0]["kind"] == "live_customer"


def test_active_plus_reversed_sibling_dedupes_to_active_only(db_session: Session):
    """One sibling stayed committed (active customer), another was reversed (its customer
    soft-deleted): only the active customer is offered, as exactly one candidate."""
    active = Customer(full_name="Stuart White", address_line1="1 Test St")
    deleted = Customer(full_name="Stuart White", address_line1="1 Test St")
    db_session.add_all([active, deleted])
    db_session.flush()
    deleted.deleted_at = datetime.now(timezone.utc)
    db_session.flush()
    b = ImportBatch(source_filename="mix.xlsx", sheet_name="COMPLETED",
                    status=ImportBatchStatus.REVIEWING.value)
    db_session.add(b)
    db_session.flush()

    _white_row(db_session, b, 2, status=ImportRowReviewStatus.COMMITTED.value, committed_cid=active.id)
    reversed_row = _white_row(db_session, b, 3, status=ImportRowReviewStatus.REVERSED.value, committed_cid=deleted.id)
    target = _white_row(db_session, b, 4, status=ImportRowReviewStatus.PENDING.value, committed_cid=None)

    cands = find_candidates(db_session, target)
    offered = {c["customer_id"] for c in cands if c["customer_id"] is not None}
    assert offered == {active.id}  # only the active customer, never the deleted one
    assert all(c["row_id"] != reversed_row.id for c in cands)  # reversed sibling excluded
    assert len([c for c in cands if c["customer_id"] == active.id]) == 1  # collapsed to one


def test_pending_grouped_candidate_still_exposes_group_id(db_session: Session):
    """The #5b fix must not affect pending grouped candidates — they still expose
    customer_group_id (for "Join this group") and carry no committed customer_id."""
    b = ImportBatch(source_filename="grp2.xlsx", sheet_name="COMPLETED",
                    status=ImportBatchStatus.REVIEWING.value)
    db_session.add(b)
    db_session.flush()

    def _mk(idx):
        r = ImportRow(
            batch_id=b.id, source_row_index=idx, row_class=ImportRowClass.JOB.value,
            legacy_reference=f"GG{idx}", raw={},
            parsed={"customer_name": "Pat Lin", "phones": [{"number": "0400888999"}],
                    "emails": [], "address": "1 G St"},
            review_status=ImportRowReviewStatus.PENDING.value,
        )
        db_session.add(r)
        db_session.flush()
        return r

    grouped_row = _mk(2)
    grp = ImportCustomerGroup(batch_id=b.id, primary_row_id=grouped_row.id)
    db_session.add(grp)
    db_session.flush()
    grouped_row.customer_group_id = grp.id
    target = _mk(3)
    db_session.flush()

    cands = find_candidates(db_session, target)
    grouped_cand = [c for c in cands if c["row_id"] == grouped_row.id]
    assert len(grouped_cand) == 1
    assert grouped_cand[0]["customer_group_id"] == grp.id
    assert grouped_cand[0]["customer_id"] is None  # pending: no committed customer
