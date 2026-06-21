"""add hardware catalogue + aliases (Hardware Parser lane, Stage 1 — storage foundation)

Creates the DB-backed canonical hardware catalogue and its parser aliases:

  * ``hardware_catalogue`` — canonical hardware (inverter / battery / panel / metering),
    keyed by a stable ``spec_id`` from the curated spec; soft-deletable; with type-specific
    fields (phases / nominal_kw / capacity_kwh / wattage_w), ambiguous-panel ``model_options``,
    extra ``attributes`` JSON, and ``spec_source`` provenance.
  * ``hardware_aliases`` — matchable parser aliases (exact / loose / case_sensitive) for a
    catalogue entry; soft-deletable; unique per (hardware_id, alias, alias_type).

STORAGE ONLY (Stage 1). The seed (``app.hardware.seed``) populates these from the tracked
YAML; nothing reads them yet — no parser runtime, no Settings UI, no import wiring, no Job
behaviour. Additive + reversible: only creates the two new tables (+ their FKs/indexes); no
existing table/data is touched, no backfill.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-20 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: str | None = 'b2c3d4e5f6a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'hardware_catalogue',
        sa.Column('spec_id', sa.String(length=120), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('canonical_model', sa.String(length=255), nullable=True),
        sa.Column('display_name', sa.String(length=255), nullable=True),
        sa.Column('brand', sa.String(length=160), nullable=True),
        sa.Column('phases', sa.String(length=30), nullable=True),
        sa.Column('nominal_kw', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('capacity_kwh', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('wattage_w', sa.Integer(), nullable=True),
        sa.Column('model_options', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('attributes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('spec_source', sa.String(length=80), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ['created_by_id'], ['users.id'],
            name=op.f('fk_hardware_catalogue_created_by_id_users'),
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_hardware_catalogue')),
        sa.UniqueConstraint('spec_id', name=op.f('uq_hardware_catalogue_spec_id')),
    )
    op.create_index(
        op.f('ix_hardware_catalogue_category'), 'hardware_catalogue', ['category'], unique=False,
    )
    op.create_index(
        op.f('ix_hardware_catalogue_brand'), 'hardware_catalogue', ['brand'], unique=False,
    )
    op.create_index(
        op.f('ix_hardware_catalogue_deleted_at'), 'hardware_catalogue', ['deleted_at'], unique=False,
    )

    op.create_table(
        'hardware_aliases',
        sa.Column('hardware_id', sa.Integer(), nullable=False),
        sa.Column('alias', sa.String(length=255), nullable=False),
        sa.Column('alias_type', sa.String(length=20), nullable=False),
        sa.Column('confidence_override', sa.String(length=40), nullable=True),
        sa.Column('decision_log_id', sa.String(length=120), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ['hardware_id'], ['hardware_catalogue.id'],
            name=op.f('fk_hardware_aliases_hardware_id_hardware_catalogue'),
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_hardware_aliases')),
        sa.UniqueConstraint(
            'hardware_id', 'alias', 'alias_type',
            name=op.f('uq_hardware_aliases_hardware_id'),
        ),
    )
    op.create_index(
        op.f('ix_hardware_aliases_hardware_id'), 'hardware_aliases', ['hardware_id'], unique=False,
    )
    op.create_index(
        op.f('ix_hardware_aliases_alias'), 'hardware_aliases', ['alias'], unique=False,
    )
    op.create_index(
        op.f('ix_hardware_aliases_alias_type'), 'hardware_aliases', ['alias_type'], unique=False,
    )
    op.create_index(
        op.f('ix_hardware_aliases_deleted_at'), 'hardware_aliases', ['deleted_at'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_hardware_aliases_deleted_at'), table_name='hardware_aliases')
    op.drop_index(op.f('ix_hardware_aliases_alias_type'), table_name='hardware_aliases')
    op.drop_index(op.f('ix_hardware_aliases_alias'), table_name='hardware_aliases')
    op.drop_index(op.f('ix_hardware_aliases_hardware_id'), table_name='hardware_aliases')
    op.drop_table('hardware_aliases')
    op.drop_index(op.f('ix_hardware_catalogue_deleted_at'), table_name='hardware_catalogue')
    op.drop_index(op.f('ix_hardware_catalogue_brand'), table_name='hardware_catalogue')
    op.drop_index(op.f('ix_hardware_catalogue_category'), table_name='hardware_catalogue')
    op.drop_table('hardware_catalogue')
