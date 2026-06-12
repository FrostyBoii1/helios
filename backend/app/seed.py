"""Idempotent seed script.

Run after migrations to bootstrap the system:
  * One `roles` row per RoleName (with a friendly description).
  * A single first Admin account from FIRST_ADMIN_* env vars, IF no admin exists.

Usage (inside the backend container or venv):
    python -m app.seed

Safe to run repeatedly — it never duplicates roles and never overwrites an
existing admin's password.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.models.enums import RoleName
from app.models.role import Role
from app.models.user import User
from app.services.users import create_user, get_user_by_email

ROLE_DESCRIPTIONS: dict[RoleName, str] = {
    RoleName.ADMIN: "Full access: manage users, jobs, reports, and configuration.",
    RoleName.SCHEDULING: "Installs, job dates, rescheduling, and scheduling tasks.",
    RoleName.APPROVALS: "Outstanding approvals, install deadlines, missing documents.",
    RoleName.SUPPORT: "Flagged customers, technical cases, support notes and follow-ups.",
    RoleName.SALES_ADMIN: "New sales, onboarding, welcome calls, documents, admin tasks.",
}


def seed_roles(db: Session) -> None:
    log = get_logger("seed")
    existing = {r.name for r in db.scalars(select(Role)).all()}
    for role in RoleName:
        if role.value not in existing:
            db.add(Role(name=role.value, description=ROLE_DESCRIPTIONS[role]))
            log.info("role_created", role=role.value)
    db.commit()


def seed_first_admin(db: Session) -> None:
    log = get_logger("seed")
    admin_role = db.scalar(select(Role).where(Role.name == RoleName.ADMIN.value))
    if admin_role is None:
        raise RuntimeError("Admin role missing — seed roles first.")

    has_admin = db.scalar(
        select(User).where(User.role_id == admin_role.id, User.deleted_at.is_(None))
    )
    if has_admin is not None:
        log.info("admin_exists_skip")
        return

    if get_user_by_email(db, settings.FIRST_ADMIN_EMAIL) is not None:
        log.info("first_admin_email_taken_skip", email=settings.FIRST_ADMIN_EMAIL)
        return

    create_user(
        db,
        full_name=settings.FIRST_ADMIN_NAME,
        email=settings.FIRST_ADMIN_EMAIL,
        password=settings.FIRST_ADMIN_PASSWORD,
        role=RoleName.ADMIN,
    )
    db.commit()
    log.info("first_admin_created", email=settings.FIRST_ADMIN_EMAIL)


def main() -> None:
    configure_logging()
    with SessionLocal() as db:
        seed_roles(db)
        seed_first_admin(db)


if __name__ == "__main__":
    main()
