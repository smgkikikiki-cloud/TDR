#!/usr/bin/env python3
"""Scale-run entry point for official media ingestion.

Keeps experimental brand expansion out of the stable adapter table until the
large-run evidence proves the source behavior. The shared SOURCES mapping is
mutated before the normal CLI resolves supported identities.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vehreg.official_media import OfficialSource, SOURCES

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

from ingest_official_media import main


if __name__ == "__main__":
    raise SystemExit(main())
