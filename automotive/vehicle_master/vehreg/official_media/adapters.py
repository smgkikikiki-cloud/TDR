"""Declarative first-party source adapters for Thai-market OEM sites.

The crawler never leaves an adapter's official host allowlist. Model-page hints
cover OEM sites whose SPA navigation is not represented by ordinary HTML links.
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
        seed_urls=("https://www.byd.com/en-th",),
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


# Explicit current official pages are deliberately keyed by canonical generation
# identity. They are discovery hints only: every URL still has to pass the OEM
# host allowlist and candidate scoring before any asset can be approved.
MODEL_PAGE_HINTS: dict[str, tuple[str, ...]] = {
    "toyota.camry.xv80": ("https://www.toyota.co.th/model/camry",),
    "toyota.corolla_cross.xg10": ("https://www.toyota.co.th/model/corollacross",),
    "toyota.yaris_ativ.mxpa10": ("https://www.toyota.co.th/model/yarisativ",),
    "toyota.yaris_cross.ac200": ("https://www.toyota.co.th/model/yariscross",),
    "toyota.alphard.ah40": ("https://www.toyota.co.th/model/alphard",),
    "toyota.hilux_champ.champ": ("https://www.toyota.co.th/model/hilux_champ",),
    "honda.accord.cy": ("https://www.honda.co.th/accordehev2023",),
    "byd.atto3.atto3": ("https://www.byd.com/en-th/car/atto3",),
    "byd.dolphin.dol": ("https://www.byd.com/en-th/car/dolphin",),
    "byd.seal.seal": ("https://www.byd.com/en-th/car/seal",),
    "byd.sealion6.sl6": ("https://www.byd.com/en-th/car/sealion6",),
    "byd.sealion7.sl7": ("https://www.byd.com/en-th/car/sealion7",),
    "byd.byd_m6.m6": ("https://www.byd.com/en-th/car/m6",),
    "mg.mg4.mg4e": ("https://www.mgcars.com/th/cars/mg4-my2026",),
    "mg.mg_im6.gen1": ("https://www.mgcars.com/th/cars/mg-im6",),
    "mg.mg_cyberster.gen1": ("https://www.mgcars.com/th/cars/mg-cyberster",),
}


def get_source(brand_id: str) -> OfficialSource | None:
    return SOURCES.get(brand_id.casefold())


def get_page_hints(generation_id: str) -> tuple[str, ...]:
    return MODEL_PAGE_HINTS.get(generation_id, ())
