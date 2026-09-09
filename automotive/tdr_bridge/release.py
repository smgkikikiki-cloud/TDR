"""Build one deterministic TDR serving release from Vehicle Master.

The release is a projection. Vehicle identity, retail trims, specifications and
prices remain authored in ``vehreg``. TDR UUIDs are retained only as links to
editorial and industry records that already exist in Supabase.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata

from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from vehreg.entities import to_jsonable
from vehreg.product import ProductMaster


SCHEMA_VERSION = 1


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return "".join(ch for ch in text if ch.isalnum())


def _slug(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", value).lower())
    return "-".join(words) or "vehicle"


def _explicit_source(notes: object) -> str | None:
    match = re.search(r"(?:^|[;\s])source=([^;\s]+)", str(notes or ""))
    return match.group(1) if match else None


def _price_row(record) -> dict:
    row = to_jsonable(record)
    semantic = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"record_id": sha256(semantic.encode()).hexdigest()[:24], **row}


class ReleaseBuilder:
    def __init__(self, inventory: dict, *, data_dir=DATA_DIR,
                 year: int = DEFAULT_YEAR, canonical_revision: str = "working-tree",
                 overrides: dict | None = None):
        self.inventory = inventory
        self.year = year
        self.canonical_revision = canonical_revision
        self.overrides = overrides or {}
        self.master = ProductMaster.load(data_dir, year)
        problems = self.master.validate()
        if problems:
            raise ValueError("canonical product validation failed: " + "; ".join(problems))

    def _brand_crosswalk(self) -> tuple[dict[str, dict], list[dict]]:
        by_surface: dict[str, list[dict]] = {}
        for row in self.inventory.get("brands", []):
            for surface in (row.get("slug"), row.get("name_en"), row.get("name_th")):
                if _norm(surface):
                    by_surface.setdefault(_norm(surface), []).append(row)
        mapped, review = {}, []
        for brand in self.master.catalog.brands.values():
            forced = self.overrides.get("brands", {}).get(brand.id)
            if forced:
                row = next((row for row in self.inventory.get("brands", [])
                            if row["id"] == forced), None)
                if row is None:
                    review.append({"entity_type": "brand", "canonical_id": brand.id,
                                   "status": "BROKEN_OVERRIDE", "candidate_tdr_ids": [forced]})
                else:
                    mapped[brand.id] = row
                continue
            primary = {}
            for surface in (brand.id, brand.name_en, brand.name_th):
                for row in by_surface.get(_norm(surface), []):
                    primary[row["id"]] = row
            if len(primary) == 1:
                mapped[brand.id] = next(iter(primary.values()))
                continue
            candidates = {}
            for surface in (brand.id, brand.name_en, brand.name_th, *brand.aliases):
                for row in by_surface.get(_norm(surface), []):
                    candidates[row["id"]] = row
            if len(candidates) == 1:
                mapped[brand.id] = next(iter(candidates.values()))
            else:
                review.append({
                    "entity_type": "brand", "canonical_id": brand.id,
                    "status": "AMBIGUOUS" if candidates else "UNMATCHED",
                    "candidate_tdr_ids": sorted(candidates),
                })
        return mapped, review

    def _model_crosswalk(self, brands: dict[str, dict]) -> tuple[dict[str, dict], list[dict]]:
        catalog = self.master.catalog
        by_id = {row["id"]: row for row in self.inventory.get("models", [])}
        mapped: dict[str, dict] = {}
        claimed_tdr_ids: set[str] = set()
        review: list[dict] = []

        # Reviewed overrides win over legacy source markers; several old TDR
        # rows retained pre-correction IDs after the canonical catalog moved a
        # marque (Deepal/Jaecoo) or merged an alias (Galaxy E5 -> EX5).
        for canonical_id, tdr_id in self.overrides.get("models", {}).items():
            row = by_id.get(tdr_id)
            if canonical_id not in catalog.models or row is None or tdr_id in claimed_tdr_ids:
                review.append({"entity_type": "model", "canonical_id": canonical_id,
                               "status": "BROKEN_OVERRIDE", "candidate_tdr_ids": [tdr_id]})
                continue
            mapped[canonical_id] = row
            claimed_tdr_ids.add(tdr_id)

        # An explicit source marker is authoritative when it names a real model.
        for row in by_id.values():
            source = _explicit_source(row.get("notes"))
            source = self.overrides.get("source_aliases", {}).get(source, source)
            if source in catalog.models and source not in mapped and row["id"] not in claimed_tdr_ids:
                mapped[source] = row
                claimed_tdr_ids.add(row["id"])

        for model in catalog.models.values():
            if model.id in mapped:
                continue
            brand_row = brands.get(model.brand_id)
            candidates = {}
            surfaces = {
                _norm(model.id), _norm(model.id.split(".", 1)[-1]),
                _norm(model.name_en), _norm(model.name_th), _norm(model.nameplate),
                *(_norm(alias) for alias in model.aliases),
            } - {""}
            for row in by_id.values():
                if row["id"] in claimed_tdr_ids:
                    continue
                if brand_row and row.get("brand_id") not in (None, brand_row["id"]):
                    continue
                row_surfaces = {
                    _norm(row.get("slug")), _norm(row.get("name_en")),
                    _norm(row.get("name_th")),
                } - {""}
                if brand_row:
                    prefix = _norm(brand_row.get("slug"))
                    row_slug = _norm(row.get("slug"))
                    if prefix and row_slug.startswith(prefix):
                        row_surfaces.add(row_slug[len(prefix):])
                if surfaces & row_surfaces:
                    candidates[row["id"]] = row
            if len(candidates) == 1:
                row = next(iter(candidates.values()))
                mapped[model.id] = row
                claimed_tdr_ids.add(row["id"])
            else:
                review.append({
                    "entity_type": "model", "canonical_id": model.id,
                    "canonical_name": model.name_en,
                    "status": "AMBIGUOUS" if candidates else "UNMATCHED",
                    "candidate_tdr_ids": sorted(candidates),
                    "candidate_slugs": sorted(r.get("slug") or "" for r in candidates.values()),
                })

        # TDR-only rows are retained for manual review; publishing never deletes them.
        for row in by_id.values():
            if row["id"] not in claimed_tdr_ids:
                review.append({
                    "entity_type": "tdr_model", "tdr_id": row["id"],
                    "tdr_slug": row.get("slug"), "tdr_name": row.get("name_en") or row.get("name_th"),
                    "status": "UNMATCHED_TDR",
                })
        return mapped, review

    def build(self, *, as_of: date | None = None) -> dict:
        as_of = as_of or date.today()
        catalog = self.master.catalog
        brand_map, review = self._brand_crosswalk()
        model_map, model_review = self._model_crosswalk(brand_map)
        review.extend(model_review)

        brands = []
        for brand in sorted(catalog.brands.values(), key=lambda row: row.id):
            tdr = brand_map.get(brand.id)
            brands.append({
                "canonical_id": brand.id,
                "tdr_brand_id": tdr["id"] if tdr else None,
                "slug": tdr.get("slug") if tdr else _slug(brand.id),
                "name_en": brand.name_en, "name_th": brand.name_th,
                "origin_country": brand.brand_origin,
                "payload": to_jsonable(asdict(brand)),
            })

        models, generations, trims, prices, spec_facts = [], [], [], [], []
        trims_by_generation: dict[str, list] = {}
        for trim in catalog.trims.values():
            trims_by_generation.setdefault(trim.generation_id, []).append(trim)

        for model in sorted(catalog.models.values(), key=lambda row: row.id):
            tdr = model_map.get(model.id)
            brand = catalog.brands[model.brand_id]
            generation_rows = sorted(
                (g for g in catalog.generations.values() if g.model_id == model.id),
                key=lambda g: (g.launched or "", g.id), reverse=True)
            current_generation = next((g for g in generation_rows if not g.ended),
                                      generation_rows[0] if generation_rows else None)
            model_trims = [t for g in generation_rows for t in trims_by_generation.get(g.id, [])]
            generation_ids = {g.id for g in generation_rows}
            model_variants = [v for v in catalog.variants.values()
                              if v.generation_id in generation_ids]
            powertrains = sorted({v.powertrain.value for v in model_variants
                                  if v.powertrain.value != "UNKNOWN"})
            import_types = sorted({v.import_type.value for v in model_variants
                                   if v.import_type.value != "UNKNOWN"})
            origin_countries = sorted({v.origin_country for v in model_variants
                                       if v.origin_country not in ("", "UNKNOWN")})
            current_amounts = [self.master.prices.current_list_amount(t.id, as_of=as_of)
                               for t in model_trims]
            current_amounts = [n for n in current_amounts if n is not None]
            editorial = tdr or {}
            models.append({
                "canonical_id": model.id,
                "tdr_model_id": tdr["id"] if tdr else None,
                "brand_id": model.brand_id,
                "slug": editorial.get("slug") or _slug(f"{brand.id}-{model.name_en}"),
                "name_en": model.name_en, "name_th": model.name_th,
                "generation_id": current_generation.id if current_generation else None,
                "status": editorial.get("status") or model.retail_status.value,
                "segment": current_generation.segment.value if current_generation else "UNKNOWN",
                "body_type": model.body_type.value,
                "retail_price_min": min(current_amounts) if current_amounts else None,
                "retail_price_max": max(current_amounts) if current_amounts else None,
                "payload": {
                    **to_jsonable(asdict(model)),
                    "brand": {"id": brand.id, "slug": brand_map.get(brand.id, {}).get("slug") or _slug(brand.id),
                              "name_en": brand.name_en, "name_th": brand.name_th},
                    "generation": current_generation.code if current_generation else None,
                    "seats": current_generation.seats if current_generation else None,
                    "powertrains": powertrains,
                    "market_position": (editorial.get("market_position")
                                        or brand.brand_segment.value.title()),
                    "image_url": editorial.get("image_url"),
                    "consumer_description": editorial.get("consumer_description"),
                    "featured": bool(editorial.get("featured")),
                    "production_type": (import_types[0] if len(import_types) == 1
                                        else "MIXED" if import_types else editorial.get("production_type")),
                    "production_country": (origin_countries[0] if len(origin_countries) == 1
                                           else "MIXED" if origin_countries else editorial.get("production_country")),
                    "launch_year": (int(current_generation.launched[:4])
                                    if current_generation and current_generation.launched
                                    else editorial.get("launch_year")),
                    "launch_quarter": editorial.get("launch_quarter"),
                },
            })
            for generation in generation_rows:
                generations.append({
                    "canonical_id": generation.id, "model_id": model.id,
                    "code": generation.code, "segment": generation.segment.value,
                    "launched": generation.launched, "ended": generation.ended,
                    "payload": to_jsonable(asdict(generation)),
                })
                for trim in sorted(trims_by_generation.get(generation.id, []), key=lambda row: row.id):
                    detail = self.master.detail(trim.id, as_of=as_of)
                    quote = self.master.prices.campaign_quote(trim.id, as_of=as_of)
                    trims.append({
                        "canonical_id": trim.id, "model_id": model.id,
                        "generation_id": generation.id, "variant_id": trim.variant_id,
                        "name": trim.name, "powertrain": trim.powertrain.value,
                        "status": ("discontinued" if generation.ended and generation.ended <= as_of.isoformat()
                                   else "current"),
                        "payload": detail,
                        "current_list_price": detail["current_list_price"],
                        "campaign_quote": quote,
                        "price_history": detail["price_history"],
                        "source_refs": to_jsonable(trim.source_refs),
                    })
                    for record in self.master.prices.records_for(trim.id):
                        prices.append(_price_row(record))
                    for fact in detail["comparable_specs"]:
                        spec_facts.append({"trim_id": trim.id, **fact})

        semantic = {
            "schema_version": SCHEMA_VERSION, "year": self.year,
            "canonical_revision": self.canonical_revision,
            "as_of": as_of.isoformat(), "brands": brands, "models": models,
            "generations": generations, "market_trims": trims,
            "price_ledger": prices, "spec_facts": spec_facts,
        }
        source_hash = sha256(json.dumps(
            semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        counts = {key: len(semantic[key]) for key in
                  ("brands", "models", "generations", "market_trims", "price_ledger", "spec_facts")}
        return {
            **semantic,
            "release_id": f"vehicle-{self.year}-{source_hash[:16]}",
            "source_hash": source_hash,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "counts": counts,
            "crosswalk": {
                "brands": {key: value["id"] for key, value in sorted(brand_map.items())},
                "models": {key: value["id"] for key, value in sorted(model_map.items())},
                "review": review,
                "counts": {
                    "mapped_brands": len(brand_map), "mapped_models": len(model_map),
                    "review_items": len(review),
                },
            },
        }


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--revision", default="working-tree")
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--overrides", type=Path)
    args = parser.parse_args(argv)
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    overrides = (json.loads(args.overrides.read_text(encoding="utf-8"))
                 if args.overrides else {})
    release = ReleaseBuilder(inventory, year=args.year,
                             canonical_revision=args.revision,
                             overrides=overrides).build(as_of=args.as_of)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "release_id": release["release_id"], "source_hash": release["source_hash"],
        "counts": release["counts"], "crosswalk": release["crosswalk"]["counts"],
        "output": str(args.out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
