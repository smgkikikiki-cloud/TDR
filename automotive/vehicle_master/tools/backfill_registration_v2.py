#!/usr/bin/env python3
"""Backfill the live production `registrations` history into the DLT v2 shadow.

    python tools/backfill_registration_v2.py                       # dry run, all history
    python tools/backfill_registration_v2.py --period-from 2026-01 --period-to 2026-06
    python tools/backfill_registration_v2.py --apply                # write

Reads every row of the live Supabase `public.registrations` table (paged),
adapts each into a `RegistrationObservation`
(`vehreg.registration_observation.from_legacy_registration_row`), resolves it
against the canonical Vehicle Master catalog
(`vehreg.resolution_v2.resolve_observation`), and upserts the result into the
three DLT v2 shadow tables (`supabase/migration_v29_registration_dlt_v2_shadow.sql`).

Idempotent and resumable by construction, not by a checkpoint file: every
observation/fact/review row is keyed by a deterministic id
(`vehreg.registration_observation.observation_id`, a pure function of the
legacy row's own uuid), and every write is a PostgREST upsert
(`Prefer: resolution=merge-duplicates`) on that id. Re-running this tool -
over the same period, a wider period, or the whole table again - reproduces
the same rows; it never creates a duplicate fact and never needs a "resume
from here" marker. `--period-from`/`--period-to` exist only to let an
operator chunk a very large backfill into separate runs if useful, not
because a rerun without them would be unsafe.

Dry-run (no --apply) performs zero writes and prints the batch this run
would produce - counts before writing, per the packet's own requirement.
Safety boundary: this tool never touches `registrations`,
`registration_brand_aliases`, `registration_model_aliases`,
`match_registration_model`, or any `registration_*` analytics view - it only
ever reads `registrations` and writes the three v2 shadow tables.

Requires the same server-side credentials as every other Supabase-reading
tool in this repository: SUPABASE_URL (or NEXT_PUBLIC_SUPABASE_URL) plus
SUPABASE_SECRET_KEY (or legacy SUPABASE_SERVICE_ROLE_KEY). Without them this
tool fails closed and performs no read or write at all.

Exit 0: batch built (and, with --apply, written) successfully.
Exit 2: could not run at all (no credentials, no catalog, request failure).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vehreg.catalog import DATA_DIR, DEFAULT_YEAR, Catalog, CatalogError  # noqa: E402
from vehreg import db  # noqa: E402
from vehreg.ingest import Resolver  # noqa: E402
from vehreg.registration_observation import from_legacy_registration_row  # noqa: E402
from vehreg.registration_v2_writer import build_batch  # noqa: E402

DEFAULT_WAREHOUSE = ROOT / "data" / "vehreg.sqlite3"
PAGE_SIZE = 2000
UPSERT_BATCH_SIZE = 500


# --------------------------------------------------------------------------- Supabase REST
# Same minimal urllib-based PostgREST client pattern as
# tools/canonical_input_worker.py / tools/sync_external_identity_registry.py.

def _strip_wrapper_quotes(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1].strip()
    return cleaned


def _clean_env_value(value: Optional[str], *names: str) -> str:
    cleaned = _strip_wrapper_quotes(value or "")
    if "=" in cleaned:
        prefix, remainder = cleaned.split("=", 1)
        if prefix.strip() in names:
            cleaned = remainder.strip()
    return _strip_wrapper_quotes(cleaned)


class CredentialsError(RuntimeError):
    pass


def _env() -> tuple[str, str]:
    url = _clean_env_value(
        os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL"),
        "SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL",
    )
    key = _clean_env_value(
        os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY",
    )
    if not url or not key:
        raise CredentialsError(
            "SUPABASE_URL (or NEXT_PUBLIC_SUPABASE_URL) and SUPABASE_SECRET_KEY "
            "(or SUPABASE_SERVICE_ROLE_KEY) are required"
        )
    return url.rstrip("/"), key


def _request(method: str, path: str, payload=None, *, prefer: Optional[str] = None):
    url, key = _env()
    headers = {"apikey": key, "accept": "application/json"}
    if key.startswith("eyJ"):
        headers["authorization"] = f"Bearer {key}"
    body = None
    if payload is not None:
        headers["content-type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if prefer:
        headers["prefer"] = prefer
    request = Request(f"{url}/rest/v1/{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=120) as response:
            content = response.read().decode()
    except HTTPError as exc:
        content = exc.read().decode(errors="replace")
        raise RuntimeError(f"Supabase request failed ({exc.code}) for {method} {path}: {content[:1000]}") from exc
    return json.loads(content) if content else None


def _month_range(period: str) -> tuple[str, str]:
    """'2026-03' -> ('2026-03-01', '2026-04-01') for gte/lt date filters."""
    year, month = int(period[:4]), int(period[5:7])
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start.isoformat(), end.isoformat()


def fetch_legacy_registrations(*, period_from: Optional[str] = None,
                               period_to: Optional[str] = None,
                               limit: Optional[int] = None) -> list[dict[str, Any]]:
    """Every row of `public.registrations`, paged. Read-only."""
    filters = []
    if period_from:
        filters.append(f"period=gte.{_month_range(period_from)[0]}")
    if period_to:
        filters.append(f"period=lt.{_month_range(period_to)[1]}")
    base = ("registrations?select=id,period,registration_type,brand_name_raw,"
           "model_name_raw,model_id,registrations,source_id,mapping_method"
           "&order=id.asc")
    if filters:
        base += "&" + "&".join(filters)

    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page_limit = PAGE_SIZE if limit is None else min(PAGE_SIZE, limit - len(rows))
        if page_limit <= 0:
            break
        page = _request("GET", f"{base}&limit={page_limit}&offset={offset}") or []
        rows.extend(page)
        if len(page) < page_limit:
            break
        offset += len(page)
    return rows


def upsert_rows(table: str, rows: list[dict[str, Any]], *,
                on_conflict: str = "observation_id",
                batch_size: int = UPSERT_BATCH_SIZE) -> None:
    for start in range(0, len(rows), batch_size):
        chunk = rows[start:start + batch_size]
        _request("POST", f"{table}?on_conflict={on_conflict}", chunk,
                 prefer="resolution=merge-duplicates,return=minimal")


# --------------------------------------------------------------------------- CLI

def _resolver(catalog: Catalog, warehouse: Path) -> tuple[Resolver, str]:
    if warehouse.is_file():
        conn = db.connect(warehouse)
        note = f"reusing alias_override lessons from {warehouse}"
    else:
        conn = db.connect(":memory:")
        note = (f"warehouse {warehouse} not found - resolving with no taught "
               "aliases (v2 coverage may be lower than v1's until a warehouse "
               "is supplied via --warehouse)")
    return Resolver(catalog, conn), note


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--warehouse", type=Path, default=DEFAULT_WAREHOUSE,
                        help="local vehreg SQLite warehouse to reuse alias_override "
                             "lessons from (read-only); falls back to no aliases "
                             "if the path does not exist")
    parser.add_argument("--period-from", default=None, help="YYYY-MM, inclusive")
    parser.add_argument("--period-to", default=None, help="YYYY-MM, inclusive")
    parser.add_argument("--limit", type=int, default=None,
                        help="max legacy rows to read (for testing a subset)")
    parser.add_argument("--apply", action="store_true",
                        help="write to the v2 shadow tables (default: dry run)")
    parser.add_argument("--json-out", type=Path, default=None)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)

    try:
        catalog = Catalog.load(args.data_dir, args.year)
    except CatalogError as exc:
        print(f"backfill: cannot load canonical catalog: {exc}", file=sys.stderr)
        return 2

    resolver, warehouse_note = _resolver(catalog, args.warehouse)
    print(f"backfill: {warehouse_note}", file=sys.stderr)

    try:
        legacy_rows = fetch_legacy_registrations(
            period_from=args.period_from, period_to=args.period_to,
            limit=args.limit)
    except CredentialsError as exc:
        print(f"backfill: no server-side Supabase credentials found ({exc}). "
             "Nothing was read. Exiting without a report.", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"backfill: live read failed: {exc}", file=sys.stderr)
        return 2

    print(f"backfill: read {len(legacy_rows)} legacy registrations row(s)",
         file=sys.stderr)
    observations = [from_legacy_registration_row(row) for row in legacy_rows]
    batch = build_batch(observations, resolver, catalog)

    summary = batch.summary()
    print("\nbatch summary (counts before writing):", file=sys.stderr)
    for key, value in summary.items():
        print(f"  {key}: {value}", file=sys.stderr)

    if args.apply:
        print(f"\n--apply: upserting {len(batch.observation_rows)} observation(s), "
             f"{len(batch.fact_rows)} fact(s), {len(batch.review_rows)} review "
             "row(s)...", file=sys.stderr)
        try:
            upsert_rows("registration_observations_v2", batch.observation_rows)
            upsert_rows("registration_facts_v2", batch.fact_rows)
            upsert_rows("registration_resolution_review_v2", batch.review_rows)
        except RuntimeError as exc:
            print(f"backfill: write failed: {exc}", file=sys.stderr)
            return 2
        print("--apply: done.", file=sys.stderr)
    else:
        print("\ndry run: nothing written. Rerun with --apply to write.",
             file=sys.stderr)

    if args.json_out:
        args.json_out.write_text(json.dumps(summary, indent=2, sort_keys=True),
                                 encoding="utf-8")
        print(f"\nwrote JSON summary to {args.json_out}", file=sys.stderr)
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
