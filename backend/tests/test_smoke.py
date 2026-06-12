"""Smoke tests that need no database.

Verifies the app builds, the liveness endpoint responds, and core security
primitives round-trip. Database-backed tests will be added as features land.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.main import app

client = TestClient(app)


def test_health_ok() -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)


def test_access_token_roundtrip() -> None:
    token = create_access_token(123)
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == "123"
    assert payload["type"] == "access"
