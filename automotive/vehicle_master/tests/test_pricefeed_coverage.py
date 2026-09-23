"""Price Feed's coverage/scout entry mode: a catalog gap turns into a
grouped source-target fetch, and the fetch's evidence flows through the
exact same resolver/writer/PriceLedger path the live WordPress harvester
uses -- never tools.price_promote_batch's separate P6 write path.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from tools import pricefeed_coverage
from vehreg.catalog import Catalog
from vehreg.pricefeed import content_id
from vehreg.pricing import PriceLedger

YEAR = 2026
MODEL_ID = "jaecoo.j5"
TRIM_ID = MODEL_ID + ".g1.trim.dynamic"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    _write(root / f"{YEAR}/models/jaecoo.json", {
        "brand": {"id": "jaecoo", "name_en": "Jaecoo", "name_th": "เจคู",
                  "brand_segment": "MASS", "brand_origin": "CN", "aliases": []},
        "models": [{
            "id": "j5", "name_en": "Jaecoo 5", "nameplate": "Jaecoo 5",
            "body_type": "CROSSOVER", "cab_type": "NOT_APPLICABLE",
            "registration_type": "", "market_scope": "CORE", "aliases": [],
            "generations": [{
                "code": "G1", "segment": "B", "seats": 5,
                "variants": [{
                    "name": "1.6T", "powertrain": "ICE", "drivetrain": "FWD",
                    "engine_cc": 1600, "import_type": "CBU", "origin_country": "CN",
                    "aliases": [],
                }],
                "trims": [{"id": "dynamic", "name": "Dynamic", "variant": "1.6T",
                          "powertrain": "ICE", "drivetrain": "FWD", "aliases": []}],
            }],
        }],
    })
    _write(root / f"{YEAR}/market/pricefeed/sources.json", {"sources": [{
        "id": "jaecoo-official", "name": "Jaecoo Thailand", "tier": "A",
        "base_url": "https://jaecoo.example", "adapter": "official_oem",
    }]})
    _write(root / f"{YEAR}/market/pricefeed/targets.json", {
        "schema_version": 1, "source_profiles": [
            {"source_id": "jaecoo-official", "kind": "OEM"},
        ],
        "targets": [{
            "id": "jaecoo-official:model-page", "source_id": "jaecoo-official",
            "url": "https://jaecoo.example/j5", "role": "CURRENT_MODEL_PAGE",
            "model_hint": MODEL_ID, "enabled": True,
        }],
    })
    return root


def _claim_row(*, target_id: str, source_id: str, amount: int) -> dict:
    document_id = content_id(f"{target_id}|{amount}")
    return {
        "target_id": target_id, "target_role": "CURRENT_MODEL_PAGE",
        "source_id": source_id, "model_hint": MODEL_ID, "not_modified": False,
        "document": {
            "document_id": document_id, "source_id": source_id,
            "url": "https://jaecoo.example/j5", "content_hash": document_id,
            "published_at": "2026-09-23T00:00:00+00:00",
            "first_seen_at": "2026-09-23T00:00:00+00:00",
            "fetched_at": "2026-09-23T00:00:00+00:00",
            "title": "Jaecoo 5 price page", "snapshot_ref": "", "body_sketch": [],
        },
        "claims": [{
            "claim_id": f"claim-{amount}", "document_id": document_id,
            "source_id": source_id, "brand_raw": "Jaecoo", "model_raw": "Jaecoo 5",
            "trim_raw": "Dynamic", "amount_thb": amount, "price_type": "LIST_PRICE",
            "evidence_text": "Dynamic 899,000", "extraction_method": "rule",
            "effective_from": "2026-09-23", "effective_to": None,
            "reference_price_thb": None, "campaign_hint": "", "option_hint": "",
            "match": {"state": "EXACT", "trim_id": TRIM_ID},
        }],
        "extraction_warnings": [], "discovered_targets": [],
    }


def test_to_harvest_batch_drops_the_match_diagnostic_and_keeps_claim_shape():
    fetch_payload = {
        "source_batch_id": "pbatch:abc123",
        "results": [_claim_row(target_id="t1", source_id="s1", amount=899_000)],
    }
    batch = pricefeed_coverage.to_harvest_batch(fetch_payload, since="2026-09-23")
    assert len(batch["documents"]) == 1
    assert len(batch["claims"]) == 1
    claim = batch["claims"][0]
    assert "match" not in claim
    assert claim["amount_thb"] == 899_000
    assert claim["trim_raw"] == "Dynamic"


def test_select_targets_only_returns_targets_for_models_with_a_gap(data: Path):
    catalog = Catalog.load(data, YEAR)
    ledger = PriceLedger.load(data, year=YEAR, catalog=catalog)
    target_ids = pricefeed_coverage.select_targets(
        data_dir=data, year=YEAR, catalog=catalog, ledger=ledger,
        as_of=date(2026, 9, 23), stale_after_days=180, limit_models=10)
    assert target_ids == ["jaecoo-official:model-page"]


def test_select_targets_is_empty_once_the_trim_has_a_current_price(data: Path):
    _write(data / f"{YEAR}/market/prices/seed.json", {"prices": [{
        "trim_id": TRIM_ID, "amount_thb": 899_000, "price_type": "LIST_PRICE",
        "effective_from": "2026-09-01", "observed_at": "2026-09-01", "source": "admin",
    }]})
    catalog = Catalog.load(data, YEAR)
    ledger = PriceLedger.load(data, year=YEAR, catalog=catalog)
    target_ids = pricefeed_coverage.select_targets(
        data_dir=data, year=YEAR, catalog=catalog, ledger=ledger,
        as_of=date(2026, 9, 23), stale_after_days=180, limit_models=10)
    assert target_ids == []


def test_a_coverage_work_item_flows_end_to_end_into_the_price_ledger(data: Path):
    fake_payload = {
        "source_batch_id": "pbatch:def456",
        "results": [_claim_row(target_id="jaecoo-official:model-page",
                               source_id="jaecoo-official", amount=899_000)],
    }

    def fake_fetch_main(argv):
        out = Path(argv[argv.index("--out") + 1])
        out.write_text(json.dumps(fake_payload), encoding="utf-8")
        return 0

    with patch("tools.pricefeed_coverage.fetch_targets_main", side_effect=fake_fetch_main):
        batch = pricefeed_coverage.run(
            data_dir=data, year=YEAR, as_of=date(2026, 9, 23),
            stale_after_days=180, limit_models=10)

    assert batch["targets_fetched"] == 1
    assert len(batch["claims"]) == 1

    batch_path = data / "coverage-batch.json"
    _write(batch_path, batch)

    from tools import pricefeed_write
    summary = pricefeed_write.run(batch_path, data_dir=data, year=YEAR,
                                  observed_at="2026-09-23", apply=True)

    assert summary["canonical_offers"] == 1
    assert summary["planned"]["WRITTEN"] == 1
    catalog = Catalog.load(data, YEAR)
    ledger = PriceLedger.load(data, year=YEAR, catalog=catalog)
    served = ledger.current_list_amount(TRIM_ID, as_of=date(2026, 9, 23))
    assert served == 899_000


def test_no_gaps_means_no_fetch_at_all(data: Path):
    _write(data / f"{YEAR}/market/prices/seed.json", {"prices": [{
        "trim_id": TRIM_ID, "amount_thb": 899_000, "price_type": "LIST_PRICE",
        "effective_from": "2026-09-01", "observed_at": "2026-09-01", "source": "admin",
    }]})
    with patch("tools.pricefeed_coverage.fetch_targets_main") as mock_fetch:
        batch = pricefeed_coverage.run(
            data_dir=data, year=YEAR, as_of=date(2026, 9, 23),
            stale_after_days=180, limit_models=10)
    mock_fetch.assert_not_called()
    assert batch["targets_fetched"] == 0
    assert batch["documents"] == []
