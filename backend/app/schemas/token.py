"""Token-related schemas."""

from __future__ import annotations

from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPayload(BaseModel):
    """Decoded JWT contents we care about."""

    sub: str | None = None
    type: str | None = None
