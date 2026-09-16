"""Deterministic discovery scoring and image-slot classification."""
from __future__ import annotations

from urllib.parse import unquote, urlparse

from .models import ImageCandidate, ImageSlot, OfficialSource, VehicleIdentity


def _compact(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _terms(identity: VehicleIdentity) -> tuple[str, ...]:
    return tuple(value.casefold().strip() for value in (identity.model_name, *identity.aliases)
                 if value and len(value.strip()) >= 2)


def _matches(haystack: str, term: str) -> bool:
    return term in haystack or (_compact(term) and _compact(term) in _compact(haystack))


def link_score(url: str, text: str, identity: VehicleIdentity, source: OfficialSource) -> int:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not source.host_allowed(parsed.hostname or ""):
        return -999
    haystack = f"{url} {text}".casefold()
    score = 50 if any(_matches(haystack, term) for term in _terms(identity)) else 0
    if identity.generation_code and identity.generation_code.casefold() in haystack:
        score += 20
    if any(x in haystack for x in ("model", "models", "vehicle", "car", "product")):
        score += 5
    if any(x in haystack for x in ("news", "press", "media", "launch")):
        score += 3
    return score


def classify_slot(candidate: ImageCandidate) -> ImageSlot:
    text = unquote(f"{candidate.image_url} {candidate.alt}").casefold()
    rules = (
        (ImageSlot.CARGO, ("cargo", "boot", "trunk", "luggage")),
        (ImageSlot.DASHBOARD, ("dashboard", "cockpit", "instrument-panel", "instrument_panel")),
        (ImageSlot.INTERIOR, ("interior", "cabin", "seat", "console")),
        (ImageSlot.REAR_3Q, ("rear-3", "rear_3", "rear3", "back-3", "rear-quarter")),
        (ImageSlot.FRONT_3Q, ("front-3", "front_3", "front3", "3q", "3-4", "front-quarter")),
        (ImageSlot.SIDE, ("side", "profile")),
        (ImageSlot.DETAIL, ("wheel", "lamp", "light", "grille", "detail")),
    )
    for slot, needles in rules:
        if any(needle in text for needle in needles):
            return slot
    return ImageSlot.HERO if candidate.is_og_image else ImageSlot.UNKNOWN


def score_candidate(candidate: ImageCandidate, identity: VehicleIdentity,
                    source: OfficialSource) -> ImageCandidate:
    reasons: list[str] = []
    score = 0
    page_text = f"{candidate.page_title} {candidate.source_page}".casefold()
    asset_text = unquote(f"{candidate.alt} {candidate.image_url}").casefold()
    terms = _terms(identity)
    page_match = any(_matches(page_text, term) for term in terms)
    asset_match = any(_matches(asset_text, term) for term in terms)
    generation_asset_match = bool(
        identity.generation_code
        and identity.generation_code.casefold() in asset_text
    )

    if source.host_allowed(urlparse(candidate.source_page).hostname or ""):
        score += 20
        reasons.append("+20 official OEM page")
    if page_match:
        score += 15
        reasons.append("+15 relevant model page")
    if asset_match:
        score += 35
        reasons.append("+35 model in asset metadata")
    if generation_asset_match:
        score += 20
        reasons.append("+20 generation in asset metadata")
    if source.market == identity.market:
        score += 10
        reasons.append("+10 market match")
    if candidate.width and candidate.width >= 1600:
        score += 10
        reasons.append("+10 >=1600px")
    filename = unquote(urlparse(candidate.image_url).path.rsplit("/", 1)[-1])
    if any(_matches(filename, term) for term in terms):
        score += 5
        reasons.append("+5 model in filename")
    if candidate.is_og_image:
        score += 8
        reasons.append("+8 page hero metadata")
    if candidate.width and candidate.width < 600:
        score -= 50
        reasons.append("-50 thumbnail")
    if any(x in asset_text for x in ("logo", "icon", "favicon", "sprite")):
        score -= 30
        reasons.append("-30 logo/icon")
    if any(x in asset_text for x in ("accessor", "merchandise")):
        score -= 30
        reasons.append("-30 accessory")

    candidate.score = max(0, min(100, score))
    candidate.score_reasons = reasons
    candidate.slot = classify_slot(candidate)
    candidate.identity_evidence = asset_match or generation_asset_match
    return candidate
