from __future__ import annotations

from pathlib import Path

import pytest
import tools.price_promote_batch as promote_batch

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

    real_write = promote_batch._write_json
    calls = 0

    def broken_write(path: Path, payload: dict) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk fixture")
        real_write(path, payload)

    # P6 no longer calls PromotionPlan.apply(): that direct writer bypasses the
    # shared atomic writer primitive. Inject failure into the primitive the
    # production path actually uses and prove the whole touched set rolls back.
    monkeypatch.setattr(promote_batch, "_write_json", broken_write)

    with pytest.raises(OSError, match="disk fixture"):
        _apply_with_rollback(plan)

    assert existing.read_text(encoding="utf-8") == '{"before":true}\n'
    assert not new.exists()
