from __future__ import annotations

from tools.price_review_queue import build_queue


def test_review_queue_separates_candidate_approval_from_campaign_binding() -> None:
    candidate_state = {
        "schema_version": 1,
        "candidates": [{
            "candidate_id": "pcand:ready",
            "state": "CONFIRMED",
            "trim_id": "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev",
            "amount_thb": 719000,
            "price_type": "LIST_PRICE",
            "source_id": "official_jaecoo_th",
            "target_id": "jaecoo_th_home_price",
            "target_role": "PRICE_LIST",
            "first_seen_at": "2026-09-09T02:00:00+00:00",
            "last_seen_at": "2026-09-10T02:00:00+00:00",
            "observation_count": 2,
            "claim_ids": ["claim-ready"],
            "confirmed_at": "2026-09-10T02:00:00+00:00",
            "replaces_amount_thb": 699000,
            "historical_only": False,
        }],
    }
    reconcile = {
        "decisions": [
            {
                "claim_id": "claim-ready",
                "decision": {
                    "claim_id": "claim-ready",
                    "candidate_id": "pcand:ready",
                    "disposition": "CONFIRMED_REPLACEMENT",
                    "reasons": ["REPLACEMENT_PERSISTED_24H"],
                    "trim_id": "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev",
                },
            },
            {
                "claim_id": "claim-promo",
                "decision": {
                    "claim_id": "claim-promo",
                    "candidate_id": None,
                    "disposition": "REVIEW",
                    "reasons": ["CAMPAIGN_SCOPE_REQUIRED"],
                    "trim_id": "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev",
                },
            },
        ],
    }
    fetch = {
        "results": [{
            "target_id": "jaecoo_more_rain",
            "target_role": "PROMOTION",
            "source_id": "official_jaecoo_th",
            "document": {"url": "https://www.omodajaecoo.co.th/th/promotion/more-rain-more-gain"},
            "claims": [{
                "claim_id": "claim-promo",
                "amount_thb": 599000,
                "price_type": "CAMPAIGN_PRICE",
                "campaign_hint": "MORE RAIN, MORE GAIN",
                "option_hint": "",
            }],
        }],
    }

    queue = build_queue(candidate_state, reconcile, fetch)

    assert len(queue["promotion_reviews"]) == 1
    assert queue["promotion_reviews"][0]["candidate_id"] == "pcand:ready"
    assert queue["promotion_reviews"][0]["actions"] == ["APPROVE", "REJECT"]
    assert len(queue["binding_reviews"]) == 1
    binding = queue["binding_reviews"][0]
    assert binding["claim_id"] == "claim-promo"
    assert binding["raw_campaign_hint"] == "MORE RAIN, MORE GAIN"
    assert binding["required_action"] == "BIND_CANONICAL_CAMPAIGN_OPTION_THEN_RERUN_P5"
    assert queue["binding_decision_template"]["decisions"][0]["campaign_id"] == ""
