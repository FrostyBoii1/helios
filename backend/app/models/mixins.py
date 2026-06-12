"""Reusable model mixins: surrogate PK, timestamps, soft-delete.

These encode cross-cutting rules from the spec:
  * Every business record carries created/updated timestamps (auditability).
  * Business-critical records use soft deletes (`deleted_at`) rather than hard
    deletion, so records remain recoverable.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column


class IntPkMixin:
    """Integer surrogate primary key."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


class TimestampMixin:
    """created_at / updated_at, maintained by the database server clock."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Soft delete marker. NULL => active; set => logically deleted."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
