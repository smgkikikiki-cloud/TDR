"""tools/ecosticker_import.py's CLI: the monthly wrapper over
tools.import_source.plan_source_import.

Coverage this file owns, now that command-building itself lives in
vehreg/source_import.py and is proven against the real pipeline in
tests/test_source_import_specs.py: the CLI's own four reports (applied,
unresolved, dropped, repaired), its --observed-at fallback wiring, and that
--apply actually lands through the real CanonicalInputPipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pandas
import pytest

from vehreg.catalog import Catalog
from tools.ecosticker_import import main

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


def eco_row(model: str, **overrides) -> dict:
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
        "approve_date": "2026-06-01T09:00:00+07:00",
    }
    base.update(overrides)
    return base


def _write_export(path: Path, rows: list[dict]) -> None:
    pandas.DataFrame(rows).to_csv(path, index=False)


def test_matched_row_is_applied_with_facts_and_price(tree, tmp_path, capsys):
    export = tmp_path / "export.csv"
    _write_export(export, [eco_row("Runner Premium")])  # matches the existing Premium ICE trim

    report_dir = tree / str(YEAR) / "market" / "trims"
    rc = main([str(export), "--observed-at", "2026-09-18", "--data-dir", str(tree),
              "--year", str(YEAR), "--report-dir", str(report_dir)])
    assert rc == 0

    applied = json.loads((report_dir / "ecosticker_import_2026-09-18_applied.json").read_text())
    assert applied["count"] == 1
    row = applied["rows"][0]
    assert row["status"] == "MATCHED"
    assert row["trim_id"] == "acme.runner.gen1.trim.premium"
    assert row["facts"] > 0
    assert row["price_thb"] == 899000

    unresolved = json.loads((report_dir / "ecosticker_import_2026-09-18_unresolved.json").read_text())
    assert unresolved["count"] == 0


def test_new_grade_under_a_single_generation_model_is_a_new_trim(tree, tmp_path):
    export = tmp_path / "export.csv"
    # A different powertrain (BEV) than the existing Premium (ICE) trim: no
    # sibling in this row's own scope goes unclaimed, so resolve_rows()
    # creates it rather than treating the name as a possible respelling of
    # an existing grade it cannot place this run.
    _write_export(export, [eco_row("Runner Long Range", id="aaaaaaaa-0000-0000-0000-000000000000",
                                   cartype_name="BEV", engine_name="ไฟฟ้า",
                                   capacity_cylinder="-", fuel_name="-", driving_range="480")])

    report_dir = tree / str(YEAR) / "market" / "trims"
    main([str(export), "--observed-at", "2026-09-18", "--data-dir", str(tree),
         "--year", str(YEAR), "--report-dir", str(report_dir)])

    applied = json.loads((report_dir / "ecosticker_import_2026-09-18_applied.json").read_text())
    assert applied["rows"][0]["status"] == "NEW_TRIM"


def test_unresolvable_brand_is_reported_not_guessed(tree, tmp_path):
    export = tmp_path / "export.csv"
    _write_export(export, [eco_row("Whatever", brand="TOTALLY UNKNOWN BRAND")])

    report_dir = tree / str(YEAR) / "market" / "trims"
    main([str(export), "--observed-at", "2026-09-18", "--data-dir", str(tree),
         "--year", str(YEAR), "--report-dir", str(report_dir)])

    unresolved = json.loads((report_dir / "ecosticker_import_2026-09-18_unresolved.json").read_text())
    assert unresolved["count"] == 1
    applied = json.loads((report_dir / "ecosticker_import_2026-09-18_applied.json").read_text())
    assert applied["count"] == 0


def test_inapplicable_value_is_counted_in_dropped(tree, tmp_path):
    export = tmp_path / "export.csv"
    # battery.chemistry is inapplicable to an ICE row -- dropped, not written.
    _write_export(export, [eco_row("Runner Premium", battery_type="Lead Acid")])

    report_dir = tree / str(YEAR) / "market" / "trims"
    main([str(export), "--observed-at", "2026-09-18", "--data-dir", str(tree),
         "--year", str(YEAR), "--report-dir", str(report_dir)])

    dropped = json.loads((report_dir / "ecosticker_import_2026-09-18_dropped.json").read_text())
    assert dropped.get("battery.chemistry") == 1


def test_conflicting_same_day_prices_are_withheld_and_reported_as_repaired(tree, tmp_path):
    export = tmp_path / "export.csv"
    _write_export(export, [
        eco_row("Runner Premium", id="aaaaaaaa-0000-0000-0000-000000000001",
               recomend_retail_price_new="899000", approve_date="2026-06-01T09:00:00+07:00"),
        eco_row("Runner Premium", id="aaaaaaaa-0000-0000-0000-000000000002",
               recomend_retail_price_new="905000", approve_date="2026-06-01T10:00:00+07:00"),
    ])

    report_dir = tree / str(YEAR) / "market" / "trims"
    main([str(export), "--observed-at", "2026-09-18", "--data-dir", str(tree),
         "--year", str(YEAR), "--report-dir", str(report_dir)])

    applied = json.loads((report_dir / "ecosticker_import_2026-09-18_applied.json").read_text())
    assert all(row["price_thb"] is None for row in applied["rows"])

    repaired = json.loads((report_dir / "ecosticker_import_2026-09-18_repaired.json").read_text())
    assert repaired["count"] == 2
    assert all("price" in row["repairs"] for row in repaired["rows"])


def test_no_approval_date_falls_back_to_observed_at(tree, tmp_path):
    export = tmp_path / "export.csv"
    _write_export(export, [eco_row("Runner Premium", approve_date="")])

    report_dir = tree / str(YEAR) / "market" / "trims"
    main([str(export), "--observed-at", "2026-09-18", "--data-dir", str(tree),
         "--year", str(YEAR), "--report-dir", str(report_dir)])

    applied = json.loads((report_dir / "ecosticker_import_2026-09-18_applied.json").read_text())
    assert applied["rows"][0]["facts"] > 0
    assert applied["rows"][0]["price_thb"] == 899000


def test_apply_writes_through_the_real_pipeline_and_catalogue_validates(tree, tmp_path):
    export = tmp_path / "export.csv"
    _write_export(export, [eco_row("Runner Premium")])

    report_dir = tree / str(YEAR) / "market" / "trims"
    rc = main([str(export), "--observed-at", "2026-09-18", "--data-dir", str(tree),
              "--year", str(YEAR), "--report-dir", str(report_dir), "--apply"])
    assert rc == 0
    assert Catalog.load(tree, YEAR).validate() == []
