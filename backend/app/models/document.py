"""Document / file metadata model.

Files themselves live on the NAS or configured storage directory — NEVER as
blobs in the database. This table stores metadata and a relative path reference
so the app can locate, preview, download, and permission-check files. If a path
is missing on disk, the app surfaces a broken-link state rather than failing
silently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.mixins import IntPkMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.job import Job
    from app.models.user import User


class Document(IntPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "documents"

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Path RELATIVE to NAS_ROOT or STORAGE_ROOT — never an absolute host path.
    relative_path: Mapped[str] = mapped_column(String(700), nullable=False)
    # Which root the relative_path is anchored to: "nas" | "storage".
    storage_root: Mapped[str] = mapped_column(String(20), default="nas", nullable=False)

    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Optional categorisation, e.g. "contract", "invoice", "msb_photo".
    category: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)

    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True, index=True
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id"), nullable=True, index=True
    )
    uploaded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    job: Mapped["Job | None"] = relationship(back_populates="documents")
    customer: Mapped["Customer | None"] = relationship()
    uploaded_by: Mapped["User | None"] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Document {self.id} {self.original_filename!r}>"
