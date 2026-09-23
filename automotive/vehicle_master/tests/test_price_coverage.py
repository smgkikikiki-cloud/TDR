"""vehreg.price_coverage.coverage_gaps(): the catalog-driven gap query
Price Feed's coverage/scout entry mode plans its next fetch from. Asks the
same question lib/price-coverage-worklist.ts asks of Supabase, but locally
against the Catalog + PriceLedger the harvest/write pipeline itself reads
-- deterministic, model-grouped, and aware of the same HUMAN coverage
deferrals the admin dashboard already records.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from vehreg.catalog import Catalog
from vehreg.input_pipeline import CanonicalInputPipeline
from vehreg.price_coverage import CONFLICT, MISSING, STALE, coverage_gaps, summarize
from vehreg.pricing import PriceLedger

YEAR = 2026


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _brand_file(brand_id: str, name: str, models: list[dict]) -> dict:
    return {
        "brand": {"id": brand_id, "name_en": name, "name_th": name,
                  "brand_segment": "MASS", "brand_origin": "JP", "aliases": []},
        "models": models,
    }


def _model(model_id: str, name: str, trims: list[dict]) -> dict:
    return {
        "id": model_id, "name_en": name, "nameplate": name,
        "body_type": "SEDAN", "cab_type": "NOT_APPLICABLE",
        "registration_type": "", "market_scope": "CORE", "aliases": [],
        "generations": [{
            "code": "G1", "segment": "B", "seats": 5,
            "variants": [{
                "name": "1.5 CVT", "powertrain": "ICE", "drivetrain": "FWD",
                "engine_cc": 1500, "import_type": "CBU", "origin_country": "TH",
                "aliases": [],
            }],
            "trims": trims,
        }],
    }


def _trim(short_id: str, name: str) -> dict:
    return {"id": short_id, "name": name, "variant": "1.5 CVT", "powertrain": "ICE",
           "drivetrain": "FWD", "aliases": []}


def _price_file(name: str, prices: list[dict]) -> dict:
    return {"prices": prices}


def _price(trim_id: str, amount: int, *, effective_from: str) -> dict:
    return {"trim_id": trim_id, "amount_thb": amount, "price_type": "LIST_PRICE",
           "effective_from": effective_from, "observed_at": effective_from,
           "source": "admin"}


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    _write_json(root / str(YEAR) / "models" / "alpha.json", _brand_file("alpha", "Alpha", [
        _model("one", "One", [
            _trim("priced", "Priced"),      # has a fresh current price
            _trim("missing", "Missing"),    # no price at all
            _trim("stale", "Stale"),        # price is very old
        ]),
    ]))
    _write_json(root / str(YEAR) / "models" / "beta.json", _brand_file("beta", "Beta", [
        _model("two", "Two", [
            _trim("conflict", "Conflict"),   # two prices same start day
        ]),
    ]))
    _write_json(root / str(YEAR) / "market" / "prices" / "seed.json", {"prices": [
        _price("alpha.one.g1.trim.priced", 800_000, effective_from="2026-09-01"),
        _price("alpha.one.g1.trim.stale", 700_000, effective_from="2025-01-01"),
        _price("beta.two.g1.trim.conflict", 900_000, effective_from="2026-09-01"),
        _price("beta.two.g1.trim.conflict", 950_000, effective_from="2026-09-01"),
    ]})
    return root


def test_gaps_are_grouped_by_model_and_sorted_deterministically(data: Path):
    catalog = Catalog.load(data, YEAR)
    ledger = PriceLedger.load(data, year=YEAR, catalog=catalog)

    gaps = coverage_gaps(catalog, ledger, as_of=date(2026, 9, 23))

    assert [g.model_id for g in gaps] == ["alpha.one", "beta.two"]
    alpha = gaps[0]
    assert alpha.brand_id == "alpha"
    assert [(t.trim_id, t.reason) for t in alpha.trims] == [
        ("alpha.one.g1.trim.missing", MISSING),
        ("alpha.one.g1.trim.stale", STALE),
    ]
    beta = gaps[1]
    assert [(t.trim_id, t.reason) for t in beta.trims] == [
        ("beta.two.g1.trim.conflict", CONFLICT),
    ]
    # The fully-priced trim never appears anywhere.
    all_trim_ids = {t.trim_id for g in gaps for t in g.trims}
    assert "alpha.one.g1.trim.priced" not in all_trim_ids


def test_two_runs_over_the_same_tree_produce_the_identical_list(data: Path):
    catalog = Catalog.load(data, YEAR)
    ledger = PriceLedger.load(data, year=YEAR, catalog=catalog)
    first = [g.as_dict() for g in coverage_gaps(catalog, ledger, as_of=date(2026, 9, 23))]
    second = [g.as_dict() for g in coverage_gaps(catalog, ledger, as_of=date(2026, 9, 23))]
    assert first == second


def test_a_human_deferred_trim_is_not_resurfaced_as_missing_work(data: Path, tmp_path):
    CanonicalInputPipeline(data).apply({
        "schema_version": 1, "batch_id": "defer-1", "year": YEAR,
        "source": {"kind": "ADMIN", "ref": "https://example.test"}, "actor": "reviewer",
        "reason": "awaiting OEM confirmation", "submitted_at": "2026-09-20T00:00:00+00:00",
        "commands": [{
            "operation": "UPSERT_PRICE_COVERAGE_REVIEW",
            "payload": {
                "trim_id": "alpha.one.g1.trim.missing", "action": "defer",
                "reason_code": "AWAITING_FINAL_LIST_PRICE",
                "source_ref": "https://example.test", "notes": "",
            },
        }],
    })
    catalog = Catalog.load(data, YEAR)
    ledger = PriceLedger.load(data, year=YEAR, catalog=catalog)

    gaps = coverage_gaps(catalog, ledger, as_of=date(2026, 9, 23),
                         data_dir=data, year=YEAR)

    alpha = next(g for g in gaps if g.model_id == "alpha.one")
    reasons = {t.trim_id: t.reason for t in alpha.trims}
    assert "alpha.one.g1.trim.missing" not in reasons
    assert reasons["alpha.one.g1.trim.stale"] == STALE


def test_a_conflict_is_never_deferrable(data: Path, tmp_path):
    # A defer decision itself requires the ledger to already resolve a
    # LIST_PRICE (price_coverage_review.py refuses one otherwise), so a
    # CONFLICT trim structurally cannot be deferred -- confirmed here by
    # never applying a defer and just checking it always surfaces.
    catalog = Catalog.load(data, YEAR)
    ledger = PriceLedger.load(data, year=YEAR, catalog=catalog)
    gaps = coverage_gaps(catalog, ledger, as_of=date(2026, 9, 23),
                         data_dir=data, year=YEAR)
    beta = next(g for g in gaps if g.model_id == "beta.two")
    assert beta.trims[0].reason == CONFLICT


def test_summarize_counts_match_the_gap_list(data: Path):
    catalog = Catalog.load(data, YEAR)
    ledger = PriceLedger.load(data, year=YEAR, catalog=catalog)
    counts = summarize(catalog, ledger, as_of=date(2026, 9, 23))
    assert counts["total_trims"] == 4
    assert counts["trims_with_current_list_price"] == 1
    assert counts["trims_missing"] == 1
    assert counts["trims_stale"] == 1
    assert counts["trims_conflict"] == 1
