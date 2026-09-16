"""Domain objects for official vehicle media ingestion.

Media is attached at the narrowest *visual* identity needed. By default that is
one Generation, so trims inherit the same asset set instead of downloading the
same press image repeatedly. A future trim-specific override can point at a
different visual key without changing vehicle identity.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional


class SourceType(str, Enum):
    MANUFACTURER_MEDIA = "manufacturer_media"
    OFFICIAL_SITE = "official_site"
    PRESS_RELEASE = "press_release"


class ImageSlot(str, Enum):
    HERO = "hero"
    FRONT_3Q = "front_3q"
    REAR_3Q = "rear_3q"
    SIDE = "side"
    DASHBOARD = "dashboard"
    INTERIOR = "interior"
    CARGO = "cargo"
    DETAIL = "detail"
    UNKNOWN = "unknown"


class ReviewStatus(str, Enum):
    APPROVED = "approved"
    REVIEW = "review"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class VehicleIdentity:
    brand_id: str
    model_id: str
    generation_id: str
    model_name: str
    generation_code: str = ""
    market: str = "TH"
    model_year: Optional[int] = None
    aliases: tuple[str, ...] = ()

    @property
    def visual_key(self) -> str:
        """Canonical inheritance key for media shared by all trims."""
        return self.generation_id or self.model_id


@dataclass(frozen=True, slots=True)
class OfficialSource:
    brand_id: str
    seed_urls: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    market: str = "TH"

    def host_allowed(self, host: str) -> bool:
        host = host.lower().split(":", 1)[0].strip(".")
        return any(host == item or host.endswith("." + item)
                   for item in self.allowed_hosts)


@dataclass(slots=True)
class ImageCandidate:
    source_page: str
    source_type: SourceType
    image_url: str
    page_title: str = ""
    alt: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    is_og_image: bool = False
    score: int = 0
    score_reasons: list[str] = field(default_factory=list)
    slot: ImageSlot = ImageSlot.UNKNOWN
    identity_evidence: bool = False

    @property
    def status(self) -> ReviewStatus:
        # High score alone is not identity evidence. Brand sites routinely reuse
        # generic OG/background assets across every model route; those must never
        # become public merely because the page URL contains a model name.
        if self.slot is ImageSlot.UNKNOWN:
            return ReviewStatus.REVIEW if self.score >= 60 else ReviewStatus.REJECTED
        if self.score >= 85 and self.identity_evidence:
            return ReviewStatus.APPROVED
        if self.score >= 60:
            return ReviewStatus.REVIEW
        return ReviewStatus.REJECTED


@dataclass(frozen=True, slots=True)
class MediaAsset:
    vehicle_id: str
    visual_key: str
    source_url: str
    source_type: str
    source_domain: str
    image_url_original: str
    storage_path: str
    image_type: str
    market: str
    model_year: Optional[int]
    confidence: int
    sha256: str
    width: Optional[int]
    height: Optional[int]
    status: str

    def as_dict(self) -> dict:
        return asdict(self)
