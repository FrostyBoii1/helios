"""Security primitives: password hashing (Argon2) and JWT tokens.

Argon2 is used for password hashing per the project spec. JWTs are signed with
HS256 using SECRET_KEY. Access tokens are short-lived; refresh tokens are longer
and carry a distinct `type` claim so they cannot be used as access tokens.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings

# Argon2id with library defaults (sensible memory/time cost for a web app).
_password_hasher = PasswordHasher()

TokenType = Literal["access", "refresh"]


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
def hash_password(plain_password: str) -> str:
    """Return an Argon2 hash for the given plaintext password."""
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored Argon2 hash."""
    try:
        return _password_hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(hashed_password: str) -> bool:
    """True if the stored hash should be upgraded (e.g. cost params changed)."""
    try:
        return _password_hasher.check_needs_rehash(hashed_password)
    except InvalidHashError:
        return True


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def _create_token(subject: str | int, token_type: TokenType, expires_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(subject: str | int) -> str:
    return _create_token(subject, "access", settings.ACCESS_TOKEN_EXPIRE_MINUTES)


def create_refresh_token(subject: str | int) -> str:
    return _create_token(subject, "refresh", settings.REFRESH_TOKEN_EXPIRE_MINUTES)


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """Decode and validate a JWT, enforcing the expected token type.

    Raises jwt.InvalidTokenError (or a subclass) on any failure.
    """
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("Unexpected token type")
    return payload
