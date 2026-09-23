from __future__ import annotations

from datetime import date
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.import_source import spec_commands_from_outcomes
from vehreg.battlecard import BattleCardEngine
from vehreg.comparable_specs import (
    ComparisonRule, ECOCandidateSpecStore, SpecFact, SpecFieldDefinition,
    SpecRegistry, ValueState, VerificationStatus,
    is_identified_manufacturing_plant, spec_conflict_key,
)
from vehreg.ecosticker_export import normalize_row
from vehreg.ecosticker_import import UNRESOLVED, plan_row
from vehreg.source_import import PATCHED, RowOutcome, SourceRow


def _co2_registry() -> SpecRegistry:
    return SpecRegistry([SpecFieldDefinition(
        key="emissions.co2_g_km", group="emissions", label_th="CO2", label_en="CO2",
        value_type=ValueState.__mro__[1].__subclasses__()[0] if False else __import__(
            "vehreg.comparable_specs", fromlist=["ValueType"]).ValueType.NUMBER,
        comparison_rule=ComparisonRule.LOWER_BETTER, canonical_unit="g/km",
        comparison_qualifiers=("measurement_basis",),
    )])


@pytest.mark.parametrize("bad_id", ["", None, float("nan"), "   ", "-", "N/A"])
def test_missing_eco_source_id_is_rejected_before_matching(bad_id):
    plan = plan_row({"id": bad_id}, None, None)
    assert plan.status == UNRESOLVED
    assert plan.source_id == ""
    assert plan.reason == "missing ECO source id"


def test_factory_and_gear_count_semantics_are_conservative():
    company = normalize_row({
        "id": "company", "factory": "Toyota Motor Thailand Co., Ltd.",
        "gear_name": "CVT Automatic", "gear_speed": 7,
    })
    assert company.notes["factory"] == "Toyota Motor Thailand Co., Ltd."
    assert "manufacturing.factory" not in company.specs
    assert "powertrain.gear_count" not in company.specs

    plant = normalize_row({
        "id": "plant", "factory": "BMW AG Plant Dingolfing",
        "gear_name": "Automatic 8 speed", "gear_speed": 8,
    })
    assert plant.specs["manufacturing.factory"] == "BMW AG Plant Dingolfing"
    assert plant.specs["powertrain.gear_count"] == 8


def test_shared_factory_predicate_rejects_companies_and_accepts_sites():
    assert not is_identified_manufacturing_plant("Zhejiang Geely Automobile Co., Ltd.")
    assert not is_identified_manufacturing_plant("บริษัท โตโยต้า มอเตอร์ ประเทศไทย จำกัด")
    assert is_identified_manufacturing_plant("BMW AG Plant Dingolfing")
    assert is_identified_manufacturing_plant("โรงงานสมุทรปราการ")


def test_importer_withholds_conflict_against_existing_ledger_fact():
    registry = _co2_registry()
    row = SourceRow(
        source_id="new", source_kind="ECO", model_id="acme.runner",
        generation_id="acme.runner.gen1", powertrain="ICE", trim_name="Premium",
        values={},
    )
    outcome = RowOutcome(row=row, status=PATCHED,
                         trim_id="acme.runner.gen1.trim.premium")
    vehicle = normalize_row({"id": "new"})
    vehicle.powertrain = "ICE"
    vehicle.approved_at = "2026-01-01"
    vehicle.specs = {"emissions.co2_g_km": 130.0}
    vehicle.qualifiers = {
        "emissions.co2_g_km": {"measurement_basis": "ECO_STICKER_TH"}}
    existing = SpecFact(
        fact_id="eco:old:emissions.co2_g_km",
        trim_id="acme.runner.gen1.trim.premium",
        field_key="emissions.co2_g_km", value_state=ValueState.KNOWN,
        value=120.0, unit="g/km",
        qualifiers={"measurement_basis": "ECO_STICKER_TH"},
        observed_at="2026-01-01", verification_status=VerificationStatus.VERIFIED,
        source="ecosticker", source_ref="https://example.invalid/old",
        source_locator="https://example.invalid/old",
    )
    commands, stats, conflicts = spec_commands_from_outcomes(
        [outcome], vehicles={"new": vehicle}, registry=registry,
        existing_facts=[existing])
    assert commands == []
    assert stats["spec_conflicts"] == 1
    assert len(conflicts) == 1


def test_conflict_key_uses_only_registry_comparison_qualifiers():
    definition = _co2_registry().fields["emissions.co2_g_km"]
    a = spec_conflict_key(
        definition, trim_id="t", field_key=definition.key,
        qualifiers={"measurement_basis": "WLTP", "ignored": "a"}, start="2026-01-01")
    b = spec_conflict_key(
        definition, trim_id="t", field_key=definition.key,
        qualifiers={"measurement_basis": "WLTP", "ignored": "b"}, start="2026-01-01")
    assert a == b


def _factory_registry() -> SpecRegistry:
    from vehreg.comparable_specs import ValueType
    return SpecRegistry([SpecFieldDefinition(
        key="manufacturing.factory", group="manufacturing",
        label_th="Factory", label_en="Manufacturing plant",
        value_type=ValueType.TEXT, comparison_rule=ComparisonRule.INFORMATION_ONLY,
    )])


def _fake_master(factory: str):
    trim = SimpleNamespace(
        id="acme.runner.gen1.trim.premium", name="Premium",
        powertrain=SimpleNamespace(value="ICE"), drivetrain=SimpleNamespace(value="FWD"),
        engine_cc=None, battery_kwh=None, transmission=None, seats=None,
        length_mm=None, width_mm=None, height_mm=None, wheelbase_mm=None,
        tire_front=None, tire_rear=None, source_refs={},
    )
    catalog = SimpleNamespace(
        trims={trim.id: trim},
        model_for_trim=lambda _tid: SimpleNamespace(id="acme.runner", name_en="Runner"),
        brand_for_trim=lambda _tid: SimpleNamespace(name_en="Acme"),
    )
    eco = SimpleNamespace(
        source_ref="source-1", declared_total_weight_kg=None, tire_size=None,
        battery_chemistry=None, battery_supplier=None, battery_voltage_v=None,
        factory=factory, rated_range_km=None,
    )
    master = SimpleNamespace(
        catalog=catalog, eco={trim.id: eco},
        comparable_specs=SimpleNamespace(resolved=lambda *_a, **_k: []),
        prices=SimpleNamespace(current_list_price=lambda *_a, **_k: None,
                               records_for=lambda *_a, **_k: []),
    )
    return master, trim.id


def test_legacy_battlecard_uses_same_factory_semantics():
    engine = BattleCardEngine(_factory_registry())
    master, trim_id = _fake_master("Toyota Motor Thailand Co., Ltd.")
    view = engine._trim_view(master, trim_id, date(2026, 9, 23))
    assert not any(v["field_key"] == "manufacturing.factory" for v in view["values"])
    master, trim_id = _fake_master("BMW AG Plant Dingolfing")
    view = engine._trim_view(master, trim_id, date(2026, 9, 23))
    assert any(v["field_key"] == "manufacturing.factory" for v in view["values"])


def _write_gz(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_provisional_candidate_reader_uses_same_factory_semantics(tmp_path: Path):
    cohort_dir = tmp_path / "2026/product/comparable_specs/cohorts"
    cohort_dir.mkdir(parents=True)
    (cohort_dir / "c_crossover.json").write_text(json.dumps({
        "id": "c_crossover", "segment": "C", "body_type": "CROSSOVER",
        "model_ids": ["acme.runner"], "representative_source_ids": {}, "notes": "",
    }), encoding="utf-8")
    snap = tmp_path / "2026/ingest/ecosticker/snapshots/2026-09-08"
    normalized = [
        {"source_id": "company", "matched_model_id": "acme.runner",
         "matched_generation_id": "acme.runner.gen1", "model_raw": "Runner Company",
         "powertrain_candidate": "ICE", "review_status": "MATCHED",
         "source_url": "https://example.invalid/company", "snapshot_date": "2026-09-08",
         "recommended_price_thb": None, "factory": "Toyota Motor Thailand Co., Ltd."},
        {"source_id": "plant", "matched_model_id": "acme.runner",
         "matched_generation_id": "acme.runner.gen1", "model_raw": "Runner Plant",
         "powertrain_candidate": "ICE", "review_status": "MATCHED",
         "source_url": "https://example.invalid/plant", "snapshot_date": "2026-09-08",
         "recommended_price_thb": None, "factory": "BMW AG Plant Dingolfing"},
    ]
    _write_gz(snap / "normalized.jsonl.gz", normalized)
    _write_gz(snap / "raw.jsonl.gz", [{"source_id": r["source_id"], "detail": {}}
                                      for r in normalized])
    store = ECOCandidateSpecStore.load(
        tmp_path, 2026, registry=_factory_registry(), snapshot_date="2026-09-08")
    company_keys = {v["field_key"] for v in store.get("company")["values"]}
    plant_values = {v["field_key"]: v["value"] for v in store.get("plant")["values"]}
    assert "manufacturing.factory" not in company_keys
    assert plant_values["manufacturing.factory"] == "BMW AG Plant Dingolfing"
