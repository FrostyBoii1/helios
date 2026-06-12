"""User model.

Users authenticate with email + Argon2-hashed password. Each user has exactly
one role, which drives permissions. `is_active` supports admin deactivation
without deletion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.mixins import IntPkMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.role import Role


class User(IntPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"

    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    # NEVER stores plaintext — Argon2 hash only.
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False, index=True)
    role: Mapped["Role"] = relationship(back_populates="users")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<User {self.email}>"
