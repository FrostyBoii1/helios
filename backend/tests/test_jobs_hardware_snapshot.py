"""Hardware Parser lane, Stage 3A — Job.details.hardware editable SNAPSHOT.

Verifies the structured-details patch supports a Job-owned hardware snapshot:
  * a hardware patch sets/reads inverters/batteries/metering/panel/site_notes/warnings;
  * each provided sub-section replaces that whole sub-section; absent ones + the rest of
    details are preserved (partial-patch semantics);
  * the snapshot is shape-validated (extra='forbid' / wrong type) -> 422, job unchanged;
  * a hardware edit never touches the hardware_catalogue, and catalogue rename/soft-delete/
    restore never mutates an existing Job snapshot (the hard snapshot rule);
  * existing non-hardware paths still patch (alongside hardware), the NULL-details guard still
    holds, and a job whose details lack `hardware` reads back safely.

Synthetic data only (rollback-isolated db_session). No parser/import/catalogue read populates
the snapshot here — staff/tests edit it directly via the Job detail PATCH.
"""
from __future__ import annotations

import copy

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.enums import JobStatus
from app.models.hardware import HardwareCatalogue
from app.models.job import Job
from app.services import hardware as hardware_service


def _details() -> dict:
    return {
        "_v": 2,
        "system": {"panel_count": 16, "panel": "JinkoSolar 440W", "phase": "single"},
        "payment": {"total": "8500"},
        "provenance": "synthetic 3a",
    }


def _make_job(db: Session, customer: Customer, *, case_number: str, details: dict | None) -> Job:
    job = Job(
        case_number=case_number,
        customer_id=customer.id,
        status=JobStatus.INSTALLED,
        title="TEST 3a job",
        details=details,
        system_details="STALE system",
        install_details="STALE install",
        approval_details="Approval: approved",
        notes="legacy notes blob",
    )
    db.add(job)
    db.flush()
    return job


def _catalogue_row(db: Session, *, spec_id: str, model: str) -> HardwareCatalogue:
    hw = HardwareCatalogue(
        spec_id=spec_id, category="inverter", canonical_model=model,
        display_name=model, brand="TestBrand", spec_source="test",
    )
    db.add(hw)
    db.flush()
    return hw


# --------------------------------------------------------------------------- #
# Set + read + partial-patch semantics
# --------------------------------------------------------------------------- #
def test_patch_sets_and_reads_hardware_snapshot(client_for, users, customer, db_session):
    job = _make_job(db_session, customer, case_number="HW-3A-0001", details=_details())
    admin = client_for(users["admin"])

    r = admin.patch(
        f"/api/v1/jobs/{job.id}",
        json={"details": {"hardware": {
            "inverters": [{"model_text": "Sungrow SG10RT", "quantity": 1, "confidence": "exact",
                           "parser_owned": True, "source_type": "manual"}],
            "panel": {"display_name": "440W LONGi", "model": None, "wattage_w": 440, "quantity": 16},
            "site_notes": {"export_limit": ["5kW"]},
            "warnings": ["check phase"],
        }}},
    )
    assert r.status_code == 200, r.text

    db_session.refresh(job)
    hw = job.details["hardware"]
    assert hw["inverters"][0]["model_text"] == "Sungrow SG10RT"
    assert hw["inverters"][0]["quantity"] == 1 and hw["inverters"][0]["parser_owned"] is True
    assert hw["panel"]["display_name"] == "440W LONGi" and hw["panel"]["wattage_w"] == 440
    assert hw["site_notes"]["export_limit"] == ["5kW"]
    assert hw["warnings"] == ["check phase"]
    # None fields are dropped from the stored snapshot (exclude_none) — tidy.
    assert "model" not in hw["panel"]
    # Non-hardware details preserved; legacy blob re-rendered from system (hardware is not a blob).
    assert job.details["system"]["panel_count"] == 16
    assert "Panels: 16" in job.system_details

    # GET reads the snapshot back through JobRead.details.
    body = admin.get(f"/api/v1/jobs/{job.id}").json()
    assert body["details"]["hardware"]["inverters"][0]["model_text"] == "Sungrow SG10RT"


def test_partial_hardware_patch_preserves_other_subsections(client_for, users, customer, db_session):
    job = _make_job(db_session, customer, case_number="HW-3A-0002", details=_details())
    admin = client_for(users["admin"])

    assert admin.patch(f"/api/v1/jobs/{job.id}", json={"details": {"hardware": {
        "inverters": [{"model_text": "Fronius Primo"}],
        "batteries": [{"model_text": "Tesla PW2", "quantity": 1}],
    }}}).status_code == 200

    # Patch ONLY inverters — batteries + system must be preserved.
    assert admin.patch(f"/api/v1/jobs/{job.id}", json={"details": {"hardware": {
        "inverters": [{"model_text": "Sungrow SG8RT"}],
    }}}).status_code == 200

    db_session.refresh(job)
    hw = job.details["hardware"]
    assert hw["inverters"][0]["model_text"] == "Sungrow SG8RT"   # replaced
    assert hw["batteries"][0]["model_text"] == "Tesla PW2"       # preserved
    assert job.details["system"]["panel"] == "JinkoSolar 440W"   # non-hardware preserved


def test_existing_paths_still_patch_alongside_hardware(client_for, users, customer, db_session):
    job = _make_job(db_session, customer, case_number="HW-3A-0003", details=_details())
    admin = client_for(users["admin"])

    r = admin.patch(f"/api/v1/jobs/{job.id}", json={"details": {
        "system": {"panel_count": 20},
        "hardware": {"inverters": [{"model_text": "GoodWe GW5000"}]},
    }})
    assert r.status_code == 200, r.text

    db_session.refresh(job)
    assert job.details["system"]["panel_count"] == 20           # flat path applied
    assert job.details["hardware"]["inverters"][0]["model_text"] == "GoodWe GW5000"
    assert "Panels: 20" in job.system_details                   # blob re-rendered


# --------------------------------------------------------------------------- #
# Shape validation (the safety boundary)
# --------------------------------------------------------------------------- #
def test_invalid_hardware_shape_rejected_422(client_for, users, customer, db_session):
    job = _make_job(db_session, customer, case_number="HW-3A-0004", details=_details())
    admin = client_for(users["admin"])
    before = copy.deepcopy(job.details)

    for patch in (
        {"hardware": {"inverters": [{"evil": "x"}]}},        # unknown item field (extra='forbid')
        {"hardware": {"bogus_section": []}},                 # unknown sub-section
        {"hardware": {"panel": {"wattage_w": "not-a-number"}}},  # wrong type
        {"hardware": "x"},                                   # hardware not an object
        {"hardware": None},                                  # explicit null hardware
    ):
        r = admin.patch(f"/api/v1/jobs/{job.id}", json={"details": patch})
        assert r.status_code == 422, (patch, r.text)

    db_session.refresh(job)
    assert job.details == before
    assert "hardware" not in job.details
    assert job.system_details == "STALE system"  # never re-rendered on rejection


# --------------------------------------------------------------------------- #
# The hard snapshot rule: catalogue <-> Job snapshot are independent
# --------------------------------------------------------------------------- #
def test_hardware_patch_does_not_touch_catalogue(client_for, users, customer, db_session):
    cat = _catalogue_row(db_session, spec_id="hw3a_keep_inv", model="Keep Me")
    cat_id, before_model = cat.id, cat.canonical_model
    count_before = db_session.scalar(select(func.count()).select_from(HardwareCatalogue))
    job = _make_job(db_session, customer, case_number="HW-3A-0005", details=_details())
    admin = client_for(users["admin"])

    assert admin.patch(f"/api/v1/jobs/{job.id}", json={"details": {"hardware": {
        "inverters": [{"model_text": "Sungrow", "canonical_hardware_id_at_parse_time": cat_id}],
    }}}).status_code == 200

    db_session.refresh(cat)
    assert cat.canonical_model == before_model  # catalogue row untouched by a Job snapshot edit
    assert db_session.scalar(select(func.count()).select_from(HardwareCatalogue)) == count_before


def test_catalogue_edits_do_not_mutate_job_snapshot(client_for, users, customer, db_session):
    cat = _catalogue_row(db_session, spec_id="hw3a_ref_inv", model="Original Model")
    job = _make_job(db_session, customer, case_number="HW-3A-0006", details={
        **_details(),
        "hardware": {"inverters": [
            {"model_text": "Original Model", "canonical_hardware_id_at_parse_time": cat.id},
        ]},
    })
    before = copy.deepcopy(job.details["hardware"])

    # Rename + soft-delete + restore the catalogue entry (rules 2/3/4): the Job snapshot must
    # NOT change — Jobs hold a stored snapshot, never a live catalogue reference.
    hardware_service.update_hardware(db_session, hardware=cat, data={"canonical_model": "RENAMED"})
    hardware_service.soft_delete_hardware(db_session, cat)
    hardware_service.restore_hardware(db_session, cat)
    db_session.flush()

    db_session.refresh(job)
    assert job.details["hardware"] == before
    assert job.details["hardware"]["inverters"][0]["model_text"] == "Original Model"


# --------------------------------------------------------------------------- #
# Safe handling of jobs without hardware / without details
# --------------------------------------------------------------------------- #
def test_job_without_hardware_details_serializes_safely(client_for, users, customer, db_session):
    job = _make_job(db_session, customer, case_number="HW-3A-0007", details=_details())
    admin = client_for(users["admin"])

    body = admin.get(f"/api/v1/jobs/{job.id}").json()
    assert body["details"] is not None and "hardware" not in body["details"]  # reads fine, no hardware


def test_hardware_patch_on_null_details_job_rejected_422(client_for, users, customer, db_session):
    job = _make_job(db_session, customer, case_number="HW-3A-0008", details=None)
    admin = client_for(users["admin"])

    r = admin.patch(f"/api/v1/jobs/{job.id}", json={"details": {"hardware": {
        "inverters": [{"model_text": "X"}]}}})
    assert r.status_code == 422, r.text  # existing NULL-details guard still applies
    db_session.refresh(job)
    assert job.details is None
