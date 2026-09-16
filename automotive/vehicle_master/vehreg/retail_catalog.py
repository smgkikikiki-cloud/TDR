"""Read-only canonical retail catalog view.

Analytical Catalog files remain the owner of brands/models/generations/Variants.
Retail MarketTrim identity may additionally live under market/trims/canonical*.json.
Consumers that reason about showroom SKUs (price intelligence, retail QA) need
both grains merged in memory without writing retail rows back into model files.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .catalog import Catalog, CatalogError, DATA_DIR, DEFAULT_YEAR

_SCHEMA_VERSION = 1


def _retail_paths(data_dir: Path | str, year: int) -> list[Path]:
    root = Path(data_dir) / str(year) / "market" / "trims"
    paths: list[Path] = []
    base = root / "canonical.json"
    if base.exists():
        paths.append(base)
    paths.extend(sorted(root.glob("canonical_*.json")))
    return paths


def load_retail_catalog(
    data_dir: Path | str = DATA_DIR,
    year: int = DEFAULT_YEAR,
) -> Catalog:
    """Return Catalog plus every dedicated canonical MarketTrim fragment.

    The returned object is an in-memory read view only. Overlay rows are parsed
    through Catalog's existing MarketTrim constructor/validation so IDs, exact
    powertrain requirements, aliases and provenance behave exactly like nested
    catalog trims.
    """
    catalog = Catalog.load(data_dir, year)
    for path in _retail_paths(data_dir, year):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CatalogError(f"{path}: invalid JSON: {exc}") from exc
        if payload.get("schema_version") != _SCHEMA_VERSION:
            raise CatalogError(
                f"{path}: unsupported schema {payload.get('schema_version')!r}"
            )
        rows = payload.get("trims")
        if not isinstance(rows, list):
            raise CatalogError(f"{path}: trims must be an array")
        for raw in rows:
            if not isinstance(raw, Mapping):
                raise CatalogError(f"{path}: trim row must be an object")
            model_id = str(raw.get("model_id") or "").strip()
            generation_id = str(raw.get("generation_id") or "").strip()
            generation = catalog.generations.get(generation_id)
            if model_id not in catalog.models:
                raise CatalogError(f"{path}: unknown model_id {model_id!r}")
            if generation is None or generation.model_id != model_id:
                raise CatalogError(
                    f"{path}: generation {generation_id!r} is not under {model_id!r}"
                )
            if raw.get("variant_id") not in (None, ""):
                raise CatalogError(
                    f"{path}: retail overlay variant_id must stay empty until reviewed"
                )
            # Reuse the canonical parser rather than introducing a second
            # MarketTrim identity implementation. Extra overlay keys such as
            # model_id/generation_id are deliberately ignored by _add_trim.
            catalog._add_trim(generation_id, dict(raw), str(path))
    catalog.build_indexes()
    return catalog


__all__ = ["load_retail_catalog"]
