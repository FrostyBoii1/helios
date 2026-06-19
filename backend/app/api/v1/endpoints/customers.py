"""Customer endpoints.

Permissions (per approved matrix):
  * List / search / view : any authenticated user
  * Create / update      : admin, sales_admin
  * Soft delete          : admin only

Follows the standard pattern: validate -> permission check -> transaction ->
activity log -> typed response.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin, require_roles
from app.db.session import get_db
from app.models.enums import ActivityType, RoleName
from app.models.user import User
from app.schemas.customer import (
    CustomerContactVariantList,
    CustomerContactVariantRead,
    CustomerCreate,
    CustomerList,
    CustomerMergeResult,
    CustomerRead,
    CustomerUpdate,
    MergeMovedCount,
)
from app.services import customers as customers_service
from app.services.activity import log_activity

router = APIRouter()

# Roles permitted to create/update customer records.
can_write = require_roles(RoleName.ADMIN, RoleName.SALES_ADMIN)


@router.get("", response_model=CustomerList)
def list_customers(
    q: str | None = Query(default=None, description="Search name/email/phone/suburb/postcode"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> CustomerList:
    items, total = customers_service.list_customers(db, q=q, limit=limit, offset=offset)
    return CustomerList(
        items=[CustomerRead.model_validate(c) for c in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(can_write),
) -> CustomerRead:
    customer = customers_service.create_customer(db, data=payload.model_dump())
    db.flush()  # assign id before logging
    log_activity(
        db,
        activity_type=ActivityType.CUSTOMER_CREATED,
        description=f"Created customer {customer.full_name}",
        actor_id=actor.id,
        customer_id=customer.id,
    )
    db.commit()
    db.refresh(customer)
    return CustomerRead.model_validate(customer)


@router.get("/{customer_id}", response_model=CustomerRead)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> CustomerRead:
    customer = customers_service.get_customer(db, customer_id)
    if customer is None:
        # B4-4: a merged loser is hidden (deleted_at) but should not feel like a
        # mystery 404 — point a stale/bookmarked loser URL at the live winner it was
        # merged into. Deleted customers stay hidden (no loser data is exposed); only
        # genuinely-merged losers with a resolvable live winner get the enriched body.
        winner = customers_service.merged_winner_for(db, customer_id)
        if winner is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "reason": "merged",
                    "merged_into_customer_id": winner.id,
                    "merged_into_name": winner.full_name,
                },
            )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return CustomerRead.model_validate(customer)


@router.get("/{customer_id}/contact-variants", response_model=CustomerContactVariantList)
def list_customer_contact_variants(
    customer_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> CustomerContactVariantList:
    """Read-only alternate contact/identity/address variants for an ACTIVE customer
    (Stage 2). Returns a plain 404 for a missing / soft-deleted / merged-loser id (same
    active-only path as GET /customers/{id}) so no variants are exposed for a non-active
    customer. Active (non-archived) variants only; no create/update/delete in Stage 2."""
    customer = customers_service.get_customer(db, customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    variants = customers_service.list_contact_variants(db, customer)
    return CustomerContactVariantList(
        items=[CustomerContactVariantRead.model_validate(v) for v in variants],
        total=len(variants),
    )


@router.patch("/{customer_id}", response_model=CustomerRead)
def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(can_write),
) -> CustomerRead:
    customer = customers_service.get_customer(db, customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    changed = customers_service.update_customer(
        db, customer, data=payload.model_dump(exclude_unset=True)
    )
    if changed:
        log_activity(
            db,
            activity_type=ActivityType.CUSTOMER_UPDATED,
            description=f"Updated customer {customer.full_name}",
            actor_id=actor.id,
            customer_id=customer.id,
            meta={"changes": changed},
        )
    db.commit()
    db.refresh(customer)
    return CustomerRead.model_validate(customer)


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
) -> None:
    customer = customers_service.get_customer(db, customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    customers_service.soft_delete_customer(db, customer)
    log_activity(
        db,
        activity_type=ActivityType.CUSTOMER_DELETED,
        description=f"Deleted customer {customer.full_name}",
        actor_id=actor.id,
        customer_id=customer.id,
    )
    db.commit()


@router.post("/{loser_id}/merge-into/{winner_id}", response_model=CustomerMergeResult)
def merge_customer(
    loser_id: int,
    winner_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
) -> CustomerMergeResult:
    """Explicitly merge the LOSER customer into the WINNER (B4-2). Admin-only.

    One transaction: repoint every customer FK loser->winner, append the loser's
    notes into the winner's internal_notes, soft-delete the loser (never hard-delete)
    + record the immutable merge pointer, and log a CUSTOMER_MERGED activity. On any
    guard failure nothing is changed (the service raises before mutating; the endpoint
    rolls back and surfaces the mapped status).
    """
    try:
        result = customers_service.merge_customers(
            db, loser_id=loser_id, winner_id=winner_id, actor_id=actor.id
        )
    except customers_service.MergeError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.reason)
    db.commit()
    db.refresh(result["winner"])
    return CustomerMergeResult(
        winner=CustomerRead.model_validate(result["winner"]),
        loser_id=result["loser_id"],
        merged_at=result["merged_at"],
        moved={k: MergeMovedCount(**v) for k, v in result["moved"].items()},
        repointed_import={k: MergeMovedCount(**v) for k, v in result["repointed_import"].items()},
        notes_appended=result["notes_appended"],
    )
