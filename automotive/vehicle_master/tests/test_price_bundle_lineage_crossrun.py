from __future__ import annotations

import pytest

from vehreg.price_bundle import candidate_state_id, reconcile_id, source_batch_id
from vehreg.price_promote import (
    PromotionAction,
    PromotionDecision,
    PromotionError,
    _verify_price_intel_lineage,
)
from vehreg.price_reconcile import CandidateBook, CandidateState, PriceCandidate
from vehreg.price_sources import TargetRole
from vehreg.pricing import PriceType


def _fetch(stamp: str = "2026-09-09T02:00:00+00:00") -> dict:
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
                "fetched_at": stamp,
            },
            "claims": [],
        }],
    }
    payload["source_batch_id"] = source_batch_id(payload)
    return payload


def _candidate(amount: int = 719_000) -> PriceCandidate:
    return PriceCandidate(
        candidate_id="pcand:lineage-crossrun",
        state=CandidateState.NEW,
        trim_id="jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev",
        amount_thb=amount,
        price_type=PriceType.LIST_PRICE,
        source_id="official_jaecoo_th",
        target_id="jaecoo_th_home_price_cards",
        target_role=TargetRole.PRICE_LIST,
        first_seen_at="2026-09-09T02:00:00+00:00",
        last_seen_at="2026-09-09T02:00:00+00:00",
        observation_count=1,
        claim_ids=("claim-lineage",),
    )


def _report(fetch: dict, book: CandidateBook, *, summary: dict | None = None) -> dict:
    state_id = candidate_state_id(book.to_payload())
    payload = {
        "schema_version": 1,
        "year": 2026,
        "source_batch_id": fetch["source_batch_id"],
        "candidate_state_before_id": candidate_state_id(CandidateBook().to_payload()),
        "candidate_state_after_id": state_id,
        "summary": summary or {},
        "decisions": [],
    }
    payload["reconcile_id"] = reconcile_id(payload)
    return payload


def _decision(fetch: dict, book: CandidateBook, report: dict) -> PromotionDecision:
    return PromotionDecision(
        candidate_id="pcand:lineage-crossrun",
        action=PromotionAction.REJECT,
        reviewer="owner",
        origin="HUMAN",
        reviewed_at="2026-09-10T03:00:00+00:00",
        source_batch_id=fetch["source_batch_id"],
        reconcile_id=report["reconcile_id"],
        candidate_state_id=candidate_state_id(book.to_payload()),
    )


def test_review_cannot_be_reused_with_another_reconcile_of_same_fetch() -> None:
    fetch = _fetch()
    book = CandidateBook([_candidate()])
    reviewed_report = _report(fetch, book)
    decision = _decision(fetch, book, reviewed_report)

    later_report = _report(fetch, book, summary={"rerun": 1})
    assert later_report["reconcile_id"] != reviewed_report["reconcile_id"]

    with pytest.raises(PromotionError, match="HUMAN review reconcile_id"):
        _verify_price_intel_lineage(
            candidate_book=book,
            reconcile_report=later_report,
            fetch_batch=fetch,
            decisions={decision.candidate_id: decision},
        )


def test_review_cannot_be_reused_after_candidate_book_changes() -> None:
    fetch = _fetch()
    reviewed_book = CandidateBook([_candidate()])
    report = _report(fetch, reviewed_book)
    decision = _decision(fetch, reviewed_book, report)

    changed_book = CandidateBook([_candidate(amount=729_000)])
    assert candidate_state_id(changed_book.to_payload()) != decision.candidate_state_id

    with pytest.raises(PromotionError, match="does not produce the supplied CandidateBook"):
        _verify_price_intel_lineage(
            candidate_book=changed_book,
            reconcile_report=report,
            fetch_batch=fetch,
            decisions={decision.candidate_id: decision},
        )
