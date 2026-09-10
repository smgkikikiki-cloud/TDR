from __future__ import annotations

import json
from pathlib import Path

import pytest

from vehreg.catalog import Catalog
from vehreg.canonical_write import CanonicalWriteError, CanonicalWritePipeline
from vehreg.input_pipeline import CanonicalInputPipeline
from vehreg.pricing import PriceLedger, PriceType

YEAR = 2026
MODEL_ID = "jaecoo.jaecoo_5_ev"
GEN_ID = MODEL_ID + ".j5"
TRIM_ID = GEN_ID + ".trim.dynamic_bev"


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
            "generations": [{
                "code": "J5", "segment": "B", "seats": 5,
                "launched": "2025-08-19", "ended": None,
                "variants": [{
                    "id": "bev_cbu", "name": "58.9 kWh BEV CBU", "powertrain": "BEV",
                    "drivetrain": "FWD", "engine_cc": None, "battery_kwh": 58.9,
                    "price_thb": None, "price_min_thb": None, "price_max_thb": None,
                    "import_type": "CBU", "origin_country": "CN",
                    "price_note": "retail price lives on MarketTrim", "aliases": [],
                }],
                "trims": [{
                    "id": "dynamic_bev", "name": "Dynamic", "variant": "58.9 kWh BEV CBU",
                    "powertrain": "BEV", "drivetrain": "FWD", "battery_kwh": 58.9,
                    "seats": 5, "length_mm": 4380, "width_mm": 1860, "height_mm": 1650,
                    "wheelbase_mm": 2620, "tire_front": "235/55 R18", "tire_rear": "235/55 R18",
                    "wheel_front": "18 in", "wheel_rear": "18 in", "aliases": [],
                    "source_refs": {"oem": ["https://example.test/j5"]},
                }],
            }],
        }],
    })
    return data


def _command(command_id: str, operation: str, payload: dict,
             canonical_id: str | None = TRIM_ID, reason: str = "reviewed correction") -> dict:
    return {
        "command_id": command_id, "operation": operation, "year": YEAR,
        "actor": "price-reviewer", "reason": reason, "canonical_id": canonical_id,
        "payload": payload, "submitted_at": "2026-09-10T10:00:00+00:00",
    }


def _append_initial(pipeline: CanonicalWritePipeline, amount: int = 899000,
                    start: str = "2026-08-01") -> None:
    pipeline.apply(_command("price-initial", "APPEND_PRICE", {
        "trim_id": TRIM_ID, "amount_thb": amount, "price_type": "LIST_PRICE",
        "effective_from": start, "observed_at": start,
        "source": "OEM", "source_ref": "https://example.test/j5/price",
    }))


def _records(data: Path):
    catalog = Catalog.load(data, YEAR)
    return PriceLedger.load(data, year=YEAR, catalog=catalog).records_for(
        TRIM_ID, include_retracted=True)


def test_supersede_price_closes_old_row_and_replays_idempotently(tmp_path: Path):
    data = _seed(tmp_path)
    pipeline = CanonicalWritePipeline(data)
    _append_initial(pipeline)
    result = pipeline.apply(_command("price-supersede", "CORRECT_PRICE", {
        "price_type": "LIST_PRICE", "amount_thb": 859000,
        "mode": "supersede", "effective_from": "2026-09-01", "as_of": "2026-09-01",
        "source": "OEM", "source_ref": "https://example.test/j5/new-price",
    }))

    rows = _records(data)
    assert result.topic == "price"
    assert result.entity_id == TRIM_ID
    assert len(rows) == 2
    old = next(row for row in rows if row.amount_thb == 899000)
    new = next(row for row in rows if row.amount_thb == 859000)
    assert old.effective_to == "2026-08-31"
    assert new.effective_from == "2026-09-01"
    ledger = PriceLedger.load(data, year=YEAR, catalog=Catalog.load(data, YEAR))
    assert ledger.current_list_amount(TRIM_ID, as_of="2026-09-10") == 859000

    replay = pipeline.apply(_command("price-supersede", "CORRECT_PRICE", {
        "price_type": "LIST_PRICE", "amount_thb": 859000,
        "mode": "supersede", "effective_from": "2026-09-01", "as_of": "2026-09-01",
        "source": "OEM", "source_ref": "https://example.test/j5/new-price",
    }))
    assert replay.idempotent_replay
    state = data / str(YEAR) / "canonical_state" / "revisions.jsonl"
    revisions = [json.loads(line) for line in state.read_text(encoding="utf-8").splitlines()]
    assert [row["operation"] for row in revisions] == ["APPEND_PRICE", "CORRECT_PRICE"]


def test_retract_price_marks_wrong_row_and_keeps_replacement(tmp_path: Path):
    data = _seed(tmp_path)
    pipeline = CanonicalWritePipeline(data)
    _append_initial(pipeline, 899000, "2026-09-01")
    pipeline.apply(_command("price-retract", "CORRECT_PRICE", {
        "price_type": "LIST_PRICE", "amount_thb": 879000,
        "mode": "retract", "effective_from": "2026-09-01", "as_of": "2026-09-10",
        "source": "OEM", "source_ref": "https://example.test/j5/correction",
    }, reason="899,000 was a transcription error"))
    rows = _records(data)
    wrong = next(row for row in rows if row.amount_thb == 899000)
    replacement = next(row for row in rows if row.amount_thb == 879000)
    assert wrong.retracted_at == "2026-09-10"
    assert wrong.retraction_reason == "899,000 was a transcription error"
    assert replacement.reviewed_by == "price-reviewer"


def test_close_price_ends_live_observation_without_replacement(tmp_path: Path):
    data = _seed(tmp_path)
    pipeline = CanonicalWritePipeline(data)
    _append_initial(pipeline, 899000, "2026-09-01")
    result = pipeline.apply(_command("price-close", "CLOSE_PRICE", {
        "price_type": "LIST_PRICE", "ends": "2026-09-30", "as_of": "2026-09-10",
    }, reason="trim withdrawn from price list"))
    rows = _records(data)
    assert result.topic == "price"
    assert len(rows) == 1
    assert rows[0].effective_to == "2026-09-30"
    assert rows[0].reviewed_by == "price-reviewer"


def test_campaign_upsert_is_revisioned_and_rejects_noop(tmp_path: Path):
    data = _seed(tmp_path)
    pipeline = CanonicalWritePipeline(data)
    campaign = {
        "id": "campaign.jaecoo.september_2026", "brand_id": "jaecoo",
        "name": "September offer", "starts": "2026-09-01", "ends": "2026-09-30",
        "source": "official_oem", "source_ref": "https://example.test/j5/campaign",
        "options": [{
            "id": "cash", "label": "Cash offer", "starts": "2026-09-01",
            "ends": "2026-09-30", "status": "ACTIVE",
            "conditions": {"finance_required": False, "text": "cash customer"},
        }],
    }
    result = pipeline.apply(_command(
        "campaign-write", "UPSERT_CAMPAIGN", campaign,
        canonical_id="campaign.jaecoo.september_2026", reason="publish official campaign",
    ))
    assert result.topic == "campaign"
    path = data / str(YEAR) / "market" / "campaigns" / "jaecoo.json"
    saved = json.loads(path.read_text(encoding="utf-8"))["campaigns"]
    assert saved == [campaign]

    with pytest.raises(CanonicalWriteError, match="already matches"):
        pipeline.apply(_command(
            "campaign-noop", "UPSERT_CAMPAIGN", campaign,
            canonical_id="campaign.jaecoo.september_2026", reason="duplicate retry with new command id",
        ))


def test_input_batch_accepts_price_maintenance_and_stages_atomically(tmp_path: Path):
    data = _seed(tmp_path)
    writer = CanonicalWritePipeline(data)
    _append_initial(writer, 899000, "2026-08-01")
    batch = {
        "schema_version": 1, "batch_id": "price-maintenance-batch", "year": YEAR,
        "source": {"kind": "ADMIN", "ref": "admin-price-bench"},
        "actor": "price-reviewer", "reason": "official price changed",
        "submitted_at": "2026-09-10T10:00:00+00:00",
        "commands": [{
            "command_id": "batch-price-correct", "operation": "CORRECT_PRICE",
            "canonical_id": TRIM_ID,
            "payload": {
                "price_type": "LIST_PRICE", "amount_thb": 859000,
                "mode": "supersede", "effective_from": "2026-09-01", "as_of": "2026-09-01",
            },
        }],
    }
    result = CanonicalInputPipeline(data).apply(batch)
    assert result.status == "APPLIED"
    assert any(path.endswith("observations.json") for path in result.changed_files)
    ledger = PriceLedger.load(data, year=YEAR, catalog=Catalog.load(data, YEAR))
    assert ledger.current_list_amount(TRIM_ID, as_of="2026-09-10") == 859000
