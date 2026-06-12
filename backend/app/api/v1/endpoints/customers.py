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
    CustomerCreate,
    CustomerList,
    CustomerRead,
    CustomerUpdate,
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return CustomerRead.model_validate(customer)


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
