#!/usr/bin/env python3
"""Reconcile one P4 fetch batch against canonical PriceLedger without writing it.

The input is JSON produced by ``tools/pricefetch_targets.py`` with both
``--extract-prices`` and ``--match-trims``.  P5 writes only its own staging
candidate-state JSON and an optional decision report. Canonical PriceLedger,
vehicle identity, campaigns and serving data remain untouched.

Examples::

    python tools/price_reconcile_batch.py \
      --in /tmp/jaecoo-fetch.json \
      --candidate-state-in /tmp/price-candidates.json \
      --candidate-state-out /tmp/price-candidates.json \
      --out /tmp/jaecoo-reconcile.json

A legacy pricefeed decisions file may be supplied with ``--decisions``. P5 uses
only HUMAN campaign_id + option_id bindings from it; it never treats raw
``campaign_hint`` text as canonical scope.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR  # noqa: E402
from vehreg.price_match import (  # noqa: E402
    TrimMatchMethod,
    TrimMatchResult,
    TrimMatchState,
)
from vehreg.price_reconcile import (  # noqa: E402
    CandidateBook,
    ReconcileError,
    ReconcileObservation,
    reconcile_batch,
)
from vehreg.price_sources import TargetRole  # noqa: E402
from vehreg.pricefeed import (  # noqa: E402
    DecisionOrigin,
    PriceClaim,
    SourceDocument,
    load_decisions,
)
from vehreg.pricing import PriceLedger, PriceType  # noqa: E402


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconcileError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReconcileError(f"{path}: root must be an object")
    return payload


def _document(raw: dict) -> SourceDocument:
    if not isinstance(raw, dict):
        raise ReconcileError("fetch result with claims must contain a document object")
    allowed = set(SourceDocument.__dataclass_fields__)
    unknown = set(raw) - allowed
    if unknown:
        raise ReconcileError(f"unknown document fields: {sorted(unknown)}")
    payload = {name: raw.get(name) for name in SourceDocument.__dataclass_fields__}
    for name in ("document_id", "source_id", "url", "content_hash", "title", "snapshot_ref"):
        payload[name] = payload.get(name) or ""
    payload["body_sketch"] = tuple(raw.get("body_sketch") or ())
    document = SourceDocument(**payload)
    problems = document.validate()
    if problems:
        raise ReconcileError("; ".join(problems))
    return document


def _claim(raw: dict) -> PriceClaim:
    if not isinstance(raw, dict):
        raise ReconcileError("claim must be an object")
    return PriceClaim(
        claim_id=str(raw.get("claim_id") or ""),
        document_id=str(raw.get("document_id") or ""),
        source_id=str(raw.get("source_id") or ""),
        brand_raw=str(raw.get("brand_raw") or ""),
        model_raw=str(raw.get("model_raw") or ""),
        trim_raw=str(raw.get("trim_raw") or ""),
        amount_thb=int(raw.get("amount_thb") or 0),
        price_type=PriceType.parse(raw.get("price_type")),
        evidence_text=str(raw.get("evidence_text") or ""),
        extraction_method=str(raw.get("extraction_method") or "rule"),
        effective_from=raw.get("effective_from") or None,
        effective_to=raw.get("effective_to") or None,
        reference_price_thb=(int(raw["reference_price_thb"])
                             if raw.get("reference_price_thb") is not None else None),
        campaign_hint=str(raw.get("campaign_hint") or ""),
        option_hint=str(raw.get("option_hint") or ""),
    )


def _match(raw: dict) -> TrimMatchResult:
    if not isinstance(raw, dict):
        raise ReconcileError(
            "P5 requires P4 match diagnostics on every claim; rerun with --match-trims")
    try:
        return TrimMatchResult(
            state=TrimMatchState(str(raw.get("state") or "")),
            model_id=raw.get("model_id") or None,
            trim_id=raw.get("trim_id") or None,
            candidate_ids=tuple(raw.get("candidate_ids") or ()),
            method=TrimMatchMethod(str(raw.get("method") or "")),
            reason=str(raw.get("reason") or ""),
            normalized_trim_raw=str(raw.get("normalized_trim_raw") or ""),
        )
    except ValueError as exc:
        raise ReconcileError(f"invalid P4 match diagnostic: {exc}") from exc


def _candidate_book(path: Path | None) -> CandidateBook:
    if path is None or not path.exists():
        return CandidateBook()
    return CandidateBook.from_payload(_load_json(path))


def _human_binding(decisions: dict[str, dict], claim_id: str) -> tuple[str | None, str | None]:
    answer = decisions.get(claim_id)
    if not answer or answer.get("origin") != DecisionOrigin.HUMAN.value:
        return None, None
    campaign_id = answer.get("campaign_id") or None
    option_id = answer.get("option_id") or None
    return campaign_id, option_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in", dest="input_path", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--candidate-state-in", type=Path, default=None)
    parser.add_argument("--candidate-state-out", type=Path, default=None)
    parser.add_argument("--decisions", type=Path, default=None,
                        help="optional pricefeed decisions; only HUMAN campaign/option bindings are used")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    payload = _load_json(args.input_path)
    if not payload.get("extract_prices") or not payload.get("match_trims"):
        parser.error("input must come from pricefetch_targets.py --extract-prices --match-trims")
    rows = payload.get("results")
    if not isinstance(rows, list):
        raise ReconcileError("fetch batch results must be an array")

    catalog = Catalog.load(args.data_dir, args.year)
    ledger = PriceLedger.load(args.data_dir, year=args.year, catalog=catalog)
    book = _candidate_book(args.candidate_state_in)
    decisions = load_decisions(args.decisions) if args.decisions else {}

    observations: list[ReconcileObservation] = []
    locations: list[tuple[int, int]] = []
    for row_index, row in enumerate(rows):
        claims = row.get("claims") or []
        if not isinstance(claims, list):
            raise ReconcileError(f"result {row_index}: claims must be an array")
        if not claims:
            continue
        document = _document(row.get("document"))
        role = TargetRole.parse(row.get("target_role"))
        target_id = str(row.get("target_id") or "")
        if not target_id:
            raise ReconcileError(f"result {row_index}: target_id is required")
        for claim_index, raw_claim in enumerate(claims):
            claim = _claim(raw_claim)
            matched = _match(raw_claim.get("match"))
            campaign_id, option_id = _human_binding(decisions, claim.claim_id)
            observations.append(ReconcileObservation(
                claim=claim,
                match=matched,
                target_id=target_id,
                target_role=role,
                document=document,
                campaign_id=campaign_id,
                option_id=option_id,
            ))
            locations.append((row_index, claim_index))

    result = reconcile_batch(observations, ledger, candidate_book=book)
    decision_rows: list[dict] = []
    for location, observation, decision in zip(locations, observations, result.decisions):
        row_index, claim_index = location
        decision_rows.append({
            "result_index": row_index,
            "claim_index": claim_index,
            "target_id": observation.target_id,
            "target_role": observation.target_role.value,
            "claim_id": observation.claim.claim_id,
            "decision": decision.as_dict(),
        })

    report = {
        "schema_version": 1,
        "source_batch": str(args.input_path),
        "year": args.year,
        "summary": result.summary(),
        "decisions": decision_rows,
    }

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    if args.candidate_state_out:
        args.candidate_state_out.parent.mkdir(parents=True, exist_ok=True)
        args.candidate_state_out.write_text(
            json.dumps(result.candidate_book.to_payload(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(json.dumps({
        **result.summary(),
        "out": str(args.out) if args.out else None,
        "candidate_state_out": (str(args.candidate_state_out)
                                if args.candidate_state_out else None),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
