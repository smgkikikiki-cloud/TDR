"""Deterministic scores parameterized by the reviewed policy file."""
from __future__ import annotations


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def registration_relevance(models: list[dict], signals: list[dict]) -> dict[str, float]:
    """Normalize within series/stratum/period; ignore aggregate '*' rows.

    A model selects one source series (RY1 or RY3) in its input profile. The
    function never adds RY1 and RY3 or an aggregate class to a specific class.
    """
    selected = []
    profile = {m["id"]: (m.get("registration_series"), m.get("registration_stratum")) for m in models}
    for row in signals:
        series, stratum = profile.get(row.get("model_id"), (None, None))
        if not series or row.get("series") != series:
            continue
        if row.get("source_class", "MODEL") != "MODEL":
            continue
        if stratum and row.get("stratum") != stratum:
            continue
        selected.append(row)
    latest_by_bucket: dict[tuple[str, str], str] = {}
    for row in selected:
        key = (row["series"], row["stratum"])
        latest_by_bucket[key] = max(latest_by_bucket.get(key, ""), row.get("period", ""))
    maxima: dict[tuple[str, str], float] = {}
    for row in selected:
        key = (row["series"], row["stratum"])
        if row.get("period", "") != latest_by_bucket[key]:
            continue
        maxima[key] = max(maxima.get(key, 0), max(0.0, float(row.get("count", 0))))
    relevance = {}
    for row in selected:
        key = (row["series"], row["stratum"])
        if row.get("period", "") != latest_by_bucket[key]:
            continue
        maximum = maxima[key]
        score = max(0.0, float(row.get("count", 0))) / maximum if maximum else 0.0
        relevance[row["model_id"]] = max(relevance.get(row["model_id"], 0.0), score)
    return relevance


def audit_scores(models: list[dict], registration_signals: list[dict], policy: dict) -> dict[str, float]:
    weights = policy["priority_policy"]["audit_weights"]
    relevance = registration_relevance(models, registration_signals)
    return {m["id"]: round(_clamp(weights["registration_relevance"] * relevance.get(m["id"], 0)
                                  + weights["catalog_staleness"] * m.get("staleness_risk", 0)
                                  + weights["lineup_recency"] * m.get("lineup_recency", 0)
                                  + weights["document_reuse"] * m.get("document_reuse", 0)), 6)
            for m in models}


def spec_score(model: dict, gaps: dict, shared_doc: bool, policy: dict) -> tuple[float, list[str]]:
    fields_by_tier = [g.get("field_keys_by_tier", {}) for g in gaps["groups"].values()]
    p1 = sum(len(keys.get("P1", [])) for keys in fields_by_tier)
    p2 = sum(len(keys.get("P2", [])) for keys in fields_by_tier)
    within = policy["priority_policy"]["spec_missingness_weights"]
    utility = _clamp((within["P1"] if p1 else 0) + (within["P2"] if p2 else 0))
    weights = policy["priority_policy"]["spec_weights"]
    score = (weights["missingness_applicability"] * utility
             + weights["business_relevance"] * _clamp(model.get("business_relevance", 0))
             + weights["shared_document_yield"] * (1.0 if shared_doc else _clamp(model.get("shared_document_yield", 0)))
             + weights["ready_evidence"] * _clamp(model.get("ready_evidence", 0)))
    reasons = []
    if p1: reasons.append("P1_GAPS_PRESENT")
    if p2: reasons.append("P2_GAPS_PRESENT")
    if shared_doc: reasons.append("SHARED_DOCUMENT_REUSE")
    return round(score, 6), reasons
