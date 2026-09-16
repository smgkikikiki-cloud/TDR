"""Build the canonical TDR release with retail and serving enrichment.

The base ReleaseBuilder remains the owner of analytical catalog identity,
price/spec facts and TDR crosswalks. Dedicated retail MarketTrim identity is
merged from ``market/trims/canonical.json`` before lifecycle is evaluated. The
resulting retail set, lifecycle state, historical registration projection and
reconciliation report are all part of the immutable release hash.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from vehreg.catalog import DATA_DIR, DEFAULT_YEAR
from vehreg.trim_reconciliation import (
    apply_canonical_trim_overlay,
    release_reconciliation_report,
)
from tdr_bridge.historical_state import build_historical_model_state
from tdr_bridge.lifecycle import apply_retail_lifecycle
from tdr_bridge.release import ReleaseBuilder

SEMANTIC_KEYS = (
    "schema_version",
    "year",
    "canonical_revision",
    "as_of",
    "brands",
    "models",
    "generations",
    "market_trims",
    "price_ledger",
    "spec_facts",
    "historical_model_state",
    "trim_reconciliation",
)


def enrich_release(
    release: dict,
    *,
    data_dir: Path | str = DATA_DIR,
    source_aliases: dict[str, str] | None = None,
) -> dict:
    year = int(release.get("year") or DEFAULT_YEAR)

    # Retail MarketTrim is intentionally a separate authoring grain from the
    # analytical registration Variant catalog. Merge the dedicated canonical
    # retail store first so lifecycle and reconciliation operate on the exact
    # payload that will be published.
    out = apply_canonical_trim_overlay(release, data_dir=data_dir, year=year)

    # Canonical identity and "orderable today" are separate claims. Lifecycle
    # remains fail-closed after the overlay is present.
    out = apply_retail_lifecycle(out, data_dir=data_dir, year=year)
    out["historical_model_state"] = build_historical_model_state(
        data_dir=data_dir,
        source_aliases=source_aliases,
    )

    # Every source row must either be represented by a canonical source-backed
    # MarketTrim or remain explicitly unresolved/non-market/historical. Partial
    # silent loss blocks publication just like total silent loss.
    out["trim_reconciliation"] = release_reconciliation_report(
        out, data_dir=data_dir, year=year,
    )
    blockers = out["trim_reconciliation"].get("blockers", [])
    if blockers:
        sample = ", ".join(
            f"{row.get('model_id')}:{row.get('blocker')}" for row in blockers[:5]
        )
        more = f" (+{len(blockers) - 5} more)" if len(blockers) > 5 else ""
        raise ValueError(
            "MarketTrim reconciliation blocks serving release: " + sample + more
        )

    semantic = {key: out[key] for key in SEMANTIC_KEYS}
    source_hash = sha256(json.dumps(
        semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    out["source_hash"] = source_hash
    out["release_id"] = f"vehicle-{out['year']}-{source_hash[:16]}"
    out["created_at"] = datetime.now(timezone.utc).isoformat()
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--revision", default="working-tree")
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--overrides", type=Path)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    overrides = (json.loads(args.overrides.read_text(encoding="utf-8"))
                 if args.overrides else {})
    release = ReleaseBuilder(
        inventory,
        data_dir=args.data_dir,
        year=args.year,
        canonical_revision=args.revision,
        overrides=overrides,
    ).build(as_of=args.as_of)
    release = enrich_release(
        release,
        data_dir=args.data_dir,
        source_aliases=overrides.get("source_aliases", {}),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "release_id": release["release_id"],
        "source_hash": release["source_hash"],
        "counts": release["counts"],
        "historical_years": release["historical_model_state"]["catalog_years"],
        "historical_baselines": len(release["historical_model_state"]["model_year_baselines"]),
        "historical_changes": len(release["historical_model_state"]["monthly_changes"]),
        "aliased_historical_rows": release["historical_model_state"]["aliased_seed_rows"],
        "trim_reconciliation": release["trim_reconciliation"]["counts"],
        "output": str(args.out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
