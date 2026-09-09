#!/usr/bin/env python3
"""Apply reviewed P6 promotion and open a guarded GitHub price-data PR.

This operator tool is intentionally conservative. It requires ``git`` and the
GitHub CLI (``gh``) to already be authenticated. It will not run on a dirty
working tree. The sequence is:

1. fetch the latest configured base branch and create a fresh pricebot branch;
2. run ``price_promote_batch.py --apply``;
3. commit the market-only diff locally;
4. run pricefeed_guard, full Vehicle Master tests, market validate, and a
   serving-projection dry-run for every affected model;
5. only then push and open the PR.

A failed guard/test leaves the local branch for inspection and never pushes it.
Human PR merge remains the publication gate.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys

ENGINE = Path(__file__).resolve().parent.parent
REPO = ENGINE.parent.parent


def _run(args: list[str], *, cwd: Path = REPO, capture: bool = False) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=capture,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip() if capture else ""
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}"
                           + (f"\n{detail}" if detail else ""))
    return result.stdout.strip() if capture else ""


def _clean() -> None:
    status = _run(["git", "status", "--porcelain"], capture=True)
    if status:
        raise RuntimeError("working tree must be clean before opening a price PR")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _branch_default() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    return f"pricebot/{stamp}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--candidate-state", type=Path, required=True)
    parser.add_argument("--reconcile", type=Path, required=True)
    parser.add_argument("--fetch", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument(
        "--base", default=None,
        help="explicit git revision to branch/guard from; default is freshly fetched <remote>/<base-branch>",
    )
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--branch", default=None)
    parser.add_argument("--title", default="Price intelligence: reviewed price promotion")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--max-offers", type=int, default=25)
    parser.add_argument("--max-move", type=float, default=25.0)
    args = parser.parse_args(argv)

    if shutil.which("git") is None:
        raise RuntimeError("git is required")
    if shutil.which("gh") is None:
        raise RuntimeError("GitHub CLI (gh) is required to open the PR")
    _run(["gh", "auth", "status"], capture=True)
    _clean()

    # A stale local remote-tracking ref defeats P6's canonical freshness checks:
    # the bot would validate against yesterday's main and only discover the
    # conflict after pushing. Refresh the base before any market file is read.
    _run(["git", "fetch", "--no-tags", args.remote, args.base_branch])
    base = args.base or f"{args.remote}/{args.base_branch}"
    branch = args.branch or _branch_default()
    _run(["git", "switch", "--create", branch, base])
    manifest = ENGINE / ".pricebot-promotion-manifest.json"
    try:
        promote = [
            sys.executable,
            str(ENGINE / "tools" / "price_promote_batch.py"),
            "--candidate-state", str(args.candidate_state.resolve()),
            "--reconcile", str(args.reconcile.resolve()),
            "--fetch", str(args.fetch.resolve()),
            "--review", str(args.review.resolve()),
            "--year", str(args.year),
            "--manifest-out", str(manifest),
            "--apply",
        ]
        _run(promote, cwd=ENGINE)
        payload = _read(manifest)
        promoted = payload.get("items") or []
        if not promoted:
            raise RuntimeError("promotion plan contains no approved price writes")

        # Only market data produced by P6 is staged. The temporary manifest is
        # deliberately excluded from the commit.
        _run(["git", "add", f"automotive/vehicle_master/vehreg/data/{args.year}/market"])
        staged = _run(["git", "diff", "--cached", "--name-only"], capture=True)
        if not staged:
            raise RuntimeError("P6 produced no canonical market diff")
        _run(["git", "commit", "-m", f"Promote {len(promoted)} reviewed price candidate(s)"])

        _run([
            sys.executable, "tools/pricefeed_guard.py",
            "--base", base,
            "--year", str(args.year),
            "--max-offers", str(args.max_offers),
            "--max-move", str(args.max_move),
        ], cwd=ENGINE)
        _run([sys.executable, "-m", "pytest", "-q"], cwd=ENGINE)
        _run([sys.executable, "-m", "vehreg", "market", "validate"], cwd=ENGINE)
        for model_id in payload.get("affected_model_ids") or []:
            _run([
                sys.executable,
                "scripts/publish_serving_projection.py",
                model_id,
                "--year", str(args.year),
                "--compact",
            ], cwd=ENGINE)

        _run(["git", "push", "--set-upstream", args.remote, branch])
        lines = [
            "Reviewed P6 price promotion.",
            "",
            "Promotion remains human-merge gated; this PR does not publish serving data.",
            "",
            "Promoted candidates:",
        ]
        for item in promoted:
            lines.append(
                f"- `{item['candidate_id']}` — {item['trim_id']} "
                f"{item['price_type']} {int(item['amount_thb']):,} THB "
                f"({item['disposition']})"
            )
        lines.extend([
            "",
            "Local pre-push gates passed:",
            "- fresh base fetch",
            "- pricefeed_guard",
            "- full Vehicle Master pytest",
            "- market validate",
            "- serving projection dry-run for affected models",
        ])
        body = "\n".join(lines)
        url = _run([
            "gh", "pr", "create",
            "--base", args.base_branch,
            "--head", branch,
            "--title", args.title,
            "--body", body,
        ], capture=True)
        print(url)
        return 0
    finally:
        manifest.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
