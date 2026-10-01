"""Strict JSON round-trip for persisted Retail Lineup Bootstrap plans.

A durable preview must later execute the exact compiled plan that was reviewed.
This decoder rebuilds the frozen Chunk-1 dataclasses from Supabase JSON without
re-running workbook compilation or identity resolution, then independently
recomputes the immutable plan hash before returning it.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .retail_lineup_bootstrap import (
    LineupAction,
    LineupPlanItem,
    ModelLineupPlan,
    RetailLineupBootstrapError,
    RetailLineupPlan,
)

_PLAN_KEYS = {
    "schema_version", "as_of", "catalog_year", "base_release_id",
    "baseline_hash", "plan_hash", "counts", "models",
}
_MODEL_KEYS = {
    "model_id", "before_current_trim_ids", "target_current_trim_ids",
    "counts", "items",
}
_ITEM_KEYS = {
    "action", "model_id", "generation_id", "canonical_trim_id", "trim_name",
    "powertrain", "identity_resolution", "reopen_required",
}
_HEX = set("0123456789abcdef")


def _object(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RetailLineupBootstrapError(f"{label} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], *, label: str) -> None:
    held = set(value)
    if held != expected:
        missing, extra = sorted(expected - held), sorted(held - expected)
        raise RetailLineupBootstrapError(
            f"{label} schema mismatch; missing={missing}, extra={extra}")


def _text(value: Any, *, label: str, allow_blank: bool = False) -> str:
    if not isinstance(value, str):
        raise RetailLineupBootstrapError(f"{label} must be a string")
    out = value.strip()
    if not out and not allow_blank:
        raise RetailLineupBootstrapError(f"{label} must not be blank")
    return out


def _hex64(value: Any, *, label: str) -> str:
    out = _text(value, label=label)
    if len(out) != 64 or any(char not in _HEX for char in out):
        raise RetailLineupBootstrapError(f"{label} must be lowercase SHA-256 hex")
    return out


def _strings(value: Any, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise RetailLineupBootstrapError(f"{label} must be an array")
    out = tuple(_text(item, label=f"{label}[]") for item in value)
    if len(set(out)) != len(out):
        raise RetailLineupBootstrapError(f"{label} contains duplicates")
    return out


def _counts(value: Any, *, label: str) -> dict[str, int]:
    row = _object(value, label=label)
    expected = {action.value.lower() for action in LineupAction}
    if set(row) != expected:
        raise RetailLineupBootstrapError(f"{label} must contain exactly {sorted(expected)}")
    out: dict[str, int] = {}
    for key in sorted(expected):
        held = row[key]
        if isinstance(held, bool) or not isinstance(held, int) or held < 0:
            raise RetailLineupBootstrapError(f"{label}.{key} must be a non-negative integer")
        out[key] = held
    return out


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)


def _plan_hash(plan: RetailLineupPlan) -> str:
    payload = {
        "schema_version": plan.schema_version,
        "as_of": plan.as_of,
        "catalog_year": plan.catalog_year,
        "base_release_id": plan.base_release_id,
        "baseline_hash": plan.baseline_hash,
        "models": [model.as_dict() for model in plan.models],
    }
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def decode_retail_lineup_plan(
    payload: Mapping[str, Any], *,
    expected_plan_hash: str | None = None,
    expected_baseline_hash: str | None = None,
) -> RetailLineupPlan:
    raw = _object(payload, label="compiled_plan")
    _exact_keys(raw, _PLAN_KEYS, label="compiled_plan")

    schema_version = raw["schema_version"]
    if isinstance(schema_version, bool) or schema_version != 1:
        raise RetailLineupBootstrapError("compiled_plan.schema_version must be 1")
    catalog_year = raw["catalog_year"]
    if isinstance(catalog_year, bool) or not isinstance(catalog_year, int):
        raise RetailLineupBootstrapError("compiled_plan.catalog_year must be an integer")

    baseline_hash = _hex64(raw["baseline_hash"], label="compiled_plan.baseline_hash")
    plan_hash = _hex64(raw["plan_hash"], label="compiled_plan.plan_hash")
    if expected_plan_hash is not None and plan_hash != _hex64(
            expected_plan_hash, label="expected_plan_hash"):
        raise RetailLineupBootstrapError("stored plan_hash does not match durable row")
    if expected_baseline_hash is not None and baseline_hash != _hex64(
            expected_baseline_hash, label="expected_baseline_hash"):
        raise RetailLineupBootstrapError("stored baseline_hash does not match durable row")

    raw_models = raw["models"]
    if not isinstance(raw_models, list) or not raw_models:
        raise RetailLineupBootstrapError("compiled_plan.models must be a non-empty array")

    models: list[ModelLineupPlan] = []
    seen_models: set[str] = set()
    for model_index, model_value in enumerate(raw_models):
        model_raw = _object(model_value, label=f"compiled_plan.models[{model_index}]")
        _exact_keys(model_raw, _MODEL_KEYS, label=f"compiled_plan.models[{model_index}]")
        model_id = _text(model_raw["model_id"], label="model_id")
        if model_id in seen_models:
            raise RetailLineupBootstrapError(f"duplicate persisted model plan {model_id}")
        seen_models.add(model_id)

        raw_items = model_raw["items"]
        if not isinstance(raw_items, list) or not raw_items:
            raise RetailLineupBootstrapError(f"persisted model {model_id} has no plan items")
        items: list[LineupPlanItem] = []
        seen_items: set[tuple[str, str]] = set()
        for item_index, item_value in enumerate(raw_items):
            item_raw = _object(item_value, label=f"{model_id}.items[{item_index}]")
            _exact_keys(item_raw, _ITEM_KEYS, label=f"{model_id}.items[{item_index}]")
            try:
                action = LineupAction(_text(item_raw["action"], label="action"))
            except ValueError as exc:
                raise RetailLineupBootstrapError(
                    f"invalid persisted lineup action {item_raw.get('action')!r}") from exc
            reopen_required = item_raw["reopen_required"]
            if not isinstance(reopen_required, bool):
                raise RetailLineupBootstrapError("reopen_required must be boolean")
            item = LineupPlanItem(
                action=action,
                model_id=_text(item_raw["model_id"], label="item.model_id"),
                generation_id=_text(item_raw["generation_id"], label="item.generation_id"),
                canonical_trim_id=_text(
                    item_raw["canonical_trim_id"], label="item.canonical_trim_id"),
                trim_name=_text(item_raw["trim_name"], label="item.trim_name"),
                powertrain=_text(item_raw["powertrain"], label="item.powertrain"),
                identity_resolution=_text(
                    item_raw["identity_resolution"], label="item.identity_resolution"),
                reopen_required=reopen_required,
            )
            if item.model_id != model_id:
                raise RetailLineupBootstrapError(
                    f"persisted item {item.canonical_trim_id} belongs to {item.model_id}, not {model_id}")
            key = (item.action.value, item.canonical_trim_id)
            if key in seen_items:
                raise RetailLineupBootstrapError(
                    f"duplicate persisted action {item.action.value} for {item.canonical_trim_id}")
            seen_items.add(key)
            items.append(item)

        model = ModelLineupPlan(
            model_id=model_id,
            before_current_trim_ids=_strings(
                model_raw["before_current_trim_ids"], label=f"{model_id}.before_current_trim_ids"),
            target_current_trim_ids=_strings(
                model_raw["target_current_trim_ids"], label=f"{model_id}.target_current_trim_ids"),
            items=tuple(items),
        )
        if _counts(model_raw["counts"], label=f"{model_id}.counts") != model.counts:
            raise RetailLineupBootstrapError(f"persisted counts mismatch for {model_id}")
        models.append(model)

    plan = RetailLineupPlan(
        schema_version=1,
        as_of=_text(raw["as_of"], label="compiled_plan.as_of"),
        catalog_year=catalog_year,
        base_release_id=_text(
            raw["base_release_id"], label="compiled_plan.base_release_id", allow_blank=True),
        baseline_hash=baseline_hash,
        plan_hash=plan_hash,
        models=tuple(models),
    )
    if _counts(raw["counts"], label="compiled_plan.counts") != plan.counts:
        raise RetailLineupBootstrapError("persisted top-level counts do not match plan items")
    actual_hash = _plan_hash(plan)
    if actual_hash != plan.plan_hash:
        raise RetailLineupBootstrapError(
            f"PLAN_HASH_MISMATCH: persisted plan content hashes to {actual_hash}, not {plan.plan_hash}")
    return plan


__all__ = ["decode_retail_lineup_plan"]
