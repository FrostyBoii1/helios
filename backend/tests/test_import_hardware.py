"""Hardware Parser lane, Stage 4B — import integration for parsed hardware snapshots.

Proves the wiring: ingest parses hardware ONCE into ImportRow.parsed['details']['hardware'];
preview/review return that same stored value; commit persists it into Job.details.hardware (with a
commit-boundary JobHardwarePatch validation); reverse safety is unchanged (pristine reverses, a
post-commit hardware edit blocks reverse); source_examples never match; legacy details.system.*
coexists; and enrichment is read-only against the catalogue.

Synthetic, rollback-isolated db_session. The catalogue is seeded (idempotent). The end-to-end
ingest reuses the existing synthetic COMPLETED workbook.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.hardware.seed import seed_hardware_catalogue
from app.models.enums import (
    ImportBatchStatus,
    ImportRowClass,
    ImportRowReviewStatus,
)
from app.models.hardware import HardwareAlias, HardwareCatalogue
from app.models.import_staging import ImportBatch, ImportRow
from app.models.job import Job
from app.services import import_commit, import_ingest, import_review, import_reverse
from app.services.import_commit_preview import map_job_preview
from app.services.import_hardware import enrich_row_hardware, validate_committed_hardware
from tests.test_import import _synthetic_bytes


@pytest.fixture()
def seeded(db_session: Session) -> Session:
    seed_hardware_catalogue(db_session)  # idempotent
    return db_session


def _row_parsed(details_extra: dict | None = None) -> dict:
    details = {"_v": 2, "system": {"panel": "Longi 440", "inverter": "Goodwe 5kw"}}
    if details_extra:
        details.update(details_extra)
    return {"customer_name": "HW Person", "sale_date": "01/06/2025", "address": "1 HW St",
            "details": details}


def _seed_committable(db: Session, *, ref: str, hardware: dict) -> tuple[ImportBatch, ImportRow]:
    b = ImportBatch(source_filename="hw.xlsx", sheet_name="COMPLETED",
                    status=ImportBatchStatus.REVIEWING.value)
    db.add(b)
    db.flush()
    row = ImportRow(
        batch_id=b.id, source_row_index=2, row_class=ImportRowClass.JOB.value,
        legacy_reference=ref, raw={"address": "1 HW St"},
        parsed=_row_parsed({"hardware": hardware}),
        review_status=ImportRowReviewStatus.APPROVED.value,
    )
    db.add(row)
    db.flush()
    return b, row


# --------------------------------------------------------------------------- #
# Ingest enrichment
# --------------------------------------------------------------------------- #
def test_ingest_populates_hardware_snapshot_end_to_end(seeded, users):
    batch = import_ingest.ingest_bytes(
        seeded, file_bytes=_synthetic_bytes(), source_filename="syn.xlsx",
        created_by_id=users["admin"].id,
    )
    seeded.flush()
    rows = seeded.scalars(
        select(ImportRow).where(ImportRow.batch_id == batch.id,
                                ImportRow.row_class == ImportRowClass.JOB.value)
    ).all()
    # Row TESTIMP0001 has panel "Longi 440" (resolves) + inverter "Goodwe 5kw".
    r1 = next(r for r in rows if r.legacy_reference == "TESTIMP0001")
    hw = r1.parsed["details"]["hardware"]
    assert hw["panel"]["model"] == "LR5-54HTH-440M"   # parsed from the catalogue
    assert hw["inverters"]                             # inverter cell produced an item


def test_enrich_preserves_quantity_and_routes_capacity(seeded):
    """Through the import bridge, a 'N × MODEL ... - 40kw hrs' bundle preserves the battery
    quantity and routes the capacity evidence to a hardware note (not an inverter item)."""
    parsed = {"details": {"_v": 2}, "inverter_raw": "SAJ H2-10K-S3-A + 2 × SAJ B2-20.0-HV1 - 40kw hrs"}
    enrich_row_hardware(seeded, parsed)
    hw = parsed["details"]["hardware"]
    assert hw["inverters"][0]["model_text"] == "SAJ H2-10K-S3-A"
    assert len(hw["inverters"]) == 1                       # no "40kw hrs" raw inverter
    assert hw["batteries"][0]["model_text"] == "SAJ B2-20.0-HV1"
    assert hw["batteries"][0]["quantity"] == 2
    assert hw["site_notes"]["raw_misc"] == ["40kw hrs"]


def test_enrich_representative_cases(seeded):
    inv = {"customer_name": "x", "details": {"_v": 2}, "inverter_raw": "Alpha ESS SMILE-G3-B5-INV"}
    enrich_row_hardware(seeded, inv)
    assert inv["details"]["hardware"]["inverters"][0]["model_text"] == "Alpha ESS SMILE-G3-B5-INV"

    meter = {"details": {"_v": 2}, "inverter_raw": "meter 3p"}
    enrich_row_hardware(seeded, meter)
    assert meter["details"]["hardware"]["metering"][0]["model_text"] == "3P Meter"

    panel = {"details": {"_v": 2}, "panel_raw": "Suntech 415", "no_of_panels": "20"}
    enrich_row_hardware(seeded, panel)
    p = panel["details"]["hardware"]["panel"]
    assert p.get("model") is None and p["model_options"]   # ambiguous -> options, model null

    # No hardware cells -> no-op (no hardware key added).
    none = {"details": {"_v": 2}}
    enrich_row_hardware(seeded, none)
    assert "hardware" not in none["details"]


# --------------------------------------------------------------------------- #
# Preview/commit single source + commit-boundary validation
# --------------------------------------------------------------------------- #
def test_preview_and_commit_use_same_stored_hardware(seeded, users):
    hardware = {"inverters": [{"model_text": "Goodwe GW5000", "quantity": 1}],
                "panel": {"model": "LR5-54HTH-440M", "display_name": "440W LONGi Solar"}}
    b, row = _seed_committable(seeded, ref="HW-4B-0001", hardware=hardware)

    # Preview surfaces the stored snapshot verbatim.
    preview = map_job_preview(row.parsed, predicted_case_number="X", legacy_reference=row.legacy_reference,
                              raw=row.raw)
    assert preview["details"]["hardware"] == hardware

    # Commit persists exactly that stored snapshot into Job.details.hardware (no re-parse).
    import_commit.commit_batch(seeded, b, actor_id=users["admin"].id)
    seeded.refresh(row)
    job = seeded.get(Job, row.committed_job_id)
    assert job is not None
    assert job.details["hardware"] == hardware
    assert job.details["hardware"] == row.parsed["details"]["hardware"]  # same source


def test_review_edited_hardware_previews_and_commits_exactly(seeded, users):
    """H2 end-to-end: a review edit to parsed.details.hardware flows through preview AND commit
    verbatim. The edited model is a value the parser would NEVER produce, so its survival at commit
    proves the parser is not re-run — commit persists the stored (edited) snapshot exactly."""
    b, row = _seed_committable(
        seeded, ref="HW-H2-0001",
        hardware={"inverters": [{"model_text": "Goodwe GW5000", "quantity": 1}]},
    )
    import_review.edit_row(
        seeded, b, row,
        {"details": {"hardware": {"inverters": [
            {"model_text": "MANUAL-EDIT-XYZ", "quantity": 3,
             "confidence": "manual_correction", "parser_owned": False}]}}},
        actor_id=users["admin"].id,
    )
    seeded.flush()

    # Preview reflects the edited value (preview reads the same stored parsed.details).
    preview = map_job_preview(row.parsed, predicted_case_number="X",
                              legacy_reference=row.legacy_reference, raw=row.raw)
    assert preview["details"]["hardware"]["inverters"][0]["model_text"] == "MANUAL-EDIT-XYZ"

    # Commit persists exactly the edited snapshot (no re-parse).
    import_commit.commit_batch(seeded, b, actor_id=users["admin"].id)
    seeded.refresh(row)
    job = seeded.get(Job, row.committed_job_id)
    assert job is not None
    inv = job.details["hardware"]["inverters"][0]
    assert inv["model_text"] == "MANUAL-EDIT-XYZ" and inv["quantity"] == 3
    assert inv["confidence"] == "manual_correction"
    assert job.details["hardware"] == row.parsed["details"]["hardware"]  # commit == stored edited


def test_commit_rejects_malformed_hardware_safely(seeded, users):
    job_before = seeded.scalar(select(func.count()).select_from(Job))
    # extra='forbid' field -> JobHardwarePatch validation fails at the commit boundary.
    b, row = _seed_committable(seeded, ref="HW-4B-0002",
                              hardware={"inverters": [{"bogus_field": 1}]})
    res = import_commit.commit_batch(seeded, b, actor_id=users["admin"].id)
    row_res = next(r for r in res["results"] if r["row_id"] == row.id)
    assert row_res["status"] == "failed"
    seeded.refresh(row)
    assert row.committed_job_id is None
    assert seeded.scalar(select(func.count()).select_from(Job)) == job_before  # no orphan job


def test_validate_committed_hardware_passes_clean_and_rejects_dirty(seeded):
    validate_committed_hardware({"hardware": {"inverters": [{"model_text": "X", "quantity": 1}]}})
    validate_committed_hardware({})            # absent -> no-op
    validate_committed_hardware({"hardware": None})
    with pytest.raises(ValueError):
        validate_committed_hardware({"hardware": {"inverters": [{"nope": 1}]}})


# --------------------------------------------------------------------------- #
# Reverse safety (existing pristine guard; unchanged for hardware)
# --------------------------------------------------------------------------- #
def test_reverse_pristine_hardware_job_works(seeded, users):
    hardware = {"inverters": [{"model_text": "Goodwe GW5000", "quantity": 1}]}
    b, row = _seed_committable(seeded, ref="HW-4B-0003", hardware=hardware)
    import_commit.commit_batch(seeded, b, actor_id=users["admin"].id)
    seeded.refresh(row)

    assert import_reverse.reversibility(seeded, row)["reversible"] is True
    res = import_reverse.reverse_row(seeded, row, actor_id=users["admin"].id)
    assert res["status"] == "reversed"
    seeded.refresh(row)
    assert row.review_status == ImportRowReviewStatus.REVERSED.value


def test_reverse_blocked_after_post_commit_hardware_edit(seeded, client_for, users):
    hardware = {"inverters": [{"model_text": "Goodwe GW5000", "quantity": 1}]}
    b, row = _seed_committable(seeded, ref="HW-4B-0004", hardware=hardware)
    import_commit.commit_batch(seeded, b, actor_id=users["admin"].id)
    seeded.refresh(row)
    job_id = row.committed_job_id

    # A real post-commit hardware edit through the live Job-details PATCH bumps job.updated_at.
    admin = client_for(users["admin"])
    r = admin.patch(f"/api/v1/jobs/{job_id}",
                    json={"details": {"hardware": {"warnings": ["edited by staff"]}}})
    assert r.status_code == 200, r.text

    # The existing pristine guard now blocks reverse — hardware edits are preserved (irreversible).
    # A post-commit edit trips a pristine guard (the job was modified AND logged a JOB_UPDATED
    # activity); either reason proves the edit makes the row irreversible.
    check = import_reverse.reversibility(seeded, row)
    assert check["reversible"] is False
    assert check["reason"] in {"job_modified", "job_has_activity"}


# --------------------------------------------------------------------------- #
# Hard rules: source_examples, legacy coexistence, read-only
# --------------------------------------------------------------------------- #
def test_source_examples_not_matched_through_import(seeded):
    # Ambiguous hardware text (brand + capacity, no specific model) must be preserved RAW through the
    # import bridge — never guessed to a canonical model. (Previously used an Alpha-M5 example; P8c
    # made "ALPHA ESS M5 5KW INVERTER" an explicit alias, so that string now resolves by design.)
    example = "Solis 5kw and 10kw battery"
    parsed = {"details": {"_v": 2}, "inverter_raw": example}
    enrich_row_hardware(seeded, parsed)
    hw = parsed["details"]["hardware"]
    items = hw.get("inverters", []) + hw.get("batteries", []) + hw.get("metering", [])
    assert items, "expected the ambiguous text preserved as raw fragments"
    assert all(it.get("canonical_hardware_id_at_parse_time") is None for it in items)
    assert all(it["confidence"] == "unconfirmed_raw_text" for it in items)


def test_legacy_system_fields_coexist(seeded):
    parsed = _row_parsed()
    parsed["inverter_raw"] = "Alpha ESS SMILE-G3-B5-INV"
    parsed["panel_raw"] = "Longi 440"
    enrich_row_hardware(seeded, parsed)
    # Legacy text untouched...
    assert parsed["details"]["system"]["panel"] == "Longi 440"
    assert parsed["details"]["system"]["inverter"] == "Goodwe 5kw"
    # ...alongside the new structured snapshot.
    assert parsed["details"]["hardware"]["panel"]["model"] == "LR5-54HTH-440M"


def test_enrichment_is_read_only_against_catalogue(seeded):
    cat_before = seeded.scalar(select(func.count()).select_from(HardwareCatalogue))
    alias_before = seeded.scalar(select(func.count()).select_from(HardwareAlias))
    parsed = {"details": {"_v": 2}, "inverter_raw": "Alpha ESS SMILE-G3-B5-INV", "panel_raw": "Longi 440"}
    enrich_row_hardware(seeded, parsed)
    assert seeded.scalar(select(func.count()).select_from(HardwareCatalogue)) == cat_before
    assert seeded.scalar(select(func.count()).select_from(HardwareAlias)) == alias_before
