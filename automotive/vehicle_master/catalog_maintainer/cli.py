"""CLI: python -m automotive.vehicle_master.catalog_maintainer.cli simulate ..."""
from __future__ import annotations

import argparse
from .simulator import simulate
from .replay import replay


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
    args = parser.parse_args(argv)
    if args.command == "simulate":
        result = simulate(args.fixture, args.out, budget=args.budget)
        print(f"MOCK: {result['summary']['planned_items']} planned items; 0 HTTP, 0 paid calls/tokens, 0 writes")
        return 0
    if args.command == "replay":
        result = replay(args.fixture, args.documents, args.out)
        print(f"REPLAY: {result['accepted_candidates']} accepted candidates; 0 HTTP, 0 paid calls/tokens, 0 writes")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
