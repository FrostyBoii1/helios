"""Customer schemas: create, partial update, read, and paginated list."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CustomerBase(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    suburb: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=60)
    postcode: str | None = Field(default=None, max_length=20)
    notes: str | None = None
    internal_notes: str | None = None


class CustomerCreate(CustomerBase):
    """Payload to create a customer (full_name required; rest optional)."""


class CustomerUpdate(BaseModel):
    """Partial update — every field optional."""

    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    suburb: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=60)
    postcode: str | None = Field(default=None, max_length=20)
    notes: str | None = None
    internal_notes: str | None = None


class CustomerRead(CustomerBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class CustomerList(BaseModel):
    """Paginated list envelope."""

    items: list[CustomerRead]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------------------- #
# B4-2: customer merge result
# --------------------------------------------------------------------------- #
class MergeMovedCount(BaseModel):
    """How many rows of one kind moved/repointed, with their ids. ``ids`` is empty
    for kinds reported count-only (e.g. moved activities, which can be bulk)."""

    count: int
    ids: list[int] = Field(default_factory=list)


class CustomerMergeResult(BaseModel):
    """Summary of an explicit admin customer merge (loser -> winner)."""

    winner: CustomerRead
    loser_id: int
    merged_at: datetime
    moved: dict[str, MergeMovedCount]            # jobs / tasks / documents / activities
    repointed_import: dict[str, MergeMovedCount]  # rows_committed / rows_resolved / groups_committed
    notes_appended: bool
