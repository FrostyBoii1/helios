"""Import ↔ hardware-snapshot bridge (Hardware Parser lane, Stage 4B).

Wires the Stage-4A read-only parser runtime (`app.hardware.runtime.parse_hardware`) into the
completed-sheet import pipeline. Hardware is parsed ONCE, DB-aware, during INGEST (here — the pure
`import_parser` stays DB-free) and stored on ``ImportRow.parsed["details"]["hardware"]``. Because
both preview/review (which return `parsed.details`) and commit (`build_job_data` copies
`parsed.details`) read that SAME stored value, preview and commit can never diverge — the parser is
never re-run separately at commit.

Read-only w.r.t. the catalogue/jobs: `parse_hardware` mutates nothing; the only write is the row's
`parsed` JSON (done by the ingest caller). Legacy ``details.system.panel/inverter`` text is left
untouched (it coexists). Stage 4B does NOT build any review UI — preview/review surface the snapshot
through the existing `parsed.details` payload; polished rendering is Stage 4C.
"""
from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.hardware.runtime import parse_hardware
from app.schemas.job_hardware import JobHardwarePatch


def _coerce_int(value: object) -> int | None:
    """Best-effort int from a parsed cell (e.g. '30', '30.0'); None when non-numeric."""
    try:
        return int(str(value).strip().split(".")[0])
    except (TypeError, ValueError, AttributeError):
        return None


def enrich_row_hardware(db: Session, parsed: dict | None) -> None:
    """Parse the row's hardware cells into ``parsed['details']['hardware']`` IN PLACE.

    No-op when the row has no structured `details` or no hardware cells. `parse_hardware` is
    READ-ONLY (reads the DB catalogue/aliases + versioned rules; mutates nothing) and validates its
    own output against `JobHardwarePatch`, so the stored value is always a valid snapshot.
    """
    if not isinstance(parsed, dict):
        return
    details = parsed.get("details")
    if not isinstance(details, dict):
        return
    inverter_text = parsed.get("inverter_raw")
    panel_text = parsed.get("panel_raw")
    if not (inverter_text or panel_text):
        return
    details["hardware"] = parse_hardware(
        db,
        inverter_text=inverter_text,
        panel_text=panel_text,
        quantity_hint=_coerce_int(parsed.get("no_of_panels")),
        source_type="workbook",
        source_field="hardware",
    )


def validate_committed_hardware(details: dict | None) -> None:
    """Commit-boundary safety net: a stored hardware snapshot must be `JobHardwarePatch`-valid
    before it is persisted into ``Job.details.hardware``. Raises ``ValueError`` (which fails the
    single import row safely, never an orphan) on a malformed snapshot. No-op when absent."""
    hardware = (details or {}).get("hardware")
    if hardware is None:
        return
    try:
        JobHardwarePatch.model_validate(hardware)
    except ValidationError as exc:
        first = exc.errors()[:1]
        raise ValueError(f"Invalid hardware snapshot on import row: {first}")
