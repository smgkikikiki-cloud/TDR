"""Fail-closed catalog eligibility rules over a normalized local snapshot."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Eligibility:
    decision: str
    reasons: tuple[str, ...]
    generation_ids: tuple[str, ...]
    admitted_trim_ids: tuple[str, ...] = ()


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
    known = [t for t in snapshot.get("trims", []) if t.get("model_id") == mid
             and t.get("generation_id") in generations and not t.get("deleted_at")]
    if any(s.get("model_id") == mid for s in snapshot.get("current_retail_sets", [])):
        approved = next(s for s in snapshot["current_retail_sets"] if s.get("model_id") == mid)
        ids = set(approved.get("trim_ids", []))
        known_ids = {t["id"] for t in known}
        # A bad sidecar is not silently repaired by the simulator.
        if not ids or not ids <= known_ids:
            return Eligibility("HOLD_IDENTITY", ("INVALID_OWNER_RETAIL_SET",), generations)
        trims = [t for t in known if t["id"] in ids]
        if any(t.get("admin_retired") for t in trims):
            return Eligibility("HOLD_IDENTITY", ("OWNER_SET_CONFLICT",), generations)
        observed = model.get("observed_current_trim_ids")
        review = observed is not None and set(observed) != ids
        reasons = ("OWNER_CURRENT_SET", "OWNER_SET_CONFLICT_REVIEW_REQUIRED") if review else ("OWNER_CURRENT_SET",)
        return Eligibility("ELIGIBLE_ENRICH", reasons, generations,
                           tuple(sorted(t["id"] for t in trims)))

    confirmed = bool(model.get("source_current_lineup_confirmed"))
    if not confirmed:
        return Eligibility("RETAIL_AUDIT_ONLY", ("RETAIL_UNVERIFIED",), generations)
    current = [t for t in known if t.get("status") == "CURRENT" and t.get("retail_verified")
               and not t.get("admin_retired")]
    if not current:
        return Eligibility("HOLD_IDENTITY", ("CONFIRMED_LINEUP_WITHOUT_TRIMS",), generations)
    return Eligibility("ELIGIBLE_ENRICH", ("SOURCE_CONFIRMED_CURRENT_LINEUP",), generations,
                       tuple(sorted(t["id"] for t in current)))
