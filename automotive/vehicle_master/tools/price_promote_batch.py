#!/usr/bin/env python3
"""Turn reviewed P5 candidates into a validated canonical market-file plan.

Dry-run is the default.  ``--apply`` writes only ``vehreg/data/<year>/market``
files after the complete in-memory ledger validates.  It never commits, pushes,
opens a PR, or publishes Supabase serving data; ``price_promotion_pr.py`` wraps
this command for the Git branch/PR step.

Required inputs:

* ``--candidate-state``: P5 CandidateBook JSON
* ``--reconcile``: P5 reconcile report from the same/latest run
* ``--fetch``: P4 fetch batch, used to retain the exact source URL
* ``--review``: HUMAN approval/rejection bundle; may also create reviewed
  campaign identities used by bound campaign/finance candidates
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehreg.catalog import DATA_DIR, DEFAULT_YEAR  # noqa: E402
from vehreg.price_promote import (  # noqa: E402
    PromotionError,
    build_promotion_plan,
    load_promotion_bundle,
)
from vehreg.price_reconcile import CandidateBook  # noqa: E402


def _load(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise PromotionError(f"{path}: root must be an object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--candidate-state", type=Path, required=True)
    parser.add_argument("--reconcile", type=Path, required=True)
    parser.add_argument("--fetch", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--manifest-out", type=Path, default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    book = CandidateBook.from_payload(_load(args.candidate_state))
    reconcile = _load(args.reconcile)
    fetch = _load(args.fetch)
    decisions, campaigns = load_promotion_bundle(args.review)

    plan = build_promotion_plan(
        data_dir=args.data_dir,
        year=args.year,
        candidate_book=book,
        reconcile_report=reconcile,
        fetch_batch=fetch,
        decisions=decisions,
        create_campaigns=campaigns,
    )
    manifest = plan.manifest(args.data_dir)
    manifest["applied"] = bool(args.apply)
    if args.apply:
        plan.apply()
    if args.manifest_out:
        args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_out.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
