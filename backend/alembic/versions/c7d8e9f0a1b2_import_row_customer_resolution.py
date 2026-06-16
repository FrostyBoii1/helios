"""add import_rows manual same-customer resolution columns (B2-1)

Additive, nullable columns on ``import_rows`` that store a reviewer's pre-commit
intent for THIS row's customer:
  * customer_resolution_mode NULL       -> unresolved; commit creates a new
                                           customer (current default behaviour);
  * customer_resolution_mode 'new'      -> reviewer explicitly chose a new customer
                                           (resolved_customer_id stays NULL);
  * customer_resolution_mode 'existing' -> attach the job to the EXISTING customer
                                           in resolved_customer_id.

Storage only (B2-1): commit-to-live / commit-preview / reverse do NOT read these
yet (that is B2-2). Schema-only, additive, reversible. Touches NO existing data
(every existing row gets NULLs, preserving current behaviour) and NO business
data (customers/jobs/activities). The mode/resolved_customer_id invariant is
enforced in the import review service (no DB CHECK, matching existing migration
style which uses none).

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-06-17 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c7d8e9f0a1b2'
down_revision: str | None = 'b6c7d8e9f0a1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('import_rows', sa.Column('resolved_customer_id', sa.Integer(), nullable=True))
    op.add_column('import_rows', sa.Column('customer_resolution_mode', sa.String(length=20), nullable=True))
    op.add_column('import_rows', sa.Column('customer_resolution_reason', sa.Text(), nullable=True))
    op.add_column('import_rows', sa.Column('resolved_by_id', sa.Integer(), nullable=True))
    op.add_column('import_rows', sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        op.f('ix_import_rows_resolved_customer_id'),
        'import_rows', ['resolved_customer_id'], unique=False,
    )
    op.create_foreign_key(
        op.f('fk_import_rows_resolved_customer_id_customers'),
        'import_rows', 'customers', ['resolved_customer_id'], ['id'],
    )
    op.create_foreign_key(
        op.f('fk_import_rows_resolved_by_id_users'),
        'import_rows', 'users', ['resolved_by_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(op.f('fk_import_rows_resolved_by_id_users'), 'import_rows', type_='foreignkey')
    op.drop_constraint(
        op.f('fk_import_rows_resolved_customer_id_customers'), 'import_rows', type_='foreignkey'
    )
    op.drop_index(op.f('ix_import_rows_resolved_customer_id'), table_name='import_rows')
    op.drop_column('import_rows', 'resolved_at')
    op.drop_column('import_rows', 'resolved_by_id')
    op.drop_column('import_rows', 'customer_resolution_reason')
    op.drop_column('import_rows', 'customer_resolution_mode')
    op.drop_column('import_rows', 'resolved_customer_id')
