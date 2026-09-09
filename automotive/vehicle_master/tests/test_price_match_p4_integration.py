from __future__ import annotations

from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from vehreg.price_extract import extract_oem_price_claims
from vehreg.price_fetch import FetchResult, FetchState
from vehreg.price_match import TrimMatchState, match_trim_diagnostic
from vehreg.price_sources import SourceTarget, TargetRole
from vehreg.pricefeed import SourceDocument, content_id


def _blog_result() -> tuple[SourceTarget, FetchResult]:
    target = SourceTarget(
        id="p4-j5-guide",
        source_id="official_jaecoo_th",
        url="https://www.omodajaecoo.co.th/en/blog/jaecoo-5-ev-en",
        role=TargetRole.BLOG,
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
    </body></html>
    """
    raw = html.encode("utf-8")
    doc_id = content_id(raw)
    result = FetchResult(
        target_id=target.id,
        target_role=target.role,
        source_id=target.source_id,
        document=SourceDocument(
            document_id=doc_id,
            source_id=target.source_id,
            url=target.url,
            content_hash=doc_id,
            first_seen_at="2026-09-09T09:00:00+00:00",
            fetched_at="2026-09-09T09:00:00+00:00",
        ),
        raw_body=raw,
        text=html,
        state=FetchState(
            target_id=target.id,
            content_hash=doc_id,
            first_seen_at="2026-09-09T09:00:00+00:00",
        ),
    )
    return target, result


def test_p3_j5_claims_all_resolve_to_four_canonical_market_trims() -> None:
    catalog = Catalog.load(DATA_DIR, DEFAULT_YEAR)
    target, result = _blog_result()
    extracted = extract_oem_price_claims(target, result)

    matches = [match_trim_diagnostic(catalog, claim) for claim in extracted.claims]

    assert len(matches) == 8
    assert all(match.state is TrimMatchState.EXACT for match in matches)
    assert {match.trim_id for match in matches} == {
        "jaecoo.jaecoo_5_ev.j5.trim.long_range_dynamic_bev",
        "jaecoo.jaecoo_5_ev.j5.trim.long_range_max_bev",
        "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev",
        "jaecoo.jaecoo_5_ev.j5.trim.ultra_bev",
    }


def test_price_type_does_not_change_market_trim_identity() -> None:
    catalog = Catalog.load(DATA_DIR, DEFAULT_YEAR)
    target, result = _blog_result()
    extracted = extract_oem_price_claims(target, result)

    by_trim: dict[str, set[str]] = {}
    for claim in extracted.claims:
        match = match_trim_diagnostic(catalog, claim)
        by_trim.setdefault(claim.trim_raw, set()).add(match.trim_id or "")

    # LIST and CAMPAIGN claims for the same retail grade must resolve to the
    # same MarketTrim. Price type belongs to the price stream, not identity.
    assert all(len(ids) == 1 and "" not in ids for ids in by_trim.values())
