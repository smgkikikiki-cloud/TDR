#!/usr/bin/env python3
"""Scale-run entry point for official media ingestion.

Keeps experimental brand expansion out of the stable adapter table until the
large-run evidence proves the source behavior. The shared adapter mappings are
extended here with verified Thai OEM model pages and a few exact assets observed
on those official pages during the scale review.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vehreg.official_media.models import OfficialSource
from vehreg.official_media.adapters import (
    MODEL_ASSET_HINTS,
    MODEL_PAGE_HINTS,
    SOURCES,
)

# First large-scale source expansion: BMW Thailand's first-party model index.
SOURCES.setdefault(
    "bmw",
    OfficialSource(
        brand_id="bmw",
        seed_urls=(
            "https://www.bmw.co.th/en/all-models.html",
            "https://www.bmw.co.th/en/home.html",
        ),
        allowed_hosts=("bmw.co.th",),
    ),
)

# Exact first-party pages verified against the current Thai OEM sites. These are
# discovery seeds, not automatic approvals: extracted assets still pass normal
# scoring, identity evidence, hashing and cross-vehicle duplicate gates.
MODEL_PAGE_HINTS.update({
    # Toyota Thailand
    "toyota.bz4x.ea10": ("https://www.toyota.co.th/model/bz4x",),
    "toyota.commuter.gen1": ("https://www.toyota.co.th/model/commuter",),
    "toyota.corolla_altis.e210": ("https://www.toyota.co.th/model/altis",),
    "toyota.fortuner.an160": ("https://www.toyota.co.th/model/fortuner",),
    "toyota.hiace.gen1": ("https://www.toyota.co.th/model/hiace",),
    "toyota.innova_zenix.aw40": ("https://www.toyota.co.th/model/innovazenix",),
    "toyota.veloz.w100": ("https://www.toyota.co.th/model/veloz",),
    "toyota.yaris.mxpa1x": ("https://www.toyota.co.th/model/yaris",),
    "toyota.hilux_revo_cab.an120": ("https://www.toyota.co.th/model/hilux_revo_standard",),

    # BMW Thailand current model pages
    "bmw.2_series_gran_coupe.gen1": (
        "https://www.bmw.co.th/en/all-models/2-series/gran-coupe/bmw-2-series-gran-coupe.html",
    ),
    "bmw.bmw_3.g20": (
        "https://www.bmw.co.th/en/all-models/3-series/bmw-3-series-sedan/bmw-3-series-sedan.html",
    ),
    "bmw.4_series.gen1": (
        "https://www.bmw.co.th/en/all-models/4-series/4-series-coupe/bmw-4-series-coupe.html",
    ),
    "bmw.bmw_5.g60": (
        "https://www.bmw.co.th/en/all-models/5-series/sedan/bmw-5-series-sedan-overview.html",
    ),
    "bmw.7_series.gen1": (
        "https://www.bmw.co.th/en/all-models/7-series/7-series-sedan/bmw-7-series-sedan.html",
    ),
    "bmw.bmw_x1.u11": (
        "https://www.bmw.co.th/en/all-models/x-series/x1/bmw-x1.html",
    ),
    "bmw.bmw_x3.g45": (
        "https://www.bmw.co.th/en/all-models/x-series/x3/bmw-x3.html",
    ),
    "bmw.x5.gen1": (
        "https://www.bmw.co.th/en/all-models/x-series/x5/bmw-x5.html",
    ),
    "bmw.x6.gen1": (
        "https://www.bmw.co.th/en/all-models/x-series/x6/bmw-x6.html",
    ),
    "bmw.x7.gen1": (
        "https://www.bmw.co.th/en/all-models/x-series/x7/bmw-x7.html",
    ),
    "bmw.ix.gen1": (
        "https://www.bmw.co.th/en/all-models/bmw-i-series/ix/bmw-ix.html",
    ),
    "bmw.z4.gen1": (
        "https://www.bmw.co.th/en/all-models/z-series/z4/bmw-z4.html",
    ),

    # Review-queue models whose exact official page identity is already known.
    "byd.seal_5_dmi.gen1": ("https://www.byd.com/en-th/car/seal5dmi",),
    "honda.brv.dg3": ("https://www.honda.co.th/models",),
    "honda.en1.en1": ("https://www.honda.co.th/models",),
})

# Exact assets observed on the official pages above. Their semantic labels are
# deliberately model-specific so anonymous/UUID CDN filenames do not become an
# implicit identity match. These still run through the standard score/hash gates.
MODEL_ASSET_HINTS.update({
    "byd.seal_5_dmi.gen1": ((
        "https://www.byd.com/material/__CN/byd-site/th/home/model/seal5dmi-2.png",
        "BYD Seal 5 DM-i official exterior hero",
    ),),
    "honda.brv.dg3": ((
        "https://assets.honda.co.th/www-assets/brv/2025/03/20/iyDyHbv8kuVgoJ7EHjwCFSh6KP8yFEgx.png",
        "Honda BR-V official exterior hero",
    ),),
    "honda.en1.en1": ((
        "https://assets.honda.co.th/www-assets/en1/2025/03/24/QISIPapqg9Sahh6uwA3Cz7X6OHPrSlDD.png",
        "Honda e:N1 official exterior hero",
    ),),
})

from ingest_official_media import main


if __name__ == "__main__":
    raise SystemExit(main())
