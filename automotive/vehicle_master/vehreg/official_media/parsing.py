"""Extract links and image candidates from OEM HTML without dependencies."""
from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlparse

from .models import ImageCandidate, SourceType


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


class AssetParser(HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.title = ""
        self.in_title = False
        self.images: list[dict] = []
        self.links: list[tuple[str, str]] = []
        self.link_url: str | None = None
        self.link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        values = {str(k).lower(): str(v or "") for k, v in attrs}
        tag = tag.lower()
        if tag == "title":
            self.in_title = True
        elif tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key in {"og:image", "twitter:image", "twitter:image:src"} and values.get("content"):
                self.images.append((values["content"], key, None, None, True))
        elif tag in {"img", "source"}:
            url = (values.get("data-src") or values.get("data-lazy-src")
                   or values.get("data-original") or values.get("src") or "")
            srcset = values.get("data-srcset") or values.get("srcset") or ""
            if srcset:
                url = _largest_srcset(srcset) or url
            if url and not url.startswith("data:"):
                self.images.append((url, values.get("alt") or values.get("title") or "",
                                    _integer(values.get("width")), _integer(values.get("height")), False))
        elif tag == "a" and values.get("href"):
            self.link_url = urljoin(self.page_url, values["href"])
            self.link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False
        elif tag.lower() == "a" and self.link_url:
            self.links.append((self.link_url, " ".join(self.link_text)))
            self.link_url = None
            self.link_text = []

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data
        if self.link_url and data.strip():
            self.link_text.append(data.strip())


def parse_page(html: str, page_url: str, source_type: SourceType):
    parser = AssetParser(page_url)
    parser.feed(html)
    seen: set[str] = set()
    images: list[ImageCandidate] = []
    for url, alt, width, height, is_og in parser.images:
        url = urljoin(page_url, url)
        if url in seen:
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
