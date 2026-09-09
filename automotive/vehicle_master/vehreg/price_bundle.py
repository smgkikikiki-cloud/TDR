"""Deterministic lineage identities for Price Intelligence artifacts.

A Price Intelligence candidate can live across multiple fetch/reconcile runs, so
lineage belongs to artifact snapshots rather than to the candidate identity
itself. The chain is::

    P2-P4 source batch -> P5 reconcile report -> CandidateBook snapshot -> review

P6 verifies that the artifacts supplied at promotion time are exactly the ones
the reviewer saw. IDs are content-derived SHA-256 values; paths and mutable
metadata are deliberately excluded from the semantic views below.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


class PriceBundleError(ValueError):
    pass


def _digest(prefix: str, payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}:" + hashlib.sha256(raw).hexdigest()


def source_batch_id(payload: Mapping[str, Any]) -> str:
    """Identity of one P2-P4 evidence/extraction/matching batch.

    Operational fetch-state and robots diagnostics are excluded. The result
    rows themselves include immutable document identity/fetched_at, claims and
    P4 matches, so a later actual observation receives a different batch ID even
    when the source bytes are unchanged.
    """
    view = {
        "schema_version": payload.get("schema_version", 1),
        "year": payload.get("year"),
        "extract_prices": bool(payload.get("extract_prices")),
        "match_trims": bool(payload.get("match_trims")),
        "static_targets": payload.get("static_targets") or [],
        "results": payload.get("results") or [],
    }
    return _digest("pbatch", view)


def candidate_state_id(payload: Mapping[str, Any]) -> str:
    """Identity of a CandidateBook snapshot, excluding lineage metadata."""
    view = {
        "schema_version": payload.get("schema_version", 1),
        "candidates": payload.get("candidates") or [],
    }
    return _digest("pstate", view)


def reconcile_id(payload: Mapping[str, Any]) -> str:
    """Identity of a P5 decision report and the state transition it produced."""
    view = {
        "schema_version": payload.get("schema_version", 1),
        "year": payload.get("year"),
        "source_batch_id": payload.get("source_batch_id"),
        "candidate_state_before_id": payload.get("candidate_state_before_id"),
        "candidate_state_after_id": payload.get("candidate_state_after_id"),
        "summary": payload.get("summary") or {},
        "decisions": payload.get("decisions") or [],
    }
    return _digest("prec", view)


def verify_declared_id(payload: Mapping[str, Any], field: str, computed: str, *,
                       required: bool = True, source: str = "artifact") -> str:
    """Verify a content-derived ID declared by an artifact."""
    declared = str(payload.get(field) or "").strip()
    if not declared:
        if required:
            raise PriceBundleError(f"{source}: missing required {field}")
        return computed
    if declared != computed:
        raise PriceBundleError(
            f"{source}: {field} mismatch; declared {declared}, computed {computed}")
    return declared


def lineage_dict(*, source_batch: str, reconcile: str,
                 candidate_state: str) -> dict[str, str]:
    return {
        "source_batch_id": source_batch,
        "reconcile_id": reconcile,
        "candidate_state_id": candidate_state,
    }


def verify_promotion_lineage(*, candidate_state: Mapping[str, Any],
                             reconcile: Mapping[str, Any],
                             fetch: Mapping[str, Any],
                             review: Mapping[str, Any]) -> dict[str, str]:
    """Verify that all P6 inputs belong to one exact Price Intel artifact chain."""
    batch_id = source_batch_id(fetch)
    state_id = candidate_state_id(candidate_state)
    rec_id = reconcile_id(reconcile)

    verify_declared_id(
        fetch, "source_batch_id", batch_id,
        source="fetch batch")
    verify_declared_id(
        candidate_state, "candidate_state_id", state_id,
        source="candidate state")
    verify_declared_id(
        reconcile, "reconcile_id", rec_id,
        source="reconcile report")

    if reconcile.get("source_batch_id") != batch_id:
        raise PriceBundleError(
            "reconcile report source_batch_id does not match supplied fetch batch")
    if reconcile.get("candidate_state_after_id") != state_id:
        raise PriceBundleError(
            "reconcile report candidate_state_after_id does not match supplied state")
    if candidate_state.get("last_source_batch_id") != batch_id:
        raise PriceBundleError(
            "candidate state last_source_batch_id does not match supplied fetch batch")
    if candidate_state.get("last_reconcile_id") != rec_id:
        raise PriceBundleError(
            "candidate state last_reconcile_id does not match supplied reconcile report")

    expected = lineage_dict(
        source_batch=batch_id,
        reconcile=rec_id,
        candidate_state=state_id,
    )
    for field, value in expected.items():
        actual = str(review.get(field) or "").strip()
        if not actual:
            raise PriceBundleError(f"review bundle: missing required {field}")
        if actual != value:
            raise PriceBundleError(
                f"review bundle: {field} {actual} does not match reviewed artifact {value}")
    return expected
