"""Generate owner Retail Lineup Bootstrap workbooks requested by Admin.

This worker is deliberately read-only with respect to canonical vehicle data.
It claims rows from ``retail_lineup_workbook_exports``, runs the existing
Chunk-3 generator against the checked-out canonical tree, uploads the XLSX to
the private ``source-imports`` bucket, then records the exact baseline hash.

Compiling an edited workbook and applying a plan remain separate later paths.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from tools.canonical_input_worker import _clean_env_value, _env, _request
from vehreg.retail_lineup_workbook import generate_retail_lineup_workbook

BUCKET = "source-imports"
TABLE = "retail_lineup_workbook_exports"
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class RetailLineupWorkbookExportError(RuntimeError):
    pass


RestCall = Callable[..., Any]
StorageUpload = Callable[[str, bytes], None]
GenerateWorkbook = Callable[..., dict[str, Any]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pending(limit: int, *, rest: RestCall = _request) -> list[dict[str, Any]]:
    rows = rest(
        "GET",
        f"{TABLE}?select=*&status=eq.QUEUED&order=created_at.asc&limit={max(1, int(limit))}",
    ) or []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _claim(row_id: str, *, rest: RestCall = _request) -> dict[str, Any] | None:
    rows = rest(
        "PATCH",
        f"{TABLE}?id=eq.{quote(row_id)}&status=eq.QUEUED",
        {"status": "PROCESSING", "processing_started_at": _now(), "error": None},
        prefer="return=representation",
    ) or []
    if not rows:
        return None
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise RetailLineupWorkbookExportError("claim returned an unexpected export row set")
    return dict(rows[0])


def _patch_processing(
    row_id: str,
    payload: dict[str, Any],
    *,
    rest: RestCall = _request,
) -> dict[str, Any]:
    rows = rest(
        "PATCH",
        f"{TABLE}?id=eq.{quote(row_id)}&status=eq.PROCESSING",
        payload,
        prefer="return=representation",
    ) or []
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise RetailLineupWorkbookExportError(
            "export row stopped being PROCESSING before result persistence")
    return dict(rows[0])


def _storage_upload(path: str, content: bytes) -> None:
    url, api_key = _env()
    # Prefer the legacy service-role JWT when it exists because Storage accepts
    # it universally as a Bearer token. New sb_secret keys remain the fallback.
    bearer = _clean_env_value(
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or api_key,
        "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY",
    )
    encoded = quote(path.strip("/"), safe="/")
    request = Request(
        f"{url}/storage/v1/object/{BUCKET}/{encoded}",
        data=content,
        method="POST",
        headers={
            "apikey": api_key,
            "authorization": f"Bearer {bearer}",
            "content-type": XLSX_CONTENT_TYPE,
            "x-upsert": "false",
        },
    )
    try:
        with urlopen(request, timeout=120) as response:
            if response.status not in (200, 201):
                raise RetailLineupWorkbookExportError(
                    f"storage upload returned HTTP {response.status}")
    except HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RetailLineupWorkbookExportError(
            f"storage upload failed ({exc.code}): {body[:500]}") from exc


def _clean_model_ids(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        raise RetailLineupWorkbookExportError("model_ids must be an array")
    values = sorted({str(value or "").strip() for value in raw if str(value or "").strip()})
    if not values:
        raise RetailLineupWorkbookExportError("workbook export has no model_ids")
    if len(values) != len(raw):
        raise RetailLineupWorkbookExportError("model_ids must be unique and nonempty")
    return values


def process_export(
    row: dict[str, Any],
    *,
    rest: RestCall = _request,
    upload: StorageUpload = _storage_upload,
    generate: GenerateWorkbook = generate_retail_lineup_workbook,
) -> dict[str, Any]:
    row_id = str(row.get("id") or "").strip()
    if not row_id:
        raise RetailLineupWorkbookExportError("export row has no id")
    claimed = _claim(row_id, rest=rest)
    if claimed is None:
        return {"id": row_id, "status": "SKIPPED_ALREADY_CLAIMED"}

    try:
        model_ids = _clean_model_ids(claimed.get("model_ids"))
        year = int(claimed.get("catalog_year"))
        release_id = str(claimed.get("base_release_id") or "").strip()
        if not release_id:
            raise RetailLineupWorkbookExportError("base_release_id is required")

        storage_path = f"retail-lineup-exports/{row_id}.xlsx"
        with tempfile.TemporaryDirectory(prefix="tdr-retail-lineup-export-") as tmp:
            output = Path(tmp) / "retail-lineup-bootstrap.xlsx"
            result = generate(
                output,
                model_ids=model_ids,
                base_release_id=release_id,
                year=year,
            )
            upload(storage_path, output.read_bytes())

        baseline = str(result.get("baseline_hash") or "").strip().lower()
        if len(baseline) != 64:
            raise RetailLineupWorkbookExportError("generator returned an invalid baseline hash")
        return _patch_processing(
            row_id,
            {
                "status": "READY",
                "storage_path": storage_path,
                "baseline_hash": baseline,
                "summary": result,
                "error": None,
                "completed_at": _now(),
            },
            rest=rest,
        )
    except Exception as exc:
        message = str(exc)[:4000] or exc.__class__.__name__
        try:
            _patch_processing(
                row_id,
                {"status": "FAILED", "error": message, "completed_at": _now()},
                rest=rest,
            )
        except Exception as persist_exc:
            raise RetailLineupWorkbookExportError(
                f"{message}; additionally failed to persist FAILED state: {persist_exc}") from exc
        return {"id": row_id, "status": "FAILED", "error": message}


def run(limit: int = 3, *, rest: RestCall = _request) -> list[dict[str, Any]]:
    results = []
    for row in _pending(limit, rest=rest):
        results.append(process_export(row, rest=rest))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args(argv)
    print(json.dumps({"exports": run(args.limit)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
