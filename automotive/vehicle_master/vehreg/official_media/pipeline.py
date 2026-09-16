"""Official-site crawler, asset downloader and manifest writer."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import mimetypes
from pathlib import Path
import re
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .adapters import get_source
from .models import ImageCandidate, MediaAsset, ReviewStatus, VehicleIdentity
from .parsing import parse_page, source_type_for
from .scoring import link_score, score_candidate

USER_AGENT = "TDR-Official-Media/1.0 (+vehicle research; official sources only)"


def fetch_bytes(url: str, timeout: int = 20) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,image/*,*/*;q=0.8"})
    with urlopen(request, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", "")


def fetch_text(url: str, timeout: int = 20) -> str:
    body, content_type = fetch_bytes(url, timeout)
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
    for seed in source.seed_urls:
        if seed in seen:
            continue
        seen.add(seed)
        try:
            html = fetch_text(seed)
        except (HTTPError, URLError, TimeoutError, OSError):
            continue
        chosen.append(seed)
        _, links, _ = parse_page(html, seed, source_type_for(seed))
        for url, text in links:
            score = link_score(url, text, identity, source)
            if score > 0 and url not in seen:
                ranked.append((score, url))
                seen.add(url)
    ranked.sort(key=lambda item: (-item[0], item[1]))
    for _, url in ranked:
        if len(chosen) >= max_pages:
            break
        chosen.append(url)
    return chosen


def collect_candidates(identity: VehicleIdentity, max_pages: int = 8) -> list[ImageCandidate]:
    source = get_source(identity.brand_id)
    if not source:
        return []
    best: dict[str, ImageCandidate] = {}
    for page in discover_pages(identity, max_pages=max_pages):
        try:
            html = fetch_text(page)
        except (HTTPError, URLError, TimeoutError, OSError):
            continue
        images, _, _ = parse_page(html, page, source_type_for(page))
        for image in images:
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
                best["hero"] = best[preferred]
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
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
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
