"""Resolves a bulk ECO Sticker export row's brand/model/generation identity
against the catalogue.

The export names a vehicle the way its manufacturer filed it -- "ALPHARD
HYBRID G 2WD CAR" is brand, model and grade run together in one cell -- and
the catalogue stores those three as separate things. ``plan_row`` decides,
for every row, which of three situations it is in:

  MATCHED     the row is an existing MarketTrim, so its specs attach to it
  NEW_TRIM    the model exists but this grade does not, so create it
  UNRESOLVED  the brand, model or generation cannot be resolved

Brand and model matching is not reimplemented here: ``ecosticker_ingest``
already does it, and has been run against real harvests for longer than this
module has existed.

Compiling a resolved row into canonical input commands (UPSERT_MODEL_BUNDLE,
APPEND_SPEC, APPEND_PRICE) is not this module's job -- ``vehreg.source_import``
does that, from a ``SourceRow``/``RowOutcome`` this module's own ``plan_row``
feeds, shared with every other source rather than reimplemented per source.
This module used to compile ECO's rows too (``commands_for``/
``batches_from_plan``, plus ``plan_import``'s own spec-dedup and price
grouping); that duplicated ``vehreg.source_import``'s writer-facing half
under a second, ECO-only set of rules, so it was retired once
``vehreg.source_import.spec_commands_from_outcomes``/
``price_commands_from_outcomes`` could do the same job for every source that
resolves through this file's identity step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Optional

from .catalog import Catalog
from .comparable_specs import SpecRegistry
from .ecosticker_export import NormalizedVehicle, applicable_specs, normalize_row
from .ecosticker_ingest import _brand_candidates, _model_candidates
from .normalize import fold, trim_identity

MATCHED = "MATCHED"
NEW_TRIM = "NEW_TRIM"
UNRESOLVED = "UNRESOLVED"


def trim_label(model_raw: str, model_surface: str) -> str:
    """What is left of the source's model cell once the model name is removed.

    "ALPHARD HYBRID G 2WD CAR" minus the catalogue's "Alphard" is "HYBRID G
    2WD CAR", which is the grade. The source's own casing is kept, because
    this becomes a trim name a person reads and "carrera coupe" is not how
    anyone writes it.

    Matching is done on the raw string rather than folded tokens: ``fold``
    splits letters from digits, so a model named "Z9GT" becomes three tokens
    and never lines up with the one word it came from. Whole-phrase removal
    handles the usual case ("Jaecoo 5 EV Long Range Max"), and word-by-word
    removal covers a catalogue name the source abbreviates -- "Porsche 911"
    against a cell that only says "911 CARRERA COUPE".
    """
    text = " ".join(str(model_raw or "").split())
    surface = " ".join(str(model_surface or "").split())
    if not surface:
        return text

    whole = re.sub(rf"(?i)(?:(?<=\s)|^){re.escape(surface)}(?:(?=\s)|$)", " ", text, count=1)
    if whole != text:
        return " ".join(whole.split())

    words = text.split()
    wanted = {word.casefold() for word in surface.split()}
    kept = [word for word in words if word.casefold() not in wanted]
    return " ".join(kept).strip() if kept else text


@dataclass
class RowPlan:
    source_id: str
    brand_raw: str
    model_raw: str
    status: str
    vehicle: NormalizedVehicle
    model_id: Optional[str] = None
    brand_id: Optional[str] = None
    brand_name_en: str = ""
    generation_id: Optional[str] = None
    trim_id: Optional[str] = None
    trim_name: str = ""
    specs: dict[str, Any] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)
    reason: str = ""


def _match_trim(catalog: Catalog, model_id: str, label: str,
                powertrain: str) -> Optional[str]:
    """An existing trim of this model with the same grade and powertrain.

    Powertrain has to agree: "Corolla Cross 1.8 Hybrid" and "Corolla Cross
    1.8" are different products, and a catalogue that merged them would report
    one car's economy against the other's price.
    """
    wanted = fold(label)
    if not wanted:
        return None
    for trim in catalog.trims_of(model_id):
        if trim.powertrain.value != powertrain:
            continue
        name = fold(trim.name)
        if name and (name == wanted or name in wanted or wanted in name):
            return trim.id
    return None


def plan_row(raw: dict, catalog: Catalog, registry: SpecRegistry) -> RowPlan:
    vehicle = normalize_row(raw)
    specs, dropped = applicable_specs(vehicle, registry)
    plan = RowPlan(
        source_id=vehicle.source_id, brand_raw=vehicle.brand_raw,
        model_raw=vehicle.model_raw, status=UNRESOLVED, vehicle=vehicle,
        specs=specs, dropped=dropped,
    )
    if not vehicle.powertrain:
        plan.reason = "ไม่สามารถระบุ powertrain จากข้อมูลต้นทางได้"
        return plan

    brand_ids = _brand_candidates(catalog, vehicle.brand_raw)
    if not brand_ids:
        plan.reason = f"ไม่พบแบรนด์ {vehicle.brand_raw!r} ในแคตตาล็อก"
        return plan

    hits = _model_candidates(catalog, brand_ids, vehicle.model_raw)
    if not hits:
        plan.reason = f"ไม่พบรุ่น {vehicle.model_raw!r} ใต้แบรนด์ที่จับคู่ได้"
        return plan
    if len(hits) > 1:
        plan.reason = ("จับคู่ได้หลายรุ่น: "
                       + ", ".join(hit.model_id for hit in hits))
        return plan

    hit = hits[0]
    plan.model_id = hit.model_id
    plan.brand_id = hit.brand_id
    plan.brand_name_en = catalog.brands[hit.brand_id].name_en
    plan.trim_name = trim_label(vehicle.model_raw, hit.surface) or vehicle.model_raw

    existing = _match_trim(catalog, hit.model_id, plan.trim_name, vehicle.powertrain)
    if existing:
        plan.status = MATCHED
        plan.trim_id = existing
        plan.generation_id = catalog.trims[existing].generation_id
        return plan

    generations = catalog.generations_of(hit.model_id)
    if len(generations) != 1:
        plan.reason = (f"{hit.model_id} มี {len(generations)} generation "
                       "จึงเลือกให้อัตโนมัติไม่ได้")
        return plan

    plan.status = NEW_TRIM
    plan.generation_id = generations[0].id
    plan.trim_id = trim_identity(generations[0].id, None, plan.trim_name,
                                 vehicle.powertrain)
    return plan


__all__ = [
    "MATCHED", "NEW_TRIM", "UNRESOLVED", "RowPlan", "plan_row", "trim_label",
]
