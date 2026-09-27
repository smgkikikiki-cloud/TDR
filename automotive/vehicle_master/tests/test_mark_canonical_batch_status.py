"""tools/mark_canonical_batch_status.py -- moves one canonical_input_batches
row to NEEDS_REVIEW/REJECTED via the existing _patch() primitive. Network
calls mocked; these cover the status allowlist, CAS behavior, and that only
status/updated_at/error are ever written.
"""
from __future__ import annotations

import pytest

import tools.mark_canonical_batch_status as subject


def test_rejects_disallowed_target_status(monkeypatch):
    with pytest.raises(SystemExit, match="NEEDS_REVIEW.*REJECTED|REJECTED.*NEEDS_REVIEW"):
        subject.mark("some-batch", "PUBLISHED", "trying to fake a publish")


def test_missing_row_raises(monkeypatch):
    monkeypatch.setattr(subject, "_current_row", lambda batch_key: None)
    with pytest.raises(SystemExit, match="no canonical_input_batches row"):
        subject.mark("missing-batch", "REJECTED", "not found")


def test_marks_rejected_using_current_status_as_cas_expectation(monkeypatch):
    captured = {}

    def fake_current_row(batch_key):
        return {"id": "row-1", "status": "QUEUED"}

    def fake_patch(row_id, expected_status, payload):
        captured["row_id"] = row_id
        captured["expected_status"] = expected_status
        captured["payload"] = payload
        return [{"id": row_id, **payload}]

    monkeypatch.setattr(subject, "_current_row", fake_current_row)
    monkeypatch.setattr(subject, "_patch", fake_patch)

    subject.mark("ev-retail-repair-lot-02-2026-09-27", "REJECTED", "unknown campaign refs")

    assert captured["row_id"] == "row-1"
    assert captured["expected_status"] == "QUEUED"  # CAS: only patches what it just read
    assert set(captured["payload"]) == {"status", "updated_at", "error"}
    assert captured["payload"]["status"] == "REJECTED"
    assert captured["payload"]["error"] == "unknown campaign refs"


def test_stale_row_raises_instead_of_silently_no_opping(monkeypatch):
    monkeypatch.setattr(subject, "_current_row", lambda batch_key: {"id": "row-1", "status": "QUEUED"})
    monkeypatch.setattr(subject, "_patch", lambda row_id, expected_status, payload: [])

    with pytest.raises(SystemExit, match="no longer at status"):
        subject.mark("some-batch", "REJECTED", "reason")
