"""Pure planner for owner-authoritative retail-lineup bootstrap/reset.

Chunk 1 has no write path. It deterministically turns a complete target lineup
into KEEP / CREATE / REACTIVATE / ARCHIVE operations against a Catalog snapshot.
Later chunks must consume this plan instead of re-implementing identity rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence

from .catalog import Catalog
from .normalize import trim_identity
from .taxonomy import Powertrain


class RetailLineupBootstrapError(ValueError):
    pass


class LineupAction(str, Enum):
    KEEP = "KEEP"
    CREATE = "CREATE"
    REACTIVATE = "REACTIVATE"
    ARCHIVE = "ARCHIVE"


_ACTION_ORDER = {action: index for index, action in enumerate(LineupAction)}


@dataclass(frozen=True, slots=True)
class TargetTrimRow:
    model_id: str
    generation_id: str
    trim_name: str
    powertrain: str
    canonical_trim_id: str = ""
    notes: str = ""


@dataclass(frozen=True, slots=True)
class LineupPlanItem:
    action: LineupAction
    model_id: str
    generation_id: str
    canonical_trim_id: str
    trim_name: str
    powertrain: str
    identity_resolution: str
    reopen_required: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "model_id": self.model_id,
            "generation_id": self.generation_id,
            "canonical_trim_id": self.canonical_trim_id,
            "trim_name": self.trim_name,
            "powertrain": self.powertrain,
            "identity_resolution": self.identity_resolution,
            "reopen_required": self.reopen_required,
        }


@dataclass(frozen=True, slots=True)
class ModelLineupPlan:
    model_id: str
    before_current_trim_ids: tuple[str, ...]
    target_current_trim_ids: tuple[str, ...]
    items: tuple[LineupPlanItem, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {a.value.lower(): sum(i.action is a for i in self.items) for a in LineupAction}

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "before_current_trim_ids": list(self.before_current_trim_ids),
            "target_current_trim_ids": list(self.target_current_trim_ids),
            "counts": self.counts,
            "items": [item.as_dict() for item in self.items],
        }


@dataclass(frozen=True, slots=True)
class RetailLineupPlan:
    schema_version: int
    as_of: str
    catalog_year: int | None
    base_release_id: str
    baseline_hash: str
    plan_hash: str
    models: tuple[ModelLineupPlan, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {
            a.value.lower(): sum(i.action is a for m in self.models for i in m.items)
            for a in LineupAction
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "as_of": self.as_of,
            "catalog_year": self.catalog_year,
            "base_release_id": self.base_release_id,
            "baseline_hash": self.baseline_hash,
            "plan_hash": self.plan_hash,
            "counts": self.counts,
            "models": [model.as_dict() for model in self.models],
        }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _day(raw: date | str) -> date:
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw or ""))
    except ValueError as exc:
        raise RetailLineupBootstrapError("as_of must be YYYY-MM-DD") from exc


def _value(value: Any) -> str:
    return str(getattr(value, "value", value or "")).strip()


def _status(value: Any, default: str = "UNVERIFIED") -> str:
    return (_value(value) or default).upper()


def _decision_index(rows: Iterable[Mapping[str, Any]] | Mapping[str, Any]) -> dict[str, str]:
    if isinstance(rows, Mapping):
        return {
            str(trim_id): _status(value.get("status") if isinstance(value, Mapping) else value, "")
            for trim_id, value in rows.items()
            if _status(value.get("status") if isinstance(value, Mapping) else value, "")
        }
    out: dict[str, str] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise RetailLineupBootstrapError("lifecycle decisions must be objects")
        trim_id = str(raw.get("trim_id") or "").strip()
        status = _status(raw.get("status"), "")
        if not trim_id or not status:
            raise RetailLineupBootstrapError("lifecycle decision requires trim_id and status")
        if trim_id in out:
            raise RetailLineupBootstrapError(f"duplicate lifecycle decision for {trim_id}")
        out[trim_id] = status
    return out


def _model_for_generation(catalog: Catalog, generation_id: str) -> str:
    generation = catalog.generations.get(generation_id)
    return str(getattr(generation, "model_id", "") or "") if generation else ""


def _model_for_trim(catalog: Catalog, trim_id: str) -> str:
    trim = catalog.trims.get(trim_id)
    return _model_for_generation(catalog, str(getattr(trim, "generation_id", "") or "")) if trim else ""


def _ended(catalog: Catalog, generation_id: str, as_of: date) -> bool:
    generation = catalog.generations.get(generation_id)
    raw = str(getattr(generation, "ended", "") or "").strip() if generation else ""
    if not raw:
        return False
    try:
        return date.fromisoformat(raw) <= as_of
    except ValueError as exc:
        raise RetailLineupBootstrapError(
            f"generation {generation_id} has invalid ended date {raw!r}"
        ) from exc


def _trim_ids(catalog: Catalog, model_id: str) -> tuple[str, ...]:
    return tuple(sorted(tid for tid in catalog.trims if _model_for_trim(catalog, tid) == model_id))


def _resolved_current(
    catalog: Catalog,
    model_id: str,
    current_index: Mapping[str, Iterable[str]],
    decisions: Mapping[str, str],
    as_of: date,
) -> tuple[str, ...]:
    model = catalog.models.get(model_id)
    if model is None:
        raise RetailLineupBootstrapError(f"unknown model_id {model_id!r}")
    if _status(getattr(model, "retail_status", None)) == "HISTORICAL":
        return ()
    known = set(_trim_ids(catalog, model_id))
    if model_id in current_index:
        approved = {str(value).strip() for value in current_index[model_id]}
        unknown = approved - known
        if unknown:
            raise RetailLineupBootstrapError(
                f"current-retail baseline for {model_id} contains unknown/non-base trims: {sorted(unknown)}"
            )
        return tuple(sorted(
            tid for tid in approved
            if not _ended(catalog, str(catalog.trims[tid].generation_id), as_of)
        ))
    return tuple(
        tid for tid in sorted(known)
        if not _ended(catalog, str(catalog.trims[tid].generation_id), as_of)
        and decisions.get(tid) != "HISTORICAL"
    )


def baseline_hash_for_models(
    catalog: Catalog,
    model_ids: Iterable[str],
    *,
    current_retail_index: Mapping[str, Iterable[str]] | None = None,
    lifecycle_decisions: Iterable[Mapping[str, Any]] | Mapping[str, Any] = (),
    as_of: date | str,
) -> str:
    """Hash the identity/lifecycle state that an authoritative workbook replaces."""
    day = _day(as_of)
    current = current_retail_index or {}
    decisions = _decision_index(lifecycle_decisions)
    model_ids = sorted({str(mid).strip() for mid in model_ids if str(mid).strip()})
    if not model_ids:
        raise RetailLineupBootstrapError("baseline requires at least one model")
    payload_models = []
    for model_id in model_ids:
        model = catalog.models.get(model_id)
        if model is None:
            raise RetailLineupBootstrapError(f"unknown model_id {model_id!r}")
        generations = [
            {"generation_id": gid, "ended": str(getattr(gen, "ended", "") or "")}
            for gid, gen in sorted(catalog.generations.items())
            if str(getattr(gen, "model_id", "") or "") == model_id
        ]
        trims = []
        for tid in _trim_ids(catalog, model_id):
            trim = catalog.trims[tid]
            trims.append({
                "canonical_trim_id": tid,
                "generation_id": str(trim.generation_id),
                "trim_name": str(trim.name),
                "powertrain": _value(trim.powertrain),
                "lifecycle_decision": decisions.get(tid),
            })
        payload_models.append({
            "model_id": model_id,
            "model_retail_status": _status(getattr(model, "retail_status", None)),
            "approved_current_trim_ids": (
                sorted(str(v).strip() for v in current[model_id]) if model_id in current else None
            ),
            "resolved_current_trim_ids": list(_resolved_current(
                catalog, model_id, current, decisions, day
            )),
            "generations": generations,
            "trims": trims,
        })
    return _sha256({
        "schema_version": 1,
        "catalog_year": getattr(catalog, "year", None),
        "as_of": day.isoformat(),
        "models": payload_models,
    })


def _row(raw: TargetTrimRow | Mapping[str, Any]) -> TargetTrimRow:
    if isinstance(raw, TargetTrimRow):
        return raw
    if not isinstance(raw, Mapping):
        raise RetailLineupBootstrapError("target lineup rows must be objects")
    allowed = {"model_id", "generation_id", "trim_name", "powertrain",
               "canonical_trim_id", "notes"}
    unknown = set(raw) - allowed
    if unknown:
        raise RetailLineupBootstrapError(f"target row has unknown fields: {sorted(unknown)}")
    return TargetTrimRow(**{
        key: str(raw.get(key) or "").strip()
        for key in ("model_id", "generation_id", "trim_name", "powertrain",
                    "canonical_trim_id", "notes")
    })


def _powertrain(raw: str) -> Powertrain:
    try:
        parsed = Powertrain.parse(raw)
    except ValueError as exc:
        raise RetailLineupBootstrapError(f"invalid powertrain {raw!r}") from exc
    if parsed is Powertrain.UNKNOWN:
        raise RetailLineupBootstrapError("powertrain must be exact; UNKNOWN is not valid")
    return parsed


def _validate_parent(catalog: Catalog, row: TargetTrimRow, as_of: date) -> None:
    if not row.model_id or not row.generation_id or not row.trim_name:
        raise RetailLineupBootstrapError("target row requires model_id, generation_id and trim_name")
    model = catalog.models.get(row.model_id)
    if model is None:
        raise RetailLineupBootstrapError(f"unknown model_id {row.model_id!r}")
    if _status(getattr(model, "retail_status", None)) == "HISTORICAL":
        raise RetailLineupBootstrapError(
            f"model {row.model_id} is canonical HISTORICAL; model reactivation is outside bootstrap MVP"
        )
    generation = catalog.generations.get(row.generation_id)
    if generation is None:
        raise RetailLineupBootstrapError(f"unknown generation_id {row.generation_id!r}")
    if str(getattr(generation, "model_id", "") or "") != row.model_id:
        raise RetailLineupBootstrapError(
            f"generation {row.generation_id!r} does not belong to model {row.model_id!r}"
        )
    if _ended(catalog, row.generation_id, as_of):
        raise RetailLineupBootstrapError(
            f"generation {row.generation_id!r} has already ended; generation reactivation is outside bootstrap MVP"
        )


def _existing_item(
    catalog: Catalog,
    row: TargetTrimRow,
    trim_id: str,
    powertrain: Powertrain,
    before: set[str],
    decisions: Mapping[str, str],
    resolution: str,
) -> LineupPlanItem:
    trim = catalog.trims.get(trim_id)
    if trim is None:
        raise RetailLineupBootstrapError(f"unknown canonical_trim_id {trim_id!r}")
    if str(trim.generation_id) != row.generation_id:
        raise RetailLineupBootstrapError(
            f"MarketTrim {trim_id!r} does not belong to generation {row.generation_id!r}"
        )
    if _value(trim.powertrain) != powertrain.value:
        raise RetailLineupBootstrapError(
            f"MarketTrim {trim_id!r} powertrain is {_value(trim.powertrain)}, not {powertrain.value}"
        )
    if str(trim.name).strip() != row.trim_name:
        raise RetailLineupBootstrapError(
            f"MarketTrim {trim_id!r} is named {str(trim.name)!r}, not {row.trim_name!r}; "
            "bootstrap does not rename an existing identity"
        )
    action = LineupAction.KEEP if trim_id in before else LineupAction.REACTIVATE
    return LineupPlanItem(
        action, row.model_id, row.generation_id, trim_id, row.trim_name,
        powertrain.value, resolution,
        action is LineupAction.REACTIVATE and decisions.get(trim_id) == "HISTORICAL",
    )


def _plan_model(
    catalog: Catalog,
    model_id: str,
    rows: Sequence[TargetTrimRow],
    current: Mapping[str, Iterable[str]],
    decisions: Mapping[str, str],
    as_of: date,
) -> ModelLineupPlan:
    before = set(_resolved_current(catalog, model_id, current, decisions, as_of))
    target: set[str] = set()
    items: list[LineupPlanItem] = []
    for row in rows:
        _validate_parent(catalog, row, as_of)
        powertrain = _powertrain(row.powertrain)
        if row.canonical_trim_id:
            item = _existing_item(
                catalog, row, row.canonical_trim_id, powertrain, before, decisions,
                "EXPLICIT_CANONICAL_ID",
            )
        else:
            candidate = trim_identity(row.generation_id, None, row.trim_name, powertrain.value)
            if candidate in catalog.trims:
                item = _existing_item(
                    catalog, row, candidate, powertrain, before, decisions,
                    "DETERMINISTIC_EXISTING_ID",
                )
            else:
                item = LineupPlanItem(
                    LineupAction.CREATE, row.model_id, row.generation_id, candidate,
                    row.trim_name, powertrain.value, "DETERMINISTIC_NEW_ID", False,
                )
        if item.canonical_trim_id in target:
            raise RetailLineupBootstrapError(
                f"duplicate target MarketTrim identity {item.canonical_trim_id!r} for {model_id}"
            )
        target.add(item.canonical_trim_id)
        items.append(item)

    for trim_id in sorted(before - target):
        trim = catalog.trims[trim_id]
        items.append(LineupPlanItem(
            LineupAction.ARCHIVE, model_id, str(trim.generation_id), trim_id,
            str(trim.name), _value(trim.powertrain), "OMITTED_FROM_TARGET", False,
        ))
    items.sort(key=lambda item: (_ACTION_ORDER[item.action], item.canonical_trim_id))
    return ModelLineupPlan(
        model_id, tuple(sorted(before)), tuple(sorted(target)), tuple(items)
    )


def plan_retail_lineup(
    target_rows: Sequence[TargetTrimRow | Mapping[str, Any]],
    *,
    catalog: Catalog,
    current_retail_index: Mapping[str, Iterable[str]] | None = None,
    lifecycle_decisions: Iterable[Mapping[str, Any]] | Mapping[str, Any] = (),
    as_of: date | str,
    expected_baseline_hash: str = "",
    base_release_id: str = "",
) -> RetailLineupPlan:
    """Compile target state into an immutable plan; perform no writes or fuzzy matching."""
    if not target_rows:
        raise RetailLineupBootstrapError("target lineup contains no rows")
    rows = [_row(raw) for raw in target_rows]
    grouped: dict[str, list[TargetTrimRow]] = {}
    for row in rows:
        grouped.setdefault(row.model_id, []).append(row)
    if "" in grouped:
        raise RetailLineupBootstrapError("target row requires model_id")

    day = _day(as_of)
    current = current_retail_index or {}
    decisions = _decision_index(lifecycle_decisions)
    model_ids = sorted(grouped)
    baseline = baseline_hash_for_models(
        catalog, model_ids, current_retail_index=current,
        lifecycle_decisions=decisions, as_of=day,
    )
    expected = str(expected_baseline_hash or "").strip().lower()
    if expected and expected != baseline:
        raise RetailLineupBootstrapError(
            f"STALE_BASELINE: workbook {expected} != current {baseline}"
        )

    models = tuple(
        _plan_model(catalog, model_id, grouped[model_id], current, decisions, day)
        for model_id in model_ids
    )
    body = {
        "schema_version": 1,
        "as_of": day.isoformat(),
        "catalog_year": getattr(catalog, "year", None),
        "base_release_id": str(base_release_id or ""),
        "baseline_hash": baseline,
        "models": [model.as_dict() for model in models],
    }
    return RetailLineupPlan(
        1, day.isoformat(), getattr(catalog, "year", None), str(base_release_id or ""),
        baseline, _sha256(body), models,
    )


__all__ = [
    "LineupAction", "LineupPlanItem", "ModelLineupPlan",
    "RetailLineupBootstrapError", "RetailLineupPlan", "TargetTrimRow",
    "baseline_hash_for_models", "plan_retail_lineup",
]
