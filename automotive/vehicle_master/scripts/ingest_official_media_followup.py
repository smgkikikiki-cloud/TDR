#!/usr/bin/env python3
"""Targeted current-model media follow-up layered on the proven scale adapters."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Importing the scale entry point applies the verified BMW/Toyota scale adapter
# extensions without executing its CLI main block.
import ingest_official_media_scale  # noqa: F401,E402

from vehreg.official_media.adapters import (  # noqa: E402
    MODEL_ASSET_HINTS,
    MODEL_PAGE_HINTS,
    SOURCES,
)
from vehreg.official_media.models import OfficialSource  # noqa: E402

# Follow-up sources are deliberately Thai-market first-party sites. Lifecycle is
# still decided upstream by the serving-release audit; these adapters only find
# media for identities already classified TARGET_CURRENT.
SOURCES.update({
    "aion": OfficialSource(
        brand_id="aion",
        seed_urls=("https://www.gacgroup.com/th-th",),
        allowed_hosts=("gacgroup.com",),
    ),
    "tesla": OfficialSource(
        brand_id="tesla",
        seed_urls=("https://www.tesla.com/en_th/",),
        allowed_hosts=("tesla.com",),
    ),
    "xpeng": OfficialSource(
        brand_id="xpeng",
        seed_urls=("https://www.xpeng.com/th/g6",),
        allowed_hosts=("xpeng.com",),
    ),
    "zeekr": OfficialSource(
        brand_id="zeekr",
        seed_urls=("https://www.zeekrlife.com/th-th/",),
        allowed_hosts=("zeekrlife.com",),
    ),
})

MODEL_PAGE_HINTS.update({
    "aion.aion_y_plus.ayp": ("https://www.gacgroup.com/th-th/suv/aion-y-plus",),
    "aion.hyptec_ht.gen1": ("https://www.gacgroup.com/th-th/suv/hyptec-ht",),
    "tesla.model3.m3h": ("https://www.tesla.com/en_th/model3",),
    "tesla.modely.my": ("https://www.tesla.com/en_th/modely",),
    "xpeng.xpeng_g6.g6": ("https://www.xpeng.com/th/g6",),
    "zeekr.zeekr_009.z009": ("https://www.zeekrlife.com/en-th/models/009",),
    "zeekr.zeekr_x.zx": ("https://www.zeekrlife.com/th-th/models/x",),

    # Previously verified current-model provenance remains reproducible even
    # when those identities are not part of the active follow-up target file.
    "toyota.fortuner.an160": (
        "https://www.toyota.co.th/model/fortuner_leader",
        "https://www.toyota.co.th/model/fortuner_legender",
    ),
    "toyota.hilux_revo_double_cab.an120": (
        "https://www.toyota.co.th/model/hilux_revo_zedition",
    ),
    "toyota.vellfire.gen1": ("https://www.toyota.co.th/model/alphard",),
    "gwm.haval_jolion.jol": ("https://www.gwm.co.th/HAVAL_JOLION.html",),
})

# Exact first-party assets are used only where the OEM page does not expose the
# same media reliably to cloud runners. They remain tied to an official product
# page and still pass scoring, content hashing and deduplication.
MODEL_ASSET_HINTS.update({
    "gwm.haval_jolion.jol": ((
        "https://www.gwm.co.th/content/dam/gwm/pages/th/en/model/haval-jolion/360/new-sport/white-2.webp",
        "GWM HAVAL JOLION NEW SPORT official exterior hero",
    ),),
    "mg.mg_extender_cab.ext": ((
        "https://mg-upload.sgp1.cdn.digitaloceanspaces.com/a6b2f36e856e4c8c35a773a8e0a38068.png",
        "MG Extender Giant Cab official exterior hero",
    ),),
    "mg.mg_extender_double_cab.ext": ((
        "https://mg-upload.sgp1.cdn.digitaloceanspaces.com/35b2599d8eef3ceb20d8632cf603c2f2.png",
        "MG Extender Double Cab official exterior hero",
    ),),
    "mg.mg_im5.mg_im5": ((
        "https://mg-upload.sgp1.cdn.digitaloceanspaces.com/fd24c1f094fefdcb958809ae4a001e3d.jpg",
        "MG IM5 official exterior hero",
    ),),
    "mg.mg_maxus_7.gen1": ((
        "https://mg-upload.sgp1.cdn.digitaloceanspaces.com/1e7389cdd7dfec373651c3fbe89ac36b.png",
        "MG Maxus 7 official exterior hero",
    ),),
})

from ingest_official_media import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
