"""User schemas: creation (admin only), update, and read representations."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import RoleName
from app.schemas.role import RoleRead


class UserBase(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr


class UserCreate(UserBase):
    """Payload an admin sends to create an account."""

    password: str = Field(..., min_length=8, max_length=128)
    role: RoleName
    is_active: bool = True


class UserUpdate(BaseModel):
    """Partial update. All fields optional."""

    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    role: RoleName | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    """Admin-initiated password reset for a user."""

    new_password: str = Field(..., min_length=8, max_length=128)


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    role: RoleRead
    created_at: datetime
