from __future__ import annotations

import json
from pathlib import Path

import pytest

from vehreg.canonical_queue import (
    CanonicalQueueError,
    adapt_legacy_model_shadow,
    process_legacy_model_shadow,
    revision_payload,
)


YEAR = 2026
MODEL_ID = "jaecoo.jaecoo_5_ev"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _seed(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    _write_json(data / "2026" / "models" / "jaecoo.json", {
        "brand": {
            "id": "jaecoo", "name_en": "Jaecoo", "name_th": "เจคู",
            "brand_segment": "MASS", "oem_group": "Chery",
            "brand_origin": "CN", "trim_detail": True, "aliases": [],
        },
        "models": [{
            "id": "jaecoo_5_ev", "name_en": "Jaecoo 5 EV",
            "name_th": "เจคู 5", "nameplate": "Jaecoo 5",
            "body_type": "CROSSOVER", "cab_type": "NOT_APPLICABLE",
            "registration_type": "", "market_scope": "CORE", "aliases": [],
            "generations": [{
                "code": "J5", "segment": "B", "seats": 5,
                "launched": "2025-08-19", "ended": None,
                "variants": [{
                    "name": "58.9 kWh BEV CBU", "powertrain": "BEV",
                    "drivetrain": "FWD", "engine_cc": None,
                    "battery_kwh": 58.9, "price_thb": None,
                    "price_min_thb": None, "price_max_thb": None,
                    "import_type": "CBU", "origin_country": "CN",
                    "aliases": [],
                }],
                "trims": [],
            }],
        }],
    })
    return data


def _row(**overrides):
    row = {
        "id": "00000000-0000-0000-0000-000000000001",
        "command_key": "tdr-model-save:j5:test",
        "status": "queued",
        "canonical_id": MODEL_ID,
        "actor": "test-admin",
        "reason": "shadow test",
        "created_at": "2026-09-09T00:00:00+00:00",
        "payload": {
            "model": {
                "slug": "jaecoo-jaecoo-5-ev",
                "brand_id": "legacy-brand-uuid",
                "name_th": "เจคู 5",
                "generation": "gen1",
                "segment": "B",
                "body_type": "Crossover",
                "production_type": "CBU",
                "production_country": "CN",
                "status": "current",
                "seats": 5,
                "notes": "reviewed note",
            },
            "powertrains": [],
            "trims": [],
        },
    }
    row.update(overrides)
    return row


def test_adapter_uses_verified_canonical_generation_not_legacy_gen1(tmp_path: Path):
    data = _seed(tmp_path)
    adapted = adapt_legacy_model_shadow(_row(), data_dir=data, year=YEAR)
    bundle = adapted.command["payload"]
    assert bundle["generation"]["code"] == "J5"
    assert bundle["model"]["body_type"] == "Crossover"
    assert bundle["generation"]["segment"] == "B"
    assert "generation" in adapted.ignored_legacy_fields
    assert "production_type" in adapted.ignored_legacy_fields
    assert bundle["variants"] == [] and bundle["trims"] == []


def test_adapter_refuses_unverified_or_child_semantics(tmp_path: Path):
    data = _seed(tmp_path)
    with pytest.raises(CanonicalQueueError, match="only queued"):
        adapt_legacy_model_shadow(_row(status="needs_crosswalk"), data_dir=data, year=YEAR)

    child = _row()
    child["payload"]["trims"] = [{"name": "Dynamic"}]
    with pytest.raises(CanonicalQueueError, match="verified child crosswalks"):
        adapt_legacy_model_shadow(child, data_dir=data, year=YEAR)


def test_queue_adapter_can_apply_and_revision_can_be_mirrored(tmp_path: Path):
    data = _seed(tmp_path)
    result, adapted = process_legacy_model_shadow(_row(), data_dir=data, year=YEAR)
    assert result.topic == "catalog"
    revision = revision_payload(data, YEAR, result.revision_id)
    assert revision["entity_id"] == MODEL_ID
    assert revision["command_id"] == adapted.command["command_id"]

    # Exact queue retry is canonical-writer idempotent.
    replay, _ = process_legacy_model_shadow(_row(), data_dir=data, year=YEAR)
    assert replay.idempotent_replay
    assert replay.revision_id == result.revision_id
