"""add edit markers to customer_contact_variants (editable Known Customer Details)

Adds two nullable columns so a Known Customer Detail (CustomerContactVariant) can be
EDITED as real customer information while keeping its provenance:

  * edited_at      — NULL => never edited; set => a user edited this variant's fields.
  * edited_by_id   — FK users.id; who made the last edit (audit), nullable.

Behaviour these enable (no data backfill — every existing row is NULL/unedited):
  * an admin PATCH on a variant sets edited_at/edited_by_id (any source_type);
  * reversing the originating import row archives ONLY UNEDITED import_row variants —
    an EDITED variant is preserved as curated customer detail.

Additive + reversible: only adds the two nullable columns + the edited_by_id FK; no
existing column/data is touched, no index churn.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-19 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: str | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'customer_contact_variants',
        sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'customer_contact_variants',
        sa.Column('edited_by_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        op.f('fk_customer_contact_variants_edited_by_id_users'),
        'customer_contact_variants', 'users',
        ['edited_by_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f('fk_customer_contact_variants_edited_by_id_users'),
        'customer_contact_variants', type_='foreignkey',
    )
    op.drop_column('customer_contact_variants', 'edited_by_id')
    op.drop_column('customer_contact_variants', 'edited_at')
