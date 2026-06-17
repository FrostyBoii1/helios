"""Advisory customer-match candidates for an import row (Section B1).

READ-ONLY and ADVISORY. Given a staged import row, surface POSSIBLE same-customer
candidates — other rows in the same batch and existing live customers — each with
explicit reasons and a confidence band, so a reviewer can spot continuity issues
*before* any commit. Nothing here merges, links, auto-resolves, persists, or
mutates anything; the result is purely informational.

The pure, DB-free scoring core (``Signature`` / ``build_signature`` / ``score`` and
their normalization / entity / address helpers) lives in
``app.services.matching_core`` (Section B4-0) and is shared with future live-CRM
duplicate detection. It is re-exported here so existing callers keep importing
``build_signature`` / ``score`` from this module unchanged. This module keeps the
import-specific pieces: the row / live-customer ``Signature`` builders, the
candidate-list cap, and the batch-row + live-customer candidate query
(``find_candidates``).

Design (from the Section B diagnosis):
  * exact/normalized name + a corroborator (phone / email / shared legacy ref /
    address) is STRONG;
  * exact name with no corroborator is WEAK (manual);
  * spouse/order variants and subset same-surname cases are manual suggestions;
  * company/trust/entity names are conservative — only an exact string name match
    counts (never fuzzy-merged);
  * a shared legacy_reference is surfaced as a reason (it is the source's own
    grouping), never used to silently skip.

No PII is logged here (only ids / counts / reasons are returned).
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.enums import ImportRowClass
from app.models.import_staging import ImportRow
from app.services.matching_core import (
    CONF_RANK,
    Signature,
    build_signature,
    score,
)

# Re-export the shared scoring core so callers/tests that historically imported
# these from import_matching keep working unchanged (Section B4-0 extraction).
__all__ = [
    "Signature",
    "build_signature",
    "score",
    "CONF_RANK",
    "find_candidates",
]

# Import-specific cap on the advisory candidate list (candidate shaping). A future
# live-CRM duplicate-detection caller may use its own cap; this one is the import
# endpoint's.
MAX_CANDIDATES = 15


# --------------------------------------------------------------------------- #
# Signature builders from DB objects (read-only)
# --------------------------------------------------------------------------- #
def _row_signature(row: ImportRow) -> Signature:
    p = row.parsed or {}
    raw = row.raw or {}
    phones = [x.get("number") for x in (p.get("phones") or [])]
    address = p.get("address") or raw.get("address") or ""
    return build_signature(
        name=p.get("customer_name") or "",
        phones=phones,
        emails=p.get("emails") or [],
        legacy_ref=row.legacy_reference,
        address=address,
    )


def _customer_signature(c: Customer) -> Signature:
    address = ", ".join(x for x in (c.address_line1, c.suburb, c.state) if x)
    return build_signature(
        name=c.full_name,
        phones=[c.phone] if c.phone else [],
        emails=[c.email] if c.email else [],
        legacy_ref=None,
        address=address,
    )


# --------------------------------------------------------------------------- #
# Orchestration (read-only DB reads; no writes)
# --------------------------------------------------------------------------- #
_COMMITTABLE = (ImportRowClass.JOB.value, ImportRowClass.AMBIGUOUS.value)


def find_candidates(db: Session, row: ImportRow) -> list[dict]:
    """Advisory same-customer candidates for ``row`` — other batch rows + live
    customers — sorted strong→weak then by name, capped. Read-only."""
    target = _row_signature(row)
    if not (target.surname or target.phones or target.emails or target.legacy_ref):
        return []

    out: list[dict] = []

    # In-batch rows pre-filtered by surname / shared ref (keeps it cheap on a
    # ~thousands-row batch); scoring re-checks all signals authoritatively.
    name_col = ImportRow.parsed["customer_name"].astext
    conds = []
    if target.surname:
        conds.append(name_col.ilike(f"%{target.surname}%"))
    if target.legacy_ref:
        conds.append(ImportRow.legacy_reference == target.legacy_ref)
    if conds:
        batch_rows = db.scalars(
            select(ImportRow).where(
                ImportRow.batch_id == row.batch_id,
                ImportRow.id != row.id,
                ImportRow.row_class.in_(_COMMITTABLE),
                or_(*conds),
            )
        ).all()
        for r in batch_rows:
            reasons, conf = score(target, _row_signature(r))
            if reasons:
                out.append({
                    "kind": "batch_row",
                    "row_id": r.id,
                    "source_row_index": r.source_row_index,
                    "customer_id": r.committed_customer_id,
                    "name": ((r.parsed or {}).get("customer_name") or "").strip(),
                    "confidence": conf,
                    "reasons": reasons,
                })

    # Live customers pre-filtered by surname / exact phone / exact email.
    live_conds = []
    if target.surname:
        live_conds.append(Customer.full_name.ilike(f"%{target.surname}%"))
    for ph in target.phones:
        live_conds.append(Customer.phone == ph)
    for em in target.emails:
        live_conds.append(Customer.email.ilike(em))
    if live_conds:
        live = db.scalars(
            select(Customer).where(Customer.deleted_at.is_(None), or_(*live_conds)).limit(200)
        ).all()
        for c in live:
            reasons, conf = score(target, _customer_signature(c))
            if reasons:
                out.append({
                    "kind": "live_customer",
                    "row_id": None,
                    "source_row_index": None,
                    "customer_id": c.id,
                    "name": c.full_name,
                    "confidence": conf,
                    "reasons": reasons,
                })

    out.sort(key=lambda x: (CONF_RANK[x["confidence"]], (x["name"] or "").lower()))
    return out[:MAX_CANDIDATES]
