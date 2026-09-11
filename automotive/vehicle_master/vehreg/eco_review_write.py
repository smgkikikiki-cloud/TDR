"""Merge HUMAN ECO review dispositions into the existing file-backed review store.

Review decisions are staging metadata, not serving vehicle facts. They therefore
travel through the canonical input batch/staging PR path but do not enter the
canonical vehicle release projection or registration database.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from .catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from .ecosticker_ingest import (
    ECOIngestError,
    load_normalized_snapshot,
    review_dir,
    validate_decisions,
)


_ALLOWED_ACTIONS = {"reject", "defer", "reopen"}


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def upsert_review_dispositions(*, data_dir: Path | str = DATA_DIR,
                               year: int = DEFAULT_YEAR,
                               snapshot_date: str,
                               source_ids: Iterable[str],
                               action: str,
                               reviewer: str,
                               reviewed_at: str,
                               notes: str = "",
                               write: bool = False) -> dict:
    """Replace, defer, reject or reopen selected source decisions."""
    action = str(action or "").strip().lower()
    if action not in _ALLOWED_ACTIONS:
        raise ECOIngestError(f"review disposition action must be reject/defer/reopen, got {action!r}")
    reviewer = str(reviewer or "").strip()
    if not reviewer:
        raise ECOIngestError("reviewer is required")
    source_ids = [str(value or "").strip().lower() for value in source_ids]
    if not source_ids or any(not value for value in source_ids):
        raise ECOIngestError("source_ids must be a non-empty list")
    if len(source_ids) != len(set(source_ids)):
        raise ECOIngestError("source_ids must be unique")

    records = load_normalized_snapshot(data_dir, year, snapshot_date=snapshot_date)
    known = {str(row["source_id"]).lower() for row in records}
    unknown = [source_id for source_id in source_ids if source_id not in known]
    if unknown:
        raise ECOIngestError(f"unknown ECO source IDs: {unknown[:5]}")

    destination = review_dir(data_dir, year) / f"{snapshot_date}.json"
    existing_payload = {
        "schema_version": 1,
        "snapshot_date": snapshot_date,
        "decisions": [],
    }
    if destination.is_file():
        existing_payload = json.loads(destination.read_text(encoding="utf-8"))

    # Validate the existing file before modifying it. A malformed review store
    # must fail closed instead of being silently replaced by the new decision.
    catalog = Catalog.load(data_dir, year)
    existing = validate_decisions(existing_payload, records, catalog)
    selected = set(source_ids)
    merged = [decision for decision in existing if decision["source_id"] not in selected]
    if action != "reopen":
        merged.extend({
            "source_id": source_id,
            "action": action,
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "notes": str(notes or "").strip(),
        } for source_id in source_ids)
    candidate = {
        "schema_version": 1,
        "snapshot_date": snapshot_date,
        "decisions": merged,
    }
    checked = validate_decisions(candidate, records, catalog)
    canonical = {
        "schema_version": 1,
        "snapshot_date": snapshot_date,
        "decisions": checked,
    }
    changed = canonical != {
        "schema_version": 1,
        "snapshot_date": snapshot_date,
        "decisions": existing,
    }
    if write and changed:
        _atomic_json(destination, canonical)
    return {
        "written": bool(write and changed),
        "changed": changed,
        "path": str(destination),
        "decisions": len(checked),
        "rejected": sum(row["action"] == "reject" for row in checked),
        "deferred": sum(row["action"] == "defer" for row in checked),
        "reopened": len(source_ids) if action == "reopen" else 0,
        "updated_source_ids": source_ids,
    }


__all__ = ["upsert_review_dispositions"]
