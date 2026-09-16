#!/usr/bin/env python3
"""Derive official-media target eligibility from an enriched serving release.

This tool deliberately does not research retail lifecycle itself. It consumes the
same immutable release that serves the product, after retail lifecycle,
MarketTrim reconciliation and row-level source dispositions have already been
applied. Media therefore remains downstream of canonical vehicle truth.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import json
from pathlib import Path
from typing import Any, Mapping

TARGET_CURRENT = "TARGET_CURRENT"
REVIEW_UNVERIFIED = "REVIEW_UNVERIFIED"
EXCLUDE_HISTORICAL = "EXCLUDE_HISTORICAL"
EXCLUDE_NON_MARKET = "EXCLUDE_NON_MARKET"


def _ended_by(value: object, as_of: date) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    try:
        return date.fromisoformat(raw) <= as_of
    except ValueError:
        # Release validation owns malformed dates. The audit must never turn an
        # unreadable lifecycle date into a CURRENT media target.
        return False


def _status_counts(rows: list[Mapping[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get("status") or "UNVERIFIED") for row in rows).items()))


def classify_generation(
    generation: Mapping[str, Any],
    *,
    model: Mapping[str, Any],
    trims: list[Mapping[str, Any]],
    reconciliation: Mapping[str, Any] | None,
    as_of: date,
) -> tuple[str, str]:
    """Classify one Generation without inventing lifecycle evidence.

    Precedence mirrors serving semantics:
    - explicit Model HISTORICAL or ended Generation is historical;
    - an evidence-backed CURRENT Model or MarketTrim makes the live Generation a
      current media target;
    - source reconciliation can explicitly identify a non-market model;
    - an all-historical known trim set is historical;
    - all remaining identities require canonical lifecycle research first.
    """
    model_status = str(model.get("status") or "UNVERIFIED")
    trim_statuses = [str(row.get("status") or "UNVERIFIED") for row in trims]
    reconciliation_status = str((reconciliation or {}).get("status") or "")

    if model_status == "HISTORICAL":
        return EXCLUDE_HISTORICAL, "canonical model retail_status is HISTORICAL"
    if _ended_by(generation.get("ended"), as_of):
        return EXCLUDE_HISTORICAL, "canonical generation ended on/before release as_of"

    if model_status == "CURRENT":
        return TARGET_CURRENT, "canonical model retail_status is CURRENT"
    if "CURRENT" in trim_statuses:
        return TARGET_CURRENT, "at least one canonical MarketTrim is CURRENT"

    if reconciliation_status == "NON_MARKET":
        return EXCLUDE_NON_MARKET, "trim reconciliation marks source model NON_MARKET"

    if trim_statuses and all(status == "HISTORICAL" for status in trim_statuses):
        return EXCLUDE_HISTORICAL, "all canonical MarketTrims for generation are HISTORICAL"

    return REVIEW_UNVERIFIED, "no canonical evidence currently proves retail CURRENT or HISTORICAL"


def audit_release(release: Mapping[str, Any]) -> dict[str, Any]:
    as_of = date.fromisoformat(str(release.get("as_of") or ""))
    models = {
        str(row.get("canonical_id") or ""): row
        for row in release.get("models", [])
        if isinstance(row, Mapping)
    }
    trims_by_generation: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in release.get("market_trims", []):
        if isinstance(row, Mapping):
            trims_by_generation[str(row.get("generation_id") or "")].append(row)
    reconciliation_by_model = {
        str(row.get("model_id") or ""): row
        for row in (release.get("trim_reconciliation") or {}).get("models", [])
        if isinstance(row, Mapping)
    }

    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    brand_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for generation in release.get("generations", []):
        if not isinstance(generation, Mapping):
            continue
        generation_id = str(generation.get("canonical_id") or "")
        model_id = str(generation.get("model_id") or "")
        model = models.get(model_id)
        if not generation_id or model is None:
            continue
        trims = trims_by_generation.get(generation_id, [])
        reconciliation = reconciliation_by_model.get(model_id)
        disposition, reason = classify_generation(
            generation,
            model=model,
            trims=trims,
            reconciliation=reconciliation,
            as_of=as_of,
        )
        brand_id = str(model.get("brand_id") or "")
        counts[disposition] += 1
        brand_counts[brand_id][disposition] += 1
        rows.append({
            "generation_id": generation_id,
            "model_id": model_id,
            "brand_id": brand_id,
            "model_name": model.get("name_en"),
            "model_status": model.get("status") or "UNVERIFIED",
            "generation_started": generation.get("started"),
            "generation_ended": generation.get("ended"),
            "trim_status_counts": _status_counts(trims),
            "reconciliation_status": (reconciliation or {}).get("status"),
            "reconciliation_unresolved_rows": int(
                (reconciliation or {}).get("unresolved_source_trim_count") or 0
            ),
            "media_disposition": disposition,
            "reason": reason,
        })

    rows.sort(key=lambda row: (row["brand_id"], row["model_name"] or "", row["generation_id"]))
    return {
        "schema_version": 1,
        "release_id": release.get("release_id"),
        "canonical_revision": release.get("canonical_revision"),
        "source_hash": release.get("source_hash"),
        "as_of": release.get("as_of"),
        "counts": dict(sorted(counts.items())),
        "brand_counts": {
            brand: dict(sorted(values.items()))
            for brand, values in sorted(brand_counts.items())
        },
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--targets-out", type=Path)
    args = parser.parse_args(argv)

    release = json.loads(args.release.read_text(encoding="utf-8"))
    report = audit_release(release)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    targets = [
        row["generation_id"] for row in report["rows"]
        if row["media_disposition"] == TARGET_CURRENT
    ]
    if args.targets_out:
        args.targets_out.parent.mkdir(parents=True, exist_ok=True)
        args.targets_out.write_text("".join(f"{target}\n" for target in targets), encoding="utf-8")

    print(json.dumps({
        "release_id": report["release_id"],
        "canonical_revision": report["canonical_revision"],
        "counts": report["counts"],
        "target_current": len(targets),
        "out": str(args.out),
        "targets_out": str(args.targets_out) if args.targets_out else None,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
