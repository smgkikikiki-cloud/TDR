from vehreg.catalog import Catalog, DATA_DIR
from vehreg.trim_reconciliation import (
    apply_canonical_trim_overlay,
    load_canonical_trim_overlay,
    load_reconciliation_state,
    release_reconciliation_report,
    validate_reconciliation_state,
)


def _base_release(catalog: Catalog) -> dict:
    brands = [
        {
            "canonical_id": brand.id,
            "name_en": brand.name_en,
        }
        for brand in catalog.brands.values()
    ]
    models = [
        {
            "canonical_id": model.id,
            "brand_id": model.brand_id,
            "name_en": model.name_en,
        }
        for model in catalog.models.values()
    ]
    generations = [
        {
            "canonical_id": generation.id,
            "model_id": generation.model_id,
        }
        for generation in catalog.generations.values()
    ]
    market_trims = [
        {
            "canonical_id": trim.id,
            "model_id": catalog.generations[trim.generation_id].model_id,
            "generation_id": trim.generation_id,
            "source_refs": {key: list(values) for key, values in trim.source_refs.items()},
        }
        for trim in catalog.trims.values()
    ]
    return {
        "year": 2026,
        "as_of": "2026-09-16",
        "brands": brands,
        "models": models,
        "generations": generations,
        "market_trims": market_trims,
        "counts": {"market_trims": len(market_trims)},
    }


def test_2026_reconciliation_state_references_real_catalog():
    catalog = Catalog.load(DATA_DIR, 2026)
    state = load_reconciliation_state(DATA_DIR, 2026)
    assert len(state["models"]) == 36
    assert validate_reconciliation_state(catalog, state) == []


def test_2026_canonical_overlay_and_reconciliation_are_release_safe():
    catalog = Catalog.load(DATA_DIR, 2026)
    base = _base_release(catalog)
    overlay = load_canonical_trim_overlay(DATA_DIR, 2026)
    out = apply_canonical_trim_overlay(base, data_dir=DATA_DIR, year=2026)

    # A bulk source import may already have materialised some of these exact
    # canonical MarketTrim ids in the base catalog. The overlay must therefore
    # behave as a set union, merging evidence on collisions rather than adding
    # a duplicate row or requiring every overlay row to increase the count.
    base_ids = {row["canonical_id"] for row in base["market_trims"]}
    overlay_ids = {
        f"{row['generation_id']}.trim.{row['id']}"
        for row in overlay["trims"]
    }
    out_ids = [row["canonical_id"] for row in out["market_trims"]]
    assert len(out_ids) == len(set(out_ids))
    assert set(out_ids) == base_ids | overlay_ids
    assert out["counts"]["market_trims"] == len(base_ids | overlay_ids)

    report = release_reconciliation_report(out, data_dir=DATA_DIR, year=2026)
    assert report["tracked_models"] == 36
    assert report["blocker_count"] == 0
    assert sum(row["source_trim_count"] for row in report["models"]) == 111
    assert sum(row["canonical_source_trim_count"] for row in report["models"]) == 83
    assert sum(row["unresolved_source_trim_count"] for row in report["models"]) == 28

    # No READY row may retain source evidence outside canonical MarketTrim.
    assert all(
        row["unresolved_source_trim_count"] == 0
        for row in report["models"]
        if row["declared_status"] == "READY"
    )

    # The only intentionally non-market source row is Honda e:N2 concept/future.
    non_market = [row for row in report["models"] if row["declared_status"] == "NON_MARKET"]
    assert [(row["model_id"], row["unresolved_source_trim_count"]) for row in non_market] == [
        ("honda.en2", 1)
    ]
