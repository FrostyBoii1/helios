"""Section B4-0 — the pure matching core was extracted from import_matching without
behaviour change.

These tests pin the contract that matters for the refactor: the scoring core lives
in ``matching_core`` and ``import_matching`` re-exports the SAME objects, so every
existing B1/B2/B3 caller keeps the identical scoring behaviour. (The full scoring
rules themselves are exercised by test_import_matching.py, which still imports
``build_signature`` / ``score`` from ``import_matching``.)
"""

from __future__ import annotations

from app.services import import_matching
from app.services import matching_core


def test_import_matching_reexports_the_same_core_objects():
    # Re-export is a true move, not a copy: identical objects, so the two modules
    # can never drift in scoring behaviour.
    assert import_matching.score is matching_core.score
    assert import_matching.build_signature is matching_core.build_signature
    assert import_matching.Signature is matching_core.Signature
    assert import_matching.CONF_RANK is matching_core.CONF_RANK


def test_core_is_pure_and_scores_identically_through_either_module():
    a = matching_core.build_signature(name="Dana Fox", phones=["0400123123"])
    b = matching_core.build_signature(name="Dana Fox", phones=["0400123123"])
    # Same result whether called via the core or via the import_matching re-export.
    assert matching_core.score(a, b) == import_matching.score(a, b)
    reasons, conf = matching_core.score(a, b)
    assert "exact name" in reasons and "shared phone" in reasons and conf == "strong"


def test_entity_conservatism_preserved_in_core():
    # Company/trust names never fuzzy-merge — only an exact string match surfaces.
    a = matching_core.build_signature(name="Horton Family Trust")
    b = matching_core.build_signature(name="C &J Horton PTY as Trustees for Horton")
    assert matching_core.score(a, b) == ([], None)
