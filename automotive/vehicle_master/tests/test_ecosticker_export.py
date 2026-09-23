"""Folding the monthly ECO Sticker export into values that can be compared.

Every row in this file is shaped like a real one from the September 2026
export -- same column names, same spellings, same blanks -- because the whole
job of the module under test is surviving how the source is actually written,
and a tidied-up fixture would test nothing.
"""
from __future__ import annotations

import pytest

from vehreg.catalog import DATA_DIR
from vehreg.comparable_specs import SpecRegistry
from vehreg.ecosticker_export import (
    ECO_MEASUREMENT_BASIS, IGNORED_COLUMNS, airbag_count, applicable_specs,
    body_type, charging_port_type, combustion_type, emissions_standard,
    equipment_flags, fuel_type, motor_count, motor_type, normalize_row,
    powertrain, un_regulations,
)


@pytest.fixture(scope="module")
def registry():
    return SpecRegistry.load(DATA_DIR, 2026)


def row(**overrides) -> dict:
    """A row with every column the export carries, blank unless overridden."""
    base = {
        "id": "3283e6a6-999d-4964-91d2-064f22b13369",
        "brand": "TOYOTA", "model": "ALPHARD HYBRID G 2WD CAR",
        "cartype_name": "ICE",
        "car_style": "รถยนต์เอนกประสงค์  (MPV : Multi-purpose Vehicle)",
        "company_name": "บริษัท แกรนด์ ออโต้โมทีฟ จำกัด",
        "model_year": "2026", "factory": "TRENDY INFORMATION CO., LTD.",
        "recomend_retail_price_new": "1926000", "tax_rate_new": "0.15",
        "emissions_CO2": "140", "energy_combined_rate": "6.1",
        "rate_energy_urban": "6.4", "rate_energy_ex_urban": "5.9",
        "energy_consumption": "-", "driving_range": "-",
        "battery_type": "-", "battery_brand": "-", "nominal_voltage": "-",
        "motor": "-", "battery_capacity": "-", "type_charge": "-",
        "on_board_charger": "-",
        "engine_name": "ไฮบริด (HEV)", "gear_name": "เกียร์อัตโนมัติ ประเภท CVT",
        "gear_speed": "7", "fuel_name": "เชื้อเพลิงเดี่ยว (เบนซิน)",
        "capacity_cylinder": "2487.0",
        "car_width": "1850", "car_length": "4995", "car_height": "1935",
        "car_seats": "7", "wheel_size": "225/60R18",
        "front_wheel": "-", "back_wheel": "-", "total_weight": "2160",
        "particulate_matters": "-", "nox_amount": "2.549",
        "std_tis": "1", "std_euro4": "0", "std_euro5": "0", "std_euro6": "0",
        "std_abs_esc": "0", "std_un_reg13": "0", "std_un_reg13h": "0",
        "std_un_reg94": "0", "std_un_reg95": "0", "std_un_reg100": "0",
        "car_equip_energy": "", "car_equip_safety": "", "car_equip_factory": "",
        "car_equip_connectivity": "", "car_equip_adas": "", "car_equip_e_parts": "",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# The bug that would have mislabelled every hybrid in the country
# ---------------------------------------------------------------------------

def test_the_export_files_hybrids_as_ice_and_the_engine_column_corrects_it():
    """`cartype_name` has three values -- ICE, BEV, PHEV -- and no HEV at all.

    A Toyota Alphard Hybrid arrives as "ICE". Trusting that column would put
    every hybrid sold in Thailand in the catalogue as a plain petrol car.
    """
    assert powertrain("ICE", "ไฮบริด (HEV)") == "HEV"
    assert powertrain("ICE", "ปลั๊กอินไฮบริด") == "PHEV"
    assert powertrain("ICE", "แก๊สโซลีน") == "ICE"
    assert powertrain("ICE", "ดีเซล") == "ICE"
    assert powertrain("BEV", "") == "BEV"
    # A mild hybrid cannot move on its motor; the taxonomy has no MHEV value.
    assert powertrain("ICE", "ไมล์ดไฮบริด (MHEV)") == "ICE"
    assert combustion_type("ไมล์ดไฮบริด (MHEV)") == "MHEV"
    assert powertrain("", "") is None


def test_a_real_hybrid_row_normalizes_as_a_hybrid():
    vehicle = normalize_row(row())
    assert vehicle.powertrain == "HEV"
    assert vehicle.specs["identity.powertrain"] == "HEV"
    assert vehicle.specs["engine.combustion_type"] == "HEV"


# ---------------------------------------------------------------------------
# Folding source text into something comparable
# ---------------------------------------------------------------------------

def test_one_motor_written_five_ways_folds_to_one_value():
    for spelling in ("Permanent Magnet Synchronous Motor",
                     "Permanent magnet synchronous motor",
                     "PERMANENT MAGNET SYNCHRONOUS MOTOR",
                     "Permanent magnet synchronous motor ",
                     "With permanent magnets", "Synchronous", "synchronous"):
        assert motor_type(spelling) == "PMSM", spelling
    assert motor_type("Front Asynchronous motor") == "AC_INDUCTION"
    assert motor_type("separate excitation") == "SEPARATELY_EXCITED"
    assert motor_type("-") is None


def test_motor_count_is_read_from_the_axles_the_source_names():
    assert motor_count(
        "Front Asynchronous motor  Rear Permanent magnet synchronous motor") == 2
    assert motor_count("Dual motor") == 2
    # One unqualified motor name says nothing about how many there are.
    assert motor_count("Permanent magnet synchronous motor") is None
    assert motor_count("-") is None


def test_fuel_type_records_the_highest_blend_the_car_accepts():
    assert fuel_type("เชื้อเพลิงผสม (เบนซิน-E85)") == "E85"
    assert fuel_type("เชื้อเพลิงผสม (E85)") == "E85"
    assert fuel_type("เชื้อเพลิงผสม (เบนซิน-E20)") == "E20"
    assert fuel_type("เชื้อเพลิงผสม (E20)") == "E20"
    assert fuel_type("เชื้อเพลิงเดี่ยว (เบนซิน)") == "GASOLINE"
    assert fuel_type("ดีเซล (B20)") == "B20"
    assert fuel_type("ดีเซล (B10)") == "B10"
    assert fuel_type("ดีเซล") == "DIESEL"
    assert fuel_type("-") is None


def test_body_style_prose_folds_to_the_catalogue_taxonomy():
    assert body_type("รถยนต์เอนกประสงค์สมรรถนะสูง  (SUV  : Sport Utility Vehicle)") == "CROSSOVER"
    assert body_type("รถยนต์นั่ง 4 ประตู (Sedan)") == "SEDAN"
    assert body_type("รถกระบะ สองตอน (Pickup Double Cab)") == "PICKUP"
    # PPV must not be swallowed by the PICKUP rule that also matches its text.
    assert body_type("รถยนต์นั่งที่ดัดแปลงจากรถปิกอัพ (PPV : Pickup Passenger Vehicle)") == "PPV"
    assert body_type("รถยนต์นั่ง 5 ประตู (Hatchback)") == "HATCHBACK"
    assert body_type("Sportback") == "HATCHBACK"
    assert body_type("Avant") == "WAGON"
    assert body_type("Roadster") == "COUPE"
    assert body_type("Other") == "OTHER"
    assert body_type("-") is None


def test_four_standard_columns_become_one_comparable_value():
    assert emissions_standard(row(std_tis="0", std_euro4="1")) == "EURO4"
    # Highest wins: a Euro 6 car also satisfies Euro 4.
    assert emissions_standard(row(std_euro4="1", std_euro6="1")) == "EURO6"
    assert emissions_standard(row(std_tis="1")) == "TIS"
    assert emissions_standard(row()) == "TIS"
    assert emissions_standard(row(std_tis="0")) is None
    assert un_regulations(row(std_un_reg13h="1", std_un_reg100="1")) == ["R13H", "R100"]
    assert un_regulations(row()) == []


def test_charging_method_folds_twenty_seven_spellings():
    assert charging_port_type("on board charger") == "ONBOARD_AC"
    assert charging_port_type("external charger") == "EXTERNAL_DC"
    assert charging_port_type("Onboard and DC charging") == "BOTH"
    assert charging_port_type("On board/external (AC/DC)") == "BOTH"
    assert charging_port_type("-") is None


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------

ALPHARD_SAFETY = ("ABS; ถุงลมนิรภัยแบบม่าน; ถุงลมนิรภัยด้านข้าง; "
                  "ถุงลมนิรภัยด้านหน้าคนขับ; ถุงลมนิรภัยด้านหน้าคนนั่ง; ESC/VSA/VSC")


def test_equipment_prose_becomes_comparable_flags():
    flags = equipment_flags(row(car_equip_safety=ALPHARD_SAFETY))
    assert flags["safety.abs"] is True
    assert flags["safety.esc"] is True
    assert flags["safety.curtain_airbag"] is True
    assert flags["safety.side_airbag"] is True
    # The source lists what a car HAS. Silence is unknown, not absent, so a
    # missing item must never come back as False.
    assert "safety.knee_airbag" not in flags
    assert all(value is True for value in flags.values())


def test_the_same_system_spelled_four_ways_sets_one_flag():
    for spelling in ("ESC/VSA/VSC", "ESC", "ESP",
                     "โปรแกรมควบคุมการทรงตัวอัตโนมัติ ESP"):
        assert equipment_flags(row(car_equip_safety=spelling)).get("safety.esc") is True
    # ระบบเซ็นทรัลล็อก vs ระบบเซ็นทรัลล๊อก differ by one tone mark in the source;
    # both are central locking and neither should create a phantom field.
    assert "safety.esc" not in equipment_flags(row(car_equip_factory="ระบบเซ็นทรัลล๊อก"))


def test_adas_keeps_warning_and_steering_systems_apart():
    """LDW warns, LKAS steers. The registry had one field; the source has both,
    and 451 vehicles carry the warning system alone."""
    ldw = equipment_flags(row(car_equip_adas=(
        "ระบบเตือนการออกหรือเปลี่ยนช่องจราจร Lane departure warning system (LDW)")))
    assert ldw.get("safety.lane_departure_warning") is True
    assert "safety.lane_keep_assist" not in ldw

    lkas = equipment_flags(row(car_equip_adas=(
        "ระบบการดูแลภายในช่องจราจร Lane keeping assistance systems (LKAS)")))
    assert lkas.get("safety.lane_keep_assist") is True
    assert "safety.lane_departure_warning" not in lkas


def test_airbag_positions_are_counted_not_guessed():
    assert airbag_count(row(car_equip_safety=ALPHARD_SAFETY)) == 4
    # The source sometimes states the number itself.
    assert airbag_count(row(car_equip_safety="ถุงลมนิรภัยด้านหน้า 2 ตำแหน่ง")) == 2
    assert airbag_count(row()) is None


# ---------------------------------------------------------------------------
# Nothing is invented
# ---------------------------------------------------------------------------

def test_a_spreadsheet_blank_never_becomes_a_value():
    """A blank cell arrives from pandas as float("nan"), which is truthy --
    handing it straight to a folder turned "no value" into the family
    "OTHER" on every row that never stated one."""
    empty = normalize_row(row(battery_type=float("nan"), gear_name=float("nan"),
                              motor=float("nan"), fuel_name=float("nan")))
    for key in ("battery.chemistry", "powertrain.transmission",
                "powertrain.motor_type", "engine.fuel_type"):
        assert key not in empty.specs, key


def test_dashes_and_zeroes_are_not_measurements():
    vehicle = normalize_row(row(driving_range="-", battery_capacity="-",
                                car_seats="0", nox_amount="-"))
    assert "ev.rated_range_km" not in vehicle.specs
    assert "battery.catalog_capacity_kwh" not in vehicle.specs
    assert "vehicle.seats" not in vehicle.specs
    assert "emissions.nox_g_km" not in vehicle.specs


def test_range_and_consumption_are_labelled_with_the_programme_that_measured_them():
    """The export never says which drive cycle it used. Calling it NEDC or
    WLTP would be a guess, and 500 km CLTC beside 450 km WLTP is a comparison
    that misleads. It is labelled as what it verifiably is."""
    vehicle = normalize_row(row(cartype_name="BEV", engine_name="-",
                                driving_range="701", energy_consumption="199",
                                battery_type="LFP", battery_capacity="145.0"))
    assert vehicle.specs["ev.rated_range_km"] == 701
    assert vehicle.qualifiers["ev.rated_range_km"] == {
        "measurement_basis": ECO_MEASUREMENT_BASIS}
    assert vehicle.qualifiers["ev.energy_consumption_wh_km"]["measurement_basis"] \
        == ECO_MEASUREMENT_BASIS
    # A plain dimension carries no qualifier: it is not a measured figure.
    assert "vehicle.length_mm" not in vehicle.qualifiers


def test_excise_tax_is_stored_as_the_percentage_it_is_quoted_as():
    assert normalize_row(row(tax_rate_new="0.15")).specs[
        "manufacturing.excise_tax_rate"] == 15.0
    assert normalize_row(row(tax_rate_new="0.02")).specs[
        "manufacturing.excise_tax_rate"] == 2.0
    # The source has a handful of unparseable cells; they stay empty.
    for junk in ("ไม่มีอัตรา%", "ุ6%", "0"):
        assert "manufacturing.excise_tax_rate" not in normalize_row(
            row(tax_rate_new=junk)).specs


def test_the_duplicate_and_broken_columns_are_never_read():
    """rate_energy duplicates CO2, capacity_cylinder_str duplicates
    capacity_cylinder, and car_tyre is "[object Object]" on every single row."""
    vehicle = normalize_row(row(rate_energy="999", capacity_cylinder_str="9999 ซีซี",
                                car_tyre="[object Object]"))
    assert vehicle.specs["emissions.co2_g_km"] == 140
    assert vehicle.specs["engine.displacement_cc"] == 2487
    assert not any("[object" in str(v) for v in vehicle.specs.values())


# ---------------------------------------------------------------------------
# What the registry will actually accept
# ---------------------------------------------------------------------------

def test_a_petrol_car_does_not_get_a_traction_battery_chemistry(registry):
    """An ICE row routinely carries a battery_type: that is its 12V starter
    battery. `battery.chemistry` is declared for HEV/PHEV/REEV/BEV only, so
    writing it would both fail validation and state something untrue."""
    vehicle = normalize_row(row(engine_name="แก๊สโซลีน", battery_type="Lead acid"))
    assert vehicle.powertrain == "ICE"
    assert "battery.chemistry" in vehicle.specs
    accepted, dropped = applicable_specs(vehicle, registry)
    assert "battery.chemistry" not in accepted
    assert "battery.chemistry" in dropped


def test_a_bev_is_not_given_an_engine(registry):
    vehicle = normalize_row(row(cartype_name="BEV", engine_name="-",
                                capacity_cylinder="1998"))
    accepted, dropped = applicable_specs(vehicle, registry)
    assert "engine.displacement_cc" in dropped
    assert "engine.displacement_cc" not in accepted


def test_every_value_that_survives_is_one_the_canonical_writer_accepts(registry):
    """The point of the filter: what comes out can be written as-is."""
    from vehreg.comparable_specs import ValueState, ValueType
    for sample in (row(),
                   row(cartype_name="BEV", engine_name="-", driving_range="701",
                       battery_type="LFP", battery_capacity="145.0",
                       motor="Permanent magnet synchronous motor",
                       type_charge="on board charger"),
                   row(engine_name="ดีเซล", fuel_name="ดีเซล (B20)",
                       car_equip_safety=ALPHARD_SAFETY)):
        vehicle = normalize_row(sample)
        accepted, _ = applicable_specs(vehicle, registry)
        assert accepted, "a real row should produce specs"
        for key, value in accepted.items():
            definition = registry.fields[key]
            unit = (definition.canonical_unit
                    if definition.value_type is ValueType.NUMBER else "")
            assert definition.validate_value(ValueState.KNOWN, value, unit) == [], \
                f"{key}={value!r}"
            for qualifier in vehicle.qualifiers.get(key, {}):
                assert qualifier in definition.comparison_qualifiers, \
                    f"{key}: unknown qualifier {qualifier}"


def test_a_full_row_produces_a_useful_number_of_comparable_facts(registry):
    """The catalogue today has drivetrain on 4% of trims and transmission on
    0%. One import row has to be worth more than that or the exercise is
    pointless."""
    vehicle = normalize_row(row(car_equip_safety=ALPHARD_SAFETY,
                                car_equip_adas="ระบบเบรคฉุกเฉินขั้นสูง Advanced emergency braking system (AEB)"))
    accepted, _ = applicable_specs(vehicle, registry)
    assert len(accepted) >= 20, sorted(accepted)
    assert accepted["vehicle.seats"] == 7
    assert accepted["vehicle.length_mm"] == 4995
    assert accepted["fitment.tyre_size"] == "225/60R18"
    assert accepted["powertrain.transmission"] == "CVT"
    assert accepted["engine.fuel_type"] == "GASOLINE"
    assert accepted["safety.aeb"] is True
    assert "manufacturing.factory" not in accepted
    assert vehicle.notes["factory"] == "TRENDY INFORMATION CO., LTD."


# ---------------------------------------------------------------------------
# When the source says it observed what it states
# ---------------------------------------------------------------------------

def test_the_approval_date_is_kept_as_the_date_the_source_observed():
    """The export's approval timestamp, reduced to the date.

    It is not decoration: it is the start date every fact this row produces
    gets filed under, so an unchanged record re-imported next month is the
    same fact rather than a specification that changed on import day.
    """
    vehicle = normalize_row(row(approve_date="2026-09-15T09:27:32.055971+07:00"))
    assert vehicle.approved_at == "2026-09-15"


def test_a_row_with_no_usable_approval_date_states_none():
    for value in ("", "-", "ไม่ระบุ", "2026", "not a date", None):
        assert normalize_row(row(approve_date=value)).approved_at == ""


def test_the_re_listing_timestamp_is_not_read():
    """``approval_at_latest`` moves when a record is merely re-listed, so
    reading it would re-date a specification that never changed."""
    assert "approval_at_latest" in IGNORED_COLUMNS
    assert "approve_date" not in IGNORED_COLUMNS


# ---------------------------------------------------------------------------
# The column that is not what its name suggests
# ---------------------------------------------------------------------------

def test_battery_capacity_is_charge_not_energy():
    """``battery_capacity`` is ampere-hours; the catalogue compares kilowatt-hours.

    Read literally the column put a 169 kWh pack in a compact taxi. Energy is
    charge times voltage, and the export states the voltage on every row that
    states a capacity: 169 Ah at 326.4 V is 55.16 kWh, which is the car.
    """
    specs = normalize_row(row(battery_capacity="169", nominal_voltage="326.4")).specs
    assert specs["battery.gross_capacity_kwh"] == 55.16
    # The raw figure is never published as an energy.
    assert "battery.catalog_capacity_kwh" not in specs
    assert specs["battery.nominal_voltage_v"] == 326.4


def test_no_voltage_means_no_derived_capacity():
    """Half the identity is not an answer. A pack with a stated charge and no
    stated voltage has no energy this module is entitled to publish."""
    for volts in ("", "-", "0", None):
        specs = normalize_row(row(battery_capacity="169", nominal_voltage=volts)).specs
        assert "battery.gross_capacity_kwh" not in specs
    specs = normalize_row(row(battery_capacity="-", nominal_voltage="326.4")).specs
    assert "battery.gross_capacity_kwh" not in specs


def test_the_derived_capacity_agrees_with_the_range_the_source_states(registry):
    """An independent check on the unit, from columns the battery ones do not feed.

    Range times consumption is the energy the car actually uses. Voltage times
    charge is the gross pack, which is a little larger -- if the derivation
    were out by a factor, these two would not sit next to each other.
    """
    vehicle = normalize_row(row(cartype_name="BEV", engine_name="ไฟฟ้า",
                                capacity_cylinder="-", fuel_name="-",
                                battery_capacity="169", nominal_voltage="326.4",
                                driving_range="442", energy_consumption="115"))
    gross = vehicle.specs["battery.gross_capacity_kwh"]
    usable = 442 * 115 / 1000
    assert 0.8 <= usable / gross <= 1.05, (gross, usable)


def test_emissions_are_converted_from_the_unit_the_regulation_uses():
    """The export quotes NOx and particulates in mg/km; the registry compares g/km.

    Published as they arrive, the median NOx figure is 263 times the Euro 5
    petrol limit -- a number no car that passed homologation could carry, which
    is what makes the unit error detectable at all.
    """
    specs = normalize_row(row(nox_amount="15.8", particulate_matters="0.38")).specs
    assert specs["emissions.nox_g_km"] == 0.0158
    assert specs["emissions.pm_g_km"] == 0.00038


def test_no_emission_reading_is_not_a_reading_of_zero():
    for blank in ("", "-", "0", None):
        specs = normalize_row(row(nox_amount=blank, particulate_matters=blank)).specs
        assert "emissions.nox_g_km" not in specs
        assert "emissions.pm_g_km" not in specs


# ---------------------------------------------------------------------------
# When the source itself is wrong
# ---------------------------------------------------------------------------

def test_a_transposed_length_and_width_is_corrected_not_published():
    """Eight rows file the car the wrong way round. A road vehicle is never
    wider than it is long, so this is a certainty, not a guess."""
    vehicle = normalize_row(row(car_length="1890", car_width="4595", car_height="1405"))
    assert vehicle.specs["vehicle.length_mm"] == 4595
    assert vehicle.specs["vehicle.width_mm"] == 1890
    assert "dimensions" in vehicle.repairs


def test_a_measurement_nothing_can_recover_is_withheld_and_reported():
    """A 47-metre Mustang. No rule turns that into the right number, so the
    length is not published -- and the other two measurements still are."""
    vehicle = normalize_row(row(car_length="47874", car_width="1916", car_height="1381"))
    assert "vehicle.length_mm" not in vehicle.specs
    assert vehicle.specs["vehicle.width_mm"] == 1916
    assert vehicle.specs["vehicle.height_mm"] == 1381
    assert "vehicle.length_mm" in vehicle.repairs


def test_an_ordinary_car_is_left_alone():
    vehicle = normalize_row(row(car_length="4995", car_width="1850", car_height="1935"))
    assert vehicle.specs["vehicle.length_mm"] == 4995
    assert vehicle.specs["vehicle.width_mm"] == 1850
    assert vehicle.specs["vehicle.height_mm"] == 1935
    assert vehicle.repairs == {}


def test_a_narrow_cargo_vehicle_is_not_mistaken_for_an_error():
    """1,200mm wide is a real micro-cargo EV in this export, not a fault."""
    vehicle = normalize_row(row(car_length="3495", car_width="1200", car_height="1860"))
    assert vehicle.specs["vehicle.width_mm"] == 1200
    assert vehicle.repairs == {}
