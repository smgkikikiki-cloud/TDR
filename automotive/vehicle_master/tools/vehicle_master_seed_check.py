"""Check the Vehicle DB v3 master tables against the release they were seeded from.

    python -m tools.vehicle_master_seed_check [--json]

Read-only. Calls ``vehicle_master_seed_check()`` (migration_v57), which compares
the master tables with the pinned release's projections -- row counts, ids in
both directions, and every served column/payload -- checks the integrity of
the supplemental rows, and reports the preserved state the release does not
serve (variants, overlay trims, retracted prices, campaigns/options, unserved
spec-fact history, ECO evidence, sidecars, legacy ids).

Exit status 1 when any non-report check fails, including when the pinned
release is no longer the active one (the master then needs reconciling
before step 3's parity test means anything).
"""

from __future__ import annotations

import argparse
import json
import sys

from tdr_bridge.publish import _rpc
from tools.vehicle_master_seed import _env


def format_rows(rows: list[dict]) -> str:
    lines = [f"{'kind':<10} {'section':<26} {'check':<38} {'expected':>9} {'actual':>9}  ok"]
    for row in rows:
        expected = "" if row.get("expected") is None else str(row["expected"])
        lines.append(f"{row['kind']:<10} {row['section']:<26} {row['check_name']:<38} "
                     f"{expected:>9} {row['actual']!s:>9}  {'ok' if row['ok'] else 'FAIL'}")
    return "\n".join(lines)


def failures(rows: list[dict]) -> list[dict]:
    return [row for row in rows if not row["ok"]]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="print the raw rows as JSON")
    args = parser.parse_args(argv)
    url, key = _env()
    rows = _rpc("vehicle_master_seed_check", {}, url=url, service_key=key)
    print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else format_rows(rows))
    failed = failures(rows)
    if failed:
        print(f"\n{len(failed)} check(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
