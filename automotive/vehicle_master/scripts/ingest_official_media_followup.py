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

from vehreg.official_media.adapters import MODEL_ASSET_HINTS, MODEL_PAGE_HINTS  # noqa: E402

# This follow-up list is downstream of the serving-release lifecycle audit. It
# must only contain Generation IDs classified TARGET_CURRENT; OEM pages below
# are media provenance, never evidence that changes lifecycle.
MODEL_PAGE_HINTS.update({
    "toyota.fortuner.an160": (
        "https://www.toyota.co.th/model/fortuner_leader",
        "https://www.toyota.co.th/model/fortuner_legender",
    ),
    "toyota.hilux_revo_double_cab.an120": (
        "https://www.toyota.co.th/model/hilux_revo_zedition",
    ),
    # Toyota serves Alphard and Vellfire as one official product-family page.
    # Do not add a direct asset hint unless the candidate itself carries
    # Vellfire identity evidence.
    "toyota.vellfire.gen1": ("https://www.toyota.co.th/model/alphard",),
    # Use GWM's current server-rendered Thailand route. The older www1 route is
    # a JavaScript shell on cloud runners and exposes no media candidates.
    "gwm.haval_jolion.jol": ("https://www.gwm.co.th/HAVAL_JOLION.html",),
})

# Exact first-party assets are used only where the OEM page does not expose the
# same media reliably to cloud runners. They remain tied to the current official
# product page above and still pass scoring, content hashing and deduplication.
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
