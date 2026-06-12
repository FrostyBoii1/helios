"""Activity / timeline model.

The activity table is APPEND-ONLY: it records what happened, who did it, and
when. Rows are never updated or overwritten in normal operation — each important
action creates a new entry. This backs both the per-customer/job timeline and
the system audit log.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.enums import ActivityType
from app.models.mixins import IntPkMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.job import Job
    from app.models.user import User


class Activity(IntPkMixin, TimestampMixin, Base):
    """An immutable timeline/audit entry. No soft-delete: history is permanent."""

    __tablename__ = "activities"

    activity_type: Mapped[ActivityType] = mapped_column(
        String(40), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Structured before/after or contextual detail (e.g. {"from": "...", "to": "..."}).
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # The actor. Nullable because some events are system-generated.
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )

    # What the activity is about (either/both may be set).
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True, index=True
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id"), nullable=True, index=True
    )

    actor: Mapped["User | None"] = relationship()
    customer: Mapped["Customer | None"] = relationship()
    job: Mapped["Job | None"] = relationship(back_populates="activities")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Activity {self.activity_type} job={self.job_id} customer={self.customer_id}>"
