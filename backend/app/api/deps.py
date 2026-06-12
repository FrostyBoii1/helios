"""Shared FastAPI dependencies: DB session, current user, role guards.

These enforce protected routes and role-based permissions. `get_current_user`
validates the bearer access token; `require_roles(...)` builds a dependency that
asserts the authenticated user holds one of the allowed roles.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models.enums import RoleName
from app.models.user import User
from app.services.users import get_user

# tokenUrl is the login endpoint; used by the OpenAPI "Authorize" button.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")

_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = decode_token(token, expected_type="access")
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise _CREDENTIALS_EXC

    user = get_user(db, user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_EXC
    return user


def require_roles(*roles: RoleName) -> Callable[[User], User]:
    """Return a dependency asserting the current user has one of `roles`."""
    allowed: set[str] = {r.value for r in roles}

    def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.name not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user

    return _dependency


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Convenience guard for admin-only routes."""
    if current_user.role.name != RoleName.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


# Re-exported for readability in endpoint signatures.
def roles_in(roles: Iterable[RoleName]) -> Callable[[User], User]:
    return require_roles(*roles)
