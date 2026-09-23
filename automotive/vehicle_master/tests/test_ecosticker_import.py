"""Resolving an ECO Sticker export row's identity against the catalogue.

Turning a resolved row into canonical commands is not this module's job any
more -- vehreg/source_import.py does that (proven against the real pipeline
in tests/test_source_import_specs.py and tests/test_ecosticker_import_cli.py)
-- so this file covers only plan_row()'s own three-way classification
(MATCHED/NEW_TRIM/UNRESOLVED) and trim_label()'s grade-name extraction.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from vehreg.catalog import Catalog
from vehreg.comparable_specs import SpecRegistry
from vehreg.ecosticker_import import MATCHED, NEW_TRIM, UNRESOLVED, plan_row, trim_label

YEAR = 2026
REAL_REGISTRY = (Path(__file__).resolve().parents[1] / "vehreg" / "data" / "2026"
                 / "product" / "comparable_specs" / "registry.json")


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A catalogue with one brand, two models, and one existing trim."""
    data = tmp_path / "data"
    _write(data / str(YEAR) / "models" / "acme.json", {
        "brand": {"id": "acme", "name_en": "Acme", "name_th": "",
                  "brand_segment": "MASS", "oem_group": "UNKNOWN",
                  "brand_origin": "TH", "trim_detail": False, "aliases": []},
        "models": [
            {"id": "runner", "name_en": "Runner", "name_th": "", "nameplate": "",
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
             }]},
            # Two generations, so a new grade cannot be placed automatically.
            {"id": "twogen", "name_en": "Twogen", "name_th": "", "nameplate": "",
             "body_type": "SEDAN", "cab_type": "NOT_APPLICABLE",
             "registration_type": "", "market_scope": "CORE", "aliases": [],
             "generations": [
                 {"code": "g1", "segment": "B", "seats": 5, "launched": "2020-01-01",
                  "ended": "2024-12-31",
                  "variants": [{"id": "v2", "name": "Twogen 1.5 ICE", "powertrain": "ICE",
                    "drivetrain": "FWD", "engine_cc": 1496, "battery_kwh": None,
                    "price_thb": None, "price_min_thb": None, "price_max_thb": None,
                    "import_type": "CKD", "origin_country": "TH", "price_note": "",
                    "aliases": []}],
                  "trims": []},
                 {"code": "g2", "segment": "B", "seats": 5, "launched": "2025-01-01",
                  "ended": None,
                  "variants": [{"id": "v3", "name": "Twogen 1.5 II ICE", "powertrain": "ICE",
                    "drivetrain": "FWD", "engine_cc": 1496, "battery_kwh": None,
                    "price_thb": None, "price_min_thb": None, "price_max_thb": None,
                    "import_type": "CKD", "origin_country": "TH", "price_note": "",
                    "aliases": []}],
                  "trims": []},
             ]},
        ],
    })
    target = data / str(YEAR) / "product" / "comparable_specs" / "registry.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    # The real registry, not a stand-in: unit and powertrain applicability are
    # what decide which of a row's values survive.
    shutil.copyfile(REAL_REGISTRY, target)
    return data


@pytest.fixture
def catalog(tree: Path) -> Catalog:
    return Catalog.load(tree, YEAR)


@pytest.fixture
def registry(tree: Path) -> SpecRegistry:
    return SpecRegistry.load(tree, YEAR)


def row(model: str, **overrides) -> dict:
    base = {
        "id": "3283e6a6-999d-4964-91d2-064f22b13369",
        "brand": "ACME", "model": model, "cartype_name": "ICE",
        "car_style": "รถยนต์นั่ง 4 ประตู (Sedan)", "company_name": "Acme Co",
        "model_year": "2026", "factory": "Acme Plant",
        "recomend_retail_price_new": "899000", "tax_rate_new": "0.15",
        "engine_name": "แก๊สโซลีน", "fuel_name": "เชื้อเพลิงผสม (เบนซิน-E20)",
        "gear_name": "เกียร์อัตโนมัติ", "capacity_cylinder": "1496.0",
        "car_seats": "5", "car_length": "4500", "car_width": "1780",
        "car_height": "1460", "total_weight": "1600", "wheel_size": "205/55R16",
        "emissions_CO2": "120", "energy_combined_rate": "5.2",
        "std_tis": "1", "car_equip_safety": "ABS; ESC/VSA/VSC",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Pulling the grade out of the source's model cell
# ---------------------------------------------------------------------------

def test_the_grade_is_what_is_left_after_the_model_name():
    assert trim_label("ALPHARD HYBRID G 2WD CAR", "Alphard") == "HYBRID G 2WD CAR"
    assert trim_label("Jaecoo 5 EV Long Range Max", "Jaecoo 5 EV") == "Long Range Max"
    # The catalogue's name may be longer than what the source writes.
    assert trim_label("911 CARRERA COUPE", "Porsche 911") == "CARRERA COUPE"
    # fold() splits letters from digits, so "Z9GT" would never line up token
    # for token with the one word it came from; matching is on the raw string.
    assert trim_label("DENZA Z9GT PERFORMANCE", "Denza Z9GT") == "PERFORMANCE"
    # The source's own casing survives: this becomes a name a person reads.
    assert trim_label("COROLLA CROSS HYBRID PREMIUM", "Corolla Cross") == "HYBRID PREMIUM"
    assert trim_label("Yaris Ativ", "Yaris Ativ") == ""


# ---------------------------------------------------------------------------
# The three situations a row can be in
# ---------------------------------------------------------------------------

def test_a_grade_already_in_the_catalogue_attaches_to_it(catalog, registry):
    plan = plan_row(row("Runner Premium"), catalog, registry)
    assert plan.status == MATCHED
    assert plan.trim_id == "acme.runner.gen1.trim.premium"
    assert plan.model_id == "acme.runner"
    assert plan.specs["vehicle.seats"] == 5
    assert plan.specs["engine.fuel_type"] == "E20"


def test_a_grade_the_catalogue_does_not_have_is_planned_as_new(catalog, registry):
    plan = plan_row(row("Runner Sport"), catalog, registry)
    assert plan.status == NEW_TRIM
    assert plan.trim_name == "Sport"
    # The id comes from the shared identity rule, not a local slug.
    assert plan.trim_id == "acme.runner.gen1.trim.sport_ice"


def test_powertrain_must_agree_before_a_grade_counts_as_the_same_product(catalog, registry):
    """"Runner Premium" petrol and "Runner Premium" hybrid are different cars.
    Merging them would report one car's economy against the other's price."""
    plan = plan_row(row("Runner Premium", engine_name="ไฮบริด (HEV)"),
                    catalog, registry)
    assert plan.vehicle.powertrain == "HEV"
    assert plan.status == NEW_TRIM
    assert plan.trim_id != "acme.runner.gen1.trim.premium"


def test_an_unknown_brand_is_reported_not_guessed(catalog, registry):
    plan = plan_row(row("Whatever GT", brand="NOTABRAND"), catalog, registry)
    assert plan.status == UNRESOLVED
    assert "NOTABRAND" in plan.reason


def test_a_model_with_two_generations_is_left_for_a_person(catalog, registry):
    """Placing a new grade means choosing a generation, and choosing wrong
    attaches a 2026 car to a body that went off sale in 2024."""
    plan = plan_row(row("Twogen Sport"), catalog, registry)
    assert plan.status == UNRESOLVED
    assert "generation" in plan.reason


def test_a_row_whose_powertrain_cannot_be_established_is_not_imported(catalog, registry):
    plan = plan_row(row("Runner Sport", cartype_name="-", engine_name="อื่นๆ"),
                    catalog, registry)
    assert plan.status == UNRESOLVED
    assert plan.vehicle.powertrain is None
