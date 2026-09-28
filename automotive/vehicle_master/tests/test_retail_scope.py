from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest

from vehreg.catalog import Catalog
from vehreg.model_operational_state import upsert_model_operational_state
from vehreg.retail_lifecycle_review import upsert_trim_lifecycle_disposition
from vehreg.retail_scope import (
    GENERATION_UNRESOLVED,
    MODEL_HISTORICAL,
    TRIM_RETIRED,
    UNDER_MAINTENANCE,
    active_generations_of,
    current_generation_of,
    retail_scope_index,
    scoped_siblings_by_model,
    siblings_from_scope,
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
    """One model, one current generation (J5), optionally plus J4."""
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


def test_current_generation_of_resolves_the_one_active_generation(tmp_path):
    data = _seed(tmp_path)
    catalog = _catalog(data)
    generation = current_generation_of(catalog, MODEL_ID, as_of=date(2026, 9, 25))
    assert generation is not None
    assert generation.id == GEN_ID


def test_current_generation_of_is_none_when_every_generation_has_ended(tmp_path):
    data = _seed(tmp_path, second_generation=True, second_generation_ended="2025-01-01")
    raw = json.loads((data / str(YEAR) / "models" / "jaecoo.json").read_text(encoding="utf-8"))
    raw["models"][0]["generations"][0]["ended"] = "2026-01-01"
    _write_json(data / str(YEAR) / "models" / "jaecoo.json", raw)
    catalog = _catalog(data)
    assert current_generation_of(catalog, MODEL_ID, as_of=date(2026, 9, 25)) is None
    assert active_generations_of(catalog, MODEL_ID, as_of=date(2026, 9, 25)) == ()


def test_overlap_is_allowed_and_both_generations_are_active(tmp_path):
    data = _seed(tmp_path, second_generation=True, second_generation_ended=None)
    catalog = _catalog(data)
    assert current_generation_of(catalog, MODEL_ID, as_of=date(2026, 9, 25)) is None
    active = active_generations_of(catalog, MODEL_ID, as_of=date(2026, 9, 25))
    assert {generation.id for generation in active} == {GEN_ID, OLD_GEN_ID}
    scope = retail_scope_index(
        catalog, data_dir=data, year=YEAR, as_of=date(2026, 9, 25))[MODEL_ID]
    assert scope.in_scope
    assert scope.blocked_reason == ""
    siblings = scoped_siblings_by_model(
        catalog, data_dir=data, year=YEAR, as_of=date(2026, 9, 25))
    assert {trim.id for trim in siblings[MODEL_ID]} == {TRIM_ID, OLD_TRIM_ID}


def test_future_end_date_remains_active_until_as_of_reaches_it(tmp_path):
    data = _seed(tmp_path, second_generation=True, second_generation_ended="2026-12-31")
    catalog = _catalog(data)
    september = active_generations_of(catalog, MODEL_ID, as_of=date(2026, 9, 25))
    assert {generation.id for generation in september} == {GEN_ID, OLD_GEN_ID}
    december_31 = active_generations_of(catalog, MODEL_ID, as_of=date(2026, 12, 31))
    assert {generation.id for generation in december_31} == {GEN_ID}


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


def test_scope_blocks_when_no_generation_is_active(tmp_path):
    data = _seed(tmp_path)
    raw = json.loads((data / str(YEAR) / "models" / "jaecoo.json").read_text(encoding="utf-8"))
    raw["models"][0]["generations"][0]["ended"] = "2026-01-01"
    _write_json(data / str(YEAR) / "models" / "jaecoo.json", raw)
    catalog = _catalog(data)
    scope = retail_scope_index(
        catalog, data_dir=data, year=YEAR, as_of=date(2026, 9, 25))[MODEL_ID]
    assert not scope.in_scope
    assert scope.blocked_reason == GENERATION_UNRESOLVED


def test_scoped_siblings_excludes_trims_outside_active_generations(tmp_path):
    data = _seed(tmp_path, second_generation=True, second_generation_ended="2025-01-01")
    catalog = _catalog(data)
    siblings = scoped_siblings_by_model(
        catalog, data_dir=data, year=YEAR, as_of=date(2026, 9, 25))
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
    assert MODEL_ID not in siblings


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
    scope_index = retail_scope_index(
        catalog, data_dir=data, year=YEAR, as_of=date(2026, 9, 25))
    trim_reviews = trim_review_index(data_dir=data, year=YEAR)

    ok, reason = trim_price_eligibility(
        catalog, TRIM_ID, scope_index=scope_index, trim_reviews=trim_reviews, approved_index={})
    assert ok and reason == ""

    ok, reason = trim_price_eligibility(
        catalog, OLD_TRIM_ID, scope_index=scope_index, trim_reviews=trim_reviews, approved_index={})
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
        catalog, TRIM_ID, scope_index=scope_index, trim_reviews=trim_reviews, approved_index={})
    assert not ok
    assert reason == TRIM_RETIRED


def test_real_catalog_has_zero_unexpected_blocks_and_fully_accounted_trim_coverage():
    """Price scope may omit a trim only for an accounted reason: a genuinely
    HISTORICAL model (a deliberate retirement, not an accidental gap), an
    explicit HUMAN trim retirement, or exclusion from an owner-approved
    current-retail set (vehreg/current_retail.py). No other gap is
    acceptable -- UNDER_MAINTENANCE/GENERATION_UNRESOLVED/UNKNOWN_MODEL would
    mean real catalog trouble, not intended scope.

    The original version of this test asserted `blocked == {}` and full
    catalog-wide trim coverage minus only HUMAN-reviewed trims; both were
    accurate for the catalog's state at the time but are now obsolete now that
    real repairs have both retired whole models to HISTORICAL (REPAIR-04) and
    introduced owner-approved current-retail sets (REPAIR-06/07) that
    deliberately narrow a model's CURRENT trims below its full catalog
    membership. This version keeps the same rigor -- every trim's scope
    membership is checked, not just an aggregate count -- while accounting for
    both mechanisms explicitly instead of asserting they don't exist.
    """
    from vehreg.catalog import DATA_DIR, DEFAULT_YEAR
    from vehreg.current_retail import load_current_retail_index

    catalog = Catalog.load(DATA_DIR, DEFAULT_YEAR)
    scope_index = retail_scope_index(catalog, data_dir=DATA_DIR, year=DEFAULT_YEAR)
    blocked = {model_id: scope.blocked_reason
              for model_id, scope in scope_index.items() if scope.blocked_reason}
    assert set(blocked.values()) <= {MODEL_HISTORICAL}

    siblings = scoped_siblings_by_model(catalog, data_dir=DATA_DIR, year=DEFAULT_YEAR)
    scoped_trim_ids = {trim.id for trims in siblings.values() for trim in trims}
    reviews = trim_review_index(data_dir=DATA_DIR, year=DEFAULT_YEAR)
    historical_trim_ids = {
        trim_id for trim_id, review in reviews.items()
        if review.get("status") == "HISTORICAL"
    }
    approved_index = load_current_retail_index(data_dir=DATA_DIR, year=DEFAULT_YEAR)

    for trim_id, trim in catalog.trims.items():
        generation = catalog.generations.get(trim.generation_id)
        model_id = generation.model_id if generation else None
        scope = scope_index.get(model_id)
        if scope is None or not scope.in_scope:
            # Whole model out of scope -- must be one of the accounted
            # MODEL_HISTORICAL blocks asserted above, never a silent gap.
            assert trim_id not in scoped_trim_ids
            continue
        approved = approved_index.get(model_id)
        if approved is not None:
            # Explicitly managed model: approved-set membership is the sole
            # question; a HISTORICAL review on a non-member is irrelevant here.
            assert (trim_id in scoped_trim_ids) == (trim_id in approved)
        else:
            # Legacy model: full coverage minus only explicit HUMAN retirement.
            assert (trim_id in scoped_trim_ids) == (trim_id not in historical_trim_ids)


def test_siblings_from_scope_requires_approved_index_explicitly(tmp_path):
    """Forgetting current-retail authority must be a loud TypeError at the call
    site, not a silent fallback to legacy eligibility for a model that has
    since been explicitly managed (this was the exact bug in
    tools/price_coverage_backfill.py, which bypassed scoped_siblings_by_model
    and constructed its own siblings map with no approved_index at all)."""
    data = _seed(tmp_path)
    catalog = _catalog(data)
    scope_index = retail_scope_index(catalog, data_dir=data, year=YEAR)
    trim_reviews = trim_review_index(data_dir=data, year=YEAR)

    with pytest.raises(TypeError):
        siblings_from_scope(catalog, scope_index, trim_reviews)  # type: ignore[call-arg]

    # An isolated caller that genuinely wants pre-authority legacy behavior
    # (e.g. this very test file's other fixtures, which have no
    # current_retail.json at all) must say so explicitly.
    siblings = siblings_from_scope(catalog, scope_index, trim_reviews, approved_index={})
    assert {trim.id for trim in siblings[MODEL_ID]} == {TRIM_ID}


def test_trim_price_eligibility_requires_approved_index_explicitly(tmp_path):
    data = _seed(tmp_path)
    catalog = _catalog(data)
    scope_index = retail_scope_index(catalog, data_dir=data, year=YEAR)
    trim_reviews = trim_review_index(data_dir=data, year=YEAR)

    with pytest.raises(TypeError):
        trim_price_eligibility(  # type: ignore[call-arg]
            catalog, TRIM_ID, scope_index=scope_index, trim_reviews=trim_reviews)

    ok, reason = trim_price_eligibility(
        catalog, TRIM_ID, scope_index=scope_index, trim_reviews=trim_reviews, approved_index={})
    assert ok and reason == ""
