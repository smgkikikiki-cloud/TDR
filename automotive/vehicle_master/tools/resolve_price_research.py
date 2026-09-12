"""Resolve first-pass price gaps without weakening the source policy.

CONFLICT rows are checked against Car250 as a third Thai automotive source.
Missing primary-source hits get one relaxed-query retry on the same source.
No value is invented and no row is promoted to the Price Ledger here.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
from pathlib import Path
from typing import Any

from research_catalog_prices import (
    SOURCES,
    preferred_amounts,
    search_source,
)


THIRD = ("car250", "https://www.car250.com")


def resolve(row: dict[str, Any]) -> dict[str, Any]:
    row = json.loads(json.dumps(row, ensure_ascii=False))
    left = row["preferred_amounts_thb"]["autolifethailand"]
    right = row["preferred_amounts_thb"]["headlightmag"]

    if row["disposition"] == "CONFLICT":
        third = search_source(THIRD[0], THIRD[1], row)
        row["evidence"][THIRD[0]] = third
        third_amounts = preferred_amounts(third)
        row["preferred_amounts_thb"][THIRD[0]] = third_amounts
        if third_amounts and third_amounts == left:
            row["disposition"] = "RESOLVED_THIRD_MATCH_AUTOLIFE"
        elif third_amounts and third_amounts == right:
            row["disposition"] = "RESOLVED_THIRD_MATCH_HEADLIGHT"
        elif third_amounts:
            row["disposition"] = "THIRD_CONFLICT"
        else:
            row["disposition"] = "THIRD_NOT_FOUND"
        return row

    # A relaxed search is allowed only to locate evidence on the same two
    # preferred publications.  It does not relax the two-source decision rule.
    if row["disposition"] in {"ONE_SOURCE", "NOT_FOUND"}:
        for source, base in SOURCES.items():
            if row["preferred_amounts_thb"].get(source):
                continue
            retry_row = dict(row)
            retry_row["brand"] = ""
            retry = search_source(source, base, retry_row)
            retry["query_kind"] = "relaxed_model_name"
            retry_amounts = preferred_amounts(retry)
            if retry_amounts:
                row["evidence"][source] = retry
                row["preferred_amounts_thb"][source] = retry_amounts

        left = row["preferred_amounts_thb"]["autolifethailand"]
        right = row["preferred_amounts_thb"]["headlightmag"]
        if left and right:
            row["disposition"] = "AGREE" if left == right else "CONFLICT_AFTER_RETRY"
        elif left or right:
            row["disposition"] = "ONE_SOURCE"
        else:
            row["disposition"] = "NOT_FOUND"
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    work = [row for row in payload["results"] if row["disposition"] != "AGREE"]
    untouched = [row for row in payload["results"] if row["disposition"] == "AGREE"]
    resolved: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(resolve, row): row for row in work}
        for done, future in enumerate(concurrent.futures.as_completed(futures), 1):
            row = future.result()
            resolved.append(row)
            print(f"[{done}/{len(work)}] {row['model_id']}: {row['disposition']}", flush=True)

    results = sorted(untouched + resolved, key=lambda row: row["model_id"])
    summary: dict[str, int] = {}
    for row in results:
        summary[row["disposition"]] = summary.get(row["disposition"], 0) + 1
    payload["summary"] = summary
    payload["results"] = results
    payload["resolution_policy"] = {
        "conflict_third_source": THIRD[0],
        "missing_primary_retry": "model name without brand",
    }
    out = args.out or args.input.with_name(args.input.stem + "_resolved.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "summary": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
