from __future__ import annotations

import pytest

from tools.price_promote_batch import _refuse_multiple_current_approvals
from vehreg.price_promote import PromotionAction, PromotionDecision, PromotionError
from vehreg.price_reconcile import CandidateBook, CandidateState, PriceCandidate
from vehreg.price_sources import TargetRole
from vehreg.pricing import PriceType


def _candidate(candidate_id: str, amount: int) -> PriceCandidate:
    return PriceCandidate(
        candidate_id=candidate_id,
        state=CandidateState.NEW,
        trim_id="jaecoo.jaecoo_5_ev.j5.trim.ultra_bev",
        amount_thb=amount,
        price_type=PriceType.LIST_PRICE,
        source_id="official_jaecoo_th",
        target_id=candidate_id,
        target_role=TargetRole.PRICE_LIST,
        first_seen_at="2026-09-09T02:00:00+00:00",
        last_seen_at="2026-09-09T02:00:00+00:00",
        observation_count=1,
        claim_ids=(candidate_id,),
    )


def _approve(candidate_id: str) -> PromotionDecision:
    return PromotionDecision(
        candidate_id=candidate_id,
        action=PromotionAction.APPROVE,
        reviewer="owner",
        origin="HUMAN",
        reviewed_at="2026-09-09T03:00:00+00:00",
    )


def test_two_approved_current_candidates_in_same_stream_are_refused() -> None:
    one = _candidate("pcand:one", 789000)
    two = _candidate("pcand:two", 799000)
    book = CandidateBook([one, two])

    with pytest.raises(PromotionError, match="same canonical stream"):
        _refuse_multiple_current_approvals(
            book,
            {one.candidate_id: _approve(one.candidate_id),
             two.candidate_id: _approve(two.candidate_id)},
        )
