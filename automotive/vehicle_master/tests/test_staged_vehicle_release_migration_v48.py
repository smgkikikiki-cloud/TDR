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
import shlex
import subprocess
import time

import pytest

from tests import pg_cluster as _pgc
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


def _popen_psql(db) -> subprocess.Popen:
    """A psql subprocess left open on its own real connection, for tests
    that need two genuinely concurrent sessions -- Cluster.sql()/.rows()
    each spawn-and-wait-for-exit in one call, which cannot hold a
    transaction (and the locks it took) open while another session runs."""
    command = [str(_pgc.PG_BIN / "psql"), "-h", str(db.socket), "-U", _pgc.PG_USER,
              "-d", "postgres", "-q", "-v", "ON_ERROR_STOP=1"]
    if _pgc.AS_POSTGRES:
        command = ["su", _pgc.PG_USER, "-s", "/bin/sh", "-c",
                   " ".join(shlex.quote(part) for part in command)]
    return subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


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
    assert "incompatible manifest" in err


def test_begin_never_overwrites_the_stored_revision_ordinal_on_resume(db):
    # A partially staged release begun from a full clone carries an
    # ordinal. If a later resume attempt (a retry from a shallow clone,
    # say) omitted it, silently accepting that and overwriting the stored
    # ordinal with NULL would quietly disable v44's staleness guard for
    # the rest of this release's life. It must error instead, and the
    # originally stored ordinal must survive the rejected call untouched.
    ok, err = _begin(db, _manifest(RID, ordinal=30,
                                    counts={"brands": 0, "models": 0, "generations": 0,
                                            "market_trims": 0, "price_ledger": 0, "spec_facts": 0}))
    assert ok, err

    resumed_without_ordinal = _manifest(RID, counts={"brands": 0, "models": 0, "generations": 0,
                                                      "market_trims": 0, "price_ledger": 0,
                                                      "spec_facts": 0})
    assert "revision_ordinal" not in resumed_without_ordinal
    ok, err = _begin(db, resumed_without_ordinal)
    assert not ok
    assert "incompatible manifest" in err

    assert db.rows(
        f"select revision_ordinal from public.canonical_vehicle_releases "
        f"where release_id = '{RID}'") == [["30"]]


def test_begin_rejects_a_semantic_mismatch_against_an_already_active_release(db):
    ok, err = _begin(db, _manifest(RID, counts={"brands": 0, "models": 0, "generations": 0,
                                                 "market_trims": 0, "price_ledger": 0, "spec_facts": 0}))
    assert ok, err
    ok, err = _activate(db, RID)
    assert ok, err

    # Same release_id, but a genuinely different semantic manifest (a
    # different as_of here) -- content-hash release_ids mean this can only
    # be a caller bug, and it must error rather than being waved through
    # as "already finalized, who cares which manifest it was staged with".
    ok, err = _begin(db, _manifest(RID, as_of="2026-10-01",
                                    counts={"brands": 0, "models": 0, "generations": 0,
                                            "market_trims": 0, "price_ledger": 0, "spec_facts": 0}))
    assert not ok
    assert "incompatible manifest" in err


def test_begin_reports_superseded_not_active_for_a_finalized_release_that_is_no_longer_serving(db):
    manifest_a = _manifest(RID, counts={"brands": 0, "models": 0, "generations": 0,
                                        "market_trims": 0, "price_ledger": 0, "spec_facts": 0})
    ok, err = _begin(db, manifest_a)
    assert ok, err
    assert _activate(db, RID)[0]

    other = "vehicle-2026-eeeeeeeeeeeeeeee"
    ok, err = _begin(db, _manifest(other, counts={"brands": 0, "models": 0, "generations": 0,
                                                   "market_trims": 0, "price_ledger": 0, "spec_facts": 0}))
    assert ok, err
    assert _activate(db, other)[0]

    # RID is now SUPERSEDED -- begin_vehicle_release must say so, distinctly
    # from ACTIVE, so a caller cannot mistake "this release_id was once
    # finalized" for "this release_id is what is currently serving".
    result = db.rows(f"select public.begin_vehicle_release('{_q(manifest_a)}'::jsonb)")
    payload = json.loads(result[0][0])
    assert payload == {"release_id": RID, "status": "SUPERSEDED", "already_finalized": True}


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


def test_activate_serializes_concurrent_activations_so_an_older_ordinal_cannot_win_a_race(db):
    # The race this guards against: active ordinal 10; A (ordinal 30) and B
    # (ordinal 20) each read active=10 and pass their own staleness check;
    # A activates; without serialization B -- having already read stale
    # state -- can still activate afterwards and supersede A, rolling the
    # active pointer backward even though both individually "passed". Two
    # real, concurrently-open Postgres sessions (not two sequential calls)
    # are required to prove the advisory lock actually blocks the second
    # activation until the first has committed, rather than merely
    # asserting the ordinal check's logic in isolation.
    empty = {"brands": 0, "models": 0, "generations": 0,
             "market_trims": 0, "price_ledger": 0, "spec_facts": 0}
    baseline = "vehicle-2026-1010101010101010"
    assert _begin(db, _manifest(baseline, ordinal=10, counts=empty))[0]
    assert _activate(db, baseline)[0]

    release_a = "vehicle-2026-3030303030303030"
    release_b = "vehicle-2026-2020202020202020"
    assert _begin(db, _manifest(release_a, ordinal=30, counts=empty))[0]
    assert _begin(db, _manifest(release_b, ordinal=20, counts=empty))[0]

    session_a = _popen_psql(db)
    session_a.stdin.write(f"""
        begin;
        select public.activate_vehicle_release('{release_a}');
        select pg_sleep(2);
        commit;
    """)
    session_a.stdin.close()
    session_a.stdin = None  # already closed -- communicate() must not touch it again

    time.sleep(0.5)  # let A acquire the advisory lock and enter its sleep first

    session_b = _popen_psql(db)
    session_b.stdin.write(f"select public.activate_vehicle_release('{release_b}');")
    session_b.stdin.close()
    session_b.stdin = None

    _, err_a = session_a.communicate(timeout=30)
    _, err_b = session_b.communicate(timeout=30)

    assert session_a.returncode == 0, err_a
    assert session_b.returncode != 0, "B should have been refused once A (ordinal 30) activated"
    assert "stale revision" in err_b

    assert db.rows(
        "select active_release_id from public.canonical_vehicle_state "
        "where scope = 'vehicle_catalog'") == [[release_a]]
    assert db.rows(
        "select status from public.canonical_vehicle_releases "
        f"where release_id = '{release_b}'") == [["STAGING"]]


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


# ---------------------------------------------------------------------
# The actual ECO-sized workload: ~20,800 spec facts, ~819 price rows,
# staged through the production chunk size, against real Postgres.
# ---------------------------------------------------------------------

def _build_eco_sized_catalog() -> dict[str, list[dict]]:
    n_brands, n_models, n_trims, n_prices, n_specs = 20, 300, 820, 819, 20_800

    brands = [{"canonical_id": f"brand{i}", "slug": f"brand{i}", "name_en": f"Brand {i}",
              "payload": {}} for i in range(n_brands)]

    trims_per_model = [n_trims // n_models] * n_models
    for i in range(n_trims - sum(trims_per_model)):
        trims_per_model[i] += 1

    models, generations, trims = [], [], []
    for m in range(n_models):
        brand_id = f"brand{m % n_brands}"
        model_id = f"{brand_id}.model{m}"
        models.append({"canonical_id": model_id, "brand_id": brand_id, "slug": f"model{m}",
                       "name_en": f"Model {m}", "status": "CURRENT", "payload": {}})
        gen_id = f"{model_id}.gen1"
        generations.append({"canonical_id": gen_id, "model_id": model_id, "code": "G1", "payload": {}})
        for t in range(trims_per_model[m]):
            trim_id = f"{gen_id}.trim{t}"
            trims.append({"canonical_id": trim_id, "model_id": model_id, "generation_id": gen_id,
                          "name": f"Trim {t}", "powertrain": "ICE", "status": "CURRENT", "payload": {}})
    assert len(trims) == n_trims

    prices = [
        {"record_id": f"{trim['canonical_id']}.price", "trim_id": trim["canonical_id"],
         "amount_thb": 1_000_000 + i, "price_type": "LIST_PRICE",
         "observed_at": "2026-09-01", "payload": {}}
        for i, trim in enumerate(trims[:n_prices])
    ]
    assert len(prices) == n_prices

    field_keys = [f"field.{i}" for i in range(40)]
    base_per_trim, remainder = divmod(n_specs, len(trims))
    specs = []
    for i, trim in enumerate(trims):
        count = base_per_trim + (1 if i < remainder else 0)
        for k in range(count):
            specs.append({"fact_id": f"{trim['canonical_id']}.fact{k}", "trim_id": trim["canonical_id"],
                          "field_key": field_keys[k % len(field_keys)],
                          "verification_status": "VERIFIED", "payload": {}})
    assert len(specs) == n_specs

    return {"brands": brands, "models": models, "generations": generations,
           "market_trims": trims, "price_ledger": prices, "spec_facts": specs}


def test_staged_publish_round_trips_an_eco_sized_release(db):
    """Approximately the real September 2026 ECO Sticker release's actual
    scale -- ~20,800 spec facts, ~819 price rows -- staged through the
    real production chunk size (tdr_bridge.publish.CHUNK_SIZE) and the
    real v48 functions, not a convenient small catalog picked for test
    speed. This is the workload publish_vehicle_release's single
    transaction measured ~34.5s for and still could not finish within its
    45s statement_timeout; staging it is the actual point of this
    migration, so it has to be proven at this scale, not just at the
    toy scale the other tests in this file use for everything else."""
    from tdr_bridge.publish import CHUNK_SIZE, RELEASE_SECTIONS

    empty = {"brands": 0, "models": 0, "generations": 0,
             "market_trims": 0, "price_ledger": 0, "spec_facts": 0}
    baseline = "vehicle-2026-b000000000000000"
    assert _begin(db, _manifest(baseline, counts=empty))[0]
    assert _activate(db, baseline)[0]

    catalog = _build_eco_sized_catalog()
    counts = {section: len(catalog[section]) for section in RELEASE_SECTIONS}
    rid = "vehicle-2026-ec0000000000000e"

    t0 = time.monotonic()
    ok, err = _begin(db, _manifest(rid, counts=counts))
    assert ok, err
    begin_seconds = time.monotonic() - t0

    stage_timings: dict[str, float] = {}
    t_stage_start = time.monotonic()
    for section in RELEASE_SECTIONS:
        rows = catalog[section]
        statements = []
        for index in range(0, len(rows), CHUNK_SIZE):
            chunk = rows[index:index + CHUNK_SIZE]
            chunk_hash = hashlib.sha256(_q(chunk).encode()).hexdigest()
            statements.append(
                f"select public.stage_vehicle_release_chunk("
                f"'{rid}', '{section}', {index // CHUNK_SIZE}, '{chunk_hash}', "
                f"'{_q(chunk)}'::jsonb);"
            )
        t_section = time.monotonic()
        db.sql("\n".join(statements))
        stage_timings[section] = time.monotonic() - t_section

        # Staging this (large, multi-chunk, multi-second) release must not
        # move the pointer -- the old active release is still what is
        # serving after every section, not just before the first one.
        assert db.rows(
            "select active_release_id from public.canonical_vehicle_state "
            "where scope = 'vehicle_catalog'") == [[baseline]]
    total_stage_seconds = time.monotonic() - t_stage_start

    t_activate = time.monotonic()
    ok, err = _activate(db, rid)
    assert ok, err
    activate_seconds = time.monotonic() - t_activate

    print(
        f"\n[eco-sized staged publish] begin={begin_seconds:.2f}s "
        f"stage_total={total_stage_seconds:.2f}s {stage_timings} "
        f"activate={activate_seconds:.2f}s"
    )

    # The pointer changed only now, at activation.
    assert db.rows(
        "select active_release_id from public.canonical_vehicle_state "
        "where scope = 'vehicle_catalog'") == [[rid]]
    assert db.rows(
        f"select status from public.canonical_vehicle_releases "
        f"where release_id = '{baseline}'") == [["SUPERSEDED"]]

    # Real counts, from the real projection tables -- not the chunk
    # ledger's own bookkeeping, which activation already trusted to decide
    # this could proceed at all.
    for section, table in (
        ("brands", "canonical_brand_projection"),
        ("models", "canonical_model_projection"),
        ("generations", "canonical_generation_projection"),
        ("market_trims", "canonical_market_trim_projection"),
        ("price_ledger", "canonical_price_projection"),
        ("spec_facts", "canonical_spec_projection"),
    ):
        assert db.scalar(
            f"select count(*) from public.{table} where release_id = '{rid}'"
        ) == str(counts[section])
    assert counts["price_ledger"] == 819
    assert counts["spec_facts"] == 20_800
