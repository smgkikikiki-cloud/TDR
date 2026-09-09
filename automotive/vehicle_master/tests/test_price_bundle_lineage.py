from __future__ import annotations

import json
from pathlib import Path

import pytest

from vehreg.price_bundle import (
    candidate_state_id,
    reconcile_id,
    source_batch_id,
    verify_promotion_lineage,
)
from vehreg.price_promote import (
    PromotionAction,
    PromotionDecision,
    PromotionError,
    _verify_price_intel_lineage,
    load_promotion_bundle,
)
from vehreg.price_reconcile import CandidateBook


def _fetch(*, fetched_at: str = "2026-09-09T02:00:00+00:00") -> dict:
    payload = {
        "schema_version": 1,
        "year": 2026,
        "extract_prices": True,
        "match_trims": True,
        "static_targets": ["jaecoo_th_home_price_cards"],
        "results": [{
            "target_id": "jaecoo_th_home_price_cards",
            "target_role": "PRICE_LIST",
            "source_id": "official_jaecoo_th",
            "document": {
                "document_id": "sha256:" + "a" * 64,
                "content_hash": "sha256:" + "a" * 64,
                "fetched_at": fetched_at,
            },
            "claims": [],
        }],
        "robots": {"https://www.omodajaecoo.co.th": "allowed"},
        "skipped_robots": 0,
    }
    payload["source_batch_id"] = source_batch_id(payload)
    return payload


def _state() -> dict:
    payload = {"schema_version": 1, "candidates": []}
    payload["candidate_state_id"] = candidate_state_id(payload)
    return payload


def _report(fetch: dict, state: dict) -> dict:
    payload = {
        "schema_version": 1,
        "year": 2026,
        "source_batch_id": fetch["source_batch_id"],
        "candidate_state_before_id": state["candidate_state_id"],
        "candidate_state_after_id": state["candidate_state_id"],
        "summary": {},
        "decisions": [],
    }
    payload["reconcile_id"] = reconcile_id(payload)
    return payload


def _decision(fetch: dict, state: dict, report: dict, *,
              batch_override: str | None = None) -> PromotionDecision:
    return PromotionDecision(
        candidate_id="pcand:lineage",
        action=PromotionAction.REJECT,
        reviewer="owner",
        origin="HUMAN",
        reviewed_at="2026-09-10T03:00:00+00:00",
        source_batch_id=batch_override or fetch["source_batch_id"],
        reconcile_id=report["reconcile_id"],
        candidate_state_id=state["candidate_state_id"],
    )


def test_source_batch_identity_ignores_robots_but_changes_on_new_observation() -> None:
    first = _fetch()
    changed_diagnostics = json.loads(json.dumps(first))
    changed_diagnostics["robots"] = {"https://www.omodajaecoo.co.th": "different diagnostic"}
    changed_diagnostics["skipped_robots"] = 99
    assert source_batch_id(changed_diagnostics) == first["source_batch_id"]

    later = _fetch(fetched_at="2026-09-10T03:00:00+00:00")
    assert later["source_batch_id"] != first["source_batch_id"]


def test_candidate_state_identity_ignores_lineage_metadata() -> None:
    state = _state()
    decorated = dict(state)
    decorated["last_source_batch_id"] = "pbatch:old"
    decorated["last_reconcile_id"] = "prec:old"
    assert candidate_state_id(decorated) == state["candidate_state_id"]


def test_end_to_end_lineage_verifier_accepts_one_coherent_chain() -> None:
    fetch = _fetch()
    state = _state()
    report = _report(fetch, state)
    state.update({
        "last_source_batch_id": fetch["source_batch_id"],
        "last_reconcile_id": report["reconcile_id"],
    })
    review = {
        "source_batch_id": fetch["source_batch_id"],
        "reconcile_id": report["reconcile_id"],
        "candidate_state_id": state["candidate_state_id"],
    }
    assert verify_promotion_lineage(
        candidate_state=state,
        reconcile=report,
        fetch=fetch,
        review=review,
    ) == review


def test_p6_core_rejects_review_from_another_source_batch() -> None:
    fetch = _fetch()
    state = _state()
    report = _report(fetch, state)
    decision = _decision(
        fetch, state, report,
        batch_override="pbatch:" + "f" * 64,
    )
    with pytest.raises(PromotionError, match="HUMAN review source_batch_id"):
        _verify_price_intel_lineage(
            candidate_book=CandidateBook(),
            reconcile_report=report,
            fetch_batch=fetch,
            decisions={decision.candidate_id: decision},
        )


def test_p6_core_rejects_fetch_mutated_after_batch_was_stamped() -> None:
    fetch = _fetch()
    state = _state()
    report = _report(fetch, state)
    decision = _decision(fetch, state, report)
    fetch["results"][0]["document"]["fetched_at"] = "2026-09-11T03:00:00+00:00"
    with pytest.raises(PromotionError, match="source_batch_id mismatch"):
        _verify_price_intel_lineage(
            candidate_book=CandidateBook(),
            reconcile_report=report,
            fetch_batch=fetch,
            decisions={decision.candidate_id: decision},
        )


def test_review_bundle_refuses_partial_lineage(tmp_path: Path) -> None:
    path = tmp_path / "review.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "source_batch_id": "pbatch:" + "a" * 64,
        "decisions": [{
            "candidate_id": "pcand:x",
            "action": "REJECT",
            "reviewer": "owner",
            "origin": "HUMAN",
            "reviewed_at": "2026-09-10T03:00:00+00:00",
        }],
        "create_campaigns": [],
    }), encoding="utf-8")
    with pytest.raises(PromotionError, match="review lineage must provide"):
        load_promotion_bundle(path)
