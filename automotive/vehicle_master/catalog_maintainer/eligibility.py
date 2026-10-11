"""Fail-closed catalog eligibility rules over a normalized local snapshot."""
from __future__ import annotations

from dataclasses import dataclass
from .retail_reconcile import validate_model_lineup_binding


@dataclass(frozen=True)
class Eligibility:
    decision: str
    reasons: tuple[str, ...]
    generation_ids: tuple[str, ...]
    admitted_trim_ids: tuple[str, ...] = ()
    conflicting_trim_ids: tuple[str, ...] = ()


def _complete_official_lineup(snapshot: dict, model: dict) -> bool:
    evidence = model.get("lineup_evidence") or {}
    bound, _ = validate_model_lineup_binding(snapshot, model)
    return (evidence.get("market") == "TH"
            and evidence.get("source_authority") == "OFFICIAL"
            and evidence.get("completeness") == "COMPLETE_LINEUP"
            and bound)


def evaluate_model(snapshot: dict, model: dict) -> Eligibility:
    mid = model["id"]
    if model.get("deleted_at"):
        return Eligibility("HOLD_IDENTITY", ("MODEL_DELETED",), ())
    if model.get("discovered") or model.get("status") == "DISCOVERED":
        return Eligibility("EXCLUDED_DISCOVERED", ("DISCOVERED_IDENTITY_EXCLUDED",), ())
    if model.get("upcoming") or model.get("status") == "UPCOMING":
        return Eligibility("EXCLUDED_UPCOMING", ("UPCOMING_EXCLUDED",), ())
    if model.get("admin_retired"):
        return Eligibility("EXCLUDED_ADMIN_RETIRED", ("ADMIN_LIFECYCLE_WINS",), ())
    if model.get("status") == "HISTORICAL":
        return Eligibility("EXCLUDED_HISTORICAL", ("HISTORICAL_EXCLUDED",), ())
    if model.get("status") != "CURRENT":
        return Eligibility("HOLD_IDENTITY", ("MODEL_NOT_CURRENT",), ())

    generations = tuple(sorted(g["id"] for g in snapshot.get("generations", [])
                               if g.get("model_id") == mid and not g.get("deleted_at")))
    if not generations:
        return Eligibility("HOLD_IDENTITY", ("GENERATION_UNRESOLVED",), ())
    model_trims = [t for t in snapshot.get("trims", []) if t.get("model_id") == mid
                   and t.get("generation_id") in generations]
    known = [t for t in model_trims if not t.get("deleted_at")]
    if any(s.get("model_id") == mid for s in snapshot.get("current_retail_sets", [])):
        approved = next(s for s in snapshot["current_retail_sets"] if s.get("model_id") == mid)
        ids = set(approved.get("trim_ids", []))
        known_ids = {t["id"] for t in model_trims}
        # A bad sidecar is not silently repaired by the simulator.
        if not ids or not ids <= known_ids:
            return Eligibility("HOLD_IDENTITY", ("INVALID_OWNER_RETAIL_SET",), generations)
        trims = [t for t in model_trims if t["id"] in ids]
        conflicts = [t for t in trims if t.get("deleted_at") or t.get("admin_retired")
                     or t.get("owner_retired") or t.get("status") != "CURRENT"]
        admitted = [t for t in trims if t not in conflicts]
        observed = model.get("observed_current_trim_ids")
        review = bool(conflicts) or (observed is not None and set(observed) != ids)
        reasons = ["OWNER_CURRENT_SET"]
        if conflicts: reasons.append("OWNER_SET_TRIM_STATUS_CONFLICT")
        if observed is not None and set(observed) != ids: reasons.append("OWNER_SET_CONFLICT_REVIEW_REQUIRED")
        if not admitted:
            return Eligibility("HOLD_IDENTITY", tuple(reasons + ["MODEL_REVIEW_REQUIRED", "NO_ENRICHABLE_OWNER_SET_TRIMS"]),
                               generations, (), tuple(sorted(t["id"] for t in conflicts)))
        if review: reasons.append("MODEL_REVIEW_REQUIRED")
        return Eligibility("ELIGIBLE_ENRICH", tuple(reasons), generations,
                           tuple(sorted(t["id"] for t in admitted)),
                           tuple(sorted(t["id"] for t in conflicts)))

    evidence = model.get("lineup_evidence") or {}
    confirmed = _complete_official_lineup(snapshot, model)
    if not confirmed:
        partial = evidence.get("completeness") in {"PARTIAL_TRIM_LIST", "INDIVIDUAL_TRIM"}
        return Eligibility("RETAIL_AUDIT_ONLY", ("LINEUP_PARTIAL" if partial else "RETAIL_UNVERIFIED",), generations)
    current_ids = set(evidence["trim_ids"])
    known_ids = {t["id"] for t in known}
    if not current_ids or not current_ids <= known_ids:
        return Eligibility("HOLD_IDENTITY", ("COMPLETE_LINEUP_HAS_UNRESOLVED_IDENTITIES",), generations)
    current = [t for t in known if t["id"] in current_ids]
    conflicts = [t for t in current if t.get("status") != "CURRENT" or t.get("admin_retired") or t.get("owner_retired")]
    admitted = [t for t in current if t not in conflicts]
    if not admitted:
        return Eligibility("HOLD_IDENTITY", ("SOURCE_LINEUP_STATUS_CONFLICT",), generations, (),
                           tuple(sorted(t["id"] for t in conflicts)))
    reasons = ["SOURCE_CONFIRMED_CURRENT_LINEUP"]
    if conflicts: reasons.extend(["SOURCE_LINEUP_STATUS_CONFLICT", "MODEL_REVIEW_REQUIRED"])
    return Eligibility("ELIGIBLE_ENRICH", tuple(reasons), generations,
                       tuple(sorted(t["id"] for t in admitted)),
                       tuple(sorted(t["id"] for t in conflicts)))
