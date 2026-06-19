"""add customer_contact_variants (Stage 2 — storage foundation)

Creates the ``customer_contact_variants`` table: an alternate set of customer-level
identity / contact / address details for a LIVE customer, for when the same real
customer is known by a different name / email / phone / address (merged duplicate,
import row, manual entry, or document). The primary ``Customer`` columns stay
authoritative; variants are additive read-only context.

STORAGE ONLY (Stage 2). Nothing writes variants yet — merge capture, import/manual
capture, backfill, promote-to-primary, and edit/archive are later stages. Additive +
reversible: only creates the new table (with its FKs/indexes); NO data backfill and NO
existing table/data touched.

Revision ID: a1b2c3d4e5f6
Revises: f0a1b2c3d4e5
Create Date: 2026-06-19 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = 'f0a1b2c3d4e5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'customer_contact_variants',
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=True),
        sa.Column('display_name', sa.String(length=160), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=40), nullable=True),
        sa.Column('address_line1', sa.String(length=255), nullable=True),
        sa.Column('address_line2', sa.String(length=255), nullable=True),
        sa.Column('suburb', sa.String(length=120), nullable=True),
        sa.Column('state', sa.String(length=60), nullable=True),
        sa.Column('postcode', sa.String(length=20), nullable=True),
        sa.Column('source_type', sa.String(length=20), nullable=False),
        sa.Column('source_customer_id', sa.Integer(), nullable=True),
        sa.Column('source_import_row_id', sa.Integer(), nullable=True),
        sa.Column('source_document_id', sa.Integer(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ['customer_id'], ['customers.id'],
            name=op.f('fk_customer_contact_variants_customer_id_customers'),
        ),
        sa.ForeignKeyConstraint(
            ['source_customer_id'], ['customers.id'],
            name=op.f('fk_customer_contact_variants_source_customer_id_customers'),
        ),
        sa.ForeignKeyConstraint(
            ['source_import_row_id'], ['import_rows.id'],
            name=op.f('fk_customer_contact_variants_source_import_row_id_import_rows'),
        ),
        sa.ForeignKeyConstraint(
            ['source_document_id'], ['documents.id'],
            name=op.f('fk_customer_contact_variants_source_document_id_documents'),
        ),
        sa.ForeignKeyConstraint(
            ['created_by_id'], ['users.id'],
            name=op.f('fk_customer_contact_variants_created_by_id_users'),
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_customer_contact_variants')),
    )
    op.create_index(
        op.f('ix_customer_contact_variants_customer_id'),
        'customer_contact_variants', ['customer_id'], unique=False,
    )
    op.create_index(
        op.f('ix_customer_contact_variants_source_type'),
        'customer_contact_variants', ['source_type'], unique=False,
    )
    op.create_index(
        op.f('ix_customer_contact_variants_deleted_at'),
        'customer_contact_variants', ['deleted_at'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_customer_contact_variants_deleted_at'), table_name='customer_contact_variants')
    op.drop_index(op.f('ix_customer_contact_variants_source_type'), table_name='customer_contact_variants')
    op.drop_index(op.f('ix_customer_contact_variants_customer_id'), table_name='customer_contact_variants')
    op.drop_table('customer_contact_variants')
