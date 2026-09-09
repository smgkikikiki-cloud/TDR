#!/usr/bin/env python3
"""CI brake for an automated price PR: what a harvester is allowed to change.

A run that wants to rewrite fifty prices has a broken extractor, not fifty
announcements. This refuses the PR instead of merging it.

Checks, in order:

1. every changed file is under ``market/`` -- no code, catalog or warehouse;
2. the ledger and campaigns still validate against the catalog;
3. no more than ``--max-offers`` current list prices changed in one PR;
4. every trim that already had a current list price still has one, and any
   change to an existing price is inside ``--max-move`` percent.

The guard runs from ``automotive/vehicle_master`` in the consolidated repo. Git
object paths, however, are always repository-root-relative. The helper below
uses ``git rev-parse --show-prefix`` so base-revision reads continue working
after consolidation instead of silently returning an empty pre-change ledger.

Run it against the base revision:

    python tools/pricefeed_guard.py --base origin/main
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR  # noqa: E402
from vehreg.pricing import PriceLedger  # noqa: E402

ALLOWED_PREFIX = "vehreg/data/{year}/market/"


def _git(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def _repo_prefix() -> str:
    """Path from repository root to the current working directory."""
    prefix = _git(["rev-parse", "--show-prefix"]).stdout.strip()
    return prefix.rstrip("/")


def _repo_path(relative: str) -> str:
    prefix = _repo_prefix()
    clean = relative.lstrip("/")
    return f"{prefix}/{clean}" if prefix else clean


def changed_files(base: str) -> list[str]:
    # --relative makes this deterministic from the engine directory; the allow
    # list below is deliberately expressed in engine-relative paths.
    out = _git(["diff", "--name-only", "--relative", f"{base}...HEAD"])
    return [line for line in out.stdout.splitlines() if line.strip()]


def _list_price_rows_at(revision: str, year: int) -> list[dict]:
    folder = _repo_path(f"vehreg/data/{year}/market/prices")
    listed = _git(["ls-tree", "-r", "--name-only", revision, "--", folder], check=False)
    if listed.returncode != 0:
        return []
    rows: list[dict] = []
    for path in listed.stdout.splitlines():
        path = path.strip()
        if not path.endswith(".json"):
            continue
        blob = _git(["show", f"{revision}:{path}"], check=False)
        if blob.returncode != 0:
            continue
        try:
            payload = json.loads(blob.stdout)
        except json.JSONDecodeError:
            continue
        for row in payload.get("prices", []):
            if isinstance(row, dict) and row.get("price_type") == "LIST_PRICE":
                rows.append(row)
    return rows


def _resolve_current_list(rows: list[dict], *, as_of: date) -> dict[str, int]:
    """Resolve current list price per trim using the ledger's latest-start rule."""
    day = as_of.isoformat()
    by_trim: dict[str, list[dict]] = {}
    for row in rows:
        trim_id = str(row.get("trim_id") or "")
        if not trim_id or row.get("retracted_at"):
            continue
        start = row.get("effective_from") or row.get("observed_at")
        if not start or start > day:
            continue
        by_trim.setdefault(trim_id, []).append(row)

    out: dict[str, int] = {}
    for trim_id, candidates in by_trim.items():
        latest_start = max(row.get("effective_from") or row.get("observed_at")
                           for row in candidates)
        latest = [row for row in candidates
                  if (row.get("effective_from") or row.get("observed_at")) == latest_start]
        active = [row for row in latest
                  if not row.get("effective_to") or row.get("effective_to") >= day]
        amounts = {int(row["amount_thb"]) for row in active if row.get("amount_thb") is not None}
        if len(amounts) > 1:
            raise ValueError(
                f"{trim_id}: base revision has conflicting LIST_PRICE at {latest_start}")
        if amounts:
            out[trim_id] = next(iter(amounts))
    return out


def ledger_at(revision: str, year: int, *, as_of: date | None = None) -> dict[str, int]:
    """trim_id -> current list price at one git revision."""
    return _resolve_current_list(_list_price_rows_at(revision, year),
                                 as_of=as_of or date.today())


def check(base: str, *, year: int, data_dir: Path,
          max_offers: int, max_move: float) -> list[str]:
    problems: list[str] = []
    allowed = ALLOWED_PREFIX.format(year=year)
    for path in changed_files(base):
        if not path.startswith(allowed):
            problems.append(f"{path}: outside {allowed}; a price PR changes data only")

    catalog = Catalog.load(data_dir, year)
    ledger = PriceLedger.load(data_dir, year=year, catalog=catalog)
    problems.extend(ledger.validate())

    try:
        before = ledger_at(base, year)
    except ValueError as exc:
        problems.append(str(exc))
        before = {}
    after = {trim_id: row.amount_thb for trim_id in {r.trim_id for r in ledger.records}
             for row in [ledger.current_list_price(trim_id, as_of=date.today())]
             if row is not None}

    moved = {trim_id for trim_id in set(before) | set(after)
             if before.get(trim_id) != after.get(trim_id)}
    if len(moved) > max_offers:
        problems.append(
            f"{len(moved)} list prices change in one PR (limit {max_offers}); "
            "this is an extractor fault, not that many announcements")
    for trim_id in sorted(moved):
        old, new = before.get(trim_id), after.get(trim_id)
        if old is not None and new is None:
            problems.append(f"{trim_id}: had a current list price, now has none")
        elif old and new and abs(new - old) / old * 100 > max_move:
            problems.append(
                f"{trim_id}: list price moves {old:,} -> {new:,} "
                f"({abs(new - old) / old * 100:.1f}% > {max_move}%); needs a person")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--max-offers", type=int, default=25)
    parser.add_argument("--max-move", type=float, default=25.0,
                        help="percent a single list price may move unattended")
    args = parser.parse_args(argv)
    problems = check(args.base, year=args.year, data_dir=args.data_dir,
                     max_offers=args.max_offers, max_move=args.max_move)
    if problems:
        print("price PR refused:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("price PR is within limits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
