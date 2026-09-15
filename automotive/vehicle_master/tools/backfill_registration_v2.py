#!/usr/bin/env python3
"""Backfill the live production `registrations` history into the DLT v2 shadow.

    python tools/backfill_registration_v2.py                       # dry run, all history
    python tools/backfill_registration_v2.py --period-from 2026-01 --period-to 2026-06
    python tools/backfill_registration_v2.py --apply                # write

Reads every row of the live Supabase `public.registrations` table (paged),
adapts each into a `RegistrationObservation`
(`vehreg.registration_observation.from_legacy_registration_row`), resolves it
against the canonical Vehicle Master catalog
(`vehreg.resolution_v2.resolve_observation`), and writes the result into the
three DLT v2 shadow tables (`supabase/migration_v29_registration_dlt_v2_shadow.sql`).

Idempotent and resumable by construction, not by a checkpoint file: every
row is keyed by a deterministic id (`vehreg.registration_observation.
observation_id`, a pure function of the legacy row's own uuid). Re-running
this tool - over the same period, a wider period, or the whole table again -
reproduces the same rows; it never needs a "resume from here" marker.
`--period-from`/`--period-to` exist only to let an operator chunk a very
large backfill into separate runs if useful, not because a rerun without
them would be unsafe.

**Observations are write-once** (Phase 3 preflight fix): this tool fetches
the persisted `payload_hash` for every observation id in this run's batch
first, classifies each id via `vehreg.registration_v2_writer.
plan_observation_writes` (new -> plain INSERT; unchanged -> skip; drifted ->
blocker), and only ever plain-`INSERT`s a genuinely new observation row -
never an upsert, never an UPDATE (the database itself also refuses one, see
`supabase/migration_v30_registration_v2_immutable_observations.sql`). If
*any* observation id in this run's batch is in conflict (the same id already
persisted under a different payload hash, or two different payloads for the
same id within this very batch), the whole run applies zero writes - not
even for other, individually-clean ids - and exits non-zero; see
`vehreg.registration_v2_writer.writes_to_apply`. Fact/review rows remain
freely upsertable, since they are derived and may always be regenerated.

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
from vehreg.registration_v2_writer import (  # noqa: E402
    build_batch,
    plan_observation_writes,
    writes_to_apply,
)

DEFAULT_WAREHOUSE = ROOT / "data" / "vehreg.sqlite3"
PAGE_SIZE = 2000
UPSERT_BATCH_SIZE = 500
ID_FILTER_CHUNK = 200


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
    """Upsert -- only ever used for the two *derived* tables
    (facts/review), which are expected to be freely regenerated. Never used
    for `registration_observations_v2` -- see `insert_rows` below."""
    for start in range(0, len(rows), batch_size):
        chunk = rows[start:start + batch_size]
        _request("POST", f"{table}?on_conflict={on_conflict}", chunk,
                 prefer="resolution=merge-duplicates,return=minimal")


def insert_rows(table: str, rows: list[dict[str, Any]], *,
                batch_size: int = UPSERT_BATCH_SIZE) -> None:
    """Plain INSERT, no `on_conflict`/merge -- used only for
    `registration_observations_v2`, and only for ids
    `plan_observation_writes` already classified as genuinely new. A unique-
    violation here (a race between the hash-check read and this write) fails
    loudly rather than silently overwriting anything, which is the correct
    behavior for a write-once table -- the DB grants/trigger in
    migration_v30 back this up independently."""
    for start in range(0, len(rows), batch_size):
        chunk = rows[start:start + batch_size]
        _request("POST", table, chunk, prefer="return=minimal")


def fetch_existing_observation_hashes(
    observation_ids: list[str],
) -> dict[str, str]:
    """`{observation_id: payload_hash}` for every id in `observation_ids`
    that is already persisted in `registration_observations_v2` -- read-only,
    used only to classify this run's batch before writing anything."""
    out: dict[str, str] = {}
    for start in range(0, len(observation_ids), ID_FILTER_CHUNK):
        chunk = observation_ids[start:start + ID_FILTER_CHUNK]
        id_list = ",".join(quote(i, safe="") for i in chunk)
        rows = _request(
            "GET",
            "registration_observations_v2?select=observation_id,payload_hash"
            f"&observation_id=in.({id_list})",
        ) or []
        for row in rows:
            out[row["observation_id"]] = row["payload_hash"]
    return out


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

    if batch.drift_conflicts:
        print(f"\nWITHIN-BATCH DRIFT CONFLICTS ({len(batch.drift_conflicts)}) -- "
             "same observation id, different payload, within this run's own "
             "read. Not written under any circumstance:", file=sys.stderr)
        for c in batch.drift_conflicts:
            print(f"    - {c.observation_id}: {c.payload_hashes} "
                 f"({c.units:,.0f} units)", file=sys.stderr)

    plan = None
    if args.apply:
        try:
            existing_hashes = fetch_existing_observation_hashes(
                [row["observation_id"] for row in batch.observation_rows])
        except RuntimeError as exc:
            print(f"backfill: could not read existing observation hashes: {exc}",
                 file=sys.stderr)
            return 2
        plan = plan_observation_writes(batch, existing_hashes)
        applied = writes_to_apply(batch, plan)

        print(f"\nwrite plan: {plan.summary()}", file=sys.stderr)
        if plan.is_blocked:
            against_existing = [c for c in plan.drift_conflicts if c.source == "existing"]
            if against_existing:
                print(f"\nSOURCE-DRIFT CONFLICTS AGAINST ALREADY-PERSISTED DATA "
                     f"({len(against_existing)}) -- the same observation id is "
                     "already stored with a different payload hash than this "
                     "run computed. Never auto-resolved:", file=sys.stderr)
                for c in against_existing:
                    print(f"    - {c.observation_id}: {c.payload_hashes} "
                         f"({c.units:,.0f} units)", file=sys.stderr)
            print("\n--apply: BLOCKED -- zero writes this run (a run-wide "
                 "fail-closed gate; see conflicts above). Resolve the drift, "
                 "then rerun.", file=sys.stderr)
            return 2

        print(f"\n--apply: inserting {len(applied.observations)} new "
             f"observation(s), upserting {len(applied.facts)} fact(s), "
             f"{len(applied.reviews)} review row(s)...", file=sys.stderr)
        try:
            insert_rows("registration_observations_v2", applied.observations)
            upsert_rows("registration_facts_v2", applied.facts)
            upsert_rows("registration_resolution_review_v2", applied.reviews)
        except RuntimeError as exc:
            print(f"backfill: write failed: {exc}", file=sys.stderr)
            return 2
        print("--apply: done.", file=sys.stderr)
    else:
        print("\ndry run: nothing written. Rerun with --apply to write.",
             file=sys.stderr)

    output = dict(summary)
    if plan is not None:
        output["write_plan"] = plan.summary()

    if args.json_out:
        args.json_out.write_text(json.dumps(output, indent=2, sort_keys=True),
                                 encoding="utf-8")
        print(f"\nwrote JSON summary to {args.json_out}", file=sys.stderr)
    else:
        print(json.dumps(output, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
