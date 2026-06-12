"""User management endpoints (admin-only).

Demonstrates the full feature pattern the rest of the app follows:
validation (schemas) -> permission check (require_admin) -> DB write ->
activity logging -> typed response.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, require_admin
from app.core.security import hash_password
from app.db.session import get_db
from app.models.enums import ActivityType, RoleName
from app.models.user import User
from app.schemas.user import (
    PasswordReset,
    UserCreate,
    UserRead,
    UserSelectable,
    UserUpdate,
)
from app.services.activity import log_activity
from app.services.users import create_user, get_user, get_user_by_email, get_role

router = APIRouter()


@router.get("/selectable", response_model=list[UserSelectable])
def list_selectable_users(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[UserSelectable]:
    """Active users for assignee dropdowns — any authenticated user may read.

    Lightweight shape only (id / full_name / role); no email or account data.
    """
    stmt = (
        select(User)
        .options(joinedload(User.role))
        .where(User.is_active.is_(True), User.deleted_at.is_(None))
        .order_by(User.full_name)
    )
    return [
        UserSelectable(id=u.id, full_name=u.full_name, role=u.role.name)
        for u in db.scalars(stmt).all()
    ]


@router.get("", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[User]:
    stmt = (
        select(User)
        .options(joinedload(User.role))
        .where(User.deleted_at.is_(None))
        .order_by(User.full_name)
    )
    return list(db.scalars(stmt).all())


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_new_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    if get_user_by_email(db, payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )
    try:
        user = create_user(
            db,
            full_name=payload.full_name,
            email=payload.email,
            password=payload.password,
            role=payload.role,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    db.flush()  # assign user.id before logging
    log_activity(
        db,
        activity_type=ActivityType.USER_CREATED,
        description=f"Created user {user.email} with role {payload.role.value}",
        actor_id=admin.id,
        meta={"user_id": user.id, "role": payload.role.value},
    )
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserRead)
def get_single_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> User:
    user = get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    user = get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    data = payload.model_dump(exclude_unset=True)

    if "email" in data and data["email"] != user.email:
        existing = get_user_by_email(db, data["email"])
        if existing is not None and existing.id != user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists",
            )
        user.email = data["email"]
    if "full_name" in data:
        user.full_name = data["full_name"]
    if "is_active" in data:
        user.is_active = data["is_active"]
    if "role" in data and data["role"] is not None:
        role = get_role(db, RoleName(data["role"]))
        if role is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown role")
        user.role_id = role.id

    log_activity(
        db,
        activity_type=ActivityType.USER_UPDATED,
        description=f"Updated user {user.email}",
        actor_id=admin.id,
        meta={"user_id": user.id, "changes": list(data.keys())},
    )
    db.commit()
    db.refresh(user)
    return user


@router.post(
    "/{user_id}/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def reset_password(
    user_id: int,
    payload: PasswordReset,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> None:
    user = get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.hashed_password = hash_password(payload.new_password)
    log_activity(
        db,
        activity_type=ActivityType.USER_UPDATED,
        description=f"Reset password for {user.email}",
        actor_id=admin.id,
        meta={"user_id": user.id},
    )
    db.commit()


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> None:
    """Deactivate (soft) a user account. Admins cannot deactivate themselves."""
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account",
        )
    user = get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.is_active = False
    log_activity(
        db,
        activity_type=ActivityType.USER_UPDATED,
        description=f"Deactivated user {user.email}",
        actor_id=admin.id,
        meta={"user_id": user.id},
    )
    db.commit()
