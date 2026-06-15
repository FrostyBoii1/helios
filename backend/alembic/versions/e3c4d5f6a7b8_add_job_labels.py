"""add job label definitions + assignments (Phase L1)

Creates the operational-flag foundation:
  * ``job_label_definitions`` — catalogue of labels (soft-deletable), seeded with
    the default system + operational presets.
  * ``job_label_assignments`` — many-to-many Job<->definition link with provenance
    and a unique (job_id, label_id) constraint.

Additive + reversible. Does NOT touch any existing business data (customers,
jobs, activities) — only creates the two new tables and inserts the seed presets.

Revision ID: e3c4d5f6a7b8
Revises: d2b3c4e5f6a7
Create Date: 2026-06-15 10:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e3c4d5f6a7b8'
down_revision: str | None = 'd2b3c4e5f6a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Seed presets. (key, name, category, color, is_system, is_auto, sort_order).
# Approval + decommission are system+auto (locked, auto-assigned in Phase L3);
# the operational labels are user-manageable presets.
SEED_LABELS = [
    ("approval_approved", "Approval approved", "approval", "green", True, True, 10),
    ("approval_pending", "Approval pending", "approval", "amber", True, True, 20),
    ("decommission_pre_existing", "Decommission pre-existing", "system", "red", True, True, 30),
    ("needs_maintenance", "Needs maintenance", "operational", "orange", False, False, 40),
    ("warranty_issue", "Warranty issue", "operational", "orange", False, False, 50),
    ("battery_only", "Battery-only", "operational", "blue", False, False, 60),
    ("existing_solar", "Existing solar", "operational", "blue", False, False, 70),
    ("awaiting_documents", "Awaiting documents", "operational", "slate", False, False, 80),
]


def upgrade() -> None:
    op.create_table(
        'job_label_definitions',
        sa.Column('key', sa.String(length=60), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('color', sa.String(length=40), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_system', sa.Boolean(), nullable=False),
        sa.Column('is_auto', sa.Boolean(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_job_label_definitions')),
        sa.UniqueConstraint('key', name=op.f('uq_job_label_definitions_key')),
    )
    op.create_index(op.f('ix_job_label_definitions_category'), 'job_label_definitions', ['category'], unique=False)
    op.create_index(op.f('ix_job_label_definitions_deleted_at'), 'job_label_definitions', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_job_label_definitions_key'), 'job_label_definitions', ['key'], unique=False)
    op.create_index(op.f('ix_job_label_definitions_sort_order'), 'job_label_definitions', ['sort_order'], unique=False)

    op.create_table(
        'job_label_assignments',
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('label_id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('assigned_by_id', sa.Integer(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['assigned_by_id'], ['users.id'], name=op.f('fk_job_label_assignments_assigned_by_id_users')),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], name=op.f('fk_job_label_assignments_job_id_jobs')),
        sa.ForeignKeyConstraint(['label_id'], ['job_label_definitions.id'], name=op.f('fk_job_label_assignments_label_id_job_label_definitions')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_job_label_assignments')),
        sa.UniqueConstraint('job_id', 'label_id', name='uq_job_label_assignments_job_label'),
    )
    op.create_index(op.f('ix_job_label_assignments_job_id'), 'job_label_assignments', ['job_id'], unique=False)
    op.create_index(op.f('ix_job_label_assignments_label_id'), 'job_label_assignments', ['label_id'], unique=False)

    # Seed the default labels (created_at/updated_at fall back to the now() server
    # default; id autoincrements). Idempotent at the migration level because the
    # migration runs exactly once.
    label_table = sa.table(
        'job_label_definitions',
        sa.column('key', sa.String),
        sa.column('name', sa.String),
        sa.column('category', sa.String),
        sa.column('color', sa.String),
        sa.column('description', sa.Text),
        sa.column('is_system', sa.Boolean),
        sa.column('is_auto', sa.Boolean),
        sa.column('sort_order', sa.Integer),
    )
    op.bulk_insert(
        label_table,
        [
            {
                "key": key, "name": name, "category": category, "color": color,
                "description": None, "is_system": is_system, "is_auto": is_auto,
                "sort_order": sort_order,
            }
            for (key, name, category, color, is_system, is_auto, sort_order) in SEED_LABELS
        ],
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_job_label_assignments_label_id'), table_name='job_label_assignments')
    op.drop_index(op.f('ix_job_label_assignments_job_id'), table_name='job_label_assignments')
    op.drop_table('job_label_assignments')
    op.drop_index(op.f('ix_job_label_definitions_sort_order'), table_name='job_label_definitions')
    op.drop_index(op.f('ix_job_label_definitions_key'), table_name='job_label_definitions')
    op.drop_index(op.f('ix_job_label_definitions_deleted_at'), table_name='job_label_definitions')
    op.drop_index(op.f('ix_job_label_definitions_category'), table_name='job_label_definitions')
    op.drop_table('job_label_definitions')
