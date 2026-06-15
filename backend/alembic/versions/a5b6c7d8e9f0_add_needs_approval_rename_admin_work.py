"""add 'Needs approval' label + rename warranty_issue -> admin_work_required (Phase L4)

Two safe, data-only label-definition changes (config/seed data only — touches NO
business data: customers/jobs/activities/assignments — and NO schema):

  1. ADD the system+auto approval label ``approval_required`` ("Needs approval").
     The approval lifecycle becomes: Needs approval -> Pending approval -> Approved
     (plus "no approval label" = not applicable). System+auto so it is locked from
     casual chip removal and assignable by the import auto-label + the dedicated
     Network Approval control.

  2. REKEY/RENAME the operational ``warranty_issue`` ("Warranty issue") to
     ``admin_work_required`` ("Admin work required"). The assignment FK references
     the definition by ``label_id`` (not key), so a rekey never breaks existing
     assignments; this preset additionally has ZERO assignments at the time of
     writing, so the change is doubly safe. It stays a manual operational label
     (is_system=False, is_auto=False) — no auto-labelling of "FINALISE TO AGL" in
     this pass.

A new migration (rather than editing the already-applied L1 seed) so fresh and
existing databases converge identically. Fully reversible.

Revision ID: a5b6c7d8e9f0
Revises: f4d5e6a7b8c9
Create Date: 2026-06-16 10:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a5b6c7d8e9f0'
down_revision: str | None = 'f4d5e6a7b8c9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (key, name, category, color, is_system, is_auto, sort_order)
_APPROVAL_REQUIRED = (
    "approval_required", "Needs approval", "approval", "red", True, True, 5,
)


def _labels_def():
    return sa.table(
        "job_label_definitions",
        sa.column("key", sa.String),
        sa.column("name", sa.String),
        sa.column("category", sa.String),
        sa.column("color", sa.String),
        sa.column("description", sa.Text),
        sa.column("is_system", sa.Boolean),
        sa.column("is_auto", sa.Boolean),
        sa.column("sort_order", sa.Integer),
    )


def upgrade() -> None:
    labels = _labels_def()
    key, name, category, color, is_system, is_auto, sort_order = _APPROVAL_REQUIRED
    op.bulk_insert(
        labels,
        [{
            "key": key, "name": name, "category": category, "color": color,
            "description": None, "is_system": is_system, "is_auto": is_auto,
            "sort_order": sort_order,
        }],
    )
    # Rekey + rename warranty_issue -> admin_work_required (config/seed data only).
    op.execute(
        labels.update()
        .where(labels.c.key == "warranty_issue")
        .values(key="admin_work_required", name="Admin work required")
    )


def downgrade() -> None:
    labels = _labels_def()
    op.execute(
        labels.update()
        .where(labels.c.key == "admin_work_required")
        .values(key="warranty_issue", name="Warranty issue")
    )
    op.execute(labels.delete().where(labels.c.key == "approval_required"))
