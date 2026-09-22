from __future__ import annotations

import json
from pathlib import Path

from tools import requeue_canonical_result as subject


def test_requeue_only_applied_processing_batches(tmp_path: Path, monkeypatch):
    result_file = tmp_path / "result.json"
    result_file.write_text(json.dumps({
        "applied": [
            {"id": "batch-a", "batch_key": "a"},
            {"id": "batch-b", "batch_key": "b"},
        ],
        "failed": [{"id": "batch-c", "batch_key": "c", "error": "bad input"}],
    }), encoding="utf-8")

    calls = []

    def fake_patch(row_id, expected_status, payload):
        calls.append((row_id, expected_status, payload))
        return [{"id": row_id}]

    monkeypatch.setattr(subject, "_patch", fake_patch)

    assert subject.requeue(result_file, "validation exploded") == 0
    assert [call[0] for call in calls] == ["batch-a", "batch-b"]
    assert all(call[1] == "PROCESSING" for call in calls)
    assert all(call[2]["status"] == "QUEUED" for call in calls)
    assert all(call[2]["processing_started_at"] is None for call in calls)
    assert all(call[2]["error"] == "validation exploded" for call in calls)


def test_requeue_is_safe_when_batch_already_left_processing(tmp_path: Path, monkeypatch):
    result_file = tmp_path / "result.json"
    result_file.write_text(json.dumps({
        "applied": [{"id": "batch-a", "batch_key": "a"}],
        "failed": [],
    }), encoding="utf-8")

    monkeypatch.setattr(subject, "_patch", lambda *_args, **_kwargs: [])
    assert subject.requeue(result_file, "validation exploded") == 0
