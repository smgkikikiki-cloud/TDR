from __future__ import annotations

import json
from pathlib import Path

import pytest

from vehreg.input_pipeline import CanonicalInputError, CanonicalInputPipeline
from vehreg.pricing import PriceLedger
from vehreg.catalog import Catalog


YEAR = 2026
MODEL_ID = "jaecoo.jaecoo_5_ev"
TRIM_ID = MODEL_ID + ".j5.trim.dynamic_bev"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    _write(data / "2026/models/jaecoo.json", {
        "brand": {
            "id": "jaecoo", "name_en": "Jaecoo", "name_th": "เจคู",
            "brand_segment": "MASS", "brand_origin": "CN", "aliases": [],
        },
        "models": [{
            "id": "jaecoo_5_ev", "name_en": "Jaecoo 5 EV", "nameplate": "Jaecoo 5",
            "body_type": "CROSSOVER", "cab_type": "NOT_APPLICABLE",
            "registration_type": "", "market_scope": "CORE", "aliases": [],
            "generations": [{
                "code": "J5", "segment": "B", "seats": 5,
                "variants": [{
                    "name": "58.9 kWh BEV", "powertrain": "BEV", "drivetrain": "FWD",
                    "battery_kwh": 58.9, "import_type": "CBU", "origin_country": "CN",
                    "aliases": [],
                }],
                "trims": [{
                    "id": "dynamic_bev", "name": "Dynamic", "variant": "58.9 kWh BEV",
                    "powertrain": "BEV", "drivetrain": "FWD", "aliases": [],
                }],
            }],
        }],
    })
    return data


def _batch(amount: int = 899_000) -> dict:
    return {
        "schema_version": 1,
        "batch_id": "admin-j5-price-20260909",
        "year": YEAR,
        "source": {"kind": "OEM", "ref": "https://example.test/j5"},
        "actor": "owner",
        "reason": "official launch price",
        "submitted_at": "2026-09-09T00:00:00+00:00",
        "commands": [{
            "operation": "APPEND_PRICE",
            "canonical_id": TRIM_ID,
            "payload": {
                "trim_id": TRIM_ID, "amount_thb": amount, "price_type": "LIST_PRICE",
                "effective_from": "2026-09-09", "observed_at": "2026-09-09",
                "source": "OEM", "source_ref": "https://example.test/j5",
            },
        }],
    }


def test_one_batch_updates_ledger_and_writes_one_commit_marker(tmp_path: Path):
    data = _seed(tmp_path)
    result = CanonicalInputPipeline(data).apply(_batch())
    assert result.status == "APPLIED"
    assert len(result.results) == 1
    assert (data / "2026/canonical_state/input_batches/admin-j5-price-20260909.json").is_file()
    ledger = PriceLedger.load(data, year=YEAR, catalog=Catalog.load(data, YEAR))
    assert ledger.current_list_amount(TRIM_ID) == 899_000


def test_exact_batch_replay_is_idempotent_but_changed_content_is_rejected(tmp_path: Path):
    data = _seed(tmp_path)
    pipeline = CanonicalInputPipeline(data)
    first = pipeline.apply(_batch())
    replay = pipeline.apply(_batch())
    assert replay.idempotent_replay
    assert replay.batch_hash == first.batch_hash
    with pytest.raises(CanonicalInputError, match="already used with different content"):
        pipeline.apply(_batch(909_000))


def test_registration_input_cannot_create_vehicle_market_facts(tmp_path: Path):
    data = _seed(tmp_path)
    payload = _batch()
    payload["source"] = {"kind": "DLT", "ref": "dlt"}
    with pytest.raises(CanonicalInputError, match="separate analytics pipeline"):
        CanonicalInputPipeline(data).apply(payload)


def test_batch_requires_stable_submitted_timestamp(tmp_path: Path):
    data = _seed(tmp_path)
    payload = _batch()
    payload.pop("submitted_at")
    with pytest.raises(CanonicalInputError, match="deterministic retries"):
        CanonicalInputPipeline(data).apply(payload)


def test_invalid_later_command_leaves_real_data_tree_unchanged(tmp_path: Path):
    data = _seed(tmp_path)
    payload = _batch()
    payload["commands"].append({
        "operation": "APPEND_PRICE",
        "canonical_id": "missing.model.gen.trim.none",
        "payload": {
            "amount_thb": 1, "price_type": "LIST_PRICE",
            "effective_from": "2026-09-09", "observed_at": "2026-09-09",
            "source": "OEM", "source_ref": "https://example.test/missing",
        },
    })
    with pytest.raises(CanonicalInputError, match="unknown MarketTrim"):
        CanonicalInputPipeline(data).apply(payload)
    assert not (data / "2026/market/prices").exists()
    assert not (data / "2026/canonical_state").exists()


def test_retry_repairs_audit_files_after_interrupted_copy(tmp_path: Path):
    data = _seed(tmp_path)
    pipeline = CanonicalInputPipeline(data)
    first = pipeline.apply(_batch())
    marker = data / "2026/canonical_state/input_batches/admin-j5-price-20260909.json"
    outbox = data / "2026/canonical_state/outbox.jsonl"
    shadow = data / "2026/canonical_state/shadow" / f"{first.results[0]['revision_id']}.json"
    marker.unlink()
    outbox.unlink()
    shadow.unlink()

    recovered = pipeline.apply(_batch())

    assert not recovered.idempotent_replay
    assert marker.is_file()
    assert outbox.is_file()
    assert shadow.is_file()
    assert len(outbox.read_text(encoding="utf-8").splitlines()) == 1
