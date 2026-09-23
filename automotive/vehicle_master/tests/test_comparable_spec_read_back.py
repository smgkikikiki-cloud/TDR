"""Read-back compatibility: the ECO import writes into the exact contract
the comparable-spec read path already serves from, and nothing about this
importer's own fixes (gear_count/factory filtering, the trim-id-aware
idempotency check) breaks a reader that was already working.

The path under test, end to end, on the real pipeline:

    ECO source
    -> normalize_row / applicable_specs (SourceRow.specs)
    -> APPEND_SPEC (via spec_commands_from_outcomes)
    -> CanonicalInputPipeline.apply()
    -> SpecLedger.load() (a fresh read, not the ledger apply() staged)
    -> SpecLedger.resolved(trim_id, registry, as_of)
    -> registry.profiles (the profile field-list mechanism)

No new reader is added here and none of this asserts against raw fact files
or a second copy of SpecLedger's own resolution logic -- every assertion
reads through resolved(), the same call a real consumer makes.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from vehreg.catalog import Catalog
from vehreg.comparable_specs import SpecLedger, SpecRegistry
from vehreg.ecosticker_import import plan_row
from vehreg.input_pipeline import CanonicalInputPipeline
from vehreg.source_import import (
    PATCHED, ExistingTrim, RowOutcome, SourceRow, batches_from_commands,
    commands_from_outcomes, resolve_rows, resolved_trim_id,
    spec_commands_from_outcomes,
)

YEAR = 2026
REAL_REGISTRY = (Path(__file__).resolve().parents[1] / "vehreg" / "data" / str(YEAR)
                 / "product" / "comparable_specs" / "registry.json")
REAL_PROFILES = (Path(__file__).resolve().parents[1] / "vehreg" / "data" / str(YEAR)
                 / "product" / "comparable_specs" / "profiles.json")


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    _write(data / str(YEAR) / "models" / "acme.json", {
        "brand": {"id": "acme", "name_en": "Acme", "name_th": "",
                  "brand_segment": "MASS", "oem_group": "UNKNOWN",
                  "brand_origin": "TH", "trim_detail": False, "aliases": []},
        "models": [{
            "id": "runner", "name_en": "Runner", "name_th": "", "nameplate": "",
            "body_type": "SEDAN", "cab_type": "NOT_APPLICABLE",
            "registration_type": "", "market_scope": "CORE", "aliases": [],
            "generations": [{
                "code": "gen1", "segment": "B", "seats": 5,
                "launched": "2025-01-01", "ended": None,
                "variants": [{"id": "v1", "name": "Runner 1.5 ICE", "powertrain": "ICE",
                    "drivetrain": "FWD", "engine_cc": 1496, "battery_kwh": None,
                    "price_thb": None, "price_min_thb": None, "price_max_thb": None,
                    "import_type": "CKD", "origin_country": "TH", "price_note": "",
                    "aliases": []}],
                "trims": [{"id": "premium", "name": "Premium", "powertrain": "ICE",
                           "aliases": [], "source_refs": {}}],
            }],
        }],
    })
    root = data / str(YEAR) / "product" / "comparable_specs"
    root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REAL_REGISTRY, root / "registry.json")
    shutil.copyfile(REAL_PROFILES, root / "profiles.json")
    return data


@pytest.fixture
def catalog(tree: Path) -> Catalog:
    return Catalog.load(tree, YEAR)


@pytest.fixture
def registry(tree: Path) -> SpecRegistry:
    return SpecRegistry.load(tree, YEAR)


def eco_row(model: str, **overrides) -> dict:
    base = {
        "id": "3283e6a6-999d-4964-91d2-064f22b13369",
        "brand": "ACME", "model": model, "cartype_name": "ICE",
        "car_style": "รถยนต์นั่ง 4 ประตู (Sedan)", "company_name": "Acme Co",
        "model_year": "2026",
        # A legal entity, exactly the shape real ECO data mostly states --
        # not an identified plant, so it must not resolve as one.
        "factory": "บริษัท เอซีเอ็ม มอเตอร์ (ประเทศไทย) จำกัด",
        "recomend_retail_price_new": "899000", "tax_rate_new": "0.15",
        "engine_name": "แก๊สโซลีน", "fuel_name": "เชื้อเพลิงผสม (เบนซิน-E20)",
        # CVT: gear_speed is stated but must not resolve as gear_count.
        "gear_name": "เกียร์อัตโนมัติ ประเภท CVT", "gear_speed": "7",
        "capacity_cylinder": "1496.0",
        "car_seats": "5", "car_length": "4500", "car_width": "1780",
        "car_height": "1460", "total_weight": "1600", "wheel_size": "205/55R16",
        "emissions_CO2": "120", "energy_combined_rate": "5.2",
        "std_tis": "1", "car_equip_safety": "ABS; ESC/VSA/VSC",
        "approve_date": "2026-06-01T09:00:00+07:00",
    }
    base.update(overrides)
    return base


def build(raw_rows: list[dict], catalog: Catalog, registry: SpecRegistry):
    rows = []
    for raw in raw_rows:
        plan = plan_row(raw, catalog, registry)
        assert plan.status != "UNRESOLVED", plan.reason
        rows.append(SourceRow(
            source_id=plan.source_id, source_kind="ECO",
            model_id=plan.model_id, generation_id=plan.generation_id or "",
            powertrain=plan.vehicle.powertrain or "", trim_name=plan.trim_name or "",
            values=dict(plan.vehicle.specs), specs=dict(plan.specs),
            qualifiers=dict(plan.vehicle.qualifiers), observed_at=plan.vehicle.approved_at,
            source_ref=plan.vehicle.source_url, price_thb=plan.vehicle.price_thb,
        ))
    trims = [ExistingTrim(canonical_id=t.id, model_id=model_id, generation_id=t.generation_id,
                          name=t.name, powertrain=t.powertrain.value,
                          columns={"source_refs": {k: list(v) for k, v in (t.source_refs or {}).items()}},
                          source_ids=tuple(str(v) for vs in (t.source_refs or {}).values() for v in vs))
            for model_id in catalog.models for t in catalog.trims_of(model_id)]
    generation_codes = {g.id: g.code for model_id in catalog.models
                        for g in catalog.generations_of(model_id) if g.code}
    outcomes = resolve_rows(rows, trims, known_generations=generation_codes)
    model_commands, stranded = commands_from_outcomes(
        outcomes, generation_codes=generation_codes,
        existing_by_trim={t.canonical_id: t for t in trims})
    assert not stranded, stranded
    spec_commands = spec_commands_from_outcomes(outcomes, registry=registry, existing_facts={})
    return outcomes, model_commands + spec_commands


def apply(data: Path, commands: list[dict], *, prefix: str):
    batches = batches_from_commands(
        commands, year=YEAR, source_kind="ECO", source_ref="eco-book.xlsx",
        batch_prefix=prefix, submitted_at="2026-09-21T00:00:00+00:00")
    for batch in batches:
        result = CanonicalInputPipeline(data).apply(batch)
        assert result.status == "APPLIED", result
    return batches


def test_read_back_through_resolved_and_the_profile_mechanism(tree, catalog, registry):
    premium_row = eco_row("Runner Premium")
    sport_row = eco_row("Runner Sport", id="cccccccc-1111-1111-1111-111111111111")
    outcomes, commands = build([premium_row, sport_row], catalog, registry)
    apply(tree, commands, prefix="readback-1")

    premium_outcome = next(o for o in outcomes if o.row.source_id == premium_row["id"].lower())
    sport_outcome = next(o for o in outcomes if o.row.source_id == sport_row["id"].lower())
    premium_trim_id = resolved_trim_id(premium_outcome)
    sport_trim_id = resolved_trim_id(sport_outcome)

    catalog_after = Catalog.load(tree, YEAR)
    ledger = SpecLedger.load(tree, YEAR, registry=registry, catalog=catalog_after)
    resolved_by_key = {f.field_key: f for f in ledger.resolved(premium_trim_id)}

    # 1. A newly imported supported category is visible through the normal
    #    reader -- not just written, but resolvable.
    assert resolved_by_key["emissions.co2_g_km"].value == 120.0
    assert resolved_by_key["emissions.co2_g_km"].qualifiers.get(
        "measurement_basis") == "ECO_STICKER_TH"

    # 2. Valid existing fields continue to resolve exactly as before.
    assert resolved_by_key["vehicle.seats"].value == 5
    assert resolved_by_key["engine.displacement_cc"].value == 1496

    # 3. CVT pseudo gear count is absent.
    assert "powertrain.gear_count" not in resolved_by_key
    assert resolved_by_key["powertrain.transmission"].value == "CVT"

    # 4. Ambiguous ECO factory data (a legal entity, not an identified
    #    plant) is not exposed as manufacturing.factory.
    assert "manufacturing.factory" not in resolved_by_key

    # 5. The profile mechanism: reading a named profile's field list against
    #    resolved() behaves as any real consumer's read would.
    core_fields = set(registry.profiles["c_crossover_core"])
    assert "manufacturing.factory" in core_fields  # the profile still asks for it
    on_profile = {key: fact for key, fact in resolved_by_key.items() if key in core_fields}
    assert "vehicle.seats" in on_profile and "emissions.co2_g_km" in on_profile
    assert "manufacturing.factory" not in on_profile, \
        "the profile lists the field; this row must not populate it from a legal-entity value"

    # 6. Corrected trim reassignment: the same source record's facts, moved
    #    onto a different (also real) trim by a later identity correction,
    #    resolve on the new trim and no longer resolve on the old one.
    existing_facts = {
        f.fact_id: {"trim_id": f.trim_id, "value_state": f.value_state.value,
                    "value": f.value, "unit": f.unit,
                    "qualifiers": f.qualifiers, "observed_at": f.observed_at}
        for f in ledger.facts if f.trim_id == premium_trim_id
    }
    corrected_outcome = RowOutcome(row=premium_outcome.row, status=PATCHED, trim_id=sport_trim_id)
    revised = spec_commands_from_outcomes(
        [corrected_outcome], registry=registry, existing_facts=existing_facts)
    assert revised
    apply(tree, revised, prefix="readback-2")

    final_ledger = SpecLedger.load(tree, YEAR, registry=registry, catalog=Catalog.load(tree, YEAR))
    old_trim_resolved = {f.field_key for f in final_ledger.resolved(premium_trim_id)}
    new_trim_resolved = {f.field_key for f in final_ledger.resolved(sport_trim_id)}
    assert "emissions.co2_g_km" not in old_trim_resolved, \
        "the old trim must no longer resolve the revised fact"
    assert "emissions.co2_g_km" in new_trim_resolved, \
        "the corrected trim must resolve the revised fact"
    assert final_ledger.validate() == []
