from __future__ import annotations

from pathlib import Path

import pytest

from tools.price_promote_batch import (
    _apply_with_rollback,
    _refuse_multiple_current_approvals,
)
from vehreg.price_promote import (
    PlannedFile,
    PromotionAction,
    PromotionDecision,
    PromotionError,
    PromotionPlan,
)
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


def test_apply_rolls_back_existing_and_new_files_on_write_failure(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    existing = tmp_path / "existing.json"
    new = tmp_path / "new.json"
    existing.write_text('{"before":true}\n', encoding="utf-8")
    plan = PromotionPlan(
        year=2026,
        files=(
            PlannedFile(existing, {"after": True}, "supersede_prior"),
            PlannedFile(new, {"new": True}, "append_price"),
        ),
        items=(),
        rejected_candidate_ids=(),
        affected_model_ids=(),
    )

    def broken_apply(self: PromotionPlan) -> None:
        existing.write_text('{"after":true}\n', encoding="utf-8")
        new.write_text('{"new":true}\n', encoding="utf-8")
        raise OSError("disk fixture")

    monkeypatch.setattr(PromotionPlan, "apply", broken_apply)

    with pytest.raises(OSError, match="disk fixture"):
        _apply_with_rollback(plan)

    assert existing.read_text(encoding="utf-8") == '{"before":true}\n'
    assert not new.exists()
