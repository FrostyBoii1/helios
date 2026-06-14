"""add jobs details jsonb

Phase 1 of the structured-import rework: add a nullable JSONB ``details`` column
to ``jobs`` to hold structured, grouped import attributes (driven by the code
field registry). Purely additive — existing rows get NULL, and the legacy
text fields (system_details/install_details/approval_details/notes) are left
untouched. No data is migrated into ``details`` here.

Revision ID: c1a2b3d4e5f6
Revises: 91a6e16b2a20
Create Date: 2026-06-14 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: str | None = '91a6e16b2a20'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'details')
