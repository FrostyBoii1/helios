"""Customer domain logic: lookup, search/list, create, update, soft delete.

All reads exclude soft-deleted rows (`deleted_at IS NULL`). Delete is a soft
delete (sets `deleted_at`); `session.delete()` is never used on customers, so the
relationship cascade can never hard-delete child jobs.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.customer import Customer


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
