"""add customers merge-pointer storage columns (B4-1)

Additive, nullable storage that records an explicit admin merge of one customer
(the LOSER) into another (the WINNER):
  * merged_into_customer_id -> self-FK to customers.id. NULL => live / never
    merged; set => this customer was merged into that winner. Immutable once set
    (B4 owner decision). NO ACTION FK (Postgres default) so soft-deleting a loser
    never cascades onto its winner.
  * merged_at -> timestamptz of the merge.

STORAGE ONLY (B4-1). There is NO merge execution, NO endpoint, NO reassignment of
jobs/tasks/documents/activities/import links, and NO soft-delete-on-merge yet, and
NO read / search / import / commit / reverse path reads these columns (that is
B4-2+). Schema-only, additive, reversible. NO backfill: every existing customer
keeps NULL for both columns, preserving current behaviour. Touches NO business
data (customers/jobs/activities are unchanged).

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-06-18 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e9f0a1b2c3d4'
down_revision: str | None = 'd8e9f0a1b2c3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('customers', sa.Column('merged_into_customer_id', sa.Integer(), nullable=True))
    op.add_column('customers', sa.Column('merged_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        op.f('ix_customers_merged_into_customer_id'),
        'customers', ['merged_into_customer_id'], unique=False,
    )
    op.create_foreign_key(
        op.f('fk_customers_merged_into_customer_id_customers'),
        'customers', 'customers', ['merged_into_customer_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f('fk_customers_merged_into_customer_id_customers'), 'customers', type_='foreignkey'
    )
    op.drop_index(op.f('ix_customers_merged_into_customer_id'), table_name='customers')
    op.drop_column('customers', 'merged_at')
    op.drop_column('customers', 'merged_into_customer_id')
