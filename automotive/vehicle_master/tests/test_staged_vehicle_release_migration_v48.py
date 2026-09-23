"""migration_v48's three-phase staged release protocol, against a real
Postgres: begin_vehicle_release / stage_vehicle_release_chunk /
activate_vehicle_release, the chunk-ledger idempotency and FK-order
guards, the manifest-based (not caller-trusted) count validation at
activation, the same v44 staleness guard carried over unchanged, the RLS
policy that now keeps STAGING rows invisible to anon/authenticated while
ACTIVE and SUPERSEDED stay readable, and that publish_vehicle_release(jsonb)
itself -- untouched by this migration -- still works exactly as before.

The September 2026 ECO Sticker release measured ~34.5s against a 45s
function-level statement_timeout (migration_v47) and still failed: a
release this size cannot finish as one transaction. Staging lets the same
projection tables be filled by many small, independently retryable calls
instead, with the public serving pointer only ever moving at activation.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from tests.pg_cluster import apply_production_schema, pg  # noqa: F401


@pytest.fixture
def db(pg):
    apply_production_schema(pg)
    return pg


def _manifest(release_id: str, *, counts: dict[str, int] | None = None,
              ordinal: int | None = None, as_of: str = "2026-09-23") -> dict:
    counts = counts or {"brands": 0, "models": 0, "generations": 0,
                        "market_trims": 0, "price_ledger": 0, "spec_facts": 0}
    manifest = {
        "schema_version": 1,
        "release_id": release_id,
        "canonical_revision": f"sha-for-{release_id}",
        "source_hash": release_id.rsplit("-", 1)[-1],
        "as_of": as_of,
        "year": 2026,
        "counts": counts,
        "historical_model_state": {"catalog_years": [2026], "model_year_baselines": [],
                                   "monthly_changes": []},
    }
    if ordinal is not None:
        manifest["revision_ordinal"] = ordinal
    return manifest


def _q(value: dict | list) -> str:
    return json.dumps(value).replace("'", "''")


def _begin(db, manifest: dict) -> tuple[bool, str]:
    return db.try_sql(f"select public.begin_vehicle_release('{_q(manifest)}'::jsonb)")


def _stage(db, release_id: str, section: str, chunk_index: int, rows: list[dict],
          *, chunk_hash: str | None = None) -> tuple[bool, str]:
    chunk_hash = chunk_hash or hashlib.sha256(_q(rows).encode()).hexdigest()
    return db.try_sql(
        f"select public.stage_vehicle_release_chunk("
        f"'{release_id}', '{section}', {chunk_index}, '{chunk_hash}', '{_q(rows)}'::jsonb)"
    )


def _activate(db, release_id: str) -> tuple[bool, str]:
    return db.try_sql(f"select public.activate_vehicle_release('{release_id}')")


def _brand(canonical_id="toyota") -> dict:
    return {"canonical_id": canonical_id, "slug": canonical_id, "name_en": "Toyota", "payload": {}}


def _model(canonical_id="toyota.camry", brand_id="toyota") -> dict:
    return {"canonical_id": canonical_id, "brand_id": brand_id, "slug": "toyota-camry",
           "name_en": "Camry", "status": "CURRENT", "payload": {}}


def _generation(canonical_id="toyota.camry.axvh70", model_id="toyota.camry") -> dict:
    return {"canonical_id": canonical_id, "model_id": model_id, "code": "AXVH70", "payload": {}}


def _trim(canonical_id="toyota.camry.axvh70.trim.premium", model_id="toyota.camry",
         generation_id="toyota.camry.axvh70") -> dict:
    return {"canonical_id": canonical_id, "model_id": model_id, "generation_id": generation_id,
           "name": "Premium", "powertrain": "HEV", "status": "CURRENT", "payload": {}}


RID = "vehicle-2026-aaaaaaaaaaaaaaaa"


def _stage_full_catalog(db, rid: str) -> None:
    """One brand -> one model -> one generation -> one trim, staged in
    correct FK order, for tests that only care about what happens after
    the whole catalog spine exists."""
    counts = {"brands": 1, "models": 1, "generations": 1, "market_trims": 1,
             "price_ledger": 0, "spec_facts": 0}
    ok, err = _begin(db, _manifest(rid, counts=counts))
    assert ok, err
    for section, row in (("brands", _brand()), ("models", _model()),
                         ("generations", _generation()), ("market_trims", _trim())):
        ok, err = _stage(db, rid, section, 0, [row])
        assert ok, err


# ---------------------------------------------------------------------
# begin_vehicle_release
# ---------------------------------------------------------------------

def test_begin_opens_a_staging_release_with_a_small_manifest_not_the_bulk_arrays(db):
    ok, err = _begin(db, _manifest(RID))
    assert ok, err
    row = db.rows(
        f"select status, payload ? 'brands', payload ? 'historical_model_state' "
        f"from public.canonical_vehicle_releases where release_id = '{RID}'")
    assert row == [["STAGING", "f", "t"]]


def test_begin_rejects_an_invalid_release_id(db):
    ok, err = _begin(db, _manifest("not-a-valid-id"))
    assert not ok
    assert "invalid release_id" in err


def test_begin_rejects_a_manifest_missing_a_section_count(db):
    manifest = _manifest(RID)
    del manifest["counts"]["spec_facts"]
    ok, err = _begin(db, manifest)
    assert not ok
    assert "counts" in err


def test_begin_is_idempotent_for_an_already_active_release(db):
    ok, err = _begin(db, _manifest(RID, counts={"brands": 0, "models": 0, "generations": 0,
                                                 "market_trims": 0, "price_ledger": 0, "spec_facts": 0}))
    assert ok, err
    ok, err = _activate(db, RID)
    assert ok, err

    ok, err = _begin(db, _manifest(RID))
    assert ok, err
    result = db.rows(f"select public.begin_vehicle_release('{_q(_manifest(RID))}'::jsonb)")
    payload = json.loads(result[0][0])
    assert payload["already_finalized"] is True
    assert payload["status"] == "ACTIVE"
    # Re-opening an ACTIVE release must not have touched its projection rows.
    assert db.scalar(
        f"select count(*) from public.canonical_brand_projection where release_id = '{RID}'") == "0"


def test_begin_rejects_a_counts_mismatch_against_an_already_staging_release(db):
    ok, err = _begin(db, _manifest(RID, counts={"brands": 1, "models": 0, "generations": 0,
                                                 "market_trims": 0, "price_ledger": 0, "spec_facts": 0}))
    assert ok, err
    ok, err = _begin(db, _manifest(RID, counts={"brands": 2, "models": 0, "generations": 0,
                                                "market_trims": 0, "price_ledger": 0, "spec_facts": 0}))
    assert not ok
    assert "different counts" in err


def test_begin_resume_reports_already_staged_chunks(db):
    counts = {"brands": 1, "models": 0, "generations": 0, "market_trims": 0,
             "price_ledger": 0, "spec_facts": 0}
    ok, err = _begin(db, _manifest(RID, counts=counts))
    assert ok, err
    ok, err = _stage(db, RID, "brands", 0, [_brand()])
    assert ok, err

    result = db.rows(f"select public.begin_vehicle_release('{_q(_manifest(RID, counts=counts))}'::jsonb)")
    payload = json.loads(result[0][0])
    assert payload["staged"] == {"brands": 1}


# ---------------------------------------------------------------------
# stage_vehicle_release_chunk
# ---------------------------------------------------------------------

def test_stage_rejects_an_unknown_release(db):
    ok, err = _stage(db, "vehicle-2026-ffffffffffffffff", "brands", 0, [_brand()])
    assert not ok
    assert "unknown release" in err


def test_stage_rejects_an_unknown_section(db):
    ok, err = _begin(db, _manifest(RID))
    assert ok, err
    ok, err = _stage(db, RID, "vehicles", 0, [_brand()])
    assert not ok
    assert "unknown release section" in err


def test_stage_populates_the_real_projection_table_for_every_section(db):
    _stage_full_catalog(db, RID)
    assert db.scalar(
        f"select count(*) from public.canonical_brand_projection where release_id = '{RID}'") == "1"
    assert db.scalar(
        f"select count(*) from public.canonical_model_projection where release_id = '{RID}'") == "1"
    assert db.scalar(
        f"select count(*) from public.canonical_generation_projection where release_id = '{RID}'") == "1"
    assert db.scalar(
        f"select count(*) from public.canonical_market_trim_projection where release_id = '{RID}'") == "1"


def test_stage_is_idempotent_for_a_repeated_chunk_with_the_same_hash(db):
    ok, err = _begin(db, _manifest(RID, counts={"brands": 1, "models": 0, "generations": 0,
                                                 "market_trims": 0, "price_ledger": 0, "spec_facts": 0}))
    assert ok, err
    ok, err = _stage(db, RID, "brands", 0, [_brand()])
    assert ok, err
    result = db.rows(
        f"select public.stage_vehicle_release_chunk("
        f"'{RID}', 'brands', 0, '{hashlib.sha256(_q([_brand()]).encode()).hexdigest()}', "
        f"'{_q([_brand()])}'::jsonb)")
    payload = json.loads(result[0][0])
    assert payload["status"] == "already_staged"
    assert db.scalar(
        f"select count(*) from public.canonical_brand_projection where release_id = '{RID}'") == "1"


def test_stage_rejects_the_same_chunk_index_with_a_different_hash(db):
    ok, err = _begin(db, _manifest(RID, counts={"brands": 1, "models": 0, "generations": 0,
                                                 "market_trims": 0, "price_ledger": 0, "spec_facts": 0}))
    assert ok, err
    ok, err = _stage(db, RID, "brands", 0, [_brand()])
    assert ok, err
    ok, err = _stage(db, RID, "brands", 0, [_brand("honda")], chunk_hash="deliberately-different")
    assert not ok
    assert "different hash" in err


def test_stage_refuses_a_section_before_its_fk_prerequisite_is_fully_staged(db):
    ok, err = _begin(db, _manifest(RID, counts={"brands": 1, "models": 1, "generations": 0,
                                                 "market_trims": 0, "price_ledger": 0, "spec_facts": 0}))
    assert ok, err
    # brands expects 1 row but none staged yet -- models must wait.
    ok, err = _stage(db, RID, "models", 0, [_model()])
    assert not ok
    assert "before section brands is fully staged" in err


def test_stage_refuses_writes_once_the_release_is_active(db):
    ok, err = _begin(db, _manifest(RID, counts={"brands": 0, "models": 0, "generations": 0,
                                                 "market_trims": 0, "price_ledger": 0, "spec_facts": 0}))
    assert ok, err
    ok, err = _activate(db, RID)
    assert ok, err
    ok, err = _stage(db, RID, "brands", 0, [_brand()])
    assert not ok
    assert "not staging" in err


# ---------------------------------------------------------------------
# activate_vehicle_release
# ---------------------------------------------------------------------

def test_activate_refuses_an_incompletely_staged_release_by_recounting_itself(db):
    ok, err = _begin(db, _manifest(RID, counts={"brands": 2, "models": 0, "generations": 0,
                                                 "market_trims": 0, "price_ledger": 0, "spec_facts": 0}))
    assert ok, err
    ok, err = _stage(db, RID, "brands", 0, [_brand()])
    assert ok, err
    # Only 1 of the 2 promised brand rows staged -- activation must recount
    # the ledger itself and refuse, not trust any count the caller supplies
    # (this call is not even given one).
    ok, err = _activate(db, RID)
    assert not ok
    assert "not fully staged" in err
    assert "brands: 1/2" in err


def test_activate_flips_the_serving_pointer_and_supersedes_the_old_release(db):
    old_ok, old_err = _begin(db, _manifest("vehicle-2026-bbbbbbbbbbbbbbbb",
                                            counts={"brands": 0, "models": 0, "generations": 0,
                                                    "market_trims": 0, "price_ledger": 0, "spec_facts": 0}))
    assert old_ok, old_err
    assert _activate(db, "vehicle-2026-bbbbbbbbbbbbbbbb")[0]

    _stage_full_catalog(db, RID)
    ok, err = _activate(db, RID)
    assert ok, err

    assert db.rows(
        "select active_release_id from public.canonical_vehicle_state "
        "where scope = 'vehicle_catalog'") == [[RID]]
    assert db.rows(
        "select status from public.canonical_vehicle_releases "
        "where release_id = 'vehicle-2026-bbbbbbbbbbbbbbbb'") == [["SUPERSEDED"]]
    assert db.rows("select canonical_id from public.current_vehicle_brands") == [["toyota"]]


def test_activate_is_idempotent_for_an_already_active_release(db):
    ok, err = _begin(db, _manifest(RID, counts={"brands": 0, "models": 0, "generations": 0,
                                                 "market_trims": 0, "price_ledger": 0, "spec_facts": 0}))
    assert ok, err
    assert _activate(db, RID)[0]
    ok, err = _activate(db, RID)
    assert ok, err
    result = db.rows(f"select public.activate_vehicle_release('{RID}')")
    payload = json.loads(result[0][0])
    assert payload["already_active"] is True


def test_activate_still_refuses_a_stale_revision_ordinal(db):
    ok, err = _begin(db, _manifest("vehicle-2026-cccccccccccccccc", ordinal=20,
                                    counts={"brands": 0, "models": 0, "generations": 0,
                                            "market_trims": 0, "price_ledger": 0, "spec_facts": 0}))
    assert ok, err
    assert _activate(db, "vehicle-2026-cccccccccccccccc")[0]

    ok, err = _begin(db, _manifest("vehicle-2026-dddddddddddddddd", ordinal=5,
                                    counts={"brands": 0, "models": 0, "generations": 0,
                                            "market_trims": 0, "price_ledger": 0, "spec_facts": 0}))
    assert ok, err
    ok, err = _activate(db, "vehicle-2026-dddddddddddddddd")
    assert not ok
    assert "stale revision" in err
    assert db.rows(
        "select active_release_id from public.canonical_vehicle_state "
        "where scope = 'vehicle_catalog'") == [["vehicle-2026-cccccccccccccccc"]]


# ---------------------------------------------------------------------
# RLS: the actual "biggest issue" this migration closes
# ---------------------------------------------------------------------

def test_staging_rows_are_invisible_to_anon_and_authenticated(db):
    _stage_full_catalog(db, RID)
    for role in ("anon", "authenticated"):
        assert db.rows(
            f"set role {role}; select count(*) from public.canonical_brand_projection "
            f"where release_id = '{RID}'") == [["0"]]
        assert db.rows(
            f"set role {role}; select count(*) from public.canonical_market_trim_projection "
            f"where release_id = '{RID}'") == [["0"]]


def test_anon_and_authenticated_still_have_no_direct_grant_on_the_releases_table(db):
    # release_is_publicly_readable() answers the ACTIVE/SUPERSEDED question
    # as SECURITY DEFINER precisely so these policies never need to grant
    # either role real access to canonical_vehicle_releases (its own
    # payload column is exactly what must not become newly readable here).
    for role in ("anon", "authenticated"):
        ok, err = db.try_sql(
            f"set role {role}; select count(*) from public.canonical_vehicle_releases")
        assert not ok
        assert "permission denied" in err


def test_active_and_superseded_rows_remain_visible_to_anon_and_authenticated(db):
    _stage_full_catalog(db, RID)
    assert _activate(db, RID)[0]

    _stage_full_catalog(db, "vehicle-2026-eeeeeeeeeeeeeeee")
    assert _activate(db, "vehicle-2026-eeeeeeeeeeeeeeee")[0]

    for role in ("anon", "authenticated"):
        # RID is now SUPERSEDED, the second release is ACTIVE -- both readable.
        assert db.rows(
            f"set role {role}; select count(*) from public.canonical_brand_projection "
            f"where release_id = '{RID}'") == [["1"]]
        assert db.rows(
            f"set role {role}; select count(*) from public.canonical_brand_projection "
            f"where release_id = 'vehicle-2026-eeeeeeeeeeeeeeee'") == [["1"]]


# ---------------------------------------------------------------------
# publish_vehicle_release(jsonb) itself: untouched by this migration
# ---------------------------------------------------------------------

def test_the_legacy_single_call_publish_path_still_works_unchanged(db):
    release = {
        "schema_version": 1, "release_id": "vehicle-2026-9999999999999999",
        "canonical_revision": "legacy", "source_hash": "9999999999999999",
        "as_of": "2026-09-23",
        "counts": {"brands": 0, "models": 0, "generations": 0,
                  "market_trims": 0, "price_ledger": 0, "spec_facts": 0},
        "brands": [], "models": [], "generations": [],
        "market_trims": [], "price_ledger": [], "spec_facts": [],
    }
    body = json.dumps(release).replace("'", "''")
    ok, err = db.try_sql(f"select public.publish_vehicle_release('{body}'::jsonb)")
    assert ok, err
    assert db.rows(
        "select active_release_id from public.canonical_vehicle_state "
        "where scope = 'vehicle_catalog'") == [["vehicle-2026-9999999999999999"]]
