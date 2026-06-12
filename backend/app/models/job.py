"""Job model.

A job belongs to a customer and carries the operational workflow state: status,
key dates, assigned staff, and links to tasks / activities / documents. Each job
gets a unique, human-friendly case number (e.g. SCS-2026-00001) generated at
creation time (see app.services.case_number).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.enums import JobStatus
from app.models.mixins import IntPkMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.activity import Activity
    from app.models.customer import Customer
    from app.models.document import Document
    from app.models.task import Task
    from app.models.user import User


class Job(IntPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "jobs"

    # Unique, searchable business identifier, e.g. "SCS-2026-00001".
    case_number: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True
    )

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    customer: Mapped["Customer"] = relationship(back_populates="jobs")

    status: Mapped[JobStatus] = mapped_column(
        String(40), default=JobStatus.NEW, nullable=False, index=True
    )

    # Free-form descriptive fields; structured detail can be added incrementally.
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    system_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    install_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # NAS folder for this job's files (relative to NAS_ROOT). See nas service.
    nas_folder_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Key dates
    sale_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    install_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    # People
    salesperson_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    assigned_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    salesperson: Mapped["User | None"] = relationship(foreign_keys=[salesperson_id])
    assigned_user: Mapped["User | None"] = relationship(foreign_keys=[assigned_user_id])

    # Children
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    activities: Mapped[list["Activity"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Job {self.case_number} status={self.status}>"
