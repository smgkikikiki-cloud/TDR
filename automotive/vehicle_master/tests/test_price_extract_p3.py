from __future__ import annotations

from vehreg.catalog import DATA_DIR, DEFAULT_YEAR
from vehreg.price_extract import extract_oem_price_claims
from vehreg.price_fetch import FetchResult, FetchState
from vehreg.price_sources import SourceTarget, TargetRole, load_source_target_registry
from vehreg.pricefeed import SourceDocument, content_id
from vehreg.pricing import PriceType


def _result(html: str, *, target: SourceTarget) -> FetchResult:
    raw = html.encode("utf-8")
    doc_id = content_id(raw)
    document = SourceDocument(
        document_id=doc_id,
        source_id=target.source_id,
        url=target.url,
        content_hash=doc_id,
        first_seen_at="2026-09-09T09:00:00+00:00",
        fetched_at="2026-09-09T09:00:00+00:00",
    )
    return FetchResult(
        target_id=target.id,
        target_role=target.role,
        source_id=target.source_id,
        document=document,
        raw_body=raw,
        text=html,
        state=FetchState(
            target_id=target.id,
            content_hash=doc_id,
            first_seen_at="2026-09-09T09:00:00+00:00",
        ),
    )


def _target(role: TargetRole, *, target_id: str = "pilot",
            model_hint: str = "") -> SourceTarget:
    return SourceTarget(
        id=target_id,
        source_id="official_jaecoo_th",
        url="https://www.omodajaecoo.co.th/th",
        role=role,
        model_hint=model_hint,
    )


def _claim_map(claims):
    return {(c.trim_raw, c.price_type, c.amount_thb): c for c in claims}


def test_live_registry_adds_multi_model_home_price_cards_and_english_guide() -> None:
    registry = load_source_target_registry(DATA_DIR, DEFAULT_YEAR)

    home = registry.targets["jaecoo_th_home_price_cards"]
    english = registry.targets["jaecoo_en_j5_buyer_guide_2026_09_02"]
    assert home.role is TargetRole.PRICE_LIST
    assert home.model_hint == ""
    assert english.role is TargetRole.BLOG
    assert english.model_hint == "jaecoo.jaecoo_5_ev"
    assert home.source_id == english.source_id == "official_jaecoo_th"


def test_homepage_cards_classify_list_and_estimated_without_other_models() -> None:
    target = _target(TargetRole.PRICE_LIST)
    html = """
    <html><body>
      <section>JAECOO 5 EV ULTRA NEW JAECOO 5 EV
        Estimated Price THB 809,000 Test drive More information
      </section>
      <section>OMODA C5 EV MAX+ Price 709,000 THB</section>
      <section>JAECOO 5 EV MAX+ JAECOO 5 EV
        Price THB 699,000 Test drive More information
      </section>
      <section>JAECOO 6 EV 2WD MAX Price 859,000</section>
    </body></html>
    """

    extracted = extract_oem_price_claims(target, _result(html, target=target))
    rows = _claim_map(extracted.claims)

    assert extracted.warnings == ()
    assert ("ULTRA", PriceType.ESTIMATED_PRICE, 809000) in rows
    assert ("MAX+", PriceType.LIST_PRICE, 699000) in rows
    assert len(rows) == 2


def test_english_buyer_guide_yields_four_list_and_four_campaign_claims() -> None:
    target = _target(
        TargetRole.BLOG,
        model_hint="jaecoo.jaecoo_5_ev",
    )
    html = """
    <html><body>
    <h2>JAECOO 5 EV Variants and Price in Thailand</h2>
    <table>
      <tr><td>LONG RANGE DYNAMIC</td><td>629,000 (promo 589,000*)</td></tr>
      <tr><td>LONG RANGE MAX</td><td>679,000 (promo 639,000*)</td></tr>
      <tr><td>MAX+</td><td>699,000 (promo 579,000*)</td></tr>
      <tr><td>ULTRA</td><td>789,000 (Special Price 669,000*)</td></tr>
    </table>
    <h2>Installment Plans</h2>
    <p>Down payment 69,900. Monthly installment 12,682 THB.</p>
    </body></html>
    """

    extracted = extract_oem_price_claims(target, _result(html, target=target))
    rows = _claim_map(extracted.claims)

    assert len(extracted.claims) == 8
    assert ("LONG RANGE DYNAMIC", PriceType.LIST_PRICE, 629000) in rows
    assert ("LONG RANGE DYNAMIC", PriceType.CAMPAIGN_PRICE, 589000) in rows
    assert ("LONG RANGE MAX", PriceType.LIST_PRICE, 679000) in rows
    assert ("LONG RANGE MAX", PriceType.CAMPAIGN_PRICE, 639000) in rows
    assert ("MAX+", PriceType.LIST_PRICE, 699000) in rows
    assert ("MAX+", PriceType.CAMPAIGN_PRICE, 579000) in rows
    assert ("ULTRA", PriceType.LIST_PRICE, 789000) in rows
    assert ("ULTRA", PriceType.CAMPAIGN_PRICE, 669000) in rows
    assert all(c.effective_to is None for c in extracted.claims)
    assert 69900 not in {c.amount_thb for c in extracted.claims}
    assert 12682 not in {c.amount_thb for c in extracted.claims}


def test_open_ended_more_rain_promo_keeps_no_invented_expiry() -> None:
    target = _target(TargetRole.PROMOTION)
    html = """
    <html><body>
    <h1>MORE RAIN, MORE GAIN</h1>
    <p>ดาวน์เริ่มต้นเพียง 29,950 บาท สำหรับ JAECOO 5 EV MAX+</p>
    <p>JAECOO 5 EV MAX+</p>
    <p>ราคาพิเศษ 599,000 บาท* (จากราคา 699,000 บาท)</p>
    <p>JAECOO 5 EV ULTRA</p>
    <p>ราคาพิเศษ 699,000 บาท* (จากราคาคาดการณ์ 809,000 บาท)</p>
    </body></html>
    """

    extracted = extract_oem_price_claims(target, _result(html, target=target))
    rows = _claim_map(extracted.claims)

    max_campaign = rows[("MAX+", PriceType.CAMPAIGN_PRICE, 599000)]
    ultra_campaign = rows[("ULTRA", PriceType.CAMPAIGN_PRICE, 699000)]
    assert max_campaign.reference_price_thb == 699000
    assert ultra_campaign.reference_price_thb == 809000
    assert max_campaign.effective_from is None
    assert max_campaign.effective_to is None
    assert ultra_campaign.effective_from is None
    assert ultra_campaign.effective_to is None
    assert ("MAX+", PriceType.LIST_PRICE, 699000) in rows
    assert ("ULTRA", PriceType.ESTIMATED_PRICE, 809000) in rows
    assert 29950 not in {c.amount_thb for c in extracted.claims}


def test_big_motor_sale_literal_window_applies_only_to_campaign_claims() -> None:
    target = _target(TargetRole.PROMOTION)
    html = """
    <html><body>
    <h1>BIG MOTOR SALE 2026</h1>
    <p>เฉพาะภายในงาน 21–30 สิงหาคม 2569 | ไบเทค บางนา</p>
    <p>JAECOO 5 EV MAX+</p>
    <p>ราคาพิเศษ 579,000 บาท* (จากราคา 699,000 บาท)</p>
    <p>JAECOO 5 EV ULTRA</p>
    <p>ราคาพิเศษ 669,000 บาท* (จากราคา 789,000 บาท)</p>
    </body></html>
    """

    extracted = extract_oem_price_claims(target, _result(html, target=target))
    rows = _claim_map(extracted.claims)

    for key in [
        ("MAX+", PriceType.CAMPAIGN_PRICE, 579000),
        ("ULTRA", PriceType.CAMPAIGN_PRICE, 669000),
    ]:
        assert rows[key].effective_from == "2026-08-21"
        assert rows[key].effective_to == "2026-08-30"
    assert rows[("MAX+", PriceType.LIST_PRICE, 699000)].effective_to is None
    assert rows[("ULTRA", PriceType.LIST_PRICE, 789000)].effective_to is None


def test_english_explicit_campaign_window_is_also_literal() -> None:
    target = _target(TargetRole.PROMOTION)
    html = """
    <html><body>
      <p>21–30 August 2026 | BITEC Bangna</p>
      <p>JAECOO 5 EV MAX+</p>
      <p>Special Price THB 579,000 (from THB 699,000)</p>
    </body></html>
    """

    extracted = extract_oem_price_claims(target, _result(html, target=target))
    campaign = next(c for c in extracted.claims
                    if c.price_type is PriceType.CAMPAIGN_PRICE)
    assert campaign.effective_from == "2026-08-21"
    assert campaign.effective_to == "2026-08-30"


def test_claim_ids_are_stable_for_same_document_and_semantics() -> None:
    target = _target(TargetRole.PRICE_LIST)
    html = "<html><body>JAECOO 5 EV MAX+ Price THB 699,000 JAECOO 6 EV</body></html>"
    result = _result(html, target=target)

    first = extract_oem_price_claims(target, result)
    second = extract_oem_price_claims(target, result)

    assert [c.claim_id for c in first.claims] == [c.claim_id for c in second.claims]


def test_current_model_page_with_no_price_is_not_an_extraction_failure() -> None:
    target = _target(
        TargetRole.CURRENT_MODEL_PAGE,
        model_hint="jaecoo.jaecoo_5_ev",
    )
    html = "<html><body><h1>JAECOO 5 EV</h1><p>Pet friendly design</p></body></html>"

    extracted = extract_oem_price_claims(target, _result(html, target=target))
    assert extracted.claims == ()
    assert extracted.warnings == ()
