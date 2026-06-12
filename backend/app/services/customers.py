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
