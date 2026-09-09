from __future__ import annotations

import shutil
from pathlib import Path

from vehreg.catalog import DATA_DIR
from vehreg.price_match import TrimMatchMethod, TrimMatchResult, TrimMatchState
from vehreg.price_promote import PromotionAction, PromotionDecision, build_promotion_plan
from vehreg.price_reconcile import (
    CandidateBook,
    CandidateState,
    PriceCandidate,
    ReconcileDisposition,
    ReconcileObservation,
    reconcile_one,
)
from vehreg.price_sources import TargetRole
from vehreg.pricefeed import PriceClaim, SourceDocument
from vehreg.pricing import PriceLedger, PriceRecord, PriceType


YEAR = 2026
SOURCE = "official_jaecoo_th"
TARGET = "jaecoo_th_home_price"
MAX_PLUS = "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev"
DOCUMENT_ID = "sha256:" + "a" * 64
URL = "https://www.omodajaecoo.co.th/th"


def _match() -> TrimMatchResult:
    return TrimMatchResult(
        state=TrimMatchState.EXACT,
        model_id="jaecoo.jaecoo_5_ev",
        trim_id=MAX_PLUS,
        candidate_ids=(MAX_PLUS,),
        method=TrimMatchMethod.EXACT_NAME,
        reason="fixture",
        normalized_trim_raw="MAX PLUS",
    )


def _document(stamp: str) -> SourceDocument:
    return SourceDocument(
        document_id=DOCUMENT_ID,
        source_id=SOURCE,
        url=URL,
        content_hash=DOCUMENT_ID,
        first_seen_at=stamp,
        fetched_at=stamp,
    )


def test_p5_compares_explicit_window_on_thailand_business_date() -> None:
    # 18:30Z on Sep 9 is already Sep 10 in Thailand. A literal source window
    # ending Sep 9 must therefore be historical, not live for seven extra hours.
    stamp = "2026-09-09T18:30:00+00:00"
    claim = PriceClaim(
        claim_id="claim-bangkok-window",
        document_id=DOCUMENT_ID,
        source_id=SOURCE,
        brand_raw="JAECOO",
        model_raw="JAECOO 5 EV",
        trim_raw="MAX+",
        amount_thb=599_000,
        price_type=PriceType.LIST_PRICE,
        effective_from="2026-09-01",
        effective_to="2026-09-09",
    )
    observation = ReconcileObservation(
        claim=claim,
        match=_match(),
        target_id=TARGET,
        target_role=TargetRole.PRICE_LIST,
        document=_document(stamp),
    )
    ledger = PriceLedger(YEAR)
    ledger.records.append(PriceRecord(
        trim_id=MAX_PLUS,
        amount_thb=699_000,
        price_type=PriceType.LIST_PRICE,
        observed_at="2026-09-01",
        source=SOURCE,
    ))

    decision = reconcile_one(observation, ledger, candidate_book=CandidateBook())

    assert decision.disposition is ReconcileDisposition.HISTORICAL_ONLY


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


def _approval(candidate_id: str) -> PromotionDecision:
    return PromotionDecision(
        candidate_id=candidate_id,
        action=PromotionAction.APPROVE,
        reviewer="owner",
        origin="HUMAN",
        reviewed_at="2026-09-10T03:00:00+00:00",
    )


def _report(candidate_id: str) -> dict:
    return {
        "schema_version": 1,
        "decisions": [{
            "claim_id": "claim-p6-time",
            "decision": {
                "candidate_id": candidate_id,
                "disposition": "CONFIRMED_REPLACEMENT",
            },
        }],
    }


def _fetch() -> dict:
    return {
        "schema_version": 1,
        "results": [{
            "target_id": TARGET,
            "target_role": "PRICE_LIST",
            "source_id": SOURCE,
            "document": {
                "url": URL,
                "document_id": DOCUMENT_ID,
                "content_hash": DOCUMENT_ID,
            },
            "claims": [],
        }],
    }


def test_p6_infers_canonical_dates_on_thailand_business_calendar(tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = PriceCandidate(
        candidate_id="pcand:bangkok-date",
        state=CandidateState.CONFIRMED,
        trim_id=MAX_PLUS,
        amount_thb=719_000,
        price_type=PriceType.LIST_PRICE,
        source_id=SOURCE,
        target_id=TARGET,
        target_role=TargetRole.PRICE_LIST,
        first_seen_at="2026-09-08T18:30:00+00:00",  # Sep 9 Thailand
        last_seen_at="2026-09-09T18:30:00+00:00",   # Sep 10 Thailand
        observation_count=2,
        claim_ids=("claim-p6-time",),
        confirmed_at="2026-09-09T18:30:00+00:00",
        replaces_amount_thb=699_000,
    )

    plan = build_promotion_plan(
        data_dir=root,
        year=YEAR,
        candidate_book=CandidateBook([candidate]),
        reconcile_report=_report(candidate.candidate_id),
        fetch_batch=_fetch(),
        decisions={candidate.candidate_id: _approval(candidate.candidate_id)},
    )

    row = next(file for file in plan.files if file.kind == "append_price").payload["prices"][0]
    assert row["observed_at"] == "2026-09-09"
    assert row["effective_from"] == "2026-09-10"
    prior = next(file for file in plan.files if file.kind == "supersede_prior")
    prior_row = next(
        item for item in prior.payload["prices"]
        if item["trim_id"] == MAX_PLUS and item["price_type"] == "LIST_PRICE"
    )
    assert prior_row["effective_to"] == "2026-09-09"


def test_p6_preserves_literal_source_date_even_across_timezone_boundary(tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = PriceCandidate(
        candidate_id="pcand:literal-source-date",
        state=CandidateState.CONFIRMED,
        trim_id=MAX_PLUS,
        amount_thb=719_000,
        price_type=PriceType.LIST_PRICE,
        source_id=SOURCE,
        target_id=TARGET,
        target_role=TargetRole.PRICE_LIST,
        first_seen_at="2026-09-09T18:30:00+00:00",  # Sep 10 Thailand
        last_seen_at="2026-09-10T18:30:00+00:00",
        observation_count=2,
        claim_ids=("claim-p6-time",),
        confirmed_at="2026-09-10T18:30:00+00:00",
        replaces_amount_thb=699_000,
        effective_from="2026-09-09",
    )

    plan = build_promotion_plan(
        data_dir=root,
        year=YEAR,
        candidate_book=CandidateBook([candidate]),
        reconcile_report=_report(candidate.candidate_id),
        fetch_batch=_fetch(),
        decisions={candidate.candidate_id: _approval(candidate.candidate_id)},
    )

    row = next(file for file in plan.files if file.kind == "append_price").payload["prices"][0]
    assert row["effective_from"] == "2026-09-09"
    assert row["observed_at"] == "2026-09-10"
