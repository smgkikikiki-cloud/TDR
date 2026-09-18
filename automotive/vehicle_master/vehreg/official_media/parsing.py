"""Extract links and image candidates from OEM HTML without dependencies."""
from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlparse

from .models import ImageCandidate, SourceType

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
# Some first-party OEM image services use CGI/query URLs without a file suffix.
# Keep this deliberately tiny: these hosts are known BMW media services and the
# source page itself still has to pass the OEM allowlist/scoring gates.
_IMAGE_SERVICE_HOSTS = {"prod.cosy.bmw.cloud", "bmw.scene7.com"}
_EMBEDDED_IMAGE_RE = re.compile(
    r"(?P<url>(?:https?:)?(?:\\?/|/)[^\"'<>\s]{2,}?\.(?:jpe?g|png|webp|avif)(?:\\?[?#][^\"'<>\s]*)?)",
    re.I,
)
_CSS_URL_RE = re.compile(r"url\(\s*['\"]?(?P<url>[^)'\"\s]+)['\"]?\s*\)", re.I)
_BACKGROUND_ATTRS = (
    "data-background", "data-bg", "data-lazy-background", "data-background-image",
)


def _integer(value: str | None) -> int | None:
    match = re.search(r"\d+", value or "")
    return int(match.group()) if match else None


def _largest_srcset(value: str) -> str:
    choices: list[tuple[int, str]] = []
    for item in value.split(","):
        parts = item.strip().split()
        if not parts:
            continue
        weight = 1
        if len(parts) > 1:
            match = re.match(r"(\d+)", parts[-1])
            if match:
                weight = int(match.group(1))
        choices.append((weight, parts[0]))
    return max(choices, default=(0, ""))[1]


def _looks_like_image(url: str, mime: str = "") -> bool:
    if mime:
        return mime.casefold().startswith("image/")
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    if host in _IMAGE_SERVICE_HOSTS and parsed.scheme in {"http", "https"} and parsed.path:
        return True
    return any(parsed.path.casefold().endswith(suffix) for suffix in _IMAGE_SUFFIXES)


def _decode_embedded_url(value: str) -> str:
    value = unescape(value)
    value = value.replace("\\/", "/")
    value = value.replace("\\u002F", "/").replace("\\u002f", "/")
    value = value.replace("\\u0026", "&").replace("\\u003D", "=")

    # MG Thailand serializes optimized image sources as e.g.
    # ``format=webp/static/car-banner/...`` or
    # ``format=webp/https:/cdn.example/image.png``. These strings are image
    # provider directives, not paths relative to the model page. urljoin() on
    # the raw value produced /th/cars/format=webp/... and guaranteed a 404.
    # Strip only the known format directive, then restore the real root/URL.
    value = re.sub(r"^format=(?:webp|avif|jpe?g|png)/", "", value, flags=re.I)
    if re.match(r"^https?:/[^/]", value, flags=re.I):
        value = re.sub(r"^(https?):/", r"\1://", value, count=1, flags=re.I)
    if value.startswith("static/"):
        value = "/" + value

    if value.startswith("//"):
        return "https:" + value
    return value


class AssetParser(HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.title = ""
        self.in_title = False
        self.images: list[tuple[str, str, int | None, int | None, bool]] = []
        self.links: list[tuple[str, str]] = []
        self.link_url: str | None = None
        self.link_text: list[str] = []
        self.link_image_indexes: list[int] = []
        self.script_chunks: list[str] = []
        self.in_script = False

    def _append_image(self, row: tuple[str, str, int | None, int | None, bool]) -> None:
        self.images.append(row)
        if self.link_url:
            self.link_image_indexes.append(len(self.images) - 1)

    def _append_background_images(self, values: dict[str, str]) -> None:
        context = values.get("aria-label") or values.get("title") or values.get("class") or "background-image"
        for attr in _BACKGROUND_ATTRS:
            url = values.get(attr, "").strip()
            if url and not url.startswith("data:"):
                self._append_image((url, context, None, None, False))
        style = values.get("style", "")
        for match in _CSS_URL_RE.finditer(style):
            url = match.group("url").strip()
            if url and not url.startswith("data:"):
                self._append_image((url, context, None, None, False))

    def handle_starttag(self, tag: str, attrs) -> None:
        values = {str(k).lower(): str(v or "") for k, v in attrs}
        tag = tag.lower()
        # Legacy OEM/Adobe pages often render vehicle galleries on div/span
        # backgrounds rather than img/source tags. Treat those as candidates;
        # normal image suffix, OEM provenance and identity scoring still apply.
        self._append_background_images(values)
        if tag == "title":
            self.in_title = True
        elif tag == "script":
            self.in_script = True
        elif tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key in {"og:image", "twitter:image", "twitter:image:src"} and values.get("content"):
                self._append_image((values["content"], key, None, None, True))
        elif tag == "a" and values.get("href"):
            self.link_url = urljoin(self.page_url, values["href"])
            self.link_text = []
            self.link_image_indexes = []
        elif tag == "img":
            url = (values.get("data-src") or values.get("data-lazy-src")
                   or values.get("data-original") or values.get("src") or "")
            srcset = values.get("data-srcset") or values.get("srcset") or ""
            if srcset:
                url = _largest_srcset(srcset) or url
            if url and not url.startswith("data:"):
                self._append_image((url, values.get("alt") or values.get("title") or "",
                                    _integer(values.get("width")), _integer(values.get("height")), False))
        elif tag == "source":
            url = values.get("src") or ""
            srcset = values.get("srcset") or ""
            if srcset:
                url = _largest_srcset(srcset) or url
            if url and not url.startswith("data:") and _looks_like_image(url, values.get("type", "")):
                self._append_image((url, values.get("alt") or values.get("title") or "",
                                    _integer(values.get("width")), _integer(values.get("height")), False))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self.in_title = False
        elif tag == "script":
            self.in_script = False
        elif tag == "a" and self.link_url:
            text = " ".join(self.link_text).strip()
            self.links.append((self.link_url, text))
            if text:
                for index in self.link_image_indexes:
                    url, alt, width, height, is_og = self.images[index]
                    context = f"{alt} model-card {text} {self.link_url}".strip()
                    self.images[index] = (url, context, width, height, is_og)
            self.link_url = None
            self.link_text = []
            self.link_image_indexes = []

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data
        if self.in_script and data:
            self.script_chunks.append(data)
        if self.link_url and data.strip():
            self.link_text.append(data.strip())


def parse_page(html: str, page_url: str, source_type: SourceType):
    parser = AssetParser(page_url)
    parser.feed(html)

    embedded = "\n".join(parser.script_chunks)
    for match in _EMBEDDED_IMAGE_RE.finditer(embedded):
        url = _decode_embedded_url(match.group("url"))
        if _looks_like_image(url):
            parser.images.append((url, "embedded-page-data", None, None, False))

    seen: set[str] = set()
    images: list[ImageCandidate] = []
    for url, alt, width, height, is_og in parser.images:
        url = urljoin(page_url, _decode_embedded_url(url))
        if url in seen or not _looks_like_image(url):
            continue
        seen.add(url)
        images.append(ImageCandidate(
            source_page=page_url, source_type=source_type, image_url=url,
            page_title=parser.title.strip(), alt=alt, width=width,
            height=height, is_og_image=is_og,
        ))
    return images, parser.links, parser.title.strip()


def source_type_for(url: str) -> SourceType:
    path = urlparse(url).path.casefold()
    return SourceType.PRESS_RELEASE if any(x in path for x in ("/news", "/press", "/media", "/article")) else SourceType.OFFICIAL_SITE
