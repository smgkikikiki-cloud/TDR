"""Official OEM media ingestion for Vehicle Master."""

from .adapters import SOURCES, get_source
from .models import (
    ImageCandidate, ImageSlot, MediaAsset, OfficialSource, ReviewStatus,
    SourceType, VehicleIdentity,
)
from .pipeline import ContentAddressedStore, collect_candidates, ingest, select_canonical

__all__ = [
    "ContentAddressedStore", "ImageCandidate", "ImageSlot", "MediaAsset",
    "OfficialSource", "ReviewStatus", "SOURCES", "SourceType", "VehicleIdentity",
    "collect_candidates", "get_source", "ingest", "select_canonical",
]
