"""tdr_bridge.publish's client half of migration_v48's staged release
protocol: the manifest it sends to begin_vehicle_release never carries the
six bulk section arrays, chunks are sent to stage_vehicle_release_chunk in
strict foreign-key order, a transient network failure is retried but a
real server rejection is not (retrying an invalid/rejected request would
just fail the same way again), an already-finalized release short-circuits
before any chunk is sent, retention runs after a successful/confirmed ACTIVE
release, and every phase's timing is reported.

No real HTTP or Postgres here -- urlopen itself is faked so these stay
fast and only exercise the client's own orchestration; the RPCs' actual
behavior (idempotency, FK-order enforcement, manifest-based count
validation) is proven against a real Postgres in
test_staged_vehicle_release_migration_v48.py.
"""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from tdr_bridge import publish


def _release(sections: dict | None = None) -> dict:
    sections = sections or {}
    counts = {section: len(sections.get(section, [])) for section in publish.RELEASE_SECTIONS}
    release = {
        "schema_version": 1,
        "release_id": "vehicle-2026-abcdef0123456789",
        "canonical_revision": "rev",
        "source_hash": "abcdef0123456789",
        "as_of": "2026-09-23",
        "year": 2026,
        "counts": counts,
        "trim_reconciliation": {"blockers": [], "counts": {}},
        "historical_model_state": {"catalog_years": [2026], "model_year_baselines": [],
                                   "monthly_changes": []},
    }
    for section in publish.RELEASE_SECTIONS:
        release[section] = sections.get(section, [])
    return release


def _ok_response(payload: dict) -> MagicMock:
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    return cm


def _retention_response() -> dict:
    return {"deleted_superseded": 0, "deleted_staging": 0, "kept_superseded": 1}


def _rpc_name(request) -> str:
    return request.full_url.rsplit("/", 1)[-1]


def test_manifest_drops_bulk_arrays_and_trim_reconciliation_but_keeps_metadata():
    release = _release(sections={"brands": [{"canonical_id": "a"}],
                                 "spec_facts": [{"fact_id": "f"}]})
    manifest = publish._manifest(release)
    for section in publish.RELEASE_SECTIONS:
        assert section not in manifest
    assert "trim_reconciliation" not in manifest
    assert manifest["year"] == 2026
    assert manifest["historical_model_state"] == release["historical_model_state"]
    assert manifest["counts"] == release["counts"]


def test_manifest_is_an_explicit_allowlist_not_bulk_keys_dropped_from_everything_else():
    # A new release field -- some future diagnostic report, extra
    # metadata nobody thought to exclude -- must not be sent just because
    # it isn't one of the six bulk arrays or trim_reconciliation. Only
    # MANIFEST_FIELDS, kept in lockstep with migration_v48's own
    # _release_semantic_manifest() SQL allowlist, is ever included.
    release = _release()
    release["created_at"] = "2026-09-23T00:00:00Z"
    release["some_future_diagnostic_report"] = {"huge": list(range(10_000))}
    manifest = publish._manifest(release)
    assert set(manifest) <= set(publish.MANIFEST_FIELDS)
    assert "created_at" not in manifest
    assert "some_future_diagnostic_report" not in manifest


def test_chunks_splits_rows_by_size_and_yields_nothing_for_an_empty_section():
    rows = [{"i": i} for i in range(7)]
    chunks = list(publish._chunks(rows, 3))
    assert [index for index, _ in chunks] == [0, 1, 2]
    assert [len(chunk) for _, chunk in chunks] == [3, 3, 1]
    assert list(publish._chunks([], 3)) == []


def test_chunk_hash_is_deterministic_and_content_sensitive():
    rows_a = [{"canonical_id": "a"}]
    rows_b = [{"canonical_id": "b"}]
    assert publish._chunk_hash(rows_a) == publish._chunk_hash(rows_a)
    assert publish._chunk_hash(rows_a) != publish._chunk_hash(rows_b)


def test_publish_staged_calls_begin_then_chunks_in_fk_order_then_activate():
    release = _release(sections={"brands": [{"canonical_id": "a"}],
                                 "models": [{"canonical_id": "m"}]})
    calls: list[str] = []

    def fake_urlopen(request, timeout=None):
        name = _rpc_name(request)
        calls.append(name)
        if name == "begin_vehicle_release":
            return _ok_response({"release_id": release["release_id"], "status": "STAGING",
                                 "counts": release["counts"], "staged": {}})
        if name == "stage_vehicle_release_chunk":
            body = json.loads(request.data.decode())
            return _ok_response({"status": "staged", "row_count": len(body["p_rows"])})
        if name == "activate_vehicle_release":
            return _ok_response({"release_id": release["release_id"], "status": "ACTIVE",
                                 "counts": release["counts"]})
        if name == "prune_vehicle_releases":
            return _ok_response(_retention_response())
        raise AssertionError(f"unexpected rpc {name}")

    with patch("tdr_bridge.publish.urlopen", side_effect=fake_urlopen):
        result = publish.publish_staged(release, url="https://example.supabase.co", service_key="k")

    assert calls[0] == "begin_vehicle_release"
    assert calls[-2:] == ["activate_vehicle_release", "prune_vehicle_releases"]
    assert calls[1:-2] == ["stage_vehicle_release_chunk", "stage_vehicle_release_chunk"]
    assert result["status"] == "ACTIVE"
    assert result["retention"]["kept_superseded"] == 1


def test_publish_staged_stops_before_any_chunk_when_already_finalized():
    release = _release(sections={"brands": [{"canonical_id": "a"}]})
    calls: list[str] = []

    def fake_urlopen(request, timeout=None):
        name = _rpc_name(request)
        calls.append(name)
        if name == "begin_vehicle_release":
            return _ok_response({"release_id": release["release_id"], "status": "ACTIVE",
                                 "already_finalized": True})
        if name == "prune_vehicle_releases":
            return _ok_response(_retention_response())
        raise AssertionError(f"unexpected rpc {name}")

    with patch("tdr_bridge.publish.urlopen", side_effect=fake_urlopen):
        result = publish.publish_staged(release, url="https://example.supabase.co", service_key="k")

    assert calls == ["begin_vehicle_release", "prune_vehicle_releases"]
    assert result["already_finalized"] is True


def test_publish_staged_raises_when_the_release_is_already_superseded():
    # already_finalized=True covers two very different situations:
    # ACTIVE (this exact release_id really is what is serving right now --
    # a legitimate retry success) and SUPERSEDED (it was once active and
    # is not anymore -- some other release is serving). Treating both as
    # success would let an exact-publish request for release_id X report
    # success while a different release entirely is what production
    # actually serves.
    release = _release(sections={"brands": [{"canonical_id": "a"}]})
    calls: list[str] = []

    def fake_urlopen(request, timeout=None):
        name = _rpc_name(request)
        calls.append(name)
        assert name == "begin_vehicle_release"
        return _ok_response({"release_id": release["release_id"], "status": "SUPERSEDED",
                             "already_finalized": True})

    with patch("tdr_bridge.publish.urlopen", side_effect=fake_urlopen):
        with pytest.raises(RuntimeError, match="SUPERSEDED"):
            publish.publish_staged(release, url="https://example.supabase.co", service_key="k")

    assert calls == ["begin_vehicle_release"]


def test_publish_staged_retries_a_transient_network_failure_and_succeeds(monkeypatch):
    monkeypatch.setattr(publish.time, "sleep", lambda seconds: None)
    release = _release(sections={"brands": [{"canonical_id": "a"}]})
    attempts = {"begin": 0}

    def fake_urlopen(request, timeout=None):
        name = _rpc_name(request)
        if name == "begin_vehicle_release":
            attempts["begin"] += 1
            if attempts["begin"] < 3:
                raise URLError("connection reset")
            return _ok_response({"release_id": release["release_id"], "status": "STAGING",
                                 "counts": release["counts"], "staged": {}})
        if name == "stage_vehicle_release_chunk":
            return _ok_response({"status": "staged", "row_count": 1})
        if name == "activate_vehicle_release":
            return _ok_response({"release_id": release["release_id"], "status": "ACTIVE",
                                 "counts": release["counts"]})
        if name == "prune_vehicle_releases":
            return _ok_response(_retention_response())
        raise AssertionError(f"unexpected rpc {name}")

    with patch("tdr_bridge.publish.urlopen", side_effect=fake_urlopen):
        result = publish.publish_staged(release, url="https://example.supabase.co", service_key="k")

    assert attempts["begin"] == 3
    assert result["status"] == "ACTIVE"


def test_publish_staged_does_not_retry_a_real_server_rejection():
    # A 4xx from PostgREST means the RPC ran and Postgres refused it --
    # a real conflict, a stale revision, a validation failure. Retrying
    # the identical request would just fail the same way every time, so
    # this must surface on the first attempt, not the third.
    release = _release(sections={"brands": [{"canonical_id": "a"}]})
    calls = {"begin": 0}

    def fake_urlopen(request, timeout=None):
        assert _rpc_name(request) == "begin_vehicle_release"
        calls["begin"] += 1
        raise HTTPError(request.full_url, 400, "Bad Request", hdrs=None,
                        fp=io.BytesIO(b'{"message":"invalid release_id"}'))

    with patch("tdr_bridge.publish.urlopen", side_effect=fake_urlopen):
        with pytest.raises(RuntimeError, match="invalid release_id"):
            publish.publish_staged(release, url="https://example.supabase.co", service_key="k")

    assert calls["begin"] == 1


def test_publish_staged_reports_timings_for_every_phase():
    release = _release(sections={"brands": [{"canonical_id": "a"}, {"canonical_id": "b"}]})

    def fake_urlopen(request, timeout=None):
        name = _rpc_name(request)
        if name == "begin_vehicle_release":
            return _ok_response({"release_id": release["release_id"], "status": "STAGING",
                                 "counts": release["counts"], "staged": {}})
        if name == "stage_vehicle_release_chunk":
            return _ok_response({"status": "staged", "row_count": 1})
        if name == "activate_vehicle_release":
            return _ok_response({"release_id": release["release_id"], "status": "ACTIVE",
                                 "counts": release["counts"]})
        if name == "prune_vehicle_releases":
            return _ok_response(_retention_response())
        raise AssertionError(f"unexpected rpc {name}")

    with patch("tdr_bridge.publish.urlopen", side_effect=fake_urlopen):
        result = publish.publish_staged(release, url="https://example.supabase.co", service_key="k",
                                        chunk_size=1)

    timings = result["timings"]
    assert set(timings) == {"begin", "chunks", "activate", "prune", "largest_chunk", "total"}
    assert timings["chunks"]["brands"]["count"] == 2
    assert timings["chunks"]["brands"]["total_seconds"] >= 0
    assert timings["total"] >= timings["begin"]
