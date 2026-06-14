"""Structured-import field registry — the single source of truth (Phase 1).

This pure, DB-free module declares every structured import field once: its label,
section, owning entity, storage target, input type, visibility, category, source
spreadsheet column(s), and (future) validation/coercion metadata. Later phases —
the parser, commit mapping, commit-preview, review drawer, and Job/Customer
detail UI — all read from here so they cannot drift.

Phase 1 only DECLARES the registry; nothing reads it yet to change behaviour.
Storage paths use a dotted convention:
  * ``customer.<field>``           -> first-class Customer column
  * ``job.<field>``                -> first-class Job column
  * ``job.details.<section>.<key>``-> structured Job.details JSONB (Phase 1 column)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------- #
# Enumerations (plain string constants — JSON-friendly, no DB coupling)
# --------------------------------------------------------------------------- #
ENTITY_CUSTOMER = "customer"
ENTITY_JOB = "job"

CATEGORY_CORE = "core"          # a real field; core ones in the owner list show even when blank
CATEGORY_LEGACY = "legacy"      # import-only / obsolete-regional; hidden when blank
CATEGORY_DERIVED = "derived"    # produced by the parser (notes/flags/provenance), not a 1:1 column

# Input types for the structured editor (UI binds to these later).
INPUT_TEXT = "text"
INPUT_TEXTAREA = "textarea"
INPUT_NUMBER = "number"
INPUT_CURRENCY = "currency"
INPUT_DATE = "date"
INPUT_SELECT = "select"
INPUT_CONTACT_LIST = "contact_list"   # repeatable number/label rows (phones/emails)
INPUT_FLAG = "flag"                    # boolean-ish badge (e.g. remove-old-system)
INPUT_READONLY = "readonly"            # provenance, never edited

# Whether the value exists in batch 388's captured raw cells today.
CAPTURED_RAW = "raw"            # already in raw -> reparsable without re-ingest
CAPTURED_REINGEST = "reingest"  # never captured -> needs a fresh workbook ingest
CAPTURED_DERIVED = "derived"    # computed, not a source cell

# Ordered sections (key, display label). Drives section ordering in the UI.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("customer_contact", "Customer / contact"),
    ("sales", "Sales"),
    ("system", "System"),
    ("electrical_network", "Electrical / network"),
    ("install", "Install"),
    ("payment", "Payment"),
    ("compliance_admin", "Compliance / admin"),
    ("post_install", "Post-install"),
    ("legacy", "Legacy / import-only"),
    ("notes_provenance", "Notes / provenance"),
)
SECTION_KEYS: frozenset[str] = frozenset(k for k, _ in SECTIONS)


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    section: str
    entity: str
    storage: str                       # dotted storage path (see module docstring)
    input_type: str
    visible_when_blank: bool
    category: str
    editable: bool
    source_columns: tuple[str, ...]
    captured: str = CAPTURED_RAW
    validation: dict[str, Any] = field(default_factory=dict)


def _f(**kw: Any) -> FieldSpec:
    return FieldSpec(**kw)


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #
FIELDS: tuple[FieldSpec, ...] = (
    # --- Customer / contact ---
    _f(key="customer_name", label="Customer Name", section="customer_contact",
       entity=ENTITY_CUSTOMER, storage="customer.full_name", input_type=INPUT_TEXT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Customer Name",), captured=CAPTURED_RAW,
       validation={"divert_misfiled": True}),
    _f(key="address", label="Address", section="customer_contact",
       entity=ENTITY_CUSTOMER, storage="customer.address", input_type=INPUT_TEXT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("ADDRESS",), captured=CAPTURED_RAW,
       validation={"parse": "address_parts"}),
    _f(key="phone", label="Phone", section="customer_contact",
       entity=ENTITY_CUSTOMER, storage="customer.phone", input_type=INPUT_CONTACT_LIST,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Phone",), captured=CAPTURED_RAW,
       validation={"reliable_label_only": True, "divert_ambiguous": True}),
    _f(key="email", label="Email", section="customer_contact",
       entity=ENTITY_CUSTOMER, storage="customer.email", input_type=INPUT_CONTACT_LIST,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Email",), captured=CAPTURED_RAW),

    # --- Sales ---
    _f(key="salesperson", label="Sales Consultant", section="sales",
       entity=ENTITY_JOB, storage="job.details.sales.salesperson_text", input_type=INPUT_TEXT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Sales Consultant",), captured=CAPTURED_RAW,
       validation={"fk_later": "staff_directory"}),
    _f(key="sale_date", label="Sale Date", section="sales",
       entity=ENTITY_JOB, storage="job.sale_date", input_type=INPUT_DATE,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Sales Consultant",), captured=CAPTURED_RAW,
       validation={"coerce": "date"}),

    # --- System ---
    _f(key="panel_count", label="No of Panels", section="system",
       entity=ENTITY_JOB, storage="job.details.system.panel_count", input_type=INPUT_NUMBER,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("No of Panels",), captured=CAPTURED_RAW,
       validation={"coerce": "int", "divert_nonnumeric": True}),
    _f(key="panel", label="Panel Brand/Wattage", section="system",
       entity=ENTITY_JOB, storage="job.details.system.panel", input_type=INPUT_TEXT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Panel Brand/ Wattage",), captured=CAPTURED_RAW,
       validation={"catalog_later": "hardware"}),
    _f(key="inverter", label="Inverter Brand/Model", section="system",
       entity=ENTITY_JOB, storage="job.details.system.inverter", input_type=INPUT_TEXT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Inverter Brand/Model",), captured=CAPTURED_RAW,
       validation={"catalog_later": "hardware"}),
    _f(key="storey", label="Storey", section="system",
       entity=ENTITY_JOB, storage="job.details.system.storey", input_type=INPUT_SELECT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Storey",), captured=CAPTURED_RAW,
       validation={"divert_unrecognized": True}),
    _f(key="phase", label="Phase", section="system",
       entity=ENTITY_JOB, storage="job.details.system.phase", input_type=INPUT_SELECT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Phase",), captured=CAPTURED_RAW,
       validation={"select_options": ["single", "two", "three"], "divert_unrecognized": True}),
    _f(key="roof_type", label="Roof Type", section="system",
       entity=ENTITY_JOB, storage="job.details.system.roof_type", input_type=INPUT_SELECT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Roof Type",), captured=CAPTURED_RAW,
       validation={"divert_unrecognized": True}),

    # --- Electrical / network ---
    _f(key="nmi", label="NMI", section="electrical_network",
       entity=ENTITY_JOB, storage="job.details.electrical.nmi", input_type=INPUT_TEXT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("NMI",), captured=CAPTURED_RAW),
    _f(key="meter_no", label="Meter No", section="electrical_network",
       entity=ENTITY_JOB, storage="job.details.electrical.meter_no", input_type=INPUT_TEXT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Meter No",), captured=CAPTURED_RAW),
    _f(key="distributor", label="Distributor", section="electrical_network",
       entity=ENTITY_JOB, storage="job.details.electrical.distributor", input_type=INPUT_TEXT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Distributor", "NMI"), captured=CAPTURED_RAW),
    _f(key="retailer", label="Retailer", section="electrical_network",
       entity=ENTITY_JOB, storage="job.details.electrical.retailer", input_type=INPUT_TEXT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Retailer",), captured=CAPTURED_RAW),

    # --- Install ---
    _f(key="install_date", label="Date", section="install",
       entity=ENTITY_JOB, storage="job.install_date", input_type=INPUT_DATE,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Date",), captured=CAPTURED_RAW, validation={"coerce": "date"}),
    _f(key="install_day", label="Day", section="install",
       entity=ENTITY_JOB, storage="job.details.install.day", input_type=INPUT_TEXT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Day",), captured=CAPTURED_RAW),
    _f(key="install_time", label="Time", section="install",
       entity=ENTITY_JOB, storage="job.details.install.time", input_type=INPUT_TEXT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Time",), captured=CAPTURED_RAW),
    _f(key="installer", label="Installer", section="install",
       entity=ENTITY_JOB, storage="job.details.install.installer", input_type=INPUT_TEXT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Installer",), captured=CAPTURED_RAW,
       validation={"fk_later": "staff_directory"}),

    # --- Payment ---
    _f(key="total", label="Total", section="payment",
       entity=ENTITY_JOB, storage="job.details.payment.total", input_type=INPUT_CURRENCY,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Total",), captured=CAPTURED_RAW,
       validation={"coerce": "currency", "divert_nonnumeric": True}),
    _f(key="deposit", label="Deposit", section="payment",
       entity=ENTITY_JOB, storage="job.details.payment.deposit", input_type=INPUT_CURRENCY,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Deposit",), captured=CAPTURED_RAW,
       validation={"coerce": "currency", "divert_nonnumeric": True}),
    _f(key="balance", label="Balance", section="payment",
       entity=ENTITY_JOB, storage="job.details.payment.balance", input_type=INPUT_CURRENCY,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Balance",), captured=CAPTURED_RAW,
       validation={"coerce": "currency", "divert_nonnumeric": True}),
    _f(key="pay_result", label="Result of payment", section="payment",
       entity=ENTITY_JOB, storage="job.details.payment.result", input_type=INPUT_TEXT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Result of payment",), captured=CAPTURED_RAW),
    _f(key="pay_notes", label="Notes on payment", section="payment",
       entity=ENTITY_JOB, storage="job.details.payment.notes", input_type=INPUT_TEXTAREA,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Notes on payment",), captured=CAPTURED_RAW),
    _f(key="stc_amount", label="STC Amount", section="payment",
       entity=ENTITY_JOB, storage="job.details.payment.stc_amount", input_type=INPUT_CURRENCY,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("STC Amount",), captured=CAPTURED_REINGEST,
       validation={"coerce": "currency", "divert_nonnumeric": True}),

    # --- Compliance / admin ---
    _f(key="msb_status", label="MSB/SB Pics in File?", section="compliance_admin",
       entity=ENTITY_JOB, storage="job.details.compliance.msb_status", input_type=INPUT_SELECT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("MSB/SB PICS IN FILE?",), captured=CAPTURED_RAW,
       validation={"select_options": ["yes", "no", "maybe"], "divert_unrecognized": True}),
    _f(key="welcome_call", label="Welcome Call", section="compliance_admin",
       entity=ENTITY_JOB, storage="job.details.compliance.welcome_call", input_type=INPUT_TEXT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Welcome Call",), captured=CAPTURED_RAW),
    _f(key="ces_ecoc_email", label="CES/ECOC/CCEW to Retailer Email", section="compliance_admin",
       entity=ENTITY_JOB, storage="job.details.compliance.ces_ecoc_email", input_type=INPUT_TEXT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("CES/ECOC/CCEW to Retailer Email - All other distributors",),
       captured=CAPTURED_REINGEST),
    _f(key="accreditation", label="Accreditation Code", section="compliance_admin",
       entity=ENTITY_JOB, storage="job.details.compliance.accreditation", input_type=INPUT_TEXT,
       visible_when_blank=False, category=CATEGORY_CORE, editable=True,
       source_columns=("Accreditation Code",), captured=CAPTURED_RAW),

    # --- Post-install ---
    _f(key="post_install_review", label="Post-Install Call/Review date", section="post_install",
       entity=ENTITY_JOB, storage="job.details.post_install.review_date", input_type=INPUT_DATE,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Date of Post Installation Call/Review Request",),
       captured=CAPTURED_REINGEST, validation={"coerce": "date"}),
    _f(key="post_install_status", label="Post-Install Call/Review status", section="post_install",
       entity=ENTITY_JOB, storage="job.details.post_install.review_status", input_type=INPUT_TEXT,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Date of Post Installation Call/Review Request",),
       captured=CAPTURED_REINGEST),

    # --- Legacy / import-only (hidden when blank) ---
    _f(key="solar_vic", label="Solar Vic Payment", section="legacy",
       entity=ENTITY_JOB, storage="job.details.legacy.solar_vic", input_type=INPUT_TEXT,
       visible_when_blank=False, category=CATEGORY_LEGACY, editable=True,
       source_columns=("Solar Vic Payment",), captured=CAPTURED_REINGEST),
    _f(key="ces_submission", label="CES Submission to Distributor (AusNet/Powercor/United/Jemena)",
       section="legacy", entity=ENTITY_JOB, storage="job.details.legacy.ces_submission",
       input_type=INPUT_TEXT, visible_when_blank=False, category=CATEGORY_LEGACY, editable=True,
       source_columns=("CES Submission to Distributor Ausnet/Powercor/United/Jemena",),
       captured=CAPTURED_REINGEST),

    # --- Notes / provenance ---
    _f(key="notes", label="Notes", section="notes_provenance",
       entity=ENTITY_JOB, storage="job.notes", input_type=INPUT_TEXTAREA,
       visible_when_blank=True, category=CATEGORY_CORE, editable=True,
       source_columns=("Notes",), captured=CAPTURED_RAW),
    _f(key="misfiled_notes", label="Imported notes (misfiled)", section="notes_provenance",
       entity=ENTITY_JOB, storage="job.details.notes.misfiled", input_type=INPUT_TEXTAREA,
       visible_when_blank=False, category=CATEGORY_DERIVED, editable=True,
       source_columns=("(any structured column)",), captured=CAPTURED_DERIVED),
    _f(key="removes_old_system", label="Remove old system", section="notes_provenance",
       entity=ENTITY_JOB, storage="job.details.flags.removes_old_system", input_type=INPUT_FLAG,
       visible_when_blank=False, category=CATEGORY_DERIVED, editable=False,
       source_columns=("Customer Name", "Notes"), captured=CAPTURED_DERIVED),
    _f(key="provenance", label="Import provenance", section="notes_provenance",
       entity=ENTITY_JOB, storage="job.details.provenance", input_type=INPUT_READONLY,
       visible_when_blank=True, category=CATEGORY_DERIVED, editable=False,
       source_columns=("(import)",), captured=CAPTURED_DERIVED),
)


# --------------------------------------------------------------------------- #
# Lookups + integrity (validated at import time)
# --------------------------------------------------------------------------- #
FIELDS_BY_KEY: dict[str, FieldSpec] = {f.key: f for f in FIELDS}


def field_spec(key: str) -> FieldSpec | None:
    return FIELDS_BY_KEY.get(key)


def fields_for_section(section: str) -> tuple[FieldSpec, ...]:
    return tuple(f for f in FIELDS if f.section == section)


def core_fields() -> tuple[FieldSpec, ...]:
    return tuple(f for f in FIELDS if f.category == CATEGORY_CORE)


def legacy_fields() -> tuple[FieldSpec, ...]:
    return tuple(f for f in FIELDS if f.category == CATEGORY_LEGACY)


# Details paths (``<section>.<key>``) that are parser-derived / read-only and must
# never be writable via a reviewer details patch, even if the registry marks the
# field editable. Structured editing of these is out of scope for Phase 3a.
_READONLY_DETAILS_PREFIXES: tuple[str, ...] = ("flags.", "provenance", "notes.misfiled")

_DETAILS_PREFIX = "job.details."


def allowed_details_paths() -> frozenset[str]:
    """Registry-derived whitelist of writable ``details`` leaf paths.

    A path ``"<section>.<key>"`` is writable iff its field is ``editable`` and
    stored under ``job.details.*`` and not a read-only/derived path (flags,
    provenance, misfiled). This is the ONLY set a reviewer details patch may set.
    """
    out: set[str] = set()
    for f in FIELDS:
        if not f.editable or not f.storage.startswith(_DETAILS_PREFIX):
            continue
        path = f.storage[len(_DETAILS_PREFIX):]
        if any(path == p or path.startswith(p) for p in _READONLY_DETAILS_PREFIXES):
            continue
        out.add(path)
    return frozenset(out)


def as_dicts() -> list[dict[str, Any]]:
    """Serialise the registry for the read-only field-registry endpoint (no PII)."""
    return [
        {
            "key": f.key,
            "label": f.label,
            "section": f.section,
            "entity": f.entity,
            "storage": f.storage,
            "input_type": f.input_type,
            "visible_when_blank": f.visible_when_blank,
            "category": f.category,
            "editable": f.editable,
            "source_columns": list(f.source_columns),
            "captured": f.captured,
            "validation": dict(f.validation),
        }
        for f in FIELDS
    ]


def _assert_integrity() -> None:
    keys = [f.key for f in FIELDS]
    dupes = {k for k in keys if keys.count(k) > 1}
    if dupes:
        raise ValueError(f"import_field_registry: duplicate field keys: {sorted(dupes)}")
    bad = {f.key: f.section for f in FIELDS if f.section not in SECTION_KEYS}
    if bad:
        raise ValueError(f"import_field_registry: unknown section(s): {bad}")
    bad_ent = {f.key: f.entity for f in FIELDS if f.entity not in (ENTITY_CUSTOMER, ENTITY_JOB)}
    if bad_ent:
        raise ValueError(f"import_field_registry: unknown entity(ies): {bad_ent}")


_assert_integrity()
