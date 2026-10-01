from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml

from tools import retail_lineup_apply_worker as apply_worker
from tools import retail_lineup_compile_worker as compile_worker
from vehreg.retail_lineup_bootstrap import RetailLineupBootstrapError


ROOT = Path(__file__).resolve().parents[3]


def test_compile_worker_persists_one_preview_then_completes(monkeypatch, tmp_path):
    patches = []
    persisted = {}

    def fake_patch(run_id, payload, *, expected_status=None):
        patches.append((run_id, dict(payload), expected_status))
        return [{"id": run_id, **payload}]

    source = tmp_path / "lineup.xlsx"
    source.write_bytes(b"xlsx")
    monkeypatch.setattr(compile_worker, "_patch", fake_patch)
    monkeypatch.setattr(compile_worker, "_existing_preview", lambda run_id: None)
    monkeypatch.setattr(compile_worker, "_download", lambda storage_path, into: source)
    monkeypatch.setattr(
        compile_worker,
        "compile_retail_lineup_workbook",
        lambda path: SimpleNamespace(rows_read=3),
    )

    def fake_persist(compiled, *, actor, import_run_id):
        persisted.update(actor=actor, import_run_id=import_run_id, compiled=compiled)
        return {
            "id": "plan-1",
            "plan_hash": "a" * 64,
            "baseline_hash": "b" * 64,
            "summary": {"create": 2, "reactivate": 1, "archive": 3},
        }

    monkeypatch.setattr(compile_worker, "persist_preview", fake_persist)
    result = compile_worker.process_run({
        "id": "run-1",
        "status": "UPLOADED",
        "storage_path": "retail-lineup-uploads/a.xlsx",
        "original_name": "a.xlsx",
        "actor": "owner@example.test",
    })

    assert result["status"] == "COMPLETED"
    assert result["plan_id"] == "plan-1"
    assert persisted["actor"] == "owner@example.test"
    assert persisted["import_run_id"] == "run-1"
    assert patches[0][1]["status"] == "PROCESSING"
    assert patches[-1][1]["status"] == "COMPLETED"
    assert patches[-1][1]["rows_read"] == 3
    assert patches[-1][1]["created"] == 2
    assert patches[-1][1]["patched"] == 4


def test_compile_worker_recovers_processing_run_from_unique_preview(monkeypatch):
    patches = []
    monkeypatch.setattr(
        compile_worker,
        "_existing_preview",
        lambda run_id: {"id": "plan-1", "summary": {"create": 1, "archive": 2}},
    )
    monkeypatch.setattr(
        compile_worker,
        "_patch",
        lambda run_id, payload, *, expected_status=None: patches.append(
            (run_id, dict(payload), expected_status)
        ) or [{"id": run_id, **payload}],
    )
    monkeypatch.setattr(
        compile_worker,
        "compile_retail_lineup_workbook",
        lambda path: (_ for _ in ()).throw(AssertionError("must not recompile persisted preview")),
    )

    result = compile_worker.process_run({"id": "run-1", "status": "PROCESSING"})
    assert result == {"id": "run-1", "status": "COMPLETED", "plan_id": "plan-1",
                      "recovered": True}
    assert patches[-1][1]["status"] == "COMPLETED"


def test_apply_worker_executes_stored_plan_not_workbook(monkeypatch, tmp_path):
    row = {
        "id": "plan-1",
        "status": "APPLYING",
        "plan_hash": "a" * 64,
        "baseline_hash": "b" * 64,
        "compiled_plan": {"stored": True},
        "approved_by": "human-owner",
        "approved_at": "2026-09-30T10:00:00+00:00",
    }
    plan = SimpleNamespace(plan_hash="a" * 64, baseline_hash="b" * 64)
    seen = {}
    monkeypatch.setattr(apply_worker, "fetch_preview", lambda plan_id: row)

    def fake_decode(payload, **kwargs):
        seen["payload"] = payload
        seen.update(kwargs)
        return plan

    monkeypatch.setattr(apply_worker, "decode_retail_lineup_plan", fake_decode)
    monkeypatch.setattr(
        apply_worker,
        "apply_retail_lineup_plan_atomically",
        lambda held, **kwargs: SimpleNamespace(
            changed_files=("2026/current_retail.json",),
            idempotent_replay=False,
            counts={"keep": 1, "create": 0, "reactivate": 0, "archive": 1},
            release=SimpleNamespace(release_id="preview-release"),
        ),
    )
    monkeypatch.setattr(
        apply_worker,
        "mark_failed",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected failure")),
    )
    monkeypatch.setattr(
        apply_worker,
        "mark_stale",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected stale")),
    )

    result_file = tmp_path / "result.json"
    result = apply_worker.prepare("plan-1", result_file=str(result_file))
    assert result["prepared"] is True
    assert result["changed_files"] == ["2026/current_retail.json"]
    assert seen["payload"] == {"stored": True}
    assert seen["expected_plan_hash"] == "a" * 64
    assert seen["expected_baseline_hash"] == "b" * 64
    assert result_file.is_file()


def test_apply_worker_marks_stale_baseline_terminal(monkeypatch):
    row = {
        "status": "APPLYING",
        "plan_hash": "a" * 64,
        "baseline_hash": "b" * 64,
        "compiled_plan": {},
        "approved_by": "human-owner",
        "approved_at": "2026-09-30T10:00:00+00:00",
    }
    stale = {}
    monkeypatch.setattr(apply_worker, "fetch_preview", lambda plan_id: row)
    monkeypatch.setattr(
        apply_worker,
        "decode_retail_lineup_plan",
        lambda *args, **kwargs: SimpleNamespace(plan_hash="a" * 64, baseline_hash="b" * 64),
    )
    monkeypatch.setattr(
        apply_worker,
        "apply_retail_lineup_plan_atomically",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RetailLineupBootstrapError("STALE_BASELINE: current tree moved")
        ),
    )
    monkeypatch.setattr(
        apply_worker,
        "mark_stale",
        lambda plan_id, **kwargs: stale.update(plan_id=plan_id, **kwargs) or {},
    )
    monkeypatch.setattr(
        apply_worker,
        "mark_failed",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must mark stale")),
    )

    result = apply_worker.prepare("plan-1")
    assert result["status"] == "STALE"
    assert stale["plan_id"] == "plan-1"
    assert stale["expected_plan_hash"] == "a" * 64


def test_chunk7_static_wiring_contract():
    migration = (ROOT / "supabase/migration_v56_retail_lineup_import_kind.sql").read_text(
        encoding="utf-8"
    )
    assert "'RETAIL_LINEUP_BOOTSTRAP'::text" in migration

    source_workflow_path = ROOT / ".github/workflows/source-import.yml"
    source_workflow = source_workflow_path.read_text(encoding="utf-8")
    yaml.safe_load(source_workflow)
    assert "retail_lineup_compile_worker.py --limit 1000" in source_workflow
    assert source_workflow.index("retail_lineup_compile_worker.py") < source_workflow.index(
        "import_worker.py run --limit 5"
    )

    apply_workflow = (ROOT / ".github/workflows/retail-lineup-bootstrap-apply.yml").read_text(
        encoding="utf-8"
    )
    yaml.safe_load(apply_workflow)
    assert "types: [retail-lineup-bootstrap-apply]" in apply_workflow
    assert 'cron: "*/15 * * * *"' in apply_workflow
    assert "group: canonical-vehicle-input" in apply_workflow
    assert "retail_lineup_apply_worker.py next --status APPLYING" in apply_workflow
    assert "retail_lineup_apply_worker.py mark-written" in apply_workflow
    assert "tools.publish_canonical --revision" in apply_workflow
    assert "retail_lineup_apply_worker.py complete" in apply_workflow
