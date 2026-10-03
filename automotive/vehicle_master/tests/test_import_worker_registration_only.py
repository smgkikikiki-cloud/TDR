"""Vehicle DB v3 Phase 0 step 5: the source-import worker imports DLT only.

source-import.yml runs ``import_worker.py run --registration-only``. DLT
registration uploads keep landing in ``registrations`` (out of scope for the
cutover); every kind that wrote the legacy file-backed Vehicle Master is
failed with an explicit message and its importer is never called. Only the
Supabase REST calls, the storage download and the importers are faked --
``process()`` itself is the real code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import import_worker

RUNS = [
    {"id": "run-dlt", "storage_path": "a.csv", "original_name": "dlt.csv", "source_kind": "DLT",
     "created_at": "2026-10-03T00:00:00+00:00"},
    {"id": "run-eco", "storage_path": "b.csv", "original_name": "eco.csv", "source_kind": "ECO",
     "created_at": "2026-10-03T00:00:00+00:00"},
    {"id": "run-specs", "storage_path": "c.xlsx", "original_name": "specs.xlsx", "source_kind": "VEHICLE_SPECS",
     "created_at": "2026-10-03T00:00:00+00:00"},
    {"id": "run-lineup", "storage_path": "d.xlsx", "original_name": "lineup.xlsx",
     "source_kind": "RETAIL_LINEUP_BOOTSTRAP", "created_at": "2026-10-03T00:00:00+00:00"},
]


@pytest.fixture
def worker(monkeypatch, tmp_path):
    calls: dict[str, list] = {"handled": [], "patched": []}

    def rest(method, path, body=None, **_kw):
        assert method == "GET" and path.startswith("import_runs?"), (method, path)
        return [dict(row) for row in RUNS]

    def patch(run_id, changes, expected_status=None):
        calls["patched"].append((run_id, changes.get("status"), changes.get("error")))
        return True

    def handler(kind):
        def run(source_file, original_name, workdir, run_id, created_at):
            calls["handled"].append((kind, run_id))
            return {"rows_written": 1, "canonical_changed": False}, []
        return run

    monkeypatch.setattr(import_worker, "_rest", rest)
    monkeypatch.setattr(import_worker, "_patch", patch)
    monkeypatch.setattr(import_worker, "_download", lambda path, work: Path(tmp_path / "file"))
    monkeypatch.setattr(import_worker, "_store_exceptions", lambda *a, **k: None)
    monkeypatch.setattr(import_worker, "HANDLERS", {kind: handler(kind) for kind in ("DLT", "ECO", "VEHICLE_SPECS")})
    return calls


def _final(calls, run_id):
    return [entry for entry in calls["patched"] if entry[0] == run_id][-1]


def test_registration_only_imports_dlt_and_fails_every_legacy_writer_kind(worker):
    assert import_worker.process(10, registration_only=True) == 0
    assert worker["handled"] == [("DLT", "run-dlt")]
    assert _final(worker, "run-dlt")[1] == "COMPLETED"
    for run_id, kind in (("run-eco", "ECO"), ("run-specs", "VEHICLE_SPECS"), ("run-lineup", "RETAIL_LINEUP_BOOTSTRAP")):
        _, status, error = _final(worker, run_id)
        assert status == "FAILED", run_id
        assert kind in error and "closed" in error and "Phase 0 step 5" in error, error
    # Every run is claimed once (UPLOADED -> PROCESSING) before it is decided.
    assert [e[0] for e in worker["patched"] if e[1] == "PROCESSING"] == [r["id"] for r in RUNS]


def test_without_the_flag_the_worker_is_unchanged(worker):
    assert import_worker.process(10) == 0
    assert worker["handled"] == [("DLT", "run-dlt"), ("ECO", "run-eco"), ("VEHICLE_SPECS", "run-specs")]


def test_the_cli_passes_the_flag(monkeypatch):
    seen = {}
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setattr(import_worker, "process", lambda limit, registration_only=False: seen.update(
        limit=limit, registration_only=registration_only) or 0)
    assert import_worker.main(["run", "--limit", "5", "--registration-only"]) == 0
    assert seen == {"limit": 5, "registration_only": True}
