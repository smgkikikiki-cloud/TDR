from __future__ import annotations

import json
from pathlib import Path

import pytest

from vehreg.canonical_write import CanonicalWritePipeline
from vehreg.input_pipeline import CanonicalInputError, CanonicalInputPipeline
from vehreg.price_coverage_review import (
    PriceCoverageReviewError,
    load_coverage_decisions,
    upsert_coverage_disposition,
)

YEAR = 2026
MODEL_ID = "jaecoo.jaecoo_5_ev"
GEN_ID = MODEL_ID + ".j5"
TRIM_ID = GEN_ID + ".trim.ultra_bev"


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
                    "id": "ultra_bev", "name": "Ultra", "variant": "58.9 kWh BEV CBU",
                    "powertrain": "BEV", "drivetrain": "FWD", "battery_kwh": 58.9,
                    "seats": 5, "aliases": [],
                    "source_refs": {"oem": ["https://example.test/j5"]},
                }],
            }],
        }],
    })
    _write_json(data / str(YEAR) / "market" / "pricefeed" / "review" / "coverage.json", {
        "schema_version": 1, "decisions": [],
    })
    return data


def _defer_batch(actor: str = "price-reviewer", batch_id: str = "coverage-defer") -> dict:
    return {
        "schema_version": 1,
        "batch_id": batch_id,
        "year": YEAR,
        "source": {"kind": "ADMIN", "ref": "https://example.test/j5/ultra"},
        "actor": actor,
        "reason": "OEM still labels Ultra as estimated",
        "submitted_at": "2026-09-11T03:30:00+00:00",
        "commands": [{
            "operation": "UPSERT_PRICE_COVERAGE_REVIEW",
            "payload": {
                "trim_id": TRIM_ID,
                "action": "defer",
                "reason_code": "AWAITING_FINAL_LIST_PRICE",
                "source_ref": "https://example.test/j5/ultra",
                "notes": "Final MSRP not announced",
            },
        }],
    }


def test_defer_and_reopen_are_review_metadata_only(tmp_path: Path):
    data = _seed(tmp_path)
    result = CanonicalInputPipeline(data).apply(_defer_batch())
    assert result.status == "APPLIED"
    assert any(path.endswith("market/pricefeed/review/coverage.json") for path in result.changed_files)
    assert not any(path.endswith("market/prices/observations.json") for path in result.changed_files)
    assert not any(path.endswith("canonical_state/outbox.jsonl") for path in result.changed_files)

    decisions = load_coverage_decisions(data_dir=data, year=YEAR)
    assert decisions == [{
        "trim_id": TRIM_ID,
        "action": "defer",
        "reason_code": "AWAITING_FINAL_LIST_PRICE",
        "reviewer": "price-reviewer",
        "reviewed_at": "2026-09-11",
        "source_ref": "https://example.test/j5/ultra",
        "notes": "Final MSRP not announced",
    }]

    reopen = _defer_batch(batch_id="coverage-reopen")
    reopen["commands"][0]["payload"] = {
        "trim_id": TRIM_ID,
        "action": "reopen",
        "notes": "OEM published final MSRP",
    }
    CanonicalInputPipeline(data).apply(reopen)
    assert load_coverage_decisions(data_dir=data, year=YEAR) == []


def test_defer_rejects_non_human_actor(tmp_path: Path):
    data = _seed(tmp_path)
    with pytest.raises(CanonicalInputError, match="explicit HUMAN actor"):
        CanonicalInputPipeline(data).apply(_defer_batch(actor="agent-proposed"))


def test_defer_requires_admin_source_kind(tmp_path: Path):
    data = _seed(tmp_path)
    batch = _defer_batch()
    batch["source"]["kind"] = "OEM"
    with pytest.raises(CanonicalInputError, match="requires source.kind ADMIN"):
        CanonicalInputPipeline(data).apply(batch)


def test_defer_refuses_trim_that_already_has_current_list_price(tmp_path: Path):
    data = _seed(tmp_path)
    CanonicalWritePipeline(data).apply({
        "command_id": "price-ultra-final",
        "operation": "APPEND_PRICE",
        "year": YEAR,
        "actor": "price-reviewer",
        "reason": "official final MSRP",
        "canonical_id": TRIM_ID,
        "payload": {
            "amount_thb": 809000,
            "price_type": "LIST_PRICE",
            "effective_from": "2026-09-11",
            "observed_at": "2026-09-11",
            "source": "official_oem",
            "source_ref": "https://example.test/j5/ultra-final",
        },
        "submitted_at": "2026-09-11T03:00:00+00:00",
    })
    with pytest.raises(CanonicalInputError, match="already has current LIST_PRICE"):
        CanonicalInputPipeline(data).apply(_defer_batch())


def test_direct_review_writer_requires_evidence_and_known_reason(tmp_path: Path):
    data = _seed(tmp_path)
    with pytest.raises(PriceCoverageReviewError, match="source_ref"):
        upsert_coverage_disposition(
            data_dir=data, year=YEAR, trim_id=TRIM_ID, action="defer",
            reason_code="AWAITING_FINAL_LIST_PRICE", reviewer="price-reviewer",
            reviewed_at="2026-09-11", source_ref="", write=True,
        )
    with pytest.raises(PriceCoverageReviewError, match="reason_code"):
        upsert_coverage_disposition(
            data_dir=data, year=YEAR, trim_id=TRIM_ID, action="defer",
            reason_code="JUST_IGNORE_IT", reviewer="price-reviewer",
            reviewed_at="2026-09-11", source_ref="https://example.test/evidence", write=True,
        )
