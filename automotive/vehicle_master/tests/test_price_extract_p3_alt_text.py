from vehreg.price_extract import extract_oem_price_claims
from vehreg.price_fetch import FetchResult, FetchState
from vehreg.price_sources import SourceTarget, TargetRole
from vehreg.pricefeed import SourceDocument, content_id
from vehreg.pricing import PriceType


def test_homepage_can_use_image_alt_for_trim_identity() -> None:
    target = SourceTarget(
        id="home",
        source_id="official_jaecoo_th",
        url="https://www.omodajaecoo.co.th/en",
        role=TargetRole.PRICE_LIST,
    )
    html = """
    <html><body>
      <img alt="JAECOO 5 EV ULTRA" src="ultra.jpg">
      <p>Estimated Price THB 809,000</p>
      <img alt="OMODA C5 EV MAX+" src="c5.jpg">
      <p>Price 709,000 THB</p>
      <img alt="JAECOO 5 EV MAX+" src="max.jpg">
      <p>Price THB 699,000</p>
      <img alt="JAECOO 6 EV 2WD MAX" src="j6.jpg">
    </body></html>
    """
    raw = html.encode("utf-8")
    digest = content_id(raw)
    result = FetchResult(
        target_id=target.id,
        target_role=target.role,
        source_id=target.source_id,
        document=SourceDocument(
            document_id=digest,
            source_id=target.source_id,
            url=target.url,
            content_hash=digest,
            fetched_at="2026-09-09T09:00:00+00:00",
        ),
        raw_body=raw,
        text=html,
        state=FetchState(target_id=target.id, content_hash=digest),
    )

    claims = extract_oem_price_claims(target, result).claims

    assert any(c.trim_raw == "ULTRA"
               and c.price_type is PriceType.ESTIMATED_PRICE
               and c.amount_thb == 809000 for c in claims)
    assert any(c.trim_raw == "MAX+"
               and c.price_type is PriceType.LIST_PRICE
               and c.amount_thb == 699000 for c in claims)
