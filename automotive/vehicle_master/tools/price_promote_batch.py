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
    PromotionAction,
    PromotionError,
    PromotionPlan,
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


def _refuse_multiple_current_approvals(book: CandidateBook, decisions: dict) -> None:
    """One bot PR may select at most one current truth per canonical stream.

    Historical candidates carry explicit closed windows and may coexist. For
    current candidates, two HUMAN approval rows do not authorize the bot to
    decide chronology/source precedence between them.
    """
    selected: dict[tuple, str] = {}
    for candidate_id, decision in decisions.items():
        if decision.action is not PromotionAction.APPROVE:
            continue
        candidate = book.candidates.get(candidate_id)
        if candidate is None or candidate.historical_only:
            continue
        key = (
            candidate.trim_id,
            candidate.price_type.value,
            candidate.campaign_id or "",
            candidate.option_id or "",
        )
        previous = selected.get(key)
        if previous is not None and previous != candidate_id:
            raise PromotionError(
                "multiple approved current candidates target the same canonical "
                f"stream: {previous} and {candidate_id}; choose one or rerun review"
            )
        selected[key] = candidate_id


def _apply_with_rollback(plan: PromotionPlan) -> None:
    """Restore the pre-apply working tree if an ordinary filesystem write fails."""
    before: dict[Path, bytes | None] = {}
    for planned in plan.files:
        before[planned.path] = planned.path.read_bytes() if planned.path.exists() else None
    try:
        plan.apply()
    except Exception:
        for path, payload in before.items():
            if payload is None:
                path.unlink(missing_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        raise


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
    _refuse_multiple_current_approvals(book, decisions)

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
        _apply_with_rollback(plan)
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
