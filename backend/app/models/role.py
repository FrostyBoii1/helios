"""Role model.

Roles are stored as rows so they can carry human-readable descriptions and be
referenced by foreign key from users. The fixed set of role identities lives in
`RoleName`; the seed script ensures one row per enum value exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.mixins import IntPkMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Role(IntPkMixin, TimestampMixin, Base):
    __tablename__ = "roles"

    # Matches a RoleName value, e.g. "admin", "scheduling".
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    users: Mapped[list["User"]] = relationship(back_populates="role")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Role {self.name}>"
