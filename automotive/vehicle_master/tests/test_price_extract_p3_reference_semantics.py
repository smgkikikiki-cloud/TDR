from vehreg.price_extract import extract_oem_price_claims
from vehreg.price_fetch import FetchResult, FetchState
from vehreg.price_sources import SourceTarget, TargetRole
from vehreg.pricefeed import SourceDocument, content_id
from vehreg.pricing import PriceType


def _run(line: str):
    target = SourceTarget(
        id="promo",
        source_id="official_jaecoo_th",
        url="https://www.omodajaecoo.co.th/th/promotion/pilot",
        role=TargetRole.PROMOTION,
    )
    html = f"<html><body><p>JAECOO 5 EV ULTRA</p><p>{line}</p></body></html>"
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
    return extract_oem_price_claims(target, result).claims


def test_from_plain_price_is_list_reference() -> None:
    claims = _run("ราคาพิเศษ 669,000 บาท (จากราคา 789,000 บาท)")
    assert any(c.price_type is PriceType.CAMPAIGN_PRICE and c.amount_thb == 669000
               for c in claims)
    assert any(c.price_type is PriceType.LIST_PRICE and c.amount_thb == 789000
               for c in claims)
    assert not any(c.price_type is PriceType.ESTIMATED_PRICE and c.amount_thb == 789000
                   for c in claims)


def test_from_estimated_price_stays_estimated_reference() -> None:
    claims = _run("ราคาพิเศษ 699,000 บาท (จากราคาคาดการณ์ 809,000 บาท)")
    assert any(c.price_type is PriceType.CAMPAIGN_PRICE and c.amount_thb == 699000
               for c in claims)
    assert any(c.price_type is PriceType.ESTIMATED_PRICE and c.amount_thb == 809000
               for c in claims)
    assert not any(c.price_type is PriceType.LIST_PRICE and c.amount_thb == 809000
                   for c in claims)
