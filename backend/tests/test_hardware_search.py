"""Hardware Parser lane, H1 — lean staff hardware SEARCH endpoint.

`GET /api/v1/hardware/search` is a read-only autocomplete feed for hardware textboxes. Unlike the
admin catalogue API it is reachable by ANY authenticated staff member (not only admins), returns
ONLY active + non-deleted canonical hardware, and exposes a LEAN shape — never aliases, alias_count,
attributes, spec_source, is_active, timestamps, or deleted rows. The admin catalogue + alias routes
stay admin-only (regression-guarded here). Synthetic data in the rolled-back db_session.
"""
from __future__ import annotations

_LEAN_KEYS = {
    "id", "spec_id", "category", "display_name", "canonical_model", "brand",
    "phases", "nominal_kw", "capacity_kwh", "wattage_w", "model_options",
}
_FORBIDDEN_KEYS = {
    "alias_count", "attributes", "spec_source", "is_active",
    "deleted_at", "created_at", "updated_at", "created_by_id",
}


def _create(admin, **over) -> dict:
    payload = {
        "spec_id": "srch_x", "category": "inverter", "canonical_model": "M-10K",
        "display_name": "10kW", "brand": "Brand", "phases": "three_phase", "nominal_kw": 10,
    }
    payload.update(over)
    r = admin.post("/api/v1/hardware", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def test_search_requires_authentication():
    # No get_current_user override (do NOT use client_for) -> real auth -> 401.
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get("/api/v1/hardware/search").status_code == 401


def test_non_admin_authenticated_user_can_search(client_for, users):
    # support is a non-admin role; it can use the search feed (admin CRUD stays closed).
    r = client_for(users["support"]).get("/api/v1/hardware/search")
    assert r.status_code == 200
    assert "items" in r.json()


def test_search_returns_active_non_deleted_only(client_for, users):
    admin = client_for(users["admin"])
    active = _create(admin, spec_id="srch_active", brand="SrchMarkZ")
    inactive = _create(admin, spec_id="srch_inactive", brand="SrchMarkZ")
    admin.patch(f"/api/v1/hardware/{inactive['id']}", json={"is_active": False})
    deleted = _create(admin, spec_id="srch_deleted", brand="SrchMarkZ")
    admin.delete(f"/api/v1/hardware/{deleted['id']}")

    support = client_for(users["support"])
    body = support.get("/api/v1/hardware/search", params={"q": "SrchMarkZ"}).json()
    assert body["total"] == 1
    assert [it["spec_id"] for it in body["items"]] == ["srch_active"]
    assert body["items"][0]["id"] == active["id"]


def test_search_does_not_expose_aliases_or_admin_internals(client_for, users):
    admin = client_for(users["admin"])
    hw = _create(admin, spec_id="srch_lean", brand="LeanMarkZ")
    # Give it an alias — the search feed must STILL never surface alias data.
    admin.post(f"/api/v1/hardware/{hw['id']}/aliases",
               json={"alias": "lean alias", "alias_type": "exact"})

    item = client_for(users["sales"]).get(
        "/api/v1/hardware/search", params={"q": "LeanMarkZ"}
    ).json()["items"][0]
    # Exactly the lean keys — no aliases / alias_count / attributes / spec_source / is_active /
    # deleted_at / timestamps / created_by.
    assert set(item.keys()) == _LEAN_KEYS
    assert _FORBIDDEN_KEYS.isdisjoint(item.keys())
    assert "alias" not in item and "aliases" not in item


def test_search_q_and_category_filter(client_for, users):
    admin = client_for(users["admin"])
    _create(admin, spec_id="srch_inv", category="inverter", brand="CatMarkZ", canonical_model="INV-X")
    _create(admin, spec_id="srch_bat", category="battery", brand="CatMarkZ",
            canonical_model="BAT-X", nominal_kw=None, capacity_kwh=20)

    support = client_for(users["support"])
    both = support.get("/api/v1/hardware/search", params={"q": "CatMarkZ"}).json()
    assert both["total"] == 2
    # q matches canonical_model too.
    by_model = support.get("/api/v1/hardware/search", params={"q": "BAT-X"}).json()
    assert by_model["total"] == 1 and by_model["items"][0]["spec_id"] == "srch_bat"
    # category narrows it.
    bats = support.get("/api/v1/hardware/search", params={"q": "CatMarkZ", "category": "battery"}).json()
    assert bats["total"] == 1 and bats["items"][0]["spec_id"] == "srch_bat"
    assert bats["items"][0]["capacity_kwh"] == 20.0


def test_admin_catalogue_and_alias_routes_remain_admin_only(client_for, users):
    admin = client_for(users["admin"])
    hw = _create(admin, spec_id="srch_guard")
    support = client_for(users["support"])
    # The lean search is open...
    assert support.get("/api/v1/hardware/search").status_code == 200
    # ...but the admin catalogue + alias routes are NOT (search did not open them).
    assert support.get("/api/v1/hardware").status_code == 403
    assert support.get(f"/api/v1/hardware/{hw['id']}").status_code == 403
    assert support.get(f"/api/v1/hardware/{hw['id']}/aliases").status_code == 403
    assert support.post("/api/v1/hardware", json=_HW_MIN).status_code == 403


_HW_MIN = {"spec_id": "srch_nope", "category": "inverter"}
