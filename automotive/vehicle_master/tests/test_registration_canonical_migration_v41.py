"""v41 against a real Postgres carrying the rows production carries.

v41 is what lets a registration row name a canonical vehicle, gives every
unresolved import row a durable record of its own, and makes a monthly
export replace its period instead of being merged into it. All three are
claims about live data:

  * the backfill only works if the crosswalk join finds anything;
  * the exceptions table only helps if a run can actually hang rows off it
    and they survive until somebody resolves them;
  * "replace the period" is only true if the delete and the insert are one
    transaction, and if an empty file is refused rather than obeyed.

None of that can be read off the file. This applies the repository's whole
migration chain in order, seeds it the way production is seeded, applies
v41, and then asks Postgres.
"""

from __future__ import annotations

import json

import pytest

from tests.pg_cluster import SUPABASE, apply_production_schema, pg  # noqa: F401

V41 = SUPABASE / "migration_v41_registration_canonical_and_exceptions.sql"

BRAND = "11111111-1111-1111-1111-111111111111"
MODEL = "22222222-2222-2222-2222-222222222222"
UNMAPPED_MODEL = "33333333-3333-3333-3333-333333333333"
RELEASE = "vehicle-2026-test"


def _seed(pg) -> None:
    """A brand, a model, the crosswalk that names it, and one month of DLT."""
    pg.sql(f"""
    insert into public.brands (id, slug, name_th, name_en)
      values ('{BRAND}', 'toyota', 'โตโยต้า', 'Toyota');
    insert into public.models (id, slug, brand_id, name_th, name_en)
      values ('{MODEL}', 'toyota-yaris', '{BRAND}', 'ยาริส', 'Yaris'),
             ('{UNMAPPED_MODEL}', 'toyota-hilux', '{BRAND}', 'ไฮลักซ์', 'Hilux');

    insert into public.canonical_vehicle_releases
      (release_id, schema_version, canonical_revision, source_hash, as_of,
       counts, payload, status, activated_at)
      values ('{RELEASE}', 1, 'abc123', 'hash', '2026-06-01',
              '{{}}'::jsonb, '{{}}'::jsonb, 'ACTIVE', now());
    insert into public.canonical_vehicle_state (scope, active_release_id)
      values ('vehicle_catalog', '{RELEASE}');
    insert into public.canonical_model_projection
      (release_id, canonical_id, tdr_model_id, brand_id, slug, name_en, status, payload)
      values ('{RELEASE}', 'toyota.yaris', '{MODEL}', 'toyota', 'toyota-yaris',
              'Yaris', 'CURRENT', '{{}}'::jsonb);

    insert into public.registration_model_aliases
      (brand_id, registration_type, alias_norm, model_id)
      values ('{BRAND}', 'PC', 'yaris', '{MODEL}'),
             ('{BRAND}', 'PC', 'hilux', '{UNMAPPED_MODEL}');

    insert into public.registrations
      (period, registration_type, brand_name_raw, model_name_raw, registrations,
       model_id, mapping_method)
      values ('2026-06-01', 'PC', 'TOYOTA', 'YARIS', 1200, '{MODEL}', 'alias'),
             ('2026-06-01', 'PC', 'TOYOTA', 'HILUX', 900, '{UNMAPPED_MODEL}', 'alias'),
             ('2026-06-01', 'PC', 'TOYOTA', 'บางอย่าง', 7, null, 'unmapped'),
             ('2026-05-01', 'PC', 'TOYOTA', 'YARIS', 1100, '{MODEL}', 'alias');
    """)


@pytest.fixture
def db(pg):
    apply_production_schema(pg, through=40)
    _seed(pg)
    return pg


def _apply_v41(db) -> None:
    db.file(V41)


# --- it applies at all, on top of what production already has ------------

def test_v41_applies_to_the_live_schema_and_is_re_runnable(db):
    _apply_v41(db)
    _apply_v41(db)

    assert db.scalar("select count(*) from public.registrations") == "4"
    assert db.scalar(
        "select count(*) from information_schema.columns where table_name='registrations'"
        " and column_name='canonical_model_id'") == "1"


def test_no_registration_row_is_lost_or_changed_by_the_upgrade(db):
    before = db.rows("select period, model_name_raw, registrations, mapping_method"
                     " from public.registrations order by period, model_name_raw")
    _apply_v41(db)
    after = db.rows("select period, model_name_raw, registrations, mapping_method"
                    " from public.registrations order by period, model_name_raw")
    assert before == after


# --- the backfill actually finds the crosswalk ---------------------------

def test_the_backfill_attributes_rows_through_the_existing_crosswalk(db):
    _apply_v41(db)

    assert db.rows(
        "select model_name_raw, canonical_model_id from public.registrations"
        " where canonical_model_id is not null order by period, model_name_raw"
    ) == [["YARIS", "toyota.yaris"], ["YARIS", "toyota.yaris"]]
    # The legacy id a release has never crosswalked stays unattributed
    # rather than being guessed at.
    assert db.scalar(
        "select count(*) from public.registrations"
        " where model_id is not null and canonical_model_id is null") == "1"
    assert db.scalar(
        "select canonical_model_id from public.registration_model_aliases"
        " where alias_norm = 'yaris'") == "toyota.yaris"


def test_the_legacy_bridge_is_left_exactly_as_it_was(db):
    _apply_v41(db)
    assert db.scalar(
        f"select count(*) from public.registrations where model_id = '{MODEL}'") == "2"


# --- exceptions are durable, resolvable rows -----------------------------

def _run_id(db, kind: str = "DLT") -> str:
    return db.scalar(f"""
        insert into public.import_runs (storage_path, original_name, source_kind, status)
        values ('uploads/{kind.lower()}-june.csv', '{kind.lower()}-june.csv', '{kind}', 'COMPLETED')
        returning id""")


def test_every_unresolved_row_gets_its_own_record_with_no_cap(db):
    _apply_v41(db)
    run = _run_id(db)
    db.sql(f"""
      insert into public.import_run_exceptions (run_id, source_kind, kind, reason, source_identity)
      select '{run}', 'DLT', 'REGISTRATION_IDENTITY', 'brand/model not in the catalog',
             jsonb_build_object('brand_name_raw', 'TOYOTA', 'model_name_raw', 'rowue ' || i,
                                'period', '2026-06-01', 'units', i)
        from generate_series(1, 900) as i;""")

    assert db.scalar(f"select count(*) from public.import_run_exceptions where run_id='{run}'") == "900"
    assert db.scalar(f"select count(*) from public.import_run_exceptions"
                     f" where run_id='{run}' and status='OPEN'") == "900"


def test_an_exception_can_be_resolved_and_stops_being_open(db):
    _apply_v41(db)
    run = _run_id(db)
    db.sql(f"""insert into public.import_run_exceptions
               (run_id, source_kind, kind, reason, source_identity)
               values ('{run}', 'DLT', 'REGISTRATION_IDENTITY', 'unknown model',
                       '{{"model_name_raw": "YARIS CROSS"}}'::jsonb);""")

    db.sql("""update public.import_run_exceptions
                 set status='RESOLVED', resolution_target='toyota.yaris_cross',
                     resolved_by='owner', resolved_at=now()
               where status='OPEN';""")

    assert db.scalar("select count(*) from public.import_run_exceptions where status='OPEN'") == "0"
    ok, error = db.try_sql("update public.import_run_exceptions set status='MAYBE'")
    assert not ok and "import_run_exceptions_status_check" in error


def test_the_same_unresolved_identity_can_be_found_again_next_month(db):
    """The identity is indexed, so resolving it once can close the rest."""
    _apply_v41(db)
    run = _run_id(db)
    db.sql(f"""insert into public.import_run_exceptions
               (run_id, source_kind, kind, reason, source_identity)
               values ('{run}', 'DLT', 'REGISTRATION_IDENTITY', 'unknown model',
                       '{{"brand_name_raw": "TOYOTA", "model_name_raw": "YARIS CROSS"}}'::jsonb),
                      ('{run}', 'DLT', 'REGISTRATION_IDENTITY', 'unknown model',
                       '{{"brand_name_raw": "TOYOTA", "model_name_raw": "YARIS CROSS"}}'::jsonb);""")

    assert db.scalar("""select count(*) from public.import_run_exceptions
                        where source_identity @> '{"model_name_raw": "YARIS CROSS"}'::jsonb""") == "2"


def test_the_price_feed_is_a_run_kind_the_table_accepts(db):
    _apply_v41(db)
    run = _run_id(db, "PRICE")
    db.sql(f"""insert into public.import_run_exceptions
               (run_id, source_kind, kind, reason, source_identity)
               values ('{run}', 'PRICE', 'PRICE_IDENTITY', 'no trim matched',
                       '{{"amount_thb": 999000}}'::jsonb);""")
    assert db.scalar("select count(*) from public.import_run_exceptions") == "1"
    ok, error = db.try_sql("""insert into public.import_runs
        (storage_path, original_name, source_kind, status)
        values ('x', 'x', 'NONSENSE', 'COMPLETED')""")
    assert not ok and "import_runs_source_kind_check" in error


def test_a_run_can_name_the_commit_and_release_it_produced(db):
    _apply_v41(db)
    run = _run_id(db)
    db.sql(f"""update public.import_runs
                  set commit_sha='deadbeef', release_id='{RELEASE}', status='COMPLETED'
                where id='{run}'""")
    assert db.rows(f"select commit_sha, release_id from public.import_runs where id='{run}'") \
        == [["deadbeef", RELEASE]]


# --- a monthly file replaces its period ----------------------------------

def _replace(db, rows: list[dict], *, period: str = "2026-06",
             registration_type: str = "PC") -> tuple[bool, str]:
    payload = json.dumps(rows).replace("'", "''")
    return db.try_sql(
        f"select public.tdr_replace_registration_period("
        f"'{period}', '{registration_type}', '{payload}'::jsonb, null, 'dlt-june-v2.csv')")


def test_a_corrected_file_drops_the_row_it_no_longer_lists(db):
    _apply_v41(db)
    ok, error = _replace(db, [
        {"registration_type": "PC", "brand_name_raw": "TOYOTA",
         "model_name_raw": "YARIS", "registrations": 1250,
         "canonical_model_id": "toyota.yaris", "mapping_method": "import-alias"},
        {"registration_type": "PC", "brand_name_raw": "TOYOTA",
         "model_name_raw": "HILUX", "registrations": 900,
         "mapping_method": "unmapped"},
    ])
    assert ok, error

    assert db.rows("select model_name_raw, registrations from public.registrations"
                   " where period='2026-06-01' order by model_name_raw") == [
        ["HILUX", "900"], ["YARIS", "1250"]]
    # The month that was not replaced is untouched.
    assert db.scalar("select registrations from public.registrations"
                     " where period='2026-05-01'") == "1100"


def test_an_unmatched_row_is_still_part_of_the_month(db):
    _apply_v41(db)
    _replace(db, [
        {"brand_name_raw": "TOYOTA", "model_name_raw": "YARIS", "registrations": 1250,
         "canonical_model_id": "toyota.yaris", "mapping_method": "import-alias"},
        {"brand_name_raw": "TOYOTA", "model_name_raw": "ที่ยังไม่รู้จัก",
         "registrations": 40, "mapping_method": "unmapped"},
    ])
    assert db.scalar("select sum(registrations) from public.registrations"
                     " where period='2026-06-01'") == "1290"
    assert db.scalar("select canonical_model_id from public.registrations"
                     " where model_name_raw='ที่ยังไม่รู้จัก'") == ""


def test_an_empty_file_is_refused_rather_than_emptying_the_month(db):
    _apply_v41(db)
    ok, error = _replace(db, [])
    assert not ok
    assert "empty snapshot" in error
    assert db.scalar("select count(*) from public.registrations"
                     " where period='2026-06-01'") == "3"


def test_a_failed_replace_rolls_the_delete_back_with_it(db):
    """Half a month is worse than last month's month."""
    _apply_v41(db)
    before = db.rows("select model_name_raw, registrations from public.registrations"
                     " where period='2026-06-01' order by model_name_raw")

    ok, error = _replace(db, [
        {"brand_name_raw": "TOYOTA", "model_name_raw": "YARIS", "registrations": 1250},
        {"brand_name_raw": "TOYOTA", "model_name_raw": "HILUX",
         "registrations": "not a number"},
    ])

    assert not ok, "a malformed row must not be accepted"
    assert db.rows("select model_name_raw, registrations from public.registrations"
                   " where period='2026-06-01' order by model_name_raw") == before


def test_replacing_a_period_records_where_the_numbers_came_from(db):
    _apply_v41(db)
    _replace(db, [{"brand_name_raw": "TOYOTA", "model_name_raw": "YARIS",
                   "registrations": 1250}])
    assert db.scalar("select distinct source_reference from public.registrations"
                     " where period='2026-06-01'") == "dlt-june-v2.csv"


def test_a_month_is_named_the_way_the_importers_name_it(db):
    """The importers read '2026-06' off the file; the column is a date."""
    _apply_v41(db)
    ok, error = _replace(db, [{"brand_name_raw": "TOYOTA", "model_name_raw": "YARIS",
                               "registrations": 1250}], period="2026-06")
    assert ok, error
    assert db.scalar("select period from public.registrations"
                     " where model_name_raw='YARIS' and registrations=1250") == "2026-06-01"

    # Any day of the month means that month, and a period that is not a
    # month at all is refused rather than silently matching nothing.
    ok, error = _replace(db, [{"brand_name_raw": "TOYOTA", "model_name_raw": "YARIS",
                               "registrations": 1300}], period="2026-06-17")
    assert ok, error
    assert db.rows("select registrations from public.registrations"
                   " where period='2026-06-01'") == [["1300"]]
    ok, error = _replace(db, [{"brand_name_raw": "T", "model_name_raw": "Y",
                               "registrations": 1}], period="June 2026")
    assert not ok and "is not a month" in error


# --- a car created today can be given a DLT label ------------------------

def test_a_label_can_be_bound_to_a_car_with_no_legacy_row_yet(db):
    """The case that used to be impossible, and was the common one."""
    _apply_v41(db)
    ok, error = db.try_sql(f"""
        insert into public.registration_model_aliases
          (brand_id, registration_type, alias_norm, model_id, canonical_model_id, match_mode)
        values ('{BRAND}', 'PC', 'yariscross', null, 'toyota.yaris_cross', 'exact')""")
    assert ok, error
    assert db.scalar("select canonical_model_id from public.registration_model_aliases"
                     " where alias_norm='yariscross'") == "toyota.yaris_cross"


def test_an_alias_still_has_to_name_something(db):
    _apply_v41(db)
    ok, error = db.try_sql(f"""
        insert into public.registration_model_aliases
          (brand_id, registration_type, alias_norm, model_id, canonical_model_id)
        values ('{BRAND}', 'PC', 'nothing', null, null)""")
    assert not ok and "registration_model_aliases_identity_check" in error


def test_a_trim_grained_mapping_must_actually_name_a_trim(db):
    _apply_v41(db)
    ok, error = db.try_sql(f"""
        insert into public.registration_model_aliases
          (brand_id, registration_type, alias_norm, canonical_model_id, grain)
        values ('{BRAND}', 'PC', 'aionv602', 'aion.aion_v', 'TRIM')""")
    assert not ok and "registration_model_aliases_grain_check" in error

    ok, error = db.try_sql(f"""
        insert into public.registration_model_aliases
          (brand_id, registration_type, alias_norm, canonical_model_id,
           canonical_trim_id, grain)
        values ('{BRAND}', 'PC', 'aionv602luxury', 'aion.aion_v',
                'aion.aion_v.v1.trim.luxury', 'TRIM')""")
    assert ok, error


def test_every_mapping_that_already_exists_stays_model_grained(db):
    """Nothing acquires a trim by the upgrade running."""
    _apply_v41(db)
    assert db.scalar("select count(*) from public.registration_model_aliases"
                     " where grain <> 'MODEL'") == "0"
    assert db.scalar("select count(*) from public.registration_model_aliases"
                     " where canonical_trim_id is not null") == "0"


def test_the_replace_function_is_not_reachable_by_a_logged_in_visitor(db):
    _apply_v41(db)
    assert db.scalar("""
        select count(*) from information_schema.role_routine_grants
         where routine_name = 'tdr_replace_registration_period'
           and grantee in ('anon', 'authenticated')""") == "0"
