"""add import_rows.internal_notes_override (editable pre-commit internal notes)

Additive, nullable Text column on ``import_rows`` so a reviewer can override what
import commit seeds into ``Job.internal_notes``:
  * NULL  -> use the generated build_imported_notes default (existing behavior);
  * ""    -> commit blank internal notes;
  * text  -> commit that text verbatim.

Schema-only, additive, and reversible. Touches NO existing data (the column
defaults to NULL on every existing row, which preserves the current generated
behavior) and NO business data (customers/jobs/activities).

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-06-16 12:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b6c7d8e9f0a1'
down_revision: str | None = 'a5b6c7d8e9f0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'import_rows',
        sa.Column('internal_notes_override', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('import_rows', 'internal_notes_override')
