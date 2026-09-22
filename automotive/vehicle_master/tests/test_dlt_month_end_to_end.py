"""A real monthly DLT export, from the file to the rows Postgres holds.

The importer and the database each have tests of their own, and both
passed while the payload one produced and the payload the other accepted
were not quite the same shape -- which is the only thing that matters on
the day a month is uploaded. This runs the actual file through the actual
parser and resolver, hands the result to the actual function, and then
counts what is in the table.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tests.pg_cluster import SUPABASE, apply_production_schema, pg  # noqa: F401
from vehreg.registration_import import (
    MATCHED, exception_rows, parse_registration_rows, resolve_registrations,
    snapshot_rows,
)

REPO = Path(__file__).resolve().parents[1]
EXPORT = REPO / "data" / "raw" / "dlt_2025-06.csv"

BRAND = "44444444-4444-4444-4444-444444444444"
MODEL = "55555555-5555-5555-5555-555555555555"
RELEASE = "vehicle-2025-dlt"


def _file_rows():
    with EXPORT.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture
def db(pg):
    apply_production_schema(pg)
    pg.sql(f"""
    insert into public.brands (id, slug, name_th, name_en)
      values ('{BRAND}', 'toyota', 'โตโยต้า', 'Toyota');
    insert into public.models (id, slug, brand_id, name_th, name_en)
      values ('{MODEL}', 'toyota-yaris', '{BRAND}', 'ยาริส', 'Yaris');
    insert into public.canonical_vehicle_releases
      (release_id, schema_version, canonical_revision, source_hash, as_of,
       counts, payload, status, activated_at)
      values ('{RELEASE}', 1, 'rev', 'hash', '2025-06-01',
              '{{}}'::jsonb, '{{}}'::jsonb, 'ACTIVE', now());
    insert into public.canonical_vehicle_state (scope, active_release_id)
      values ('vehicle_catalog', '{RELEASE}');
    insert into public.canonical_model_projection
      (release_id, canonical_id, tdr_model_id, brand_id, slug, name_en, status, payload)
      values ('{RELEASE}', 'toyota.yaris', '{MODEL}', 'toyota', 'toyota-yaris',
              'Yaris', 'CURRENT', '{{}}'::jsonb);
    """)
    return pg


def _load_month(db, rows, *, brand_aliases, model_aliases, source="dlt_2025-06.csv"):
    resolved = resolve_registrations(rows, brand_aliases, model_aliases)
    payload = json.dumps(snapshot_rows(resolved)).replace("'", "''")
    period = rows[0].period
    ok, error = db.try_sql(
        f"select public.tdr_replace_registration_period("
        f"'{period}', null, '{payload}'::jsonb, null, '{source}')")
    assert ok, error
    return resolved


def test_the_whole_month_lands_and_the_total_is_the_file_s_total(db):
    rows, rejected = parse_registration_rows(_file_rows())
    assert rows and not rejected

    _load_month(db, rows, brand_aliases={}, model_aliases=[])

    assert db.scalar("select count(*) from public.registrations") == str(len(rows))
    assert db.scalar("select sum(registrations) from public.registrations") \
        == str(sum(row.units for row in rows))
    # Nothing was placed, because nothing was taught yet -- and the month
    # is still complete.
    assert db.scalar("select count(*) from public.registrations"
                     " where canonical_model_id is not null") == "0"


def test_teaching_one_label_attributes_it_without_changing_the_total(db):
    rows, _ = parse_registration_rows(_file_rows())
    target = next(row for row in rows if row.brand_raw == "TOYOTA")
    db.sql(f"""
      insert into public.registration_brand_aliases (raw_brand_norm, brand_id)
        values ('toyota', '{BRAND}');
      insert into public.registration_model_aliases
        (brand_id, registration_type, alias_norm, model_id, canonical_model_id, match_mode)
        values ('{BRAND}', '{target.registration_type}',
                '{target.model_raw.lower().replace(" ", "")}', '{MODEL}',
                'toyota.yaris', 'exact');
    """)
    aliases = [{
        "brand_id": BRAND, "registration_type": target.registration_type,
        "alias_norm": target.model_raw.lower().replace(" ", ""),
        "model_id": MODEL, "canonical_model_id": "toyota.yaris",
        "canonical_trim_id": "", "match_mode": "exact",
    }]

    resolved = _load_month(db, rows, brand_aliases={"toyota": BRAND},
                           model_aliases=aliases)

    assert sum(1 for item in resolved if item.status == MATCHED) >= 1
    assert db.scalar("select sum(registrations) from public.registrations") \
        == str(sum(row.units for row in rows))
    assert db.scalar("select count(*) from public.registrations"
                     " where canonical_model_id = 'toyota.yaris'") == "1"
    # Model grain, because that is what this file publishes.
    assert db.scalar("select count(*) from public.registrations"
                     " where canonical_trim_id is not null") == "0"


def test_uploading_a_corrected_file_replaces_the_month_rather_than_adding_to_it(db):
    rows, _ = parse_registration_rows(_file_rows())
    _load_month(db, rows, brand_aliases={}, model_aliases=[])
    first_total = db.scalar("select sum(registrations) from public.registrations")

    # The same file again, with one row corrected and one row dropped.
    corrected = [row for row in rows[1:]]
    corrected[0] = corrected[0].__class__(
        period=corrected[0].period, registration_type=corrected[0].registration_type,
        brand_raw=corrected[0].brand_raw, model_raw=corrected[0].model_raw,
        units=corrected[0].units + 5)
    _load_month(db, corrected, brand_aliases={}, model_aliases=[],
                source="dlt_2025-06-corrected.csv")

    assert db.scalar("select count(*) from public.registrations") == str(len(corrected))
    assert db.scalar("select sum(registrations) from public.registrations") \
        == str(sum(row.units for row in corrected))
    assert db.scalar("select sum(registrations) from public.registrations") != first_total
    assert db.scalar("select distinct source_reference from public.registrations") \
        == "dlt_2025-06-corrected.csv"


def test_what_could_not_be_placed_is_reported_row_by_row(db):
    rows, _ = parse_registration_rows(_file_rows())
    resolved = resolve_registrations(rows, {}, [])
    exceptions = exception_rows(resolved)

    assert len(exceptions) == len(rows)
    assert {row["kind"] for row in exceptions} == {"REGISTRATION_IDENTITY"}
    # And they fit the table that has to hold them.
    run = db.scalar("""
        insert into public.import_runs (storage_path, original_name, source_kind, status)
        values ('uploads/dlt_2025-06.csv', 'dlt_2025-06.csv', 'DLT', 'COMPLETED')
        returning id""")
    payload = json.dumps([{
        "run_id": run, "source_kind": "DLT", "kind": row["kind"],
        "reason": row["reason"], "source_identity": row["source_identity"],
        "status": "OPEN",
    } for row in exceptions]).replace("'", "''")
    ok, error = db.try_sql(f"""
        insert into public.import_run_exceptions
          (run_id, source_kind, kind, reason, source_identity, status)
        select (item->>'run_id')::uuid, item->>'source_kind', item->>'kind',
               item->>'reason', item->'source_identity', item->>'status'
          from jsonb_array_elements('{payload}'::jsonb) as item""")
    assert ok, error
    assert db.scalar("select count(*) from public.import_run_exceptions"
                     " where status = 'OPEN'") == str(len(exceptions))
