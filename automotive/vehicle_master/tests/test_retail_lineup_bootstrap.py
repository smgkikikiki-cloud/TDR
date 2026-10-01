from __future__ import annotations

import json
from pathlib import Path

import pytest

from vehreg.catalog import Catalog
from vehreg.normalize import trim_identity
from vehreg.retail_lineup_bootstrap import (
    LineupAction,
    RetailLineupBootstrapError,
    baseline_hash_for_models,
    plan_retail_lineup,
)


YEAR = 2026
MODEL_ID = "acme.echo"
GEN_ID = f"{MODEL_ID}.e1"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _trim(local_id: str, name: str, powertrain: str = "BEV") -> dict:
    return {
        "id": local_id,
        "name": name,
        "powertrain": powertrain,
        "aliases": [],
        "source_refs": {},
    }


def _seed_catalog(tmp_path: Path, *, trims: list[dict],
                  retail_status: str = "UNVERIFIED", ended: str | None = None) -> Catalog:
    data = tmp_path / "data"
    _write_json(data / str(YEAR) / "models" / "acme.json", {
        "brand": {
            "id": "acme", "name_en": "Acme", "name_th": "",
            "brand_segment": "MASS", "brand_origin": "US", "aliases": [],
        },
        "models": [{
            "id": "echo", "name_en": "Echo", "name_th": "",
            "body_type": "SEDAN", "cab_type": "NOT_APPLICABLE",
            "registration_type": "RY1", "market_scope": "CORE", "aliases": [],
            "retail_status": retail_status,
            "generations": [{
                "code": "E1", "segment": "C", "seats": 5,
                "launched": "2025-01-01", "ended": ended,
                "variants": [{
                    "id": "bev", "name": "Echo BEV", "powertrain": "BEV",
                    "drivetrain": "FWD", "price_thb": None, "import_type": "CBU",
                    "origin_country": "US", "aliases": [], "battery_kwh": 60.0,
                }], "trims": trims,
            }],
        }],
    })
    return Catalog.load(data, YEAR)


def _actions(plan):
    return {
        item.canonical_trim_id: item
        for model in plan.models
        for item in model.items
    }


def test_planner_classifies_keep_create_reactivate_archive(tmp_path):
    catalog = _seed_catalog(tmp_path, trims=[
        _trim("old_a_bev", "Old A"),
        _trim("keep_b_bev", "Keep B"),
        _trim("return_c_bev", "Return C"),
    ])
    old_a = f"{GEN_ID}.trim.old_a_bev"
    keep_b = f"{GEN_ID}.trim.keep_b_bev"
    return_c = f"{GEN_ID}.trim.return_c_bev"
    new_d = trim_identity(GEN_ID, None, "New D", "BEV")

    plan = plan_retail_lineup([
        {
            "model_id": MODEL_ID, "generation_id": GEN_ID,
            "trim_name": "Keep B", "powertrain": "BEV",
            "canonical_trim_id": keep_b,
        },
        {
            "model_id": MODEL_ID, "generation_id": GEN_ID,
            "trim_name": "Return C", "powertrain": "BEV",
            "canonical_trim_id": return_c,
        },
        {
            "model_id": MODEL_ID, "generation_id": GEN_ID,
            "trim_name": "New D", "powertrain": "BEV",
        },
    ], catalog=catalog,
       current_retail_index={MODEL_ID: frozenset({old_a, keep_b})},
       lifecycle_decisions=[{"trim_id": return_c, "status": "HISTORICAL"}],
       as_of="2026-09-30")

    actions = _actions(plan)
    assert actions[keep_b].action is LineupAction.KEEP
    assert actions[return_c].action is LineupAction.REACTIVATE
    assert actions[return_c].reopen_required is True
    assert actions[new_d].action is LineupAction.CREATE
    assert actions[old_a].action is LineupAction.ARCHIVE
    assert plan.models[0].target_current_trim_ids == tuple(sorted({keep_b, return_c, new_d}))
    assert plan.counts == {"keep": 1, "create": 1, "reactivate": 1, "archive": 1}


def test_similar_name_is_not_fuzzy_matched(tmp_path):
    catalog = _seed_catalog(tmp_path, trims=[_trim("premium_bev", "Premium")])
    existing = f"{GEN_ID}.trim.premium_bev"
    plan = plan_retail_lineup([{
        "model_id": MODEL_ID, "generation_id": GEN_ID,
        "trim_name": "Premium Plus", "powertrain": "BEV",
    }], catalog=catalog,
       current_retail_index={MODEL_ID: frozenset({existing})},
       as_of="2026-09-30")

    actions = _actions(plan)
    created = trim_identity(GEN_ID, None, "Premium Plus", "BEV")
    assert actions[created].action is LineupAction.CREATE
    assert actions[existing].action is LineupAction.ARCHIVE


def test_explicit_id_must_match_name_generation_and_powertrain(tmp_path):
    catalog = _seed_catalog(tmp_path, trims=[_trim("premium_bev", "Premium")])
    existing = f"{GEN_ID}.trim.premium_bev"

    with pytest.raises(RetailLineupBootstrapError, match="does not rename"):
        plan_retail_lineup([{
            "model_id": MODEL_ID, "generation_id": GEN_ID,
            "trim_name": "Premium Renamed", "powertrain": "BEV",
            "canonical_trim_id": existing,
        }], catalog=catalog, as_of="2026-09-30")

    with pytest.raises(RetailLineupBootstrapError, match="powertrain"):
        plan_retail_lineup([{
            "model_id": MODEL_ID, "generation_id": GEN_ID,
            "trim_name": "Premium", "powertrain": "HEV",
            "canonical_trim_id": existing,
        }], catalog=catalog, as_of="2026-09-30")


def test_unknown_powertrain_is_refused(tmp_path):
    catalog = _seed_catalog(tmp_path, trims=[])
    with pytest.raises(RetailLineupBootstrapError, match="UNKNOWN"):
        plan_retail_lineup([{
            "model_id": MODEL_ID, "generation_id": GEN_ID,
            "trim_name": "Mystery", "powertrain": "UNKNOWN",
        }], catalog=catalog, as_of="2026-09-30")


def test_duplicate_target_identity_is_refused(tmp_path):
    catalog = _seed_catalog(tmp_path, trims=[])
    row = {
        "model_id": MODEL_ID, "generation_id": GEN_ID,
        "trim_name": "New D", "powertrain": "BEV",
    }
    with pytest.raises(RetailLineupBootstrapError, match="duplicate target MarketTrim"):
        plan_retail_lineup([row, dict(row)], catalog=catalog, as_of="2026-09-30")


def test_stale_baseline_is_refused(tmp_path):
    catalog = _seed_catalog(tmp_path, trims=[_trim("premium_bev", "Premium")])
    current = {MODEL_ID: frozenset({f"{GEN_ID}.trim.premium_bev"})}
    baseline = baseline_hash_for_models(
        catalog, [MODEL_ID], current_retail_index=current, as_of="2026-09-30")

    plan_retail_lineup([{
        "model_id": MODEL_ID, "generation_id": GEN_ID,
        "trim_name": "Premium", "powertrain": "BEV",
    }], catalog=catalog, current_retail_index=current,
       expected_baseline_hash=baseline, as_of="2026-09-30")

    with pytest.raises(RetailLineupBootstrapError, match="STALE_BASELINE"):
        plan_retail_lineup([{
            "model_id": MODEL_ID, "generation_id": GEN_ID,
            "trim_name": "Premium", "powertrain": "BEV",
        }], catalog=catalog, current_retail_index=current,
           expected_baseline_hash="0" * 64, as_of="2026-09-30")


def test_plan_is_order_independent(tmp_path):
    catalog = _seed_catalog(tmp_path, trims=[_trim("a_bev", "A")])
    a = f"{GEN_ID}.trim.a_bev"
    rows = [
        {"model_id": MODEL_ID, "generation_id": GEN_ID,
         "trim_name": "A", "powertrain": "BEV"},
        {"model_id": MODEL_ID, "generation_id": GEN_ID,
         "trim_name": "B", "powertrain": "BEV"},
    ]
    kwargs = dict(catalog=catalog,
                  current_retail_index={MODEL_ID: frozenset({a})},
                  as_of="2026-09-30", base_release_id="release-123")
    first = plan_retail_lineup(rows, **kwargs)
    second = plan_retail_lineup(list(reversed(rows)), **kwargs)
    assert first.plan_hash == second.plan_hash
    assert first.as_dict() == second.as_dict()


def test_legacy_current_by_default_excludes_historical_decision(tmp_path):
    catalog = _seed_catalog(tmp_path, trims=[
        _trim("a_bev", "A"), _trim("b_bev", "B"),
    ])
    a = f"{GEN_ID}.trim.a_bev"
    b = f"{GEN_ID}.trim.b_bev"
    plan = plan_retail_lineup([{
        "model_id": MODEL_ID, "generation_id": GEN_ID,
        "trim_name": "A", "powertrain": "BEV",
    }], catalog=catalog,
       lifecycle_decisions=[{"trim_id": b, "status": "HISTORICAL"}],
       as_of="2026-09-30")

    assert plan.models[0].before_current_trim_ids == (a,)
    assert _actions(plan)[a].action is LineupAction.KEEP
    assert b not in _actions(plan)


def test_ended_generation_and_historical_model_cannot_be_targeted(tmp_path):
    ended = _seed_catalog(tmp_path, trims=[], ended="2026-09-01")
    with pytest.raises(RetailLineupBootstrapError, match="already ended"):
        plan_retail_lineup([{
            "model_id": MODEL_ID, "generation_id": GEN_ID,
            "trim_name": "New", "powertrain": "BEV",
        }], catalog=ended, as_of="2026-09-30")

    historical = _seed_catalog(tmp_path / "other", trims=[], retail_status="HISTORICAL")
    with pytest.raises(RetailLineupBootstrapError, match="model reactivation"):
        plan_retail_lineup([{
            "model_id": MODEL_ID, "generation_id": GEN_ID,
            "trim_name": "New", "powertrain": "BEV",
        }], catalog=historical, as_of="2026-09-30")
