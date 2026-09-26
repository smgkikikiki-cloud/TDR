from __future__ import annotations

from tdr_bridge import publish as publish_module


def _release() -> dict:
    return {
        "schema_version": 1,
        "release_id": "vehicle-2026-0123456789abcdef",
        "canonical_revision": "deadbeef",
        "source_hash": "cafebabe",
        "as_of": "2026-09-26",
        "counts": {
            "brands": 0,
            "models": 0,
            "generations": 0,
            "market_trims": 0,
            "price_ledger": 0,
            "spec_facts": 0,
        },
        "brands": [],
        "models": [],
        "generations": [],
        "market_trims": [],
        "price_ledger": [],
        "spec_facts": [],
    }


def test_staged_publish_prunes_only_after_activation(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_rpc(name, params, **kwargs):
        calls.append((name, params))
        if name == "begin_vehicle_release":
            return {"release_id": _release()["release_id"], "status": "STAGING"}
        if name == "activate_vehicle_release":
            return {"release_id": _release()["release_id"], "status": "ACTIVE", "counts": _release()["counts"]}
        if name == "prune_vehicle_releases":
            return {"deleted_superseded": 1, "deleted_staging": 0, "kept_superseded": 1}
        raise AssertionError(name)

    monkeypatch.setattr(publish_module, "_rpc", fake_rpc)

    result = publish_module.publish_staged(_release(), url="https://example.supabase.co", service_key="secret")

    assert [name for name, _ in calls] == [
        "begin_vehicle_release",
        "activate_vehicle_release",
        "prune_vehicle_releases",
    ]
    assert result["status"] == "ACTIVE"
    assert result["retention"]["kept_superseded"] == 1


def test_active_retry_retries_retention_without_restaging(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_rpc(name, params, **kwargs):
        calls.append((name, params))
        if name == "begin_vehicle_release":
            return {
                "release_id": _release()["release_id"],
                "status": "ACTIVE",
                "already_finalized": True,
            }
        if name == "prune_vehicle_releases":
            return {"deleted_superseded": 0, "deleted_staging": 1, "kept_superseded": 1}
        raise AssertionError(name)

    monkeypatch.setattr(publish_module, "_rpc", fake_rpc)

    result = publish_module.publish_staged(_release(), url="https://example.supabase.co", service_key="secret")

    assert [name for name, _ in calls] == ["begin_vehicle_release", "prune_vehicle_releases"]
    assert result["already_finalized"] is True
    assert result["retention"]["deleted_staging"] == 1


def test_superseded_retry_still_fails_before_retention(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_rpc(name, params, **kwargs):
        calls.append((name, params))
        if name == "begin_vehicle_release":
            return {
                "release_id": _release()["release_id"],
                "status": "SUPERSEDED",
                "already_finalized": True,
            }
        raise AssertionError(name)

    monkeypatch.setattr(publish_module, "_rpc", fake_rpc)

    try:
        publish_module.publish_staged(_release(), url="https://example.supabase.co", service_key="secret")
    except RuntimeError as exc:
        assert "SUPERSEDED" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert [name for name, _ in calls] == ["begin_vehicle_release"]


def test_legacy_publish_also_prunes(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_rpc(name, params, **kwargs):
        calls.append((name, params))
        if name == "publish_vehicle_release":
            return {"release_id": _release()["release_id"], "status": "ACTIVE"}
        if name == "prune_vehicle_releases":
            return {"deleted_superseded": 1, "deleted_staging": 0, "kept_superseded": 1}
        raise AssertionError(name)

    monkeypatch.setattr(publish_module, "_rpc", fake_rpc)

    result = publish_module.publish(_release(), url="https://example.supabase.co", service_key="secret")

    assert [name for name, _ in calls] == ["publish_vehicle_release", "prune_vehicle_releases"]
    assert result["retention"]["deleted_superseded"] == 1
