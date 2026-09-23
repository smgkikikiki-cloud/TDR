#!/usr/bin/env python3
"""Price Feed's coverage/scout entry mode: fetch OEM evidence for whatever
the catalog itself says is missing a price, instead of waiting for the
WordPress delta harvester to happen to mention it.

    python -m tools.pricefeed_coverage --out batch.json
    python -m tools.pricefeed_coverage --out batch.json --apply --observed-at 2026-09-23

This is not a second pipeline. It is a second way to produce the same
harvest-batch JSON tools/pricefeed_harvest.py already produces
(``{"documents": [...], "claims": [...]}``), by asking the catalog what
is missing instead of asking an outlet what is new:

    catalog gap (vehreg.price_coverage)
      -> grouped source target (vehreg.price_sources, targets.json's
         model_hint -- the same grouping tools/pricefetch_targets.py
         already fetches by, so one model page's fetch can carry prices
         for every trim on it, not one request per trim)
      -> fetch/extract/match (tools.pricefetch_targets.main(), called as
         a library, not reimplemented -- match_trim_diagnostic itself
         calls the one production matcher, vehreg.pricefeed.match_trim)
      -> the same batch shape the WordPress harvester produces

From there everything is identical to the live feed: tools.pricefeed_write
resolves precedence, writes through CanonicalInputPipeline/PriceLedger,
and a canonical change is the only thing that ever triggers a release
publish. Coverage mode never calls tools.price_promote_batch (P6) -- that
pipeline writes market files directly and bypasses PriceLedger's own
writer, which is exactly the second parallel pipeline this must not be.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import pricefeed_write  # noqa: E402
from tools.pricefetch_targets import main as fetch_targets_main  # noqa: E402
from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR  # noqa: E402
from vehreg.price_coverage import coverage_gaps  # noqa: E402
from vehreg.price_sources import load_source_target_registry  # noqa: E402
from vehreg.pricing import PriceLedger  # noqa: E402


def select_targets(*, data_dir: Path, year: int, catalog: Catalog,
                   ledger: PriceLedger, as_of: date,
                   stale_after_days: int, limit_models: int) -> list[str]:
    """Enabled target ids whose model_hint names a model with coverage work,
    in the gap query's own deterministic order, capped at ``limit_models``
    models so one tick has a bounded number of fetches."""
    gaps = coverage_gaps(catalog, ledger, as_of=as_of,
                         stale_after_days=stale_after_days,
                         data_dir=data_dir, year=year)
    wanted_models = [g.model_id for g in gaps][:max(0, limit_models)]
    if not wanted_models:
        return []
    registry = load_source_target_registry(data_dir, year)
    wanted = set(wanted_models)
    return [target.id for target in registry.targets_for()
           if target.model_hint in wanted]


def fetch_batch(target_ids: list[str], *, data_dir: Path, year: int) -> dict:
    """Run P2-P4 (fetch, extract, match) over exactly these targets, via the
    existing tools.pricefetch_targets entrypoint -- not a reimplementation."""
    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch) / "fetch.json"
        argv = ["--data-dir", str(data_dir), "--year", str(year),
               "--extract-prices", "--match-trims", "--out", str(out)]
        for target_id in target_ids:
            argv += ["--target", target_id]
        code = fetch_targets_main(argv)
        if code != 0:
            raise RuntimeError(f"tools.pricefetch_targets exited {code}")
        return json.loads(out.read_text(encoding="utf-8"))


def to_harvest_batch(fetch_payload: dict, *, since: str) -> dict:
    """The P2-P4 fetch/extract/match output, reshaped into exactly the
    harvest-batch format tools.pricefeed_write already reads
    (vehreg.pricefeed.load_batch): {"documents": [...], "claims": [...]}.

    Every claim/document field already matches PriceClaim/SourceDocument's
    own shape (tools.pricefetch_targets._claim_dict/_document_dict build
    them that way on purpose) -- the only thing that does not belong here
    is the "match" diagnostic P4 attaches for its own review tooling;
    pricefeed.run() re-matches every claim itself (the same match_trim)
    regardless of what P4 already found, so dropping it changes nothing
    about the result, only what is redundantly carried in the file.
    """
    documents: list[dict] = []
    claims: list[dict] = []
    for row in fetch_payload.get("results", []):
        document = row.get("document")
        if document is not None:
            documents.append(document)
        for claim in row.get("claims", []):
            claims.append({k: v for k, v in claim.items() if k != "match"})
    return {
        "schema_version": 1,
        "harvested_at": fetch_payload.get("source_batch_id", ""),
        "since": since,
        "documents": documents,
        "claims": claims,
        "skipped": {},
        "failed_sources": [],
    }


def run(*, data_dir: Path, year: int, as_of: date, stale_after_days: int,
       limit_models: int) -> dict:
    catalog = Catalog.load(data_dir, year)
    ledger = PriceLedger.load(data_dir, year=year, catalog=catalog)
    target_ids = select_targets(
        data_dir=data_dir, year=year, catalog=catalog, ledger=ledger,
        as_of=as_of, stale_after_days=stale_after_days, limit_models=limit_models)
    if not target_ids:
        return {"schema_version": 1, "harvested_at": as_of.isoformat(),
               "since": as_of.isoformat(), "documents": [], "claims": [],
               "skipped": {}, "failed_sources": [], "targets_fetched": 0}
    fetched = fetch_batch(target_ids, data_dir=data_dir, year=year)
    batch = to_harvest_batch(fetched, since=as_of.isoformat())
    batch["targets_fetched"] = len(target_ids)
    return batch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--stale-after-days", type=int, default=180)
    parser.add_argument("--limit-models", type=int, default=10,
                        help="fetch at most this many gap models' targets per run")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--apply", action="store_true",
                        help="also run tools.pricefeed_write against the batch")
    parser.add_argument("--observed-at", default=None,
                        help="required with --apply; defaults to --as-of")
    args = parser.parse_args(argv)

    as_of = args.as_of or date.today()
    batch = run(data_dir=args.data_dir, year=args.year, as_of=as_of,
               stale_after_days=args.stale_after_days,
               limit_models=args.limit_models)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")

    result = {"targets_fetched": batch.get("targets_fetched", 0),
             "documents": len(batch["documents"]), "claims": len(batch["claims"]),
             "out": str(args.out) if args.out else None}
    if args.apply:
        if not args.out:
            raise SystemExit("--apply requires --out (pricefeed_write reads a file)")
        observed_at = args.observed_at or as_of.isoformat()
        result["write"] = pricefeed_write.run(
            args.out, data_dir=args.data_dir, year=args.year,
            observed_at=observed_at, apply=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
