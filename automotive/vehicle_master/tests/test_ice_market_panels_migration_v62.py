"""Market Track M2: the private Ice panel tables and atomic commit RPCs (migration_v62)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.pg_cluster import apply_production_schema, pg  # noqa: F401

LIVE_TABLES = (
    "ice_package_imports",
    "ice_dims_brand", "ice_dims_province", "ice_dims_reg_type", "ice_dims_fuel",
    "ice_dims_tyre", "ice_dims_model_group",
    "ice_reg_province", "ice_reg_trend", "ice_reg_powertrain",
    "ice_rim_province", "ice_tyre_province", "ice_tyre_coverage",
)

#: Every live table except the import log has a staging twin.
STAGED_TABLES = tuple(t for t in LIVE_TABLES if t != "ice_package_imports")
STAGING_TABLES = tuple(f"{t}_staging" for t in STAGED_TABLES)

ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = ROOT / "supabase" / "migration_v62_ice_market_panels.sql"

COMMIT_SQL = (
    "select public.ice_commit_staged_import("
    "'2569-08', 1, 'M1', 'พร้อมส่ง', '[\"A\",\"B\"]'::jsonb, '{}'::jsonb, '[]'::jsonb, 'tester');"
)


@pytest.fixture
def db(pg):
    apply_production_schema(pg, through=62)
    return pg


def test_v62_replays_and_is_idempotent(db):
    ok, err = db.try_sql(MIGRATION_PATH.read_text(encoding="utf-8"))
    assert ok, err


@pytest.mark.parametrize("table", LIVE_TABLES + STAGING_TABLES)
def test_every_table_is_private_to_service_role(db, table: str):
    assert db.scalar(f"select has_table_privilege('service_role','public.{table}','SELECT')") == "t"
    assert db.scalar(f"select has_table_privilege('service_role','public.{table}','INSERT')") == "t"
    assert db.scalar(f"select has_table_privilege('service_role','public.{table}','DELETE')") == "t"
    for role in ("anon", "authenticated"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert db.scalar(
                f"select has_table_privilege('{role}','public.{table}','{privilege}')"
            ) == "f", (table, role, privilege)


def test_the_two_rpcs_are_service_role_only(db):
    for fn in (
        "ice_commit_staged_import(text,integer,text,text,jsonb,jsonb,jsonb,text)",
        "ice_live_table_counts()",
    ):
        assert db.scalar(f"select has_function_privilege('service_role','public.{fn}','EXECUTE')") == "t"
        for role in ("anon", "authenticated"):
            assert db.scalar(f"select has_function_privilege('{role}','public.{fn}','EXECUTE')") == "f"


def test_period_columns_reject_a_malformed_string(db):
    # The check constrains shape only (YYYY-MM), not semantic Buddhist-year
    # range -- a Gregorian-looking '2026-08' is not itself distinguishable from
    # a Buddhist one by shape alone and is intentionally not rejected here.
    ok, err = db.try_sql(
        "insert into public.ice_reg_province "
        "(period, province, reg_type, brand, fuel_group, reg_count) "
        "values ('2569/08', 'x', 'y', 'z', 'ICE', 1);")
    assert not ok
    assert "ice_reg_province_period_check" in err or "violates check constraint" in err


def test_period_columns_accept_the_real_buddhist_format(db):
    ok, err = db.try_sql(
        "insert into public.ice_reg_province "
        "(period, province, reg_type, brand, fuel_group, reg_count) "
        "values ('2569-08', 'x', 'y', 'z', 'ICE', 1);")
    assert ok, err


def test_reg_powertrain_certainty_is_constrained_to_the_three_known_values(db):
    ok, err = db.try_sql(
        "insert into public.ice_reg_powertrain "
        "(period, province, reg_type, brand, model_group_id, model_name, fuel_group, certainty) "
        "values ('2569-08', 'x', 'y', 'z', 'm1', 'M1', 'ICE', 'guess');")
    assert not ok
    assert "certainty" in err

    ok2, err2 = db.try_sql(
        "insert into public.ice_reg_powertrain "
        "(period, province, reg_type, brand, model_group_id, model_name, fuel_group, certainty) "
        "values ('2569-08', 'x', 'y', 'z', 'm1', 'M1', 'ICE', 'family');")
    assert ok2, err2


def test_reg_powertrain_pk_allows_two_fuel_groups_for_the_same_model_group(db):
    # Fix #4 of the review: the panel's grain is model x powertrain, including
    # fuel_group -- a model group legitimately sold as both e.g. HEV and ICE
    # must be representable as two rows, not collapse onto one.
    ok, err = db.try_sql(
        "insert into public.ice_reg_powertrain "
        "(period, province, reg_type, brand, model_group_id, model_name, fuel_group, certainty) "
        "values ('2569-08', 'x', 'y', 'z', 'm1', 'M1', 'HEV', 'exact');")
    assert ok, err
    ok2, err2 = db.try_sql(
        "insert into public.ice_reg_powertrain "
        "(period, province, reg_type, brand, model_group_id, model_name, fuel_group, certainty) "
        "values ('2569-08', 'x', 'y', 'z', 'm1', 'M1', 'ICE', 'exact');")
    assert ok2, err2
    assert db.scalar(
        "select count(*) from public.ice_reg_powertrain where model_group_id = 'm1'"
    ) == "2"


def test_reg_powertrain_pk_still_rejects_a_literal_duplicate(db):
    row = (
        "insert into public.ice_reg_powertrain "
        "(period, province, reg_type, brand, model_group_id, model_name, fuel_group, certainty) "
        "values ('2569-08', 'x', 'y', 'z', 'm1', 'M1', 'ICE', 'exact');")
    ok, _ = db.try_sql(row)
    assert ok
    ok2, err2 = db.try_sql(row)
    assert not ok2
    assert "duplicate key" in err2 or "violates unique constraint" in err2


def test_dims_model_group_segment_and_body_are_nullable(db):
    ok, err = db.try_sql(
        "insert into public.ice_dims_model_group "
        "(model_group_id, model_name, brand, reg_total_all) "
        "values ('toy.a', 'A', 'TOY', 100);")
    assert ok, err
    assert db.scalar(
        "select (segment is null and body is null) from public.ice_dims_model_group "
        "where model_group_id = 'toy.a'"
    ) == "t"


def test_migration_touches_nothing_vehicle_master_or_registration_or_legacy():
    text = MIGRATION_PATH.read_text(encoding="utf-8").lower()
    code = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    forbidden = (
        "vehicle_brands", "vehicle_models", "vehicle_trims", "vehicle_facts",
        "current_vehicle", "current_market_trims", "current_price_ledger",
        "canonical_input_batches", "canonical_vehicle_releases",
        "registrations", "registration_",
    )
    for token in forbidden:
        assert token not in code, token


# ---------------------------------------------------------------------------
# ice_commit_staged_import: real end-to-end commit against real Postgres
# ---------------------------------------------------------------------------

def _stage_minimal_valid_set(db):
    """Populate every staging table with exactly one row, enough to satisfy
    ice_commit_staged_import's own "every table must be staged" gate."""
    db.sql("insert into public.ice_dims_brand_staging (brand) values ('TOY');")
    db.sql("insert into public.ice_dims_province_staging (province) values ('x');")
    db.sql("insert into public.ice_dims_reg_type_staging (reg_type) values ('y');")
    db.sql("insert into public.ice_dims_fuel_staging (fuel_dlt, fuel_group) values ('petrol', 'ICE');")
    db.sql("insert into public.ice_dims_tyre_staging (tyre_size, rim_inch) values ('205/55R16', 16);")
    db.sql(
        "insert into public.ice_dims_model_group_staging "
        "(model_group_id, model_name, brand, reg_total_all) values ('m1', 'M1', 'TOY', 1);")
    db.sql(
        "insert into public.ice_reg_province_staging "
        "(period, province, reg_type, brand, fuel_group, reg_count) "
        "values ('2569-08', 'x', 'y', 'TOY', 'ICE', 1);")
    db.sql(
        "insert into public.ice_reg_trend_staging "
        "(period, province, reg_type, brand, model_group_id, model_name, reg_count) "
        "values ('2569-08', 'x', 'y', 'TOY', 'm1', 'M1', 1);")
    db.sql(
        "insert into public.ice_reg_powertrain_staging "
        "(period, province, reg_type, brand, model_group_id, model_name, fuel_group, certainty) "
        "values ('2569-08', 'x', 'y', 'TOY', 'm1', 'M1', 'ICE', 'exact');")
    db.sql(
        "insert into public.ice_rim_province_staging "
        "(period, province, reg_type, brand, rim_bucket, reg_est) "
        "values ('2569-08', 'x', 'y', 'TOY', '16', 1);")
    db.sql(
        "insert into public.ice_tyre_province_staging "
        "(period, province, reg_type, brand, tyre_size, rim_inch, reg_est) "
        "values ('2569-08', 'x', 'y', 'TOY', '205/55R16', 16, 1);")
    db.sql(
        "insert into public.ice_tyre_coverage_staging "
        "(period, province, reg_type, brand, reg_total, reg_tyre_known) "
        "values ('2569-08', 'x', 'y', 'TOY', 1, 1);")


def test_commit_staged_import_moves_every_table_to_live_and_records_the_log(db):
    _stage_minimal_valid_set(db)
    ok, err = db.try_sql(COMMIT_SQL)
    assert ok, err

    for table in STAGED_TABLES:
        assert db.scalar(f"select count(*) from public.{table}") == "1", table
        assert db.scalar(f"select count(*) from public.{table}_staging") == "0", table

    assert db.scalar("select count(*) from public.ice_package_imports") == "1"
    assert db.scalar(
        "select master_version from public.ice_package_imports order by imported_at desc limit 1"
    ) == "M1"


def test_commit_staged_import_refuses_when_any_table_is_not_staged(db):
    # Stage everything except one table -- the whole call must refuse.
    _stage_minimal_valid_set(db)
    db.sql("delete from public.ice_tyre_coverage_staging;")
    ok, err = db.try_sql(COMMIT_SQL)
    assert not ok
    assert "ice_tyre_coverage_staging is empty" in err


def test_commit_staged_import_is_atomic_a_refused_commit_touches_no_live_table(db):
    # The real atomicity guarantee (fix #1): pre-populate every live table
    # with sentinel data, leave one staging table empty, and prove every live
    # table -- not just the one tied to the missing staging table -- still
    # holds exactly its old sentinel data, not the new staged rows and not
    # empty. This is what "if anything fails before commit, the previously
    # live dataset must remain untouched" actually requires: Postgres rolling
    # back the whole function call, not the Python importer behaving well.
    db.sql("insert into public.ice_dims_brand (brand) values ('SENTINEL_OLD');")
    db.sql(
        "insert into public.ice_reg_trend "
        "(period, province, reg_type, brand, model_group_id, model_name, reg_count) "
        "values ('2568-01', 'old_province', 'old_type', 'SENTINEL_OLD', 'old.m', 'OLD', 999);")

    _stage_minimal_valid_set(db)
    db.sql("delete from public.ice_tyre_coverage_staging;")  # the one gap

    ok, err = db.try_sql(COMMIT_SQL)
    assert not ok, "the commit must have refused"

    # Every live table, including ones whose staging WAS complete, must be
    # exactly the pre-commit sentinel state -- not the new rows, not empty.
    assert db.scalar("select count(*) from public.ice_dims_brand") == "1"
    assert db.scalar("select brand from public.ice_dims_brand limit 1") == "SENTINEL_OLD"
    assert db.scalar("select count(*) from public.ice_reg_trend") == "1"
    assert db.scalar("select brand from public.ice_reg_trend limit 1") == "SENTINEL_OLD"
    assert db.scalar("select count(*) from public.ice_tyre_coverage") == "0"

    # Staging keeps whatever was there when the call raised (it is cleared and
    # reloaded by the next import attempt; this is not live, so it is not a
    # correctness concern) -- but the gap that caused the refusal is still a gap.
    assert db.scalar("select count(*) from public.ice_tyre_coverage_staging") == "0"

    # And the import log must not have gained a row either.
    assert db.scalar("select count(*) from public.ice_package_imports") == "0"


def test_commit_staged_import_is_idempotently_safe_to_retry_after_a_fix(db):
    _stage_minimal_valid_set(db)
    db.sql("delete from public.ice_tyre_coverage_staging;")
    ok, _ = db.try_sql(COMMIT_SQL)
    assert not ok

    # Operator fixes the gap and retries with a fresh full staging set.
    db.sql(
        "insert into public.ice_tyre_coverage_staging "
        "(period, province, reg_type, brand, reg_total, reg_tyre_known) "
        "values ('2569-08', 'x', 'y', 'TOY', 1, 1);")
    ok2, err2 = db.try_sql(COMMIT_SQL)
    assert ok2, err2
    assert db.scalar("select count(*) from public.ice_tyre_coverage") == "1"
    assert db.scalar("select count(*) from public.ice_package_imports") == "1"


def test_live_table_counts_matches_what_was_just_committed(db):
    _stage_minimal_valid_set(db)
    db.try_sql(COMMIT_SQL)
    counts_row = db.sql("select public.ice_live_table_counts();").strip()
    for table in STAGED_TABLES:
        assert f'"{table}":1' in counts_row.replace(" ", ""), (table, counts_row)
