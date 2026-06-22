"""Shared, path-restricted structured-details patch helper (Phase 4b).

Used by live ``Job.details`` edits. Mirrors the staging-side
``import_review.apply_details_patch`` but operates on a *bare* details dict
(``job.details``) rather than a parsed candidate. The set of writable leaf paths
is the single registry-derived whitelist ``allowed_details_paths()`` — so live
jobs and import rows can never drift on what is editable.
"""

from __future__ import annotations

import copy
from typing import Any

from app.schemas.job_hardware import validate_hardware_patch
from app.services.import_field_registry import allowed_details_paths

_UNSET = object()


def flatten_leaves(patch: dict, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested patch to ``{"<section>.<key>...": value}`` leaf paths."""
    out: dict[str, Any] = {}
    for k, v in (patch or {}).items():
        path = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten_leaves(v, path + "."))
        else:
            out[path] = v
    return out


def merge_details_patch(details: dict | None, patch: Any) -> dict:
    """Return a NEW details dict with ``patch`` deep-merged, path-restricted.

    Only the registry's editable ``<section>.<key>`` leaf paths may be written;
    any other path (unknown section/key, or a derived/read-only path such as
    flags / provenance / notes.misfiled) raises ``ValueError``. A non-dict patch
    (including ``None``) also raises ``ValueError`` — the update path treats
    ``details`` as a partial patch, never a full replacement. Never mutates the
    input in place; always stamps ``_v = 2``.
    """
    if not isinstance(patch, dict):
        raise ValueError("details must be an object (partial patch), not null/scalar")

    # The `hardware` snapshot (Stage 3) is a deeply-nested, Job-owned structure validated by
    # SHAPE (JobHardwarePatch, extra='forbid') rather than the flat <section>.<key> path
    # whitelist, and written as whole sub-sections — never a live catalogue reference. Split it
    # out here; everything else stays the exact registry-whitelisted flat patch as before.
    rest = dict(patch)
    hardware_patch = rest.pop("hardware", _UNSET)

    leaves = flatten_leaves(rest)
    allowed = allowed_details_paths()
    disallowed = sorted(p for p in leaves if p not in allowed)
    if disallowed:
        raise ValueError(f"Disallowed details path(s): {disallowed}")

    merged = copy.deepcopy(details) if isinstance(details, dict) else {}
    merged.setdefault("_v", 2)
    for path, value in leaves.items():
        section, key = path.split(".", 1)
        sect = merged.get(section)
        sect = dict(sect) if isinstance(sect, dict) else {}
        sect[key] = value
        merged[section] = sect

    if hardware_patch is not _UNSET:
        merged["hardware"] = _merge_hardware(merged.get("hardware"), hardware_patch)
    return merged


def _merge_hardware(existing: Any, patch: Any) -> dict:
    """Merge a validated hardware-snapshot patch into the existing hardware object. Each PROVIDED
    sub-section replaces that whole sub-section (a snapshot the user fully controls); an explicit
    ``null`` clears one; absent sub-sections are preserved. Validated by ``JobHardwarePatch`` —
    unknown fields / wrong types raise ``ValueError`` (-> 422), so garbage can't reach details."""
    if not isinstance(patch, dict):
        raise ValueError("hardware must be an object (partial snapshot), not null/scalar")
    validated = validate_hardware_patch(patch)
    dumped = validated.model_dump(exclude_none=True)
    hw = dict(existing) if isinstance(existing, dict) else {}
    for key in validated.model_fields_set:
        if getattr(validated, key) is None:
            hw.pop(key, None)        # explicit null -> clear that sub-section
        else:
            hw[key] = dumped[key]    # replace the whole sub-section (list / object)
    return hw
