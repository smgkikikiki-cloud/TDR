from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from vehreg.catalog import DATA_DIR, Catalog
from vehreg.price_promote import (
    PromotionAction,
    PromotionDecision,
    PromotionError,
    build_promotion_plan,
)
from vehreg.price_reconcile import CandidateBook, CandidateState, PriceCandidate
from vehreg.price_sources import TargetRole
from vehreg.pricing import PriceLedger, PriceType


YEAR = 2026
MAX_PLUS = "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev"
ULTRA = "jaecoo.jaecoo_5_ev.j5.trim.ultra_bev"
SOURCE = "official_jaecoo_th"
TARGET = "jaecoo_th_home_price"
URL = "https://www.omodajaecoo.co.th/th"
DOCUMENT_ID = "sha256:" + "a" * 64


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


def _candidate(candidate_id: str, *, trim_id: str = MAX_PLUS,
               amount: int = 719000,
               price_type: PriceType = PriceType.LIST_PRICE,
               state: CandidateState = CandidateState.CONFIRMED,
               first: str = "2026-09-09T02:00:00+00:00",
               last: str = "2026-09-10T02:00:00+00:00",
               confirmed: str | None = "2026-09-10T02:00:00+00:00",
               replaces: int | None = 699000,
               effective_from: str | None = None,
               effective_to: str | None = None,
               campaign_id: str | None = None,
               option_id: str | None = None,
               historical_only: bool = False,
               target_role: TargetRole = TargetRole.PRICE_LIST) -> PriceCandidate:
    return PriceCandidate(
        candidate_id=candidate_id,
        state=state,
        trim_id=trim_id,
        amount_thb=amount,
        price_type=price_type,
        source_id=SOURCE,
        target_id=TARGET,
        target_role=target_role,
        first_seen_at=first,
        last_seen_at=last,
        observation_count=2 if state is CandidateState.CONFIRMED else 1,
        claim_ids=("claim-1",),
        campaign_id=campaign_id,
        option_id=option_id,
        confirmed_at=confirmed,
        replaces_amount_thb=replaces,
        effective_from=effective_from,
        effective_to=effective_to,
        historical_only=historical_only,
    )


def _approval(candidate_id: str, action: PromotionAction = PromotionAction.APPROVE) -> PromotionDecision:
    return PromotionDecision(
        candidate_id=candidate_id,
        action=action,
        reviewer="owner",
        origin="HUMAN",
        reviewed_at="2026-09-10T03:00:00+00:00",
        notes="reviewed fixture",
    )


def _report(candidate_id: str, disposition: str) -> dict:
    return {
        "schema_version": 1,
        "decisions": [{
            "claim_id": "claim-1",
            "decision": {
                "candidate_id": candidate_id,
                "disposition": disposition,
            },
        }],
    }


def _fetch(*, target_id: str = TARGET, role: str = "PRICE_LIST") -> dict:
    return {
        "schema_version": 1,
        "results": [{
            "target_id": target_id,
            "target_role": role,
            "source_id": SOURCE,
            "document": {
                "url": URL,
                "document_id": DOCUMENT_ID,
                "content_hash": DOCUMENT_ID,
            },
            "claims": [],
        }],
    }


def _build(root: Path, candidate: PriceCandidate, disposition: str, *,
           decision: PromotionDecision | None = None,
           campaigns: tuple[dict, ...] = ()):
    return build_promotion_plan(
        data_dir=root,
        year=YEAR,
        candidate_book=CandidateBook([candidate]),
        reconcile_report=_report(candidate.candidate_id, disposition),
        fetch_batch=_fetch(),
        decisions={candidate.candidate_id: decision or _approval(candidate.candidate_id)},
        create_campaigns=campaigns,
    )


def test_confirmed_list_replacement_closes_prior_and_appends_new(tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = _candidate("pcand:replace-max-plus")

    plan = _build(root, candidate, "CONFIRMED_REPLACEMENT")

    kinds = {file.kind for file in plan.files}
    assert kinds == {"supersede_prior", "append_price"}
    prior = next(file for file in plan.files if file.kind == "supersede_prior")
    old = next(row for row in prior.payload["prices"]
               if row["trim_id"] == MAX_PLUS and row["price_type"] == "LIST_PRICE")
    assert old["amount_thb"] == 699000
    assert old["effective_to"] == "2026-09-09"

    new = next(file for file in plan.files if file.kind == "append_price")
    row = new.payload["prices"][0]
    assert row["amount_thb"] == 719000
    assert row["observed_at"] == "2026-09-09"
    assert row["effective_from"] == "2026-09-10"
    assert row["source"] == SOURCE
    assert row["source_ref"] == URL
    assert row["source_document_id"] == DOCUMENT_ID
    assert row["reviewed_by"] == "owner"

    plan.apply()
    catalog = Catalog.load(root, YEAR)
    ledger = PriceLedger.load(root, year=YEAR, catalog=catalog)
    assert ledger.current_list_amount(MAX_PLUS, as_of=__import__("datetime").date(2026, 9, 9)) == 699000
    assert ledger.current_list_amount(MAX_PLUS, as_of=__import__("datetime").date(2026, 9, 10)) == 719000


def test_literal_effective_from_is_preserved_when_replacement_confirms_later(tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = _candidate(
        "pcand:explicit-date",
        first="2026-09-10T02:00:00+00:00",
        last="2026-09-11T02:00:00+00:00",
        confirmed="2026-09-11T02:00:00+00:00",
        effective_from="2026-09-09",
    )

    plan = _build(root, candidate, "CONFIRMED_REPLACEMENT")

    prior = next(file for file in plan.files if file.kind == "supersede_prior")
    old = next(row for row in prior.payload["prices"]
               if row["trim_id"] == MAX_PLUS and row["price_type"] == "LIST_PRICE")
    assert old["effective_to"] == "2026-09-08"
    new = next(file for file in plan.files if file.kind == "append_price").payload["prices"][0]
    assert new["effective_from"] == "2026-09-09"
    assert new["observed_at"] == "2026-09-10"


def test_new_list_stream_promotes_without_closing_estimated_stream(tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = _candidate(
        "pcand:ultra-list",
        trim_id=ULTRA,
        amount=789000,
        state=CandidateState.NEW,
        first="2026-09-09T03:00:00+00:00",
        last="2026-09-09T03:00:00+00:00",
        confirmed=None,
        replaces=None,
    )

    plan = _build(root, candidate, "SAFE_CANDIDATE")

    assert [file.kind for file in plan.files] == ["append_price"]
    plan.apply()
    catalog = Catalog.load(root, YEAR)
    ledger = PriceLedger.load(root, year=YEAR, catalog=catalog)
    assert ledger.current_list_amount(ULTRA, as_of=__import__("datetime").date(2026, 9, 9)) == 789000
    estimates = ledger.records_for(ULTRA, price_type=PriceType.ESTIMATED_PRICE)
    assert len(estimates) == 1
    assert estimates[0].amount_thb == 809000
    assert estimates[0].effective_to is None


def test_pending_reverted_and_review_candidates_cannot_promote(tmp_path: Path) -> None:
    root = _data(tmp_path)
    for state in (CandidateState.PENDING_24H, CandidateState.REVERTED, CandidateState.REVIEW):
        candidate = _candidate(
            f"pcand:{state.value.lower()}",
            state=state,
            confirmed=None,
        )
        with pytest.raises(PromotionError):
            _build(root, candidate, "CONFIRMED_REPLACEMENT")


def test_non_promotable_p5_disposition_cannot_be_overridden_by_human_approve(tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = _candidate("pcand:conflict")
    with pytest.raises(PromotionError, match="not promotable"):
        _build(root, candidate, "CONFLICT")


def test_reject_is_a_no_write_review_decision(tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = _candidate("pcand:rejected")

    plan = _build(
        root,
        candidate,
        "CONFIRMED_REPLACEMENT",
        decision=_approval(candidate.candidate_id, PromotionAction.REJECT),
    )

    assert plan.files == ()
    assert plan.items == ()
    assert plan.rejected_candidate_ids == (candidate.candidate_id,)


def test_approval_must_be_human() -> None:
    with pytest.raises(PromotionError, match="origin HUMAN"):
        PromotionDecision.from_dict({
            "candidate_id": "pcand:x",
            "action": "APPROVE",
            "reviewer": "pricebot",
            "origin": "SYSTEM_EVIDENCE",
            "reviewed_at": "2026-09-10T03:00:00+00:00",
        })


def test_p6_rejects_url_only_fetch_evidence(tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = _candidate("pcand:url-only")
    fetch = _fetch()
    fetch["results"][0]["document"] = {"url": URL}

    with pytest.raises(PromotionError, match="immutable document_id"):
        build_promotion_plan(
            data_dir=root,
            year=YEAR,
            candidate_book=CandidateBook([candidate]),
            reconcile_report=_report(candidate.candidate_id, "CONFIRMED_REPLACEMENT"),
            fetch_batch=fetch,
            decisions={candidate.candidate_id: _approval(candidate.candidate_id)},
        )


def test_p6_rejects_document_hash_mismatch(tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = _candidate("pcand:hash-mismatch")
    fetch = _fetch()
    fetch["results"][0]["document"]["content_hash"] = "sha256:" + "b" * 64

    with pytest.raises(PromotionError, match="document_id/content_hash"):
        build_promotion_plan(
            data_dir=root,
            year=YEAR,
            candidate_book=CandidateBook([candidate]),
            reconcile_report=_report(candidate.candidate_id, "CONFIRMED_REPLACEMENT"),
            fetch_batch=fetch,
            decisions={candidate.candidate_id: _approval(candidate.candidate_id)},
        )


def _open_campaign() -> dict:
    return {
        "id": "campaign.jaecoo.more_rain_2026",
        "brand_id": "jaecoo",
        "name": "More Rain, More Gain",
        "source": SOURCE,
        "source_ref": "https://www.omodajaecoo.co.th/th/promotion/more-rain-more-gain",
        "options": [{
            "id": "cash_special",
            "label": "ราคาพิเศษเงินสด",
            "status": "ACTIVE",
            "conditions": {
                "finance_required": False,
                "text": "Official promotion; no explicit end date published.",
            },
        }],
    }


def test_reviewed_campaign_identity_can_be_created_with_price(tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = _candidate(
        "pcand:new-campaign",
        amount=599000,
        price_type=PriceType.CAMPAIGN_PRICE,
        state=CandidateState.NEW,
        first="2026-09-09T03:00:00+00:00",
        last="2026-09-09T03:00:00+00:00",
        confirmed=None,
        replaces=None,
        campaign_id="campaign.jaecoo.more_rain_2026",
        option_id="cash_special",
        target_role=TargetRole.PROMOTION,
    )

    plan = _build(
        root, candidate, "SAFE_CANDIDATE",
        campaigns=(_open_campaign(),),
    )

    assert {file.kind for file in plan.files} == {"campaign_create", "append_price"}
    plan.apply()
    catalog = Catalog.load(root, YEAR)
    ledger = PriceLedger.load(root, year=YEAR, catalog=catalog)
    offers = ledger.current_campaign_offers(
        MAX_PLUS, as_of=__import__("datetime").date(2026, 9, 9))
    assert [(row.amount_thb, row.campaign_id, row.option_id) for row in offers] == [
        (599000, "campaign.jaecoo.more_rain_2026", "cash_special")
    ]


def test_campaign_candidate_cannot_publish_to_unknown_binding(tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = _candidate(
        "pcand:unknown-campaign",
        amount=599000,
        price_type=PriceType.CAMPAIGN_PRICE,
        state=CandidateState.NEW,
        confirmed=None,
        replaces=None,
        campaign_id="campaign.jaecoo.missing",
        option_id="cash_special",
        target_role=TargetRole.PROMOTION,
    )
    with pytest.raises(PromotionError, match="does not exist"):
        _build(root, candidate, "SAFE_CANDIDATE")


def test_campaign_replacement_closes_only_exact_campaign_option_stream(tmp_path: Path) -> None:
    root = _data(tmp_path)
    campaigns = root / str(YEAR) / "market" / "campaigns"
    campaigns.mkdir(parents=True)
    (campaigns / "jaecoo_fixture.json").write_text(
        json.dumps({"campaigns": [_open_campaign()]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    prices = root / str(YEAR) / "market" / "prices"
    (prices / "jaecoo_campaign_fixture.json").write_text(
        json.dumps({"prices": [{
            "trim_id": MAX_PLUS,
            "amount_thb": 579000,
            "price_type": "CAMPAIGN_PRICE",
            "observed_at": "2026-09-01",
            "source": SOURCE,
            "source_ref": URL,
            "campaign_id": "campaign.jaecoo.more_rain_2026",
            "option_id": "cash_special",
        }]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    candidate = _candidate(
        "pcand:campaign-replace",
        amount=599000,
        price_type=PriceType.CAMPAIGN_PRICE,
        campaign_id="campaign.jaecoo.more_rain_2026",
        option_id="cash_special",
        replaces=579000,
        target_role=TargetRole.PROMOTION,
    )

    plan = _build(root, candidate, "CONFIRMED_REPLACEMENT")
    prior = next(file for file in plan.files if file.kind == "supersede_prior")
    old = prior.payload["prices"][0]
    assert old["amount_thb"] == 579000
    assert old["effective_to"] == "2026-09-09"
    new = next(file for file in plan.files if file.kind == "append_price").payload["prices"][0]
    assert new["campaign_id"] == "campaign.jaecoo.more_rain_2026"
    assert new["option_id"] == "cash_special"


def test_explicit_historical_candidate_appends_history_without_superseding_current(tmp_path: Path) -> None:
    root = _data(tmp_path)
    candidate = _candidate(
        "pcand:history",
        amount=579000,
        price_type=PriceType.CAMPAIGN_PRICE,
        state=CandidateState.NEW,
        first="2026-09-09T03:00:00+00:00",
        last="2026-09-09T03:00:00+00:00",
        confirmed=None,
        replaces=None,
        effective_from="2026-08-21",
        effective_to="2026-08-30",
        campaign_id="campaign.jaecoo.big_motor_sale_2026",
        option_id="event_cash",
        historical_only=True,
        target_role=TargetRole.PROMOTION,
    )
    campaign = {
        "id": "campaign.jaecoo.big_motor_sale_2026",
        "brand_id": "jaecoo",
        "name": "BIG MOTOR SALE 2026",
        "starts": "2026-08-21",
        "ends": "2026-08-30",
        "source": SOURCE,
        "source_ref": "https://www.omodajaecoo.co.th/th/promotion/big-motor-sales",
        "options": [{
            "id": "event_cash",
            "label": "Event special price",
            "starts": "2026-08-21",
            "ends": "2026-08-30",
            "status": "ACTIVE",
            "conditions": {"text": "BIG MOTOR SALE event window"},
        }],
    }

    plan = _build(root, candidate, "HISTORICAL_ONLY", campaigns=(campaign,))

    assert {file.kind for file in plan.files} == {"campaign_create", "append_price"}
    assert not any(file.kind == "supersede_prior" for file in plan.files)
    row = next(file for file in plan.files if file.kind == "append_price").payload["prices"][0]
    assert row["effective_from"] == "2026-08-21"
    assert row["effective_to"] == "2026-08-30"
