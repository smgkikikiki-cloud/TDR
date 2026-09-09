from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from vehreg.catalog import DATA_DIR, DEFAULT_YEAR
from vehreg.price_fetch import (
    FetchError,
    FetchState,
    HttpResponse,
    OmodaJaecooThailandAdapter,
    adapter_for,
    parse_page_metadata,
)
from vehreg.price_sources import SourceTarget, TargetRole, load_source_target_registry
from vehreg.pricefeed import content_id


HTML = b"""<!doctype html>
<html><head>
<title>fallback title</title>
<meta property="og:title" content="JAECOO 5 EV Thailand">
<meta property="article:published_time" content="2026-09-02T09:00:00+07:00">
<script type="application/ld+json">
{"@type":"Article","dateModified":"2026-09-08T10:30:00+07:00"}
</script>
</head><body>
<h1>JAECOO 5 EV</h1><p>ราคาและรายละเอียดรถ</p>
<a href="/th/promotion/big-motor-sales">Big Motor Sale</a>
<a href="https://www.omodajaecoo.co.th/th/promotion/big-motor-sales#terms">duplicate</a>
<a href="/th/blog/jaecoo-5-ev">blog</a>
<a href="https://example.com/th/promotion/evil">external</a>
</body></html>"""


@dataclass
class FakeTransport:
    responses: list[HttpResponse]

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def fetch(self, url: str, *, headers, timeout: float) -> HttpResponse:
        self.calls.append((url, dict(headers), timeout))
        if not self.responses:
            raise AssertionError("unexpected fetch")
        return self.responses.pop(0)


def _target(role: TargetRole = TargetRole.CURRENT_MODEL_PAGE) -> SourceTarget:
    return SourceTarget(
        id="jaecoo_test",
        source_id="official_jaecoo_th",
        url="https://www.omodajaecoo.co.th/th/model/jaecoo-5-ev",
        role=role,
        model_hint="jaecoo.jaecoo_5_ev",
    )


def _response(body: bytes = HTML, *, status: int = 200,
              url: str = "https://www.omodajaecoo.co.th/th/model/jaecoo-5-ev",
              headers: dict[str, str] | None = None) -> HttpResponse:
    return HttpResponse(
        status=status,
        url=url,
        headers=headers or {
            "content-type": "text/html; charset=utf-8",
            "etag": '"abc"',
            "last-modified": "Wed, 09 Sep 2026 07:00:00 GMT",
        },
        body=body,
    )


def test_live_registry_routes_jaecoo_to_p2_adapter() -> None:
    registry = load_source_target_registry(DATA_DIR, DEFAULT_YEAR)
    target = registry.targets["jaecoo_th_j5_model"]

    assert registry.effective_adapter(target) == "omoda_jaecoo_th"
    assert isinstance(adapter_for(registry, target), OmodaJaecooThailandAdapter)


def test_fetch_builds_immutable_source_document_and_keeps_role_outside_it() -> None:
    transport = FakeTransport([_response()])
    adapter = OmodaJaecooThailandAdapter(
        transport=transport,
        clock=lambda: "2026-09-09T08:00:00+00:00",
    )

    result = adapter.fetch(_target())

    assert result.target_role is TargetRole.CURRENT_MODEL_PAGE
    assert result.source_id == "official_jaecoo_th"
    assert result.document is not None
    assert result.document.document_id == content_id(HTML)
    assert result.document.content_hash == content_id(HTML)
    assert result.document.source_id == "official_jaecoo_th"
    assert result.document.title == "JAECOO 5 EV Thailand"
    assert result.document.published_at == "2026-09-02T09:00:00+07:00"
    assert result.document.modified_at == "2026-09-08T10:30:00+07:00"
    assert result.document.first_seen_at == "2026-09-09T08:00:00+00:00"
    assert result.document.fetched_at == "2026-09-09T08:00:00+00:00"
    assert result.raw_body == HTML
    assert "JAECOO 5 EV" in result.text
    assert result.state.etag == '"abc"'
    assert result.state.last_modified == "Wed, 09 Sep 2026 07:00:00 GMT"


def test_same_content_preserves_first_seen_and_sends_conditional_headers() -> None:
    first = "2026-09-09T01:00:00+00:00"
    previous = FetchState(
        target_id="jaecoo_test",
        content_hash=content_id(HTML),
        first_seen_at=first,
        etag='"old-etag"',
        last_modified="Tue, 08 Sep 2026 07:00:00 GMT",
    )
    transport = FakeTransport([_response(headers={
        "content-type": "text/html",
        "etag": '"new-etag"',
        "last-modified": "Wed, 09 Sep 2026 07:00:00 GMT",
    })])
    adapter = OmodaJaecooThailandAdapter(
        transport=transport,
        clock=lambda: "2026-09-09T08:00:00+00:00",
    )

    result = adapter.fetch(_target(), previous=previous)

    assert result.document is not None
    assert result.document.first_seen_at == first
    assert result.state.first_seen_at == first
    headers = transport.calls[0][1]
    assert headers["If-None-Match"] == '"old-etag"'
    assert headers["If-Modified-Since"] == "Tue, 08 Sep 2026 07:00:00 GMT"


def test_changed_content_gets_new_identity_and_new_first_seen() -> None:
    previous = FetchState(
        target_id="jaecoo_test",
        content_hash=content_id(HTML),
        first_seen_at="2026-09-08T08:00:00+00:00",
    )
    changed = HTML.replace(b"699,000", b"719,000") + b"<!--changed-->"
    transport = FakeTransport([_response(changed)])
    adapter = OmodaJaecooThailandAdapter(
        transport=transport,
        clock=lambda: "2026-09-09T08:00:00+00:00",
    )

    result = adapter.fetch(_target(), previous=previous)

    assert result.document is not None
    assert result.document.document_id == content_id(changed)
    assert result.document.document_id != previous.content_hash
    assert result.document.first_seen_at == "2026-09-09T08:00:00+00:00"


def test_http_304_returns_no_new_document() -> None:
    previous = FetchState(
        target_id="jaecoo_test",
        content_hash="sha256:" + "a" * 64,
        first_seen_at="2026-09-08T08:00:00+00:00",
        etag='"abc"',
    )
    transport = FakeTransport([HttpResponse(
        status=304,
        url=_target().url,
        headers={},
    )])
    adapter = OmodaJaecooThailandAdapter(transport=transport)

    result = adapter.fetch(_target(), previous=previous)

    assert result.not_modified is True
    assert result.document is None
    assert result.raw_body == b""
    assert result.state == previous


def test_promotion_index_discovers_only_same_site_promotion_details() -> None:
    transport = FakeTransport([_response(
        url="https://www.omodajaecoo.co.th/th/promotion",
    )])
    adapter = OmodaJaecooThailandAdapter(
        transport=transport,
        clock=lambda: "2026-09-09T08:00:00+00:00",
    )
    target = SourceTarget(
        id="jaecoo_promotions",
        source_id="official_jaecoo_th",
        url="https://www.omodajaecoo.co.th/th/promotion",
        role=TargetRole.PROMOTION_INDEX,
    )

    result = adapter.fetch(target)

    assert len(result.discovered_targets) == 1
    discovered = result.discovered_targets[0]
    assert discovered.url == "https://www.omodajaecoo.co.th/th/promotion/big-motor-sales"
    assert discovered.role is TargetRole.PROMOTION
    assert discovered.source_id == "official_jaecoo_th"
    assert discovered.as_source_target().role is TargetRole.PROMOTION


def test_redirect_cannot_escape_oem_domain() -> None:
    transport = FakeTransport([_response(url="https://evil.example/prices")])
    adapter = OmodaJaecooThailandAdapter(transport=transport)

    with pytest.raises(FetchError, match="redirect escaped"):
        adapter.fetch(_target())


def test_wrong_source_and_previous_state_are_rejected() -> None:
    adapter = OmodaJaecooThailandAdapter(transport=FakeTransport([]))
    wrong_source = SourceTarget(
        id="wrong",
        source_id="official_oem",
        url="https://www.omodajaecoo.co.th/th/model/jaecoo-5-ev",
        role=TargetRole.CURRENT_MODEL_PAGE,
    )
    with pytest.raises(FetchError, match="not supported"):
        adapter.fetch(wrong_source)

    with pytest.raises(FetchError, match="previous state belongs"):
        adapter.fetch(_target(), previous=FetchState(target_id="other"))


def test_metadata_parser_falls_back_to_jsonld() -> None:
    page = """
    <html><head><script type="application/ld+json">
    {"@type":"Article","headline":"Pilot page",
     "datePublished":"2026-09-02T00:00:00+07:00",
     "dateModified":"2026-09-03T00:00:00+07:00"}
    </script></head><body>Hello</body></html>
    """
    metadata = parse_page_metadata(page)

    assert metadata.title == "Pilot page"
    assert metadata.published_at == "2026-09-02T00:00:00+07:00"
    assert metadata.modified_at == "2026-09-03T00:00:00+07:00"
    assert metadata.visible_text == "Hello"
