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


# --------------------------------------------------------------------------- #
# Stage 2: customer alternate contact/address variants (read-only)
# --------------------------------------------------------------------------- #
class CustomerContactVariantRead(BaseModel):
    """A read view of one alternate contact/identity/address set for a customer.
    `email` is a plain string (a stored variant is not re-validated as an EmailStr)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    label: str | None
    display_name: str | None
    email: str | None
    phone: str | None
    address_line1: str | None
    address_line2: str | None
    suburb: str | None
    state: str | None
    postcode: str | None
    source_type: str
    # The source FK ids (source_customer_id / source_import_row_id / source_document_id)
    # are intentionally NOT exposed in the read API: a merged loser's id must stay hidden
    # (it would otherwise be enumerable here once merge capture populates it). They live on
    # the table for backend/audit use only; source_type is the non-identifying label.
    note: str | None
    created_at: datetime
    updated_at: datetime


class CustomerContactVariantList(BaseModel):
    items: list[CustomerContactVariantRead]
    total: int


class CustomerContactVariantCreate(BaseModel):
    """Stage 4 manual-add input. `source_type` is forced to 'manual' server-side and the
    source FK ids are NOT accepted from the client (not declared here, so any are dropped).
    At least one DETAIL field (name/email/phone/address/suburb/state/postcode) must be
    non-blank — a label or note alone does not create a variant (enforced in the service).
    Max lengths mirror the table columns."""

    label: str | None = Field(default=None, max_length=120)
    display_name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    suburb: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=60)
    postcode: str | None = Field(default=None, max_length=20)
    note: str | None = None
