"""APPEND_PRODUCTION_STATE: a live-editable analogue of the price ledger's
APPEND_PRICE, but for the two temporal facets (origin_country, import_type)
data/research/monthly_production_state.csv already carries as a reviewed
seed. Writing here, not a second file, means historical_state.py's next
release build picks the change up with no other change required.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from vehreg.canonical_write import CanonicalWriteError, CanonicalWritePipeline

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


def _command(command_id: str, payload: dict, canonical_id: str | None = MODEL_ID) -> dict:
    return {
        "command_id": command_id,
        "operation": "APPEND_PRODUCTION_STATE",
        "year": YEAR,
        "actor": "production-state-test",
        "reason": "contract test",
        "canonical_id": canonical_id,
        "payload": payload,
        "submitted_at": "2026-09-11T00:00:00+00:00",
    }


def _rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_append_writes_a_new_row_to_the_reviewed_seed_csv(tmp_path: Path):
    data = _seed(tmp_path)
    seed_csv = tmp_path / "research" / "monthly_production_state.csv"
    pipeline = CanonicalWritePipeline(data, production_state_path=seed_csv)

    result = pipeline.apply(_command("cmd-state-001", {
        "grain": "MODEL", "effective_month": "2025-09",
        "origin_country": "CN", "import_type": "CBU",
        "evidence": "Launch import before local assembly began",
        "source_url": "https://example.com/launch",
    }))

    assert result.topic == "production_state"
    assert any(path.endswith("monthly_production_state.csv") for path in result.changed_files)
    rows = _rows(seed_csv)
    assert len(rows) == 1
    assert rows[0]["unit_id"] == MODEL_ID
    assert rows[0]["effective_month"] == "2025-09"
    assert rows[0]["origin_country"] == "CN"
    assert rows[0]["import_type"] == "CBU"
    assert rows[0]["evidence"]


def test_resubmitting_the_same_change_point_replaces_it_not_duplicates(tmp_path: Path):
    data = _seed(tmp_path)
    seed_csv = tmp_path / "research" / "monthly_production_state.csv"
    pipeline = CanonicalWritePipeline(data, production_state_path=seed_csv)
    pipeline.apply(_command("cmd-state-001", {
        "grain": "MODEL", "effective_month": "2025-09",
        "origin_country": "CN", "import_type": "CBU", "evidence": "first pass",
    }))
    result = pipeline.apply(_command("cmd-state-002", {
        "grain": "MODEL", "effective_month": "2025-09",
        "origin_country": "TH", "import_type": "CKD", "evidence": "corrected: local assembly confirmed",
    }))

    rows = _rows(seed_csv)
    assert len(rows) == 1
    assert rows[0]["origin_country"] == "TH"
    assert rows[0]["import_type"] == "CKD"
    assert result.idempotent_replay is False


def test_a_second_effective_month_adds_a_second_change_point(tmp_path: Path):
    data = _seed(tmp_path)
    seed_csv = tmp_path / "research" / "monthly_production_state.csv"
    pipeline = CanonicalWritePipeline(data, production_state_path=seed_csv)
    pipeline.apply(_command("cmd-state-001", {
        "grain": "MODEL", "effective_month": "2025-09",
        "origin_country": "CN", "import_type": "CBU", "evidence": "launch",
    }))
    pipeline.apply(_command("cmd-state-002", {
        "grain": "MODEL", "effective_month": "2026-03",
        "origin_country": "TH", "import_type": "CKD", "evidence": "local assembly began",
    }))

    rows = sorted(_rows(seed_csv), key=lambda r: r["effective_month"])
    assert [r["effective_month"] for r in rows] == ["2025-09", "2026-03"]


def test_replay_of_the_same_command_id_is_idempotent(tmp_path: Path):
    data = _seed(tmp_path)
    seed_csv = tmp_path / "research" / "monthly_production_state.csv"
    pipeline = CanonicalWritePipeline(data, production_state_path=seed_csv)
    command = _command("cmd-state-001", {
        "grain": "MODEL", "effective_month": "2025-09",
        "origin_country": "CN", "import_type": "CBU", "evidence": "launch",
    })
    pipeline.apply(command)
    replay = pipeline.apply(command)
    assert replay.idempotent_replay is True
    assert len(_rows(seed_csv)) == 1


@pytest.mark.parametrize("mutation,match", [
    ({"grain": "TRIM"}, "grain"),
    ({"effective_month": "2025-9"}, "effective_month"),
    ({"effective_month": "2025-09", "origin_country": "", "import_type": ""}, "origin_country and/or import_type"),
    ({"evidence": ""}, "evidence"),
])
def test_bad_production_state_commands_are_rejected(tmp_path: Path, mutation: dict, match: str):
    data = _seed(tmp_path)
    seed_csv = tmp_path / "research" / "monthly_production_state.csv"
    pipeline = CanonicalWritePipeline(data, production_state_path=seed_csv)
    base = {
        "grain": "MODEL", "effective_month": "2025-09",
        "origin_country": "CN", "import_type": "CBU", "evidence": "launch",
    }
    base.update(mutation)
    with pytest.raises(CanonicalWriteError, match=match):
        pipeline.apply(_command("cmd-state-bad", base))
    assert not seed_csv.exists() or not _rows(seed_csv)


def test_unknown_model_is_rejected_without_guessing_a_match(tmp_path: Path):
    data = _seed(tmp_path)
    seed_csv = tmp_path / "research" / "monthly_production_state.csv"
    pipeline = CanonicalWritePipeline(data, production_state_path=seed_csv)
    with pytest.raises(CanonicalWriteError, match="unknown model"):
        pipeline.apply(_command("cmd-state-001", {
            "grain": "MODEL", "effective_month": "2025-09",
            "origin_country": "CN", "import_type": "CBU", "evidence": "launch",
        }, canonical_id="toyota.does_not_exist"))
