"""HUMAN dispositions for missing LIST_PRICE work items.

A coverage disposition is workflow metadata, not a price fact. It records that a
reviewer inspected a specific MarketTrim and intentionally deferred LIST_PRICE
work because the market evidence is not yet publishable. The trim remains
price-unready until a real canonical LIST_PRICE exists.

These decisions travel through the canonical input staging/PR path, but never
enter serving vehicle projections or the PriceLedger.
"""
from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
from typing import Any

from .catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from .pricing import PriceLedger, PricingError


class PriceCoverageReviewError(ValueError):
    pass


_ALLOWED_ACTIONS = {"defer", "reopen"}
_ALLOWED_REASONS = {
    "AWAITING_FINAL_LIST_PRICE",
    "OFFICIAL_EVIDENCE_CONFLICT",
    "NO_RELIABLE_EVIDENCE",
}


def review_path(data_dir: Path | str = DATA_DIR, year: int = DEFAULT_YEAR) -> Path:
    return Path(data_dir) / str(year) / "market" / "pricefeed" / "review" / "coverage.json"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _validate_date(value: str, label: str) -> str:
    try:
        return date.fromisoformat(str(value or "")) .isoformat()
    except ValueError as exc:
        raise PriceCoverageReviewError(f"{label} must be YYYY-MM-DD") from exc


def _validate_source_ref(value: str) -> str:
    source_ref = str(value or "").strip()
    if not source_ref:
        raise PriceCoverageReviewError("source_ref is required for a defer decision")
    if not (source_ref.startswith("https://") or source_ref.startswith("http://")):
        raise PriceCoverageReviewError("source_ref must be an http(s) URL")
    return source_ref


def validate_coverage_decisions(payload: dict[str, Any], *,
                                data_dir: Path | str = DATA_DIR,
                                year: int = DEFAULT_YEAR) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("schema_version", 1) != 1:
        raise PriceCoverageReviewError("coverage review schema_version must be 1")
    rows = payload.get("decisions")
    if not isinstance(rows, list):
        raise PriceCoverageReviewError("coverage review decisions must be an array")

    catalog = Catalog.load(data_dir, year)
    seen: set[str] = set()
    checked: list[dict[str, Any]] = []
    allowed = {
        "trim_id", "action", "reason_code", "reviewer", "reviewed_at",
        "source_ref", "notes",
    }
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise PriceCoverageReviewError(f"decision[{index}] must be an object")
        unknown = set(raw) - allowed
        if unknown:
            raise PriceCoverageReviewError(
                f"decision[{index}] unknown fields: {sorted(unknown)}")
        trim_id = str(raw.get("trim_id") or "").strip()
        if trim_id not in catalog.trims:
            raise PriceCoverageReviewError(f"decision[{index}] unknown trim_id {trim_id!r}")
        if trim_id in seen:
            raise PriceCoverageReviewError(f"duplicate coverage decision for {trim_id}")
        seen.add(trim_id)
        action = str(raw.get("action") or "").strip().lower()
        if action != "defer":
            raise PriceCoverageReviewError("stored coverage decisions must use action defer")
        reason_code = str(raw.get("reason_code") or "").strip().upper()
        if reason_code not in _ALLOWED_REASONS:
            raise PriceCoverageReviewError(
                f"decision[{index}] invalid reason_code {reason_code!r}")
        reviewer = str(raw.get("reviewer") or "").strip()
        if not reviewer or reviewer.lower() in {"system", "agent", "agent-proposed"}:
            raise PriceCoverageReviewError("coverage defer requires explicit HUMAN reviewer")
        reviewed_at = _validate_date(str(raw.get("reviewed_at") or ""), "reviewed_at")
        source_ref = _validate_source_ref(str(raw.get("source_ref") or ""))
        checked.append({
            "trim_id": trim_id,
            "action": "defer",
            "reason_code": reason_code,
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "source_ref": source_ref,
            "notes": str(raw.get("notes") or "").strip(),
        })
    return sorted(checked, key=lambda row: row["trim_id"])


def load_coverage_decisions(*, data_dir: Path | str = DATA_DIR,
                            year: int = DEFAULT_YEAR) -> list[dict[str, Any]]:
    path = review_path(data_dir, year)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PriceCoverageReviewError(f"cannot read {path}: {exc}") from exc
    return validate_coverage_decisions(payload, data_dir=data_dir, year=year)


def upsert_coverage_disposition(*, data_dir: Path | str = DATA_DIR,
                                year: int = DEFAULT_YEAR,
                                trim_id: str,
                                action: str,
                                reason_code: str,
                                reviewer: str,
                                reviewed_at: str,
                                source_ref: str = "",
                                notes: str = "",
                                write: bool = False) -> dict[str, Any]:
    action = str(action or "").strip().lower()
    if action not in _ALLOWED_ACTIONS:
        raise PriceCoverageReviewError("coverage action must be defer or reopen")
    trim_id = str(trim_id or "").strip()
    catalog = Catalog.load(data_dir, year)
    if trim_id not in catalog.trims:
        raise PriceCoverageReviewError(f"unknown MarketTrim {trim_id!r}")
    reviewer = str(reviewer or "").strip()
    if not reviewer or reviewer.lower() in {"system", "agent", "agent-proposed"}:
        raise PriceCoverageReviewError("coverage review requires explicit HUMAN reviewer")
    reviewed_at = _validate_date(reviewed_at, "reviewed_at")

    existing = load_coverage_decisions(data_dir=data_dir, year=year)
    merged = [row for row in existing if row["trim_id"] != trim_id]

    if action == "defer":
        reason_code = str(reason_code or "").strip().upper()
        if reason_code not in _ALLOWED_REASONS:
            raise PriceCoverageReviewError(
                f"reason_code must be one of {sorted(_ALLOWED_REASONS)}")
        source_ref = _validate_source_ref(source_ref)
        try:
            ledger = PriceLedger.load(data_dir, year=year, catalog=catalog)
            current = ledger.current_list_price(trim_id, as_of=date.fromisoformat(reviewed_at))
        except (PricingError, ValueError) as exc:
            raise PriceCoverageReviewError(f"cannot resolve current LIST_PRICE: {exc}") from exc
        if current is not None:
            raise PriceCoverageReviewError(
                f"{trim_id} already has current LIST_PRICE {current.amount_thb}; cannot defer coverage work")
        merged.append({
            "trim_id": trim_id,
            "action": "defer",
            "reason_code": reason_code,
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "source_ref": source_ref,
            "notes": str(notes or "").strip(),
        })

    candidate = {"schema_version": 1, "decisions": merged}
    checked = validate_coverage_decisions(candidate, data_dir=data_dir, year=year)
    canonical = {"schema_version": 1, "decisions": checked}
    before = {"schema_version": 1, "decisions": existing}
    changed = canonical != before
    destination = review_path(data_dir, year)
    if write and changed:
        _atomic_json(destination, canonical)
    return {
        "written": bool(write and changed),
        "changed": changed,
        "path": str(destination),
        "decisions": len(checked),
        "deferred": len(checked),
        "reopened": 1 if action == "reopen" and changed else 0,
        "trim_id": trim_id,
    }


__all__ = [
    "PriceCoverageReviewError", "load_coverage_decisions", "review_path",
    "upsert_coverage_disposition", "validate_coverage_decisions",
]
