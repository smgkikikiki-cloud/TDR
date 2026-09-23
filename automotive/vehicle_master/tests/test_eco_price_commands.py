"""tools.import_source.compile_price_commands: an ECO Sticker filed price
becomes ECO_STICKER_PRICE history, never a guess at which of two
disagreeing records is the real one.

Every test drives the real pipeline where it matters: normalize_row via
plan_row, resolve_rows, and (for the end-to-end cases) a real
CanonicalInputPipeline.apply() read back with PriceLedger.load().
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pandas
import pytest

from vehreg.catalog import Catalog
from vehreg.comparable_specs import SpecRegistry
from vehreg.pricing import PriceLedger, PriceType
from tools.import_source import compile_price_commands, main

YEAR = 2026
REAL_REGISTRY = (Path(__file__).resolve().parents[1] / "vehreg" / "data" / str(YEAR)
                 / "product" / "comparable_specs" / "registry.json")


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
    target = data / str(YEAR) / "product" / "comparable_specs" / "registry.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REAL_REGISTRY, target)
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
        "model_year": "2026", "factory": "-",
        "recomend_retail_price_new": "899000", "tax_rate_new": "0.15",
        "engine_name": "แก๊สโซลีน", "fuel_name": "เชื้อเพลิงผสม (เบนซิน-E20)",
        "gear_name": "เกียร์อัตโนมัติ", "capacity_cylinder": "1496.0",
        "car_seats": "5", "car_length": "4500", "car_width": "1780",
        "car_height": "1460", "total_weight": "1600", "wheel_size": "205/55R16",
        "emissions_CO2": "120", "energy_combined_rate": "5.2",
        "std_tis": "1", "car_equip_safety": "ABS; ESC/VSA/VSC",
        "approve_date": "2026-06-01T09:00:00+07:00",
    }
    base.update(overrides)
    return base


def _write_export(path: Path, rows: list[dict]) -> None:
    pandas.DataFrame(rows).to_csv(path, index=False)


def _run(tree: Path, rows: list[dict], *, tmp_path: Path, prefix: str, apply: bool = False):
    export = tmp_path / f"{prefix}.csv"
    _write_export(export, rows)
    report_dir = tree / str(YEAR) / "market" / "trims"
    argv = [str(export), "--source", "ECO", "--data-dir", str(tree),
           "--year", str(YEAR), "--report-dir", str(report_dir),
           "--submitted-at", "2026-09-23T08:00:00+00:00"]
    if apply:
        argv.append("--apply")
    rc = main(argv)
    assert rc == 0
    report = json.loads((report_dir / f"import_eco_{prefix}_report.json").read_text())
    exceptions = json.loads((report_dir / f"import_eco_{prefix}_exceptions.json").read_text())
    return report, exceptions


def test_the_price_is_dated_by_the_rows_own_approval_date(tree, tmp_path):
    report, _ = _run(tree, [eco_row("Runner Premium",
                                    approve_date="2023-04-11T09:00:00+07:00",
                                    recomend_retail_price_new="899000")],
                     tmp_path=tmp_path, prefix="dated")
    assert report["price_commands"] == 1


def test_apply_records_eco_sticker_price_and_never_surfaces_as_list_price(tree, catalog, tmp_path):
    report, _ = _run(tree, [eco_row("Runner Premium", recomend_retail_price_new="899000")],
                     tmp_path=tmp_path, prefix="apply1", apply=True)
    assert report["applied"] is True
    assert report["post_apply_catalog_problems"] == 0
    assert report["post_apply_spec_problems"] == 0
    assert report["post_apply_price_problems"] == 0

    final = Catalog.load(tree, YEAR)
    ledger = PriceLedger.load(tree, year=YEAR, catalog=final)
    trim_id = "acme.runner.gen1.trim.premium"
    records = ledger.records_for(trim_id)
    assert [r.amount_thb for r in records] == [899000]
    assert records[0].price_type is PriceType.ECO_STICKER_PRICE
    assert records[0].observed_at == "2026-06-01"
    # The thing that must never happen: it is not the current list price.
    assert ledger.current_list_amount(trim_id) is None


def test_no_stated_price_produces_no_price_command(tree, tmp_path):
    for blank in ("", "-", "0"):
        report, _ = _run(tree, [eco_row("Runner Premium", recomend_retail_price_new=blank)],
                         tmp_path=tmp_path, prefix=f"blank{blank or 'empty'}")
        assert report["price_commands"] == 0


def test_the_same_amount_filed_twice_is_one_price_observation(tree, tmp_path):
    report, _ = _run(tree, [
        eco_row("Runner Premium", id="aaaaaaaa-0000-0000-0000-000000000001",
               approve_date="2024-01-10T09:00:00+07:00", recomend_retail_price_new="899000"),
        eco_row("Runner Premium", id="aaaaaaaa-0000-0000-0000-000000000002",
               approve_date="2024-01-10T09:00:00+07:00", recomend_retail_price_new="899000"),
    ], tmp_path=tmp_path, prefix="dup")
    assert report["price_commands"] == 1
    assert report["price_equal_duplicates_collapsed"] == 1
    assert report["price_conflicts"] == 0


def test_two_different_prices_one_day_are_withheld_not_guessed(tree, tmp_path):
    """The Civic EL+/Everest case: two ECO records disagree on one trim's
    price for one date. Neither is written; both are reported."""
    report, exceptions = _run(tree, [
        eco_row("Runner Premium", id="aaaaaaaa-0000-0000-0000-000000000003",
               approve_date="2026-03-01T09:00:00+07:00", recomend_retail_price_new="949000"),
        eco_row("Runner Premium", id="aaaaaaaa-0000-0000-0000-000000000004",
               approve_date="2026-03-01T09:00:00+07:00", recomend_retail_price_new="1109000"),
    ], tmp_path=tmp_path, prefix="conflict")
    assert report["price_commands"] == 0
    assert report["price_conflicts"] == 1
    conflict = next(c for c in exceptions["conflicts"]
                    if c["conflicts"][0]["field_key"] == "price.eco_sticker_price")
    values = {v["value"] for v in conflict["conflicts"][0]["values"]}
    assert values == {949000, 1109000}


def test_a_new_record_conflicting_with_an_already_published_price_is_withheld(
        tree, catalog, tmp_path):
    """Not just within one workbook -- a later import that disagrees with an
    already-published ECO_STICKER_PRICE for the same trim/date is withheld
    too, never silently retracting the published record."""
    first_report, _ = _run(tree, [eco_row(
        "Runner Premium", id="aaaaaaaa-0000-0000-0000-000000000005",
        approve_date="2026-05-01T09:00:00+07:00", recomend_retail_price_new="1527000",
    )], tmp_path=tmp_path, prefix="published", apply=True)
    assert first_report["price_commands"] == 1

    second_report, exceptions = _run(tree, [eco_row(
        "Runner Premium", id="aaaaaaaa-0000-0000-0000-000000000006",
        approve_date="2026-05-01T09:00:00+07:00", recomend_retail_price_new="1619000",
    )], tmp_path=tmp_path, prefix="disagree")
    assert second_report["price_commands"] == 0
    assert second_report["price_conflicts"] == 1

    final = Catalog.load(tree, YEAR)
    ledger = PriceLedger.load(tree, year=YEAR, catalog=final)
    records = ledger.records_for("acme.runner.gen1.trim.premium")
    assert [r.amount_thb for r in records] == [1527000], \
        "the published price must survive untouched"


def test_direct_unit_conflict_against_existing_ledger(tree, catalog):
    """compile_price_commands itself, not just through main() -- proving the
    existing-ledger comparison independent of a real apply."""
    from vehreg.ecosticker_export import normalize_row
    from vehreg.source_import import PATCHED, RowOutcome, SourceRow

    vehicle_a = normalize_row(eco_row("Runner Premium", id="cccccccc-0000-0000-0000-000000000001",
                                      recomend_retail_price_new="1000000"))
    row = SourceRow(source_id=vehicle_a.source_id, source_kind="ECO",
                    model_id="acme.runner", generation_id="acme.runner.gen1",
                    powertrain="ICE", trim_name="Premium", values={})
    outcome = RowOutcome(row=row, status=PATCHED, trim_id="acme.runner.gen1.trim.premium")

    empty_ledger = PriceLedger(YEAR, catalog=catalog)
    commands, stats, conflicts = compile_price_commands(
        [outcome], {vehicle_a.source_id: vehicle_a}, empty_ledger)
    assert len(commands) == 1 and stats["price_conflicts"] == 0

    conflicting_ledger = PriceLedger(YEAR, catalog=catalog)
    conflicting_ledger.add_payload({"prices": [{
        "trim_id": "acme.runner.gen1.trim.premium", "amount_thb": 1200000,
        "price_type": "ECO_STICKER_PRICE", "observed_at": vehicle_a.approved_at,
        "source": "ecosticker", "source_ref": "https://example.invalid/existing",
    }]})
    commands, stats, conflicts = compile_price_commands(
        [outcome], {vehicle_a.source_id: vehicle_a}, conflicting_ledger)
    assert commands == []
    assert stats["price_conflicts"] == 1
    assert len(conflicts) == 1


def test_a_pilot_models_eco_price_is_excluded_not_published(tree, catalog):
    """A pilot model's current market price is promoted from its own
    manufacturer's listing, never from an ECO filing alone -- an ECO price
    landing on one would contest a more authoritative source, not merely
    duplicate it, so it is excluded outright rather than merely withheld
    as a conflict."""
    from vehreg.ecosticker_export import normalize_row
    from vehreg.source_import import PATCHED, RowOutcome, SourceRow

    vehicle = normalize_row(eco_row("Runner Premium", id="dddddddd-0000-0000-0000-000000000001",
                                    recomend_retail_price_new="1000000"))
    row = SourceRow(source_id=vehicle.source_id, source_kind="ECO",
                    model_id="acme.runner", generation_id="acme.runner.gen1",
                    powertrain="ICE", trim_name="Premium", values={})
    outcome = RowOutcome(row=row, status=PATCHED, trim_id="acme.runner.gen1.trim.premium")
    empty_ledger = PriceLedger(YEAR, catalog=catalog)

    commands, stats, conflicts = compile_price_commands(
        [outcome], {vehicle.source_id: vehicle}, empty_ledger,
        pilot_model_ids=frozenset({"acme.runner"}))
    assert commands == []
    assert conflicts == []
    assert stats["price_pilot_model_skipped"] == 1
    assert stats["price_commands"] == 0

    # A different model_id in the pilot set does not exclude this one.
    commands, stats, conflicts = compile_price_commands(
        [outcome], {vehicle.source_id: vehicle}, empty_ledger,
        pilot_model_ids=frozenset({"some.other.model"}))
    assert len(commands) == 1
    assert stats["price_pilot_model_skipped"] == 0


def test_main_excludes_pilot_model_prices_end_to_end(tree, catalog, tmp_path):
    """The same exclusion, driven through main() against a real cohort file,
    for a model main() itself resolves the pilot list from -- not just the
    unit-level compile_price_commands call."""
    _write(tree / str(YEAR) / "product" / "comparable_specs" / "cohorts" / "c_crossover.json", {
        "id": "c_crossover", "segment": "B", "body_type": "SEDAN",
        "model_ids": ["acme.runner"],
        "representative_source_ids": {"acme.runner": "some-source-id"},
    })
    report, exceptions = _run(tree, [eco_row("Runner Premium", recomend_retail_price_new="899000")],
                              tmp_path=tmp_path, prefix="pilot_e2e")
    assert report["price_commands"] == 0
    assert report["price_pilot_model_skipped"] == 1
