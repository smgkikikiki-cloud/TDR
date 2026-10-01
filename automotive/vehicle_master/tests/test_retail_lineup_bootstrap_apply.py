from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from vehreg.catalog import Catalog
from vehreg.current_retail import load_current_retail_index, replace_current_retail_set
from vehreg.retail_lifecycle_review import (
    RetailLifecycleReviewError,
    load_trim_lifecycle_decisions,
    upsert_trim_lifecycle_disposition,
)
from vehreg.retail_lineup_bootstrap import RetailLineupBootstrapError, plan_retail_lineup
from vehreg.retail_lineup_bootstrap_apply import apply_retail_lineup_plan_to_staged_tree

YEAR = 2026
MODEL = "acme.echo"
GEN = f"{MODEL}.e1"
A = f"{GEN}.trim.a_bev"
B = f"{GEN}.trim.b_bev"
C = f"{GEN}.trim.c_bev"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _trim(local_id: str, name: str) -> dict:
    return {"id": local_id, "name": name, "powertrain": "BEV", "seats": 5,
            "aliases": [], "source_refs": {}}


def _seed(tmp_path: Path, *, status: str = "CURRENT", trims: list[dict] | None = None) -> Path:
    data = tmp_path / "data"
    model = {
        "id": "echo", "name_en": "Echo", "name_th": "",
        "body_type": "SEDAN", "cab_type": "NOT_APPLICABLE",
        "registration_type": "RY1", "market_scope": "CORE", "aliases": [],
        "retail_status": status,
        "generations": [{
            "code": "E1", "segment": "C", "seats": 5,
            "launched": "2024-01-01", "ended": None,
            "variants": [{
                "id": "bev", "name": "Echo BEV", "powertrain": "BEV",
                "drivetrain": "FWD", "battery_kwh": 60.0, "price_thb": None,
                "import_type": "CBU", "origin_country": "US", "aliases": [],
            }],
            "trims": trims or [_trim("a_bev", "A"), _trim("b_bev", "B"), _trim("c_bev", "C")],
        }],
    }
    if status == "CURRENT":
        model["retail_checked_at"] = "2026-09-30"
        model["retail_source"] = "https://example.test/echo"
    _write(data / str(YEAR) / "models" / "acme.json", {
        "brand": {"id": "acme", "name_en": "Acme", "name_th": "",
                  "brand_segment": "MASS", "brand_origin": "US", "aliases": []},
        "models": [model],
    })
    return data


def _current(data: Path, trim_ids: list[str]) -> None:
    replace_current_retail_set(
        data_dir=data, year=YEAR, model_id=MODEL, trim_ids=trim_ids,
        reviewer="Owner", reviewed_at="2026-09-30", source_ref="", write=True)


def _historical(data: Path, trim_id: str) -> None:
    upsert_trim_lifecycle_disposition(
        data_dir=data, year=YEAR, trim_id=trim_id, action="historical",
        reviewer="Owner", reviewed_at="2026-09-30",
        source_ref="https://example.test/history", write=True)


def _plan(data: Path, rows: list[dict]):
    return plan_retail_lineup(
        rows, catalog=Catalog.load(data, YEAR),
        current_retail_index=load_current_retail_index(data_dir=data, year=YEAR),
        lifecycle_decisions=load_trim_lifecycle_decisions(data_dir=data, year=YEAR),
        as_of="2026-09-30", base_release_id="vehicle-test")


def test_apply_keep_create_reactivate_archive_and_preserve_old_identity(tmp_path):
    data = _seed(tmp_path)
    _current(data, [A, B])
    _historical(data, C)
    price_path = data / str(YEAR) / "market" / "prices" / "legacy_a.json"
    original_price = {"prices": [{"trim_id": A, "amount_thb": 999000,
                                   "price_type": "LIST_PRICE", "observed_at": "2025-01-01"}]}
    _write(price_path, original_price)

    plan = _plan(data, [
        {"model_id": MODEL, "generation_id": GEN, "canonical_trim_id": B,
         "trim_name": "B", "powertrain": "BEV"},
        {"model_id": MODEL, "generation_id": GEN, "canonical_trim_id": C,
         "trim_name": "C", "powertrain": "BEV"},
        {"model_id": MODEL, "generation_id": GEN, "trim_name": "D New", "powertrain": "BEV"},
    ])
    assert plan.counts == {"keep": 1, "create": 1, "reactivate": 1, "archive": 1}
    new_id = next(item.canonical_trim_id for m in plan.models for item in m.items
                  if item.action.value == "CREATE")

    result = apply_retail_lineup_plan_to_staged_tree(
        plan, data_dir=data, actor="Owner", submitted_at="2026-09-30T12:00:00+07:00")
    assert result.idempotent_replay is False

    catalog = Catalog.load(data, YEAR)
    assert set(load_current_retail_index(data_dir=data, year=YEAR)[MODEL]) == {B, C, new_id}
    assert A in catalog.trims
    assert new_id in catalog.trims
    assert catalog.trims[new_id].name == "D New"
    assert catalog.trims[new_id].powertrain.value == "BEV"
    assert catalog.trims[new_id].battery_kwh is None
    decisions = {row["trim_id"]: row for row in load_trim_lifecycle_decisions(
        data_dir=data, year=YEAR)}
    assert decisions[A]["status"] == "HISTORICAL"
    assert decisions[A]["source_ref"] == ""
    assert C not in decisions
    assert json.loads(price_path.read_text(encoding="utf-8")) == original_price

    replay = apply_retail_lineup_plan_to_staged_tree(
        plan, data_dir=data, actor="Owner", submitted_at="2026-09-30T12:00:00+07:00")
    assert replay.idempotent_replay is True
    assert replay.changed_files == ()


def test_unverified_parent_without_prior_set_archives_after_set_replace(tmp_path):
    data = _seed(tmp_path, status="UNVERIFIED", trims=[_trim("a_bev", "A"), _trim("b_bev", "B")])
    plan = _plan(data, [{"model_id": MODEL, "generation_id": GEN,
                         "canonical_trim_id": B, "trim_name": "B", "powertrain": "BEV"}])
    assert plan.counts["archive"] == 1
    apply_retail_lineup_plan_to_staged_tree(
        plan, data_dir=data, actor="Owner", submitted_at="2026-09-30T12:00:00+07:00")
    assert set(load_current_retail_index(data_dir=data, year=YEAR)[MODEL]) == {B}
    decisions = {row["trim_id"]: row for row in load_trim_lifecycle_decisions(
        data_dir=data, year=YEAR)}
    assert decisions[A]["status"] == "HISTORICAL"
    assert decisions[A]["source_ref"] == ""


def test_ordinary_lifecycle_review_still_requires_real_url(tmp_path):
    data = _seed(tmp_path)
    with pytest.raises(RetailLifecycleReviewError, match="source_ref"):
        upsert_trim_lifecycle_disposition(
            data_dir=data, year=YEAR, trim_id=A, action="historical",
            reviewer="Owner", reviewed_at="2026-09-30", source_ref="", write=True)


def test_plan_hash_tampering_fails_before_create(tmp_path):
    data = _seed(tmp_path, trims=[_trim("a_bev", "A")])
    plan = _plan(data, [{"model_id": MODEL, "generation_id": GEN,
                         "trim_name": "Brand New", "powertrain": "BEV"}])
    new_id = next(item.canonical_trim_id for m in plan.models for item in m.items
                  if item.action.value == "CREATE")
    with pytest.raises(RetailLineupBootstrapError, match="PLAN_HASH_MISMATCH"):
        apply_retail_lineup_plan_to_staged_tree(
            replace(plan, plan_hash="0" * 64), data_dir=data, actor="Owner",
            submitted_at="2026-09-30T12:00:00+07:00")
    assert new_id not in Catalog.load(data, YEAR).trims


def test_baseline_drift_fails_closed_before_create(tmp_path):
    data = _seed(tmp_path, trims=[_trim("a_bev", "A"), _trim("b_bev", "B")])
    _current(data, [A, B])
    plan = _plan(data, [
        {"model_id": MODEL, "generation_id": GEN, "canonical_trim_id": B,
         "trim_name": "B", "powertrain": "BEV"},
        {"model_id": MODEL, "generation_id": GEN, "trim_name": "Brand New", "powertrain": "BEV"},
    ])
    new_id = next(item.canonical_trim_id for m in plan.models for item in m.items
                  if item.action.value == "CREATE")
    _current(data, [A])
    with pytest.raises(RetailLineupBootstrapError, match="STALE_BASELINE"):
        apply_retail_lineup_plan_to_staged_tree(
            plan, data_dir=data, actor="Owner", submitted_at="2026-09-30T12:00:00+07:00")
    assert new_id not in Catalog.load(data, YEAR).trims


def test_bootstrap_rejects_fake_source_ref(tmp_path):
    data = _seed(tmp_path, trims=[_trim("a_bev", "A"), _trim("b_bev", "B")])
    plan = _plan(data, [{"model_id": MODEL, "generation_id": GEN,
                         "canonical_trim_id": B, "trim_name": "B", "powertrain": "BEV"}])
    with pytest.raises(RetailLineupBootstrapError, match="http"):
        apply_retail_lineup_plan_to_staged_tree(
            plan, data_dir=data, actor="Owner", submitted_at="2026-09-30T12:00:00+07:00",
            source_ref="owner approved")
