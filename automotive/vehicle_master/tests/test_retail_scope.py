from __future__ import annotations

import json
from pathlib import Path

from vehreg.catalog import Catalog
from vehreg.model_operational_state import upsert_model_operational_state
from vehreg.retail_lifecycle_review import upsert_trim_lifecycle_disposition
from vehreg.retail_scope import (
    GENERATION_UNRESOLVED,
    MODEL_HISTORICAL,
    TRIM_RETIRED,
    UNDER_MAINTENANCE,
    current_generation_of,
    retail_scope_index,
    scoped_siblings_by_model,
    trim_price_eligibility,
    trim_review_index,
)

YEAR = 2026
MODEL_ID = "jaecoo.jaecoo_5_ev"
GEN_ID = MODEL_ID + ".j5"
OLD_GEN_ID = MODEL_ID + ".j4"
TRIM_ID = GEN_ID + ".trim.ultra_bev"
OLD_TRIM_ID = OLD_GEN_ID + ".trim.legacy_bev"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed(tmp_path: Path, *, second_generation: bool = False,
         second_generation_ended: str | None = "2025-01-01",
         retail_status: str = "CURRENT") -> Path:
    """One model, one current generation (J5, not ended), one trim (Ultra).

    ``second_generation`` adds a J4 generation so tests can exercise
    ambiguity (two non-ended generations) or a fully historical model
    (both generations ended).
    """
    data = tmp_path / "data"
    generations = [{
        "code": "J5", "segment": "B", "seats": 5,
        "launched": "2025-08-19", "ended": None,
        "variants": [{
            "id": "bev_cbu", "name": "58.9 kWh BEV CBU", "powertrain": "BEV",
            "drivetrain": "FWD", "engine_cc": None, "battery_kwh": 58.9,
            "price_thb": None, "price_min_thb": None, "price_max_thb": None,
            "import_type": "CBU", "origin_country": "CN",
            "price_note": "retail price lives on MarketTrim", "aliases": [],
        }],
        "trims": [{
            "id": "ultra_bev", "name": "Ultra", "variant": "58.9 kWh BEV CBU",
            "powertrain": "BEV", "drivetrain": "FWD", "battery_kwh": 58.9,
            "seats": 5, "aliases": [],
            "source_refs": {"oem": ["https://example.test/j5"]},
        }],
    }]
    if second_generation:
        generations.append({
            "code": "J4", "segment": "B", "seats": 5,
            "launched": "2023-01-01", "ended": second_generation_ended,
            "variants": [{
                "id": "legacy_bev", "name": "Legacy BEV", "powertrain": "BEV",
                "drivetrain": "FWD", "engine_cc": None, "battery_kwh": 50.0,
                "price_thb": None, "price_min_thb": None, "price_max_thb": None,
                "import_type": "CBU", "origin_country": "CN",
                "price_note": "", "aliases": [],
            }],
            "trims": [{
                "id": "legacy_bev", "name": "Legacy", "variant": "Legacy BEV",
                "powertrain": "BEV", "drivetrain": "FWD", "battery_kwh": 50.0,
                "seats": 5, "aliases": [],
                "source_refs": {"oem": ["https://example.test/j4"]},
            }],
        })
    _write_json(data / str(YEAR) / "models" / "jaecoo.json", {
        "brand": {
            "id": "jaecoo", "name_en": "Jaecoo", "name_th": "เจคู",
            "brand_segment": "MASS", "oem_group": "Chery", "brand_origin": "CN",
            "trim_detail": True, "aliases": [],
        },
        "models": [{
            "id": "jaecoo_5_ev", "name_en": "Jaecoo 5 EV", "name_th": "เจคู 5",
            "nameplate": "Jaecoo 5", "body_type": "CROSSOVER",
            "cab_type": "NOT_APPLICABLE", "registration_type": "",
            "market_scope": "CORE", "aliases": [],
            "retail_status": retail_status,
            "retail_checked_at": "2026-09-11",
            "retail_source": "https://example.test/j5/model",
            "generations": generations,
        }],
    })
    return data


def _catalog(data_dir: Path) -> Catalog:
    return Catalog.load(data_dir, YEAR)


def test_current_generation_of_resolves_the_one_non_ended_generation(tmp_path):
    data = _seed(tmp_path)
    catalog = _catalog(data)
    generation = current_generation_of(catalog, MODEL_ID)
    assert generation is not None
    assert generation.id == GEN_ID


def test_current_generation_of_is_none_when_every_generation_has_ended(tmp_path):
    data = _seed(tmp_path, second_generation=True, second_generation_ended="2025-01-01")
    # Force the "current" generation to have ended too, so both are historical.
    raw = json.loads((data / str(YEAR) / "models" / "jaecoo.json").read_text(encoding="utf-8"))
    raw["models"][0]["generations"][0]["ended"] = "2026-01-01"
    _write_json(data / str(YEAR) / "models" / "jaecoo.json", raw)
    catalog = _catalog(data)
    assert current_generation_of(catalog, MODEL_ID) is None


def test_current_generation_of_is_none_when_two_generations_are_both_open(tmp_path):
    data = _seed(tmp_path, second_generation=True, second_generation_ended=None)
    catalog = _catalog(data)
    assert current_generation_of(catalog, MODEL_ID) is None


def test_scope_blocks_model_under_maintenance(tmp_path):
    data = _seed(tmp_path)
    upsert_model_operational_state(
        data_dir=data, year=YEAR, model_id=MODEL_ID, action="under_maintenance",
        reviewer="ops", reviewed_at="2026-09-24", notes="generation changeover in progress",
        write=True,
    )
    catalog = _catalog(data)
    scope = retail_scope_index(catalog, data_dir=data, year=YEAR)[MODEL_ID]
    assert not scope.in_scope
    assert scope.blocked_reason == UNDER_MAINTENANCE


def test_maintenance_can_be_cleared_back_to_normal(tmp_path):
    data = _seed(tmp_path)
    upsert_model_operational_state(
        data_dir=data, year=YEAR, model_id=MODEL_ID, action="under_maintenance",
        reviewer="ops", reviewed_at="2026-09-24", write=True,
    )
    upsert_model_operational_state(
        data_dir=data, year=YEAR, model_id=MODEL_ID, action="normal",
        reviewer="ops", reviewed_at="2026-09-25", write=True,
    )
    catalog = _catalog(data)
    scope = retail_scope_index(catalog, data_dir=data, year=YEAR)[MODEL_ID]
    assert scope.in_scope


def test_scope_blocks_canonically_historical_model(tmp_path):
    data = _seed(tmp_path, retail_status="HISTORICAL")
    catalog = _catalog(data)
    scope = retail_scope_index(catalog, data_dir=data, year=YEAR)[MODEL_ID]
    assert not scope.in_scope
    assert scope.blocked_reason == MODEL_HISTORICAL


def test_scope_blocks_ambiguous_generation(tmp_path):
    data = _seed(tmp_path, second_generation=True, second_generation_ended=None)
    catalog = _catalog(data)
    scope = retail_scope_index(catalog, data_dir=data, year=YEAR)[MODEL_ID]
    assert not scope.in_scope
    assert scope.blocked_reason == GENERATION_UNRESOLVED


def test_scoped_siblings_excludes_trims_outside_the_current_generation(tmp_path):
    data = _seed(tmp_path, second_generation=True, second_generation_ended="2025-01-01")
    catalog = _catalog(data)
    siblings = scoped_siblings_by_model(catalog, data_dir=data, year=YEAR)
    trim_ids = {t.id for t in siblings.get(MODEL_ID, [])}
    assert trim_ids == {TRIM_ID}
    assert OLD_TRIM_ID not in trim_ids


def test_scoped_siblings_excludes_human_retired_trim(tmp_path):
    data = _seed(tmp_path)
    upsert_trim_lifecycle_disposition(
        data_dir=data, year=YEAR, trim_id=TRIM_ID, action="historical",
        reviewer="retail-reviewer", reviewed_at="2026-09-11",
        source_ref="https://example.test/j5/retired", write=True,
    )
    catalog = _catalog(data)
    siblings = scoped_siblings_by_model(catalog, data_dir=data, year=YEAR)
    assert MODEL_ID not in siblings  # the model's only trim was just retired


def test_scoped_siblings_omits_blocked_models_entirely(tmp_path):
    data = _seed(tmp_path)
    upsert_model_operational_state(
        data_dir=data, year=YEAR, model_id=MODEL_ID, action="under_maintenance",
        reviewer="ops", reviewed_at="2026-09-24", write=True,
    )
    catalog = _catalog(data)
    siblings = scoped_siblings_by_model(catalog, data_dir=data, year=YEAR)
    assert MODEL_ID not in siblings


def test_trim_price_eligibility_mirrors_scoped_siblings(tmp_path):
    data = _seed(tmp_path, second_generation=True, second_generation_ended="2025-01-01")
    catalog = _catalog(data)
    scope_index = retail_scope_index(catalog, data_dir=data, year=YEAR)
    trim_reviews = trim_review_index(data_dir=data, year=YEAR)

    ok, reason = trim_price_eligibility(
        catalog, TRIM_ID, scope_index=scope_index, trim_reviews=trim_reviews)
    assert ok and reason == ""

    ok, reason = trim_price_eligibility(
        catalog, OLD_TRIM_ID, scope_index=scope_index, trim_reviews=trim_reviews)
    assert not ok
    assert reason == GENERATION_UNRESOLVED


def test_trim_price_eligibility_reports_retired(tmp_path):
    data = _seed(tmp_path)
    upsert_trim_lifecycle_disposition(
        data_dir=data, year=YEAR, trim_id=TRIM_ID, action="historical",
        reviewer="retail-reviewer", reviewed_at="2026-09-11",
        source_ref="https://example.test/j5/retired", write=True,
    )
    catalog = _catalog(data)
    scope_index = retail_scope_index(catalog, data_dir=data, year=YEAR)
    trim_reviews = trim_review_index(data_dir=data, year=YEAR)
    ok, reason = trim_price_eligibility(
        catalog, TRIM_ID, scope_index=scope_index, trim_reviews=trim_reviews)
    assert not ok
    assert reason == TRIM_RETIRED


def test_real_catalog_has_zero_blocked_models_and_full_trim_coverage():
    """Sanity check against the actual repository catalog: the strict
    generation/lifecycle scope must not silently drop real coverage today
    -- every one of the 321 real models resolves to exactly one current
    generation and no trim has been human-retired yet."""
    from vehreg.catalog import DATA_DIR, DEFAULT_YEAR

    catalog = Catalog.load(DATA_DIR, DEFAULT_YEAR)
    scope_index = retail_scope_index(catalog, data_dir=DATA_DIR, year=DEFAULT_YEAR)
    blocked = {model_id: scope.blocked_reason
              for model_id, scope in scope_index.items() if scope.blocked_reason}
    assert blocked == {}

    siblings = scoped_siblings_by_model(catalog, data_dir=DATA_DIR, year=DEFAULT_YEAR)
    assert sum(len(v) for v in siblings.values()) == len(catalog.trims)
