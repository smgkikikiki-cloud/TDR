"""HUMAN-set operational state for a canonical Model.

Separate axis from retail lifecycle: ``Model.retail_status`` says whether a
buyer can order the car today; this says whether the *price system* is
currently allowed to touch it. A model under active generation changeover,
a data-quality investigation, or any other reason staff wants automated
price writes paused, is flagged here -- registration/model-level analytics
are unaffected, only automated price mutation is gated.

Mirrors :mod:`vehreg.retail_lifecycle_review`: a sidecar workflow store, not
part of MarketTrim/Model identity, HUMAN-only, absence means NORMAL.
"""
from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
from typing import Any

from .catalog import Catalog, DATA_DIR, DEFAULT_YEAR


class ModelOperationalStateError(ValueError):
    pass


_ALLOWED_ACTIONS = {"under_maintenance", "normal"}
_STORED_ACTIONS = {"UNDER_MAINTENANCE"}


def model_state_path(data_dir: Path | str = DATA_DIR, year: int = DEFAULT_YEAR) -> Path:
    return Path(data_dir) / str(year) / "market" / "operational_state" / "model_state.json"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _validated_date(value: str, label: str) -> str:
    try:
        return date.fromisoformat(str(value or "")).isoformat()
    except ValueError as exc:
        raise ModelOperationalStateError(f"{label} must be YYYY-MM-DD") from exc


def _validated_reviewer(value: str) -> str:
    reviewer = str(value or "").strip()
    if not reviewer or reviewer.lower() in {"system", "agent", "agent-proposed"}:
        raise ModelOperationalStateError("model operational state requires explicit HUMAN reviewer")
    return reviewer


def validate_model_operational_state_decisions(payload: dict[str, Any], *,
                                               data_dir: Path | str = DATA_DIR,
                                               year: int = DEFAULT_YEAR) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("schema_version", 1) != 1:
        raise ModelOperationalStateError("model operational state schema_version must be 1")
    rows = payload.get("decisions")
    if not isinstance(rows, list):
        raise ModelOperationalStateError("model operational state decisions must be an array")
    catalog = Catalog.load(data_dir, year)
    seen: set[str] = set()
    checked: list[dict[str, Any]] = []
    allowed = {"model_id", "status", "reviewer", "reviewed_at", "source_ref", "notes"}
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ModelOperationalStateError(f"decision[{index}] must be an object")
        unknown = set(raw) - allowed
        if unknown:
            raise ModelOperationalStateError(f"decision[{index}] unknown fields: {sorted(unknown)}")
        model_id = str(raw.get("model_id") or "").strip()
        if model_id not in catalog.models:
            raise ModelOperationalStateError(f"decision[{index}] unknown model_id {model_id!r}")
        if model_id in seen:
            raise ModelOperationalStateError(f"duplicate model operational state decision for {model_id}")
        seen.add(model_id)
        status = str(raw.get("status") or "").strip().upper()
        if status not in _STORED_ACTIONS:
            raise ModelOperationalStateError(
                "stored model operational state status must be UNDER_MAINTENANCE")
        checked.append({
            "model_id": model_id,
            "status": status,
            "reviewer": _validated_reviewer(str(raw.get("reviewer") or "")),
            "reviewed_at": _validated_date(str(raw.get("reviewed_at") or ""), "reviewed_at"),
            "source_ref": str(raw.get("source_ref") or "").strip(),
            "notes": str(raw.get("notes") or "").strip(),
        })
    return sorted(checked, key=lambda row: row["model_id"])


def load_model_operational_states(*, data_dir: Path | str = DATA_DIR,
                                  year: int = DEFAULT_YEAR) -> list[dict[str, Any]]:
    path = model_state_path(data_dir, year)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelOperationalStateError(f"cannot read {path}: {exc}") from exc
    return validate_model_operational_state_decisions(payload, data_dir=data_dir, year=year)


def under_maintenance_model_ids(*, data_dir: Path | str = DATA_DIR,
                                year: int = DEFAULT_YEAR) -> frozenset[str]:
    """The fast-lookup set every price-touching caller actually wants."""
    return frozenset(
        row["model_id"] for row in load_model_operational_states(data_dir=data_dir, year=year)
    )


def upsert_model_operational_state(*, data_dir: Path | str = DATA_DIR,
                                   year: int = DEFAULT_YEAR,
                                   model_id: str,
                                   action: str,
                                   reviewer: str,
                                   reviewed_at: str,
                                   source_ref: str = "",
                                   notes: str = "",
                                   write: bool = False) -> dict[str, Any]:
    action = str(action or "").strip().lower()
    if action not in _ALLOWED_ACTIONS:
        raise ModelOperationalStateError(
            "model operational state action must be under_maintenance or normal")
    catalog = Catalog.load(data_dir, year)
    model_id = str(model_id or "").strip()
    if model_id not in catalog.models:
        raise ModelOperationalStateError(f"unknown Model {model_id!r}")
    reviewer = _validated_reviewer(reviewer)
    reviewed_at = _validated_date(reviewed_at, "reviewed_at")

    existing = load_model_operational_states(data_dir=data_dir, year=year)
    merged = [row for row in existing if row["model_id"] != model_id]
    if action == "under_maintenance":
        merged.append({
            "model_id": model_id,
            "status": "UNDER_MAINTENANCE",
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "source_ref": str(source_ref or "").strip(),
            "notes": str(notes or "").strip(),
        })
    candidate = {"schema_version": 1, "decisions": merged}
    checked = validate_model_operational_state_decisions(candidate, data_dir=data_dir, year=year)
    canonical = {"schema_version": 1, "decisions": checked}
    before = {"schema_version": 1, "decisions": existing}
    changed = canonical != before
    destination = model_state_path(data_dir, year)
    if write and changed:
        _atomic_json(destination, canonical)
    return {
        "written": bool(write and changed),
        "changed": changed,
        "path": str(destination),
        "decisions": len(checked),
        "model_id": model_id,
        "status": "UNDER_MAINTENANCE" if action == "under_maintenance" else "NORMAL",
    }


__all__ = [
    "ModelOperationalStateError", "load_model_operational_states", "model_state_path",
    "under_maintenance_model_ids", "upsert_model_operational_state",
    "validate_model_operational_state_decisions",
]
