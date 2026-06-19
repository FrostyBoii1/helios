"""Customer domain logic: lookup, search/list, create, update, soft delete.

All reads exclude soft-deleted rows (`deleted_at IS NULL`). Delete is a soft
delete (sets `deleted_at`); `session.delete()` is never used on customers, so the
relationship cascade can never hard-delete child jobs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.customer import Customer
from app.models.customer_contact_variant import CustomerContactVariant
from app.models.document import Document
from app.models.enums import ActivityType, CustomerContactVariantSource
from app.models.import_staging import ImportCustomerGroup, ImportRow
from app.models.job import Job
from app.models.task import Task
from app.services.activity import log_activity


def get_customer(db: Session, customer_id: int) -> Customer | None:
    stmt = select(Customer).where(
        Customer.id == customer_id, Customer.deleted_at.is_(None)
    )
    return db.scalar(stmt)


def resolve_active_customer(db: Session, customer_id: int) -> Customer | None:
    """Walk the ``merged_into_customer_id`` chain to the live winner customer.

    B4-1 pure read helper. Given a (possibly merged, soft-deleted, or missing)
    customer id, follow merge pointers loser -> winner until the chain ends and
    return the final customer only when it is genuinely active.

    Returns:
      * the customer itself — when it exists, is not merged, and is not deleted
        (a normal active customer resolves to itself);
      * the final winner of a one-or-more-hop merge chain — when that winner is
        active;
      * ``None`` — when the id does not exist, when the chain terminates at a
        soft-deleted customer (no active customer to resolve to), or when a cycle
        is detected (guarded — the walk visits each id at most once and never
        loops).

    Intermediate losers are followed regardless of their own ``deleted_at`` (a
    merged loser is itself soft-deleted); only the FINAL node's active state
    decides the result. Never mutates. NOT used by merge execution — there is no
    merge execution yet (B4-2+).
    """
    seen: set[int] = set()
    current = db.get(Customer, customer_id)
    while current is not None:
        if current.id in seen:
            # Corrupt chain (cycle) — refuse to loop; there is no safe winner.
            return None
        seen.add(current.id)
        next_id = current.merged_into_customer_id
        if next_id is None:
            # End of the chain: active only when not soft-deleted.
            return current if current.deleted_at is None else None
        current = db.get(Customer, next_id)
    return None


def list_contact_variants(db: Session, customer: Customer) -> list[CustomerContactVariant]:
    """Active (non-archived) alternate contact/address variants for a LIVE customer,
    newest first. Read-only (Stage 2). The caller resolves the active customer first
    (``get_customer``), so variants are never exposed for a missing / soft-deleted /
    merged-loser id; archived (``deleted_at``) variants are excluded here too."""
    stmt = (
        select(CustomerContactVariant)
        .where(
            CustomerContactVariant.customer_id == customer.id,
            CustomerContactVariant.deleted_at.is_(None),
        )
        .order_by(
            CustomerContactVariant.created_at.desc(),
            CustomerContactVariant.id.desc(),
        )
    )
    return list(db.scalars(stmt).all())


def merged_winner_for(db: Session, customer_id: int) -> Customer | None:
    """If ``customer_id`` is a MERGED loser, return the final LIVE winner it resolves
    to; else None. Pure read (B4-4).

    A merged loser is a row that EXISTS, is soft-deleted, and carries
    ``merged_into_customer_id``. For one, chain-walk ``merged_into`` to the live winner
    via :func:`resolve_active_customer`. Returns None for a non-existent id, a normally
    soft-deleted (non-merged) customer, or a chain that dead-ends at a deleted/cyclic
    target — the caller (GET /customers/{id}) then falls back to a plain 404. Used only
    to turn a stale merged-loser URL into an explicit "merged into X" notice; it never
    exposes the loser's own (soft-deleted) data.
    """
    raw = db.get(Customer, customer_id)
    if raw is None or raw.merged_into_customer_id is None:
        return None
    return resolve_active_customer(db, customer_id)


def list_customers(
    db: Session,
    *,
    q: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[Customer], int]:
    """Return (page of active customers, total matching count).

    `q` performs a case-insensitive ILIKE across name/email/phone/suburb/postcode.
    """
    filters = [Customer.deleted_at.is_(None)]
    if q:
        like = f"%{q.strip()}%"
        filters.append(
            or_(
                Customer.full_name.ilike(like),
                Customer.email.ilike(like),
                Customer.phone.ilike(like),
                Customer.suburb.ilike(like),
                Customer.postcode.ilike(like),
            )
        )

    total = db.scalar(select(func.count()).select_from(Customer).where(*filters)) or 0

    stmt = (
        select(Customer)
        .where(*filters)
        .order_by(Customer.full_name)
        .limit(limit)
        .offset(offset)
    )
    items = list(db.scalars(stmt).all())
    return items, total


def create_customer(db: Session, *, data: dict) -> Customer:
    """Create a customer from a validated dict. Adds (does not commit)."""
    customer = Customer(**data)
    db.add(customer)
    return customer


def update_customer(db: Session, customer: Customer, *, data: dict) -> list[str]:
    """Apply a partial update in place. Returns the list of changed field names."""
    changed: list[str] = []
    for field, value in data.items():
        if getattr(customer, field) != value:
            setattr(customer, field, value)
            changed.append(field)
    return changed


def soft_delete_customer(db: Session, customer: Customer) -> None:
    """Mark a customer deleted. Never performs a hard delete."""
    customer.deleted_at = datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# B4-2: explicit admin customer merge (LOSER -> WINNER), transactional.
# --------------------------------------------------------------------------- #
class MergeError(Exception):
    """A B4-2 merge guard failure. Carries the HTTP status the endpoint should
    surface. Guard failures are raised BEFORE any mutation, so the transaction
    stays clean; a mid-merge integrity failure raises 500 and the endpoint rolls
    back the whole (single) transaction."""

    def __init__(self, reason: str, http_status: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.http_status = http_status


def _build_merge_note(loser: Customer, *, merged_at: datetime) -> str | None:
    """The provenance block appended to the winner's internal_notes, or None when
    the loser carries no notes/internal_notes worth preserving. NULL/blank-safe."""
    parts: list[str] = []
    if loser.notes and loser.notes.strip():
        parts.append(f"Notes: {loser.notes.strip()}")
    if loser.internal_notes and loser.internal_notes.strip():
        parts.append(f"Internal notes: {loser.internal_notes.strip()}")
    if not parts:
        return None
    header = f"--- Merged from {loser.full_name} (#{loser.id}) on {merged_at:%Y-%m-%d} ---"
    return header + "\n" + "\n".join(parts)


# Customer-level fields captured into a merge variant: (loser/winner attr, variant attr).
# full_name maps to the variant's display_name; everything else maps 1:1. Job-specific
# notes and Job.details.site are deliberately NOT captured here.
_MERGE_VARIANT_FIELDS: tuple[tuple[str, str], ...] = (
    ("full_name", "display_name"),
    ("email", "email"),
    ("phone", "phone"),
    ("address_line1", "address_line1"),
    ("address_line2", "address_line2"),
    ("suburb", "suburb"),
    ("state", "state"),
    ("postcode", "postcode"),
)


def _capture_merge_variant(
    db: Session, *, loser: Customer, winner: Customer, merged_at: datetime, actor_id: int
) -> CustomerContactVariant | None:
    """Stage 3: preserve the LOSER's meaningfully-different customer-level fields as one
    ``CustomerContactVariant`` on the WINNER (``source_type=merged_customer``,
    ``source_customer_id=loser``).

    Conservative + deterministic: a field is captured only when the loser value (trimmed)
    is NON-empty AND differs from the winner's same field (trimmed) — identical or empty
    fields are skipped, and NO variant is created when nothing meaningfully differs. NEVER
    touches the winner's primary fields; never captures job notes or Job.details.site.
    ``source_customer_id`` is stored for audit but is NOT exposed by the read API (Stage 2).
    """
    captured: dict[str, str] = {}
    for attr, variant_attr in _MERGE_VARIANT_FIELDS:
        loser_val = (getattr(loser, attr) or "").strip()
        winner_val = (getattr(winner, attr) or "").strip()
        if loser_val and loser_val != winner_val:
            captured[variant_attr] = loser_val
    if not captured:
        return None
    variant = CustomerContactVariant(
        customer_id=winner.id,
        source_type=CustomerContactVariantSource.MERGED_CUSTOMER.value,
        source_customer_id=loser.id,
        label="Merged customer details",
        note=f"From merged customer {loser.full_name} (#{loser.id}) on {merged_at:%Y-%m-%d}",
        created_by_id=actor_id,
        **captured,
    )
    db.add(variant)
    return variant


def _repoint_returning_ids(
    db: Session,
    model: Any,
    column: str,
    *,
    loser_id: int,
    winner_id: int,
    extra_values: dict[str, Any] | None = None,
) -> list[int]:
    """Repoint ``model.<column>`` loser_id -> winner_id in one bulk UPDATE and return
    the affected row ids (RETURNING). Pre-counts and asserts the rowcount matches so a
    silent orphan can never slip through. ``synchronize_session=False`` — no stale ORM
    object is read afterwards (counts/ids come from RETURNING, the loser/winner Customer
    rows are not touched by these child-table updates)."""
    col = getattr(model, column)
    expected = db.scalar(select(func.count()).select_from(model).where(col == loser_id)) or 0
    values: dict[str, Any] = {column: winner_id}
    if extra_values:
        values.update(extra_values)
    stmt = (
        update(model)
        .where(col == loser_id)
        .values(**values)
        .returning(model.id)
        .execution_options(synchronize_session=False)
    )
    ids = list(db.execute(stmt).scalars().all())
    if len(ids) != expected:
        raise MergeError("repoint_count_mismatch", 500)
    return ids


def merge_customers(db: Session, *, loser_id: int, winner_id: int, actor_id: int) -> dict:
    """Merge the LOSER customer into the WINNER (B4-2). ONE transaction; the caller
    (endpoint) commits. Admin-only, explicit, non-destructive — nothing is hard-deleted.

    Guards (re-checked under a row lock, before any mutation): loser != winner; both
    exist; neither is already merged (immutable); both are live. Then repoints every
    customer FK loser->winner (Job/Activity/Task/Document + the import links
    committed_customer_id / resolved_customer_id / group committed_customer_id), appends
    the loser's notes into the winner's internal_notes with a provenance header,
    soft-deletes the loser + records the (immutable) merge pointer, and logs ONE
    CUSTOMER_MERGED activity. Returns a summary dict (winner + moved/repointed ids/counts).
    """
    if loser_id == winner_id:
        raise MergeError("same_customer", 400)

    # Lock BOTH customer rows in canonical (id-ascending) order to avoid a deadlock
    # between inverse concurrent merges; FOR UPDATE on the loser also blocks any
    # concurrent insert of a child row referencing it (an FK insert takes FOR KEY
    # SHARE, which conflicts), so the loser's child set is frozen for the merge.
    locked = db.scalars(
        select(Customer)
        .where(Customer.id.in_((loser_id, winner_id)))
        .order_by(Customer.id)
        .with_for_update()
    ).all()
    by_id = {c.id: c for c in locked}
    loser = by_id.get(loser_id)
    winner = by_id.get(winner_id)

    # Re-validate ALL guards under the lock (TOCTOU-safe). already_merged is checked
    # before not_live so a merged customer reports the precise immutability reason.
    if loser is None:
        raise MergeError("loser_not_found", 404)
    if winner is None:
        raise MergeError("winner_not_found", 404)
    if loser.merged_into_customer_id is not None:
        raise MergeError("loser_already_merged", 409)
    if winner.merged_into_customer_id is not None:
        raise MergeError("winner_already_merged", 409)
    if loser.deleted_at is not None:
        raise MergeError("loser_not_live", 409)
    if winner.deleted_at is not None:
        raise MergeError("winner_not_live", 409)

    merged_at = datetime.now(timezone.utc)

    # Repoint live-CRM customer FKs loser -> winner. The Job repoint ALSO bumps
    # updated_at (server now()) so every moved job becomes non-pristine and a later
    # reverse is blocked by the existing `job_modified` guard — the moved job must
    # never be reversible into soft-deleting the merge WINNER (owner decision 2).
    # NOTE: this relies on merge running in its OWN transaction strictly AFTER the
    # import commit (the normal endpoint path). Postgres now() is transaction-stable,
    # so created_at (commit, txn T1) < updated_at (merge, txn T2). Do NOT call merge
    # in the same transaction as the commit, or the bump is a no-op — the
    # `job_customer_mismatch` guard still covers partial/divergent states regardless.
    job_ids = _repoint_returning_ids(
        db, Job, "customer_id", loser_id=loser_id, winner_id=winner_id,
        extra_values={"updated_at": func.now()},
    )
    # Repoint activities BEFORE logging the CUSTOMER_MERGED row, so the new row
    # (customer_id=winner) is never swept by this loser->winner UPDATE.
    activity_ids = _repoint_returning_ids(db, Activity, "customer_id", loser_id=loser_id, winner_id=winner_id)
    task_ids = _repoint_returning_ids(db, Task, "customer_id", loser_id=loser_id, winner_id=winner_id)
    document_ids = _repoint_returning_ids(db, Document, "customer_id", loser_id=loser_id, winner_id=winner_id)

    # Import links — each its OWN column WHERE/SET (never a blanket two-column update,
    # else a row with committed==loser but resolved==other would have resolved clobbered).
    committed_row_ids = _repoint_returning_ids(db, ImportRow, "committed_customer_id", loser_id=loser_id, winner_id=winner_id)
    resolved_row_ids = _repoint_returning_ids(db, ImportRow, "resolved_customer_id", loser_id=loser_id, winner_id=winner_id)
    group_ids = _repoint_returning_ids(db, ImportCustomerGroup, "committed_customer_id", loser_id=loser_id, winner_id=winner_id)

    # Append the loser's notes/internal_notes into the winner's internal_notes with a
    # provenance header. Winner contact/address/notes stay authoritative (untouched).
    note_block = _build_merge_note(loser, merged_at=merged_at)
    notes_appended = note_block is not None
    if notes_appended:
        if winner.internal_notes and winner.internal_notes.strip():
            winner.internal_notes = f"{winner.internal_notes}\n\n{note_block}"
        else:
            winner.internal_notes = note_block

    # Stage 3: also preserve the loser's meaningfully-different customer-level identity/
    # contact/address fields as a structured CustomerContactVariant on the winner (only
    # when something differs). This is additive — the winner's primary fields and the
    # notes-append above are unchanged.
    _capture_merge_variant(db, loser=loser, winner=winner, merged_at=merged_at, actor_id=actor_id)

    # Soft-delete the loser + record the immutable merge pointer. Never hard-delete.
    loser.deleted_at = merged_at
    loser.merged_into_customer_id = winner.id
    loser.merged_at = merged_at

    moved = {
        "jobs": {"count": len(job_ids), "ids": job_ids},
        "tasks": {"count": len(task_ids), "ids": task_ids},
        "documents": {"count": len(document_ids), "ids": document_ids},
        "activities": {"count": len(activity_ids)},  # count-only (owner decision 3)
    }
    repointed_import = {
        "rows_committed": {"count": len(committed_row_ids), "ids": committed_row_ids},
        "rows_resolved": {"count": len(resolved_row_ids), "ids": resolved_row_ids},
        "groups_committed": {"count": len(group_ids), "ids": group_ids},
    }
    log_activity(
        db,
        activity_type=ActivityType.CUSTOMER_MERGED,
        description=(
            f"Merged customer {loser.full_name} (#{loser.id}) "
            f"into {winner.full_name} (#{winner.id})"
        ),
        actor_id=actor_id,
        customer_id=winner.id,
        meta={
            "loser_customer_id": loser.id,
            "winner_customer_id": winner.id,
            "loser_name": loser.full_name,
            "merged_at": merged_at.isoformat(),
            "moved": moved,
            "repointed_import": repointed_import,
            "notes_appended": notes_appended,
        },
    )

    return {
        "winner": winner,
        "loser_id": loser.id,
        "merged_at": merged_at,
        "moved": moved,
        "repointed_import": repointed_import,
        "notes_appended": notes_appended,
    }
