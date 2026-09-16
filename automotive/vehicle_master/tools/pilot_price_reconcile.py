#!/usr/bin/env python3
"""Run P5 against the canonical retail MarketTrim view for the pilot branch."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehreg.retail_catalog import load_retail_catalog  # noqa: E402
import tools.price_reconcile_batch as runner  # noqa: E402


class _RetailCatalogFacade:
    @classmethod
    def load(cls, data_dir, year):
        return load_retail_catalog(data_dir, year)


runner.Catalog = _RetailCatalogFacade


if __name__ == "__main__":
    raise SystemExit(runner.main())
