"""Case number generation.

Format: SCS-<YEAR>-<5-digit zero-padded sequence>, e.g. SCS-2026-00001.

The sequence resets per calendar year. We derive the next sequence by counting
existing jobs for the year inside the SAME transaction as the insert, and rely on
the unique constraint on `jobs.case_number` to reject the rare race; callers
should retry on IntegrityError. (A PostgreSQL sequence per year is a possible
future optimisation — see CHANGES.md if adopted.)
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.job import Job

CASE_PREFIX = "SCS"


def build_case_number(year: int, sequence: int) -> str:
    return f"{CASE_PREFIX}-{year}-{sequence:05d}"


def next_case_number(db: Session, year: int) -> str:
    """Compute the next case number for the given year.

    Counts existing jobs whose case_number starts with the year prefix. The
    caller must hold a transaction and handle a unique-violation retry.
    """
    prefix = f"{CASE_PREFIX}-{year}-"
    count = db.scalar(
        select(func.count()).select_from(Job).where(Job.case_number.like(f"{prefix}%"))
    )
    return build_case_number(year, (count or 0) + 1)
