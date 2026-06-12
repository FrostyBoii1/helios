"""Test configuration and shared fixtures.

Sets safe default environment variables BEFORE application settings are imported,
so smoke tests run without a real .env file. Also provides a database-backed,
rollback-isolated session + a TestClient factory for integration tests.

Isolation strategy: each `db_session` opens a connection, begins a transaction,
and binds a Session in "create_savepoint" mode so endpoint `commit()` calls land
in a SAVEPOINT. The outer transaction is rolled back on teardown, so tests never
persist data into the database they run against.
"""

from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "testing")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("BACKEND_CORS_ORIGINS", "http://localhost:5173")

from collections.abc import Callable, Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.api.deps import get_current_user  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.enums import RoleName  # noqa: E402
from app.models.role import Role  # noqa: E402
from app.models.user import User  # noqa: E402


@pytest.fixture
def db_session() -> Iterator[Session]:
    connection = engine.connect()
    trans = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()


def _get_or_create_role(session: Session, role: RoleName) -> Role:
    existing = session.scalar(select(Role).where(Role.name == role.value))
    if existing is not None:
        return existing
    created = Role(name=role.value, description=role.value)
    session.add(created)
    session.flush()
    return created


@pytest.fixture
def users(db_session: Session) -> dict[str, User]:
    """One active user per role relevant to customer permissions."""
    spec = {
        "admin": RoleName.ADMIN,
        "sales": RoleName.SALES_ADMIN,
        "support": RoleName.SUPPORT,
    }
    out: dict[str, User] = {}
    for key, role_name in spec.items():
        role = _get_or_create_role(db_session, role_name)
        user = User(
            full_name=f"Test {key}",
            email=f"test_{key}@example.com",
            hashed_password=hash_password("test-password"),
            role_id=role.id,
            is_active=True,
        )
        user.role = role  # avoid a later lazy-load for role-based guards
        db_session.add(user)
        out[key] = user
    db_session.flush()
    return out


@pytest.fixture
def client_for(db_session: Session) -> Iterator[Callable[[User], TestClient]]:
    """Factory: build a TestClient acting as the given user.

    Overrides get_db with the rollback-isolated session and get_current_user with
    the chosen user, so role guards run against a known role with no JWT needed.
    """

    def _override_db() -> Iterator[Session]:
        yield db_session

    def _make(current_user: User) -> TestClient:
        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = lambda: current_user
        return TestClient(app)

    yield _make
    app.dependency_overrides.clear()
