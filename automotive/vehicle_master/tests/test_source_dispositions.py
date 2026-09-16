from vehreg.catalog import Catalog, DATA_DIR
from vehreg.trim_reconciliation import apply_canonical_trim_overlay
from tdr_bridge.source_dispositions import (
    load_source_dispositions,
    release_reconciliation_report_with_dispositions,
)
from tdr_bridge.trim_fragments import apply_verified_trim_fragments


def _base_release(catalog: Catalog) -> dict:
    return {
        "year": 2026,
        "as_of": "2026-09-16",
        "brands": [
            {"canonical_id": brand.id, "name_en": brand.name_en}
            for brand in catalog.brands.values()
        ],
        "models": [
            {"canonical_id": model.id, "brand_id": model.brand_id, "name_en": model.name_en}
            for model in catalog.models.values()
        ],
        "generations": [
            {"canonical_id": gen.id, "model_id": gen.model_id}
            for gen in catalog.generations.values()
        ],
        "market_trims": [
            {
                "canonical_id": trim.id,
                "model_id": catalog.generations[trim.generation_id].model_id,
                "generation_id": trim.generation_id,
                "source_refs": {key: list(values) for key, values in trim.source_refs.items()},
            }
            for trim in catalog.trims.values()
        ],
        "counts": {"market_trims": len(catalog.trims)},
    }


def _report() -> dict:
    catalog = Catalog.load(DATA_DIR, 2026)
    release = _base_release(catalog)
    release = apply_canonical_trim_overlay(release, data_dir=DATA_DIR, year=2026)
    release = apply_verified_trim_fragments(release, data_dir=DATA_DIR, year=2026)
    return release_reconciliation_report_with_dispositions(
        release, data_dir=DATA_DIR, year=2026,
    )


def _row(report: dict, model_id: str) -> dict:
    return next(row for row in report["models"] if row["model_id"] == model_id)


def test_dispositions_name_real_owner_rows_and_balance_accounting():
    dispositions = load_source_dispositions(DATA_DIR, 2026)
    assert sum(len(rows) for rows in dispositions.values()) == 10

    report = _report()
    assert report["blocker_count"] == 0
    assert report["source_row_totals"] == {
        "source_trim_rows": 111,
        "canonical_source_rows": 92,
        "disposed_source_rows": 10,
        "unresolved_source_rows": 9,
    }
    assert report["counts"] == {
        "AMBIGUOUS_POWERTRAIN": 1,
        "CANONICAL": 26,
        "NON_MARKET": 1,
        "RECONCILED": 4,
        "RESEARCH_UNRESOLVED": 4,
    }


def test_stale_and_aggregate_rows_are_not_research_debt():
    report = _report()

    bentley = _row(report, "bentley.flying_spur")
    assert bentley["disposed_source_trim_count"] == 1
    assert bentley["unresolved_source_trim_count"] == 0
    assert bentley["status"] == "RECONCILED"
    assert bentley["source_dispositions"][0]["source_name"] == "Flying Spur Speed / Mulliner"
    assert bentley["source_dispositions"][0]["disposition"] == "AGGREGATE_SOURCE_ROW"

    e07 = _row(report, "deepal.deepal_e07")
    assert e07["canonical_source_trim_count"] == 0
    assert e07["disposed_source_trim_count"] == 4
    assert e07["unresolved_source_trim_count"] == 0
    assert e07["status"] == "RECONCILED"

    for model_id in ("toyota.hilux_travo_cab", "toyota.hilux_travo_double_cab"):
        row = _row(report, model_id)
        assert row["disposed_source_trim_count"] == 2
        assert row["unresolved_source_trim_count"] == 0
        assert row["status"] == "RECONCILED"


def test_non_market_source_row_stays_non_market_when_fully_accounted():
    report = _report()
    en2 = _row(report, "honda.en2")
    assert en2["canonical_trim_count"] == 0
    assert en2["disposed_source_trim_count"] == 1
    assert en2["unresolved_source_trim_count"] == 0
    assert en2["status"] == "NON_MARKET"
    assert en2["source_dispositions"][0]["disposition"] == "NON_MARKET_SOURCE_ROW"


def test_only_true_ambiguity_remains_unresolved():
    report = _report()
    unresolved = {
        row["model_id"]: row["unresolved_source_trim_count"]
        for row in report["models"]
        if row["unresolved_source_trim_count"]
    }
    assert unresolved == {
        "avatr.avatr_07": 1,
        "land_rover.range_rover": 1,
        "land_rover.range_rover_sport": 3,
        "land_rover.range_rover_velar": 3,
        "leapmotor.leapmotor_c10": 1,
    }
