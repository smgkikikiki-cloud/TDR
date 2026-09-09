#!/usr/bin/env python3
"""Build a human review queue from P5 decisions and candidate state.

Two queues are deliberately separate:

* ``promotion_reviews``: P5 already resolved a canonical stream; the person may
  APPROVE or REJECT the candidate for P6 canonical write.
* ``binding_reviews``: P5 refused automatic campaign scope. The person must
  bind canonical campaign_id + option_id, then rerun P5. A raw campaign_hint is
  shown only as context and is never copied into canonical scope automatically.

Promotion reviews are content-bound to the exact P2-P4 source batch, P5 report
and CandidateBook snapshot shown to the reviewer. P6 recomputes these identities
before any canonical write.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehreg.price_bundle import (  # noqa: E402
    PriceBundleError,
    candidate_state_id,
    lineage_dict,
    reconcile_id,
    source_batch_id,
    verify_declared_id,
)
from vehreg.price_reconcile import CandidateBook, ReconcileDisposition  # noqa: E402


PROMOTABLE = {
    ReconcileDisposition.SAFE_CANDIDATE.value,
    ReconcileDisposition.CONFIRMED_REPLACEMENT.value,
    ReconcileDisposition.HISTORICAL_ONLY.value,
}


def _load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: root must be an object")
    return payload


def _artifact_lineage(candidate_state: dict, reconcile: dict, fetch: dict, *,
                      strict: bool) -> dict[str, str]:
    batch_id = source_batch_id(fetch)
    state_id = candidate_state_id(candidate_state)
    rec_id = reconcile_id(reconcile)
    try:
        verify_declared_id(
            fetch, "source_batch_id", batch_id,
            required=strict, source="fetch batch")
        verify_declared_id(
            candidate_state, "candidate_state_id", state_id,
            required=strict, source="candidate state")
        verify_declared_id(
            reconcile, "reconcile_id", rec_id,
            required=strict, source="reconcile report")
    except PriceBundleError as exc:
        raise ValueError(str(exc)) from exc

    if strict:
        if reconcile.get("source_batch_id") != batch_id:
            raise ValueError(
                "reconcile report does not belong to the supplied source batch")
        if reconcile.get("candidate_state_after_id") != state_id:
            raise ValueError(
                "reconcile report does not produce the supplied candidate state")
        if candidate_state.get("last_source_batch_id") != batch_id:
            raise ValueError(
                "candidate state last_source_batch_id does not match source batch")
        if candidate_state.get("last_reconcile_id") != rec_id:
            raise ValueError(
                "candidate state last_reconcile_id does not match reconcile report")

    return lineage_dict(
        source_batch=batch_id,
        reconcile=rec_id,
        candidate_state=state_id,
    )


def _fetch_claims(fetch: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for result in fetch.get("results") or []:
        if not isinstance(result, dict):
            continue
        for claim in result.get("claims") or []:
            if not isinstance(claim, dict):
                continue
            claim_id = str(claim.get("claim_id") or "")
            if claim_id:
                out[claim_id] = {
                    "claim": claim,
                    "target_id": result.get("target_id"),
                    "target_role": result.get("target_role"),
                    "source_id": result.get("source_id"),
                    "url": ((result.get("document") or {}).get("url")
                            if isinstance(result.get("document"), dict) else None),
                }
    return out


def build_queue(candidate_state: dict, reconcile: dict, fetch: dict, *,
                strict_lineage: bool = False) -> dict:
    lineage = _artifact_lineage(
        candidate_state, reconcile, fetch, strict=strict_lineage)
    book = CandidateBook.from_payload(candidate_state)
    claims = _fetch_claims(fetch)
    promotion: list[dict] = []
    binding: list[dict] = []
    seen_candidates: set[str] = set()
    seen_bindings: set[str] = set()

    for row in reconcile.get("decisions") or []:
        if not isinstance(row, dict):
            continue
        decision = row.get("decision") or {}
        if not isinstance(decision, dict):
            continue
        disposition = str(decision.get("disposition") or "")
        candidate_id = str(decision.get("candidate_id") or "")
        claim_id = str(decision.get("claim_id") or row.get("claim_id") or "")
        reasons = list(decision.get("reasons") or [])

        if candidate_id and disposition in PROMOTABLE and candidate_id not in seen_candidates:
            candidate = book.candidates.get(candidate_id)
            if candidate is not None:
                promotion.append({
                    "candidate_id": candidate_id,
                    "disposition": disposition,
                    "state": candidate.state.value,
                    "trim_id": candidate.trim_id,
                    "amount_thb": candidate.amount_thb,
                    "price_type": candidate.price_type.value,
                    "previous_amount_thb": candidate.replaces_amount_thb,
                    "campaign_id": candidate.campaign_id,
                    "option_id": candidate.option_id,
                    "first_seen_at": candidate.first_seen_at,
                    "confirmed_at": candidate.confirmed_at,
                    "source_id": candidate.source_id,
                    "target_id": candidate.target_id,
                    "actions": ["APPROVE", "REJECT"],
                })
                seen_candidates.add(candidate_id)

        if "CAMPAIGN_SCOPE_REQUIRED" in reasons and claim_id and claim_id not in seen_bindings:
            context = claims.get(claim_id) or {}
            claim = context.get("claim") or {}
            binding.append({
                "claim_id": claim_id,
                "trim_id": decision.get("trim_id"),
                "amount_thb": claim.get("amount_thb"),
                "price_type": claim.get("price_type"),
                "raw_campaign_hint": claim.get("campaign_hint"),
                "raw_option_hint": claim.get("option_hint"),
                "source_id": context.get("source_id"),
                "target_id": context.get("target_id"),
                "target_role": context.get("target_role"),
                "url": context.get("url"),
                "required_action": "BIND_CANONICAL_CAMPAIGN_OPTION_THEN_RERUN_P5",
            })
            seen_bindings.add(claim_id)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    promotion_template = {
        "schema_version": 1,
        **lineage,
        "decisions": [{
            "candidate_id": item["candidate_id"],
            "action": "",
            "reviewer": "",
            "origin": "HUMAN",
            "reviewed_at": now,
            "notes": "",
        } for item in promotion],
        "create_campaigns": [],
    }
    binding_template = {
        "decisions": [{
            "claim_id": item["claim_id"],
            "campaign_id": "",
            "option_id": "",
            "action": "accept",
            "reviewer": "",
            "origin": "HUMAN",
            "reviewed_at": now,
            "notes": "",
        } for item in binding],
    }
    return {
        "schema_version": 1,
        **lineage,
        "promotion_reviews": promotion,
        "binding_reviews": binding,
        "promotion_review_template": promotion_template,
        "binding_decision_template": binding_template,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--candidate-state", type=Path, required=True)
    parser.add_argument("--reconcile", type=Path, required=True)
    parser.add_argument("--fetch", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    payload = build_queue(
        _load(args.candidate_state),
        _load(args.reconcile),
        _load(args.fetch),
        strict_lineage=True,
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
