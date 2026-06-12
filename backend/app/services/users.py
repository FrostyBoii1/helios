"""User-related domain logic: lookup, authentication, creation.

Kept separate from the API layer so it can be reused (e.g. by the seed script)
and unit-tested without HTTP.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.security import hash_password, verify_password
from app.models.enums import RoleName
from app.models.role import Role
from app.models.user import User


def get_user_by_email(db: Session, email: str) -> User | None:
    stmt = (
        select(User)
        .options(joinedload(User.role))
        .where(User.email == email, User.deleted_at.is_(None))
    )
    return db.scalar(stmt)


def get_user(db: Session, user_id: int) -> User | None:
    stmt = (
        select(User)
        .options(joinedload(User.role))
        .where(User.id == user_id, User.deleted_at.is_(None))
    )
    return db.scalar(stmt)


def get_role(db: Session, role: RoleName) -> Role | None:
    return db.scalar(select(Role).where(Role.name == role.value))


def authenticate(db: Session, *, email: str, password: str) -> User | None:
    """Return the user if credentials are valid and the account is active."""
    user = get_user_by_email(db, email)
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_user(
    db: Session,
    *,
    full_name: str,
    email: str,
    password: str,
    role: RoleName,
    is_active: bool = True,
) -> User:
    """Create a user with an Argon2-hashed password. Adds (does not commit)."""
    role_row = get_role(db, role)
    if role_row is None:
        raise ValueError(f"Role '{role.value}' does not exist. Run the seed script.")

    user = User(
        full_name=full_name,
        email=email,
        hashed_password=hash_password(password),
        role_id=role_row.id,
        is_active=is_active,
    )
    db.add(user)
    return user
