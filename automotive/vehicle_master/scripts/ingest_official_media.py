#!/usr/bin/env python3
"""Bulk-ingest official OEM images for canonical Vehicle Master generations."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vehreg.catalog import Catalog, DATA_DIR
from vehreg.official_media import ContentAddressedStore, VehicleIdentity, get_source, ingest
from vehreg.official_media.pipeline import write_jsonl


def identities(catalog: Catalog, brands: set[str] | None = None):
    for generation in catalog.generations.values():
        model = catalog.models[generation.model_id]
        brand = catalog.brands[model.brand_id]
        if brands and brand.id not in brands:
            continue
        if get_source(brand.id) is None:
            continue
        aliases = tuple(dict.fromkeys((model.nameplate, *model.aliases)))
        yield VehicleIdentity(
            brand_id=brand.id,
            model_id=model.id,
            generation_id=generation.id,
            model_name=model.name_en,
            generation_code=generation.code,
            model_year=catalog.year,
            aliases=aliases,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--brands", nargs="*", default=[])
    parser.add_argument(
        "--vehicle-ids", nargs="*", default=[],
        help="Exact canonical generation IDs to ingest, preserving this order.",
    )
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--max-pages", type=int, default=8)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "integration_data" / "official_media")
    parser.add_argument("--cache-dir", type=Path,
                        default=ROOT / "data" / "media" / "cache")
    args = parser.parse_args()

    catalog = Catalog.load(args.data_dir, args.year)
    wanted = {item.casefold() for item in args.brands} or None
    available = list(identities(catalog, wanted))

    if args.vehicle_ids:
        by_id = {item.generation_id: item for item in available}
        missing = [item for item in args.vehicle_ids if item not in by_id]
        if missing:
            parser.error("unknown or unsupported --vehicle-ids: " + ", ".join(missing))
        vehicles = [by_id[item] for item in args.vehicle_ids]
    else:
        vehicles = available
        if args.limit:
            vehicles = vehicles[:args.limit]

    store = ContentAddressedStore(args.cache_dir)
    manifest: list[dict] = []
    review: list[dict] = []
    summary: list[dict] = []
    for identity in vehicles:
        assets, flags = ingest(identity, store, max_pages=args.max_pages)
        manifest.extend(asset.as_dict() for asset in assets)
        review.extend(flags)
        summary.append({
            "vehicle_id": identity.generation_id,
            "brand": identity.brand_id,
            "model": identity.model_name,
            "assets": len(assets),
            "approved": sum(asset.status == "approved" for asset in assets),
            "review": len(flags),
        })
        print(f"{identity.generation_id}: {len(assets)} assets, {len(flags)} review")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_dir / f"media_manifest_{args.year}.jsonl", manifest)
    write_jsonl(args.output_dir / f"review_queue_{args.year}.jsonl", review)
    write_jsonl(args.output_dir / f"run_summary_{args.year}.jsonl", summary)
    print(f"wrote {len(manifest)} assets for {len(vehicles)} visual identities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
