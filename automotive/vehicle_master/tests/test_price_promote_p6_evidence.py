from __future__ import annotations

import pytest

from tools.price_promote_batch import _refuse_unbound_evidence
from vehreg.price_promote import PromotionAction, PromotionDecision, PromotionError
from vehreg.price_reconcile import CandidateBook, CandidateState, PriceCandidate
from vehreg.price_sources import TargetRole
from vehreg.pricing import PriceType


TRIM = "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev"
SOURCE = "official_jaecoo_th"
TARGET = "jaecoo_th_home_price"
DOCUMENT = "sha256:" + "a" * 64
LATEST_CLAIM = "claim-latest"


def _candidate() -> PriceCandidate:
    return PriceCandidate(
        candidate_id="pcand:evidence",
        state=CandidateState.CONFIRMED,
        trim_id=TRIM,
        amount_thb=719_000,
        price_type=PriceType.LIST_PRICE,
        source_id=SOURCE,
        target_id=TARGET,
        target_role=TargetRole.PRICE_LIST,
        first_seen_at="2026-09-09T02:00:00+00:00",
        last_seen_at="2026-09-10T02:00:00+00:00",
        observation_count=2,
        claim_ids=("claim-first", LATEST_CLAIM),
        confirmed_at="2026-09-10T02:00:00+00:00",
        replaces_amount_thb=699_000,
    )


def _approve(candidate_id: str) -> PromotionDecision:
    return PromotionDecision(
        candidate_id=candidate_id,
        action=PromotionAction.APPROVE,
        reviewer="owner",
        origin="HUMAN",
        reviewed_at="2026-09-10T03:00:00+00:00",
    )


def _fetch(*, claim_id: str = LATEST_CLAIM, amount: int = 719_000,
           match_state: str = "EXACT", trim_id: str = TRIM) -> dict:
    return {
        "results": [{
            "source_id": SOURCE,
            "target_id": TARGET,
            "document": {
                "document_id": DOCUMENT,
                "content_hash": DOCUMENT,
                "url": "https://www.omodajaecoo.co.th/th",
            },
            "claims": [{
                "claim_id": claim_id,
                "document_id": DOCUMENT,
                "source_id": SOURCE,
                "amount_thb": amount,
                "price_type": "LIST_PRICE",
                "match": {
                    "state": match_state,
                    "trim_id": trim_id,
                },
            }],
        }],
    }


def test_latest_p5_claim_must_bind_to_same_exact_p4_document_and_trim() -> None:
    candidate = _candidate()

    _refuse_unbound_evidence(
        book=CandidateBook([candidate]),
        fetch=_fetch(),
        decisions={candidate.candidate_id: _approve(candidate.candidate_id)},
    )


def test_old_fetch_batch_cannot_supply_immutable_sha_for_newer_candidate() -> None:
    candidate = _candidate()

    with pytest.raises(PromotionError, match="latest supporting claim"):
        _refuse_unbound_evidence(
            book=CandidateBook([candidate]),
            fetch=_fetch(claim_id="claim-first"),
            decisions={candidate.candidate_id: _approve(candidate.candidate_id)},
        )


def test_supporting_claim_must_keep_same_amount_type_and_exact_trim() -> None:
    candidate = _candidate()

    with pytest.raises(PromotionError, match="amount/type"):
        _refuse_unbound_evidence(
            book=CandidateBook([candidate]),
            fetch=_fetch(amount=729_000),
            decisions={candidate.candidate_id: _approve(candidate.candidate_id)},
        )

    with pytest.raises(PromotionError, match="same P4 EXACT MarketTrim"):
        _refuse_unbound_evidence(
            book=CandidateBook([candidate]),
            fetch=_fetch(match_state="AMBIGUOUS", trim_id=""),
            decisions={candidate.candidate_id: _approve(candidate.candidate_id)},
        )
