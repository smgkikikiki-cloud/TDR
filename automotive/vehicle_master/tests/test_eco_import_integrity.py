from __future__ import annotations

from datetime import date
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from vehreg.battlecard import BattleCardEngine
from vehreg.comparable_specs import (
    ComparisonRule, ECOCandidateSpecStore, SpecFieldDefinition, SpecRegistry,
    ValueType, is_identified_manufacturing_plant,
)
from vehreg.ecosticker_import import UNRESOLVED, plan_row
from vehreg.source_import import (
    PATCHED, RowOutcome, SourceRow, preflight_spec_commands,
    spec_commands_from_outcomes,
)


def _co2_registry() -> SpecRegistry:
    return SpecRegistry([SpecFieldDefinition(
        key="emissions.co2_g_km", group="emissions", label_th="CO2", label_en="CO2",
        value_type=ValueType.NUMBER, comparison_rule=ComparisonRule.LOWER_BETTER,
        canonical_unit="g/km", comparison_qualifiers=("measurement_basis",),
    )])


def _co2_outcome(source_id: str, value: float, *, observed_at: str = "2026-01-01",
                 basis: str = "ECO_STICKER_TH") -> RowOutcome:
    row = SourceRow(
        source_id=source_id, source_kind="ECO", model_id="acme.runner",
        generation_id="acme.runner.gen1", powertrain="ICE", trim_name="Premium",
        values={}, specs={"emissions.co2_g_km": value},
        qualifiers={"emissions.co2_g_km": {"measurement_basis": basis}},
        observed_at=observed_at, source_ref=f"https://example.invalid/{source_id}",
    )
    return RowOutcome(row=row, status=PATCHED, trim_id="acme.runner.gen1.trim.premium")


@pytest.mark.parametrize("bad_id", ["", None, float("nan"), "   ", "-", "N/A"])
def test_missing_eco_source_id_is_unresolved_before_matching(bad_id):
    plan = plan_row({"id": bad_id}, None, None)
    assert plan.status == UNRESOLVED
    assert plan.source_id == ""
    assert plan.reason == "missing ECO source id"


def test_spec_preflight_withholds_same_key_same_date_different_values():
    registry = _co2_registry()
    outcomes = [_co2_outcome("source-a", 120.0), _co2_outcome("source-b", 130.0)]
    commands = spec_commands_from_outcomes(outcomes, registry=registry, existing_facts={})
    safe, conflicts = preflight_spec_commands(commands, registry=registry, existing_facts={})
    assert safe == []
    assert len(conflicts) == 1
    assert conflicts[0]["source_ids"] == ["source-a", "source-b"]
    assert conflicts[0]["qualifiers"] == {"measurement_basis": "ECO_STICKER_TH"}


def test_spec_preflight_keeps_duplicates_history_and_distinct_contexts():
    registry = _co2_registry()
    same_value = [_co2_outcome("a", 120.0), _co2_outcome("b", 120.0)]
    commands = spec_commands_from_outcomes(same_value, registry=registry, existing_facts={})
    safe, conflicts = preflight_spec_commands(commands, registry=registry, existing_facts={})
    assert len(safe) == 2 and conflicts == []

    history = [_co2_outcome("c", 120.0, observed_at="2026-01-01"),
               _co2_outcome("d", 118.0, observed_at="2026-07-01")]
    commands = spec_commands_from_outcomes(history, registry=registry, existing_facts={})
    safe, conflicts = preflight_spec_commands(commands, registry=registry, existing_facts={})
    assert len(safe) == 2 and conflicts == []

    contexts = [_co2_outcome("e", 120.0, basis="ECO_STICKER_TH"),
                _co2_outcome("f", 130.0, basis="WLTP")]
    commands = spec_commands_from_outcomes(contexts, registry=registry, existing_facts={})
    safe, conflicts = preflight_spec_commands(commands, registry=registry, existing_facts={})
    assert len(safe) == 2 and conflicts == []


def test_spec_preflight_checks_existing_ledger_state_too():
    registry = _co2_registry()
    commands = spec_commands_from_outcomes(
        [_co2_outcome("new-source", 130.0)], registry=registry, existing_facts={})
    existing = {
        "eco:old-source:emissions.co2_g_km": {
            "trim_id": "acme.runner.gen1.trim.premium",
            "field_key": "emissions.co2_g_km", "value_state": "KNOWN",
            "value": 120.0, "unit": "g/km",
            "qualifiers": {"measurement_basis": "ECO_STICKER_TH"},
            "observed_at": "2026-01-01", "source": "ecosticker",
            "source_ref": "https://example.invalid/old-source",
        }
    }
    safe, conflicts = preflight_spec_commands(
        commands, registry=registry, existing_facts=existing)
    assert safe == [] and len(conflicts) == 1
    assert conflicts[0]["source_ids"] == ["new-source"]


def _factory_registry() -> SpecRegistry:
    return SpecRegistry([SpecFieldDefinition(
        key="manufacturing.factory", group="manufacturing",
        label_th="Factory", label_en="Manufacturing plant",
        value_type=ValueType.TEXT, comparison_rule=ComparisonRule.INFORMATION_ONLY,
    )])


def _fake_master(factory: str):
    trim = SimpleNamespace(
        id="acme.runner.gen1.trim.premium", name="Premium",
        powertrain=SimpleNamespace(value="ICE"),
        drivetrain=SimpleNamespace(value="FWD"), engine_cc=None, battery_kwh=None,
        transmission=None, seats=None, length_mm=None, width_mm=None, height_mm=None,
        wheelbase_mm=None, tire_front=None, tire_rear=None, source_refs={},
    )
    catalog = SimpleNamespace(
        trims={trim.id: trim},
        model_for_trim=lambda _tid: SimpleNamespace(id="acme.runner", name_en='Runner'),
        brand_for_trim=lambda _tid: SimpleNamespace(name_en="Acme"),
    )
    eco = SimpleNamespace(
        source_ref="source-1", declared_total_weight_kg=None, tire_size=None,
        battery_chemistry=None, battery_supplier=None, battery_voltage_v=None,
        factory=factory, rated_range_km=None,
    )
    master = SimpleNamespace(
        catalog=catalog, eco={trim.id: eco},
        comparable_specs=SimpleNamespace(resolved=lambda *_args, **_kwargs: []),
        prices=SimpleNamespace(current_list_price=lambda *_args, **_kwargs: None,
                               records_for=lambda *_args, **_kwargs: []),
    )
    return master, trim.id


def test_legacy_battlecard_uses_the_same_factory_semantics():
    engine = BattleCardEngine(_factory_registry())
    master, trim_id = _fake_master("Toyota Motor Thailand Co., Ltd.")
    view = engine._trim_view(master, trim_id, date(2026, 9, 23))
    assert not any(v["field_key"] == "manufacturing.factory" for v in view["values"])

    master, trim_id = _fake_master("BMW AG Plant Dingolfing")
    view = engine._trim_view(master, trim_id, date(2026, 9, 23))
    assert any(v["field_key"] == "manufacturing.factory"
               and v["value"] == "BMW AG Plant Dingolfing" for v in view["values"])


def _write_gz(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_provisional_candidate_reader_uses_the_same_factory_semantics(tmp_path: Path):
    year = 2026
    cohort_dir = tmp_path / str(year) / "product" / "comparable_specs" / "cohorts"
    cohort_dir.mkdir(parents=True)
    (cohort_dir / "c_crossover.json").write_text(json.dumps({
        "id": "c_crossover", "segment": "C", "body_type": "CROSSOVER",
        "model_ids": ["acme.runner"], "representative_source_ids": {}, "notes": "",
    }), encoding="utf-8")
    snap = tmp_path / str(year) / "ingest" / "ecosticker" / "snapshots" / "2026-09-08"
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
    raw = [{"source_id": row["source_id"], "detail": {}} for row in normalized]
    _write_gz(snap / "normalized.jsonl.gz", normalized)
    _write_gz(snap / "raw.jsonl.gz", raw)

    store = ECOCandidateSpecStore.load(
        tmp_path, year, registry=_factory_registry(), snapshot_date="2026-09-08")
    company_keys = {v["field_key"] for v in store.get("company")["values"]}
    plant_values = {v["field_key"]: v["value"] for v in store.get("plant")["values"]}
    assert "manufacturing.factory" not in company_keys
    assert plant_values["manufacturing.factory"] == "BMW AG Plant Dingolfing"


def test_shared_factory_predicate_rejects_companies_and_accepts_sites():
    assert not is_identified_manufacturing_plant("Zhejiang Geely Automobile Co., Ltd.")
    assert not is_identified_manufacturing_plant("บริษัท โตโยต้า มอเตอร์ ประเทศไทย จำกัด")
    assert is_identified_manufacturing_plant("BMW AG Plant Dingolfing")
    assert is_identified_manufacturing_plant("โรงงานสมุทรปราการ")


def test_fact_reimport_rewrites_provenance_and_verification_changes():
    registry = _co2_registry()
    outcome = _co2_outcome("source-a", 120.0)
    exact = {
        "trim_id": "acme.runner.gen1.trim.premium",
        "field_key": "emissions.co2_g_km",
        "value_state": "KNOWN",
        "value": 120.0,
        "unit": "g/km",
        "qualifiers": {"measurement_basis": "ECO_STICKER_TH"},
        "observed_at": "2026-01-01",
        "verification_status": "VERIFIED",
        "source": "ecosticker",
        "source_ref": "https://example.invalid/source-a",
    }
    fact_id = "eco:source-a:emissions.co2_g_km"
    assert spec_commands_from_outcomes(
        [outcome], registry=registry, existing_facts={fact_id: exact}) == []

    provisional = dict(exact, verification_status="PROVISIONAL")
    commands = spec_commands_from_outcomes(
        [outcome], registry=registry, existing_facts={fact_id: provisional})
    assert len(commands) == 1
    assert commands[0]["payload"]["verification_status"] == "VERIFIED"

    old_ref = dict(exact, source_ref="https://example.invalid/old-source-a")
    commands = spec_commands_from_outcomes(
        [outcome], registry=registry, existing_facts={fact_id: old_ref})
    assert len(commands) == 1
    assert commands[0]["payload"]["source_ref"] == "https://example.invalid/source-a"


def test_plan_rejects_invalid_submitted_at_before_reading_rows(monkeypatch, tmp_path: Path):
    import tools.import_source as source_tool

    def should_not_read(_path):
        raise AssertionError("read_rows must not run for an invalid submitted_at")

    monkeypatch.setattr(source_tool, "read_rows", should_not_read)
    with pytest.raises(ValueError, match="submitted_at must be a valid ISO-8601"):
        source_tool.plan_source_import(
            tmp_path / "never-read.csv", catalog=None, registry=None,
            source_kind="ECO", data_dir=tmp_path, year=2026,
            submitted_at="2026-99-99T25:61:00+07:00",
        )
