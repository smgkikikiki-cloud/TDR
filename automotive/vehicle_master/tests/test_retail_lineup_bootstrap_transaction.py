from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from vehreg.catalog import Catalog
from vehreg.current_retail import load_current_retail_index, replace_current_retail_set
from vehreg.retail_lifecycle_review import load_trim_lifecycle_decisions
from vehreg.retail_lineup_bootstrap import RetailLineupBootstrapError, plan_retail_lineup
import vehreg.retail_lineup_bootstrap_transaction as transaction

YEAR = 2026
MODEL = "acme.echo"
GEN = f"{MODEL}.e1"
A = f"{GEN}.trim.a_bev"
B = f"{GEN}.trim.b_bev"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    _write(data / str(YEAR) / "models" / "acme.json", {
        "brand": {
            "id": "acme", "name_en": "Acme", "name_th": "",
            "brand_segment": "MASS", "brand_origin": "US", "aliases": [],
        },
        "models": [{
            "id": "echo", "name_en": "Echo", "name_th": "",
            "body_type": "SEDAN", "cab_type": "NOT_APPLICABLE",
            "registration_type": "RY1", "market_scope": "CORE", "aliases": [],
            "retail_status": "CURRENT", "retail_checked_at": "2026-09-30",
            "retail_source": "https://example.test/echo",
            "generations": [{
                "code": "E1", "segment": "C", "seats": 5,
                "launched": "2024-01-01", "ended": None,
                "variants": [{
                    "id": "bev", "name": "Echo BEV", "powertrain": "BEV",
                    "drivetrain": "FWD", "battery_kwh": 60.0, "price_thb": None,
                    "import_type": "CBU", "origin_country": "US", "aliases": [],
                }],
                "trims": [
                    {"id": "a_bev", "name": "A", "powertrain": "BEV", "seats": 5,
                     "aliases": [], "source_refs": {}},
                    {"id": "b_bev", "name": "B", "powertrain": "BEV", "seats": 5,
                     "aliases": [], "source_refs": {}},
                ],
            }],
        }],
    })
    replace_current_retail_set(
        data_dir=data, year=YEAR, model_id=MODEL, trim_ids=[A, B],
        reviewer="Owner", reviewed_at="2026-09-30", source_ref="", write=True)
    return data


def _plan(data: Path):
    return plan_retail_lineup(
        [
            {"model_id": MODEL, "generation_id": GEN, "canonical_trim_id": B,
             "trim_name": "B", "powertrain": "BEV"},
            {"model_id": MODEL, "generation_id": GEN,
             "trim_name": "D New", "powertrain": "BEV"},
        ],
        catalog=Catalog.load(data, YEAR),
        current_retail_index=load_current_retail_index(data_dir=data, year=YEAR),
        lifecycle_decisions=load_trim_lifecycle_decisions(data_dir=data, year=YEAR),
        as_of="2026-09-30", base_release_id="vehicle-test",
    )


def _files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }


def _fake_validation(plan, *, data_dir, **_kwargs):
    staged = Path(data_dir)
    current = load_current_retail_index(data_dir=staged, year=YEAR)
    expected = set(plan.models[0].target_current_trim_ids)
    assert set(current[MODEL]) == expected
    decisions = {row["trim_id"]: row for row in load_trim_lifecycle_decisions(
        data_dir=staged, year=YEAR)}
    assert decisions[A]["status"] == "HISTORICAL"
    return transaction.RetailLineupReleaseValidation(
        release_id="vehicle-test-release", source_hash="f" * 64,
        counts={"market_trims": 3}, trim_reconciliation_counts={"blockers": 0})


def test_success_validates_stage_then_promotes_whole_plan(tmp_path, monkeypatch):
    data = _seed(tmp_path)
    plan = _plan(data)
    new_id = next(item.canonical_trim_id for model in plan.models for item in model.items
                  if item.action.value == "CREATE")
    monkeypatch.setattr(transaction, "validate_retail_lineup_staged_release", _fake_validation)

    result = transaction.apply_retail_lineup_plan_atomically(
        plan, data_dir=data, actor="Owner",
        submitted_at="2026-09-30T12:00:00+07:00")

    assert result.release.release_id == "vehicle-test-release"
    assert result.changed_files
    assert new_id in Catalog.load(data, YEAR).trims
    assert set(load_current_retail_index(data_dir=data, year=YEAR)[MODEL]) == {B, new_id}
    decisions = {row["trim_id"]: row for row in load_trim_lifecycle_decisions(
        data_dir=data, year=YEAR)}
    assert decisions[A]["status"] == "HISTORICAL"


def test_release_validation_failure_promotes_nothing(tmp_path, monkeypatch):
    data = _seed(tmp_path)
    plan = _plan(data)
    before = _files(data)

    def fail_validation(*_args, **_kwargs):
        raise RetailLineupBootstrapError("synthetic release failure")

    monkeypatch.setattr(transaction, "validate_retail_lineup_staged_release", fail_validation)
    with pytest.raises(RetailLineupBootstrapError, match="synthetic release failure"):
        transaction.apply_retail_lineup_plan_atomically(
            plan, data_dir=data, actor="Owner",
            submitted_at="2026-09-30T12:00:00+07:00")

    assert _files(data) == before


def test_mid_promotion_failure_rolls_back_files_already_replaced(tmp_path, monkeypatch):
    data = _seed(tmp_path)
    plan = _plan(data)
    before = _files(data)
    monkeypatch.setattr(transaction, "validate_retail_lineup_staged_release", _fake_validation)

    real_replace = os.replace
    promotion_count = 0

    def flaky_replace(src, dst):
        nonlocal promotion_count
        src_path = Path(src)
        if src_path.name.endswith(".rlb-tmp"):
            promotion_count += 1
            if promotion_count == 2:
                raise OSError("synthetic disk failure")
        return real_replace(src, dst)

    monkeypatch.setattr(transaction.os, "replace", flaky_replace)
    with pytest.raises(RetailLineupBootstrapError, match="promotion failed"):
        transaction.apply_retail_lineup_plan_atomically(
            plan, data_dir=data, actor="Owner",
            submitted_at="2026-09-30T12:00:00+07:00")

    assert promotion_count >= 2
    assert _files(data) == before


def test_live_baseline_is_rechecked_after_staged_validation(tmp_path, monkeypatch):
    data = _seed(tmp_path)
    plan = _plan(data)
    new_id = next(item.canonical_trim_id for model in plan.models for item in model.items
                  if item.action.value == "CREATE")

    def validate_then_external_writer(plan, *, data_dir, **_kwargs):
        result = _fake_validation(plan, data_dir=data_dir)
        replace_current_retail_set(
            data_dir=data, year=YEAR, model_id=MODEL, trim_ids=[A],
            reviewer="Other owner", reviewed_at="2026-09-30", source_ref="", write=True)
        return result

    monkeypatch.setattr(
        transaction, "validate_retail_lineup_staged_release", validate_then_external_writer)
    with pytest.raises(RetailLineupBootstrapError, match="STALE_BASELINE_BEFORE_PROMOTION"):
        transaction.apply_retail_lineup_plan_atomically(
            plan, data_dir=data, actor="Owner",
            submitted_at="2026-09-30T12:00:00+07:00")

    assert set(load_current_retail_index(data_dir=data, year=YEAR)[MODEL]) == {A}
    assert new_id not in Catalog.load(data, YEAR).trims


def test_shared_sidecar_metadata_write_is_not_overwritten(tmp_path, monkeypatch):
    data = _seed(tmp_path)
    plan = _plan(data)
    new_id = next(item.canonical_trim_id for model in plan.models for item in model.items
                  if item.action.value == "CREATE")

    def validate_then_metadata_writer(plan, *, data_dir, **_kwargs):
        result = _fake_validation(plan, data_dir=data_dir)
        # Same membership means the semantic target-model baseline stays the
        # same, but current_retail.json bytes change. The file-level CAS must
        # still reject promotion so this concurrent audit metadata is not lost.
        replace_current_retail_set(
            data_dir=data, year=YEAR, model_id=MODEL, trim_ids=[A, B],
            reviewer="Other owner", reviewed_at="2026-09-30", source_ref="",
            notes="concurrent metadata", write=True)
        return result

    monkeypatch.setattr(
        transaction, "validate_retail_lineup_staged_release", validate_then_metadata_writer)
    with pytest.raises(RetailLineupBootstrapError, match="CONCURRENT_WRITE_BEFORE_PROMOTION"):
        transaction.apply_retail_lineup_plan_atomically(
            plan, data_dir=data, actor="Owner",
            submitted_at="2026-09-30T12:00:00+07:00")

    current_path = data / str(YEAR) / "market" / "trims" / "current_retail.json"
    payload = json.loads(current_path.read_text(encoding="utf-8"))
    row = next(row for row in payload["models"] if row["model_id"] == MODEL)
    assert row["notes"] == "concurrent metadata"
    assert set(row["trim_ids"]) == {A, B}
    assert new_id not in Catalog.load(data, YEAR).trims
