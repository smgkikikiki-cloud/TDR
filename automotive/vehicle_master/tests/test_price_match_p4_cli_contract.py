from pathlib import Path

from vehreg.catalog import DATA_DIR, DEFAULT_YEAR
from vehreg.price_match import TrimMatchState, match_trim_diagnostic
from vehreg.pricefeed import PriceClaim
from vehreg.pricing import PriceType
from vehreg.catalog import Catalog


def test_match_result_serializes_review_safe_fields() -> None:
    catalog = Catalog.load(DATA_DIR, DEFAULT_YEAR)
    claim = PriceClaim(
        claim_id="p4-cli",
        document_id="sha256:" + "b" * 64,
        source_id="official_jaecoo_th",
        brand_raw="JAECOO",
        model_raw="JAECOO 5 EV",
        trim_raw="MAX+",
        amount_thb=699000,
        price_type=PriceType.LIST_PRICE,
    )

    row = match_trim_diagnostic(catalog, claim).as_dict()

    assert row["state"] == TrimMatchState.EXACT.value
    assert row["model_id"] == "jaecoo.jaecoo_5_ev"
    assert row["trim_id"] == "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev"
    assert row["candidate_ids"] == [row["trim_id"]]
    assert row["normalized_trim_raw"] == "MAX PLUS"
    assert row["reason"]
