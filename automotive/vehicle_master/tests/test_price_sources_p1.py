import json
from pathlib import Path

import pytest

from vehreg.catalog import DATA_DIR, DEFAULT_YEAR
from vehreg.price_sources import (
    SourceKind,
    TargetRole,
    load_source_target_registry,
)
from vehreg.pricefeed import Tier


def _write(tmp_path: Path, *, targets: list[dict],
           profiles: list[dict] | None = None) -> None:
    folder = tmp_path / "2026" / "market" / "pricefeed"
    folder.mkdir(parents=True)
    (folder / "sources.json").write_text(json.dumps({
        "sources": [
            {
                "id": "oem_x",
                "name": "OEM X Thailand",
                "tier": "A",
                "base_url": "https://example.com",
                "adapter": "manual",
                "poll_minutes": 360,
            },
            {
                "id": "media_x",
                "name": "Media X",
                "tier": "B",
                "base_url": "https://media.example.com",
                "adapter": "wordpress",
                "poll_minutes": 20,
            },
        ]
    }), encoding="utf-8")
    (folder / "targets.json").write_text(json.dumps({
        "schema_version": 1,
        "source_profiles": profiles or [
            {"source_id": "oem_x", "kind": "OEM"},
            {"source_id": "media_x", "kind": "MEDIA"},
        ],
        "targets": targets,
    }), encoding="utf-8")


def test_live_registry_separates_legacy_generic_source_from_jaecoo() -> None:
    registry = load_source_target_registry(DATA_DIR, DEFAULT_YEAR)

    assert registry.sources["official_jaecoo_th"].tier is Tier.A
    assert registry.profiles["official_jaecoo_th"].kind is SourceKind.OEM
    assert registry.profiles["official_oem"].legacy is True
    assert registry.targets_for(source_id="official_oem") == []

    jaecoo = registry.targets_for(source_id="official_jaecoo_th")
    assert {target.role for target in jaecoo} == {
        TargetRole.CURRENT_MODEL_PAGE,
        TargetRole.PROMOTION_INDEX,
        TargetRole.BLOG,
    }
    assert next(target for target in jaecoo
                if target.role is TargetRole.CURRENT_MODEL_PAGE).model_hint == \
        "jaecoo.jaecoo_5_ev"


def test_target_override_and_source_defaults_are_independent(tmp_path: Path) -> None:
    _write(tmp_path, targets=[
        {
            "id": "oem_model",
            "source_id": "oem_x",
            "url": "https://example.com/model/x",
            "role": "CURRENT_MODEL_PAGE",
        },
        {
            "id": "media_feed",
            "source_id": "media_x",
            "url": "https://media.example.com",
            "role": "DISCOVERY_FEED",
            "adapter": "custom-feed",
            "poll_minutes": 45,
        },
    ])
    registry = load_source_target_registry(tmp_path, 2026)

    oem = registry.targets["oem_model"]
    media = registry.targets["media_feed"]
    assert registry.effective_adapter(oem) == "manual"
    assert registry.effective_poll_minutes(oem) == 360
    assert registry.effective_adapter(media) == "custom-feed"
    assert registry.effective_poll_minutes(media) == 45


def test_disabled_targets_do_not_join_active_fetch_set(tmp_path: Path) -> None:
    _write(tmp_path, targets=[
        {
            "id": "active",
            "source_id": "oem_x",
            "url": "https://example.com/a",
            "role": "PRICE_LIST",
            "enabled": True,
        },
        {
            "id": "disabled",
            "source_id": "oem_x",
            "url": "https://example.com/b",
            "role": "PRESS_RELEASE",
            "enabled": False,
        },
    ])
    registry = load_source_target_registry(tmp_path, 2026)

    assert [target.id for target in registry.targets_for(source_id="oem_x")] == ["active"]
    assert [target.id for target in registry.targets_for(
        source_id="oem_x", enabled_only=False)] == ["active", "disabled"]


@pytest.mark.parametrize("mutation,match", [
    (
        {"source_id": "missing"},
        "unknown source missing",
    ),
    (
        {"url": "http://example.com/model/x"},
        "url must be absolute https",
    ),
    (
        {"role": "WHATEVER"},
        "unknown target role",
    ),
    (
        {"poll_minutes": 0},
        "poll_minutes must be positive",
    ),
])
def test_bad_targets_are_rejected(tmp_path: Path, mutation: dict, match: str) -> None:
    target = {
        "id": "oem_model",
        "source_id": "oem_x",
        "url": "https://example.com/model/x",
        "role": "CURRENT_MODEL_PAGE",
    }
    target.update(mutation)
    _write(tmp_path, targets=[target])

    with pytest.raises(ValueError, match=match):
        load_source_target_registry(tmp_path, 2026)


def test_duplicate_target_ids_are_rejected(tmp_path: Path) -> None:
    target = {
        "id": "same",
        "source_id": "oem_x",
        "url": "https://example.com/model/x",
        "role": "CURRENT_MODEL_PAGE",
    }
    _write(tmp_path, targets=[target, dict(target, url="https://example.com/model/y")])

    with pytest.raises(ValueError, match="duplicate target id"):
        load_source_target_registry(tmp_path, 2026)


def test_model_hint_never_changes_source_authority(tmp_path: Path) -> None:
    _write(tmp_path, targets=[{
        "id": "hinted",
        "source_id": "media_x",
        "url": "https://media.example.com/post/1",
        "role": "BLOG",
        "model_hint": "brand.model",
    }])
    registry = load_source_target_registry(tmp_path, 2026)

    target = registry.targets["hinted"]
    assert target.model_hint == "brand.model"
    assert registry.sources[target.source_id].tier is Tier.B
    assert registry.profiles[target.source_id].kind is SourceKind.MEDIA
