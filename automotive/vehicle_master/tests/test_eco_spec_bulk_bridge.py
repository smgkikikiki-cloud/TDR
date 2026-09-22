"""The uploaded ECO workbook must feed the comparable-spec store too.

These tests sit on the narrow bridge added to tools.import_source: identity is
still resolved by source_import, normalization is still owned by
vehreg.ecosticker_export, and APPEND_SPEC is still validated by the canonical
writer. The bridge only connects those already-existing pieces without
inventing values or dates.
"""

from vehreg.comparable_specs import (
    ComparisonRule, SpecFact, SpecFieldDefinition, SpecRegistry,
    ValueState, ValueType, VerificationStatus,
)
from vehreg.ecosticker_export import NormalizedVehicle
from vehreg.source_import import CREATED, UNCHANGED, RowOutcome, SourceRow
from tools.import_source import spec_commands_from_outcomes

GEN = "aion.aion_ut.gen1"
MODEL = "aion.aion_ut"
TRIM = f"{GEN}.trim.premium_bev"


def registry() -> SpecRegistry:
    return SpecRegistry([
        SpecFieldDefinition(
            key="ev.rated_range_km", group="energy", label_th="ระยะทาง",
            label_en="Rated range", value_type=ValueType.NUMBER,
            comparison_rule=ComparisonRule.HIGHER_BETTER, canonical_unit="km",
            applicable_powertrains=("BEV",),
            comparison_qualifiers=("measurement_basis",),
        ),
        SpecFieldDefinition(
            key="battery.gross_capacity_kwh", group="battery",
            label_th="ความจุแบตเตอรี่รวม", label_en="Gross battery capacity",
            value_type=ValueType.NUMBER,
            comparison_rule=ComparisonRule.HIGHER_BETTER, canonical_unit="kWh",
            applicable_powertrains=("BEV",),
        ),
        SpecFieldDefinition(
            key="battery.chemistry", group="battery", label_th="เคมีแบตเตอรี่",
            label_en="Battery chemistry", value_type=ValueType.ENUM,
            comparison_rule=ComparisonRule.INFORMATION_ONLY,
            applicable_powertrains=("HEV", "PHEV", "REEV", "BEV"),
        ),
    ])


def source_row(source_id="eco-1", name="Premium", powertrain="BEV") -> SourceRow:
    return SourceRow(
        source_id=source_id, source_kind="ECO", model_id=MODEL,
        generation_id=GEN, powertrain=powertrain, trim_name=name, values={},
    )


def vehicle(source_id="eco-1", *, approved_at="2026-09-01",
            powertrain="BEV", specs=None, qualifiers=None) -> NormalizedVehicle:
    return NormalizedVehicle(
        source_id=source_id, brand_raw="AION", model_raw="AION UT Premium",
        importer_raw="AION AUTOMOBILE SALES (THAILAND) CO., LTD.",
        powertrain=powertrain, body_type="HATCHBACK", price_thb=None,
        approved_at=approved_at, specs=dict(specs or {}),
        qualifiers=dict(qualifiers or {}),
    )


def test_unchanged_trim_still_backfills_registry_specs():
    row = source_row()
    outcome = RowOutcome(row=row, status=UNCHANGED, trim_id=TRIM)
    v = vehicle(
        specs={"ev.rated_range_km": 490.0, "battery.gross_capacity_kwh": 58.4},
        qualifiers={"ev.rated_range_km": {"measurement_basis": "ECO_STICKER_TH"}},
    )

    commands, stats, conflicts = spec_commands_from_outcomes(
        [outcome], vehicles={"eco-1": v}, registry=registry())

    assert conflicts == [] and stats["spec_conflicts"] == 0
    assert [c["operation"] for c in commands] == ["APPEND_SPEC", "APPEND_SPEC"]
    facts = {c["payload"]["field_key"]: c["payload"] for c in commands}
    assert facts["ev.rated_range_km"] == {
        "fact_id": "eco:eco-1:ev.rated_range_km",
        "field_key": "ev.rated_range_km",
        "value_state": "KNOWN",
        "value": 490.0,
        "unit": "km",
        "observed_at": "2026-09-01",
        "verification_status": "VERIFIED",
        "source": "ecosticker",
        "source_ref": "https://car.ecosticker.go.th/landing-page/detail/eco-1",
        "source_locator": "https://car.ecosticker.go.th/landing-page/detail/eco-1",
        "qualifiers": {"measurement_basis": "ECO_STICKER_TH"},
        "trim_id": TRIM,
    }
    # ECO's Ah x voltage result is explicitly the gross pack. It must never be
    # relabelled as the catalogue capacity that MarketTrim.battery_kwh means.
    assert facts["battery.gross_capacity_kwh"]["value"] == 58.4
    assert "battery.catalog_capacity_kwh" not in facts


def test_new_trim_uses_writer_trim_ref_after_the_upsert_creates_it():
    row = source_row(source_id="eco-new", name="Long Range")
    outcome = RowOutcome(row=row, status=CREATED)
    v = vehicle(source_id="eco-new", specs={"ev.rated_range_km": 550.0})

    commands, _, conflicts = spec_commands_from_outcomes(
        [outcome], vehicles={"eco-new": v}, registry=registry())

    assert conflicts == [] and len(commands) == 1
    command = commands[0]
    assert "canonical_id" not in command
    assert command["payload"]["trim_ref"] == {
        "generation_id": GEN,
        "name": "Long Range",
        "powertrain": "BEV",
    }


def test_missing_approval_date_is_not_replaced_with_the_import_clock():
    row = source_row()
    outcome = RowOutcome(row=row, status=UNCHANGED, trim_id=TRIM)
    v = vehicle(approved_at="", specs={"ev.rated_range_km": 490.0})

    commands, stats, conflicts = spec_commands_from_outcomes(
        [outcome], vehicles={"eco-1": v}, registry=registry())

    assert commands == [] and conflicts == []
    assert stats["spec_rows_missing_observed_at"] == 1


def test_powertrain_applicability_filters_a_starter_battery_claim():
    row = source_row(powertrain="ICE")
    outcome = RowOutcome(row=row, status=UNCHANGED, trim_id=TRIM)
    v = vehicle(powertrain="ICE", specs={"battery.chemistry": "LFP"})

    commands, stats, conflicts = spec_commands_from_outcomes(
        [outcome], vehicles={"eco-1": v}, registry=registry())

    assert commands == [] and conflicts == []
    assert stats["spec_values_dropped"] == 1


def test_same_day_disagreement_is_reported_instead_of_poisoning_the_batch():
    row_a = source_row(source_id="eco-a")
    row_b = source_row(source_id="eco-b")
    outcomes = [
        RowOutcome(row=row_a, status=UNCHANGED, trim_id=TRIM),
        RowOutcome(row=row_b, status=UNCHANGED, trim_id=TRIM),
    ]
    vehicles = {
        "eco-a": vehicle(source_id="eco-a", specs={"ev.rated_range_km": 490.0}),
        "eco-b": vehicle(source_id="eco-b", specs={"ev.rated_range_km": 510.0}),
    }

    commands, stats, conflicts = spec_commands_from_outcomes(
        outcomes, vehicles=vehicles, registry=registry())

    assert commands == []
    assert stats["spec_conflicts"] == 1 and len(conflicts) == 1
    detail = conflicts[0]["conflicts"][0]
    assert detail["field_key"] == "ev.rated_range_km"
    assert {row["value"] for row in detail["values"]} == {490.0, 510.0}


def test_exact_existing_fact_is_an_idempotent_noop():
    row = source_row()
    outcome = RowOutcome(row=row, status=UNCHANGED, trim_id=TRIM)
    v = vehicle(specs={"ev.rated_range_km": 490.0}, qualifiers={
        "ev.rated_range_km": {"measurement_basis": "ECO_STICKER_TH"}
    })
    existing = SpecFact(
        fact_id="eco:eco-1:ev.rated_range_km", trim_id=TRIM,
        field_key="ev.rated_range_km", value_state=ValueState.KNOWN,
        value=490.0, unit="km",
        qualifiers={"measurement_basis": "ECO_STICKER_TH"},
        observed_at="2026-09-01", verification_status=VerificationStatus.VERIFIED,
        source="ecosticker",
        source_ref="https://car.ecosticker.go.th/landing-page/detail/eco-1",
        source_locator="https://car.ecosticker.go.th/landing-page/detail/eco-1",
    )

    commands, stats, conflicts = spec_commands_from_outcomes(
        [outcome], vehicles={"eco-1": v}, registry=registry(),
        existing_facts=[existing])

    assert commands == [] and conflicts == []
    assert stats["spec_unchanged"] == 1
