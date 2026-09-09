"""Phase-E projection from canonical Vehicle Master into TDR serving grain.

The output of this module is deliberately *not* another master.  It is a
versioned, deterministic payload for the Supabase serving tables.  Identity,
retail trim specification and price truth remain in the canonical catalog and
PriceLedger.
"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Optional

from .catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from .pricing import PriceLedger
from .taxonomy import RetailStatus


class ServingProjectionError(ValueError):
    pass


_BODY_TO_TDR = {
    "HATCHBACK": "Hatchback",
    "SEDAN": "Sedan",
    "CROSSOVER": "Crossover",
    "PPV": "PPV",
    "OFFROAD": "Offroad ladder frame",
    "COUPE": "Coupe",
    "MPV": "MPV",
    "PICKUP": "Pickup truck",
    "WAGON": "Wagon",
    "VAN": "Van",
    "TRUCK": "Truck",
    "OTHER": "Other",
}


def _value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _known(value: Any) -> Any:
    value = _value(value)
    if value in (None, "", "UNKNOWN", "NOT_APPLICABLE"):
        return None
    return value


def _known_consensus(values: Iterable[Any]) -> Any:
    """One known value if all known assertions agree; gaps do not conflict."""
    known = {_known(value) for value in values}
    known.discard(None)
    return next(iter(known)) if len(known) == 1 else None


def _complete_consensus(values: Iterable[Any]) -> Any:
    """One value only when every row asserts it and every assertion agrees."""
    materialized = list(values)
    if not materialized or any(_known(value) is None for value in materialized):
        return None
    known = {_known(value) for value in materialized}
    return next(iter(known)) if len(known) == 1 else None


def _quarter(iso_date: Optional[str]) -> Optional[str]:
    if not iso_date:
        return None
    month = int(iso_date[5:7])
    return f"Q{((month - 1) // 3) + 1}"


def _generation_for_serving(catalog: Catalog, model_id: str, as_of: date):
    generations = list(catalog.generations_of(model_id))
    if not generations:
        raise ServingProjectionError(f"{model_id}: no canonical generation")
    day = as_of.isoformat()
    active = [g for g in generations if not g.ended or g.ended >= day]
    pool = active or generations

    # TDR currently has one serving model row. Pick the newest canonical
    # generation by Thai launch date, but refuse an exact chronology tie rather
    # than silently choose by name/code.
    dated = [g for g in pool if g.launched]
    if dated:
        newest = max(g.launched for g in dated)
        winners = [g for g in dated if g.launched == newest]
        if len(winners) != 1:
            raise ServingProjectionError(
                f"{model_id}: {len(winners)} generations share latest launch {newest}"
            )
        return winners[0]
    if len(pool) == 1:
        return pool[0]
    raise ServingProjectionError(
        f"{model_id}: cannot choose serving generation without launch chronology"
    )


def _retail_status(model: Any) -> Optional[str]:
    status = _value(model.retail_status)
    if status == RetailStatus.CURRENT.value:
        return "current"
    if status == RetailStatus.HISTORICAL.value:
        return "discontinued"
    return None


def _child_status(model: Any, generation: Any, as_of: date) -> str:
    explicit = _retail_status(model)
    if explicit == "discontinued":
        return "discontinued"
    if generation.ended and generation.ended < as_of.isoformat():
        return "discontinued"
    return "current"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def build_model_serving_projection(
    model_id: str,
    *,
    data_dir: Path | str = DATA_DIR,
    year: int = DEFAULT_YEAR,
    as_of: Optional[date] = None,
) -> dict[str, Any]:
    """Build one deterministic serving payload from canonical truth.

    `as_of` affects dated LIST_PRICE selection and generation activity. It is
    metadata only; the projection hash covers the served facts themselves, so
    an unchanged model does not churn merely because another day passed.
    """
    when = as_of or date.today()
    catalog = Catalog.load(data_dir, year)
    model = catalog.models.get(model_id)
    if model is None:
        raise ServingProjectionError(f"unknown canonical model {model_id!r}")
    brand = catalog.brands[model.brand_id]
    generation = _generation_for_serving(catalog, model_id, when)
    variants = [v for v in catalog.variants_of(model_id)
                if v.generation_id == generation.id]
    trims = [t for t in catalog.trims_of(model_id)
             if t.generation_id == generation.id]
    prices = PriceLedger.load(data_dir, year=year, catalog=catalog)

    variant_rows: list[dict[str, Any]] = []
    for variant in variants:
        linked = [t for t in trims if t.variant_id == variant.id]
        variant_rows.append({
            "canonical_id": variant.id,
            "label": variant.name,
            "powertrain_type": _known(variant.powertrain),
            "engine_code": _known_consensus(t.engine_code for t in linked),
            "displacement_cc": variant.engine_cc,
            "battery_capacity_kwh": variant.battery_kwh,
            "transmission": _known_consensus(t.transmission for t in linked),
            "drivetrain": _known(variant.drivetrain),
            "import_type": _known(variant.import_type),
            "origin_country": _known(variant.origin_country),
        })

    trim_rows: list[dict[str, Any]] = []
    current_list_records = []
    for index, trim in enumerate(trims):
        listed = prices.current_list_price(trim.id, as_of=when)
        current_list_records.append(listed)
        trim_rows.append({
            "canonical_id": trim.id,
            "canonical_variant_id": trim.variant_id,
            "name": trim.name,
            "price_baht": listed.amount_thb if listed else None,
            "status": _child_status(model, generation, when),
            "seats_override": (trim.seats if trim.seats and trim.seats != generation.seats else None),
            "sort_order": index,
            "tire_size_front": trim.tire_front or None,
            "tire_size_rear": trim.tire_rear or None,
            "wheel_size_front": trim.wheel_front or None,
            "wheel_size_rear": trim.wheel_rear or None,
            "list_price_source": listed.source if listed else None,
            "list_price_source_ref": listed.source_ref if listed else None,
            "list_price_effective_from": listed.effective_from if listed else None,
            "list_price_observed_at": listed.observed_at if listed else None,
        })

    powertrains = sorted({str(_known(v.powertrain)) for v in variants
                          if _known(v.powertrain) is not None})
    production_type = _complete_consensus(v.import_type for v in variants)
    production_country = _complete_consensus(v.origin_country for v in variants)

    # Model-level price range is safe only when every canonical MarketTrim in
    # the serving generation has a current LIST_PRICE. Partial coverage must not
    # turn one known grade into a fake full-model price range.
    complete_prices = bool(trims) and all(current_list_records)
    amounts = [r.amount_thb for r in current_list_records if r]
    price_dates = [r.effective_from or r.observed_at for r in current_list_records
                   if r and (r.effective_from or r.observed_at)]

    model_row = {
        "canonical_id": model.id,
        "canonical_generation_id": generation.id,
        "brand_canonical_id": brand.id,
        "name_en": model.name_en,
        "name_th": model.name_th or None,
        "generation": generation.code or generation.id.rsplit(".", 1)[-1],
        "body_type": _BODY_TO_TDR.get(str(_value(model.body_type)), "Other"),
        "segment": _known(generation.segment),
        "powertrain": powertrains[0] if len(powertrains) == 1 else None,
        "powertrains": powertrains,
        "production_type": production_type,
        "production_country": production_country,
        "launch_date": generation.launched,
        "launch_quarter": _quarter(generation.launched),
        "launch_month": int(generation.launched[5:7]) if generation.launched else None,
        "launch_year": int(generation.launched[:4]) if generation.launched else None,
        "seats": generation.seats,
        "length_mm": _known_consensus(t.length_mm for t in trims),
        "width_mm": _known_consensus(t.width_mm for t in trims),
        "wheelbase_mm": _known_consensus(t.wheelbase_mm for t in trims),
        "retail_price_min": min(amounts) if complete_prices else None,
        "retail_price_max": max(amounts) if complete_prices else None,
        "retail_price_updated_month": (int(max(price_dates)[5:7])
                                       if complete_prices and price_dates else None),
        "retail_price_updated_year": (int(max(price_dates)[:4])
                                      if complete_prices and price_dates else None),
        # `None` means canonical retail status is not verified, so the SQL apply
        # function preserves the existing TDR editorial/current-state choice.
        "status": _retail_status(model),
    }

    served = {
        "schema_version": 1,
        "canonical_model_id": model.id,
        "canonical_generation_id": generation.id,
        "model": model_row,
        "variants": variant_rows,
        "trims": trim_rows,
    }
    projection_hash = _hash_payload(served)
    return {
        **served,
        "year": year,
        "as_of": when.isoformat(),
        "projection_hash": projection_hash,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Export one canonical TDR serving projection")
    parser.add_argument("model_id", help="canonical model id, e.g. jaecoo.jaecoo_5_ev")
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--as-of", dest="as_of")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    when = date.fromisoformat(args.as_of) if args.as_of else None
    payload = build_model_serving_projection(args.model_id, year=args.year, as_of=when)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["ServingProjectionError", "build_model_serving_projection"]
