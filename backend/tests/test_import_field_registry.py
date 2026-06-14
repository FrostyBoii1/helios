"""Phase 1 tests: field registry integrity + Job.details JSONB round-trip.

Pure-data assertions on the registry plus a DB check that the new nullable
Job.details column stores/reads JSON. No import/live behaviour is exercised.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import JobStatus
from app.models.job import Job
from app.services import import_field_registry as reg
from app.services import jobs as jobs_service
from app.services.customers import create_customer

# The owner's "core fields that should show even when blank" (registry keys).
EXPECTED_CORE_VISIBLE = {
    "salesperson", "customer_name", "address", "phone", "notes", "msb_status",
    "email", "distributor", "retailer", "nmi", "meter_no", "panel_count",
    "panel", "inverter", "storey", "phase", "roof_type", "install_date",
    "install_day", "install_time", "installer", "welcome_call", "total",
    "deposit", "balance", "pay_result", "pay_notes", "stc_amount",
    "post_install_review", "post_install_status", "ces_ecoc_email",
}


def test_phase_select_options_include_two():
    f = reg.field_spec("phase")
    assert f is not None
    assert f.validation.get("select_options") == ["single", "two", "three"]


def test_post_install_status_field_is_editable_text():
    f = reg.field_spec("post_install_status")
    assert f is not None
    assert f.section == "post_install"
    assert f.storage == "job.details.post_install.review_status"
    assert f.input_type == reg.INPUT_TEXT and f.editable is True
    # editable job.details.* leaf -> writable via the path-restricted patch
    assert "post_install.review_status" in reg.allowed_details_paths()


def test_post_install_status_columns_editable_hidden_when_blank():
    paths = reg.allowed_details_paths()
    for key, path in (
        ("warranty_rego_completed", "post_install.warranty_rego_completed"),
        ("post_install_email_sent", "post_install.post_install_email_sent"),
    ):
        f = reg.field_spec(key)
        assert f is not None, key
        assert f.section == "post_install"
        assert f.input_type == reg.INPUT_TEXT and f.editable is True
        assert f.visible_when_blank is False  # hidden when blank; addable via the picker
        assert path in paths  # writable via the path-restricted patch


# --------------------------------------------------------------------------- #
# Registry integrity
# --------------------------------------------------------------------------- #
def test_field_keys_are_unique():
    keys = [f.key for f in reg.FIELDS]
    assert len(keys) == len(set(keys))


def test_required_core_fields_present_and_visible():
    for key in EXPECTED_CORE_VISIBLE:
        f = reg.field_spec(key)
        assert f is not None, f"missing core field: {key}"
        assert f.category == reg.CATEGORY_CORE, key
        assert f.visible_when_blank is True, key


def test_legacy_fields_marked_hidden_when_blank():
    legacy = {f.key for f in reg.legacy_fields()}
    assert {"solar_vic", "ces_submission"} <= legacy
    for f in reg.legacy_fields():
        assert f.category == reg.CATEGORY_LEGACY
        assert f.visible_when_blank is False


def test_sections_entities_and_storage_paths_well_formed():
    for f in reg.FIELDS:
        assert f.section in reg.SECTION_KEYS, f.key
        assert f.entity in (reg.ENTITY_CUSTOMER, reg.ENTITY_JOB), f.key
        # storage prefix must agree with the owning entity
        if f.entity == reg.ENTITY_CUSTOMER:
            assert f.storage.startswith("customer."), f.key
        else:
            assert f.storage.startswith("job."), f.key
        # JSONB-backed fields live under job.details.<section>...
        if f.storage.startswith("job.details."):
            assert f.entity == reg.ENTITY_JOB, f.key


def test_input_types_are_known():
    known = {
        reg.INPUT_TEXT, reg.INPUT_TEXTAREA, reg.INPUT_NUMBER, reg.INPUT_CURRENCY,
        reg.INPUT_DATE, reg.INPUT_SELECT, reg.INPUT_CONTACT_LIST, reg.INPUT_FLAG,
        reg.INPUT_READONLY,
    }
    for f in reg.FIELDS:
        assert f.input_type in known, f"{f.key}: {f.input_type}"


def test_every_section_has_at_least_one_field():
    used = {f.section for f in reg.FIELDS}
    for key, _label in reg.SECTIONS:
        assert key in used, f"section with no fields: {key}"


# --------------------------------------------------------------------------- #
# Job.details JSONB round-trip (the migration's column)
# --------------------------------------------------------------------------- #
def test_job_details_jsonb_round_trip(db_session: Session):
    cust = create_customer(db_session, data={"full_name": "Reg Test Cust"})
    db_session.flush()
    job = jobs_service.create_job(
        db_session, customer_id=cust.id, data={}, year=2025, status=JobStatus.INSTALLED
    )
    db_session.flush()

    # Defaults to NULL when never set.
    assert job.details is None

    payload = {"_v": 1, "system": {"panel_count": 16, "phase": "single"},
               "payment": {"total": "12345.67"}, "flags": {"removes_old_system": True}}
    job.details = payload
    db_session.flush()
    db_session.expire(job)

    reloaded = db_session.scalar(select(Job).where(Job.id == job.id))
    assert reloaded.details == payload
    assert reloaded.details["system"]["panel_count"] == 16
    assert reloaded.details["flags"]["removes_old_system"] is True
