from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

from tdr_bridge.lifecycle import apply_retail_lifecycle


def _release(*, model_status="UNVERIFIED", model_row_status="current", ended=None,
             current_list_price=None):
    return {
        "as_of": "2026-09-11",
        "models": [{
            "canonical_id": "brand.model",
            "status": model_row_status,
            "payload": {"retail_status": model_status},
        }],
        "generations": [{
            "canonical_id": "brand.model.gen1",
            "model_id": "brand.model",
            "ended": ended,
        }],
        "market_trims": [{
            "canonical_id": "brand.model.gen1.trim.grade",
            "model_id": "brand.model",
            "generation_id": "brand.model.gen1",
            "status": "current",
            "current_list_price": current_list_price,
        }],
    }


def _decision(status: str):
    return [{
        "trim_id": "brand.model.gen1.trim.grade",
        "status": status,
        "reviewer": "Human Reviewer",
        "reviewed_at": "2026-09-11",
        "source_ref": "https://example.com/official-lineup",
        "notes": "official retail evidence",
    }]


def test_catalog_vehicle_is_current_by_default_even_without_price():
    source = _release()
    before = deepcopy(source)
    projected = apply_retail_lifecycle(source)

    assert source == before  # enrichment does not mutate the builder output
    assert projected["models"][0]["status"] == "CURRENT"
    assert projected["market_trims"][0]["status"] == "CURRENT"


def test_missing_price_is_price_debt_not_lifecycle_debt():
    unpriced = apply_retail_lifecycle(_release(model_status="UNVERIFIED"))
    priced = apply_retail_lifecycle(_release(
        model_status="UNVERIFIED",
        current_list_price={"amount_thb": 699000, "price_type": "LIST_PRICE"},
    ))

    assert unpriced["models"][0]["status"] == "CURRENT"
    assert unpriced["market_trims"][0]["status"] == "CURRENT"
    assert priced["models"][0]["status"] == "CURRENT"
    assert priced["market_trims"][0]["status"] == "CURRENT"


def test_human_current_review_remains_auditable():
    with patch("tdr_bridge.lifecycle.load_trim_lifecycle_decisions", return_value=_decision("CURRENT")):
        projected = apply_retail_lifecycle(_release())
    trim = projected["market_trims"][0]
    assert trim["status"] == "CURRENT"
    assert trim["retail_lifecycle_review"]["reviewer"] == "Human Reviewer"


def test_human_historical_review_archives_one_trim():
    with patch("tdr_bridge.lifecycle.load_trim_lifecycle_decisions", return_value=_decision("HISTORICAL")):
        projected = apply_retail_lifecycle(_release(
            current_list_price={"amount_thb": 999000},
        ))
    assert projected["models"][0]["status"] == "CURRENT"
    assert projected["market_trims"][0]["status"] == "HISTORICAL"


def test_ended_generation_beats_default_current_and_human_current_review():
    with patch("tdr_bridge.lifecycle.load_trim_lifecycle_decisions", return_value=_decision("CURRENT")):
        projected = apply_retail_lifecycle(_release(ended="2026-08-31"))
    assert projected["models"][0]["status"] == "CURRENT"
    assert projected["market_trims"][0]["status"] == "HISTORICAL"
    assert "retail_lifecycle_review" not in projected["market_trims"][0]


def test_archived_model_forces_child_trim_historical_even_with_human_current_review():
    with patch("tdr_bridge.lifecycle.load_trim_lifecycle_decisions", return_value=_decision("CURRENT")):
        projected = apply_retail_lifecycle(_release(
            model_status="HISTORICAL",
            current_list_price={"amount_thb": 999000},
        ))
    assert projected["models"][0]["status"] == "HISTORICAL"
    assert projected["market_trims"][0]["status"] == "HISTORICAL"


def test_legacy_or_unknown_non_historical_status_stays_current_by_owner_policy():
    lowercase = apply_retail_lifecycle(_release(model_status="current"))
    unknown = apply_retail_lifecycle(_release(model_status="SOMETHING_OLD"))

    assert lowercase["models"][0]["status"] == "CURRENT"
    assert lowercase["market_trims"][0]["status"] == "CURRENT"
    assert unknown["models"][0]["status"] == "CURRENT"
    assert unknown["market_trims"][0]["status"] == "CURRENT"
