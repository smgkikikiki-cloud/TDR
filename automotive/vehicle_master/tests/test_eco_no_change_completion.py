"""Blocker 2: an ECO run that reads cleanly but changes nothing must
finish, not hang at WRITTEN_PENDING_PUBLISH forever.

Two layers are exercised, both against the real production code paths --
nothing here is a test-only reimplementation:

  - ``tools.import_source.main()`` itself (a real CSV file, a real
    catalogue on disk, the real resolver/compiler/pipeline), proving the
    ``canonical_changed`` field in its report is the true signal.
  - ``tools.import_worker.process()``, proving that signal actually
    decides COMPLETED vs WRITTEN_PENDING_PUBLISH -- with only the
    storage download and the Supabase REST calls faked, and
    ``run_eco_import`` still the real ``tools.import_source.main``
    (pointed at a throwaway data dir instead of the production tree).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from tools import import_source, import_worker
from vehreg.catalog import Catalog

YEAR = 2026
MODEL = "toyota.camry"
TRIM = f"{MODEL}.axvh70.trim.premium"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    _write_json(root / f"{YEAR}/models/toyota.json", {
        "brand": {"id": "toyota", "name_en": "Toyota", "name_th": "โตโยต้า",
                  "brand_segment": "MASS", "brand_origin": "JP", "aliases": []},
        "models": [{
            "id": "camry", "name_en": "Camry", "nameplate": "Camry",
            "body_type": "SEDAN", "cab_type": "NOT_APPLICABLE",
            "registration_type": "", "market_scope": "CORE", "aliases": [],
            "generations": [{
                "code": "AXVH70", "segment": "D", "seats": 5,
                "variants": [{"name": "2.5 HEV", "powertrain": "HEV",
                              "drivetrain": "FWD", "import_type": "CKD",
                              "origin_country": "TH", "aliases": []}],
                "trims": [{
                    "id": "premium", "name": "Premium", "variant": "2.5 HEV",
                    "powertrain": "HEV", "drivetrain": "FWD", "seats": 5,
                    "aliases": [],
                }],
            }],
        }],
    })
    return root


def _catalog(data: Path) -> Catalog:
    return Catalog.load(data, YEAR)


def _write_csv(path: Path, rows: list[dict]) -> Path:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _eco_row(row_id: str, *, model: str = "Camry Premium", car_length: str = "") -> dict:
    # engine_name carries the Thai homologation word for "hybrid" -- the
    # export's own powertrain column has no HEV value at all, so this is
    # the only field that actually resolves it (see ecosticker_export.py).
    return {
        "id": row_id, "brand": "Toyota", "model": model,
        "engine_name": "ไฮบริด",
        "car_length": car_length,
    }


def _run(data: Path, export: Path, report_dir: Path, *, submitted_at: str) -> dict:
    import_source.main([
        str(export), "--source", "ECO", "--data-dir", str(data), "--year", str(YEAR),
        "--report-dir", str(report_dir), "--apply", "--submitted-at", submitted_at,
    ])
    return json.loads(next(report_dir.glob("*_report.json")).read_text(encoding="utf-8"))


# --- Layer 1: tools.import_source.main() against a real catalogue --------

def test_g_a_real_patch_reports_canonical_changed_true(data: Path, tmp_path: Path):
    export = _write_csv(tmp_path / "book.csv", [_eco_row("eco-1", car_length="4885")])

    report = _run(data, export, tmp_path / "report1", submitted_at="2026-09-01T00:00:00+00:00")

    assert report["patched"] == 1
    assert report["commands"] == 1
    assert report["applied"] is True
    assert report["canonical_changed"] is True
    assert _catalog(data).trims[TRIM].length_mm == 4885


def test_e_the_exact_same_file_uploaded_again_reports_no_change(data: Path, tmp_path: Path):
    export = _write_csv(tmp_path / "book.csv", [_eco_row("eco-1", car_length="4885")])
    _run(data, export, tmp_path / "report1", submitted_at="2026-09-01T00:00:00+00:00")

    report = _run(data, export, tmp_path / "report2", submitted_at="2026-10-01T00:00:00+00:00")

    assert report["rows_read"] == 1
    assert report["patched"] == 0
    assert report["commands"] == 0
    assert report["applied"] is False
    assert report["canonical_changed"] is False


def test_f_unresolved_rows_beside_unchanged_ones_still_report_no_change(
        data: Path, tmp_path: Path):
    export = _write_csv(tmp_path / "book.csv", [_eco_row("eco-1", car_length="4885")])
    _run(data, export, tmp_path / "report1", submitted_at="2026-09-01T00:00:00+00:00")

    # Same matched row again (now UNCHANGED) plus one nobody's catalogue has.
    export2 = _write_csv(tmp_path / "book2.csv", [
        _eco_row("eco-1", car_length="4885"),
        _eco_row("eco-2", model="Ghost Nameplate X1"),
    ])
    report = _run(data, export2, tmp_path / "report2", submitted_at="2026-10-01T00:00:00+00:00")

    assert report["exceptions"] == 1
    assert report["commands"] == 0
    assert report["applied"] is False
    assert report["canonical_changed"] is False


# --- Layer 2: tools.import_worker.process(), faking only storage + REST --

class FakeBackend:
    """Enough of import_runs + Supabase Storage to run process() for real."""

    def __init__(self, source_path: Path):
        self.source_path = source_path
        self.rows: dict[str, dict] = {}

    def insert(self, **fields) -> str:
        run_id = "run-1"
        self.rows[run_id] = {
            "id": run_id, "status": "UPLOADED", "commit_sha": None,
            "release_id": None, "error": None, **fields,
        }
        return run_id

    def _matches(self, row: dict, filters: dict[str, list[str]]) -> bool:
        for key, values in filters.items():
            if key in ("select", "limit", "order"):
                continue
            value = values[0]
            if value.startswith("eq."):
                if str(row.get(key)) != value[len("eq."):]:
                    return False
            else:  # pragma: no cover - no other filter shape is used here
                raise AssertionError(f"unhandled filter {key}={value}")
        return True

    def rest(self, method: str, path: str, payload=None, *, prefer=None):
        parsed = urlparse(path)
        table = parsed.path.split("?")[0]
        filters = parse_qs(parsed.query)
        if table == "import_runs":
            if method == "GET":
                matched = [row for row in self.rows.values() if self._matches(row, filters)]
                select = filters.get("select", ["*"])[0].split(",")
                return [{k: row[k] for k in select if k in row} for row in matched]
            if method == "PATCH":
                target_id = filters["id"][0][len("eq."):]
                row = self.rows.get(target_id)
                if row is None or not self._matches(row, filters):
                    return []
                row.update(payload)
                return [dict(row)]
        if table == "import_run_exceptions" and method == "POST":
            self.rows.setdefault("_exceptions", []).extend(
                payload if isinstance(payload, list) else [payload])
            return []
        raise AssertionError(f"unhandled {method} {path}")  # pragma: no cover

    def download(self, storage_path: str, into: Path) -> Path:
        target = into / storage_path.split("/")[-1]
        target.write_bytes(self.source_path.read_bytes())
        return target


@pytest.fixture
def backend(monkeypatch, data: Path, tmp_path: Path):
    """``run_eco_import`` is the real ``tools.import_source.main`` --
    only pointed at a throwaway data dir instead of the production tree,
    since process() itself never passes --data-dir and always writes
    through the live repository otherwise."""

    def routed_eco_import(argv):
        return import_source.main([*argv, "--data-dir", str(data)])

    monkeypatch.setattr(import_worker, "run_eco_import", routed_eco_import)
    fake = FakeBackend(tmp_path / "upload.csv")
    monkeypatch.setattr(import_worker, "_rest", fake.rest)
    monkeypatch.setattr(import_worker, "_download", fake.download)
    return fake


def test_g_changed_run_lands_written_pending_publish(backend: FakeBackend, tmp_path: Path):
    _write_csv(backend.source_path, [_eco_row("eco-1", car_length="4885")])
    run_id = backend.insert(storage_path="x/book.csv", original_name="book.csv",
                            source_kind="ECO", created_at="2026-09-01T00:00:00+00:00")

    import_worker.process(limit=5)

    row = backend.rows[run_id]
    assert row["status"] == "WRITTEN_PENDING_PUBLISH"
    assert row["patched"] == 1
    assert "finished_at" not in row or row.get("finished_at") is None


def test_e_no_change_run_completes_without_pending_publish(
        backend: FakeBackend, data: Path, tmp_path: Path):
    # Prime the catalogue with the same source_id already patched once,
    # outside process(), so the run under test is genuinely a no-op --
    # the exact acceptance case: the same ECO file, uploaded a second time.
    import_source.main([
        str(_write_csv(tmp_path / "prime.csv", [_eco_row("eco-1", car_length="4885")])),
        "--source", "ECO", "--data-dir", str(data), "--year", str(YEAR),
        "--report-dir", str(tmp_path / "prime-report"), "--apply",
        "--submitted-at", "2026-09-01T00:00:00+00:00",
    ])
    assert _catalog(data).trims[TRIM].length_mm == 4885

    _write_csv(backend.source_path, [_eco_row("eco-1", car_length="4885")])
    run_id = backend.insert(storage_path="x/book.csv", original_name="book.csv",
                            source_kind="ECO", created_at="2026-10-01T00:00:00+00:00")

    import_worker.process(limit=5)

    row = backend.rows[run_id]
    assert row["status"] == "COMPLETED"
    assert row["patched"] == 0
    assert row["error"] is None
    assert row.get("finished_at")
    assert row.get("release_id") is None
    assert row.get("commit_sha") is None


def test_f_unresolved_rows_but_zero_canonical_writes_still_complete(
        backend: FakeBackend, data: Path, tmp_path: Path):
    """90/10-style split, scaled down: one row already matches (UNCHANGED),
    one row's brand/model the catalogue has never heard of (an exception).
    Neither produces a command, so there is nothing to publish -- but the
    exception still has to be there for the owner to resolve."""
    import_source.main([
        str(_write_csv(tmp_path / "prime.csv", [_eco_row("eco-1", car_length="4885")])),
        "--source", "ECO", "--data-dir", str(data), "--year", str(YEAR),
        "--report-dir", str(tmp_path / "prime-report"), "--apply",
        "--submitted-at", "2026-09-01T00:00:00+00:00",
    ])

    _write_csv(backend.source_path, [
        _eco_row("eco-1", car_length="4885"),
        _eco_row("eco-2", model="Ghost Nameplate X1"),
    ])
    run_id = backend.insert(storage_path="x/book2.csv", original_name="book2.csv",
                            source_kind="ECO", created_at="2026-10-01T00:00:00+00:00")

    import_worker.process(limit=5)

    row = backend.rows[run_id]
    assert row["status"] == "COMPLETED"
    assert row["exceptions"] == 1
    assert row.get("finished_at")
    assert row.get("release_id") is None
    stored_exceptions = backend.rows.get("_exceptions", [])
    assert len(stored_exceptions) == 1
    assert stored_exceptions[0]["run_id"] == run_id
    assert stored_exceptions[0]["status"] == "OPEN"