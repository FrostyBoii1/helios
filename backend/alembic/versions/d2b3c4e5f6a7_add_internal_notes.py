"""add internal_notes to customers and jobs

Phase A (notes separation): add a nullable ``internal_notes`` Text column to
``customers`` and ``jobs`` for manual staff-communication notes, kept distinct
from the legacy/imported ``notes`` blob. Purely additive — existing rows get
NULL and no data is migrated or touched.

Revision ID: d2b3c4e5f6a7
Revises: c1a2b3d4e5f6
Create Date: 2026-06-15 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd2b3c4e5f6a7'
down_revision: str | None = 'c1a2b3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('customers', sa.Column('internal_notes', sa.Text(), nullable=True))
    op.add_column('jobs', sa.Column('internal_notes', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'internal_notes')
    op.drop_column('customers', 'internal_notes')
