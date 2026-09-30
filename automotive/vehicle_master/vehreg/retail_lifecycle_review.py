"""HUMAN-reviewed retail lifecycle dispositions for MarketTrim identity.

Ordinary CURRENT/HISTORICAL reviews require http(s) evidence. Retail Lineup
Bootstrap is owner-authoritative and may intentionally store an empty
``source_ref`` through its dedicated helper; reviewer/date/notes and the
immutable bootstrap plan are the audit trail. Parent/approved-set safeguards
remain identical on both paths.
"""
from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
from typing import Any

from .catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from .current_retail import resolve_approved_current_trim_ids


class RetailLifecycleReviewError(ValueError):
    pass


_ALLOWED_ACTIONS = {"current", "historical", "reopen"}
_STORED_ACTIONS = {"CURRENT", "HISTORICAL"}


def review_path(data_dir: Path | str = DATA_DIR, year: int = DEFAULT_YEAR) -> Path:
    return Path(data_dir) / str(year) / "market" / "retail_lifecycle" / "trim_review.json"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _validated_date(value: str, label: str) -> str:
    try:
        return date.fromisoformat(str(value or "")).isoformat()
    except ValueError as exc:
        raise RetailLifecycleReviewError(f"{label} must be YYYY-MM-DD") from exc


def _validated_source_ref(value: str, *, required: bool = False) -> str:
    source_ref = str(value or "").strip()
    if not source_ref:
        if required:
            raise RetailLifecycleReviewError("source_ref must be an http(s) URL")
        return ""
    if not source_ref.startswith(("https://", "http://")):
        raise RetailLifecycleReviewError("source_ref must be an http(s) URL")
    return source_ref


def _validated_reviewer(value: str) -> str:
    reviewer = str(value or "").strip()
    if not reviewer or reviewer.lower() in {"system", "agent", "agent-proposed"}:
        raise RetailLifecycleReviewError("trim lifecycle review requires explicit HUMAN reviewer")
    return reviewer


def _parent_model(catalog: Catalog, trim_id: str) -> tuple[str, str]:
    trim = catalog.trims[trim_id]
    generation = catalog.generations.get(trim.generation_id)
    model_id = str(generation.model_id) if generation else ""
    model = catalog.models.get(model_id) if generation else None
    retail_status = getattr(model, "retail_status", None)
    status = str(getattr(retail_status, "value", retail_status or "UNVERIFIED")).strip().upper()
    return model_id, status


def _parent_model_status(catalog: Catalog, trim_id: str) -> str:
    return _parent_model(catalog, trim_id)[1]


def validate_trim_lifecycle_decisions(payload: dict[str, Any], *,
                                      data_dir: Path | str = DATA_DIR,
                                      year: int = DEFAULT_YEAR) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("schema_version", 1) != 1:
        raise RetailLifecycleReviewError("trim lifecycle review schema_version must be 1")
    rows = payload.get("decisions")
    if not isinstance(rows, list):
        raise RetailLifecycleReviewError("trim lifecycle decisions must be an array")
    catalog = Catalog.load(data_dir, year)
    seen, checked = set(), []
    allowed = {"trim_id", "status", "reviewer", "reviewed_at", "source_ref", "notes"}
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise RetailLifecycleReviewError(f"decision[{index}] must be an object")
        unknown = set(raw) - allowed
        if unknown:
            raise RetailLifecycleReviewError(f"decision[{index}] unknown fields: {sorted(unknown)}")
        trim_id = str(raw.get("trim_id") or "").strip()
        if trim_id not in catalog.trims:
            raise RetailLifecycleReviewError(f"decision[{index}] unknown trim_id {trim_id!r}")
        if trim_id in seen:
            raise RetailLifecycleReviewError(f"duplicate trim lifecycle decision for {trim_id}")
        seen.add(trim_id)
        status = str(raw.get("status") or "").strip().upper()
        if status not in _STORED_ACTIONS:
            raise RetailLifecycleReviewError("stored trim lifecycle status must be CURRENT or HISTORICAL")
        checked.append({
            "trim_id": trim_id,
            "status": status,
            "reviewer": _validated_reviewer(str(raw.get("reviewer") or "")),
            "reviewed_at": _validated_date(str(raw.get("reviewed_at") or ""), "reviewed_at"),
            "source_ref": _validated_source_ref(str(raw.get("source_ref") or "")),
            "notes": str(raw.get("notes") or "").strip(),
        })
    return sorted(checked, key=lambda row: row["trim_id"])


def load_trim_lifecycle_decisions(*, data_dir: Path | str = DATA_DIR,
                                  year: int = DEFAULT_YEAR) -> list[dict[str, Any]]:
    path = review_path(data_dir, year)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RetailLifecycleReviewError(f"cannot read {path}: {exc}") from exc
    return validate_trim_lifecycle_decisions(payload, data_dir=data_dir, year=year)


def _upsert(*, data_dir: Path | str, year: int, trim_id: str, action: str,
            reviewer: str, reviewed_at: str, source_ref: str, notes: str,
            write: bool, require_source_ref: bool) -> dict[str, Any]:
    action = str(action or "").strip().lower()
    if action not in _ALLOWED_ACTIONS:
        raise RetailLifecycleReviewError("trim lifecycle action must be current, historical or reopen")
    catalog = Catalog.load(data_dir, year)
    trim_id = str(trim_id or "").strip()
    if trim_id not in catalog.trims:
        raise RetailLifecycleReviewError(f"unknown MarketTrim {trim_id!r}")
    reviewer = _validated_reviewer(reviewer)
    reviewed_at = _validated_date(reviewed_at, "reviewed_at")
    source_ref = "" if action == "reopen" else _validated_source_ref(
        source_ref, required=require_source_ref)

    if action != "reopen":
        model_id, parent_status = _parent_model(catalog, trim_id)
        if parent_status != "CURRENT":
            approved = None if parent_status == "HISTORICAL" else resolve_approved_current_trim_ids(
                model_id, data_dir=data_dir, year=year)
            if approved is None or action != "historical":
                raise RetailLifecycleReviewError(
                    "parent model must be canonical CURRENT before trim lifecycle review")
            if trim_id in approved:
                raise RetailLifecycleReviewError(
                    "trim is a member of the approved current-retail set; "
                    "cannot record a contradictory historical disposition")

    existing = load_trim_lifecycle_decisions(data_dir=data_dir, year=year)
    merged = [row for row in existing if row["trim_id"] != trim_id]
    if action != "reopen":
        merged.append({
            "trim_id": trim_id, "status": action.upper(), "reviewer": reviewer,
            "reviewed_at": reviewed_at, "source_ref": source_ref,
            "notes": str(notes or "").strip(),
        })
    checked = validate_trim_lifecycle_decisions(
        {"schema_version": 1, "decisions": merged}, data_dir=data_dir, year=year)
    canonical, before = {"schema_version": 1, "decisions": checked}, {
        "schema_version": 1, "decisions": existing}
    changed = canonical != before
    destination = review_path(data_dir, year)
    if write and changed:
        _atomic_json(destination, canonical)
    return {
        "written": bool(write and changed), "changed": changed,
        "path": str(destination), "decisions": len(checked), "trim_id": trim_id,
        "status": action.upper() if action != "reopen" else "UNVERIFIED",
        "reopened": 1 if action == "reopen" and changed else 0,
    }


def upsert_trim_lifecycle_disposition(*, data_dir: Path | str = DATA_DIR,
                                      year: int = DEFAULT_YEAR, trim_id: str,
                                      action: str, reviewer: str, reviewed_at: str,
                                      source_ref: str = "", notes: str = "",
                                      write: bool = False) -> dict[str, Any]:
    """Ordinary evidence-backed path; CURRENT/HISTORICAL require a real URL."""
    return _upsert(
        data_dir=data_dir, year=year, trim_id=trim_id, action=action,
        reviewer=reviewer, reviewed_at=reviewed_at, source_ref=source_ref,
        notes=notes, write=write, require_source_ref=True)


def upsert_bootstrap_trim_lifecycle_disposition(*, data_dir: Path | str = DATA_DIR,
                                                year: int = DEFAULT_YEAR,
                                                trim_id: str, action: str,
                                                reviewer: str, reviewed_at: str,
                                                source_ref: str = "", notes: str = "",
                                                write: bool = False) -> dict[str, Any]:
    """Owner-authoritative bootstrap archive/reopen path; never creates CURRENT review."""
    action = str(action or "").strip().lower()
    if action not in {"historical", "reopen"}:
        raise RetailLifecycleReviewError(
            "bootstrap lifecycle action must be historical or reopen; CURRENT membership belongs to current_retail")
    return _upsert(
        data_dir=data_dir, year=year, trim_id=trim_id, action=action,
        reviewer=reviewer, reviewed_at=reviewed_at, source_ref=source_ref,
        notes=notes, write=write, require_source_ref=False)


__all__ = [
    "RetailLifecycleReviewError", "load_trim_lifecycle_decisions", "review_path",
    "upsert_bootstrap_trim_lifecycle_disposition",
    "upsert_trim_lifecycle_disposition", "validate_trim_lifecycle_decisions",
]
