from __future__ import annotations

from pathlib import Path

from tools import retail_lineup_workbook_export_worker as worker


HEX = "a" * 64


class FakeRest:
    def __init__(self):
        self.status = "QUEUED"
        self.calls: list[tuple[str, str, object, str | None]] = []

    def __call__(self, method, path, payload=None, *, prefer=None):
        self.calls.append((method, path, payload, prefer))
        row = {
            "id": "export-1",
            "status": self.status,
            "actor": "Owner",
            "model_ids": ["toyota.camry"],
            "catalog_year": 2026,
            "base_release_id": "vehicle-2026-test",
        }
        if method == "GET":
            return [row] if self.status == "QUEUED" else []
        assert method == "PATCH"
        if "status=eq.QUEUED" in path:
            if self.status != "QUEUED":
                return []
            self.status = "PROCESSING"
            return [{**row, **payload, "status": "PROCESSING"}]
        if "status=eq.PROCESSING" in path:
            if self.status != "PROCESSING":
                return []
            self.status = payload["status"]
            return [{**row, **payload}]
        raise AssertionError(path)


def test_export_claims_generates_uploads_and_records_exact_baseline(tmp_path):
    rest = FakeRest()
    uploaded: list[tuple[str, bytes]] = []
    generated: list[dict] = []

    def generate(path: Path, **kwargs):
        generated.append(kwargs)
        path.write_bytes(b"xlsx bytes")
        return {
            "baseline_hash": HEX,
            "target_model_ids": ["toyota.camry"],
            "target_rows": 2,
            "snapshot_rows": 4,
        }

    result = worker.process_export(
        {"id": "export-1"},
        rest=rest,
        upload=lambda path, content: uploaded.append((path, content)),
        generate=generate,
    )

    assert result["status"] == "READY"
    assert generated == [{
        "model_ids": ["toyota.camry"],
        "base_release_id": "vehicle-2026-test",
        "year": 2026,
    }]
    assert uploaded == [("retail-lineup-exports/export-1.xlsx", b"xlsx bytes")]
    final_payload = rest.calls[-1][2]
    assert final_payload["status"] == "READY"
    assert final_payload["baseline_hash"] == HEX
    assert final_payload["storage_path"] == "retail-lineup-exports/export-1.xlsx"


def test_duplicate_claim_is_a_noop():
    rest = FakeRest()
    rest.status = "PROCESSING"
    result = worker.process_export({"id": "export-1"}, rest=rest)
    assert result == {"id": "export-1", "status": "SKIPPED_ALREADY_CLAIMED"}


def test_generation_failure_is_persisted_as_failed():
    rest = FakeRest()

    def explode(*_args, **_kwargs):
        raise RuntimeError("unknown model")

    result = worker.process_export(
        {"id": "export-1"}, rest=rest, upload=lambda *_args: None, generate=explode)
    assert result["status"] == "FAILED"
    assert "unknown model" in result["error"]
    assert rest.calls[-1][2]["status"] == "FAILED"


def test_export_migration_is_server_only_and_request_identity_is_immutable():
    root = Path(__file__).resolve().parents[3]
    sql = (root / "supabase" / "migration_v55_retail_lineup_workbook_exports.sql").read_text(
        encoding="utf-8")
    assert "create table if not exists public.retail_lineup_workbook_exports" in sql
    assert "RETAIL_LINEUP_WORKBOOK_EXPORT_IMMUTABLE" in sql
    assert "alter table public.retail_lineup_workbook_exports enable row level security" in sql
    assert "revoke all on table public.retail_lineup_workbook_exports from public, anon, authenticated" in sql
    assert "grant select, insert, update on table public.retail_lineup_workbook_exports to service_role" in sql
    assert "status in ('QUEUED','PROCESSING','READY','FAILED')" in sql


def test_export_workflow_never_pushes_canonical_data():
    root = Path(__file__).resolve().parents[3]
    flow = (root / ".github" / "workflows" / "retail-lineup-workbook-export.yml").read_text(
        encoding="utf-8")
    assert "retail-lineup-workbook-export" in flow
    assert "ref: main" in flow
    assert "permissions:\n  contents: read" in flow
    assert "git push" not in flow
    assert "publish_canonical" not in flow
