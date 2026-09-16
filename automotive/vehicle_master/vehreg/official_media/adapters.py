"""Declarative first-party source adapters for Thai-market OEM sites.

The crawler never leaves an adapter's official host allowlist. Brand-specific
parsers can be added later without changing the pipeline contract.
"""
from __future__ import annotations

from .models import OfficialSource


SOURCES: dict[str, OfficialSource] = {
    "toyota": OfficialSource(
        brand_id="toyota",
        seed_urls=(
            "https://www.toyota.co.th/",
            "https://www.toyota.co.th/model",
            "https://www.toyota.co.th/news",
        ),
        allowed_hosts=("toyota.co.th",),
    ),
    "honda": OfficialSource(
        brand_id="honda",
        seed_urls=(
            "https://www.honda.co.th/models",
            "https://www.honda.co.th/news",
        ),
        allowed_hosts=("honda.co.th",),
    ),
    "byd": OfficialSource(
        brand_id="byd",
        seed_urls=("https://www.byd.com/th",),
        allowed_hosts=("byd.com",),
    ),
    "mg": OfficialSource(
        brand_id="mg",
        seed_urls=("https://www.mgcars.com/th",),
        allowed_hosts=("mgcars.com",),
    ),
    "gwm": OfficialSource(
        brand_id="gwm",
        seed_urls=("https://www.gwm.co.th/",),
        allowed_hosts=("gwm.co.th",),
    ),
}


def get_source(brand_id: str) -> OfficialSource | None:
    return SOURCES.get(brand_id.casefold())
