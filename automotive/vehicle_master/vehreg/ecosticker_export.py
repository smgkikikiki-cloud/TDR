"""Normalizes one row of the monthly ECO Sticker spreadsheet export.

The export is 71 columns of source text: the same motor written five ways,
the same battery chemistry written forty-seven, equipment as semicolon-joined
Thai prose, and a powertrain column that has no value for "hybrid" at all.
None of that can be compared, which is the whole point of the catalogue.

This module is the one place that folding happens. It turns a raw row into
canonical comparable-spec values keyed by the registry keys in
``product/comparable_specs/registry.json``, and says nothing at all where the
source says nothing -- a blank is left blank rather than guessed, because a
wrong specification is worse than a missing one.

It is deliberately pure: it takes and returns plain dicts, opens no files and
reaches no catalogue, so the folding rules can be tested directly against real
rows. ``tools/ecosticker_import.py`` does the reading and the matching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Any, Optional

from .comparable_specs import (
    ValueState, ValueType, battery_chemistry_family,
    is_identified_manufacturing_plant, transmission_family,
)
from .ecosticker_ingest import infer_powertrain

#: Columns the export carries that this module deliberately drops.
#:
#: ``rate_energy`` duplicates ``emissions_CO2``; ``fuel_consumption_combined``
#: and ``rate_energy_elec`` duplicate each other AND ``energy_combined_rate``;
#: ``capacity_cylinder_str`` is ``capacity_cylinder`` with "ซีซี" appended;
#: ``car_tyre`` arrives as the literal string "[object Object]" on every row
#: (the harvester is broken upstream); ``car_equip_parts_of_engine`` is empty
#: in every row; ``year`` duplicates ``model_year``.
#:
#: ``approve_date`` is not dropped -- it dates every fact the row produces --
#: but ``approval_at_latest`` is: it moves when the record is merely re-listed,
#: so using it would re-date a specification that never changed.
IGNORED_COLUMNS = (
    "rate_energy", "fuel_consumption_combined", "rate_energy_elec",
    "capacity_cylinder_str", "car_tyre", "car_equip_parts_of_engine", "year",
    "_synced_at", "approval_at_latest",
)

#: Values the export uses to mean "no value".
_BLANKS = {"", "-", "nan", "none", "null", "n/a", "ไม่ระบุ"}


def _text(raw: Any) -> str:
    text = str(raw if raw is not None else "").strip()
    return "" if text.lower() in _BLANKS else text


def _number(raw: Any) -> Optional[float]:
    text = _text(raw).replace(",", "")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _integer(raw: Any) -> Optional[int]:
    value = _number(raw)
    if value is None:
        return None
    return int(round(value))


def _flag(raw: Any) -> bool:
    """The std_* columns are "1"/"0" strings."""
    return _text(raw) in {"1", "1.0", "true", "True"}


# --------------------------------------------------------------------------
# Body style
# --------------------------------------------------------------------------

#: ``car_style`` is Thai prose with the English term in brackets, plus a dozen
#: bare English marketing words ("Sportback", "Avant", "Roadster"). Ordered
#: longest-signal-first so "Pickup Passenger Vehicle" cannot match "Pickup".
_BODY_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("ppv", "pickup passenger", "ดัดแปลงจากรถปิกอัพ"), "PPV"),
    (("pickup", "กระบะ"), "PICKUP"),
    (("suv", "sport utility"), "CROSSOVER"),
    (("crossover",), "CROSSOVER"),
    (("mpv", "multi-purpose", "เอนกประสงค์"), "MPV"),
    (("station wagon", "avant", "wagon"), "WAGON"),
    (("hatchback", "sportback"), "HATCHBACK"),
    (("sedan", "4 ประตู"), "SEDAN"),
    (("coupe", "roadster", "convertible", "cabriolet", "สปอร์ต"), "COUPE"),
    (("รถตู้", "van"), "VAN"),
    (("cab & chassis", "บรรทุก", "truck"), "TRUCK"),
)


def approval_date(raw: Any) -> str:
    """The date part of the export's approval timestamp, or "".

    The column arrives as a full ISO timestamp in Bangkok time
    ("2026-09-15T09:27:32.055971+07:00"); only the date is kept, because that
    is the resolution a homologation record is meaningful at and the ledger
    keys facts by date.
    """
    text = _text(raw)
    if len(text) < 10:
        return ""
    head = text[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", head):
        return ""
    return head


#: What a road vehicle's body can physically measure, in millimetres. Checked
#: against the whole 1,647-row export: once transposed rows are corrected this
#: rejects three lengths and nothing else -- no width and no height at all.
_DIMENSION_BANDS = {
    "vehicle.length_mm": (2500, 8000),
    "vehicle.width_mm": (1200, 2600),
    "vehicle.height_mm": (1100, 3000),
}


def dimensions(row: dict) -> tuple[dict[str, int], dict[str, str]]:
    """Length, width and height, with the source's own mistakes handled.

    Two faults appear in the export and they need opposite treatment.

    Eight rows have length and width the wrong way round -- a Civic Type R
    filed as 1,890 long and 4,595 wide. A road vehicle is never wider than it
    is long, so the transposition is certain rather than probable, and every
    one of the eight is a car whose real dimensions the swap restores exactly.
    That is a correction, not a guess.

    Three rows are simply wrong in a way nothing can recover: an Alphard
    1,950mm long, a Mustang 47,874mm long. There is no rule that turns those
    into the right number, so the measurement is withheld and reported. A
    missing dimension shows as a blank; a wrong one shows as a fact.
    """
    values = {"vehicle.length_mm": _integer(row.get("car_length")),
              "vehicle.width_mm": _integer(row.get("car_width")),
              "vehicle.height_mm": _integer(row.get("car_height"))}
    repairs: dict[str, str] = {}

    length, width = values["vehicle.length_mm"], values["vehicle.width_mm"]
    if length and width and length > 0 and width > 0 and length <= width:
        values["vehicle.length_mm"], values["vehicle.width_mm"] = width, length
        repairs["dimensions"] = (f"ต้นทางสลับ length/width ({length}/{width}) "
                                 f"สลับกลับเป็น {width}/{length}")

    specs: dict[str, int] = {}
    for key, value in values.items():
        if value is None or value <= 0:
            continue
        low, high = _DIMENSION_BANDS[key]
        if low <= value <= high:
            specs[key] = value
        else:
            repairs[key] = f"{value} mm อยู่นอกช่วงที่เป็นไปได้ ({low}-{high}) จึงไม่บันทึก"
    return specs, repairs


def body_type(car_style: Any) -> Optional[str]:
    text = _text(car_style).lower()
    if not text:
        return None
    for needles, value in _BODY_RULES:
        if any(needle in text for needle in needles):
            return value
    return "OTHER"


# --------------------------------------------------------------------------
# Powertrain, fuel and engine
# --------------------------------------------------------------------------

#: ``engine_name`` is the only column that distinguishes a hybrid.
_COMBUSTION_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("ปลั๊กอิน",), "PHEV"),
    (("ไมล์ดไฮบริด", "mhev"), "MHEV"),
    (("ไฮบริด", "hev"), "HEV"),
    (("ดีเซล",), "DIESEL"),
    (("แก๊สโซลีน", "เบนซิน"), "GASOLINE"),
)


def combustion_type(engine_name: Any) -> Optional[str]:
    text = _text(engine_name).lower()
    if not text:
        return None
    for needles, value in _COMBUSTION_RULES:
        if any(needle in text for needle in needles):
            return value
    return "OTHER"


def powertrain(cartype_name: Any, engine_name: Any, label: str = "") -> Optional[str]:
    """The retail powertrain, which ``cartype_name`` alone cannot give.

    The export's own powertrain column has exactly three values -- ICE, BEV,
    PHEV -- and no HEV at all, so a Toyota Alphard Hybrid and a Honda Step WGN
    e:HEV both arrive filed as "ICE". Taking that column at face value would
    record every hybrid in the country as a plain combustion car.

    The rule for resolving that already exists: ``ecosticker_ingest`` has been
    reading the same two source fields since the first ECO harvest, including
    the REEV case a plug-in whose name says "range extender" needs. This
    delegates to it rather than keeping a second copy that could drift.
    """
    resolved, _basis = infer_powertrain(str(label or ""), {
        "engine_name": _text(engine_name),
        "cartype_name": _text(cartype_name),
    })
    return resolved


#: Stored as the highest blend the car accepts: an E85 car runs E20 and plain
#: gasoline too, so one value answers the question a buyer is asking.
_FUEL_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("e85",), "E85"),
    (("e20",), "E20"),
    (("e10",), "E10"),
    (("b20",), "B20"),
    (("b10",), "B10"),
    (("ดีเซล", "diesel"), "DIESEL"),
    (("เบนซิน", "gasoline", "petrol"), "GASOLINE"),
)


def fuel_type(fuel_name: Any) -> Optional[str]:
    text = _text(fuel_name).lower()
    if not text:
        return None
    for needles, value in _FUEL_RULES:
        if any(needle in text for needle in needles):
            return value
    return "OTHER"


# --------------------------------------------------------------------------
# Motor
# --------------------------------------------------------------------------

#: 339 BEVs, seventy distinct spellings of the same handful of motors --
#: "Permanent Magnet Synchronous Motor", "Permanent magnet synchronous motor",
#: "PERMANENT MAGNET SYNCHRONOUS MOTOR", the same again with a trailing space,
#: "With permanent magnets", "Synchronous", "synchronous".
_MOTOR_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("permanent magnet", "permanent magnets", "pmsm"), "PMSM"),
    (("asynchronous", "induction"), "AC_INDUCTION"),
    (("separate excitation", "separately excited"), "SEPARATELY_EXCITED"),
    (("synchronous",), "PMSM"),
)


def motor_type(motor: Any) -> Optional[str]:
    text = _text(motor).lower()
    if not text:
        return None
    for needles, value in _MOTOR_RULES:
        if any(needle in text for needle in needles):
            return value
    return "OTHER"


def motor_count(motor: Any) -> Optional[int]:
    """Read off the axle words the source already uses.

    "Front Asynchronous motor  Rear Permanent magnet synchronous motor" is two
    motors and says so; a string that names no axle says nothing about how
    many there are, so it returns None rather than assuming one.
    """
    text = _text(motor).lower()
    if not text:
        return None
    axles = sum(1 for word in ("front", "rear", "หน้า", "หลัง") if word in text)
    if axles >= 2:
        return 2
    if "dual" in text or "twin" in text:
        return 2
    if "tri-motor" in text or "three motor" in text:
        return 3
    return None


# --------------------------------------------------------------------------
# Emissions standards
# --------------------------------------------------------------------------

#: The export spends four boolean columns on one fact. Highest standard wins:
#: a car that satisfies Euro 6 also satisfies Euro 4.
_EMISSION_COLUMNS = (("std_euro6", "EURO6"), ("std_euro5", "EURO5"),
                     ("std_euro4", "EURO4"), ("std_tis", "TIS"))

_UN_COLUMNS = (("std_un_reg13", "R13"), ("std_un_reg13h", "R13H"),
               ("std_un_reg94", "R94"), ("std_un_reg95", "R95"),
               ("std_un_reg100", "R100"))


def emissions_standard(row: dict) -> Optional[str]:
    for column, value in _EMISSION_COLUMNS:
        if _flag(row.get(column)):
            return value
    return None


def un_regulations(row: dict) -> list[str]:
    return [value for column, value in _UN_COLUMNS if _flag(row.get(column))]


# --------------------------------------------------------------------------
# Equipment
# --------------------------------------------------------------------------

#: The equipment columns hold semicolon- or comma-joined Thai prose:
#: car_equip_factory alone has 3,915 distinct entries across 1,647 rows, of
#: which 1,499 appear exactly once. That tail cannot be compared and is not
#: turned into fields. These are the items present on enough vehicles to make
#: a column worth having, each with the spellings the source actually uses --
#: "ระบบเซ็นทรัลล็อก" and "ระบบเซ็นทรัลล๊อก" differ by one tone mark, and
#: ESC arrives as ESC, ESP, VSA and VSC.
_EQUIPMENT_RULES: dict[str, tuple[str, ...]] = {
    "safety.abs": ("abs", "ป้องกันล้อล็อก"),
    "safety.esc": ("esc", "esp", "vsa", "vsc", "ควบคุมการทรงตัว"),
    "safety.side_airbag": ("ถุงลมนิรภัยด้านข้าง", "side airbag"),
    "safety.curtain_airbag": ("ถุงลมนิรภัยแบบม่าน", "ถุงลมม่าน", "curtain airbag"),
    "safety.knee_airbag": ("ถุงลมบริเวณหัวเข่า", "ถุงลมหัวเข่า", "knee airbag"),
    "safety.driver_attention_alert": ("เหนื่อยล้า", "attention"),
    "safety.aeb": ("advanced emergency braking", "aeb", "เบรคฉุกเฉินขั้นสูง", "เบรกฉุกเฉินขั้นสูง"),
    "safety.forward_collision_warning": ("forward vehicle collision warning", "fcw", "เตือนการชนด้านหน้า"),
    "safety.lane_departure_warning": ("lane departure warning", "ldw", "เตือนการออกหรือเปลี่ยนช่องจราจร"),
    "safety.lane_keep_assist": ("lane keeping assistance", "lkas", "ดูแลภายในช่องจราจร"),
    "safety.blind_spot": ("blind spot", "bsd", "จุดอับสายตา", "จุดบอด"),
    "safety.adaptive_cruise": ("adaptive cruise control", "acc", "ควบคุมความเร็วของยานยนต์"),
    "safety.rear_cross_traffic": ("rear cross", "rcta", "rctb", "ขณะถอยหลัง"),
    "comfort.power_windows": ("กระจกไฟฟ้า",),
    "comfort.keyless_entry": ("กุญแจรีโมท", "keyless", "สมาร์ทคีย์", "สมาร์ทคีย์"),
    "comfort.auto_climate": ("ปรับอากาศอัตโนมัติ", "automatic climate"),
    "comfort.electric_parking_brake": ("เบรกมือไฟฟ้า", "electric parking"),
    "comfort.panoramic_roof": ("พาโนรามิก", "panoramic"),
    "comfort.ventilated_front_seats": ("ระบายอากาศ", "ventilated"),
    "technology.smartphone_mirroring": ("ระบบปฏิบัติการ ios", "carplay", "android auto"),
    "technology.connected_services": ("เชื่อมต่ออินเตอร์เน็ต", "เชื่อมต่ออินเทอร์เน็ต", "connected"),
    "technology.ota_update": ("ota", "over the air"),
    "technology.surround_view_camera": ("360", "surround"),
    "technology.head_up_display": ("head-up", "head up", "แสดงข้อมูลบนกระจก"),
    "technology.led_headlights": ("ไฟหน้าแบบ led", "ไฟหน้า led", "led headlight"),
}

#: Which of the export's list columns are searched for equipment.
_EQUIPMENT_COLUMNS = ("car_equip_safety", "car_equip_adas", "car_equip_factory",
                      "car_equip_connectivity", "car_equip_e_parts")

_AIRBAG_WORDS = ("ถุงลม", "airbag")


def _equipment_text(row: dict) -> str:
    parts = [_text(row.get(column)) for column in _EQUIPMENT_COLUMNS]
    return " ; ".join(p for p in parts if p).lower()


def equipment_flags(row: dict) -> dict[str, bool]:
    """True where the source lists an item, absent where it does not.

    Deliberately never False. The export lists what a car *has*; it does not
    state what a car lacks, so "not mentioned" is unknown, not absent. Writing
    False here would turn a gap in the source into a claim about the car.
    """
    haystack = _equipment_text(row)
    if not haystack:
        return {}
    return {key: True for key, needles in _EQUIPMENT_RULES.items()
            if any(needle in haystack for needle in needles)}


def airbag_count(row: dict) -> Optional[int]:
    """Count the airbag positions the source names.

    Each entry names one position ("ถุงลมนิรภัยด้านหน้าคนขับ"), except where
    it states a number itself ("ถุงลมนิรภัยด้านหน้า 2 ตำแหน่ง").
    """
    total = 0
    seen = set()
    for column in _EQUIPMENT_COLUMNS:
        for item in re.split(r"[;,]", _text(row.get(column))):
            entry = re.sub(r"\s+", " ", item).strip()
            if not entry or entry.lower() in seen:
                continue
            if not any(word in entry.lower() for word in _AIRBAG_WORDS):
                continue
            seen.add(entry.lower())
            positions = re.search(r"(\d+)\s*ตำแหน่ง", entry)
            total += int(positions.group(1)) if positions else 1
    return total or None


# --------------------------------------------------------------------------
# Charging
# --------------------------------------------------------------------------

def charging_port_type(type_charge: Any) -> Optional[str]:
    text = _text(type_charge).lower()
    if not text:
        return None
    on_board = "on board" in text or "onboard" in text
    external = "external" in text or "dc" in text
    if on_board and external:
        return "BOTH"
    if on_board:
        return "ONBOARD_AC"
    if external:
        return "EXTERNAL_DC"
    return "OTHER"


# --------------------------------------------------------------------------
# One row
# --------------------------------------------------------------------------

@dataclass
class NormalizedVehicle:
    """One export row, folded into values the catalogue can compare."""

    source_id: str
    brand_raw: str
    model_raw: str
    importer_raw: str
    powertrain: Optional[str]
    body_type: Optional[str]
    price_thb: Optional[int]
    #: The date this ECO record was approved (YYYY-MM-DD), which is when the
    #: source observed what it states. Facts are dated by this rather than by
    #: the day an import happens to run: the ledger keys a fact by its start,
    #: so an import-day stamp would invent a specification change on every
    #: monthly re-import and collapse the source's own chronology.
    approved_at: str = ""
    #: registry key -> canonical value, ready for an APPEND_SPEC fact.
    specs: dict[str, Any] = field(default_factory=dict)
    #: registry key -> {qualifier: value}
    qualifiers: dict[str, dict[str, str]] = field(default_factory=dict)
    #: Source text kept for a human to read, never compared.
    notes: dict[str, str] = field(default_factory=dict)
    #: What had to be corrected or withheld, and why, so a person can audit it.
    repairs: dict[str, str] = field(default_factory=dict)

    @property
    def source_url(self) -> str:
        return f"https://car.ecosticker.go.th/landing-page/detail/{self.source_id}"


#: Straight number columns: export column -> (registry key, converter).
_NUMERIC_SPECS: tuple[tuple[str, str, str], ...] = (
    ("car_seats", "vehicle.seats", "int"),
    ("total_weight", "vehicle.declared_total_weight_kg", "int"),
    ("model_year", "vehicle.model_year", "int"),
    ("capacity_cylinder", "engine.displacement_cc", "int"),

    ("nominal_voltage", "battery.nominal_voltage_v", "float"),
    ("driving_range", "ev.rated_range_km", "float"),
    ("energy_consumption", "ev.energy_consumption_wh_km", "float"),
    ("emissions_CO2", "emissions.co2_g_km", "float"),
    ("energy_combined_rate", "efficiency.fuel_consumption_l_100km", "float"),
    ("rate_energy_urban", "efficiency.fuel_consumption_urban_l_100km", "float"),
    ("rate_energy_ex_urban", "efficiency.fuel_consumption_extra_urban_l_100km", "float"),
)

_TEXT_SPECS: tuple[tuple[str, str], ...] = (
    ("battery_brand", "battery.supplier"),
    ("wheel_size", "fitment.tyre_size"),
    ("front_wheel", "fitment.tyre_front"),
    ("back_wheel", "fitment.tyre_rear"),
    ("on_board_charger", "charging.onboard_charger_spec"),
)

_GEAR_COUNT_FAMILIES = frozenset({"AUTOMATIC", "MANUAL"})

#: The ECO Sticker does not say which drive cycle its range and consumption
#: figures come from. Recording them as NEDC or WLTP would be a guess, and a
#: 500 km CLTC figure beside a 450 km WLTP one is a comparison that misleads.
#: They are labelled as what they verifiably are: the figure this programme
#: published. Every vehicle in the export is measured the same way, so they
#: compare correctly with each other, which is the case the site is for.
ECO_MEASUREMENT_BASIS = "ECO_STICKER_TH"

_BASIS_FIELDS = (
    "ev.rated_range_km", "ev.energy_consumption_wh_km",
    "efficiency.fuel_consumption_l_100km",
    "efficiency.fuel_consumption_urban_l_100km",
    "efficiency.fuel_consumption_extra_urban_l_100km",
    "emissions.co2_g_km",
)


def normalize_row(row: dict) -> NormalizedVehicle:
    """Fold one export row. Anything the source does not state stays absent."""
    vehicle = NormalizedVehicle(
        source_id=_text(row.get("id")).lower(),
        brand_raw=_text(row.get("brand")),
        model_raw=_text(row.get("model")),
        importer_raw=_text(row.get("company_name")),
        powertrain=powertrain(row.get("cartype_name"), row.get("engine_name"),
                              _text(row.get("model"))),
        body_type=body_type(row.get("car_style")),
        price_thb=_integer(row.get("recomend_retail_price_new")),
        approved_at=approval_date(row.get("approve_date")),
    )
    specs = vehicle.specs

    for column, key, kind in _NUMERIC_SPECS:
        value = _integer(row.get(column)) if kind == "int" else _number(row.get(column))
        if value is not None and value > 0:
            specs[key] = value
    for column, key in _TEXT_SPECS:
        value = _text(row.get(column))
        if value:
            specs[key] = value

    transmission = transmission_family(_text(row.get("gear_name")))
    gear_count = _integer(row.get("gear_speed"))
    if transmission in _GEAR_COUNT_FAMILIES and gear_count and gear_count > 0:
        specs["powertrain.gear_count"] = gear_count

    factory_raw = _text(row.get("factory"))
    if factory_raw:
        vehicle.notes["factory"] = factory_raw
        if is_identified_manufacturing_plant(factory_raw):
            specs["manufacturing.factory"] = factory_raw

    if vehicle.powertrain:
        specs["identity.powertrain"] = vehicle.powertrain
    for key, value in (
        ("engine.fuel_type", fuel_type(row.get("fuel_name"))),
        ("engine.combustion_type", combustion_type(row.get("engine_name"))),
        # _text() first: a spreadsheet blank arrives as float("nan"), which is
        # truthy, so handing it straight to the folders turns "no value" into
        # the literal family "OTHER" on every row that never stated one.
        ("powertrain.transmission", transmission),
        ("powertrain.motor_type", motor_type(row.get("motor"))),
        ("powertrain.motor_count", motor_count(row.get("motor"))),
        ("battery.chemistry", battery_chemistry_family(_text(row.get("battery_type")))),
        ("charging.port_type", charging_port_type(row.get("type_charge"))),
        ("emissions.standard", emissions_standard(row)),
        ("safety.airbag_count", airbag_count(row)),
    ):
        if value is not None:
            specs[key] = value

    # The export's ``battery_capacity`` is the pack's charge in ampere-hours,
    # not its energy in kilowatt-hours, and reading it as kWh put a 169 kWh
    # battery in a compact taxi. Energy is charge times voltage, and the
    # export states the nominal voltage on every row that states a capacity.
    #
    # Checked against the source's own range and consumption figures, which
    # are collected independently of the battery columns: read as kWh the
    # column is 2.48x the energy the car's own range implies and only 48 of
    # 490 rows are plausible; derived this way the median is 0.91x with 399
    # plausible -- and 0.91 is what it should be, because voltage times charge
    # is the gross pack and range times consumption is what is usable from it.
    #
    # It is filed as gross rather than catalog capacity for the same reason:
    # this is the nameplate pack, not the figure a brochure quotes.
    # NOx and particulates are quoted in milligrams per kilometre, the unit
    # the regulation is written in; the registry compares grams. Published as
    # they arrive, the median NOx figure would be 263 times the Euro 5 petrol
    # limit -- a number no homologated car could carry. Divided by a thousand
    # it is 0.26 times the limit, which is where a compliant car sits.
    for column, key in (("nox_amount", "emissions.nox_g_km"),
                        ("particulate_matters", "emissions.pm_g_km")):
        mg = _number(row.get(column))
        if mg is not None and mg > 0:
            specs[key] = round(mg / 1000, 5)

    charge_ah = _number(row.get("battery_capacity"))
    volts = _number(row.get("nominal_voltage"))
    if charge_ah and volts and charge_ah > 0 and volts > 0:
        specs["battery.gross_capacity_kwh"] = round(charge_ah * volts / 1000, 2)

    body_specs, repairs = dimensions(row)
    specs.update(body_specs)
    vehicle.repairs.update(repairs)

    regulations = un_regulations(row)
    if regulations:
        specs["safety.un_regulations"] = regulations

    # Stored as a percentage, which is how the rate is quoted and compared.
    tax = _number(row.get("tax_rate_new"))
    if tax is not None and 0 < tax <= 1:
        specs["manufacturing.excise_tax_rate"] = round(tax * 100, 2)

    specs.update(equipment_flags(row))

    for key in _BASIS_FIELDS:
        if key in specs:
            vehicle.qualifiers[key] = {"measurement_basis": ECO_MEASUREMENT_BASIS}

    # Kept for a person to read on the trim page. Not comparable, not a fact.
    for column in ("car_equip_factory", "car_equip_energy", "car_equip_connectivity"):
        text = _text(row.get(column))
        if text:
            vehicle.notes[column] = text
    return vehicle


def applicable_specs(vehicle: NormalizedVehicle, registry) -> tuple[dict[str, Any], list[str]]:
    """The subset of a row's values the registry will actually accept.

    Two things get dropped, and both are the source being loosely worded
    rather than the row being wrong. An ICE car frequently carries a
    ``battery_type`` -- that is its 12V starter battery, not a traction pack,
    and ``battery.chemistry`` is declared for HEV/PHEV/REEV/BEV only. And a
    key the registry does not know cannot be written at all.

    Returns the accepted values and the keys that were dropped, so an import
    can report what it discarded instead of discarding it quietly.
    """
    accepted: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in vehicle.specs.items():
        definition = registry.fields.get(key)
        if definition is None:
            dropped.append(key)
            continue
        allowed = definition.applicable_powertrains
        if allowed and (vehicle.powertrain or "") not in allowed:
            dropped.append(key)
            continue
        problems = definition.validate_value(
            ValueState.KNOWN, value, definition.canonical_unit
            if definition.value_type is ValueType.NUMBER else "")
        if problems:
            dropped.append(key)
            continue
        accepted[key] = value
    return accepted, dropped


__all__ = [
    "ECO_MEASUREMENT_BASIS",
    "applicable_specs",
    "IGNORED_COLUMNS",
    "NormalizedVehicle",
    "airbag_count",
    "body_type",
    "charging_port_type",
    "combustion_type",
    "emissions_standard",
    "equipment_flags",
    "fuel_type",
    "motor_count",
    "motor_type",
    "normalize_row",
    "powertrain",
    "un_regulations",
]
