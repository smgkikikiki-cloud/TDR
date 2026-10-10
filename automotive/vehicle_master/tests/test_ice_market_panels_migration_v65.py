"""Market Track R5 production fix (migration_v65): ice_commit_staged_import's DELETEs carry a WHERE clause.

Production rejects an unconditional DELETE (`DELETE requires a WHERE clause`, SQLSTATE 21000: the
safe-update guard on API roles). migration_v62's commit function used `delete from public.%I`, so the
real R5 import staged the whole Ice package and then failed at the first replace-whole-set DELETE.
The repository's CI Postgres does not load that guard, so the v62 tests could not see it. These tests
therefore check the delete *statements themselves* (statically, and on the function as applied), and
prove the fixed function still commits exactly as before.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.pg_cluster import apply_production_schema, migration_files, pg  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
V62 = ROOT / "supabase" / "migration_v62_ice_market_panels.sql"
V65 = ROOT / "supabase" / "migration_v65_ice_commit_delete_where.sql"

COMMIT_SQL = (
    "select public.ice_commit_staged_import("
    "'2569-08', 1, 'M1', 'พร้อมส่ง', '[\"A\",\"B\"]'::jsonb, '{}'::jsonb, '[]'::jsonb, 'tester');"
)
LIVE_TABLES = (
    "ice_reg_province", "ice_reg_trend", "ice_reg_powertrain", "ice_rim_province",
    "ice_tyre_province", "ice_tyre_coverage", "ice_dims_brand", "ice_dims_province",
    "ice_dims_reg_type", "ice_dims_fuel", "ice_dims_tyre", "ice_dims_model_group",
)

#: `delete from <target ...>` up to the quote or semicolon that ends the statement text.
DELETE_STATEMENT = re.compile(r"delete\s+from\s+([^;'\"]*)", re.IGNORECASE)


def unconditional_deletes(sql: str) -> list[str]:
    """Every DELETE in `sql` that has no WHERE clause (what production's guard refuses)."""
    return [m.group(0).strip() for m in DELETE_STATEMENT.finditer(sql)
            if not re.search(r"\bwhere\b", m.group(1), re.IGNORECASE)]


def function_definition(sql: str, name: str) -> str:
    start = sql.index(f"create or replace function public.{name}(")
    return sql[start:sql.index("$$;", sql.index("as $$", start)) + 3]


# ---------------------------------------------------------------------------
# Static: the guard is detected, and the final definition obeys it
# ---------------------------------------------------------------------------

def test_the_checker_catches_the_unconditional_deletes_that_failed_in_production():
    v62 = function_definition(V62.read_text(encoding="utf-8"), "ice_commit_staged_import")
    found = unconditional_deletes(v62)
    assert len(found) == 2, found  # the live-table delete and the staging delete


def test_v65_replaces_both_deletes_with_where_true_and_nothing_else_changes_semantics():
    v65 = function_definition(V65.read_text(encoding="utf-8"), "ice_commit_staged_import")
    assert unconditional_deletes(v65) == []
    assert v65.count("where true") == 2
    v62 = function_definition(V62.read_text(encoding="utf-8"), "ice_commit_staged_import")
    # The only difference between the two bodies is the two WHERE clauses.
    assert v65.replace(" where true", "") == v62


def test_the_last_migration_defining_the_commit_function_has_no_unconditional_delete():
    final = None
    for path in migration_files():
        text = path.read_text(encoding="utf-8")
        if "create or replace function public.ice_commit_staged_import(" in text:
            final = (path, function_definition(text, "ice_commit_staged_import"))
    assert final is not None and final[0] == V65
    assert unconditional_deletes(final[1]) == []


def test_v65_keeps_the_function_service_role_only():
    text = V65.read_text(encoding="utf-8")
    assert "from public, anon, authenticated" in text
    assert "to service_role" in text
    assert "to anon" not in text and "to authenticated" not in text


# ---------------------------------------------------------------------------
# Real Postgres: the applied function has the WHERE clauses and still commits
# ---------------------------------------------------------------------------

@pytest.fixture
def db(pg):
    apply_production_schema(pg, through=65)
    return pg


def test_v65_replays_and_is_idempotent(db):
    ok, err = db.try_sql(V65.read_text(encoding="utf-8"))
    assert ok, err


def test_the_applied_function_has_no_unconditional_delete(db):
    definition = db.scalar(
        "select pg_get_functiondef('public.ice_commit_staged_import("
        "text, integer, text, text, jsonb, jsonb, jsonb, text)'::regprocedure)")
    assert unconditional_deletes(definition) == []


def _stage_minimal_valid_set(db):
    db.sql("insert into public.ice_dims_brand_staging (brand) values ('TOY');")
    db.sql("insert into public.ice_dims_province_staging (province) values ('x');")
    db.sql("insert into public.ice_dims_reg_type_staging (reg_type) values ('y');")
    db.sql("insert into public.ice_dims_fuel_staging (fuel_dlt, fuel_group) values ('petrol', 'ICE');")
    db.sql("insert into public.ice_dims_tyre_staging (tyre_size, rim_inch) values ('205/55R16', 16);")
    db.sql("insert into public.ice_dims_model_group_staging "
           "(model_group_id, model_name, brand, reg_total_all) values ('m1', 'M1', 'TOY', 1);")
    db.sql("insert into public.ice_reg_province_staging "
           "(period, province, reg_type, brand, fuel_group, reg_count) "
           "values ('2569-08', 'x', 'y', 'TOY', 'ICE', 1);")
    db.sql("insert into public.ice_reg_trend_staging "
           "(period, province, reg_type, brand, model_group_id, model_name, reg_count) "
           "values ('2569-08', 'x', 'y', 'TOY', 'm1', 'M1', 1);")
    db.sql("insert into public.ice_reg_powertrain_staging "
           "(period, province, reg_type, brand, model_group_id, model_name, fuel_group, certainty) "
           "values ('2569-08', 'x', 'y', 'TOY', 'm1', 'M1', 'ICE', 'exact');")
    db.sql("insert into public.ice_rim_province_staging "
           "(period, province, reg_type, brand, rim_bucket, reg_est) "
           "values ('2569-08', 'x', 'y', 'TOY', '16', 1);")
    db.sql("insert into public.ice_tyre_province_staging "
           "(period, province, reg_type, brand, tyre_size, rim_inch, reg_est) "
           "values ('2569-08', 'x', 'y', 'TOY', '205/55R16', 16, 1);")
    db.sql("insert into public.ice_tyre_coverage_staging "
           "(period, province, reg_type, brand, reg_total, reg_tyre_known) "
           "values ('2569-08', 'x', 'y', 'TOY', 1, 1);")


def test_the_fixed_function_still_replaces_the_whole_set_and_records_the_import(db):
    # A stale live row must be replaced, not merged: the DELETE ... WHERE true still removes every row.
    db.sql("insert into public.ice_dims_brand (brand) values ('OLD');")
    _stage_minimal_valid_set(db)
    ok, err = db.try_sql(COMMIT_SQL)
    assert ok, err
    assert db.scalar("select string_agg(brand, ',') from public.ice_dims_brand") == "TOY"
    for table in LIVE_TABLES:
        assert db.scalar(f"select count(*) from public.{table}") == "1", table
        assert db.scalar(f"select count(*) from public.{table}_staging") == "0", table
    assert db.scalar("select count(*) from public.ice_package_imports") == "1"
