from __future__ import annotations

from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from vehreg.price_match import match_trim_diagnostic
from vehreg.price_reconcile import (
    CandidateBook,
    ReconcileDisposition,
    ReconcileObservation,
    ReconcileReason,
    reconcile_batch,
)
from vehreg.price_sources import TargetRole
from vehreg.pricefeed import PriceClaim, SourceDocument
from vehreg.pricing import PriceLedger, PriceType


SOURCE = "official_jaecoo_th"
AT = "2026-09-09T09:00:00+00:00"


def _claim(trim: str, amount: int, price_type: PriceType, *,
           claim_id: str) -> PriceClaim:
    return PriceClaim(
        claim_id=claim_id,
        document_id="sha256:" + claim_id.encode().hex().ljust(64, "0")[:64],
        source_id=SOURCE,
        brand_raw="JAECOO",
        model_raw="JAECOO 5 EV",
        trim_raw=trim,
        amount_thb=amount,
        price_type=price_type,
    )


def _observation(catalog: Catalog, trim: str, amount: int,
                 price_type: PriceType, *, role: TargetRole,
                 target_id: str, claim_id: str) -> ReconcileObservation:
    claim = _claim(trim, amount, price_type, claim_id=claim_id)
    document = SourceDocument(
        document_id=claim.document_id,
        source_id=SOURCE,
        url=f"https://www.omodajaecoo.co.th/th/{target_id}",
        content_hash=claim.document_id,
        first_seen_at=AT,
        fetched_at=AT,
    )
    return ReconcileObservation(
        claim=claim,
        match=match_trim_diagnostic(catalog, claim),
        target_id=target_id,
        target_role=role,
        document=document,
    )


def test_j5_current_page_matches_existing_max_plus_and_ultra_estimate() -> None:
    catalog = Catalog.load(DATA_DIR, DEFAULT_YEAR)
    ledger = PriceLedger.load(DATA_DIR, year=DEFAULT_YEAR, catalog=catalog)
    observations = [
        _observation(
            catalog, "MAX+", 699000, PriceType.LIST_PRICE,
            role=TargetRole.PRICE_LIST,
            target_id="jaecoo_th_home_price_cards",
            claim_id="j5-max-plus-699",
        ),
        _observation(
            catalog, "ULTRA", 809000, PriceType.ESTIMATED_PRICE,
            role=TargetRole.PRICE_LIST,
            target_id="jaecoo_th_home_price_cards",
            claim_id="j5-ultra-est-809",
        ),
    ]

    result = reconcile_batch(observations, ledger)

    assert [decision.disposition for decision in result.decisions] == [
        ReconcileDisposition.NO_CHANGE,
        ReconcileDisposition.NO_CHANGE,
    ]
    assert all(decision.reasons == (ReconcileReason.SAME_CANONICAL_PRICE,)
               for decision in result.decisions)


def test_j5_official_blog_does_not_silently_promote_ultra_789_list() -> None:
    catalog = Catalog.load(DATA_DIR, DEFAULT_YEAR)
    ledger = PriceLedger.load(DATA_DIR, year=DEFAULT_YEAR, catalog=catalog)
    observation = _observation(
        catalog, "ULTRA", 789000, PriceType.LIST_PRICE,
        role=TargetRole.BLOG,
        target_id="jaecoo_en_j5_buyer_guide_2026_09_02",
        claim_id="j5-blog-ultra-789",
    )

    result = reconcile_batch([observation], ledger)
    decision = result.decisions[0]

    # The blog is first-party evidence, but without a literal effective_from it
    # is not allowed to turn the historical/guide wording into a current MSRP.
    assert decision.disposition is ReconcileDisposition.REVIEW
    assert decision.reasons == (ReconcileReason.NON_CURRENT_ROLE_NEEDS_DATE,)


def test_j5_campaign_claim_stays_review_until_campaign_option_is_bound() -> None:
    catalog = Catalog.load(DATA_DIR, DEFAULT_YEAR)
    ledger = PriceLedger.load(DATA_DIR, year=DEFAULT_YEAR, catalog=catalog)
    observation = _observation(
        catalog, "MAX+", 579000, PriceType.CAMPAIGN_PRICE,
        role=TargetRole.PROMOTION,
        target_id="jaecoo_big_motor_sale_2026",
        claim_id="j5-promo-max-plus-579",
    )

    result = reconcile_batch([observation], ledger, candidate_book=CandidateBook())
    decision = result.decisions[0]

    assert decision.disposition is ReconcileDisposition.REVIEW
    assert decision.reasons == (ReconcileReason.CAMPAIGN_SCOPE_REQUIRED,)
    assert result.candidate_book.candidates == {}
