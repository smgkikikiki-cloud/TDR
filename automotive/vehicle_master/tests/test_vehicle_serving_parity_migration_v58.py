"""migration_v58 (Vehicle DB v3 Phase 0 step 3) against a real Postgres.

The six current_* views switch from the release projections to the master
tables. These tests pin that the switch only commits when the new output
equals the old output row for row and value for value, that the parity
check is not a view compared with itself and reports a drift with the ids
and columns involved, that browser roles see exactly what they saw and
nothing more of the master, and that the release pointer can no longer move
away from what is served.
"""

from __future__ import annotations

import pytest

from tests.pg_cluster import SUPABASE, apply_production_schema, pg  # noqa: F401
from tests.test_vehicle_master_tables_migration_v57 import (
    AS_OF, MODEL, OVERLAY, RID, RID_NEXT, TRIM, _publish, _release, _rpc, _sections)
from tools import vehicle_master_seed as seed

V58 = SUPABASE / "migration_v58_vehicle_serving_parity.sql"
VIEWS = {
    "current_vehicle_brands": ("canonical_brand_projection", "canonical_id"),
    "current_vehicle_models": ("canonical_model_projection", "canonical_id"),
    "current_vehicle_generations": ("canonical_generation_projection", "canonical_id"),
    "current_market_trims": ("canonical_market_trim_projection", "canonical_id"),
    "current_spec_facts": ("canonical_spec_projection", "fact_id"),
    "current_price_ledger": ("canonical_price_projection", "record_id"),
}
CHECKS = ("columns_differ", "reads_master_not_projection", "security_invoker", "row_count",
          "duplicate_ids", "ids_missing", "ids_extra", "values_differ",
          "rows_old_not_in_new", "rows_new_not_in_old")
BROWSER = ("anon", "authenticated")
MASTER_TABLES = (
    "vehicle_master_state", "vehicle_master_seed_runs", "vehicle_brands", "vehicle_models",
    "vehicle_generations", "vehicle_variants", "vehicle_trims", "vehicle_facts",
    "vehicle_price_ledger", "vehicle_campaigns", "vehicle_promotions", "vehicle_eco_evidence",
    "vehicle_current_retail_sets", "vehicle_trim_lifecycle_decisions",
    "vehicle_model_operational_states", "vehicle_legacy_identities")
#: Readable by browser roles after v58: the served columns plus each view's filter column.
SERVED_COLUMNS = {
    "vehicle_master_state": {"scope", "seed_release_id"},
    "vehicle_brands": {"canonical_id", "tdr_brand_id", "slug", "name_en", "name_th",
                       "origin_country", "payload", "deleted_at"},
    "vehicle_models": {"canonical_id", "tdr_model_id", "brand_id", "slug", "name_en", "name_th",
                       "generation_id", "status", "segment", "body_type", "retail_price_min",
                       "retail_price_max", "payload", "deleted_at"},
    "vehicle_generations": {"canonical_id", "model_id", "code", "segment", "launched", "ended",
                            "payload", "deleted_at"},
    "vehicle_trims": {"canonical_id", "model_id", "generation_id", "variant_id", "name",
                      "powertrain", "status", "payload", "current_list_price", "campaign_quote",
                      "price_history", "source_refs", "deleted_at"},
    "vehicle_price_ledger": {"record_id", "trim_id", "amount_thb", "price_type", "effective_from",
                             "effective_to", "observed_at", "campaign_id", "option_id", "source",
                             "source_ref", "payload", "in_release"},
    "vehicle_facts": {"fact_id", "trim_id", "field_key", "verification_status", "payload",
                      "served_in_release"},
}
RETRACTED = "b" * 24


def _old_rows(db, view: str, role: str | None = None) -> list[list[str]]:
    """The v15 view body over the projections -- what current_* served before."""
    projection, key = VIEWS[view]
    prefix = f"set role {role}; " if role else ""
    return db.rows(
        f"{prefix}select to_jsonb(r)::text from (select p.* from public.{projection} p"
        f" join public.canonical_vehicle_state s on s.scope = 'vehicle_catalog'"
        f" and s.active_release_id = p.release_id) r order by r.{key}")


def _new_rows(db, view: str, role: str | None = None) -> list[list[str]]:
    key = VIEWS[view][1]
    prefix = f"set role {role}; " if role else ""
    return db.rows(f"{prefix}select to_jsonb(r)::text from public.{view} r order by r.{key}")


def _parity(db) -> dict[tuple[str, str], tuple[str, bool, str]]:
    rows = db.rows("select view_name, check_name, actual, ok, coalesce(detail::text, '')"
                   " from public.vehicle_serving_parity_check()")
    return {(r[0], r[1]): (r[2], r[3] == "t", r[4]) for r in rows}


def _apply_v58(db) -> tuple[bool, str]:
    return db.try_sql(V58.read_text(encoding="utf-8"))


def _view_sources(db, view: str) -> set[str]:
    return {r[0] for r in db.rows(
        "select distinct d.refobjid::regclass::text from pg_rewrite rw join pg_depend d"
        " on d.classid = 'pg_rewrite'::regclass and d.objid = rw.oid"
        " and d.refclassid = 'pg_class'::regclass and d.refobjid <> rw.ev_class"
        f" where rw.ev_class = 'public.{view}'::regclass")}


def _active(db) -> str:
    return db.scalar("select active_release_id from canonical_vehicle_state where scope = 'vehicle_catalog'")


@pytest.fixture
def before(pg):
    """Production today: v57 applied, the active release published and seeded."""
    # Supabase's service_role carries BYPASSRLS; the bare test role does not.
    pg.sql("alter role service_role bypassrls;")
    apply_production_schema(pg, through=57)
    _publish(pg, _release())
    seed.apply(_sections(), release_id=RID, as_of=AS_OF, rpc=_rpc(pg), log=lambda _: None)
    return pg


@pytest.fixture
def db(before):
    ok, err = _apply_v58(before)
    assert ok, err
    return before


# ---------------------------------------------------------------------------
# Parity
# ---------------------------------------------------------------------------

def test_switch_serves_identical_rows_and_values_for_every_view(before):
    old = {view: _old_rows(before, view) for view in VIEWS}
    old_columns = before.rows(
        "select table_name, ordinal_position, column_name, data_type, is_nullable"
        " from information_schema.columns"
        " where table_schema = 'public' and table_name like 'current\\_%' order by 1, 2")
    assert all(old[view] for view in VIEWS)

    ok, err = _apply_v58(before)
    assert ok, err

    for view in VIEWS:
        assert _new_rows(before, view) == old[view], view
        assert any(s.startswith("vehicle_") for s in _view_sources(before, view)), view
        assert not any(s.endswith("_projection") for s in _view_sources(before, view)), view
    assert before.rows(
        "select table_name, ordinal_position, column_name, data_type, is_nullable"
        " from information_schema.columns"
        " where table_schema = 'public' and table_name like 'current\\_%' order by 1, 2") == old_columns
    # release_id is still the real release id admin actions look up.
    assert before.rows("select distinct release_id from current_market_trims") == [[RID]]
    assert before.rows("select count(*) from pg_class where relname like 'current\\_%'"
                       " and relkind = 'v' and 'security_invoker=true' = any(reloptions)") == [["6"]]


def test_parity_check_passes_every_check_for_every_view(db):
    checks = _parity(db)
    assert {k: v for k, v in checks.items() if not v[1]} == {}
    assert checks[("*", "master_pin_is_active_release")][:2] == ("1", True)
    assert checks[("*", "activation_guard_installed")][:2] == ("1", True)
    for view in VIEWS:
        for name in CHECKS:
            assert (view, name) in checks, (view, name)
    assert checks[("current_market_trims", "row_count")][0] == "2"
    assert checks[("current_price_ledger", "row_count")][0] == "1"   # retracted row not served
    assert checks[("current_spec_facts", "row_count")][0] == "1"     # provisional fact not served


def test_switch_is_refused_and_rolled_back_when_the_master_differs(before):
    before.sql(f"update vehicle_trims set payload = payload || '{{\"x\": 1}}'::jsonb"
               f" where canonical_id = '{TRIM}'")
    ok, err = _apply_v58(before)
    assert not ok
    assert "serving parity failed" in err
    assert "current_market_trims.values_differ expected 0 actual 1" in err
    assert TRIM in err and "payload" in err
    # Nothing switched: every view still reads its projection, no check
    # function, no guard, no browser access to the master.
    for view, (projection, _) in VIEWS.items():
        assert projection in _view_sources(before, view), view
    assert before.scalar("select count(*) from pg_proc where proname = 'vehicle_serving_parity_check'") == "0"
    assert before.scalar("select count(*) from pg_trigger"
                         " where tgname = 'canonical_vehicle_state_master_pin_guard'") == "0"
    ok, err = before.try_sql("set role anon; select canonical_id from public.vehicle_trims;")
    assert not ok and "permission denied" in err


def test_switch_is_refused_when_the_master_is_not_seeded(pg):
    apply_production_schema(pg, through=57)
    _publish(pg, _release())
    ok, err = _apply_v58(pg)
    assert not ok
    assert "current_vehicle_brands.ids_missing expected 0 actual 1" in err
    assert "master_pin_is_active_release" in err


def test_check_reports_ids_values_and_columns_that_drift(db):
    db.sql(f"""
      update vehicle_price_ledger set amount_thb = amount_thb + 1 where in_release;
      update vehicle_models set deleted_at = now() where canonical_id = '{MODEL}';
      update vehicle_facts set served_in_release = true where not served_in_release;
    """)
    checks = _parity(db)
    actual, ok, detail = checks[("current_price_ledger", "values_differ")]
    assert (actual, ok) == ("1", False) and "amount_thb" in detail and "payload" not in detail
    assert checks[("current_price_ledger", "rows_old_not_in_new")][:2] == ("1", False)
    assert checks[("current_vehicle_models", "ids_missing")][:2] == ("1", False)
    assert MODEL in checks[("current_vehicle_models", "ids_missing")][2]
    assert checks[("current_spec_facts", "ids_extra")][:2] == ("1", False)
    assert checks[("current_spec_facts", "row_count")][:2] == ("2", False)
    assert checks[("current_market_trims", "values_differ")][:2] == ("0", True)


def test_check_is_not_a_view_compared_with_itself(db):
    # Point one view back at its projection: rows would match, but the
    # check must still fail because it is no longer reading the master.
    db.sql("""create or replace view public.current_vehicle_brands with (security_invoker = true) as
              select p.* from public.canonical_brand_projection p
              join public.canonical_vehicle_state s
                on s.scope = 'vehicle_catalog' and s.active_release_id = p.release_id""")
    checks = _parity(db)
    actual, ok, detail = checks[("current_vehicle_brands", "reads_master_not_projection")]
    assert (actual, ok) == ("0", False) and "canonical_brand_projection" in detail
    assert checks[("current_vehicle_brands", "values_differ")][:2] == ("0", True)


def test_reapplying_the_migration_is_a_no_op(db):
    snapshot = {view: _new_rows(db, view) for view in VIEWS}
    ok, err = _apply_v58(db)
    assert ok, err
    assert {view: _new_rows(db, view) for view in VIEWS} == snapshot
    assert {k: v for k, v in _parity(db).items() if not v[1]} == {}


def test_empty_database_replays_the_whole_chain(pg):
    apply_production_schema(pg)
    checks = _parity(pg)
    assert {k: v for k, v in checks.items() if not v[1]} == {}


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------

def test_browser_view_output_matches_the_old_contract(before):
    old = {(role, view): _old_rows(before, view, role) for role in BROWSER for view in VIEWS}
    ok, err = _apply_v58(before)
    assert ok, err
    for (role, view), rows in old.items():
        assert rows, (role, view)
        assert _new_rows(before, view, role) == rows, (role, view)


def test_deleted_retracted_and_unserved_rows_are_invisible(db):
    db.sql(f"update vehicle_trims set deleted_at = now() where canonical_id = '{OVERLAY}'")
    for role in BROWSER:
        # Through the views.
        assert db.rows(f"set role {role}; select canonical_id from current_market_trims") == [[TRIM]]
        assert db.rows(f"set role {role}; select record_id from current_price_ledger") == [["a" * 24]]
        assert db.rows(f"set role {role}; select verification_status from current_spec_facts") == [["VERIFIED"]]
        # And directly on the master tables, where RLS applies the same rule.
        assert db.rows(f"set role {role}; select canonical_id from vehicle_trims") == [[TRIM]]
        assert db.scalar(f"set role {role}; select count(*) from vehicle_price_ledger"
                         f" where record_id = '{RETRACTED}'") == "0"
        assert db.scalar(f"set role {role}; select count(*) from vehicle_facts"
                         " where verification_status = 'PROVISIONAL'") == "0"
    # The rows are still there for the server.
    assert db.scalar("set role service_role; select count(*) from vehicle_trims") == "2"
    assert db.scalar("set role service_role; select count(*) from vehicle_price_ledger") == "2"
    assert db.scalar("set role service_role; select count(*) from vehicle_facts") == "2"


def test_internal_columns_and_tables_cannot_be_selected(db):
    for role in BROWSER:
        for table, served in SERVED_COLUMNS.items():
            columns = [r[0] for r in db.rows(
                "select column_name from information_schema.columns"
                f" where table_schema = 'public' and table_name = '{table}'")]
            for column in columns:
                ok, err = db.try_sql(f"set role {role}; select {column} from public.{table} limit 1;")
                if column in served:
                    assert ok, (role, table, column, err)
                else:
                    assert not ok and "permission denied" in err, (role, table, column)
            ok, err = db.try_sql(f"set role {role}; select * from public.{table} limit 1;")
            assert not ok and "permission denied" in err, (role, table)
        for table in set(MASTER_TABLES) - set(SERVED_COLUMNS):
            ok, err = db.try_sql(f"set role {role}; select count(*) from public.{table};")
            assert not ok and "permission denied" in err, (role, table)
        for fn in ("vehicle_serving_parity_check()", "vehicle_master_seed_check()"):
            ok, err = db.try_sql(f"set role {role}; select * from public.{fn};")
            assert not ok and "permission denied" in err, (role, fn)


def test_browser_roles_cannot_write_the_master(db):
    for role in BROWSER:
        for table in MASTER_TABLES:
            for statement in (f"delete from public.{table}",
                              f"update public.{table} set created_at = created_at"
                              if table not in ("vehicle_master_state",)
                              else f"update public.{table} set seed_as_of = seed_as_of",
                              f"insert into public.{table} default values"):
                ok, err = db.try_sql(f"set role {role}; {statement};")
                assert not ok and "permission denied" in err, (role, statement, err)
    assert db.scalar("select count(*) from vehicle_trims") == "2"


def test_service_role_reads_everything_and_runs_the_check(db):
    assert db.scalar("set role service_role; select count(*) from vehicle_price_ledger where not in_release") == "1"
    assert db.scalar("set role service_role; select count(*) from vehicle_trims where catalog_payload is not null") == "1"
    for view in VIEWS:
        assert _new_rows(db, view, "service_role") == _new_rows(db, view), view
    assert db.scalar("set role service_role; select count(*) from vehicle_serving_parity_check() where not ok") == "0"
    assert db.scalar("set role service_role; select count(*) from vehicle_master_seed_check() where not ok") == "0"


# ---------------------------------------------------------------------------
# Transition guard (step 3 -> step 5)
# ---------------------------------------------------------------------------

def test_activating_another_release_is_refused_with_a_diagnostic(db):
    snapshot = {view: _new_rows(db, view) for view in VIEWS}
    release = _release(RID_NEXT)
    release["models"][0]["name_en"] = "Camry Next"
    with pytest.raises(RuntimeError) as raised:
        _publish(db, release)
    message = str(raised.value)
    assert "release activation refused: the Vehicle Master is serving" in message
    assert f"seed pin {RID}" in message and f"cannot activate {RID_NEXT}" in message
    assert f"active_release_id is {RID} and must stay {RID}" in message
    assert "Phase 0 step 3" in message
    # Nothing moved: pointer, release statuses, served rows, parity.
    assert _active(db) == RID
    assert db.rows("select release_id, status from canonical_vehicle_releases order by 1") == [
        [RID, "ACTIVE"], [RID_NEXT, "STAGING"]]
    assert {view: _new_rows(db, view) for view in VIEWS} == snapshot
    assert {k: v for k, v in _parity(db).items() if not v[1]} == {}


def test_every_path_that_moves_the_pointer_is_refused(db):
    with pytest.raises(RuntimeError, match="release activation refused"):
        _publish(db, _release(RID_NEXT))   # leaves RID_NEXT staged, not active
    for statement in (
        f"update canonical_vehicle_state set active_release_id = '{RID_NEXT}'",
        "delete from canonical_vehicle_state",
        f"select public.rollback_vehicle_release('{RID_NEXT}')",
    ):
        ok, err = db.try_sql(f"{statement};")
        assert not ok and "refused" in err, (statement, err)
    assert _active(db) == RID
    # The rollback's own status flips were undone with it.
    assert db.rows("select release_id, status from canonical_vehicle_releases order by 1") == [
        [RID, "ACTIVE"], [RID_NEXT, "STAGING"]]


def test_the_pinned_release_can_still_be_reactivated(db):
    result = db.scalar(f"select public.activate_vehicle_release('{RID}')::text")
    assert '"already_active": true' in result
    db.sql(f"update canonical_vehicle_state set activated_at = now() where scope = 'vehicle_catalog'")
    assert _active(db) == RID


def test_guard_does_nothing_before_the_master_is_seeded(pg):
    # The legacy release RPCs this file exercises were closed by migration_v60
    # (Vehicle DB v3 Phase 0 step 5); their behaviour before the cutover is
    # tested on the schema through v59. The closure itself is
    # test_vehicle_close_old_write_path_migration_v60.py.
    apply_production_schema(pg, through=59)
    _publish(pg, _release())
    _publish(pg, _release(RID_NEXT))
    assert _active(pg) == RID_NEXT
