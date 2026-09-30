"""Compile uploaded Retail Lineup Bootstrap workbooks into durable previews.

This is deliberately a compile-only source-import worker. It never calls the
canonical writer. An uploaded workbook is claimed from ``import_runs``, compiled
against the checked-out canonical tree, persisted once as an immutable
``PREVIEW_READY`` plan linked to that import run, and then the import run is
marked COMPLETED. Invalid or stale workbooks fail closed.

The worker also recovers a PROCESSING run after a process crash. If the preview
was already persisted before the crash, the unique import_run_id link is the
idempotency key and the run is simply completed from that durable preview.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import quote

from tools.import_worker import _download, _patch, _rest
from tools.retail_lineup_plan_store import persist_preview
from vehreg.retail_lineup_workbook import compile_retail_lineup_workbook

SOURCE_KIND = "RETAIL_LINEUP_BOOTSTRAP"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pending(limit: int) -> list[dict[str, Any]]:
    rows = _rest(
        "GET",
        "import_runs?select=id,storage_path,original_name,source_kind,status,actor,created_at"
        f"&source_kind=eq.{SOURCE_KIND}&status=in.(UPLOADED,PROCESSING)"
        f"&order=created_at.asc&limit={max(1, int(limit))}",
    ) or []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _existing_preview(run_id: str) -> dict[str, Any] | None:
    rows = _rest(
        "GET",
        "retail_lineup_plans?select=id,status,source_sha256,baseline_hash,plan_hash,summary"
        f"&import_run_id=eq.{quote(run_id)}&limit=2",
    ) or []
    if not rows:
        return None
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise RuntimeError(f"import run {run_id} has more than one retail lineup preview")
    return dict(rows[0])


def _counts_from_summary(summary: Any) -> tuple[int, int]:
    row = summary if isinstance(summary, dict) else {}
    created = int(row.get("create") or 0)
    patched = int(row.get("reactivate") or 0) + int(row.get("archive") or 0)
    return patched, created


def _complete_from_preview(run_id: str, preview: dict[str, Any], *, rows_read: int | None = None) -> None:
    patched, created = _counts_from_summary(preview.get("summary"))
    payload: dict[str, Any] = {
        "status": "COMPLETED",
        "patched": patched,
        "created": created,
        "exceptions": 0,
        "error": None,
        "finished_at": _now(),
    }
    if rows_read is not None:
        payload["rows_read"] = int(rows_read)
    changed = _patch(run_id, payload, expected_status="PROCESSING")
    if len(changed) != 1:
        raise RuntimeError(f"import run {run_id} stopped being PROCESSING before completion")


def _fail(run_id: str, error: Exception) -> None:
    message = str(error)[:2000] or error.__class__.__name__
    _patch(run_id, {
        "status": "FAILED",
        "error": message,
        "finished_at": _now(),
    }, expected_status="PROCESSING")


def process_run(row: dict[str, Any]) -> dict[str, Any]:
    run_id = str(row.get("id") or "").strip()
    if not run_id:
        raise RuntimeError("retail lineup import row has no id")
    status = str(row.get("status") or "").upper()

    if status == "UPLOADED":
        claimed = _patch(run_id, {
            "status": "PROCESSING",
            "started_at": _now(),
            "error": None,
        }, expected_status="UPLOADED")
        if not claimed:
            return {"id": run_id, "status": "SKIPPED_ALREADY_CLAIMED"}
    elif status != "PROCESSING":
        return {"id": run_id, "status": f"SKIPPED_{status or 'UNKNOWN'}"}

    try:
        existing = _existing_preview(run_id)
        if existing is not None:
            _complete_from_preview(run_id, existing)
            return {"id": run_id, "status": "COMPLETED", "plan_id": existing.get("id"),
                    "recovered": True}

        actor = str(row.get("actor") or "tdr-admin").strip() or "tdr-admin"
        with tempfile.TemporaryDirectory(prefix="tdr-retail-lineup-compile-") as temp:
            source_file = _download(str(row.get("storage_path") or ""), Path(temp))
            compiled = compile_retail_lineup_workbook(source_file)
            preview = persist_preview(compiled, actor=actor, import_run_id=run_id)

        _complete_from_preview(run_id, preview, rows_read=compiled.rows_read)
        return {
            "id": run_id,
            "status": "COMPLETED",
            "plan_id": preview.get("id"),
            "plan_hash": preview.get("plan_hash"),
            "baseline_hash": preview.get("baseline_hash"),
            "rows_read": compiled.rows_read,
        }
    except Exception as exc:  # noqa: BLE001 - every durable run must record failure
        _fail(run_id, exc)
        return {"id": run_id, "status": "FAILED", "error": str(exc)[:2000]}


def run(limit: int = 100) -> list[dict[str, Any]]:
    results = []
    for row in _pending(limit):
        results.append(process_run(row))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    results = run(max(1, min(args.limit, 1000)))
    print(json.dumps({"processed": len(results), "runs": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
