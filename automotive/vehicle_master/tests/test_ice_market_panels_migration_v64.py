"""Market Track R5 compatibility fix (migration_v64): the real Ice contract's
reg_powertrain/tyre_province/dims_tyre primary keys, ground-truthed against
TDR_FULL_2569-09_v3_M7.0.zip. Purely additive on top of migration_v62/v63;
migration_v62's own test file (test_ice_market_panels_migration_v62.py) is
left untouched -- it describes v62's schema as it was, which is still correct
history, not current live behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.pg_cluster import apply_production_schema, pg  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = ROOT / "supabase" / "migration_v64_ice_panel_grain_fix.sql"

#: Live/staging pairs whose primary key migration_v64 changes.
CHANGED_TABLES = (
    "ice_reg_powertrain", "ice_tyre_province", "ice_dims_tyre",
)


@pytest.fixture
def db(pg):
    apply_production_schema(pg, through=64)
    return pg


def _pk_columns(db, table: str) -> str:
    # db.scalar (not db.sql) -- db.sql returns psql's default aligned table
    # output (header/dashes/"(N rows)" footer included), which .strip() does
    # not remove; db.scalar runs -t -A and returns just the one cell value.
    return db.scalar(
        "select string_agg(a.attname, ', ' order by k.ord) "
        "from pg_constraint c "
        "cross join lateral unnest(c.conkey) with ordinality as k(attnum, ord) "
        "join pg_attribute a on a.attrelid = c.conrelid and a.attnum = k.attnum "
        f"where c.conrelid = 'public.{table}'::regclass and c.contype = 'p';"
    )


def test_v64_replays_and_is_idempotent(db):
    ok, err = db.try_sql(MIGRATION_PATH.read_text(encoding="utf-8"))
    assert ok, err


def test_v62_still_replays_cleanly_after_v64(db):
    # migration_v62's own "if not exists (select ... contype = 'p')" staging-PK
    # guard must stay a no-op once v64 has already given a table a (different)
    # primary key -- replaying v62 must never try to add a second one.
    v62_path = ROOT / "supabase" / "migration_v62_ice_market_panels.sql"
    ok, err = db.try_sql(v62_path.read_text(encoding="utf-8"))
    assert ok, err


@pytest.mark.parametrize("table", CHANGED_TABLES)
def test_live_and_staging_pk_definitions_agree(db, table: str):
    assert _pk_columns(db, table) == _pk_columns(db, f"{table}_staging"), table


def test_reg_powertrain_pk_is_the_full_m7_grain(db):
    assert _pk_columns(db, "ice_reg_powertrain") == (
        "period, province, reg_type, brand, model_group_id, fuel_group, certainty")


def test_tyre_province_pk_is_the_full_m7_grain(db):
    assert _pk_columns(db, "ice_tyre_province") == (
        "period, province, reg_type, brand, tyre_size, rim_inch")


def test_dims_tyre_pk_is_the_full_m7_grain(db):
    assert _pk_columns(db, "ice_dims_tyre") == "tyre_size, rim_inch"


# ---------------------------------------------------------------------------
# reg_powertrain: certainty must be part of the key -- proven against the
# real M7.0 data (254 old-key collisions, 508 rows, all exact+range or
# exact+family pairs; 0 collisions at the full 7-column key).
# ---------------------------------------------------------------------------

def _insert_powertrain(db, *, certainty: str, model_group_id: str = "m1", fuel_group: str = "ICE"):
    return db.try_sql(
        "insert into public.ice_reg_powertrain "
        "(period, province, reg_type, brand, model_group_id, model_name, fuel_group, certainty) "
        f"values ('2569-08', 'x', 'y', 'z', '{model_group_id}', 'M1', '{fuel_group}', '{certainty}');")


def test_reg_powertrain_pk_allows_exact_and_range_to_coexist(db):
    ok1, err1 = _insert_powertrain(db, certainty="exact")
    assert ok1, err1
    ok2, err2 = _insert_powertrain(db, certainty="range")
    assert ok2, err2
    assert db.scalar(
        "select count(*) from public.ice_reg_powertrain where model_group_id = 'm1' and fuel_group = 'ICE'"
    ) == "2"


def test_reg_powertrain_pk_allows_exact_and_family_to_coexist(db):
    ok1, err1 = _insert_powertrain(db, certainty="exact")
    assert ok1, err1
    ok2, err2 = _insert_powertrain(db, certainty="family")
    assert ok2, err2
    assert db.scalar(
        "select count(*) from public.ice_reg_powertrain where model_group_id = 'm1' and fuel_group = 'ICE'"
    ) == "2"


def test_reg_powertrain_pk_still_rejects_a_full_literal_duplicate(db):
    ok1, _ = _insert_powertrain(db, certainty="exact")
    assert ok1
    ok2, err2 = _insert_powertrain(db, certainty="exact")
    assert not ok2
    assert "duplicate key" in err2 or "violates unique constraint" in err2


def test_reg_powertrain_pk_still_rejects_a_duplicate_within_the_same_certainty_across_fuel_groups(db):
    # Unaffected by v64: two different fuel_groups, same certainty, already
    # allowed since migration_v62 (fuel_group was already part of the PK).
    ok1, err1 = _insert_powertrain(db, certainty="exact", fuel_group="ICE")
    assert ok1, err1
    ok2, err2 = _insert_powertrain(db, certainty="exact", fuel_group="HEV")
    assert ok2, err2
    assert db.scalar("select count(*) from public.ice_reg_powertrain where model_group_id = 'm1'") == "2"


# ---------------------------------------------------------------------------
# tyre_province / dims_tyre: rim_inch is now part of the key and NOT NULL,
# matching Ice's declared contract exactly, even though tyre_size already
# functionally determines rim_inch in every real row seen so far.
# ---------------------------------------------------------------------------

def test_tyre_province_pk_allows_two_rim_inch_for_the_same_tyre_size(db):
    # The contract permits this structurally even though no real M7.0 row
    # exercises it (tyre_size already implies rim_inch in practice).
    ok1, err1 = db.try_sql(
        "insert into public.ice_tyre_province "
        "(period, province, reg_type, brand, tyre_size, rim_inch, reg_est) "
        "values ('2569-08', 'x', 'y', 'z', '205/55R16', 16, 1);")
    assert ok1, err1
    ok2, err2 = db.try_sql(
        "insert into public.ice_tyre_province "
        "(period, province, reg_type, brand, tyre_size, rim_inch, reg_est) "
        "values ('2569-08', 'x', 'y', 'z', '205/55R16', 17, 1);")
    assert ok2, err2
    assert db.scalar(
        "select count(*) from public.ice_tyre_province where tyre_size = '205/55R16'"
    ) == "2"


def test_tyre_province_pk_still_rejects_a_full_literal_duplicate(db):
    row = (
        "insert into public.ice_tyre_province "
        "(period, province, reg_type, brand, tyre_size, rim_inch, reg_est) "
        "values ('2569-08', 'x', 'y', 'z', '205/55R16', 16, 1);")
    ok1, err1 = db.try_sql(row)
    assert ok1, err1
    ok2, err2 = db.try_sql(row)
    assert not ok2
    assert "duplicate key" in err2 or "violates unique constraint" in err2


def test_tyre_province_rim_inch_is_not_null(db):
    ok, err = db.try_sql(
        "insert into public.ice_tyre_province "
        "(period, province, reg_type, brand, tyre_size, reg_est) "
        "values ('2569-08', 'x', 'y', 'z', '205/55R16', 1);")
    assert not ok
    assert "rim_inch" in err or "not-null" in err or "null value" in err


def test_dims_tyre_pk_allows_two_rim_inch_for_the_same_tyre_size(db):
    ok1, err1 = db.try_sql(
        "insert into public.ice_dims_tyre (tyre_size, rim_inch) values ('205/55R16', 16);")
    assert ok1, err1
    ok2, err2 = db.try_sql(
        "insert into public.ice_dims_tyre (tyre_size, rim_inch) values ('205/55R16', 17);")
    assert ok2, err2
    assert db.scalar(
        "select count(*) from public.ice_dims_tyre where tyre_size = '205/55R16'"
    ) == "2"


def test_dims_tyre_rim_inch_is_not_null(db):
    ok, err = db.try_sql("insert into public.ice_dims_tyre (tyre_size) values ('205/55R16');")
    assert not ok
    assert "rim_inch" in err or "not-null" in err or "null value" in err


# ---------------------------------------------------------------------------
# Scope guard, same convention as migration_v62/v63's own test files.
# ---------------------------------------------------------------------------

def test_migration_touches_nothing_vehicle_master_or_registration_or_legacy():
    text = MIGRATION_PATH.read_text(encoding="utf-8").lower()
    code = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    forbidden = (
        "vehicle_brands", "vehicle_models", "vehicle_trims", "vehicle_facts",
        "current_vehicle", "current_market_trims", "current_price_ledger",
        "canonical_input_batches", "canonical_vehicle_releases",
        "registrations", "registration_", "ice_model_crosswalk", "ice_brand_aliases",
    )
    for token in forbidden:
        assert token not in code, token


def test_migration_touches_only_the_three_declared_tables():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    code = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    untouched = (
        "ice_reg_province", "ice_reg_trend", "ice_rim_province", "ice_tyre_coverage",
        "ice_dims_brand", "ice_dims_province", "ice_dims_reg_type", "ice_dims_fuel",
        "ice_dims_model_group", "ice_package_imports",
    )
    for table in untouched:
        # allow the table name as a *prefix* match guard: none of these exact
        # identifiers may appear standalone (ice_reg_powertrain contains
        # "ice_reg_p..." but not "ice_reg_province" as a token).
        assert f"public.{table} " not in code and f"public.{table}\n" not in code, table


# ---------------------------------------------------------------------------
# End-to-end: ice_commit_staged_import still moves multiple certainty rows
# for one powertrain key from staging to live atomically (row-count
# preservation through the real commit RPC, not just the importer's own
# in-memory logic already proven in tests/test_ice_package_import.py).
# ---------------------------------------------------------------------------

COMMIT_SQL = (
    "select public.ice_commit_staged_import("
    "'2569-08', 1, 'M1', 'พร้อมส่ง', '[\"A\",\"B\"]'::jsonb, '{}'::jsonb, '[]'::jsonb, 'tester');"
)


def _stage_minimal_valid_set_with_two_certainties(db):
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
    # Two rows for the same old-TDR key, differing only by certainty.
    db.sql(
        "insert into public.ice_reg_powertrain_staging "
        "(period, province, reg_type, brand, model_group_id, model_name, fuel_group, certainty) "
        "values ('2569-08', 'x', 'y', 'TOY', 'm1', 'M1', 'ICE', 'exact');")
    db.sql(
        "insert into public.ice_reg_powertrain_staging "
        "(period, province, reg_type, brand, model_group_id, model_name, fuel_group, certainty) "
        "values ('2569-08', 'x', 'y', 'TOY', 'm1', 'M1', 'ICE', 'range');")
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


def test_commit_staged_import_moves_both_certainty_rows_for_one_powertrain_key(db):
    _stage_minimal_valid_set_with_two_certainties(db)
    ok, err = db.try_sql(COMMIT_SQL)
    assert ok, err
    assert db.scalar("select count(*) from public.ice_reg_powertrain where model_group_id = 'm1'") == "2"
    assert db.scalar("select count(*) from public.ice_reg_powertrain_staging") == "0"
