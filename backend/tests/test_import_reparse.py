"""Tests for the in-place additive reparse maintenance (Phase: backfill).

Synthetic data only. Covers the pure `compute_additive_patch` helper and the
DB-level dry-run/apply: scope gating, write policy, original_parsed mirroring,
and the guarantee that committed/reversed/linked/wrong-status rows and live
records are never touched.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.customer import Customer
from app.models.enums import ImportBatchStatus, ImportRowClass, ImportRowReviewStatus, JobStatus
from app.models.import_staging import ImportBatch, ImportRow
from app.models.job import Job
from app.services import import_reparse
from app.services import jobs as jobs_service
from app.services.customers import create_customer
from app.services.import_reparse import ADDITIVE_KEYS, compute_additive_patch


# --------------------------------------------------------------------------- #
# Pure helper: compute_additive_patch
# --------------------------------------------------------------------------- #
def test_patch_preserves_name_cell_note():
    patch = compute_additive_patch({"customer_name": "Pat Lee - includes hot water timer"}, {})
    assert patch["customer_name_notes"] == "includes hot water timer"
    assert "removes_old_system" not in patch
    assert "decommission_marker" not in patch


def test_patch_strips_pure_approval():
    # Pure approval → nothing meaningful → no note key.
    assert "customer_name_notes" not in compute_additive_patch(
        {"customer_name": "Jane Doe - APPROVED"}, {}
    )
    # Approval mixed with a real note → only the real note survives.
    patch = compute_additive_patch(
        {"customer_name": "Jane Doe - includes timer - ESSENTIAL APPROVED"}, {}
    )
    assert "includes timer" in patch["customer_name_notes"]
    assert "APPROVED" not in patch["customer_name_notes"]


def test_patch_detects_decommission_variants():
    for cell in (
        "Sam Roe - REMOVE OLD SYSTEM",
        "Sam Roe DECOM",
        "Sam Roe - decommission first",
        "Sam Roe - decommision typo",
        "Sam Roe - decomission typo",
    ):
        patch = compute_additive_patch({"customer_name": cell}, {})
        assert patch["removes_old_system"] is True, cell
        assert patch["decommission_marker"], cell
    # Marker can also come from the Notes cell.
    patch = compute_additive_patch(
        {"customer_name": "Dana Fox", "notes": "REMOVE OLD SYSTEM before install"}, {}
    )
    assert patch["removes_old_system"] is True


def test_patch_fill_only_if_empty_for_name_notes():
    # A reviewer-curated note must NOT be overwritten.
    patch = compute_additive_patch(
        {"customer_name": "Pat Lee - includes hot water timer"},
        {"customer_name_notes": "reviewer wrote this"},
    )
    assert "customer_name_notes" not in patch
    # But parser-owned decommission is still (re)derived.
    patch2 = compute_additive_patch(
        {"customer_name": "Pat Lee DECOM"}, {"customer_name_notes": "reviewer wrote this"}
    )
    assert patch2["removes_old_system"] is True
    assert "customer_name_notes" not in patch2


def test_patch_returns_no_keys_beyond_the_three():
    patch = compute_additive_patch(
        {"customer_name": "Pat Lee - includes timer - REMOVE OLD SYSTEM"}, {}
    )
    assert set(patch).issubset(set(ADDITIVE_KEYS))


def test_patch_does_not_touch_protected_fields_and_is_idempotent():
    parsed = {
        "customer_name": "Pat Lee",
        "sale_date": "01/06/2025",
        "install_date": "02/06/2025",
        "phones": [{"number": "0400000000", "label": ""}],
        "emails": ["x@example.test"],
        "panel_raw": "Longi 440",
        "approval_state": "approved",
    }
    before = dict(parsed)
    patch = compute_additive_patch({"customer_name": "Pat Lee - includes hot water timer"}, parsed)
    merged = {**parsed, **patch}
    # Protected fields unchanged.
    for k, v in before.items():
        assert merged[k] == v
    # Second run is a no-op (idempotent).
    assert compute_additive_patch(
        {"customer_name": "Pat Lee - includes hot water timer"}, merged
    ) == {}


# --------------------------------------------------------------------------- #
# DB integration: dry-run + apply
# --------------------------------------------------------------------------- #
def _seed(db: Session) -> dict:
    b = ImportBatch(
        source_filename="syn.xlsx",
        sheet_name="COMPLETED",
        status=ImportBatchStatus.REVIEWING.value,
    )
    db.add(b)
    db.flush()

    # A real Customer + Job so the "committed"/"reversed" rows can carry valid
    # committed_* FK links (created once; counted into the test's baseline).
    link_cust = create_customer(db, data={"full_name": "Linked Cust"})
    db.flush()
    link_job = jobs_service.create_job(
        db, customer_id=link_cust.id, data={}, year=2025, status=JobStatus.INSTALLED
    )
    db.flush()

    def row(idx, name, status, *, klass="job", linked=False, notes="", original=None, parsed=None):
        r = ImportRow(
            batch_id=b.id,
            source_row_index=idx,
            row_class=klass,
            legacy_reference=f"SCS{idx:04d}",
            raw={"customer_name": name, "notes": notes},
            parsed=parsed if parsed is not None else {"customer_name": name.split(" - ")[0]},
            original_parsed=original,
            review_status=status,
        )
        if linked:
            r.committed_customer_id = link_cust.id
            r.committed_job_id = link_job.id
        db.add(r)
        return r

    rows = {
        "pending_note": row(101, "Cust One - includes hot water timer", "pending"),
        "pending_decom": row(102, "Cust Two - REMOVE OLD SYSTEM", "pending"),
        "approved_note": row(103, "Cust Three - undersold Brighte fees", "approved"),
        "rejected": row(104, "Cust Four - includes timer", "rejected"),
        "skipped": row(105, "Cust Five - DECOM", "skipped"),
        "committed": row(106, "Cust Six - includes timer", "committed", linked=True),
        "reversed": row(107, "Cust Seven - REMOVE OLD SYSTEM", "reversed", linked=True),
        "divider": row(108, "", "pending", klass="divider"),
        # Edited row (original_parsed present) carrying a decommission marker.
        "edited": row(
            109,
            "Cust Nine - REMOVE OLD SYSTEM",
            "pending",
            original={"customer_name": "Cust Nine"},
            parsed={"customer_name": "Cust Nine EDITED"},
        ),
    }
    db.flush()
    return {"batch": b, "rows": rows}


def test_dry_run_writes_nothing(db_session: Session):
    seed = _seed(db_session)
    bid = seed["batch"].id
    snapshot = {r.id: (dict(r.parsed or {}), None if r.original_parsed is None else dict(r.original_parsed))
                for r in db_session.scalars(select(ImportRow).where(ImportRow.batch_id == bid))}

    plan = import_reparse.plan_reparse(db_session, bid)

    # Nothing changed by the dry-run.
    for r in db_session.scalars(select(ImportRow).where(ImportRow.batch_id == bid)):
        assert r.parsed == snapshot[r.id][0]
        assert (None if r.original_parsed is None else dict(r.original_parsed)) == snapshot[r.id][1]

    # Considered = pending/approved job rows only (101,102,103,109) = 4.
    assert plan["rows_considered"] == 4
    assert plan["skipped_committed_reversed_linked"] == 2          # committed + reversed
    assert plan["skipped_wrong_status"] == 2                       # rejected + skipped
    assert plan["skipped_blank_divider_nonjob"] == 1              # divider


def test_apply_updates_only_in_scope_rows(db_session: Session):
    seed = _seed(db_session)
    bid = seed["batch"].id
    rows = seed["rows"]

    c0 = db_session.scalar(select(func.count()).select_from(Customer))
    j0 = db_session.scalar(select(func.count()).select_from(Job))
    a0 = db_session.scalar(select(func.count()).select_from(Activity))
    batch_status0 = seed["batch"].status

    counts = import_reparse.apply_reparse(db_session, bid)
    for r in rows.values():
        db_session.refresh(r)

    # In-scope rows gained the fields.
    assert rows["pending_note"].parsed["customer_name_notes"] == "includes hot water timer"
    assert rows["pending_decom"].parsed["removes_old_system"] is True
    assert rows["pending_decom"].parsed["decommission_marker"]
    assert rows["approved_note"].parsed["customer_name_notes"] == "undersold Brighte fees"

    # Out-of-scope rows untouched (no additive keys written).
    for key in ("rejected", "skipped", "committed", "reversed", "divider"):
        p = rows[key].parsed or {}
        assert "customer_name_notes" not in p
        assert "removes_old_system" not in p
        assert "decommission_marker" not in p

    # original_parsed mirrored on the edited row (so it won't read as "edited").
    assert rows["edited"].parsed["removes_old_system"] is True
    assert rows["edited"].original_parsed["removes_old_system"] is True
    assert counts["original_parsed_mirrored"] == 1

    # Review state + batch status unchanged.
    assert rows["committed"].review_status == "committed"
    assert rows["reversed"].review_status == "reversed"
    assert all(r.reviewer_id is None and r.reviewed_at is None for r in rows.values())
    db_session.refresh(seed["batch"])
    assert seed["batch"].status == batch_status0

    # Zero live records created.
    assert db_session.scalar(select(func.count()).select_from(Customer)) == c0
    assert db_session.scalar(select(func.count()).select_from(Job)) == j0
    assert db_session.scalar(select(func.count()).select_from(Activity)) == a0


def test_apply_is_idempotent(db_session: Session):
    seed = _seed(db_session)
    bid = seed["batch"].id
    first = import_reparse.apply_reparse(db_session, bid)
    assert first["rows_changed"] >= 3
    second = import_reparse.apply_reparse(db_session, bid)
    assert second["rows_changed"] == 0
