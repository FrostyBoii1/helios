"""add import_customer_groups + import_rows.customer_group_id (B3-2)

Pending-row grouping storage: a reviewer can mark several pending import rows as
ONE future customer. The new ``import_customer_groups`` table holds the group
(with its primary row + audit), and ``import_rows.customer_group_id`` records
membership. STORAGE ONLY — commit-to-live / commit-preview / reverse do NOT read
these yet (that is B3-3). ``import_customer_groups.committed_customer_id`` is
added now as nullable storage for B3-3 but is unused in B3-2.

Additive + reversible. No backfill (every existing row keeps customer_group_id
NULL, preserving current behaviour) and NO business data touched.

The two tables reference each other (groups.primary_row_id -> rows.id and
rows.customer_group_id -> groups.id): create the group table first (it references
the EXISTING import_rows), then add the row column + FK to the new group table.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-06-17 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd8e9f0a1b2c3'
down_revision: str | None = 'c7d8e9f0a1b2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'import_customer_groups',
        sa.Column('batch_id', sa.Integer(), nullable=False),
        sa.Column('primary_row_id', sa.Integer(), nullable=False),
        sa.Column('committed_customer_id', sa.Integer(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['batch_id'], ['import_batches.id'],
            name=op.f('fk_import_customer_groups_batch_id_import_batches'),
        ),
        sa.ForeignKeyConstraint(
            ['primary_row_id'], ['import_rows.id'],
            name=op.f('fk_import_customer_groups_primary_row_id_import_rows'),
        ),
        sa.ForeignKeyConstraint(
            ['committed_customer_id'], ['customers.id'],
            name=op.f('fk_import_customer_groups_committed_customer_id_customers'),
        ),
        sa.ForeignKeyConstraint(
            ['created_by_id'], ['users.id'],
            name=op.f('fk_import_customer_groups_created_by_id_users'),
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_import_customer_groups')),
    )
    op.create_index(
        op.f('ix_import_customer_groups_batch_id'), 'import_customer_groups', ['batch_id'], unique=False
    )
    op.create_index(
        op.f('ix_import_customer_groups_primary_row_id'),
        'import_customer_groups', ['primary_row_id'], unique=False,
    )
    op.add_column('import_rows', sa.Column('customer_group_id', sa.Integer(), nullable=True))
    op.create_index(
        op.f('ix_import_rows_customer_group_id'), 'import_rows', ['customer_group_id'], unique=False
    )
    op.create_foreign_key(
        op.f('fk_import_rows_customer_group_id_import_customer_groups'),
        'import_rows', 'import_customer_groups', ['customer_group_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f('fk_import_rows_customer_group_id_import_customer_groups'),
        'import_rows', type_='foreignkey',
    )
    op.drop_index(op.f('ix_import_rows_customer_group_id'), table_name='import_rows')
    op.drop_column('import_rows', 'customer_group_id')
    op.drop_index(op.f('ix_import_customer_groups_primary_row_id'), table_name='import_customer_groups')
    op.drop_index(op.f('ix_import_customer_groups_batch_id'), table_name='import_customer_groups')
    op.drop_table('import_customer_groups')
