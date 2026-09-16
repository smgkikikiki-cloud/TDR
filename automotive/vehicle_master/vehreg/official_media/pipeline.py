"""Official-site crawler, asset downloader and manifest writer."""
from __future__ import annotations

from dataclasses import asdict, replace
from functools import lru_cache
import hashlib
import json
import mimetypes
from pathlib import Path
import re
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .adapters import get_page_hints, get_source
from .models import ImageCandidate, ImageSlot, MediaAsset, ReviewStatus, VehicleIdentity
from .parsing import parse_page, source_type_for
from .scoring import link_score, score_candidate

# Some OEM CDNs return an empty application shell to non-browser user agents.
# Keep a normal browser signature while retaining the TDR identifier.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36 "
    "TDR-Official-Media/1.0"
)
_NON_PAGE_SUFFIXES = {
    ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".avif", ".svg", ".gif",
    ".zip", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".mp4",
    ".mov", ".avi", ".mp3", ".wav",
}


def _safe_url(url: str) -> str:
    """Remove control characters and percent-encode literal spaces."""
    clean = "".join(ch for ch in str(url).strip() if ord(ch) >= 32 and ord(ch) != 127)
    return clean.replace(" ", "%20")


def _crawlable_page(url: str) -> bool:
    parsed = urlparse(_safe_url(url))
    return parsed.scheme in {"http", "https"} and Path(parsed.path).suffix.casefold() not in _NON_PAGE_SUFFIXES


def fetch_bytes(url: str, timeout: int = 20) -> tuple[bytes, str]:
    request = Request(_safe_url(url), headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": "th-TH,th;q=0.9,en;q=0.8",
    })
    with urlopen(request, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", "")


@lru_cache(maxsize=256)
def fetch_text(url: str, timeout: int = 20) -> str:
    body, content_type = fetch_bytes(url, timeout)
    media_type = content_type.split(";", 1)[0].strip().casefold()
    if media_type and not (media_type.startswith("text/") or media_type in {"application/json", "application/xhtml+xml"}):
        return ""
    match = re.search(r"charset=([\w.-]+)", content_type, re.I)
    charset = match.group(1) if match else "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def discover_pages(identity: VehicleIdentity, max_pages: int = 8) -> list[str]:
    source = get_source(identity.brand_id)
    if not source:
        return []
    chosen: list[str] = []
    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()
    starts = (*get_page_hints(identity.generation_id), *source.seed_urls)
    for raw_seed in starts:
        seed = _safe_url(raw_seed)
        if seed in seen or not _crawlable_page(seed):
            continue
        if not source.host_allowed(urlparse(seed).hostname or ""):
            continue
        seen.add(seed)
        try:
            html = fetch_text(seed)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            continue
        chosen.append(seed)
        if not html:
            continue
        _, links, _ = parse_page(html, seed, source_type_for(seed))
        for raw_url, text in links:
            url = _safe_url(raw_url)
            if not _crawlable_page(url):
                continue
            score = link_score(url, text, identity, source)
            if score > 0 and url not in seen:
                ranked.append((score, url))
                seen.add(url)
    ranked.sort(key=lambda item: (-item[0], item[1]))
    for _, url in ranked:
        if len(chosen) >= max_pages:
            break
        chosen.append(url)
    return chosen[:max_pages]


def collect_candidates(identity: VehicleIdentity, max_pages: int = 8) -> list[ImageCandidate]:
    source = get_source(identity.brand_id)
    if not source:
        return []
    best: dict[str, ImageCandidate] = {}
    for page in discover_pages(identity, max_pages=max_pages):
        try:
            html = fetch_text(page)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            continue
        if not html:
            continue
        images, _, _ = parse_page(html, page, source_type_for(page))
        for image in images:
            image.image_url = _safe_url(image.image_url)
            image = score_candidate(image, identity, source)
            prior = best.get(image.image_url)
            if prior is None or image.score > prior.score:
                best[image.image_url] = image
    return sorted(best.values(), key=lambda item: (-item.score, item.slot.value, item.image_url))


def _extension(url: str, content_type: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".avif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip().lower()) or ".bin"
    return ".jpg" if guessed == ".jpe" else guessed


class ContentAddressedStore:
    """Local SHA cache; a production object-store sink can mirror these paths."""
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def put(self, identity: VehicleIdentity, candidate: ImageCandidate) -> tuple[str, str]:
        body, content_type = fetch_bytes(candidate.image_url)
        digest = hashlib.sha256(body).hexdigest()
        relative = (Path(identity.brand_id) / identity.visual_key.replace(".", "/") /
                    candidate.slot.value / f"{digest}{_extension(candidate.image_url, content_type)}")
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(body)
        return digest, relative.as_posix()


def select_canonical(candidates: Iterable[ImageCandidate]) -> list[ImageCandidate]:
    best: dict[str, ImageCandidate] = {}
    unknown: list[ImageCandidate] = []
    for candidate in candidates:
        if candidate.status is ReviewStatus.REJECTED:
            continue
        if candidate.slot.value == "unknown":
            unknown.append(candidate)
            continue
        prior = best.get(candidate.slot.value)
        if prior is None or candidate.score > prior.score:
            best[candidate.slot.value] = candidate
    if "hero" not in best:
        for preferred in ("front_3q", "side", "rear_3q"):
            if preferred in best:
                best["hero"] = replace(best[preferred], slot=ImageSlot.HERO)
                break
    return list(best.values()) + unknown[:3]


def ingest(identity: VehicleIdentity, store: ContentAddressedStore, max_pages: int = 8):
    source = get_source(identity.brand_id)
    if source is None:
        return [], [{"vehicle_id": identity.generation_id, "reason": "unsupported_brand"}]
    assets: list[MediaAsset] = []
    review: list[dict] = []
    for candidate in select_canonical(collect_candidates(identity, max_pages=max_pages)):
        if candidate.status is ReviewStatus.REVIEW or candidate.slot.value == "unknown":
            review.append({"vehicle_id": identity.generation_id, "visual_key": identity.visual_key,
                           **asdict(candidate), "status": candidate.status.value})
        try:
            digest, storage_path = store.put(identity, candidate)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            review.append({"vehicle_id": identity.generation_id, "image_url": candidate.image_url,
                           "reason": f"download_failed:{type(exc).__name__}"})
            continue
        assets.append(MediaAsset(
            vehicle_id=identity.generation_id, visual_key=identity.visual_key,
            source_url=candidate.source_page, source_type=candidate.source_type.value,
            source_domain=urlparse(candidate.source_page).hostname or "",
            image_url_original=candidate.image_url, storage_path=storage_path,
            image_type=candidate.slot.value, market=identity.market,
            model_year=identity.model_year, confidence=candidate.score, sha256=digest,
            width=candidate.width, height=candidate.height, status=candidate.status.value,
        ))
    return assets, review


def write_jsonl(path: Path | str, rows: Iterable[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str, sort_keys=True) + "\n")
