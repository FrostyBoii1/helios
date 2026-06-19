"""make job_label_definitions.key a single UNIQUE index (drift reconcile)

Reconciles a pre-existing model<->DB drift on ``job_label_definitions.key`` that
kept surfacing in ``alembic check`` / autogenerate. The model declares the column
``unique=True, index=True`` (i.e. a single UNIQUE index), but the original Phase-L1
migration (e3c4d5f6a7b8) redundantly created BOTH a unique constraint
(``uq_job_label_definitions_key``) AND a separate NON-unique index
(``ix_job_label_definitions_key``).

Uniqueness was ALREADY enforced (by the unique constraint) and is PRESERVED here:
this only collapses the redundant pair into the single UNIQUE index the model
expects. Verified before applying: zero duplicate ``key`` values exist. DDL only on
the label catalogue — NO business data is touched (the seeded rows are unchanged),
and nothing references ``key`` as a foreign-key target (FKs point at ``id``).

Reversible: downgrade restores the original split (a unique constraint + a separate
non-unique index).

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-06-19 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f0a1b2c3d4e5'
down_revision: str | None = 'e9f0a1b2c3d4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Collapse the redundant (non-unique index + unique constraint) into the single
    # UNIQUE index the model declares (`key` is `unique=True, index=True`). Uniqueness
    # is preserved throughout — the create at the end re-establishes it.
    op.drop_index(op.f('ix_job_label_definitions_key'), table_name='job_label_definitions')
    op.drop_constraint(op.f('uq_job_label_definitions_key'), 'job_label_definitions', type_='unique')
    op.create_index(
        op.f('ix_job_label_definitions_key'), 'job_label_definitions', ['key'], unique=True
    )


def downgrade() -> None:
    # Restore the original Phase-L1 split: a unique constraint + a non-unique index.
    op.drop_index(op.f('ix_job_label_definitions_key'), table_name='job_label_definitions')
    op.create_unique_constraint(
        op.f('uq_job_label_definitions_key'), 'job_label_definitions', ['key']
    )
    op.create_index(
        op.f('ix_job_label_definitions_key'), 'job_label_definitions', ['key'], unique=False
    )
