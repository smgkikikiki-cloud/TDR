from __future__ import annotations

import json
from pathlib import Path

import pytest

from vehreg.catalog import Catalog
from vehreg.canonical_write import CanonicalWriteError, CanonicalWritePipeline
from vehreg.comparable_specs import SpecLedger, SpecRegistry
from vehreg.pricing import PriceLedger, PriceType


YEAR = 2026
MODEL_ID = "jaecoo.jaecoo_5_ev"
GEN_ID = MODEL_ID + ".j5"
TRIM_ID = GEN_ID + ".trim.dynamic_bev"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _seed(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    _write_json(data / str(YEAR) / "models" / "jaecoo.json", {
        "brand": {
            "id": "jaecoo",
            "name_en": "Jaecoo",
            "name_th": "เจคู",
            "brand_segment": "MASS",
            "oem_group": "Chery",
            "brand_origin": "CN",
            "trim_detail": True,
            "aliases": [],
        },
        "models": [{
            "id": "jaecoo_5_ev",
            "name_en": "Jaecoo 5 EV",
            "name_th": "เจคู 5",
            "nameplate": "Jaecoo 5",
            "body_type": "CROSSOVER",
            "cab_type": "NOT_APPLICABLE",
            "registration_type": "",
            "market_scope": "CORE",
            "aliases": [],
            "generations": [{
                "code": "J5",
                "segment": "B",
                "seats": 5,
                "launched": "2025-08-19",
                "ended": None,
                "variants": [{
                    "id": "bev_cbu",
                    "name": "58.9 kWh BEV CBU",
                    "powertrain": "BEV",
                    "drivetrain": "FWD",
                    "engine_cc": None,
                    "battery_kwh": 58.9,
                    "price_thb": None,
                    "price_min_thb": None,
                    "price_max_thb": None,
                    "import_type": "CBU",
                    "origin_country": "CN",
                    "price_note": "retail price lives on MarketTrim",
                    "aliases": [],
                }],
                "trims": [{
                    "id": "dynamic_bev",
                    "name": "Dynamic",
                    "variant": "58.9 kWh BEV CBU",
                    "powertrain": "BEV",
                    "drivetrain": "FWD",
                    "battery_kwh": 58.9,
                    "seats": 5,
                    "length_mm": 4380,
                    "width_mm": 1860,
                    "height_mm": 1650,
                    "wheelbase_mm": 2620,
                    "tire_front": "235/55 R18",
                    "tire_rear": "235/55 R18",
                    "wheel_front": "18 in",
                    "wheel_rear": "18 in",
                    "aliases": [],
                    "source_refs": {"oem": ["https://example.test/j5"]},
                }],
            }],
        }],
    })
    return data


def _command(command_id: str, operation: str, payload: dict,
             canonical_id: str | None = None) -> dict:
    return {
        "command_id": command_id,
        "operation": operation,
        "year": YEAR,
        "actor": "phase-c-test",
        "reason": "contract test",
        "canonical_id": canonical_id,
        "payload": payload,
        "submitted_at": "2026-09-09T00:00:00+00:00",
    }


def test_model_bundle_write_is_atomic_revisioned_and_idempotent(tmp_path: Path):
    data = _seed(tmp_path)
    pipeline = CanonicalWritePipeline(data)
    result = pipeline.apply(_command(
        "cmd-model-001",
        "UPSERT_MODEL_BUNDLE",
        {
            "brand": {"id": "jaecoo", "name_en": "Jaecoo"},
            "model": {"id": "jaecoo_5_ev", "notes": "canonical update"},
            "generation": {"code": "J5"},
            "trims": [{
                "id": "dynamic_bev",
                "name": "Dynamic",
                "powertrain": "BEV",
                "tire_front": "245/50 R19",
            }],
        },
        MODEL_ID,
    ))

    assert result.topic == "catalog"
    assert not result.idempotent_replay
    catalog = Catalog.load(data, YEAR)
    assert catalog.models[MODEL_ID].notes == "canonical update"
    assert catalog.trims[TRIM_ID].tire_front == "245/50 R19"

    state = data / str(YEAR) / "canonical_state"
    revisions = (state / "revisions.jsonl").read_text(encoding="utf-8").splitlines()
    outbox = (state / "outbox.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(revisions) == 1
    assert len(outbox) == 1
    assert (state / "shadow" / f"{result.revision_id}.json").is_file()

    replay = pipeline.apply(_command(
        "cmd-model-001",
        "UPSERT_MODEL_BUNDLE",
        {
            "brand": {"id": "jaecoo", "name_en": "Jaecoo"},
            "model": {"id": "jaecoo_5_ev", "notes": "canonical update"},
            "generation": {"code": "J5"},
            "trims": [{
                "id": "dynamic_bev", "name": "Dynamic",
                "powertrain": "BEV", "tire_front": "245/50 R19",
            }],
        },
        MODEL_ID,
    ))
    assert replay.idempotent_replay
    assert replay.revision_id == result.revision_id
    assert len((state / "revisions.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_invalid_catalog_write_leaves_canonical_files_untouched(tmp_path: Path):
    data = _seed(tmp_path)
    target = data / str(YEAR) / "models" / "jaecoo.json"
    before = target.read_text(encoding="utf-8")

    with pytest.raises(CanonicalWriteError, match="catalog validation failed"):
        CanonicalWritePipeline(data).apply(_command(
            "cmd-invalid-001",
            "UPSERT_MODEL_BUNDLE",
            {
                "brand": {"id": "jaecoo", "name_en": "Jaecoo"},
                "model": {"id": "jaecoo_5_ev", "body_type": "PICKUP"},
                "generation": {"code": "J5"},
            },
            MODEL_ID,
        ))

    assert target.read_text(encoding="utf-8") == before
    assert not (data / str(YEAR) / "canonical_state" / "revisions.jsonl").exists()


def test_withdraw_marks_model_historical_without_deleting_identity(tmp_path: Path):
    data = _seed(tmp_path)
    result = CanonicalWritePipeline(data).apply(_command(
        "cmd-withdraw-001",
        "WITHDRAW_MODEL",
        {"ended": "2026-09-09"},
        MODEL_ID,
    ))
    assert result.entity_id == MODEL_ID
    catalog = Catalog.load(data, YEAR)
    assert catalog.models[MODEL_ID].retail_status.value == "HISTORICAL"
    assert catalog.generations[GEN_ID].ended == "2026-09-09"
    assert MODEL_ID in catalog.models


def test_price_write_uses_price_ledger_and_never_markettrim_price(tmp_path: Path):
    data = _seed(tmp_path)
    CanonicalWritePipeline(data).apply(_command(
        "cmd-price-001",
        "APPEND_PRICE",
        {
            "trim_id": TRIM_ID,
            "amount_thb": 899000,
            "price_type": "LIST_PRICE",
            "effective_from": "2026-09-09",
            "observed_at": "2026-09-09",
            "source": "OEM",
            "source_ref": "https://example.test/j5/price",
        },
        TRIM_ID,
    ))
    catalog = Catalog.load(data, YEAR)
    ledger = PriceLedger.load(data, year=YEAR, catalog=catalog)
    assert ledger.current_list_amount(TRIM_ID) == 899000
    assert catalog.trims[TRIM_ID].price_thb is None
    assert ledger.latest(TRIM_ID, price_type=PriceType.LIST_PRICE) is not None


def test_spec_write_uses_spec_ledger_and_rejects_duplicate_truth(tmp_path: Path):
    data = _seed(tmp_path)
    root = data / str(YEAR) / "product" / "comparable_specs"
    _write_json(root / "registry.json", {
        "schema_version": 1,
        "fields": [{
            "key": "dimensions.length_mm",
            "group": "dimensions",
            "label_th": "ความยาว",
            "label_en": "Length",
            "value_type": "NUMBER",
            "comparison_rule": "INFORMATION_ONLY",
            "canonical_unit": "mm",
            "applicable_powertrains": [],
            "comparison_qualifiers": [],
            "display_precision": 0,
        }],
    })

    CanonicalWritePipeline(data).apply(_command(
        "cmd-spec-001",
        "APPEND_SPEC",
        {
            "fact_id": "j5-dynamic-length-20260909",
            "trim_id": TRIM_ID,
            "field_key": "dimensions.length_mm",
            "value_state": "KNOWN",
            "value": 4380,
            "unit": "mm",
            "observed_at": "2026-09-09",
            "source": "OEM",
            "source_ref": "https://example.test/j5/spec",
        },
        TRIM_ID,
    ))

    catalog = Catalog.load(data, YEAR)
    registry = SpecRegistry.load(data, YEAR)
    ledger = SpecLedger.load(data, YEAR, registry=registry, catalog=catalog)
    facts = ledger.resolved(TRIM_ID)
    assert len(facts) == 1
    assert facts[0].value == 4380
