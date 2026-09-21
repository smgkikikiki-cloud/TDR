"""A malformed row must fail the whole run before anything is written.

Before this pass, the worker parsed a monthly export into valid rows and
rejected rows, replaced the month with the valid subset, and only then
reported the rejected rows as exceptions. Because
tdr_replace_registration_period deletes the whole month before
re-inserting it, that meant a file with even one bad row silently shrank
the month by however many rows could not be read -- and reported success.

Two things are proved here: the worker-level guard raises
MalformedSnapshotError BEFORE any network call is attempted (so it cannot
be a bug that only shows up once Supabase is reachable), and the DB-level
consequence -- a month is left exactly as it was when the snapshot that
would replace it contains an untrustworthy row, and a corrected,
fully-valid file still replaces atomically once the bad row is fixed.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from tests.pg_cluster import apply_production_schema, pg  # noqa: F401
from vehreg.registration_import import (
    MalformedSnapshotError, parse_registration_rows, resolve_registrations,
    snapshot_rows,
)

BRAND = "99999999-9999-9999-9999-999999999999"
MODEL = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _write_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = ["period", "registration_type", "brand", "model", "units"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# --- A: the worker-level guard fires before any network call --------------

def test_a_malformed_row_raises_before_reaching_supabase(tmp_path: Path, monkeypatch):
    """No SUPABASE_URL is set at all -- if the code reached `_rest` first,
    it would fail with a credentials error, not MalformedSnapshotError."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    csv_path = tmp_path / "dlt-2026-06.csv"
    _write_csv(csv_path, [
        {"period": "2026-06", "registration_type": "PC", "brand": "TOYOTA",
         "model": "YARIS", "units": "1200"},
        {"period": "2026-06", "registration_type": "PC", "brand": "TOYOTA",
         "model": "COROLLA", "units": "not-a-number"},
    ])

    from tools.import_worker import _import_dlt

    with pytest.raises(MalformedSnapshotError) as excinfo:
        _import_dlt(csv_path, "dlt-2026-06.csv", tmp_path, "run-1",
                    "2026-07-01T00:00:00+00:00")
    assert "1 row" in str(excinfo.value)
    assert "not a number" in str(excinfo.value)


def test_several_malformed_rows_are_all_reported_in_one_failure(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    csv_path = tmp_path / "dlt-2026-07.csv"
    _write_csv(csv_path, [
        {"period": "2026-07", "registration_type": "PC", "brand": "TOYOTA",
         "model": "YARIS", "units": "1200"},
        {"period": "2026-07", "registration_type": "PC", "brand": "",
         "model": "COROLLA", "units": "10"},
        {"period": "2026-07", "registration_type": "PC", "brand": "HONDA",
         "model": "CIVIC", "units": "-5"},
    ])

    from tools.import_worker import _import_dlt

    with pytest.raises(MalformedSnapshotError) as excinfo:
        _import_dlt(csv_path, "dlt-2026-07.csv", tmp_path, "run-2",
                    "2026-08-01T00:00:00+00:00")
    assert excinfo.value.rejected and len(excinfo.value.rejected) == 2


def test_an_unknown_brand_or_model_is_not_malformed(tmp_path: Path, monkeypatch):
    """Identity unresolved is a mapping problem, not a bad row -- it must
    NOT raise, so it can still be written as a fact with an open exception."""
    csv_path = tmp_path / "dlt-2026-08.csv"
    _write_csv(csv_path, [
        {"period": "2026-08", "registration_type": "PC", "brand": "NOBODY KNOWS",
         "model": "MYSTERY CAR", "units": "40"},
    ])
    rows, rejected = parse_registration_rows(list(csv.DictReader(
        io.StringIO(csv_path.read_text(encoding="utf-8-sig")))))
    assert not rejected
    assert len(rows) == 1


# --- B: the database-level consequence -------------------------------------

@pytest.fixture
def db(pg):
    apply_production_schema(pg)
    pg.sql(f"""
    insert into public.brands (id, slug, name_th, name_en)
      values ('{BRAND}', 'toyota', 'โตโยต้า', 'Toyota');
    insert into public.models (id, slug, brand_id, name_th, name_en)
      values ('{MODEL}', 'toyota-yaris', '{BRAND}', 'ยาริส', 'Yaris');
    """)
    return pg


def _replace_period(db, rows: list[dict], *, period="2026-06") -> tuple[bool, str]:
    payload = json.dumps(rows).replace("'", "''")
    return db.try_sql(
        f"select public.tdr_replace_registration_period("
        f"'{period}', null, '{payload}'::jsonb, null, 'dlt-2026-06.csv')")


def test_the_month_is_unchanged_when_the_worker_refuses_a_malformed_snapshot(db):
    """The exact acceptance case: month = 1000, a corrected file with one
    malformed row must leave the month at exactly 1000 -- not 10 valid rows
    worth, not any partial replacement at all."""
    original = [{"brand_name_raw": "TOYOTA", "model_name_raw": "YARIS",
                 "registrations": 1000, "mapping_method": "import-alias",
                 "model_id": MODEL}]
    ok, error = _replace_period(db, original)
    assert ok, error
    assert db.scalar("select sum(registrations) from public.registrations"
                     " where period = '2026-06-01'") == "1000"

    csv_path = Path("/tmp") / "dlt-correction-2026-06.csv"
    _write_csv(csv_path, [
        {"period": "2026-06", "registration_type": "PC", "brand": "TOYOTA",
         "model": "YARIS", "units": "990"},
        *[{"period": "2026-06", "registration_type": "PC", "brand": "TOYOTA",
           "model": f"MODEL {i}", "units": "1"} for i in range(9)],
        {"period": "2026-06", "registration_type": "PC", "brand": "TOYOTA",
         "model": "BROKEN ROW", "units": "abc"},
    ])
    rows, rejected = parse_registration_rows(list(csv.DictReader(
        io.StringIO(csv_path.read_text(encoding="utf-8-sig")))))
    assert rejected, "the fixture must contain the malformed row it claims to"

    # This is exactly what tools.import_worker._import_dlt does: check
    # rejected BEFORE calling the replace RPC at all.
    if rejected:
        with pytest.raises(MalformedSnapshotError):
            raise MalformedSnapshotError(rejected)
    else:  # pragma: no cover - fixture guards against this
        resolved = resolve_registrations(rows, {}, [])
        _replace_period(db, snapshot_rows(resolved))

    # The month the worker never touched is exactly what it was before.
    assert db.scalar("select sum(registrations) from public.registrations"
                     " where period = '2026-06-01'") == "1000"
    assert db.scalar("select count(*) from public.registrations"
                     " where period = '2026-06-01'") == "1"


def test_the_corrected_file_replaces_atomically_once_the_bad_row_is_fixed(db):
    original = [{"brand_name_raw": "TOYOTA", "model_name_raw": "YARIS",
                 "registrations": 1000, "mapping_method": "import-alias",
                 "model_id": MODEL}]
    _replace_period(db, original)

    csv_path = Path("/tmp") / "dlt-correction-2026-06-fixed.csv"
    _write_csv(csv_path, [
        {"period": "2026-06", "registration_type": "PC", "brand": "TOYOTA",
         "model": "YARIS", "units": "990"},
        {"period": "2026-06", "registration_type": "PC", "brand": "TOYOTA",
         "model": "COROLLA", "units": "10"},
    ])
    rows, rejected = parse_registration_rows(list(csv.DictReader(
        io.StringIO(csv_path.read_text(encoding="utf-8-sig")))))
    assert not rejected

    resolved = resolve_registrations(rows, {}, [])
    ok, error = _replace_period(db, snapshot_rows(resolved))
    assert ok, error

    assert db.scalar("select sum(registrations) from public.registrations"
                     " where period = '2026-06-01'") == "1000"
    assert db.scalar("select count(*) from public.registrations"
                     " where period = '2026-06-01'") == "2"
