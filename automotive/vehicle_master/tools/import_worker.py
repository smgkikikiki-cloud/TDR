"""Run uploaded source files through the deterministic importer.

    python -m tools.import_worker --limit 5

Claims each UPLOADED row in ``import_runs``, downloads the file it points
at, runs ``tools.import_source`` against it with ``--apply``, and writes
back what happened. The owner's page reads that row and nothing else, so
everything here -- claiming, downloading, retrying -- stays invisible.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from tools.canonical_input_worker import _env
from tools.import_source import main as run_import

BUCKET = "source-imports"


def _headers(key: str) -> dict:
    headers = {"apikey": key, "accept": "application/json"}
    if key.startswith("eyJ"):
        headers["authorization"] = f"Bearer {key}"
    return headers


def _rest(method: str, path: str, payload=None, *, prefer: str | None = None):
    url, key = _env()
    headers = _headers(key)
    body = None
    if payload is not None:
        headers["content-type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False).encode()
    if prefer:
        headers["prefer"] = prefer
    request = Request(f"{url}/rest/v1/{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            content = response.read().decode()
    except HTTPError as exc:
        raise RuntimeError(f"Supabase request failed ({exc.code}): "
                           f"{exc.read().decode(errors='replace')[:500]}") from exc
    return json.loads(content) if content else None


def _download(storage_path: str, into: Path) -> Path:
    url, key = _env()
    request = Request(f"{url}/storage/v1/object/{BUCKET}/{quote(storage_path)}",
                      headers=_headers(key))
    target = into / storage_path.split("/")[-1]
    with urlopen(request, timeout=300) as response:
        target.write_bytes(response.read())
    return target


def _finish(run_id: str, patch: dict):
    _rest("PATCH", f"import_runs?id=eq.{quote(run_id)}",
          {**patch, "finished_at": datetime.now(timezone.utc).isoformat()},
          prefer="return=minimal")


def process(limit: int) -> int:
    rows = _rest("GET", "import_runs?select=id,storage_path,original_name,source_kind"
                        f"&status=eq.UPLOADED&order=created_at.asc&limit={limit}") or []
    if not rows:
        print(json.dumps({"claimed": 0}))
        return 0

    done = 0
    for row in rows:
        run_id = str(row["id"])
        claimed = _rest(
            "PATCH", f"import_runs?id=eq.{quote(run_id)}&status=eq.UPLOADED",
            {"status": "PROCESSING",
             "started_at": datetime.now(timezone.utc).isoformat()},
            prefer="return=representation") or []
        if not claimed:
            continue
        with tempfile.TemporaryDirectory() as workdir:
            work = Path(workdir)
            try:
                source_file = _download(str(row["storage_path"]), work)
                report_dir = work / "report"
                run_import([
                    str(source_file), "--source", str(row["source_kind"]),
                    "--source-ref", str(row["original_name"]),
                    "--report-dir", str(report_dir), "--apply",
                ])
                report = json.loads(next(report_dir.glob("*_report.json")).read_text())
                _finish(run_id, {
                    "status": "COMPLETED",
                    "rows_read": report.get("rows_read"),
                    "patched": report.get("patched"),
                    "created": report.get("created"),
                    "exceptions": report.get("exceptions"),
                    "error": None,
                })
                done += 1
            except Exception as exc:  # noqa: BLE001 - the row must record any failure
                _finish(run_id, {"status": "FAILED", "error": str(exc)[:2000]})
    print(json.dumps({"claimed": len(rows), "completed": done}))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)
    if not os.environ.get("SUPABASE_URL"):
        raise SystemExit("SUPABASE_URL is required")
    return process(max(1, min(args.limit, 20)))


if __name__ == "__main__":
    raise SystemExit(main())
