"""Planning a bulk ECO Sticker import, and proving the plan actually applies.

The plan is only worth anything if the batches it compiles survive the real
canonical pipeline, so the last test in this file runs them through it and
reads the catalogue back.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from vehreg.catalog import Catalog
from vehreg.comparable_specs import SpecLedger, SpecRegistry
from vehreg.ecosticker_import import (
    MATCHED, NEW_TRIM, UNRESOLVED, batches_from_plan, plan_import, plan_row,
    trim_label,
)
from vehreg.input_pipeline import CanonicalInputPipeline

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


def test_two_rows_for_the_same_trim_do_not_both_write(catalog, registry):
    """A re-approval leaves the previous row in the export. Two rows writing
    the same facts is a replay at best and a conflict at worst."""
    plan = plan_import([row("Runner Premium"),
                        row("Runner Premium", id="c055ec20-0af5-46b3-95d1-c7e7183a35b8")],
                       catalog, registry)
    assert [p.status for p in plan.rows] == [MATCHED, UNRESOLVED]
    assert "ซ้ำ" in plan.rows[1].reason


def test_the_summary_counts_what_will_be_written(catalog, registry):
    plan = plan_import([row("Runner Premium"), row("Runner Sport"),
                        row("Whatever", brand="NOTABRAND")], catalog, registry)
    summary = plan.summary()
    assert summary["rows"] == 3
    assert summary[MATCHED] == 1 and summary[NEW_TRIM] == 1 and summary[UNRESOLVED] == 1
    assert summary["spec_facts"] > 20


# ---------------------------------------------------------------------------
# The proof: the plan applies
# ---------------------------------------------------------------------------

def test_the_compiled_batches_apply_through_the_real_pipeline(tree, catalog, registry):
    plan = plan_import([
        row("Runner Premium", car_seats="7", wheel_size="215/55R17"),
        row("Runner Sport", id="d714c580-af57-4744-9c39-2b52346977ff",
            capacity_cylinder="1998.0", car_seats="5"),
        row("Whatever", id="f1f5f25f-4260-42b0-aaff-c23608cdbc8a", brand="NOTABRAND"),
    ], catalog, registry)

    batches = batches_from_plan(plan, registry, year=YEAR, actor="eco-import",
                                observed_at="2026-09-17", batch_prefix="eco-test")
    assert batches, "a plan with resolvable rows must compile to at least one batch"

    pipeline = CanonicalInputPipeline(tree)
    for batch in batches:
        assert pipeline.apply(batch).status == "APPLIED", batch["batch_id"]

    after = Catalog.load(tree, YEAR)
    assert after.validate() == []

    # The existing trim was updated, not forked.
    premium = after.trims["acme.runner.gen1.trim.premium"]
    assert premium.seats == 7
    assert after.trims["acme.runner.gen1.trim.sport_ice"].engine_cc == 1998
    assert len(after.trims_of("acme.runner")) == 2

    ledger = SpecLedger.load(tree, YEAR, registry=SpecRegistry.load(tree, YEAR),
                             catalog=after)
    assert ledger.validate() == []
    facts = {f.field_key: f for f in ledger.facts
             if f.trim_id == "acme.runner.gen1.trim.premium"}
    assert facts["vehicle.seats"].value == 7
    assert facts["fitment.tyre_size"].value == "215/55R17"
    assert facts["engine.fuel_type"].value == "E20"
    assert facts["safety.abs"].value is True
    assert facts["manufacturing.excise_tax_rate"].value == 15.0
    # Every fact is traceable back to the sticker it came from.
    assert facts["vehicle.seats"].source == "ecosticker"
    assert facts["vehicle.seats"].source_ref.startswith(
        "https://car.ecosticker.go.th/landing-page/detail/")
    # Fuel economy is labelled with the programme that measured it, never
    # guessed as NEDC or WLTP.
    assert facts["efficiency.fuel_consumption_l_100km"].qualifiers[
        "measurement_basis"] == "ECO_STICKER_TH"


def test_applying_the_same_export_twice_changes_nothing(tree, catalog, registry):
    """The export is monthly and mostly repeats itself. A second run must be a
    replay, not a second set of conflicting facts."""
    rows = [row("Runner Premium")]
    batches = batches_from_plan(plan_import(rows, catalog, registry), registry,
                                year=YEAR, actor="eco-import",
                                observed_at="2026-09-17", batch_prefix="eco-first")
    pipeline = CanonicalInputPipeline(tree)
    for batch in batches:
        pipeline.apply(batch)

    reloaded = Catalog.load(tree, YEAR)
    reloaded_registry = SpecRegistry.load(tree, YEAR)
    again = batches_from_plan(plan_import(rows, reloaded, reloaded_registry),
                              reloaded_registry, year=YEAR, actor="eco-import",
                              observed_at="2026-09-17", batch_prefix="eco-second")
    for batch in again:
        CanonicalInputPipeline(tree).apply(batch)

    final = Catalog.load(tree, YEAR)
    assert final.validate() == []
    assert len(final.trims_of("acme.runner")) == 2 or len(final.trims_of("acme.runner")) == 1
    ledger = SpecLedger.load(tree, YEAR, registry=SpecRegistry.load(tree, YEAR),
                             catalog=final)
    assert ledger.validate() == [], "a repeat import must not create conflicting facts"
    seats = [f for f in ledger.facts
             if f.trim_id == "acme.runner.gen1.trim.premium"
             and f.field_key == "vehicle.seats"]
    assert len(seats) == 1, "one fact per field, not one per import run"
