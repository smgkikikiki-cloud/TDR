from __future__ import annotations

import json
from types import SimpleNamespace

from tools import pricefeed_guard


def test_repo_path_embeds_vehicle_master_prefix() -> None:
    assert pricefeed_guard.repo_path(
        "automotive/vehicle_master/", "vehreg/data/2026/market/"
    ) == "automotive/vehicle_master/vehreg/data/2026/market/"
    assert pricefeed_guard.repo_path("", "vehreg/data/2026/market/") == (
        "vehreg/data/2026/market/"
    )


def test_ledger_at_uses_repository_root_prefix(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        target = args[-1]
        if target.endswith("/prices"):
            return SimpleNamespace(returncode=0, stdout="tree\nheader\ntoyota.json\n")
        payload = {
            "prices": [
                {
                    "trim_id": "trim:test",
                    "price_type": "LIST_PRICE",
                    "amount_thb": 999000,
                }
            ]
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload))

    monkeypatch.setattr(pricefeed_guard.subprocess, "run", fake_run)

    result = pricefeed_guard.ledger_at(
        "origin/main", 2026, repo_prefix="automotive/vehicle_master/"
    )

    assert result == {"trim:test": 999000}
    assert calls[0][-1] == (
        "origin/main:automotive/vehicle_master/vehreg/data/2026/market/prices"
    )
    assert calls[1][-1] == (
        "origin/main:automotive/vehicle_master/vehreg/data/2026/market/prices/toyota.json"
    )


def test_main_accepts_repo_prefix(monkeypatch) -> None:
    captured = {}

    def fake_check(base, **kwargs):
        captured["base"] = base
        captured.update(kwargs)
        return []

    monkeypatch.setattr(pricefeed_guard, "check", fake_check)

    assert pricefeed_guard.main(
        ["--base", "origin/main", "--repo-prefix", "automotive/vehicle_master/"]
    ) == 0
    assert captured["repo_prefix"] == "automotive/vehicle_master/"
