from __future__ import annotations

import json
from pathlib import Path

import pytest

from vehreg.input_pipeline import CanonicalInputError, CanonicalInputPipeline
from vehreg.model_operational_state import (
    ModelOperationalStateError,
    load_model_operational_states,
    under_maintenance_model_ids,
    upsert_model_operational_state,
)

YEAR = 2026
MODEL_ID = "jaecoo.jaecoo_5_ev"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    _write_json(data / str(YEAR) / "models" / "jaecoo.json", {
        "brand": {
            "id": "jaecoo", "name_en": "Jaecoo", "name_th": "เจคู",
            "brand_segment": "MASS", "oem_group": "Chery", "brand_origin": "CN",
            "trim_detail": True, "aliases": [],
        },
        "models": [{
            "id": "jaecoo_5_ev", "name_en": "Jaecoo 5 EV", "name_th": "เจคู 5",
            "nameplate": "Jaecoo 5", "body_type": "CROSSOVER",
            "cab_type": "NOT_APPLICABLE", "registration_type": "",
            "market_scope": "CORE", "aliases": [],
            "retail_status": "CURRENT",
            "retail_checked_at": "2026-09-11",
            "retail_source": "https://example.test/j5/model",
            "generations": [{
                "code": "J5", "segment": "B", "seats": 5,
                "launched": "2025-08-19", "ended": None,
                "variants": [{
                    "id": "bev_cbu", "name": "58.9 kWh BEV CBU", "powertrain": "BEV",
                    "drivetrain": "FWD", "engine_cc": None, "battery_kwh": 58.9,
                    "price_thb": None, "price_min_thb": None, "price_max_thb": None,
                    "import_type": "CBU", "origin_country": "CN",
                    "price_note": "", "aliases": [],
                }],
                "trims": [{
                    "id": "ultra_bev", "name": "Ultra", "variant": "58.9 kWh BEV CBU",
                    "powertrain": "BEV", "drivetrain": "FWD", "battery_kwh": 58.9,
                    "seats": 5, "aliases": [],
                    "source_refs": {"oem": ["https://example.test/j5"]},
                }],
            }],
        }],
    })
    state = data / str(YEAR) / "canonical_state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "revisions.jsonl").write_text('{"old":true}\n', encoding="utf-8")
    (state / "outbox.jsonl").write_text('{"old":true}\n', encoding="utf-8")
    _write_json(state / "shadow" / "old.json", {"old": True})
    return data


def _batch(action: str = "under_maintenance", *, actor: str = "ops-reviewer",
          batch_id: str = "model-maintenance") -> dict:
    payload = {"model_id": MODEL_ID, "action": action, "notes": "generation changeover"}
    return {
        "schema_version": 1,
        "batch_id": batch_id,
        "year": YEAR,
        "source": {"kind": "ADMIN", "ref": "https://example.test/ops"},
        "actor": actor,
        "reason": "operational state change",
        "submitted_at": "2026-09-24T05:00:00+00:00",
        "commands": [{"operation": "UPSERT_MODEL_OPERATIONAL_STATE", "payload": payload}],
    }


def test_under_maintenance_is_sidecar_only_and_does_not_fake_canonical_audit_changes(tmp_path: Path):
    data = _seed(tmp_path)
    result = CanonicalInputPipeline(data).apply(_batch())
    assert result.status == "APPLIED"
    assert any(path.endswith("market/operational_state/model_state.json")
              for path in result.changed_files)
    assert not any(path.endswith("canonical_state/revisions.jsonl") for path in result.changed_files)
    assert not any(path.endswith("canonical_state/outbox.jsonl") for path in result.changed_files)
    assert not any("canonical_state/shadow/old.json" in path for path in result.changed_files)
    assert load_model_operational_states(data_dir=data, year=YEAR) == [{
        "model_id": MODEL_ID, "status": "UNDER_MAINTENANCE", "reviewer": "ops-reviewer",
        "reviewed_at": "2026-09-24", "source_ref": "", "notes": "generation changeover",
    }]
    assert under_maintenance_model_ids(data_dir=data, year=YEAR) == frozenset({MODEL_ID})


def test_normal_clears_the_stored_maintenance_row(tmp_path: Path):
    data = _seed(tmp_path)
    CanonicalInputPipeline(data).apply(_batch("under_maintenance"))
    assert under_maintenance_model_ids(data_dir=data, year=YEAR) == frozenset({MODEL_ID})
    CanonicalInputPipeline(data).apply(_batch("normal", batch_id="model-normal"))
    assert load_model_operational_states(data_dir=data, year=YEAR) == []
    assert under_maintenance_model_ids(data_dir=data, year=YEAR) == frozenset()


def test_rejects_non_human_actor_and_non_admin_source(tmp_path: Path):
    data = _seed(tmp_path)
    with pytest.raises(CanonicalInputError, match="explicit HUMAN actor"):
        CanonicalInputPipeline(data).apply(_batch(actor="agent-proposed"))
    batch = _batch(batch_id="wrong-source")
    batch["source"]["kind"] = "OEM"
    with pytest.raises(CanonicalInputError, match="requires source.kind ADMIN"):
        CanonicalInputPipeline(data).apply(batch)


def test_rejects_unknown_action(tmp_path: Path):
    data = _seed(tmp_path)
    batch = _batch()
    batch["commands"][0]["payload"]["action"] = "paused"
    with pytest.raises(CanonicalInputError, match="action must be under_maintenance or normal"):
        CanonicalInputPipeline(data).apply(batch)


def test_direct_store_requires_known_model_and_human_reviewer(tmp_path: Path):
    data = _seed(tmp_path)
    with pytest.raises(ModelOperationalStateError, match="unknown Model"):
        upsert_model_operational_state(
            data_dir=data, year=YEAR, model_id="fake.model", action="under_maintenance",
            reviewer="ops-reviewer", reviewed_at="2026-09-24", write=True,
        )
    with pytest.raises(ModelOperationalStateError, match="explicit HUMAN reviewer"):
        upsert_model_operational_state(
            data_dir=data, year=YEAR, model_id=MODEL_ID, action="under_maintenance",
            reviewer="system", reviewed_at="2026-09-24", write=True,
        )


def test_no_stored_row_means_normal(tmp_path: Path):
    data = _seed(tmp_path)
    assert load_model_operational_states(data_dir=data, year=YEAR) == []
    assert under_maintenance_model_ids(data_dir=data, year=YEAR) == frozenset()
