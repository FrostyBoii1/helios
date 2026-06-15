"""rename default approval label display names

User-facing copy fix: the seeded approval labels read better as "Approved" /
"Pending approval" than "Approval approved" / "Approval pending". The internal
KEYS are unchanged (approval_approved / approval_pending) — import auto-labeling
and all lookups key off those, so nothing else changes.

Data-only update of two ``job_label_definitions`` rows (config/seed data). Touches
NO business data (customers/jobs/activities) and NO schema. Idempotent (sets a
fixed value) and reversible. A new migration rather than editing the already-
applied L1 seed, so fresh and existing databases converge identically.

Revision ID: f4d5e6a7b8c9
Revises: e3c4d5f6a7b8
Create Date: 2026-06-15 11:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f4d5e6a7b8c9'
down_revision: str | None = 'e3c4d5f6a7b8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_NAMES = [
    ("approval_approved", "Approved"),
    ("approval_pending", "Pending approval"),
]
_OLD_NAMES = [
    ("approval_approved", "Approval approved"),
    ("approval_pending", "Approval pending"),
]


def _rename(pairs: list[tuple[str, str]]) -> None:
    labels = sa.table(
        "job_label_definitions",
        sa.column("key", sa.String),
        sa.column("name", sa.String),
    )
    for key, name in pairs:
        op.execute(labels.update().where(labels.c.key == key).values(name=name))


def upgrade() -> None:
    _rename(_NEW_NAMES)


def downgrade() -> None:
    _rename(_OLD_NAMES)
