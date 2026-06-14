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

from app.services.import_field_registry import allowed_details_paths


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

    leaves = flatten_leaves(patch)
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
    return merged
