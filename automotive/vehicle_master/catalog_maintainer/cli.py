"""CLI: python -m automotive.vehicle_master.catalog_maintainer.cli simulate ..."""
from __future__ import annotations

import argparse
from .simulator import simulate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="catalog-maintainer")
    sub = parser.add_subparsers(dest="command", required=True)
    sim = sub.add_parser("simulate", help="run deterministic offline fixture planning")
    sim.add_argument("--fixture", required=True)
    sim.add_argument("--out", required=True)
    sim.add_argument("--budget", type=int, default=None)
    args = parser.parse_args(argv)
    if args.command == "simulate":
        result = simulate(args.fixture, args.out, budget=args.budget)
        print(f"MOCK: {result['summary']['planned_items']} planned items; 0 HTTP, 0 paid calls/tokens, 0 writes")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
