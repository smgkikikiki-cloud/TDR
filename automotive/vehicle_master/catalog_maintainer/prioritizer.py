"""Deterministic, normalized scoring; registration affects order only."""
from __future__ import annotations


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def audit_scores(models: list[dict], registration_signals: list[dict]) -> dict[str, float]:
    # Comparable cohorts are normalized independently (e.g. segment/source stratum).
    buckets: dict[str, list[dict]] = {}
    for row in registration_signals:
        buckets.setdefault(str(row.get("stratum", "ALL")), []).append(row)
    relevance: dict[str, float] = {}
    for rows in buckets.values():
        maximum = max((max(0, float(x.get("count", 0))) for x in rows), default=0)
        for row in rows:
            relevance[row["model_id"]] = max(relevance.get(row["model_id"], 0.0),
                                               float(row.get("count", 0)) / maximum if maximum else 0)
    out = {}
    for m in models:
        # Queue A: registration relevance 45%, catalog staleness 30%, launch recency 15%,
        # document reuse readiness 10%. Missing signals are neutral zero, never evidence.
        out[m["id"]] = round(_clamp(.45 * relevance.get(m["id"], 0)
                                  + .30 * float(m.get("staleness_risk", 0))
                                  + .15 * float(m.get("lineup_recency", 0))
                                  + .10 * float(m.get("document_reuse", 0))), 6)
    return out


def spec_score(model: dict, gaps: dict, shared_doc: bool) -> tuple[float, list[str]]:
    groups = gaps["groups"]
    p1 = sum(len(g["field_keys"]) for g in groups.values() if g["tier"] == "P1")
    p2 = sum(len(g["field_keys"]) for g in groups.values() if g["tier"] == "P2")
    # Missingness is saturated; P1 has greater value without rewarding raw cell count.
    utility = _clamp((.75 if p1 else 0) + (.25 if p2 else 0))
    relevance = _clamp(float(model.get("business_relevance", 0)))
    yield_score = 1.0 if shared_doc else _clamp(float(model.get("shared_document_yield", 0)))
    ready = _clamp(float(model.get("ready_evidence", 0)))
    score = .50 * utility + .25 * relevance + .20 * yield_score + .05 * ready
    reasons = []
    if p1: reasons.append("P1_GAPS_PRESENT")
    if p2: reasons.append("P2_GAPS_PRESENT")
    if shared_doc: reasons.append("SHARED_DOCUMENT_REUSE")
    return round(score, 6), reasons
