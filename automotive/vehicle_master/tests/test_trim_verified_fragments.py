from vehreg.catalog import Catalog, DATA_DIR
from vehreg.trim_reconciliation import apply_canonical_trim_overlay
from tdr_bridge.trim_fragments import (
    apply_verified_trim_fragments,
    load_reconciliation_with_overrides,
    release_reconciliation_report_with_overrides,
)


def _base_release(catalog: Catalog) -> dict:
    return {
        "year": 2026,
        "as_of": "2026-09-16",
        "brands": [
            {"canonical_id": brand.id, "name_en": brand.name_en}
            for brand in catalog.brands.values()
        ],
        "models": [
            {
                "canonical_id": model.id,
                "brand_id": model.brand_id,
                "name_en": model.name_en,
            }
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
                "source_refs": {
                    key: list(values) for key, values in trim.source_refs.items()
                },
            }
            for trim in catalog.trims.values()
        ],
        "counts": {"market_trims": len(catalog.trims)},
    }


def _row(report: dict, model_id: str) -> dict:
    return next(row for row in report["models"] if row["model_id"] == model_id)


def test_verified_fragments_load_against_real_2026_catalog():
    catalog = Catalog.load(DATA_DIR, 2026)
    base = _base_release(catalog)
    owner = apply_canonical_trim_overlay(base, data_dir=DATA_DIR, year=2026)
    out = apply_verified_trim_fragments(owner, data_dir=DATA_DIR, year=2026)

    # Base catalog, owner overlay and verified fragments are independent
    # evidence streams. A later ECO bulk import can materialise an id that an
    # overlay already knows, so counts are no longer additive. The invariant is
    # one serving row per canonical id, with earlier rows preserved.
    base_ids = {row["canonical_id"] for row in base["market_trims"]}
    owner_ids = {row["canonical_id"] for row in owner["market_trims"]}
    out_ids = [row["canonical_id"] for row in out["market_trims"]]
    assert base_ids <= owner_ids <= set(out_ids)
    assert len(out_ids) == len(set(out_ids))
    assert out["counts"]["market_trims"] == len(out_ids)


def test_verified_reconciliation_reduces_only_rows_that_really_map():
    catalog = Catalog.load(DATA_DIR, 2026)
    base = _base_release(catalog)
    owner = apply_canonical_trim_overlay(base, data_dir=DATA_DIR, year=2026)
    out = apply_verified_trim_fragments(owner, data_dir=DATA_DIR, year=2026)
    state = load_reconciliation_with_overrides(DATA_DIR, 2026)
    report = release_reconciliation_report_with_overrides(out, data_dir=DATA_DIR, year=2026)

    assert len(state["models"]) == 36
    assert report["tracked_models"] == 36
    assert report["blocker_count"] == 0
    assert sum(row["source_trim_count"] for row in report["models"]) == 111
    assert sum(row["canonical_source_trim_count"] for row in report["models"]) == 92
    assert sum(row["unresolved_source_trim_count"] for row in report["models"]) == 19

    assert _row(report, "avatr.avatr_07")["unresolved_source_trim_count"] == 1
    assert _row(report, "bentley.flying_spur")["unresolved_source_trim_count"] == 1
    # Total MarketTrim count is allowed to grow from other evidence streams
    # (notably ECO); source reconciliation below remains scoped to its own refs.
    assert _row(report, "deepal.deepal_e07")["unresolved_source_trim_count"] == 4

    gac = _row(report, "gac.gac_m8")
    assert gac["unresolved_source_trim_count"] == 0
    assert gac["status"] == "CANONICAL"

    rr = _row(report, "land_rover.range_rover")
    assert rr["canonical_source_trim_count"] == 2
    assert rr["unresolved_source_trim_count"] == 1

    c10 = _row(report, "leapmotor.leapmotor_c10")
    assert c10["canonical_source_trim_count"] == 2
    assert c10["unresolved_source_trim_count"] == 1

    # These source rows are still unresolved regardless of how many additional
    # ECO-backed retail grades now exist under the same pickup model.
    travo_cab = _row(report, "toyota.hilux_travo_cab")
    assert travo_cab["canonical_source_trim_count"] == 0
    assert travo_cab["unresolved_source_trim_count"] == 2

    travo_double = _row(report, "toyota.hilux_travo_double_cab")
    assert travo_double["canonical_source_trim_count"] == 0
    assert travo_double["unresolved_source_trim_count"] == 2

    # READY still means fully reconciled. Later evidence may downgrade a stale
    # READY/AMBIGUOUS row to RESEARCH_UNRESOLVED, but may never hide a READY gap.
    assert all(
        row["unresolved_source_trim_count"] == 0
        for row in report["models"]
        if row["declared_status"] == "READY"
    )
