#!/usr/bin/env python3
"""Dual-run parity / cutover readiness: v1 production `registrations` vs the
DLT v2 shadow output.

    python tools/registration_v2_parity.py
    python tools/registration_v2_parity.py --period-from 2026-01 --period-to 2026-06 --json-out parity.json
    python tools/registration_v2_parity.py --readiness --required-periods 2026-01,2026-02,2026-03

Read-only against every table it touches - this tool never writes anything,
to production or to the v2 shadow (the cutover switch itself is
`tools/registration_v2_cutover.py`). It reads `public.registrations` (v1),
`registration_observations_v2`/`registration_facts_v2` (v2),
`registration_serving_state` (the current source-ownership boundary), and
`current_vehicle_models` (the Mechanism A release-build crosswalk, the only
source this tool uses to translate a v1 row's legacy `model_id` uuid into a
canonical text id for comparison - see
`vehreg.registration_v2_parity`'s own module docstring for why a v1 row whose
`model_id` is not present in that crosswalk is its own reported bucket
(`v1_uncrosswalked`), not folded into "unresolved").

All the actual comparison logic is pure (`vehreg/registration_v2_parity.py`);
this file only fetches and adapts - `--readiness` reuses the same fetch and
the same `ParityReport` this tool always builds, wrapping it in
`build_cutover_readiness_report` rather than standing up a second, redundant
validator. See that module's docstring for the four questions a plain
parity run keeps strictly separate: volume parity, identity parity,
resolution-coverage difference, and grain difference. A mapping
disagreement between v1 and v2 is never, by itself, treated as a failure of
`is_clean` or of cutover readiness - only real volume mismatches,
reconciliation failures, duplicate keys, unresolved source-lineage
ownership, or a missing required period are. 100% identity agreement is
never required.

Requires the same server-side credentials as every other Supabase-reading
tool in this repository.

Exit 0: report built successfully. In `--readiness` mode, also means the
gate is clean (`is_ready_for_cutover: true`).
Exit 1: `--readiness` mode only - the report built successfully but the gate
is not clean; see `blockers` in the output. Never cut over on this exit code.
Exit 2: could not run at all (no credentials, no catalog, request failure).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.backfill_registration_v2 import (  # noqa: E402
    CredentialsError,
    _request,
    fetch_legacy_registrations,
)
from vehreg.registration_v2_parity import (  # noqa: E402
    LegacyRegistrationRow,
    V2FactRow,
    V2ObservationRow,
    build_cutover_readiness_report,
    build_parity_report,
)

PAGE_SIZE = 2000


def _paged(path_base: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        page = _request("GET", f"{path_base}&limit={PAGE_SIZE}&offset={offset}") or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += len(page)


def fetch_v2_observations() -> list[V2ObservationRow]:
    rows = _paged(
        "registration_observations_v2?select=observation_id,source_kind,"
        "source_ref,period,registration_type,units&order=observation_id.asc")
    return [V2ObservationRow(observation_id=r["observation_id"],
                             source_kind=r["source_kind"], source_ref=r["source_ref"],
                             period=r["period"], registration_type=r["registration_type"],
                             units=float(r["units"])) for r in rows]


def fetch_v2_facts() -> list[V2FactRow]:
    rows = _paged(
        "registration_facts_v2?select=observation_id,canonical_id,grain,units"
        "&order=observation_id.asc")
    return [V2FactRow(observation_id=r["observation_id"], canonical_id=r["canonical_id"],
                      grain=r["grain"], units=float(r["units"])) for r in rows]


def fetch_crosswalk() -> dict[str, str]:
    """{tdr_model_id (legacy uuid) -> canonical_id (text)} from the active
    Vehicle Master release's own crosswalk - Mechanism A, not this pass's
    resolver, and not `canonical_object_map` (Phase 1's separate mechanism)."""
    rows = _paged(
        "current_vehicle_models?select=canonical_id,tdr_model_id"
        "&tdr_model_id=not.is.null&order=canonical_id.asc")
    return {r["tdr_model_id"]: r["canonical_id"] for r in rows}


def fetch_serving_state() -> dict:
    rows = _request(
        "GET",
        "registration_serving_state?select=active_source,v2_source_boundary_period"
        "&scope=eq.registration_analytics",
    ) or []
    if not rows:
        return {"active_source": "legacy", "v2_source_boundary_period": None}
    return rows[0]


def adapt_legacy_rows(raw_rows: list[dict]) -> list[LegacyRegistrationRow]:
    return [LegacyRegistrationRow(
        id=str(r["id"]), period=str(r["period"])[:7],
        registration_type=str(r.get("registration_type") or "*"),
        brand_name_raw=str(r.get("brand_name_raw") or ""),
        model_name_raw=str(r.get("model_name_raw") or ""),
        model_id=(str(r["model_id"]) if r.get("model_id") else None),
        units=float(r.get("registrations") or 0),
    ) for r in raw_rows]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--period-from", default=None, help="YYYY-MM, inclusive")
    parser.add_argument("--period-to", default=None, help="YYYY-MM, inclusive")
    parser.add_argument("--limit", type=int, default=None,
                        help="max v1 rows to read (for testing a subset)")
    parser.add_argument("--readiness", action="store_true",
                        help="produce the machine-readable cutover-readiness gate "
                             "report instead of a plain parity report")
    parser.add_argument("--required-periods", default=None,
                        help="comma-separated YYYY-MM list; --readiness only. "
                             "A period missing from v2 blocks readiness.")
    parser.add_argument("--json-out", type=Path, default=None)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    required_periods = ([p.strip() for p in args.required_periods.split(",") if p.strip()]
                        if args.required_periods else [])

    try:
        legacy_raw = fetch_legacy_registrations(
            period_from=args.period_from, period_to=args.period_to,
            limit=args.limit)
        v2_observations = fetch_v2_observations()
        v2_facts = fetch_v2_facts()
        crosswalk = fetch_crosswalk()
        serving_state = fetch_serving_state() if args.readiness else None
    except CredentialsError as exc:
        print(f"parity: no server-side Supabase credentials found ({exc}). "
             "Nothing was read. Exiting without a report.", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"parity: live read failed: {exc}", file=sys.stderr)
        return 2

    legacy_rows = adapt_legacy_rows(legacy_raw)
    print(f"parity: {len(legacy_rows)} v1 row(s), {len(v2_observations)} v2 "
         f"observation(s), {len(v2_facts)} v2 fact(s), {len(crosswalk)} "
         "crosswalk entr(ies)", file=sys.stderr)

    if args.readiness:
        boundary = serving_state.get("v2_source_boundary_period")
        report = build_cutover_readiness_report(
            legacy_rows, v2_observations, v2_facts, crosswalk,
            boundary_period=boundary, required_periods=required_periods)
        summary = report.summary()

        print(f"\ncutover readiness (source boundary: {boundary!r}):",
             file=sys.stderr)
        for key, value in summary.items():
            print(f"  {key}: {value}", file=sys.stderr)

        output = {
            "summary": summary,
            "source_lineage_overlaps": summary["source_lineage_overlaps"],
        }
        exit_code = 0 if summary["is_ready_for_cutover"] else 1
        if exit_code:
            print("\nNOT READY for cutover -- see blockers above. "
                 "Never switch reads through a failed/unknown gate.",
                 file=sys.stderr)
        else:
            print("\nREADY for cutover.", file=sys.stderr)
    else:
        report = build_parity_report(legacy_rows, v2_observations, v2_facts, crosswalk)
        summary = report.summary()

        print("\nparity summary:", file=sys.stderr)
        for key, value in summary.items():
            print(f"  {key}: {value}", file=sys.stderr)

        output = {
            "summary": summary,
            "volume_by_period": [
                {"period": v.key, "v1_units": v.v1_units, "v2_units": v.v2_units,
                "matches": v.matches} for v in report.volume_by_period],
            "volume_by_registration_type": [
                {"registration_type": v.key, "v1_units": v.v1_units,
                "v2_units": v.v2_units, "matches": v.matches}
                for v in report.volume_by_registration_type],
            "reconciliation_failures": report.reconciliation_failures,
            "duplicate_source_refs": [list(k) for k in report.duplicate_source_refs],
            "legacy_rows_missing_v2_backfill":
                report.pairing.legacy_rows_missing_v2_backfill,
            "v2_orphaned_backfill_observations":
                report.pairing.v2_orphaned_backfill_observations,
        }
        exit_code = 0

    if args.json_out:
        args.json_out.write_text(json.dumps(output, indent=2, sort_keys=True),
                                 encoding="utf-8")
        print(f"\nwrote JSON report to {args.json_out}", file=sys.stderr)
    else:
        print(json.dumps(output, indent=2, sort_keys=True))

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
