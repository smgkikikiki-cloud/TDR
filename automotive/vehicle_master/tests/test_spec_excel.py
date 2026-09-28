from types import SimpleNamespace

import pytest

from tools.export_vehicle_spec_template import DISPLAY_COLUMNS, workbook_headers
from tools.import_vehicle_specs import DISPLAY_COLUMNS as IMPORT_DISPLAY_COLUMNS
from vehreg.catalog import DATA_DIR, DEFAULT_YEAR
from vehreg.comparable_specs import (
    ComparisonRule, SpecFieldDefinition, SpecRegistry, ValueState, ValueType,
)
from vehreg.spec_excel import IDENTITY_COLUMN, SpecExcelError, build_column_targets, compile_rows


TRIM_ID = "test.model.g1.trim.long-range-bev"


def _field(key, value_type, *, unit="", powertrains=(), qualifiers=()):
    return SpecFieldDefinition(
        key=key,
        group=key.split(".", 1)[0],
        label_th=key,
        label_en=key,
        value_type=value_type,
        comparison_rule=ComparisonRule.INFORMATION_ONLY,
        canonical_unit=unit,
        applicable_powertrains=tuple(powertrains),
        comparison_qualifiers=tuple(qualifiers),
    )


def _registry():
    return SpecRegistry([
        _field("vehicle.length_mm", ValueType.NUMBER, unit="mm"),
        _field("engine.displacement_cc", ValueType.NUMBER, unit="cc", powertrains=("ICE", "HEV", "PHEV")),
        _field("battery.catalog_capacity_kwh", ValueType.NUMBER, unit="kWh",
               powertrains=("BEV", "PHEV", "REEV", "HEV")),
        _field("safety.aeb", ValueType.BOOLEAN),
        _field("identity.powertrain", ValueType.ENUM),
        _field("ev.rated_range_km", ValueType.NUMBER, unit="km",
               powertrains=("BEV", "PHEV", "REEV"),
               qualifiers=("measurement_basis", "range_scope")),
    ])


def _catalog():
    trim = SimpleNamespace(
        id=TRIM_ID,
        generation_id="test.model.g1",
        name="Long Range",
        powertrain=SimpleNamespace(value="BEV"),
        seats=5,
        length_mm=4500,
        width_mm=1800,
        height_mm=1600,
        wheelbase_mm=2700,
        engine_cc=None,
        battery_kwh=60,
        drivetrain=SimpleNamespace(value="RWD"),
        transmission="1-speed",
        tire_front="225/50 R18",
        tire_rear="225/50 R18",
        engine_code=None,
        wheel_front=None,
        wheel_rear=None,
    )
    generation = SimpleNamespace(id="test.model.g1", model_id="test.model", code="G1")
    model = SimpleNamespace(id="test.model", brand_id="test")
    return SimpleNamespace(
        trims={TRIM_ID: trim},
        generations={generation.id: generation},
        models={model.id: model},
    )


def _compile(row, *, facts=()):
    return compile_rows(
        [row],
        catalog=_catalog(),
        registry=_registry(),
        existing_facts=facts,
        observed_at="2026-09-28",
    )


def test_boolean_and_qualified_ranges_compile_without_guessing():
    result = _compile({
        "canonical_trim_id": TRIM_ID,
        "safety.aeb": "YES",
        "range_nedc_km": 300,
        "range_wltp_km": 250,
    })
    specs = [command for command in result.commands if command["operation"] == "APPEND_SPEC"]
    assert len(specs) == 3
    aeb = next(command for command in specs if command["payload"]["field_key"] == "safety.aeb")
    assert aeb["payload"]["value"] is True
    ranges = [command for command in specs if command["payload"]["field_key"] == "ev.rated_range_km"]
    assert {command["payload"]["qualifiers"]["measurement_basis"] for command in ranges} == {"NEDC", "WLTP"}
    assert len({command["payload"]["fact_id"] for command in ranges}) == 2


def test_qualified_registry_field_rejects_ambiguous_bare_header():
    with pytest.raises(SpecExcelError, match="requires qualifier context"):
        build_column_targets(["ev.rated_range_km"], _registry())


def test_generic_qualified_header_is_supported():
    targets = build_column_targets(
        ["ev.rated_range_km__measurement_basis=CLTC__range_scope=FULL"],
        _registry(),
    )
    target = next(iter(targets.values()))
    assert target.field_key == "ev.rated_range_km"
    assert target.qualifiers == {"measurement_basis": "CLTC", "range_scope": "FULL"}


def test_blank_cells_are_noop():
    result = _compile({
        "canonical_trim_id": TRIM_ID,
        "safety.aeb": "",
        "vehicle.length_mm": "",
    })
    assert result.commands == ()
    assert result.rows_changed == 0


def test_unknown_trim_is_rejected_instead_of_matched_by_name():
    with pytest.raises(SpecExcelError, match="unknown canonical_trim_id"):
        _compile({"canonical_trim_id": "test.model.g1.trim.not-real", "safety.aeb": "YES"})


def test_dash_is_rejected_as_ambiguous_state():
    with pytest.raises(SpecExcelError, match="ambiguous"):
        _compile({"canonical_trim_id": TRIM_ID, "safety.aeb": "-"})


def test_registry_value_dual_writes_market_trim_core():
    result = _compile({
        "canonical_trim_id": TRIM_ID,
        "vehicle.length_mm": 4555,
        "battery.catalog_capacity_kwh": 64.8,
    })
    bundle = next(command for command in result.commands
                  if command["operation"] == "UPSERT_MODEL_BUNDLE")
    trim_patch = bundle["payload"]["trims"][0]
    assert trim_patch["length_mm"] == 4555
    assert trim_patch["battery_kwh"] == 64.8
    assert len([command for command in result.commands
                if command["operation"] == "APPEND_SPEC"]) == 2


def test_wrong_powertrain_value_is_rejected():
    with pytest.raises(SpecExcelError, match="contradicts canonical trim powertrain"):
        _compile({"canonical_trim_id": TRIM_ID, "identity.powertrain": "ICE"})


def test_inapplicable_token_is_noop_for_field_outside_powertrain():
    result = _compile({"canonical_trim_id": TRIM_ID, "engine.displacement_cc": "NOT_APPLICABLE"})
    assert result.commands == ()
    assert result.values_unchanged == 1


def test_inapplicable_field_rejects_an_actual_value():
    with pytest.raises(SpecExcelError, match="does not apply to BEV"):
        _compile({"canonical_trim_id": TRIM_ID, "engine.displacement_cc": 1498})


def test_same_existing_fact_becomes_noop():
    fact = SimpleNamespace(
        fact_id=f"admin:{TRIM_ID}:safety.aeb",
        trim_id=TRIM_ID,
        field_key="safety.aeb",
        value_state=ValueState.KNOWN,
        value=True,
        unit="",
        qualifiers={},
    )
    result = _compile({"canonical_trim_id": TRIM_ID, "safety.aeb": "YES"}, facts=[fact])
    assert result.commands == ()
    assert result.values_unchanged == 1


def test_live_registry_template_headers_cover_every_field_and_parse():
    registry = SpecRegistry.load(DATA_DIR, DEFAULT_YEAR)
    headers = workbook_headers(registry)
    machine_headers = [
        header for header in headers
        if header != IDENTITY_COLUMN and header not in DISPLAY_COLUMNS
    ]
    targets = build_column_targets(machine_headers, registry)
    assert len(targets) == len(machine_headers)
    assert IMPORT_DISPLAY_COLUMNS == frozenset(DISPLAY_COLUMNS)
    covered_fields = {target.field_key for target in targets.values() if target.field_key}
    assert set(registry.fields) <= covered_fields
    # Any field requiring qualifier context must be represented by an explicit
    # alias/header context, never an ambiguous bare value column.
    for key, definition in registry.fields.items():
        if definition.comparison_qualifiers:
            assert key not in headers
