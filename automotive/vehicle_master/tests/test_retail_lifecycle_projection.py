from __future__ import annotations

from copy import deepcopy

from tdr_bridge.lifecycle import apply_retail_lifecycle


def _release(*, model_status="UNVERIFIED", model_row_status="current", ended=None,
             current_list_price=None):
    return {
        "as_of": "2026-09-11",
        "models": [{
            "canonical_id": "brand.model",
            # Deliberately simulate the legacy editorial projection bug.
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


def test_legacy_editorial_current_cannot_promote_unverified_canonical_model_or_trim():
    source = _release()
    before = deepcopy(source)
    projected = apply_retail_lifecycle(source)

    assert source == before  # enrichment does not mutate the builder output
    assert projected["models"][0]["status"] == "UNVERIFIED"
    assert projected["market_trims"][0]["status"] == "UNVERIFIED"


def test_current_canonical_list_price_is_trim_currentness_evidence():
    projected = apply_retail_lifecycle(_release(
        model_status="CURRENT",
        current_list_price={"amount_thb": 699000, "price_type": "LIST_PRICE"},
    ))
    assert projected["models"][0]["status"] == "CURRENT"
    assert projected["market_trims"][0]["status"] == "CURRENT"


def test_active_generation_without_retail_evidence_does_not_make_trim_current():
    projected = apply_retail_lifecycle(_release(model_status="CURRENT"))
    assert projected["models"][0]["status"] == "CURRENT"
    assert projected["market_trims"][0]["status"] == "UNVERIFIED"


def test_ended_generation_is_historical_even_if_old_price_row_is_still_present():
    projected = apply_retail_lifecycle(_release(
        model_status="CURRENT",
        ended="2026-08-31",
        current_list_price={"amount_thb": 999000},
    ))
    assert projected["market_trims"][0]["status"] == "HISTORICAL"


def test_historical_model_forces_child_trim_historical():
    projected = apply_retail_lifecycle(_release(
        model_status="HISTORICAL",
        current_list_price={"amount_thb": 999000},
    ))
    assert projected["models"][0]["status"] == "HISTORICAL"
    assert projected["market_trims"][0]["status"] == "HISTORICAL"


def test_unknown_or_malformed_status_fails_closed():
    projected = apply_retail_lifecycle(_release(model_status="current"))
    # Lowercase is intentionally not accepted: that is the exact legacy value
    # that used to be supplied for free by the serving bridge.
    assert projected["models"][0]["status"] == "UNVERIFIED"
    assert projected["market_trims"][0]["status"] == "UNVERIFIED"
