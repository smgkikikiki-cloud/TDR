"""Run the current Contract v1 evaluator on real recorded evidence or one snapshot.

Examples (from automotive/vehicle_master):
  python -m identity_resolution.engine.cli --snapshot /tmp/ir-snapshot.json --out /tmp/ir-result.json
  python -m identity_resolution.engine.cli --archived-m7 --out /tmp/ir-m7-result.json

This makes no HTTP, Production DB call, database write or mapping approval.
The archived M7.0 mode reads a locally present, SHA-256-pinned Ice ZIP and
the repo's previously captured read-only R6 extract; no network fallback.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from identity_resolution.engine.runner import run_snapshot


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--snapshot", type=Path, help="provider-neutral contract/v1 record.schema.json snapshot")
    src.add_argument("--archived-m7", action="store_true", help="use SHA-256-pinned local Ice M7.0 archive and R6 extracts")
    p.add_argument("--out", type=Path, required=True, help="write a read-only QA report JSON, never a canonical file")
    args = p.parse_args(argv)
    try:
        if args.archived_m7:
            from identity_resolution.calibration import adapters
            snapshot = adapters.build_snapshot(
                adapters.load_ice_package(), adapters.load_extracts())
        else:
            snapshot = json.loads(args.snapshot.read_text(encoding="utf-8-sig"))
        report = run_snapshot(snapshot)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True,
                       allow_nan=False) + "\n",
            encoding="utf-8")
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(f"IR_OFFLINE_SMOKE_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": report["status"], "snapshot_sha256": report["snapshot_sha256"],
                      "summary": report["summary"], "out": str(args.out)},
                     ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "EVALUATED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
