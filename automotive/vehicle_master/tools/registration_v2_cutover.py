#!/usr/bin/env python3
"""The registration serving cutover switch: legacy <-> v2, and the
source-ownership boundary. Never cut over through a failed/unknown parity
gate - run `tools/registration_v2_parity.py --readiness` first.

    python tools/registration_v2_cutover.py --status
    python tools/registration_v2_cutover.py --set-boundary 2026-08
    python tools/registration_v2_cutover.py --switch v2
    python tools/registration_v2_cutover.py --switch legacy            # rollback

Wraps `set_registration_serving_source`/`set_registration_v2_source_boundary`
(`supabase/migration_v31_registration_v2_serving_and_cutover.sql`) - each a
single, atomic `UPDATE` of one row. Switching `--switch legacy` is the
rollback path: it requires no data reconstruction, since
`registration_reporting_source`'s legacy branch reads `public.registrations`
directly and that table is never touched by any part of the v2 pipeline or
this switch.

This tool performs no readiness check itself - it is a dumb, honest switch,
by design (so the switch and the gate stay two separately-auditable steps,
never coupled into one command an operator could run half-attentively). The
operator is responsible for having run `tools/registration_v2_parity.py
--readiness` and confirmed `is_ready_for_cutover: true` immediately before
`--switch v2`.

Requires the same server-side credentials as every other Supabase-writing
tool in this repository.

Exit 0: the requested read/write succeeded.
Exit 2: could not run at all (no credentials, invalid argument, request
failure).
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.backfill_registration_v2 import CredentialsError, _request  # noqa: E402
from tools.registration_v2_parity import fetch_serving_state  # noqa: E402


def set_serving_source(source: str, *, switched_by: Optional[str] = None) -> dict:
    rows = _request(
        "POST", "rpc/set_registration_serving_source",
        {"p_source": source, "p_switched_by": switched_by or getpass.getuser()},
    )
    return rows[0] if isinstance(rows, list) else rows


def set_source_boundary(boundary_period: Optional[str]) -> dict:
    rows = _request(
        "POST", "rpc/set_registration_v2_source_boundary",
        {"p_boundary_period": boundary_period},
    )
    return rows[0] if isinstance(rows, list) else rows


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true",
                       help="print the current active_source/boundary and exit")
    group.add_argument("--switch", choices=("legacy", "v2"),
                       help="atomically switch registration_reporting_source's "
                            "source. 'legacy' is the rollback path.")
    group.add_argument("--set-boundary",
                       help="YYYY-MM, or 'none' to clear it (every period reverts "
                            "to legacy_registrations_backfill-authoritative)")
    parser.add_argument("--json-out", type=Path, default=None)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)

    try:
        if args.status:
            result = fetch_serving_state()
        elif args.switch:
            print(f"cutover: switching active_source -> {args.switch!r}...",
                 file=sys.stderr)
            result = set_serving_source(args.switch)
            print(f"cutover: done. Rollback: rerun with "
                 f"--switch {'legacy' if args.switch == 'v2' else 'v2'} "
                 "(no data reconstruction required).", file=sys.stderr)
        else:
            boundary = None if args.set_boundary.lower() == "none" else args.set_boundary
            print(f"cutover: setting v2 source boundary -> {boundary!r}...",
                 file=sys.stderr)
            result = set_source_boundary(boundary)
            print("cutover: done.", file=sys.stderr)
    except CredentialsError as exc:
        print(f"cutover: no server-side Supabase credentials found ({exc}). "
             "Nothing was read or written.", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"cutover: request failed: {exc}", file=sys.stderr)
        return 2

    if args.json_out:
        args.json_out.write_text(json.dumps(result, indent=2, sort_keys=True, default=str),
                                 encoding="utf-8")
        print(f"wrote JSON result to {args.json_out}", file=sys.stderr)
    else:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
