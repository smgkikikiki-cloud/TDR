"""Market Track M2: the private Ice panel tables (migration_v62)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.pg_cluster import apply_production_schema, pg  # noqa: F401

V62_TABLES = (
    "ice_package_imports",
    "ice_dims_brand", "ice_dims_province", "ice_dims_reg_type", "ice_dims_fuel",
    "ice_dims_tyre", "ice_dims_model_group",
    "ice_reg_province", "ice_reg_trend", "ice_reg_powertrain",
    "ice_rim_province", "ice_tyre_province", "ice_tyre_coverage",
)

ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = ROOT / "supabase" / "migration_v62_ice_market_panels.sql"


@pytest.fixture
def db(pg):
    apply_production_schema(pg, through=62)
    return pg


def test_v62_replays_and_is_idempotent(db):
    ok, err = db.try_sql(MIGRATION_PATH.read_text(encoding="utf-8"))
    assert ok, err


@pytest.mark.parametrize("table", V62_TABLES)
def test_every_table_is_private_to_service_role(db, table: str):
    assert db.scalar(f"select has_table_privilege('service_role','public.{table}','SELECT')") == "t"
    assert db.scalar(f"select has_table_privilege('service_role','public.{table}','INSERT')") == "t"
    assert db.scalar(f"select has_table_privilege('service_role','public.{table}','DELETE')") == "t"
    for role in ("anon", "authenticated"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert db.scalar(
                f"select has_table_privilege('{role}','public.{table}','{privilege}')"
            ) == "f", (table, role, privilege)


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


def test_replace_whole_set_is_representable_without_a_full_table_lock_error(db):
    # The "replace" pattern the importer uses: delete every row (PK is NOT NULL,
    # so filtering on it true matches everything), then reinsert.
    db.sql(
        "insert into public.ice_dims_brand (brand) values ('TOY'), ('HON');")
    ok, err = db.try_sql("delete from public.ice_dims_brand where brand is not null;")
    assert ok, err
    assert db.scalar("select count(*) from public.ice_dims_brand") == "0"


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
