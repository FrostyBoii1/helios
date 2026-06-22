"""Hardware Parser lane, Stage 2A — admin catalogue + alias API.

Admin-only CRUD + search/filter + soft-delete/restore over the hardware catalogue and aliases.
Verifies: admin lifecycle works; non-admins are 403 on EVERY route (catalogue + aliases — normal
users can't even see aliases); deleted entries are excluded by default and visible in deleted
mode; restore keeps aliases intact; filters/search work; spec_id is immutable + unique;
soft-delete only (no hard delete). Nothing here touches Jobs/imports/parser.

Synthetic data inside the rolled-back db_session — entries are created via the API and never
persist. Tests use unique spec_ids and scope list checks with ?q= so they don't depend on the
seeded catalogue.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.hardware.seed import seed_hardware_catalogue
from app.models.hardware import HardwareCatalogue


def _hw(**over) -> dict:
    payload = {
        "spec_id": "test_hw", "category": "inverter", "canonical_model": "TEST-INV-10K",
        "display_name": "10kW Test", "brand": "TestBrand", "phases": "three_phase", "nominal_kw": 10,
    }
    payload.update(over)
    return payload


# --------------------------------------------------------------------------- #
# Admin lifecycle
# --------------------------------------------------------------------------- #
def test_admin_hardware_lifecycle(client_for, users):
    admin = client_for(users["admin"])
    created = admin.post("/api/v1/hardware", json=_hw(spec_id="lc_inv"))
    assert created.status_code == 201
    hw = created.json()
    hid = hw["id"]
    assert hw["spec_id"] == "lc_inv" and hw["category"] == "inverter"
    assert hw["spec_source"] == "admin" and hw["nominal_kw"] == 10.0
    assert hw["alias_count"] == 0 and hw["deleted_at"] is None and hw["is_active"] is True

    assert admin.get(f"/api/v1/hardware/{hid}").json()["spec_id"] == "lc_inv"

    # update — spec_id is immutable (not in the update shape), other fields change.
    upd = admin.patch(f"/api/v1/hardware/{hid}", json={"display_name": "Updated", "nominal_kw": 15})
    assert upd.status_code == 200
    assert upd.json()["display_name"] == "Updated" and upd.json()["nominal_kw"] == 15.0
    assert upd.json()["spec_id"] == "lc_inv"

    # soft-delete -> excluded by default, visible in deleted mode.
    deleted = admin.delete(f"/api/v1/hardware/{hid}")
    assert deleted.status_code == 200 and deleted.json()["deleted_at"] is not None
    assert admin.get("/api/v1/hardware?q=lc_inv").json()["total"] == 0
    assert admin.get("/api/v1/hardware?q=lc_inv&deleted=only").json()["total"] == 1
    assert admin.get("/api/v1/hardware?q=lc_inv&deleted=include").json()["total"] == 1

    # restore.
    restored = admin.post(f"/api/v1/hardware/{hid}/restore")
    assert restored.status_code == 200 and restored.json()["deleted_at"] is None
    assert admin.get("/api/v1/hardware?q=lc_inv").json()["total"] == 1

    # never hard-deleted: the row still exists.
    assert admin.get(f"/api/v1/hardware/{hid}").status_code == 200


def test_create_rejects_duplicate_spec_id(client_for, users):
    admin = client_for(users["admin"])
    assert admin.post("/api/v1/hardware", json=_hw(spec_id="dup_1")).status_code == 201
    assert admin.post("/api/v1/hardware", json=_hw(spec_id="dup_1")).status_code == 409


def test_create_rejects_blank_spec_id(client_for, users):
    admin = client_for(users["admin"])
    assert admin.post("/api/v1/hardware", json=_hw(spec_id="   ")).status_code == 400


# --------------------------------------------------------------------------- #
# Permissions — every route is admin-only
# --------------------------------------------------------------------------- #
def test_non_admin_cannot_access_any_route(client_for, users):
    admin = client_for(users["admin"])
    hid = admin.post("/api/v1/hardware", json=_hw(spec_id="na_hw")).json()["id"]
    aid = admin.post(
        f"/api/v1/hardware/{hid}/aliases", json={"alias": "NA Alias", "alias_type": "exact"}
    ).json()["id"]

    for role in ("support", "sales", "scheduling", "approvals"):
        c = client_for(users[role])
        # catalogue (incl. read/list) — admin-only.
        assert c.get("/api/v1/hardware").status_code == 403, role
        assert c.get(f"/api/v1/hardware/{hid}").status_code == 403, role
        assert c.post("/api/v1/hardware", json=_hw(spec_id=f"x_{role}")).status_code == 403, role
        assert c.patch(f"/api/v1/hardware/{hid}", json={"brand": "x"}).status_code == 403, role
        assert c.delete(f"/api/v1/hardware/{hid}").status_code == 403, role
        assert c.post(f"/api/v1/hardware/{hid}/restore").status_code == 403, role
        # aliases — normal users must NEVER see or touch them.
        assert c.get(f"/api/v1/hardware/{hid}/aliases").status_code == 403, role
        assert c.post(f"/api/v1/hardware/{hid}/aliases", json={"alias": "y", "alias_type": "exact"}).status_code == 403, role
        assert c.patch(f"/api/v1/hardware/{hid}/aliases/{aid}", json={"alias": "z"}).status_code == 403, role
        assert c.delete(f"/api/v1/hardware/{hid}/aliases/{aid}").status_code == 403, role
        assert c.post(f"/api/v1/hardware/{hid}/aliases/{aid}/restore").status_code == 403, role

    # the entries were not mutated by the rejected calls. (Re-acquire the admin client: the
    # client_for fixture overrides get_current_user GLOBALLY, so the loop left it on the last
    # non-admin role.)
    admin = client_for(users["admin"])
    assert admin.get(f"/api/v1/hardware/{hid}").json()["deleted_at"] is None
    assert admin.get(f"/api/v1/hardware/{hid}/aliases").json()["total"] == 1


# --------------------------------------------------------------------------- #
# Search + multi-filter
# --------------------------------------------------------------------------- #
def test_search_and_filters(client_for, users):
    admin = client_for(users["admin"])
    admin.post("/api/v1/hardware", json={
        "spec_id": "f_inv", "category": "inverter", "brand": "FilterCo", "phases": "single_phase", "nominal_kw": 5})
    admin.post("/api/v1/hardware", json={
        "spec_id": "f_bat", "category": "battery", "brand": "FilterCo", "capacity_kwh": 10})
    admin.post("/api/v1/hardware", json={
        "spec_id": "f_pan", "category": "panel", "brand": "OtherCo", "wattage_w": 440})

    # brand filter spans categories.
    assert {h["category"] for h in admin.get("/api/v1/hardware?brand=FilterCo").json()["items"]} == {"inverter", "battery"}
    # category + brand.
    assert admin.get("/api/v1/hardware?brand=FilterCo&category=inverter").json()["total"] == 1
    # phase.
    assert admin.get("/api/v1/hardware?brand=FilterCo&phase=single_phase").json()["total"] == 1
    # nominal_kw size filter.
    assert admin.get("/api/v1/hardware?brand=FilterCo&nominal_kw=5").json()["total"] == 1
    assert admin.get("/api/v1/hardware?brand=FilterCo&nominal_kw=999").json()["total"] == 0
    # capacity / wattage size filters.
    assert admin.get("/api/v1/hardware?brand=FilterCo&capacity_kwh=10").json()["total"] == 1
    assert admin.get("/api/v1/hardware?wattage_w=440&brand=OtherCo").json()["total"] == 1
    # search by spec_id / model / brand text.
    assert admin.get("/api/v1/hardware?q=f_bat").json()["total"] == 1
    assert admin.get("/api/v1/hardware?q=OtherCo").json()["total"] == 1


def test_lists_seeded_catalogue(client_for, users, db_session: Session):
    # Ensure the catalogue exists (idempotent — no-op if the dev DB is already seeded), then
    # confirm the admin list surfaces a seeded entry.
    seed_hardware_catalogue(db_session)
    admin = client_for(users["admin"])
    body = admin.get("/api/v1/hardware?q=meter_generic").json()
    assert body["total"] >= 1
    item = next(h for h in body["items"] if h["spec_id"] == "meter_generic")
    assert item["category"] == "metering" and item["canonical_model"] == "Meter"


# --------------------------------------------------------------------------- #
# Aliases
# --------------------------------------------------------------------------- #
def test_alias_lifecycle_and_uniqueness(client_for, users):
    admin = client_for(users["admin"])
    hid = admin.post("/api/v1/hardware", json=_hw(spec_id="al_hw")).json()["id"]

    created = admin.post(f"/api/v1/hardware/{hid}/aliases", json={
        "alias": "My Alias", "alias_type": "exact", "confidence_override": "manual_review"})
    assert created.status_code == 201
    aid = created.json()["id"]
    assert created.json()["alias"] == "My Alias" and created.json()["alias_type"] == "exact"
    assert created.json()["confidence_override"] == "manual_review"

    # active duplicate (same hardware/alias/type) -> 409.
    assert admin.post(f"/api/v1/hardware/{hid}/aliases", json={"alias": "My Alias", "alias_type": "exact"}).status_code == 409

    assert admin.get(f"/api/v1/hardware/{hid}/aliases").json()["total"] == 1
    assert admin.get(f"/api/v1/hardware/{hid}").json()["alias_count"] == 1

    # update.
    upd = admin.patch(f"/api/v1/hardware/{hid}/aliases/{aid}", json={"alias": "Renamed", "alias_type": "loose"})
    assert upd.status_code == 200 and upd.json()["alias"] == "Renamed" and upd.json()["alias_type"] == "loose"

    # soft-delete -> excluded by default, visible in deleted mode.
    assert admin.delete(f"/api/v1/hardware/{hid}/aliases/{aid}").status_code == 200
    assert admin.get(f"/api/v1/hardware/{hid}/aliases").json()["total"] == 0
    assert admin.get(f"/api/v1/hardware/{hid}/aliases?deleted=only").json()["total"] == 1

    # restore.
    assert admin.post(f"/api/v1/hardware/{hid}/aliases/{aid}/restore").status_code == 200
    assert admin.get(f"/api/v1/hardware/{hid}/aliases").json()["total"] == 1

    # re-creating a same-key alias after soft-delete RESTORES the row (no true duplicate).
    admin.delete(f"/api/v1/hardware/{hid}/aliases/{aid}")
    recreated = admin.post(f"/api/v1/hardware/{hid}/aliases", json={"alias": "Renamed", "alias_type": "loose"})
    assert recreated.status_code == 201 and recreated.json()["id"] == aid


def test_alias_update_onto_soft_deleted_key_is_clean_409(client_for, users):
    # The (hardware_id, alias, alias_type) unique constraint is FULL — it spans soft-deleted rows
    # (no partial deleted_at IS NULL index), so a soft-deleted alias still OWNS its key. Renaming
    # an active alias onto that key must be a clean 409 (the admin restores the deleted alias
    # instead), NEVER a 500 IntegrityError at flush, and the active alias must be left untouched.
    # This locks in update_alias's deliberate choice to span deleted rows in its clash query.
    admin = client_for(users["admin"])
    hid = admin.post("/api/v1/hardware", json=_hw(spec_id="usd_hw")).json()["id"]
    # B owns ("Bravo", exact), then is soft-deleted (its key is still reserved at the DB level).
    bid = admin.post(f"/api/v1/hardware/{hid}/aliases", json={"alias": "Bravo", "alias_type": "exact"}).json()["id"]
    assert admin.delete(f"/api/v1/hardware/{hid}/aliases/{bid}").status_code == 200
    # A is active.
    aid = admin.post(f"/api/v1/hardware/{hid}/aliases", json={"alias": "Alpha", "alias_type": "exact"}).json()["id"]

    # Rename A -> B's reserved key: clean 409, not a 500.
    resp = admin.patch(f"/api/v1/hardware/{hid}/aliases/{aid}", json={"alias": "Bravo"})
    assert resp.status_code == 409

    # A was not mutated by the rejected rename (still "Alpha"); the active list is unchanged.
    items = admin.get(f"/api/v1/hardware/{hid}/aliases").json()["items"]
    a = next(x for x in items if x["id"] == aid)
    assert a["alias"] == "Alpha"
    assert {x["id"] for x in items} == {aid}  # B stays soft-deleted, A stays active+unrenamed


def test_case_sensitive_alias_type_supported(client_for, users):
    admin = client_for(users["admin"])
    hid = admin.post("/api/v1/hardware", json=_hw(spec_id="cs_hw", category="panel")).json()["id"]
    a = admin.post(f"/api/v1/hardware/{hid}/aliases", json={"alias": "Jinko 440", "alias_type": "case_sensitive"})
    assert a.status_code == 201 and a.json()["alias_type"] == "case_sensitive"


def test_hardware_restore_keeps_aliases_intact(client_for, users):
    admin = client_for(users["admin"])
    hid = admin.post("/api/v1/hardware", json=_hw(spec_id="ra_hw")).json()["id"]
    admin.post(f"/api/v1/hardware/{hid}/aliases", json={"alias": "A1", "alias_type": "exact"})
    admin.post(f"/api/v1/hardware/{hid}/aliases", json={"alias": "A2", "alias_type": "loose"})
    assert admin.get(f"/api/v1/hardware/{hid}/aliases").json()["total"] == 2

    admin.delete(f"/api/v1/hardware/{hid}")                       # soft-delete hardware
    assert admin.get(f"/api/v1/hardware/{hid}/aliases").json()["total"] == 2  # aliases untouched
    admin.post(f"/api/v1/hardware/{hid}/restore")                 # restore
    restored = admin.get(f"/api/v1/hardware/{hid}").json()
    assert restored["deleted_at"] is None and restored["alias_count"] == 2
    assert admin.get(f"/api/v1/hardware/{hid}/aliases").json()["total"] == 2


def test_admin_create_does_not_hard_delete_or_touch_jobs(client_for, users, db_session: Session):
    # Soft-delete genuinely soft-deletes (row + deleted_at), never a hard delete.
    admin = client_for(users["admin"])
    hid = admin.post("/api/v1/hardware", json=_hw(spec_id="sd_hw")).json()["id"]
    admin.delete(f"/api/v1/hardware/{hid}")
    row = db_session.get(HardwareCatalogue, hid)
    assert row is not None and row.deleted_at is not None  # soft-deleted, not gone
