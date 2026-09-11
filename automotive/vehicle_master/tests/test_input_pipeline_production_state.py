"""APPEND_PRODUCTION_STATE through the batch input pipeline.

data/research/ sits beside vehreg/data, not under it, so CanonicalInputPipeline
must stage/copy-back that sibling too -- this is the one command whose write
target lives outside the tree the pipeline normally sandboxes.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from vehreg.input_pipeline import CanonicalInputError, CanonicalInputPipeline

YEAR = 2026
MODEL_ID = "jaecoo.jaecoo_5_ev"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed(tmp_path: Path) -> Path:
    """Real repo shape: <root>/vehreg/data and <root>/data/research side by side."""
    root = tmp_path / "vehicle_master"
    data = root / "vehreg" / "data"
    _write_json(data / str(YEAR) / "models" / "jaecoo.json", {
        "brand": {
            "id": "jaecoo", "name_en": "Jaecoo", "name_th": "เจคู",
            "brand_segment": "MASS", "oem_group": "Chery", "brand_origin": "CN",
            "trim_detail": True, "aliases": [],
        },
        "models": [{
            "id": "jaecoo_5_ev", "name_en": "Jaecoo 5 EV", "name_th": "เจคู 5",
            "nameplate": "Jaecoo 5", "body_type": "CROSSOVER", "cab_type": "NOT_APPLICABLE",
            "registration_type": "", "market_scope": "CORE", "aliases": [],
            "generations": [{
                "code": "J5", "segment": "B", "seats": 5, "launched": "2025-08-19", "ended": None,
                "variants": [{
                    "id": "bev_cbu", "name": "58.9 kWh BEV CBU", "powertrain": "BEV",
                    "drivetrain": "FWD", "engine_cc": None, "battery_kwh": 58.9,
                    "aliases": [], "overrides": {},
                }],
                "trims": [],
            }],
        }],
    })
    return data


def _batch(*, batch_id: str = "admin-state-20260911") -> dict:
    return {
        "schema_version": 1,
        "batch_id": batch_id,
        "year": YEAR,
        "source": {"kind": "ADMIN", "ref": None},
        "actor": "owner",
        "reason": "reviewed production-country change",
        "submitted_at": "2026-09-11T00:00:00+00:00",
        "commands": [{
            "operation": "APPEND_PRODUCTION_STATE",
            "canonical_id": MODEL_ID,
            "payload": {
                "grain": "MODEL", "effective_month": "2026-03",
                "origin_country": "TH", "import_type": "CKD",
                "evidence": "Local assembly confirmed at Rayong plant",
                "source_url": "https://example.test/rayong",
            },
        }],
    }


def _rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_batch_stages_and_commits_the_research_csv(tmp_path: Path):
    data = _seed(tmp_path)
    research = data.parent.parent / "data" / "research"
    research.mkdir(parents=True)
    seed_csv = research / "monthly_production_state.csv"

    result = CanonicalInputPipeline(data).apply(_batch())

    assert any(path.endswith("monthly_production_state.csv") for path in result.changed_files)
    rows = _rows(seed_csv)
    assert len(rows) == 1
    assert rows[0]["unit_id"] == MODEL_ID
    assert rows[0]["origin_country"] == "TH"
    assert rows[0]["import_type"] == "CKD"


def test_a_rejected_command_never_touches_the_real_research_csv(tmp_path: Path):
    data = _seed(tmp_path)
    research = data.parent.parent / "data" / "research"
    research.mkdir(parents=True)
    seed_csv = research / "monthly_production_state.csv"

    bad = _batch()
    bad["commands"][0]["payload"]["evidence"] = ""
    with pytest.raises(CanonicalInputError):
        CanonicalInputPipeline(data).apply(bad)

    assert not seed_csv.exists()


def test_batch_replay_is_idempotent_for_production_state(tmp_path: Path):
    data = _seed(tmp_path)
    research = data.parent.parent / "data" / "research"
    research.mkdir(parents=True)
    seed_csv = research / "monthly_production_state.csv"

    pipeline = CanonicalInputPipeline(data)
    batch = _batch()
    pipeline.apply(batch)
    replay = pipeline.apply(batch)

    assert replay.idempotent_replay is True
    assert len(_rows(seed_csv)) == 1
