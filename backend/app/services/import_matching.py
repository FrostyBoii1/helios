"""Advisory customer-match candidates for an import row (Section B1).

READ-ONLY and ADVISORY. Given a staged import row, surface POSSIBLE same-customer
candidates — other rows in the same batch and existing live customers — each with
explicit reasons and a confidence band, so a reviewer can spot continuity issues
*before* any commit. Nothing here merges, links, auto-resolves, persists, or
mutates anything; the result is purely informational.

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

import re
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.enums import ImportRowClass
from app.models.import_staging import ImportRow

# Company / trust / organisation markers — treat these names conservatively
# (exact-string name match only; never normalized/spouse/subset merging).
_ENTITY_RE = re.compile(
    r"\b(?:pty|ltd|inc|llc|trust|trustee|trustees|superannuation|fund|"
    r"company|corp|enterprises|holdings|services|group|motel|motor\s+inn|"
    r"hotel|c/o)\b",
    re.IGNORECASE,
)
# A leading "House 2 -", "Unit 4", "Lot 7" style prefix on an address — stripping
# it lets two properties at the same base address match as House/Unit variants.
_HOUSE_PREFIX_RE = re.compile(
    r"^\s*(?:house|unit|flat|apt|apartment|villa|lot)\b\s*\w*\s*[-,:]?\s*",
    re.IGNORECASE,
)

CONF_RANK = {"strong": 0, "medium": 1, "weak": 2}
MAX_CANDIDATES = 15

_NAME_LABEL = {
    "exact": "exact name",
    "normalized": "normalized name match",
    "spouse": "possible spouse/order variation",
    "subset": "subset same-surname match",
}


@dataclass(frozen=True)
class Signature:
    """The comparable fields extracted from a row or a live customer (pure)."""

    name: str          # display name (original)
    name_lc: str       # lowercased + stripped (exact compare)
    norm_sorted: str   # normalized + token-sorted (spouse/order + & variants)
    tokens: frozenset  # token set, "and" removed (subset detection)
    surname: str       # last cleaned token
    has_couple: bool   # contains "and"/"&"
    is_entity: bool    # company/trust/org name
    phones: frozenset  # digits-only phone numbers
    emails: frozenset  # lowercased emails
    legacy_ref: str    # exact legacy reference string
    addr_norm: str     # normalized full address
    addr_base: str     # normalized address with a leading House/Unit prefix removed


def _clean(name: str) -> str:
    s = re.sub(r"&", " and ", (name or "").lower())
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _norm_addr(addr: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", (addr or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def build_signature(
    *,
    name: str | None,
    phones: list | None = None,
    emails: list | None = None,
    legacy_ref: str | None = None,
    address: str | None = None,
) -> Signature:
    """Build a comparable Signature from raw values (pure, DB-free)."""
    cleaned = _clean(name or "")
    toks = [t for t in cleaned.split() if t != "and"]
    return Signature(
        name=(name or "").strip(),
        name_lc=(name or "").strip().lower(),
        norm_sorted=" ".join(sorted(toks)),
        tokens=frozenset(toks),
        surname=toks[-1] if toks else "",
        has_couple=bool(re.search(r"\band\b", cleaned)) or "&" in (name or ""),
        is_entity=bool(_ENTITY_RE.search(name or "")),
        phones=frozenset(d for d in (re.sub(r"\D", "", str(p)) for p in (phones or [])) if d),
        emails=frozenset(e.strip().lower() for e in (emails or []) if e and str(e).strip()),
        legacy_ref=(legacy_ref or "").strip(),
        addr_norm=_norm_addr(address or ""),
        addr_base=_norm_addr(_HOUSE_PREFIX_RE.sub("", address or "")),
    )


def score(a: Signature, b: Signature) -> tuple[list[str], str | None]:
    """Pure: (reasons, confidence) for candidate ``b`` against target ``a``.

    Returns ([], None) when ``b`` is not a candidate. Confidence is advisory only —
    NO automatic action is implied by any band.
    """
    # Corroborators (booleans first, so reasons read name-first).
    ph = bool(a.phones & b.phones)
    em = bool(a.emails & b.emails)
    shared_ref = bool(a.legacy_ref and a.legacy_ref == b.legacy_ref)
    addr_exact = bool(a.addr_norm and a.addr_norm == b.addr_norm)
    addr_house = bool(
        not addr_exact and a.addr_base and b.addr_base and a.addr_base == b.addr_base
        and a.addr_norm and b.addr_norm
    )
    strong_corrob = ph or em or shared_ref or addr_exact or addr_house

    # Name-match level. Entities (company/trust) only ever match on exact string.
    entity = a.is_entity or b.is_entity
    name_level: str | None = None
    if a.name_lc and a.name_lc == b.name_lc:
        name_level = "exact"
    elif not entity:
        if a.norm_sorted and a.norm_sorted == b.norm_sorted:
            name_level = "spouse" if (a.has_couple or b.has_couple) else "normalized"
        elif a.surname and a.surname == b.surname and (a.tokens < b.tokens or b.tokens < a.tokens):
            name_level = "subset"

    reasons: list[str] = []
    if name_level:
        reasons.append(_NAME_LABEL[name_level])
    if ph:
        reasons.append("shared phone")
    if em:
        reasons.append("shared email")
    if shared_ref:
        reasons.append("shared legacy reference")
    if addr_exact:
        reasons.append("address match")
    if addr_house:
        reasons.append("address differs only by House/Unit prefix")

    if not reasons:
        return [], None

    strong_name = name_level in ("exact", "normalized")
    variant_name = name_level in ("spouse", "subset")
    if strong_name and strong_corrob:
        conf = "strong"
    elif shared_ref and name_level:
        conf = "strong"
    elif variant_name and strong_corrob:
        conf = "medium"
    elif shared_ref:
        conf = "medium"
    else:
        # name-only (incl. exact without a corroborator) or a lone corroborator.
        conf = "weak"
    return reasons, conf


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
