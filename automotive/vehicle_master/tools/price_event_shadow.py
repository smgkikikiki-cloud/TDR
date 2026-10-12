#!/usr/bin/env python3
"""PEE-2: run the offline shadow evaluation and write reproducible artifacts.

Replays prerecorded fixtures through the unchanged PEE-1 engine with a scripted
replay provider. No network, no real model, no Price Ledger or Supabase write;
the only files written are the four report artifacts under ``--out``.

    python tools/price_event_shadow.py --out docs/price-intelligence/pee2
    python tools/price_event_shadow.py --out docs/price-intelligence/pee2 --check

``--check`` regenerates in memory and exits 1 if the stored artifacts differ.
``--enforce`` exits 2 if any proposed *regression* gate fails. That is not a
readiness verdict: the report and the JSON output carry a separate
``readiness`` status, which stays BLOCKED without owner-labelled,
permission-cleared evidence and explicit owner authorization.
Token prices are never assumed: pass ``--in-per-mtok`` and ``--out-per-mtok``
together for a what-if cost line.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehreg.price_event_shadow import (  # noqa: E402
    ARTIFACT_NAMES as ARTIFACTS,
    FIXTURE_DIR,
    estimate_cost,
    render_artifacts,
    run_corpus,
)


def build(fixtures: Path, in_price, out_price) -> tuple[dict[str, str], dict]:
    result = run_corpus(fixtures)
    cost = estimate_cost(result["summary"]["usage"], in_per_mtok=in_price,
                         out_per_mtok=out_price)
    return render_artifacts(result, cost=cost), result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixtures", type=Path, default=FIXTURE_DIR)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--check", action="store_true",
                        help="compare with stored artifacts instead of writing")
    parser.add_argument("--enforce", action="store_true",
                        help="exit 2 when a proposed safety gate fails")
    parser.add_argument("--in-per-mtok", type=float, default=None)
    parser.add_argument("--out-per-mtok", type=float, default=None)
    args = parser.parse_args(argv)
    if (args.in_per_mtok is None) != (args.out_per_mtok is None):
        parser.error("--in-per-mtok and --out-per-mtok must be given together")

    artifacts, result = build(args.fixtures, args.in_per_mtok, args.out_per_mtok)
    failed = [name for name, gate in result["summary"]["gates"].items() if not gate["pass"]]
    readiness = result["readiness"]["status"]

    if args.check:
        drift = [name for name in ARTIFACTS
                 if not (args.out / name).is_file()
                 or (args.out / name).read_text(encoding="utf-8") != artifacts[name]]
        print(json.dumps({"drift": drift, "failed_gates": failed,
                          "readiness": readiness}, indent=2))
        return 1 if drift else (2 if failed and args.enforce else 0)

    args.out.mkdir(parents=True, exist_ok=True)
    for name in ARTIFACTS:
        (args.out / name).write_text(artifacts[name], encoding="utf-8")
    print(json.dumps({"written": [str(args.out / n) for n in ARTIFACTS],
                      "failed_gates": failed, "readiness": readiness}, indent=2))
    return 2 if failed and args.enforce else 0


if __name__ == "__main__":
    raise SystemExit(main())
