#!/usr/bin/env python3
"""Direct DLT -> v2 ingest for one or more months: the forward registration
ingestion path (Phase 3 preflight fix #2).

    python tools/registration_v2_dlt_ingest.py --period 2026-08                    # dry run
    python tools/registration_v2_dlt_ingest.py --period 2026-08 --period 2026-09
    python tools/registration_v2_dlt_ingest.py --period 2026-08 --apply             # write

Reads DLT's own CKAN `datastore_search` API directly (`vehreg.dlt.
monthly_index`/`fetch_records`/`REGISTRATION_BY_THAI_TYPE` - unchanged,
reused exactly as `vehreg.dlt.fetch_month` uses them), adapts each RY1/RY2/RY3
record into a `RegistrationObservation`
(`vehreg.registration_observation.from_dlt_record`), resolves it with the
same unchanged `vehreg.ingest.Resolver` every other v2 tool uses
(`vehreg.registration_v2_writer.build_batch` - no Resolver logic is
duplicated here), and writes the result into the three DLT v2 shadow tables,
under the same write-once observation guarantee as the backfill tool (see
`vehreg.registration_v2_writer.plan_observation_writes`/`writes_to_apply`
and `supabase/migration_v30_registration_v2_immutable_observations.sql`).

This is the intended **forward** ingestion path once Phase 3 is live: going
forward, a period's v2 volume should come from here, not from
`legacy_registrations_backfill` (that adapter exists for historical
backfill only - `public.registrations` will not receive new DLT months once
this path is in regular use). Nothing here writes to `registrations`,
`registration_brand_aliases`, `registration_model_aliases`,
`match_registration_model`, any `registration_*` analytics view, or routes
through the canonical vehicle-market command intake
(`vehreg/canonical_write.py`/`vehreg/canonical_queue.py`) - DLT registration
data is a distinct, separate write path from ECO/product canonical writes,
and stays that way.

**Source-lineage ownership** (preventing `legacy_registrations_backfill` and
`dlt_ckan` from both becoming authoritative v2 volume for the same period)
is enforced at serving/read time by `registration_facts_v2_serving`'s
deterministic period/source ownership rule
(`supabase/migration_v31_registration_v2_serving_and_cutover.sql`,
`vehreg.registration_v2_parity.authoritative_source_for_period`), not by
refusing to write here - writing a period's DLT observations/facts into the
shadow tables is always safe (they are inspectable, immutable, and
idempotent); which source's volume actually counts as authoritative for a
given period is a read-time decision, made in exactly one place. Run
`tools/registration_v2_parity.py --readiness` to see current source-lineage
overlaps before treating a freshly-ingested period as production-ready.

Dry-run (no --apply, the default) performs zero writes and prints the batch
this run would produce.

Requires the same server-side credentials as every other Supabase-writing
tool in this repository. Requires no DLT-side credentials - the CKAN API is
public.

Exit 0: batch built (and, with --apply, written) successfully.
Exit 2: could not run at all (no credentials, no catalog, DLT/Supabase
request failure, or a source-drift conflict blocked the whole run).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vehreg import dlt  # noqa: E402
from vehreg.catalog import DATA_DIR, DEFAULT_YEAR, Catalog, CatalogError  # noqa: E402
from vehreg.registration_observation import (  # noqa: E402
    RegistrationObservation,
    from_dlt_record,
)
from vehreg.registration_v2_writer import (  # noqa: E402
    build_batch,
    plan_observation_writes,
    writes_to_apply,
)

from tools.backfill_registration_v2 import (  # noqa: E402
    CredentialsError,
    _resolver,
    fetch_existing_observation_hashes,
    insert_rows,
    upsert_rows,
)


class DltFetchError(RuntimeError):
    pass


def fetch_month_observations(period: str, *,
                             resources: Optional[dict] = None,
                             ) -> tuple[list[RegistrationObservation], dict[str, int]]:
    """Every RY1/RY2/RY3 observation DLT publishes for one month, plus the
    skipped-units-by-class count (motorcycles, trailers, etc. - counted,
    never silently dropped, exactly as `vehreg.dlt.fetch_month` already
    reports it for the CSV path)."""
    index = resources if resources is not None else dlt.monthly_index()
    resource = index.get(period)
    if resource is None:
        available = ", ".join(sorted(index)[-6:])
        raise DltFetchError(f"DLT publishes no resource for {period}; "
                           f"most recent are {available}")

    observations: list[RegistrationObservation] = []
    skipped: dict[str, int] = {}
    for record in dlt.fetch_records(resource.id):
        thai_type = str(record.get("ประเภทรถ", "")).strip()
        registration = dlt.REGISTRATION_BY_THAI_TYPE.get(thai_type)
        if registration is None:
            try:
                units = int(str(record.get("จำนวน", 0)).replace(",", ""))
            except (TypeError, ValueError):
                units = 0
            key = thai_type or "(ว่าง)"
            skipped[key] = skipped.get(key, 0) + units
            continue
        observations.append(from_dlt_record(
            record, resource_id=resource.id, period=period,
            registration_type=registration.value))
    return observations, skipped


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--period", action="append", default=[],
                        help="YYYY-MM; repeatable for several months in one run")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--warehouse", type=Path,
                        default=ROOT / "data" / "vehreg.sqlite3",
                        help="local vehreg SQLite warehouse to reuse alias_override "
                             "lessons from (read-only)")
    parser.add_argument("--apply", action="store_true",
                        help="write to the v2 shadow tables (default: dry run)")
    parser.add_argument("--json-out", type=Path, default=None)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if not args.period:
        print("registration_v2_dlt_ingest: at least one --period YYYY-MM is required",
             file=sys.stderr)
        return 2

    try:
        catalog = Catalog.load(args.data_dir, args.year)
    except CatalogError as exc:
        print(f"dlt-ingest: cannot load canonical catalog: {exc}", file=sys.stderr)
        return 2

    resolver, warehouse_note = _resolver(catalog, args.warehouse)
    print(f"dlt-ingest: {warehouse_note}", file=sys.stderr)

    try:
        resources = dlt.monthly_index()
        observations: list[RegistrationObservation] = []
        skipped_total: dict[str, int] = {}
        for period in args.period:
            month_observations, skipped = fetch_month_observations(
                period, resources=resources)
            print(f"dlt-ingest: {period}: {len(month_observations)} RY1/RY2/RY3 "
                 "observation(s) fetched from DLT", file=sys.stderr)
            observations.extend(month_observations)
            for key, units in skipped.items():
                skipped_total[key] = skipped_total.get(key, 0) + units
    except DltFetchError as exc:
        print(f"dlt-ingest: {exc}", file=sys.stderr)
        return 2
    except dlt.DltError as exc:
        print(f"dlt-ingest: DLT request failed: {exc}", file=sys.stderr)
        return 2

    if skipped_total:
        top = sorted(skipped_total.items(), key=lambda kv: -kv[1])[:5]
        print("dlt-ingest: skipped (not รย.1/รย.2/รย.3, counted not dropped): "
             + ", ".join(f"{k} {v:,}" for k, v in top), file=sys.stderr)

    batch = build_batch(observations, resolver, catalog)
    summary = batch.summary()
    print("\nbatch summary (counts before writing):", file=sys.stderr)
    for key, value in summary.items():
        print(f"  {key}: {value}", file=sys.stderr)

    if batch.drift_conflicts:
        print(f"\nWITHIN-BATCH DRIFT CONFLICTS ({len(batch.drift_conflicts)}):",
             file=sys.stderr)
        for c in batch.drift_conflicts:
            print(f"    - {c.observation_id}: {c.payload_hashes} "
                 f"({c.units:,.0f} units)", file=sys.stderr)

    plan = None
    if args.apply:
        try:
            existing_hashes = fetch_existing_observation_hashes(
                [row["observation_id"] for row in batch.observation_rows])
        except CredentialsError as exc:
            print(f"dlt-ingest: no server-side Supabase credentials found ({exc}). "
                 "Nothing was written.", file=sys.stderr)
            return 2
        except RuntimeError as exc:
            print(f"dlt-ingest: could not read existing observation hashes: {exc}",
                 file=sys.stderr)
            return 2

        plan = plan_observation_writes(batch, existing_hashes)
        applied = writes_to_apply(batch, plan)
        print(f"\nwrite plan: {plan.summary()}", file=sys.stderr)

        if plan.is_blocked:
            against_existing = [c for c in plan.drift_conflicts if c.source == "existing"]
            if against_existing:
                print(f"\nSOURCE-DRIFT CONFLICTS AGAINST ALREADY-PERSISTED DATA "
                     f"({len(against_existing)}):", file=sys.stderr)
                for c in against_existing:
                    print(f"    - {c.observation_id}: {c.payload_hashes} "
                         f"({c.units:,.0f} units)", file=sys.stderr)
            print("\n--apply: BLOCKED -- zero writes this run.", file=sys.stderr)
            return 2

        print(f"\n--apply: inserting {len(applied.observations)} new "
             f"observation(s), upserting {len(applied.facts)} fact(s), "
             f"{len(applied.reviews)} review row(s)...", file=sys.stderr)
        try:
            insert_rows("registration_observations_v2", applied.observations)
            upsert_rows("registration_facts_v2", applied.facts)
            upsert_rows("registration_resolution_review_v2", applied.reviews)
        except CredentialsError as exc:
            print(f"dlt-ingest: no server-side Supabase credentials found ({exc}). "
                 "Nothing was written.", file=sys.stderr)
            return 2
        except RuntimeError as exc:
            print(f"dlt-ingest: write failed: {exc}", file=sys.stderr)
            return 2
        print("--apply: done. Run tools/registration_v2_parity.py --readiness "
             "before relying on this period as authoritative.", file=sys.stderr)
    else:
        print("\ndry run: nothing written. Rerun with --apply to write.",
             file=sys.stderr)

    output = dict(summary)
    output["periods"] = args.period
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
