#!/usr/bin/env python3
"""Fetch registered OEM targets into SourceDocument evidence.

By default this command keeps the P2 fetch-only behaviour. Pass
``--extract-prices`` to run the deterministic P3 extractor against fetched
documents. In extraction mode an HTTP 304 is revalidated with one unconditional
GET so unchanged price text can count as a real later observation for P5's 24h
rule. Pass ``--match-trims`` as well to run P4 canonical MarketTrim matching.
No mode writes PriceLedger, the catalog, or serving data.

Discovered promotion detail URLs are durable fetch state. Once an index exposes
a promotion page, later polls keep watching that page even when the index itself
returns 304. This prevents a detail-page price edit from disappearing behind an
unchanged discovery index.

Examples:

    python tools/pricefetch_targets.py --source official_jaecoo_th
    python tools/pricefetch_targets.py --source official_jaecoo_th \
        --follow-discovery --extract-prices --match-trims \
        --out /tmp/jaecoo-fetch.json --state-out /tmp/jaecoo-state.json \
        --snapshot-dir /tmp/jaecoo-snapshots
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import robots_check  # noqa: E402
from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR  # noqa: E402
from vehreg.price_bundle import source_batch_id  # noqa: E402
from vehreg.price_extract import extract_oem_price_claims  # noqa: E402
from vehreg.price_fetch import (  # noqa: E402
    ADAPTERS,
    DiscoveredTarget,
    FetchError,
    FetchResult,
    FetchState,
    adapter_for,
)
from vehreg.price_match import match_trim_diagnostic  # noqa: E402
from vehreg.price_sources import (  # noqa: E402
    SourceTarget,
    TargetRole,
    load_source_target_registry,
)


def _load_state_bundle(path: Path | None) -> tuple[
        dict[str, FetchState], dict[str, DiscoveredTarget]]:
    if path is None or not path.exists():
        return {}, {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version", 1) != 1:
        raise FetchError(f"{path}: unsupported state schema_version")

    states: dict[str, FetchState] = {}
    for row in payload.get("states", []):
        state = FetchState(
            target_id=str(row.get("target_id") or ""),
            content_hash=str(row.get("content_hash") or ""),
            first_seen_at=str(row.get("first_seen_at") or ""),
            etag=str(row.get("etag") or ""),
            last_modified=str(row.get("last_modified") or ""),
        )
        if not state.target_id:
            raise FetchError(f"{path}: state row missing target_id")
        states[state.target_id] = state

    discovered: dict[str, DiscoveredTarget] = {}
    rows = payload.get("discovered_targets", [])
    if not isinstance(rows, list):
        raise FetchError(f"{path}: discovered_targets must be an array")
    for row in rows:
        if not isinstance(row, dict):
            raise FetchError(f"{path}: discovered target must be an object")
        item = DiscoveredTarget(
            id=str(row.get("id") or "").strip(),
            source_id=str(row.get("source_id") or "").strip(),
            url=str(row.get("url") or "").strip(),
            role=TargetRole.parse(row.get("role")),
            model_hint=str(row.get("model_hint") or "").strip(),
        )
        if not item.id or not item.source_id or not item.url:
            raise FetchError(f"{path}: discovered target missing id/source_id/url")
        previous = discovered.get(item.id)
        if previous is not None and previous != item:
            raise FetchError(f"{path}: duplicate discovered target id {item.id}")
        discovered[item.id] = item
    return states, discovered


def _state_dict(state: FetchState) -> dict:
    return {
        "target_id": state.target_id,
        "content_hash": state.content_hash,
        "first_seen_at": state.first_seen_at,
        "etag": state.etag,
        "last_modified": state.last_modified,
    }


def _discovered_dict(item: DiscoveredTarget) -> dict:
    return {
        "id": item.id,
        "source_id": item.source_id,
        "url": item.url,
        "role": item.role.value,
        "model_hint": item.model_hint,
    }


def _document_dict(result: FetchResult, snapshot_ref: str = "") -> dict | None:
    document = result.document
    if document is None:
        return None
    return {
        "document_id": document.document_id,
        "source_id": document.source_id,
        "url": document.url,
        "content_hash": document.content_hash,
        "published_at": document.published_at,
        "modified_at": document.modified_at,
        "first_seen_at": document.first_seen_at,
        "fetched_at": document.fetched_at,
        "title": document.title,
        "snapshot_ref": snapshot_ref,
        "body_sketch": list(document.body_sketch),
    }


def _claim_dict(claim, *, match=None) -> dict:
    row = {
        "claim_id": claim.claim_id,
        "document_id": claim.document_id,
        "source_id": claim.source_id,
        "brand_raw": claim.brand_raw,
        "model_raw": claim.model_raw,
        "trim_raw": claim.trim_raw,
        "amount_thb": claim.amount_thb,
        "price_type": claim.price_type.value,
        "evidence_text": claim.evidence_text,
        "extraction_method": claim.extraction_method,
        "effective_from": claim.effective_from,
        "effective_to": claim.effective_to,
        "reference_price_thb": claim.reference_price_thb,
        "campaign_hint": claim.campaign_hint,
        "option_hint": claim.option_hint,
    }
    if match is not None:
        row["match"] = match.as_dict()
    return row


def _origin(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _robots_allowed(url: str, cache: dict[str, str]) -> bool:
    origin = _origin(url)
    if origin not in cache:
        cache[origin] = robots_check.verdict(robots_check.audit(origin))
    verdict = cache[origin]
    if not verdict.startswith("allowed"):
        print(f"{origin}: {verdict}", file=sys.stderr)
        return False
    return True


def _snapshot(result: FetchResult, folder: Path | None) -> str:
    if folder is None or result.document is None or not result.raw_body:
        return ""
    folder.mkdir(parents=True, exist_ok=True)
    digest = result.document.content_hash.removeprefix("sha256:")
    path = folder / f"{digest}.html"
    if not path.exists():
        path.write_bytes(result.raw_body)
    return str(path)


def _persisted_selected(item: DiscoveredTarget, *, sources: list[str] | None,
                        target_ids: list[str] | None) -> bool:
    if sources and item.source_id not in sources:
        return False
    if target_ids and not any(
            item.id == target_id or item.id.startswith(target_id + ":")
            for target_id in target_ids):
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--source", action="append", default=None)
    parser.add_argument("--target", action="append", default=None)
    parser.add_argument("--follow-discovery", action="store_true")
    parser.add_argument("--extract-prices", action="store_true",
                        help="run P3 deterministic extraction on fetched documents")
    parser.add_argument("--match-trims", action="store_true",
                        help="run P4 canonical MarketTrim matching; requires --extract-prices")
    parser.add_argument("--max-discovered", type=int, default=20,
                        help="maximum newly discovered targets to follow in this run")
    parser.add_argument("--state-in", type=Path, default=None)
    parser.add_argument("--state-out", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--snapshot-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.match_trims and not args.extract_prices:
        parser.error("--match-trims requires --extract-prices")

    registry = load_source_target_registry(args.data_dir, args.year)
    states, persisted_discovered = _load_state_bundle(args.state_in)
    robots_cache: dict[str, str] = {}
    catalog = Catalog.load(args.data_dir, args.year) if args.match_trims else None
    siblings_by_model = None
    model_memo: dict = {}

    targets = [target for target in registry.targets_for()
               if registry.effective_adapter(target) in ADAPTERS]
    if args.source:
        targets = [target for target in targets if target.source_id in args.source]
    if args.target:
        targets = [target for target in targets if target.id in args.target]
    if not targets:
        raise FetchError("no enabled P2 targets matched")

    persisted_targets = [
        item.as_source_target()
        for item in sorted(persisted_discovered.values(), key=lambda row: row.id)
        if args.follow_discovery and _persisted_selected(
            item, sources=args.source, target_ids=args.target)
    ]
    queue: list[SourceTarget] = [*targets, *persisted_targets]
    static_ids = {target.id for target in targets}
    seen_urls = {target.url for target in queue}
    queued_ids = {target.id for target in queue}
    rows: list[dict] = []
    skipped_robots = 0
    followed = 0
    claims_total = 0
    extraction_warnings_total = 0
    match_counts = {"EXACT": 0, "AMBIGUOUS": 0, "UNMAPPED": 0}

    while queue:
        target = queue.pop(0)
        if not _robots_allowed(target.url, robots_cache):
            skipped_robots += 1
            continue
        adapter = adapter_for(registry, target)
        result = adapter.fetch(
            target,
            previous=states.get(target.id),
            # P5 confirmation requires a fresh sighting after 24h. A 304 proves
            # representation stability but carries no body to re-extract, so
            # extraction mode revalidates with one unconditional GET.
            refetch_not_modified=args.extract_prices,
        )
        states[target.id] = result.state
        snapshot_ref = _snapshot(result, args.snapshot_dir)

        claims: list[dict] = []
        extraction_warnings: list[str] = []
        if args.extract_prices:
            extracted = extract_oem_price_claims(target, result)
            for claim in extracted.claims:
                matched = None
                if catalog is not None:
                    matched = match_trim_diagnostic(
                        catalog, claim,
                        siblings_by_model=siblings_by_model,
                        model_memo=model_memo,
                    )
                    match_counts[matched.state.value] += 1
                claims.append(_claim_dict(claim, match=matched))
            extraction_warnings = list(extracted.warnings)
            claims_total += len(claims)
            extraction_warnings_total += len(extraction_warnings)

        rows.append({
            "target_id": result.target_id,
            "target_role": result.target_role.value,
            "source_id": result.source_id,
            "model_hint": target.model_hint,
            "not_modified": result.not_modified,
            "document": _document_dict(result, snapshot_ref),
            "claims": claims,
            "extraction_warnings": extraction_warnings,
            "discovered_targets": [
                _discovered_dict(item) for item in result.discovered_targets
            ],
        })

        if not args.follow_discovery:
            continue
        for item in result.discovered_targets:
            # Discovery is durable. Do not make future polling depend on the
            # index itself returning 200 again.
            persisted_discovered[item.id] = item
            if followed >= args.max_discovered:
                continue
            if item.url in seen_urls or item.id in queued_ids:
                continue
            seen_urls.add(item.url)
            queued_ids.add(item.id)
            queue.append(item.as_source_target())
            followed += 1

    payload = {
        "schema_version": 1,
        "year": args.year,
        "extract_prices": args.extract_prices,
        "match_trims": args.match_trims,
        "match_counts": match_counts if args.match_trims else None,
        "static_targets": sorted(static_ids),
        "results": rows,
        "robots": robots_cache,
        "skipped_robots": skipped_robots,
    }
    payload["source_batch_id"] = source_batch_id(payload)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    if args.state_out:
        args.state_out.parent.mkdir(parents=True, exist_ok=True)
        args.state_out.write_text(json.dumps({
            "schema_version": 1,
            "states": [_state_dict(states[key]) for key in sorted(states)],
            "discovered_targets": [
                _discovered_dict(persisted_discovered[key])
                for key in sorted(persisted_discovered)
            ],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "source_batch_id": payload["source_batch_id"],
        "fetched": sum(1 for row in rows if row["document"] is not None),
        "not_modified": sum(1 for row in rows if row["not_modified"]),
        "claims": claims_total,
        "extraction_warnings": extraction_warnings_total,
        "match_counts": match_counts if args.match_trims else None,
        "followed_discovered": followed,
        "persisted_discovered": len(persisted_discovered),
        "skipped_robots": skipped_robots,
        "out": str(args.out) if args.out else None,
        "state_out": str(args.state_out) if args.state_out else None,
        "snapshot_dir": str(args.snapshot_dir) if args.snapshot_dir else None,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
