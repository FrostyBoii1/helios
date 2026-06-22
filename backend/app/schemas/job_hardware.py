"""Job hardware SNAPSHOT shape (Hardware Parser lane, Stage 3 — Job.details.hardware).

A Job stores its hardware as an editable, durable SNAPSHOT under ``Job.details.hardware``
(JSONB) — NOT a live reference to the ``hardware_catalogue``. Settings > Hardware catalogue /
alias edits, soft-deletes and restores must NEVER mutate an existing Job snapshot; a Job's
hardware display depends only on this stored text. ``canonical_hardware_id_at_parse_time`` is
provenance/debug only and is never display truth. No parser runtime or catalogue read populates
this in Stage 3 — staff edit it directly (Stage 3B UI).

These models are the *safety boundary* for the structured-details patch: the ``hardware`` key of
a ``Job.details`` patch is validated against ``JobHardwarePatch`` (every model is ``extra='forbid'``,
so unknown fields are rejected — the schema analog of the flat ``<section>.<key>`` path whitelist).
Each sub-section provided in a patch replaces that whole sub-section; absent sub-sections are
preserved (see ``services.details_patch.merge_details_patch``).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError


class _Strict(BaseModel):
    # Reject unknown fields anywhere in the snapshot — the schema-level whitelist.
    model_config = ConfigDict(extra="forbid")


class JobHardwareItem(_Strict):
    """One inverter / battery / metering line item (editable snapshot text + provenance)."""

    model_text: str | None = None
    quantity: int | None = None
    confidence: str | None = None
    parser_owned: bool | None = None
    source_fragment: str | None = None
    # How this row entered the snapshot: manual | import | parser | catalogue (free text — a
    # snapshot, not a validated vocabulary).
    source_type: str | None = None
    source_field: str | None = None
    # Provenance/debug only — the catalogue spec_id/id matched at parse time, NEVER display truth.
    canonical_hardware_id_at_parse_time: int | None = None
    parser_rule_version: str | None = None


class JobHardwarePanel(_Strict):
    """The panel sub-object. ``display_name`` is the editable job-facing name; ``model`` is the
    actual model (or null for an ambiguous panel that carries ``model_options`` instead)."""

    quantity: int | None = None
    brand: str | None = None
    display_name: str | None = None
    model: str | None = None
    model_options: list[str] | None = None
    canonical_hardware_id_at_parse_time: int | None = None
    wattage_w: int | None = None
    panel_array_kw: float | None = None
    confidence: str | None = None
    parser_owned: bool | None = None
    source_fragment: str | None = None
    parser_rule_version: str | None = None


class JobHardwareSiteNotes(_Strict):
    """Free-form site/electrical notes captured alongside hardware (editable text)."""

    ct: str | None = None
    export_limit: str | None = None
    underground: str | None = None
    comms: str | None = None
    raw_misc: list[str] | None = None


class JobHardwarePatch(_Strict):
    """A partial hardware-snapshot patch. Every sub-section is optional, so a patch may touch just
    one (e.g. only ``inverters``); each PROVIDED sub-section replaces that whole sub-section, and
    absent ones are preserved by the merge."""

    inverters: list[JobHardwareItem] | None = None
    batteries: list[JobHardwareItem] | None = None
    metering: list[JobHardwareItem] | None = None
    panel: JobHardwarePanel | None = None
    site_notes: JobHardwareSiteNotes | None = None
    warnings: list[str] | None = None


def validate_hardware_patch(patch: dict) -> JobHardwarePatch:
    """Validate a hardware patch dict, converting a Pydantic ``ValidationError`` into a plain
    ``ValueError`` so the details-patch service keeps its single error contract (-> HTTP 422)."""
    try:
        return JobHardwarePatch.model_validate(patch)
    except ValidationError as exc:
        errs = exc.errors()
        first = errs[0] if errs else {}
        loc = ".".join(str(p) for p in first.get("loc", ())) or "hardware"
        raise ValueError(f"Invalid hardware snapshot at '{loc}': {first.get('msg', 'invalid')}")
