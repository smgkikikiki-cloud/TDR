"""tools.pricefeed_harvest.main(): one dead outlet must not fail the run
(test_pricefeed_resilience_cutover.py already proves harvest() itself
keeps going past it), but every candidate source being unreachable is not
"no news today" -- it means the network is down or every outlet is,
and the workflow tick should fail/alert instead of silently exiting 0.
"""

from __future__ import annotations

import unittest.mock

import pytest

from tools import pricefeed_harvest as harvest_mod


def _source(source_id: str, url: str):
    from vehreg import pricefeed as pf
    return pf.Source(id=source_id, name=source_id, tier=pf.Tier("B"),
                     adapter="wordpress", base_url=url)


@pytest.fixture
def two_sources(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    models_dir = data_dir / "2026" / "models"
    models_dir.mkdir(parents=True)
    (models_dir / "toyota.json").write_text(
        '{"brand": {"id": "toyota", "name_en": "Toyota", "name_th": "โตโยต้า", '
        '"brand_segment": "MASS", "brand_origin": "JP", "aliases": []}, '
        '"models": []}', encoding="utf-8")
    feed_dir = data_dir / "2026" / "market" / "pricefeed"
    feed_dir.mkdir(parents=True)
    (feed_dir / "sources.json").write_text(
        '{"sources": ['
        '{"id": "outlet_a", "name": "A", "tier": "B", "adapter": "wordpress", '
        '"base_url": "https://a.example.test"},'
        '{"id": "outlet_b", "name": "B", "tier": "B", "adapter": "wordpress", '
        '"base_url": "https://b.example.test"}'
        ']}', encoding="utf-8")
    return data_dir


def _list_posts_all_fail(base_url, **_):
    raise harvest_mod.HarvestError("connection refused")


def _list_posts_one_fails(base_url, **_):
    if "a.example" in base_url:
        raise harvest_mod.HarvestError("connection refused")
    return []


def test_every_source_unreachable_exits_nonzero(two_sources, tmp_path, monkeypatch):
    monkeypatch.setattr(harvest_mod.robots_check, "audit", lambda *_: {})
    monkeypatch.setattr(harvest_mod.robots_check, "verdict", lambda *_: "allowed")
    monkeypatch.setattr(harvest_mod, "list_posts", _list_posts_all_fail)

    exit_code = harvest_mod.main([
        "--since", "2026-09-01", "--data-dir", str(two_sources), "--year", "2026",
        "--out", str(tmp_path / "batch.json"), "--delay", "0",
    ])
    assert exit_code == 1


def test_one_source_unreachable_still_exits_zero(two_sources, tmp_path, monkeypatch):
    monkeypatch.setattr(harvest_mod.robots_check, "audit", lambda *_: {})
    monkeypatch.setattr(harvest_mod.robots_check, "verdict", lambda *_: "allowed")
    monkeypatch.setattr(harvest_mod, "list_posts", _list_posts_one_fails)

    exit_code = harvest_mod.main([
        "--since", "2026-09-01", "--data-dir", str(two_sources), "--year", "2026",
        "--out", str(tmp_path / "batch.json"), "--delay", "0",
    ])
    assert exit_code == 0
