from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from tools.price_promote_batch import _refuse_stale_replacements
from vehreg.catalog import DATA_DIR
from vehreg.price_promote import PromotionAction, PromotionDecision, PromotionError
from vehreg.price_reconcile import CandidateBook, CandidateState, PriceCandidate
from vehreg.price_sources import TargetRole
from vehreg.pricing import PriceType


YEAR = 2026
MAX_PLUS = "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev"


def _data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    models = root / str(YEAR) / "models"
    prices = root / str(YEAR) / "market" / "prices"
    models.mkdir(parents=True)
    prices.mkdir(parents=True)
    shutil.copy(DATA_DIR / str(YEAR) / "models" / "jaecoo.json", models / "jaecoo.json")
    shutil.copy(
        DATA_DIR / str(YEAR) / "market" / "prices" / "jaecoo.json",
        prices / "jaecoo.json",
    )
    return root


def _candidate(candidate_id: str = "pcand:stale") -> PriceCandidate:
    return PriceCandidate(
        candidate_id=candidate_id,
        state=CandidateState.CONFIRMED,
        trim_id=MAX_PLUS,
        amount_thb=719_000,
        price_type=PriceType.LIST_PRICE,
        source_id="official_jaecoo_th",
        target_id="jaecoo_th_home_price",
        target_role=TargetRole.PRICE_LIST,
        first_seen_at="2026-09-09T02:00:00+00:00",
        last_seen_at="2026-09-10T02:00:00+00:00",
        observation_count=2,
        claim_ids=("claim-1",),
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


def _report(candidate_id: str, disposition: str = "CONFIRMED_REPLACEMENT") -> dict:
    return {
        "decisions": [{
            "claim_id": "claim-1",
            "decision": {
                "candidate_id": candidate_id,
                "disposition": disposition,
            },
        }],
    }


def test_confirmed_replacement_passes_when_expected_prior_is_still_current(
        tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = _candidate()

    _refuse_stale_replacements(
        data_dir=root,
        year=YEAR,
        book=CandidateBook([candidate]),
        reconcile=_report(candidate.candidate_id),
        decisions={candidate.candidate_id: _approve(candidate.candidate_id)},
    )


def test_confirmed_replacement_is_refused_if_canonical_changed_after_p5(
        tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = _candidate()
    prices = root / str(YEAR) / "market" / "prices"
    (prices / "intervening_manual.json").write_text(
        json.dumps({"prices": [{
            "trim_id": MAX_PLUS,
            "amount_thb": 729_000,
            "price_type": "LIST_PRICE",
            "observed_at": "2026-09-10",
            "source": "manual_review",
            "source_ref": "https://example.com/intervening",
            "reviewed_by": "owner",
        }]}, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PromotionError, match="canonical stream changed since P5"):
        _refuse_stale_replacements(
            data_dir=root,
            year=YEAR,
            book=CandidateBook([candidate]),
            reconcile=_report(candidate.candidate_id),
            decisions={candidate.candidate_id: _approve(candidate.candidate_id)},
        )


def test_campaign_candidate_needs_canonical_option_at_write_boundary(
        tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = PriceCandidate(
        candidate_id="pcand:campaign-unscoped",
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
        claim_ids=("claim-campaign",),
        campaign_id="campaign.jaecoo.some_offer",
        option_id=None,
    )

    with pytest.raises(PromotionError, match=r"campaign_id \+ option_id"):
        _refuse_stale_replacements(
            data_dir=root,
            year=YEAR,
            book=CandidateBook([candidate]),
            reconcile=_report(candidate.candidate_id, "SAFE_CANDIDATE"),
            decisions={candidate.candidate_id: _approve(candidate.candidate_id)},
        )
