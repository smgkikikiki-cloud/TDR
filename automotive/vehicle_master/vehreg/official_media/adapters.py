"""Declarative first-party source adapters for Thai-market OEM sites.

The crawler never leaves an adapter's official host allowlist. Model-page hints
cover OEM sites whose SPA navigation is not represented by ordinary HTML links.
A very small set of asset hints covers pages where the public HTML is rendered
through an image proxy that urllib cannot discover; every hint is tied to an
exact official model page and still passes the normal scoring/hash gates.
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
        seed_urls=(
            "https://www.mgcars.com/th",
            "https://new.mgcars.com/th",
        ),
        allowed_hosts=("mgcars.com",),
    ),
    "gwm": OfficialSource(
        brand_id="gwm",
        seed_urls=("https://www.gwm.co.th/",),
        allowed_hosts=("gwm.co.th",),
    ),
}


MODEL_PAGE_HINTS: dict[str, tuple[str, ...]] = {
    "toyota.camry.xv80": ("https://www.toyota.co.th/model/camry",),
    "toyota.corolla_cross.xg10": ("https://www.toyota.co.th/model/corollacross",),
    "toyota.yaris_ativ.mxpa10": ("https://www.toyota.co.th/model/yarisativ",),
    "toyota.yaris_cross.ac200": ("https://www.toyota.co.th/model/yariscross",),
    "toyota.alphard.ah40": ("https://www.toyota.co.th/model/alphard",),
    "toyota.hilux_champ.champ": ("https://www.toyota.co.th/model/hilux_champ",),
    "honda.accord.cy": ("https://www.honda.co.th/accordehev",),
    "honda.city.gn2": ("https://www.honda.co.th/city",),
    "byd.atto2.atto2": ("https://www.byd.com/en-th/car/atto2",),
    "byd.atto3.atto3": ("https://www.byd.com/en-th/car/atto3",),
    "byd.dolphin.dol": ("https://www.byd.com/en-th/car/dolphin",),
    "byd.seal.seal": ("https://www.byd.com/en-th/car/seal",),
    "byd.sealion5.sealion5": ("https://www.byd.com/en-th/car/sealion5",),
    "byd.sealion6.sl6": ("https://www.byd.com/en-th/car/sealion6",),
    "byd.sealion7.sl7": ("https://www.byd.com/en-th/car/sealion7",),
    "byd.byd_m6.m6": ("https://www.byd.com/en-th/car/m6",),
    "mg.mg3.mg3h": ("https://www.mgcars.com/th/cars/all-new-mg3",),
    "mg.mg4.mg4e": ("https://www.mgcars.com/th/cars/mg4-my2026",),
    "mg.mg_s5_ev.gen1": ("https://www.mgcars.com/th/cars/mg-s5-ev-plus",),
    "mg.mg_im6.gen1": ("https://www.mgcars.com/th/cars/mg-im6",),
    "mg.mg_cyberster.gen1": ("https://www.mgcars.com/th/cars/mg-cyberster",),
    "mg.mg_maxus_9.mifa9": ("https://www.mgcars.com/th/cars/mg-maxus9-my26",),
    "gwm.haval_h6.h6hev": ("https://www.gwm.co.th/en/models/haval-h6",),
    "gwm.tank300.t300": ("https://www.gwm.co.th/en/models/tank-300-diesel",),
    "gwm.tank500.t500": ("https://www.gwm.co.th/en/models/tank-500-diesel",),
    "gwm.poer_sahar.gen1": ("https://www.gwm.co.th/en/models/sahar-diesel",),
}


# (image URL, semantic label). These were read directly from the exact official
# model pages above. The label intentionally includes the canonical model name,
# providing explicit identity evidence for scoring rather than granting trust to
# an anonymous CDN hash.
MODEL_ASSET_HINTS: dict[str, tuple[tuple[str, str], ...]] = {
    "honda.city.gn2": ((
        "https://www.honda.co.th/_next/image?q=75&url=https%3A%2F%2Fassets.honda.co.th%2Fwww-assets%2Fmodel%2F2026%2F06%2F24%2FSKERbsE7s6sWdABI81aBOnYJp6dGLBtB.png&w=1920",
        "Honda City official exterior hero",
    ),),
    "mg.mg3.mg3h": ((
        "https://www.mgcars.com/cdn-cgi/image/width%3D3840%2Cquality%3D75%2Cformat%3Dwebp/https%3A//mg-upload.sgp1.cdn.digitaloceanspaces.com/4ba961ae9c7d561f100728488d21e07d.png",
        "MG3 official hero",
    ),),
    "mg.mg4.mg4e": ((
        "https://www.mgcars.com/cdn-cgi/image/width%3D3840%2Cquality%3D75%2Cformat%3Dwebp/https%3A//mg-upload.sgp1.cdn.digitaloceanspaces.com/a6d79e25ae46909487301a2f8e382e22.png",
        "MG4 Electric official hero",
    ),),
    "mg.mg_s5_ev.gen1": ((
        "https://www.mgcars.com/cdn-cgi/image/width%3D3840%2Cquality%3D75%2Cformat%3Dwebp/https%3A//mg-upload.sgp1.cdn.digitaloceanspaces.com/b4b9be2127b7e8b5fca955d26754dd4a.png",
        "MG S5 EV official hero",
    ),),
    "mg.mg_im6.gen1": ((
        "https://www.mgcars.com/cdn-cgi/image/width%3D3840%2Cquality%3D75%2Cformat%3Dwebp/https%3A//mg-upload.sgp1.cdn.digitaloceanspaces.com/c5ab9149a6033aa6a55517e80c87dbe9.png",
        "MG IM6 official hero",
    ),),
    "mg.mg_cyberster.gen1": ((
        "https://www.mgcars.com/cdn-cgi/image/width%3D3840%2Cquality%3D75%2Cformat%3Dwebp/https%3A//mg-upload.sgp1.cdn.digitaloceanspaces.com/e09c2003de5f52815f8ca2b3125d48e0.png",
        "MG Cyberster official hero",
    ),),
    "mg.mg_maxus_9.mifa9": ((
        "https://www.mgcars.com/cdn-cgi/image/width%3D3840%2Cquality%3D75%2Cformat%3Dwebp/https%3A//mg-upload.sgp1.cdn.digitaloceanspaces.com/9b17852986667fc582699b4dc436ace3.jpg",
        "MG Maxus 9 official hero",
    ),),
}


def get_source(brand_id: str) -> OfficialSource | None:
    return SOURCES.get(brand_id.casefold())


def get_page_hints(generation_id: str) -> tuple[str, ...]:
    return MODEL_PAGE_HINTS.get(generation_id, ())


def get_asset_hints(generation_id: str) -> tuple[tuple[str, str], ...]:
    return MODEL_ASSET_HINTS.get(generation_id, ())
