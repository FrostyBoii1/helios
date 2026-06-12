"""Task model.

Tasks are assignable units of work linked to a customer and/or job. They carry
an owner (assignee), status, priority, due date, and completion metadata so the
system can show outstanding/overdue work and a historical completion log.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.enums import TaskPriority, TaskStatus
from app.models.mixins import IntPkMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.job import Job
    from app.models.user import User


class Task(IntPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "tasks"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[TaskStatus] = mapped_column(
        String(20), default=TaskStatus.OPEN, nullable=False, index=True
    )
    priority: Mapped[TaskPriority] = mapped_column(
        String(20), default=TaskPriority.NORMAL, nullable=False, index=True
    )

    due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Links — a task may be attached to a customer, a job, or both.
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True, index=True
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id"), nullable=True, index=True
    )

    # Ownership / accountability
    assigned_to_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # Completion log
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    job: Mapped["Job | None"] = relationship(back_populates="tasks")
    customer: Mapped["Customer | None"] = relationship()
    assigned_to: Mapped["User | None"] = relationship(foreign_keys=[assigned_to_id])
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_id])
    completed_by: Mapped["User | None"] = relationship(foreign_keys=[completed_by_id])

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Task {self.id} {self.title!r} status={self.status}>"
