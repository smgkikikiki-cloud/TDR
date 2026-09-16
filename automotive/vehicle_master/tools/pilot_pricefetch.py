#!/usr/bin/env python3
"""Bounded P2 pilot adapter for Toyota/Honda Thailand static model pages.

This file exists only on the price backfill pilot branch.  It proves the generic
first-party HTML fetch/extract/match path before production adapter registry
changes.  It does not write PriceLedger or serving data.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehreg.price_fetch import ADAPTERS, OfficialOEMAdapter  # noqa: E402
from tools.pricefetch_targets import main as pricefetch_main  # noqa: E402


class _PilotToyotaHondaAdapter(OfficialOEMAdapter):
    # The registry still labels these sources "manual" on main.  The pilot
    # deliberately overrides that one adapter id in-process, bounded by both
    # source-id and hostname allow-lists below.
    adapter_id = "manual"
    allowed_hosts = frozenset({
        "toyota.co.th",
        "www.toyota.co.th",
        "honda.co.th",
        "www.honda.co.th",
    })
    source_ids = frozenset({"official_toyota_th", "official_honda_th"})


ADAPTERS[_PilotToyotaHondaAdapter.adapter_id] = _PilotToyotaHondaAdapter


if __name__ == "__main__":
    raise SystemExit(pricefetch_main())
