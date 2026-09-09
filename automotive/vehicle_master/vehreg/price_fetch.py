"""P2 fetch layer for price intelligence.

This module fetches configured source targets and turns each HTTP representation
into immutable :class:`vehreg.pricefeed.SourceDocument` evidence.  It does not
extract prices, reconcile candidates, or write PriceLedger.

The important boundary is:

    SourceTarget -> HTTP fetch -> FetchResult(SourceDocument + raw body)

Target role travels beside the document so later phases can distinguish a
current model page from a promotion archive or launch article without changing
source authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import re
from typing import Callable, Mapping, Optional, Protocol
import urllib.error
import urllib.parse
import urllib.request

from .price_sources import SourceTarget, SourceTargetRegistry, TargetRole
from .pricefeed import SourceDocument, body_sketch, content_id


# Keep the token before '/' identical to tools.robots_check.AGENT.  Python's
# RobotFileParser compares that token, so auditing one agent and fetching as
# another would be a policy bug.
USER_AGENT = (
    "vehicle-market-master/tdr-price-intelligence-1.0 "
    "(+https://github.com/smgkikikiki-cloud/TDR)"
)


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FetchState:
    """Transport state only; never canonical price state."""

    target_id: str
    content_hash: str = ""
    first_seen_at: str = ""
    etag: str = ""
    last_modified: str = ""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    url: str
    headers: Mapping[str, str]
    body: bytes = b""


class Transport(Protocol):
    def fetch(self, url: str, *, headers: Mapping[str, str],
              timeout: float) -> HttpResponse:
        ...


class UrllibTransport:
    """Small stdlib HTTP transport with conditional-request support."""

    def fetch(self, url: str, *, headers: Mapping[str, str],
              timeout: float = 45.0) -> HttpResponse:
        request = urllib.request.Request(url, headers=dict(headers))
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(
                    status=int(getattr(response, "status", 200)),
                    url=response.geturl(),
                    headers={key.lower(): value for key, value in response.headers.items()},
                    body=response.read(),
                )
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return HttpResponse(
                    status=304,
                    url=exc.geturl() or url,
                    headers={key.lower(): value for key, value in exc.headers.items()},
                    body=b"",
                )
            raise FetchError(f"{url}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise FetchError(f"{url}: {exc}") from exc


@dataclass(frozen=True, slots=True)
class DiscoveredTarget:
    id: str
    source_id: str
    url: str
    role: TargetRole
    model_hint: str = ""

    def as_source_target(self) -> SourceTarget:
        return SourceTarget(
            id=self.id,
            source_id=self.source_id,
            url=self.url,
            role=self.role,
            model_hint=self.model_hint,
        )


@dataclass(frozen=True, slots=True)
class FetchResult:
    target_id: str
    target_role: TargetRole
    source_id: str
    document: Optional[SourceDocument]
    raw_body: bytes
    text: str
    state: FetchState
    not_modified: bool = False
    discovered_targets: tuple[DiscoveredTarget, ...] = ()


class _HTMLMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.in_title = False
        self.meta: dict[str, str] = {}
        self.links: list[str] = []
        self.jsonld_parts: list[str] = []
        self.in_jsonld = False
        self._jsonld_buffer: list[str] = []
        self.visible_parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        lower = tag.lower()
        if lower == "title":
            self.in_title = True
        elif lower == "meta":
            key = (values.get("property") or values.get("name")
                   or values.get("itemprop") or "").strip().lower()
            content = values.get("content", "").strip()
            if key and content:
                self.meta.setdefault(key, content)
        elif lower == "a" and values.get("href"):
            self.links.append(values["href"])
        elif lower == "script":
            script_type = values.get("type", "").lower()
            if "ld+json" in script_type:
                self.in_jsonld = True
                self._jsonld_buffer = []
            self._hidden_depth += 1
        elif lower == "style":
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower == "title":
            self.in_title = False
        elif lower == "script":
            if self.in_jsonld:
                self.jsonld_parts.append("".join(self._jsonld_buffer))
                self._jsonld_buffer = []
                self.in_jsonld = False
            self._hidden_depth = max(0, self._hidden_depth - 1)
        elif lower == "style":
            self._hidden_depth = max(0, self._hidden_depth - 1)

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if self.in_jsonld:
            self._jsonld_buffer.append(data)
        if self._hidden_depth == 0:
            clean = " ".join(data.split())
            if clean:
                self.visible_parts.append(clean)


@dataclass(frozen=True, slots=True)
class PageMetadata:
    title: str = ""
    published_at: Optional[str] = None
    modified_at: Optional[str] = None
    visible_text: str = ""
    links: tuple[str, ...] = ()


def _walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _first(mapping: Mapping[str, str], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key.lower(), "").strip()
        if value:
            return value
    return ""


def _iso_timestamp_or_none(raw: object) -> Optional[str]:
    """Keep explicit ISO timestamps; treat localised prose dates as unknown."""
    if not raw:
        return None
    text = str(raw).strip()
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return text


def parse_page_metadata(text: str) -> PageMetadata:
    parser = _HTMLMetadataParser()
    parser.feed(text)

    title = _first(parser.meta, "og:title", "twitter:title")
    published = _first(
        parser.meta,
        "article:published_time", "datepublished", "date", "publish_date",
    )
    modified = _first(
        parser.meta,
        "article:modified_time", "datemodified", "last-modified",
    )

    if not title:
        title = " ".join(" ".join(parser.title_parts).split())

    for raw in parser.jsonld_parts:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _walk_json(payload):
            if not title:
                title = str(node.get("headline") or node.get("name") or "").strip()
            if not published:
                published = str(node.get("datePublished") or "").strip()
            if not modified:
                modified = str(node.get("dateModified") or "").strip()
            if title and published and modified:
                break
        if title and published and modified:
            break

    return PageMetadata(
        title=title,
        published_at=_iso_timestamp_or_none(published),
        modified_at=_iso_timestamp_or_none(modified),
        visible_text="\n".join(parser.visible_parts),
        links=tuple(parser.links),
    )


def _charset(headers: Mapping[str, str]) -> str:
    content_type = headers.get("content-type", "")
    match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type, re.I)
    return match.group(1) if match else "utf-8"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _host(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")


def _normalise_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path,
                                   parts.query, ""))


class OfficialOEMAdapter:
    """Base class for deterministic first-party HTML fetch adapters."""

    adapter_id = "official_oem_html"
    allowed_hosts: frozenset[str] = frozenset()
    source_ids: frozenset[str] = frozenset()

    def __init__(self, *, transport: Optional[Transport] = None,
                 clock: Callable[[], str] = _now_iso) -> None:
        self.transport = transport or UrllibTransport()
        self.clock = clock

    def _host_allowed(self, url: str) -> bool:
        host = _host(url)
        return bool(host and host in self.allowed_hosts)

    def validate_target(self, target: SourceTarget) -> None:
        if target.source_id not in self.source_ids:
            raise FetchError(
                f"{self.adapter_id}: source {target.source_id!r} is not supported")
        if not target.enabled:
            raise FetchError(f"{target.id}: target is disabled")
        if not self._host_allowed(target.url):
            raise FetchError(f"{target.id}: host is outside adapter allow-list")

    def _headers(self, previous: Optional[FetchState]) -> dict[str, str]:
        headers = {
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
            "User-Agent": USER_AGENT,
        }
        if previous and previous.etag:
            headers["If-None-Match"] = previous.etag
        if previous and previous.last_modified:
            headers["If-Modified-Since"] = previous.last_modified
        return headers

    def fetch(self, target: SourceTarget, *, previous: Optional[FetchState] = None,
              timeout: float = 45.0,
              refetch_not_modified: bool = False) -> FetchResult:
        """Fetch one target.

        Conditional GET remains the cheap default.  Price reconciliation is
        different: a P5 replacement is allowed to confirm only after a *fresh*
        observation at/after 24h.  In that mode callers pass
        ``refetch_not_modified=True``.  A 304 is then followed by one
        unconditional GET so unchanged-but-still-present price text produces a
        new fetched_at observation instead of leaving the candidate pending
        forever.
        """
        self.validate_target(target)
        if previous and previous.target_id != target.id:
            raise FetchError(
                f"{target.id}: previous state belongs to {previous.target_id}")

        fetched_at = self.clock()
        response = self.transport.fetch(
            target.url, headers=self._headers(previous), timeout=timeout)

        if response.status == 304:
            if previous is None:
                raise FetchError(f"{target.id}: HTTP 304 without previous state")
            if not refetch_not_modified:
                return FetchResult(
                    target_id=target.id,
                    target_role=target.role,
                    source_id=target.source_id,
                    document=None,
                    raw_body=b"",
                    text="",
                    state=previous,
                    not_modified=True,
                )
            response = self.transport.fetch(
                target.url, headers=self._headers(None), timeout=timeout)
            if response.status == 304:
                raise FetchError(
                    f"{target.id}: unconditional revalidation unexpectedly returned HTTP 304")

        response_headers = {
            str(key).lower(): str(value) for key, value in response.headers.items()
        }
        if response.status != 200:
            raise FetchError(f"{target.url}: unexpected HTTP {response.status}")
        if not self._host_allowed(response.url):
            raise FetchError(
                f"{target.id}: redirect escaped adapter host allow-list: {response.url}")

        content_type = response_headers.get("content-type", "").lower()
        if content_type and "html" not in content_type:
            raise FetchError(f"{target.id}: expected HTML, got {content_type!r}")

        try:
            text = response.body.decode(_charset(response_headers), "replace")
        except LookupError as exc:
            raise FetchError(f"{target.id}: unknown response charset") from exc

        metadata = parse_page_metadata(text)
        digest = content_id(response.body)
        first_seen = (
            previous.first_seen_at
            if previous and previous.content_hash == digest and previous.first_seen_at
            else fetched_at
        )
        state = FetchState(
            target_id=target.id,
            content_hash=digest,
            first_seen_at=first_seen,
            etag=response_headers.get("etag", ""),
            last_modified=response_headers.get("last-modified", ""),
        )
        document = SourceDocument(
            document_id=digest,
            source_id=target.source_id,
            url=_normalise_url(response.url),
            content_hash=digest,
            published_at=metadata.published_at,
            modified_at=metadata.modified_at,
            first_seen_at=first_seen,
            fetched_at=fetched_at,
            title=metadata.title,
            body_sketch=body_sketch(metadata.visible_text),
        )
        problems = document.validate()
        if problems:
            raise FetchError("; ".join(problems))

        discovered = tuple(self.discover(target, metadata.links, response.url))
        return FetchResult(
            target_id=target.id,
            target_role=target.role,
            source_id=target.source_id,
            document=document,
            raw_body=response.body,
            text=text,
            state=state,
            discovered_targets=discovered,
        )

    def discover(self, target: SourceTarget, links: tuple[str, ...],
                 final_url: str) -> list[DiscoveredTarget]:
        return []


class OmodaJaecooThailandAdapter(OfficialOEMAdapter):
    adapter_id = "omoda_jaecoo_th"
    allowed_hosts = frozenset({"omodajaecoo.co.th", "www.omodajaecoo.co.th"})
    source_ids = frozenset({"official_jaecoo_th"})

    def discover(self, target: SourceTarget, links: tuple[str, ...],
                 final_url: str) -> list[DiscoveredTarget]:
        if target.role is not TargetRole.PROMOTION_INDEX:
            return []
        found: dict[str, DiscoveredTarget] = {}
        for href in links:
            absolute = _normalise_url(urllib.parse.urljoin(final_url, href))
            parts = urllib.parse.urlsplit(absolute)
            if parts.scheme != "https" or not self._host_allowed(absolute):
                continue
            path = parts.path.rstrip("/")
            if not path.startswith("/th/promotion/"):
                continue
            slug = path.rsplit("/", 1)[-1]
            if not slug:
                continue
            item = DiscoveredTarget(
                id=f"{target.id}:promotion:{slug}",
                source_id=target.source_id,
                url=absolute,
                role=TargetRole.PROMOTION,
            )
            found[absolute] = item
        return sorted(found.values(), key=lambda item: item.url)


ADAPTERS = {
    OmodaJaecooThailandAdapter.adapter_id: OmodaJaecooThailandAdapter,
}


def adapter_for(registry: SourceTargetRegistry, target: SourceTarget, *,
                transport: Optional[Transport] = None,
                clock: Callable[[], str] = _now_iso) -> OfficialOEMAdapter:
    adapter_id = registry.effective_adapter(target)
    cls = ADAPTERS.get(adapter_id)
    if cls is None:
        raise FetchError(f"{target.id}: no P2 fetch adapter for {adapter_id!r}")
    return cls(transport=transport, clock=clock)
