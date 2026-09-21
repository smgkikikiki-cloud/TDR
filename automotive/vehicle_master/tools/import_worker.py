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

Whatever the owner has to come back and resolve becomes a row in
``import_run_exceptions``, not a capped JSON blob and not a file in the
temp directory this uses for processing -- that directory is gone by the
time anybody reads the result, and a cap loses work silently.
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
from vehreg.catalog import DATA_DIR, DEFAULT_YEAR, Catalog, CatalogError
from vehreg.registration_import import (
    MATCHED, UnsupportedRegistrationSchema, exception_rows, normalize_token,
    parse_registration_rows, resolve_registrations, snapshot_rows,
)

BUCKET = "source-imports"
#: Sources that write canonical vehicle files, so their run is only finished
#: once those files are committed and pushed.
CANONICAL_SOURCES = {"ECO"}


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

def _import_eco(source_file: Path, original_name: str, workdir: Path,
                run_id: str, submitted_at: str) -> tuple[dict, list[dict]]:
    report_dir = workdir / "report"
    run_eco_import([
        str(source_file), "--source", "ECO", "--source-ref", original_name,
        "--report-dir", str(report_dir), "--apply",
        # The run's own submission time, so a run picked up again after a
        # failure sends the same batches and the pipeline replays them
        # instead of rejecting the one that already landed.
        "--submitted-at", submitted_at,
    ])
    report = json.loads(next(report_dir.glob("*_report.json")).read_text(encoding="utf-8"))
    payload = json.loads(next(report_dir.glob("*_exceptions.json")).read_text(encoding="utf-8"))
    exceptions = [{
        "kind": "VEHICLE_IDENTITY",
        "reason": str(row.get("reason") or "identity unresolved"),
        "source_identity": {k: v for k, v in row.items() if k != "reason"},
    } for row in (payload.get("exceptions") or [])]
    for conflict in payload.get("conflicts") or []:
        exceptions.append({
            "kind": "CONFLICT",
            "reason": json.dumps(conflict.get("conflicts"), ensure_ascii=False),
            "source_identity": {"source_id": conflict.get("source_id"),
                                "trim_id": conflict.get("trim_id")},
        })
    return {
        "rows_read": report.get("rows_read"), "patched": report.get("patched"),
        "created": report.get("created"), "exceptions": len(exceptions),
    }, exceptions


def _trim_detail_brands() -> frozenset[str]:
    """Marques whose registration files print the grade inside the model field.

    Whether a label can be resolved to a trim at all is a property of the
    source, and the catalogue is where that is recorded (``Brand.trim_detail``,
    true for the Chinese marques and Tesla). Reading it here keeps the
    registration importer itself free of vehicle data while still refusing
    to offer a trim for a marque that never files one.
    """
    try:
        catalog = Catalog.load(DATA_DIR, DEFAULT_YEAR)
    except (CatalogError, OSError, ValueError):
        # Without the catalogue nothing is known to carry trim detail, and
        # model grain is the safe answer.
        return frozenset()
    tokens: set[str] = set()
    for brand in catalog.brands.values():
        if not brand.trim_detail:
            continue
        for label in (brand.id, brand.name_en, brand.name_th, *brand.aliases):
            token = normalize_token(label)
            if token:
                tokens.add(token)
    return frozenset(tokens)


def _import_dlt(source_file: Path, original_name: str, workdir: Path,
                run_id: str, submitted_at: str) -> tuple[dict, list[dict]]:
    rows, rejected = parse_registration_rows(_read_rows(source_file))
    periods = sorted({row.period for row in rows})
    if len(periods) != 1:
        raise UnsupportedRegistrationSchema(
            "an official monthly export covers exactly one period; this file has "
            + (", ".join(periods) if periods else "none"))

    brand_aliases = {
        str(row["raw_brand_norm"]): str(row["brand_id"])
        for row in _rest("GET", "registration_brand_aliases?select=raw_brand_norm,brand_id&limit=5000") or []
    }
    model_aliases = _rest(
        "GET",
        "registration_model_aliases?select=brand_id,registration_type,alias_norm,"
        "model_id,canonical_model_id,canonical_trim_id,match_mode&limit=20000",
    ) or []

    resolved = resolve_registrations(rows, brand_aliases, model_aliases)
    matched = [r for r in resolved if r.status == MATCHED]

    # A monthly export is the whole period, so the period is replaced rather
    # than merged: a row a corrected file no longer lists has to disappear,
    # which upsert can never do. Every row goes in, matched or not -- an
    # unknown label is a mapping problem, not a reason for the month to lose
    # its units. The RPC does the delete and the insert in one transaction,
    # so a failure cannot leave the month emptied.
    written = _rest("POST", "rpc/tdr_replace_registration_period", {
        "p_period": periods[0],
        "p_registration_type": None,
        "p_rows": snapshot_rows(resolved),
        "p_import_run_id": run_id,
        "p_source_reference": original_name,
    })

    exceptions = exception_rows(resolved, trim_detail_brands=_trim_detail_brands())
    exceptions.extend({
        "kind": "MALFORMED_ROW", "reason": item["reason"],
        "source_identity": {"row": item.get("row"), "period": periods[0]},
    } for item in rejected)
    return {
        "rows_read": len(rows) + len(rejected),
        "patched": len(matched),
        "created": 0,
        "exceptions": len(exceptions),
        "rows_written": written if isinstance(written, int) else len(rows),
    }, exceptions


HANDLERS = {"ECO": _import_eco, "DLT": _import_dlt}


def process(limit: int) -> int:
    rows = _rest("GET", "import_runs?select=id,storage_path,original_name,source_kind,created_at"
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
                counts, exceptions = handler(
                    source_file, str(row["original_name"]), work, run_id,
                    str(row.get("created_at") or datetime.now(timezone.utc).isoformat()))
            except UnsupportedRegistrationSchema as exc:
                _finish_failed(run_id, f"unsupported schema: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 - the row must record any failure
                _finish_failed(run_id, str(exc)[:2000])
                continue

        # Every unresolved row, not the first five hundred of them.
        _store_exceptions(run_id, source_kind, exceptions)

        # A canonical source is not finished until its files are committed
        # AND the release carrying them is published; it waits for
        # finalize. A DLT run has already landed in registrations, and
        # never goes near the canonical release.
        pending = source_kind in CANONICAL_SOURCES
        _patch(run_id, {
            **counts,
            "status": "WRITTEN_PENDING_PUBLISH" if pending else "COMPLETED",
            "error": None,
            **({} if pending else {"finished_at": datetime.now(timezone.utc).isoformat()}),
        })
        done += 1
    print(json.dumps({"claimed": len(rows), "processed": done}))
    return 0


def _store_exceptions(run_id: str, source_kind: str, exceptions: list[dict]):
    """Every unresolved row gets its own durable, resolvable record.

    These used to be a JSON array on the run, truncated at 500, so a file
    with 900 unplaceable rows quietly lost 400 of them -- work nobody could
    see and nobody would ever be asked to do."""
    if not exceptions:
        return
    for start in range(0, len(exceptions), 500):
        _rest("POST", "import_run_exceptions", [{
            "run_id": run_id,
            "source_kind": source_kind,
            "kind": str(item.get("kind") or "UNKNOWN"),
            "reason": str(item.get("reason") or "")[:2000],
            "source_identity": item.get("source_identity") or {},
            "status": "OPEN",
        } for item in exceptions[start:start + 500]], prefer="return=minimal")


def _finish_failed(run_id: str, error: str):
    _patch(run_id, {
        "status": "FAILED", "error": error,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    })


def finalize(run_ids: list[str], commit_sha: str, release_id: str) -> int:
    """Complete the runs this publish actually carried.

    Named runs only. Sweeping every WRITTEN_PENDING_PUBLISH row would let
    one run's successful publish mark another run's work complete, when
    that other run's write may not be in this commit at all.
    """
    if not run_ids:
        print(json.dumps({"completed": 0}))
        return 0
    if not commit_sha or not release_id:
        raise SystemExit("finalize needs the commit and the release it published")
    completed = 0
    for run_id in run_ids:
        rows = _patch(run_id, {
            "status": "COMPLETED",
            "commit_sha": commit_sha,
            "release_id": release_id,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }, expected_status="WRITTEN_PENDING_PUBLISH")
        completed += len(rows)
    print(json.dumps({"completed": completed, "release_id": release_id}))
    return 0


def pending_runs() -> int:
    """The runs a publish is about to carry, so it can name them afterwards."""
    rows = _rest("GET", "import_runs?select=id&status=eq.WRITTEN_PENDING_PUBLISH&limit=50") or []
    print(" ".join(str(row["id"]) for row in rows))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--limit", type=int, default=5)
    sub.add_parser("pending-runs")
    p_final = sub.add_parser("finalize")
    p_final.add_argument("--run-id", action="append", default=[])
    p_final.add_argument("--commit-sha", default="")
    p_final.add_argument("--release-id", default="")
    args = parser.parse_args(argv)
    if not os.environ.get("SUPABASE_URL"):
        raise SystemExit("SUPABASE_URL is required")
    if args.command == "pending-runs":
        return pending_runs()
    if args.command == "finalize":
        return finalize(args.run_id, args.commit_sha, args.release_id)
    return process(max(1, min(args.limit, 20)))


if __name__ == "__main__":
    raise SystemExit(main())
