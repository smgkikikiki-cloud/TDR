"""Plans a bulk ECO Sticker import against the catalogue, then compiles it.

The export names a vehicle the way its manufacturer filed it -- "ALPHARD
HYBRID G 2WD CAR" is brand, model and grade run together in one cell -- and
the catalogue stores those three as separate things. This module decides, for
every row, which of three situations it is in:

  MATCHED     the row is an existing MarketTrim, so its specs attach to it
  NEW_TRIM    the model exists but this grade does not, so create it
  UNRESOLVED  the brand, model or generation cannot be resolved

and then compiles the first two into canonical input batches. The third is
reported for a person to look at rather than being guessed at, because a
wrongly attached specification is harder to notice, and harder to undo, than a
missing one.

Brand and model matching is not reimplemented here: ``ecosticker_ingest``
already does it, and has been run against real harvests for longer than this
module has existed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable, Optional

from .catalog import Catalog
from .comparable_specs import SpecRegistry
from .ecosticker_export import NormalizedVehicle, applicable_specs, normalize_row
from .ecosticker_ingest import _brand_candidates, _model_candidates
from .normalize import fold, trim_identity

#: How many commands one batch carries. The input pipeline stages a whole
#: batch in a temp tree and applies it atomically, so a batch is also the unit
#: of "all of this landed or none of it did"; a few hundred keeps a failure
#: readable and a diff reviewable.
DEFAULT_BATCH_SIZE = 200

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


@dataclass
class ImportPlan:
    rows: list[RowPlan] = field(default_factory=list)

    def of(self, status: str) -> list[RowPlan]:
        return [row for row in self.rows if row.status == status]

    def summary(self) -> dict[str, int]:
        counts = {MATCHED: 0, NEW_TRIM: 0, UNRESOLVED: 0}
        for row in self.rows:
            counts[row.status] = counts.get(row.status, 0) + 1
        counts["spec_facts"] = sum(len(row.specs) for row in self.rows
                                   if row.status != UNRESOLVED)
        counts["rows"] = len(self.rows)
        return counts


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


def plan_import(rows: Iterable[dict], catalog: Catalog,
                registry: SpecRegistry) -> ImportPlan:
    plan = ImportPlan()
    for raw in rows:
        plan.rows.append(plan_row(raw, catalog, registry))

    # One source row per trim. The export occasionally files the same grade
    # twice (a re-approval keeps the old row), and two rows writing the same
    # facts would be an idempotent replay at best and a conflict at worst.
    seen: dict[str, RowPlan] = {}
    for row in plan.rows:
        if row.status == UNRESOLVED or not row.trim_id:
            continue
        first = seen.get(row.trim_id)
        if first is None:
            seen[row.trim_id] = row
            continue
        row.status = UNRESOLVED
        row.reason = (f"ซ้ำกับ source_id {first.source_id} "
                      f"ซึ่งชี้ไปที่ trim เดียวกัน ({row.trim_id})")
    return plan


def _trim_row(plan: RowPlan) -> dict[str, Any]:
    """The MarketTrim patch for one planned row.

    Only the columns MarketTrim owns, and only where the export actually said
    something. `id` is sent for a trim that exists so the writer updates it
    rather than deriving a new identity from a name that may have been
    re-spelled upstream.
    """
    specs = plan.specs
    row: dict[str, Any] = {"name": plan.trim_name, "powertrain": plan.vehicle.powertrain}
    if plan.status == MATCHED and plan.trim_id:
        row["canonical_id"] = plan.trim_id
    for key, column in (("vehicle.seats", "seats"),
                        ("vehicle.length_mm", "length_mm"),
                        ("vehicle.width_mm", "width_mm"),
                        ("vehicle.height_mm", "height_mm"),
                        ("engine.displacement_cc", "engine_cc"),
                        ("battery.gross_capacity_kwh", "battery_kwh"),
                        ("powertrain.transmission", "transmission"),
                        ("fitment.tyre_front", "tire_front"),
                        ("fitment.tyre_rear", "tire_rear")):
        if key in specs:
            row[column] = specs[key]
    return row


def commands_for(plan: RowPlan, registry: SpecRegistry, *,
                 observed_at: str) -> list[dict[str, Any]]:
    """One UPSERT_MODEL_BUNDLE, the row's ECO price, and one APPEND_SPEC per value.

    The registry is needed for the unit: a numeric fact must carry exactly the
    field's canonical unit or the writer rejects the whole batch.

    Facts are dated by the row's own ECO approval date, not by the day the
    import runs. The ledger keys a fact by its start, so an import-day stamp
    would file next month's re-import of an unchanged record as a fresh
    specification dated that day -- a change the source never made. Where the
    export states no approval date, ``observed_at`` is the fallback.
    """
    if plan.status == UNRESOLVED or not plan.model_id:
        return []
    # The writer requires all three objects to be present even when only the
    # trim list is being changed: brand and model are sent empty-but-identified
    # so their own fields are left exactly as they are (dict.update() with
    # nothing in it patches nothing).
    commands: list[dict[str, Any]] = [{
        "operation": "UPSERT_MODEL_BUNDLE",
        "canonical_id": plan.model_id,
        "payload": {
            "brand": {"id": plan.brand_id, "name_en": plan.brand_name_en},
            "model": {},
            "generation": {"code": plan.generation_id.rsplit(".", 1)[-1]},
            "variants": [],
            "trims": [_trim_row(plan)],
        },
    }]
    source_ref = plan.vehicle.source_url
    observed = plan.vehicle.approved_at or observed_at

    # The recommended retail price the manufacturer filed with the programme.
    #
    # It is recorded as ECO_STICKER_PRICE and dated to the day the record was
    # approved, never as a current MSRP: an ECO record can be years old, and
    # PriceLedger.current_list_price() resolves LIST_PRICE only, so nothing
    # here can become the price a reader is shown today. It is evidence of
    # what the price was when the car was homologated, which is a real fact
    # with a real date, and that is all it claims to be.
    if plan.vehicle.price_thb and plan.vehicle.price_thb > 0:
        commands.append({
            "operation": "APPEND_PRICE",
            "canonical_id": plan.trim_id,
            "payload": {
                "trim_id": plan.trim_id,
                "amount_thb": int(plan.vehicle.price_thb),
                "price_type": "ECO_STICKER_PRICE",
                "effective_from": observed,
                "observed_at": observed,
                "source": "ecosticker",
                "source_ref": source_ref,
                "notes": ("ราคาแนะนำที่ผู้ผลิตยื่นไว้กับ ECO Sticker ณ วันที่อนุมัติ "
                          "เก็บเป็นหลักฐานเท่านั้น ไม่ใช่ราคาขายปัจจุบัน"),
            },
        })

    for key, value in sorted(plan.specs.items()):
        fact: dict[str, Any] = {
            "trim_id": plan.trim_id,
            "field_key": key,
            "value_state": "KNOWN",
            "value": value,
            "observed_at": observed,
            "verification_status": "VERIFIED",
            "source": "ecosticker",
            "source_ref": source_ref,
            "unit": registry.fields[key].canonical_unit,
        }
        qualifiers = plan.vehicle.qualifiers.get(key)
        if qualifiers:
            fact["qualifiers"] = qualifiers
        commands.append({"operation": "APPEND_SPEC",
                         "canonical_id": plan.trim_id, "payload": fact})
    return commands


def batches_from_plan(plan: ImportPlan, registry: SpecRegistry, *, year: int,
                      actor: str, observed_at: str, batch_prefix: str,
                      batch_size: int = DEFAULT_BATCH_SIZE) -> list[dict[str, Any]]:
    """Canonical input batches, chunked so one failure stays readable.

    A row's commands are never split across two batches: the spec facts have
    to land in the same atomic apply as the trim that carries them.
    """
    batches: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        index = len(batches) + 1
        batches.append({
            "schema_version": 1,
            "batch_id": f"{batch_prefix}-{index:03d}",
            "year": year,
            "actor": actor,
            "submitted_at": f"{observed_at}T00:00:00+00:00",
            "source": {"kind": "ADMIN", "ref": "ecosticker-export"},
            "reason": f"ECO Sticker bulk import {observed_at} ({index})",
            "commands": list(current),
        })
        current.clear()

    for row in plan.rows:
        commands = commands_for(row, registry, observed_at=observed_at)
        if not commands:
            continue
        if current and len(current) + len(commands) > batch_size:
            flush()
        current.extend(commands)
    flush()
    return batches


__all__ = [
    "DEFAULT_BATCH_SIZE", "MATCHED", "NEW_TRIM", "UNRESOLVED",
    "ImportPlan", "RowPlan", "batches_from_plan", "commands_for",
    "plan_import", "plan_row", "trim_label",
]
