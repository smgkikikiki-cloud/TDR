from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from tools.price_promote_batch import (
    _refuse_orphan_campaign_creations,
    _refuse_stale_replacements,
)
from vehreg.catalog import DATA_DIR
from vehreg.price_promote import PromotionAction, PromotionDecision, PromotionError
from vehreg.price_reconcile import CandidateBook, CandidateState, PriceCandidate
from vehreg.price_sources import TargetRole
from vehreg.pricing import PriceType


YEAR = 2026
MAX_PLUS = "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev"
ULTRA = "jaecoo.jaecoo_5_ev.j5.trim.ultra_bev"


def _data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    models = root / str(YEAR) / "models"
    prices = root / str(YEAR) / "market" / "prices"
    models.mkdir(parents=True)
    prices.mkdir(parents=True)
    shutil.copy(DATA_DIR / str(YEAR) / "models" / "jaecoo.json", models / "jaecoo.json")
    shutil.copy(DATA_DIR / str(YEAR) / "market" / "prices" / "jaecoo.json",
                prices / "jaecoo.json")
    return root


def _approve(candidate_id: str, *, reviewed_at: str = "2026-09-10T03:00:00+00:00") -> PromotionDecision:
    return PromotionDecision(
        candidate_id=candidate_id,
        action=PromotionAction.APPROVE,
        reviewer="owner",
        origin="HUMAN",
        reviewed_at=reviewed_at,
    )


def _report(candidate_id: str, disposition: str = "SAFE_CANDIDATE") -> dict:
    return {
        "decisions": [{
            "claim_id": "claim-audit",
            "decision": {
                "candidate_id": candidate_id,
                "disposition": disposition,
            },
        }],
    }


def _safe_list(candidate_id: str = "pcand:safe-ultra") -> PriceCandidate:
    return PriceCandidate(
        candidate_id=candidate_id,
        state=CandidateState.NEW,
        trim_id=ULTRA,
        amount_thb=789_000,
        price_type=PriceType.LIST_PRICE,
        source_id="official_jaecoo_th",
        target_id="jaecoo_th_home_price",
        target_role=TargetRole.PRICE_LIST,
        first_seen_at="2026-09-09T02:00:00+00:00",
        last_seen_at="2026-09-09T02:00:00+00:00",
        observation_count=1,
        claim_ids=("claim-audit",),
    )


def _campaign_candidate(candidate_id: str = "pcand:campaign-audit") -> PriceCandidate:
    return PriceCandidate(
        candidate_id=candidate_id,
        state=CandidateState.NEW,
        trim_id=MAX_PLUS,
        amount_thb=599_000,
        price_type=PriceType.CAMPAIGN_PRICE,
        source_id="official_jaecoo_th",
        target_id="jaecoo_promo",
        target_role=TargetRole.PROMOTION,
        first_seen_at="2026-09-09T02:00:00+00:00",
        last_seen_at="2026-09-09T02:00:00+00:00",
        observation_count=1,
        claim_ids=("claim-audit",),
        campaign_id="campaign.audit.offer",
        option_id="cash",
    )


def _campaign(*, brand_id: str = "jaecoo", status: str = "ACTIVE",
              closed_at: str | None = None) -> dict:
    option = {
        "id": "cash",
        "label": "cash",
        "status": status,
        "conditions": {"finance_required": False},
    }
    if closed_at:
        option["closed_at"] = closed_at
    return {
        "id": "campaign.audit.offer",
        "brand_id": brand_id,
        "name": "Audit Offer",
        "options": [option],
    }


def test_safe_candidate_refuses_stream_that_gained_canonical_truth_after_p5(
        tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = _safe_list()
    prices = root / str(YEAR) / "market" / "prices"
    (prices / "intervening_ultra_list.json").write_text(
        json.dumps({"prices": [{
            "trim_id": ULTRA,
            "amount_thb": 799_000,
            "price_type": "LIST_PRICE",
            "observed_at": "2026-09-10",
            "source": "manual_review",
            "source_ref": "https://example.com/intervening-ultra",
            "reviewed_by": "owner",
        }]}, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PromotionError, match="SAFE_CANDIDATE stream is no longer empty"):
        _refuse_stale_replacements(
            data_dir=root,
            year=YEAR,
            book=CandidateBook([candidate]),
            reconcile=_report(candidate.candidate_id),
            decisions={candidate.candidate_id: _approve(candidate.candidate_id)},
        )


def test_campaign_candidate_refuses_campaign_from_wrong_brand(tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = _campaign_candidate()

    with pytest.raises(PromotionError, match="not trim brand"):
        _refuse_stale_replacements(
            data_dir=root,
            year=YEAR,
            book=CandidateBook([candidate]),
            reconcile=_report(candidate.candidate_id),
            decisions={candidate.candidate_id: _approve(candidate.candidate_id)},
            campaigns=(_campaign(brand_id="suzuki"),),
        )


def test_campaign_candidate_refuses_option_closed_before_review(tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = _campaign_candidate()

    with pytest.raises(PromotionError, match="campaign/option is not open"):
        _refuse_stale_replacements(
            data_dir=root,
            year=YEAR,
            book=CandidateBook([candidate]),
            reconcile=_report(candidate.candidate_id),
            decisions={candidate.candidate_id: _approve(candidate.candidate_id)},
            campaigns=(_campaign(status="SOLD_OUT", closed_at="2026-09-10"),),
        )


def test_orphan_created_campaign_cannot_ride_alongside_unrelated_approval() -> None:
    candidate = _safe_list()

    with pytest.raises(PromotionError, match="not referenced by any approved candidate"):
        _refuse_orphan_campaign_creations(
            CandidateBook([candidate]),
            {candidate.candidate_id: _approve(candidate.candidate_id)},
            (_campaign(),),
        )


def test_reviewed_campaign_used_by_approved_candidate_is_not_orphaned() -> None:
    candidate = _campaign_candidate()

    _refuse_orphan_campaign_creations(
        CandidateBook([candidate]),
        {candidate.candidate_id: _approve(candidate.candidate_id)},
        (_campaign(),),
    )
