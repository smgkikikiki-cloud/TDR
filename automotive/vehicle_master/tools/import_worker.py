"""Run uploaded source files through the importer that fits them.

    python -m tools.import_worker run --limit 5
    python -m tools.import_worker finalize

``run`` claims each uploaded row in ``import_runs``, downloads its file and
routes it by source kind -- ECO to the canonical MarketTrim importer, DLT to
the registration importer, anything with no parser of its own to an explicit
unsupported result. It never falls back to a parser built for a different
source: a confident wrong answer is worse than a refusal.

``finalize`` is what marks a canonical run COMPLETED, and it runs only after
the commit and push succeeded. A run whose write never reached the
repository must not tell the owner it is done.

Whatever the owner has to come back and resolve is written onto the
``import_runs`` row itself, not into the temp directory this uses for
processing -- that directory is gone by the time anybody reads the result.
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
from tools.import_source import main as run_eco_import
from vehreg.registration_import import (
    MATCHED, UnsupportedRegistrationSchema, parse_registration_rows,
    registration_payload, resolve_registrations,
)

BUCKET = "source-imports"
#: Sources that write canonical vehicle files, so their run is only finished
#: once those files are committed and pushed.
CANONICAL_SOURCES = {"ECO"}
MAX_STORED_EXCEPTIONS = 500


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
        with urlopen(request, timeout=120) as response:
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


def _patch(run_id: str, patch: dict, *, expected_status: str | None = None):
    path = f"import_runs?id=eq.{quote(run_id)}"
    if expected_status:
        path += f"&status=eq.{quote(expected_status)}"
    return _rest("PATCH", path, patch, prefer="return=representation") or []


def _read_rows(path: Path) -> list[dict]:
    import pandas

    frame = (pandas.read_csv(path) if path.suffix.lower() == ".csv"
             else pandas.read_excel(path))
    return frame.to_dict(orient="records")


# --- source handlers ---------------------------------------------------
# Each returns (counts, exception_rows). Neither may reach for another
# source's parser.

def _import_eco(source_file: Path, original_name: str, workdir: Path) -> tuple[dict, list[dict]]:
    report_dir = workdir / "report"
    run_eco_import([
        str(source_file), "--source", "ECO", "--source-ref", original_name,
        "--report-dir", str(report_dir), "--apply",
    ])
    report = json.loads(next(report_dir.glob("*_report.json")).read_text(encoding="utf-8"))
    payload = json.loads(next(report_dir.glob("*_exceptions.json")).read_text(encoding="utf-8"))
    exceptions = list(payload.get("exceptions") or [])
    for conflict in payload.get("conflicts") or []:
        exceptions.append({
            "kind": "CONFLICT", "source_id": conflict.get("source_id"),
            "model_id": conflict.get("trim_id"),
            "reason": json.dumps(conflict.get("conflicts"), ensure_ascii=False),
        })
    return {
        "rows_read": report.get("rows_read"), "patched": report.get("patched"),
        "created": report.get("created"), "exceptions": len(exceptions),
    }, exceptions


def _import_dlt(source_file: Path, original_name: str, workdir: Path) -> tuple[dict, list[dict]]:
    rows, rejected = parse_registration_rows(_read_rows(source_file))
    brand_aliases = {
        str(row["raw_brand_norm"]): str(row["brand_id"])
        for row in _rest("GET", "registration_brand_aliases?select=raw_brand_norm,brand_id&limit=5000") or []
    }
    model_aliases = _rest(
        "GET",
        "registration_model_aliases?select=brand_id,registration_type,alias_norm,model_id,match_mode&limit=20000",
    ) or []

    resolved = resolve_registrations(rows, brand_aliases, model_aliases)
    matched = [r for r in resolved if r.status == MATCHED]
    unknown = [r for r in resolved if r.status != MATCHED]

    # The table's own key is (period, registration_type, brand_name_raw,
    # model_name_raw), so re-uploading a month replaces it, a correction
    # corrects it, and a new month appends -- no duplicate rows either way.
    for start in range(0, len(matched), 500):
        chunk = [registration_payload(r, mapping_method="import-alias")
                 for r in matched[start:start + 500]]
        _rest("POST",
              "registrations?on_conflict=period,registration_type,brand_name_raw,model_name_raw",
              chunk, prefer="resolution=merge-duplicates,return=minimal")

    exceptions = [{
        "kind": "REGISTRATION_IDENTITY",
        "period": r.row.period, "registration_type": r.row.registration_type,
        "brand": r.row.brand_raw, "model": r.row.model_raw,
        "units": r.row.units, "reason": r.reason,
    } for r in unknown]
    exceptions.extend({"kind": "MALFORMED_ROW", "reason": item["reason"]} for item in rejected)
    return {
        "rows_read": len(rows) + len(rejected), "patched": len(matched),
        "created": 0, "exceptions": len(exceptions),
    }, exceptions


HANDLERS = {"ECO": _import_eco, "DLT": _import_dlt}


def process(limit: int) -> int:
    rows = _rest("GET", "import_runs?select=id,storage_path,original_name,source_kind"
                        f"&status=eq.UPLOADED&order=created_at.asc&limit={limit}") or []
    if not rows:
        print(json.dumps({"claimed": 0}))
        return 0

    done = 0
    for row in rows:
        run_id = str(row["id"])
        source_kind = str(row["source_kind"]).upper()
        if not _patch(run_id, {"status": "PROCESSING",
                               "started_at": datetime.now(timezone.utc).isoformat()},
                      expected_status="UPLOADED"):
            continue

        handler = HANDLERS.get(source_kind)
        if handler is None:
            _finish_failed(run_id, f"{source_kind} has no import profile yet; "
                                   "this file was not read by another source's parser")
            continue

        with tempfile.TemporaryDirectory() as workdir:
            work = Path(workdir)
            try:
                source_file = _download(str(row["storage_path"]), work)
                counts, exceptions = handler(source_file, str(row["original_name"]), work)
            except UnsupportedRegistrationSchema as exc:
                _finish_failed(run_id, f"unsupported schema: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 - the row must record any failure
                _finish_failed(run_id, str(exc)[:2000])
                continue

        # A canonical source is not finished until its files are pushed, so
        # it waits for finalize; everything else has already landed.
        pending = source_kind in CANONICAL_SOURCES
        _patch(run_id, {
            **counts,
            "exception_rows": exceptions[:MAX_STORED_EXCEPTIONS],
            "status": "WRITTEN_PENDING_PUBLISH" if pending else "COMPLETED",
            "error": None,
            **({} if pending else {"finished_at": datetime.now(timezone.utc).isoformat()}),
        })
        done += 1
    print(json.dumps({"claimed": len(rows), "processed": done}))
    return 0


def _finish_failed(run_id: str, error: str):
    _patch(run_id, {
        "status": "FAILED", "error": error,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    })


def finalize() -> int:
    """Mark pushed canonical runs COMPLETED. Only ever called after a push."""
    rows = _rest("GET", "import_runs?select=id&status=eq.WRITTEN_PENDING_PUBLISH&limit=50") or []
    for row in rows:
        _patch(str(row["id"]), {
            "status": "COMPLETED",
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }, expected_status="WRITTEN_PENDING_PUBLISH")
    print(json.dumps({"completed": len(rows)}))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--limit", type=int, default=5)
    sub.add_parser("finalize")
    args = parser.parse_args(argv)
    if not os.environ.get("SUPABASE_URL"):
        raise SystemExit("SUPABASE_URL is required")
    if args.command == "finalize":
        return finalize()
    return process(max(1, min(args.limit, 20)))


if __name__ == "__main__":
    raise SystemExit(main())
