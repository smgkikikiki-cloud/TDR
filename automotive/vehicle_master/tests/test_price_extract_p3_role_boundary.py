from vehreg.price_extract import extract_oem_price_claims
from vehreg.price_fetch import FetchResult, FetchState
from vehreg.price_sources import SourceTarget, TargetRole
from vehreg.pricefeed import SourceDocument, content_id


def _fetch(target: SourceTarget, html: str) -> FetchResult:
    raw = html.encode("utf-8")
    digest = content_id(raw)
    return FetchResult(
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


def test_generic_blog_without_j5_scope_does_not_invent_j5_identity() -> None:
    target = SourceTarget(
        id="generic_blog",
        source_id="official_jaecoo_th",
        url="https://www.omodajaecoo.co.th/th/blog/something-else",
        role=TargetRole.BLOG,
    )
    html = "<html><body><p>MAX+ 699,000 (promo 579,000*)</p></body></html>"

    extracted = extract_oem_price_claims(target, _fetch(target, html))

    # A naked grade name is not enough to turn an arbitrary OEM blog into J5.
    assert extracted.claims == ()
    assert extracted.warnings
