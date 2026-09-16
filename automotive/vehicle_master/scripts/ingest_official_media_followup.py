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

MODEL_PAGE_HINTS.update({
    # Current MG Thailand models verified during the 2026 lifecycle audit.
    "mg.mg_extender_cab.ext": ("https://www.mgcars.com/th/cars/mg-extender-gc",),
    "mg.mg_extender_double_cab.ext": ("https://www.mgcars.com/th/cars/mg-extender-dc",),
    "mg.mg_im5.mg_im5": ("https://www.mgcars.com/th/cars/mg-im5",),
    "mg.mg_maxus_7.gen1": ("https://www.mgcars.com/th/cars/mg-maxus7",),

    # Current Honda Thailand models verified against the live 2026 model list.
    # Start with discovery-only page hints; promote exact assets only if the
    # normal parser/scoring path cannot produce a safe primary exterior.
    "honda.city_hatchback.gn7": ("https://www.honda.co.th/cityhatchback",),
    "honda.en2.en2": ("https://www.honda.co.th/en2",),
    "honda.step_wgn.gen1": ("https://www.honda.co.th/stepwgnehev",),
})

# Exact hero assets observed on the official MG Thailand product pages above.
# Use the underlying first-party upload objects rather than the nested
# Cloudflare optimizer URL; provenance remains the exact MG product page.
MODEL_ASSET_HINTS.update({
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
