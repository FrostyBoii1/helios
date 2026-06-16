"""Section B1 — advisory customer-match candidate engine (read-only).

Pure scoring-rule unit tests + a read-only endpoint test. Nothing here commits,
merges, or links — the engine is advisory only.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.enums import ImportBatchStatus, ImportRowClass, ImportRowReviewStatus
from app.models.import_staging import ImportBatch, ImportRow
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
