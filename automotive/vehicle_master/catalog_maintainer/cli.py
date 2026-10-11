"""CLI: python -m automotive.vehicle_master.catalog_maintainer.cli simulate ..."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from .simulator import simulate
from .replay import replay
from .retail_reconcile import reconcile_retail_lineup
from .validation import validate_fixture, validate_policy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="catalog-maintainer")
    sub = parser.add_subparsers(dest="command", required=True)
    sim = sub.add_parser("simulate", help="run deterministic offline fixture planning")
    sim.add_argument("--fixture", required=True)
    sim.add_argument("--out", required=True)
    sim.add_argument("--budget", type=int, default=None)
    rep = sub.add_parser("replay", help="replay recorded local evidence without network/provider access")
    rep.add_argument("--fixture", required=True)
    rep.add_argument("--documents", required=True, nargs="+")
    rep.add_argument("--out", required=True)
    retail = sub.add_parser("retail-reconcile", help="validate and diff a recorded Thai retail lineup offline")
    retail.add_argument("--fixture", required=True)
    retail.add_argument("--document", required=True)
    retail.add_argument("--policy", default=str(Path(__file__).parent / "contract" / "policy.yaml"))
    retail.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.command == "simulate":
        result = simulate(args.fixture, args.out, budget=args.budget)
        print(f"MOCK: {result['summary']['planned_items']} planned items; 0 HTTP, 0 paid calls/tokens, 0 writes")
        return 0
    if args.command == "replay":
        result = replay(args.fixture, args.documents, args.out)
        print(f"REPLAY: {result['accepted_candidates']} accepted candidates; 0 HTTP, 0 paid calls/tokens, 0 writes")
        return 0
    if args.command == "retail-reconcile":
        snapshot = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        document = json.loads(Path(args.document).read_text(encoding="utf-8"))
        policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
        validate_fixture(snapshot)
        validate_policy(policy)
        result = reconcile_retail_lineup(snapshot, document, policy=policy)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(f"RETAIL REPLAY: {len(result['outcomes'])} outcomes; 0 HTTP, 0 paid calls/tokens, 0 writes")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
