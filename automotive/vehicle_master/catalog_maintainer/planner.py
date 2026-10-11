"""Model/document-level queue planning; never emits a task per missing cell."""
from __future__ import annotations

import hashlib
import json

from .eligibility import evaluate_model
from .gap_inventory import gaps_for_model
from .prioritizer import audit_scores, spec_score


def _stable_key(parts: list[object]) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()


def plan(snapshot: dict, policy: dict, *, budget: int | None = None) -> dict:
    autonomy = policy["autonomy"]
    if any((autonomy.get("allow_external_http"), autonomy.get("allow_paid_ai"),
            autonomy.get("allow_paid_search"), autonomy.get("enable_prod_writer"), autonomy.get("enable_cron"),
            autonomy.get("max_paid_tokens", 0), autonomy.get("max_paid_model_calls", 0))):
        raise ValueError("unsafe policy: simulator requires HTTP, paid calls, writer, and cron disabled")
    if budget is not None and budget < 0:
        raise ValueError("budget must be >= 0")
    models = sorted(snapshot.get("models", []), key=lambda x: x["id"])
    scores = audit_scores(models, snapshot.get("registration_signals", []))
    decisions, items = [], []
    for model in models:
        result = evaluate_model(snapshot, model)
        work_kind = "RETAIL_AUDIT" if result.decision == "RETAIL_AUDIT_ONLY" else None
        owner_set = next((s for s in snapshot.get("current_retail_sets", []) if s.get("model_id") == model["id"]), None)
        trim_decisions = []
        for trim in sorted((t for t in snapshot.get("trims", []) if t.get("model_id") == model["id"]), key=lambda t: t["id"]):
            if trim.get("admin_retired"):
                disposition = "EXCLUDED_ADMIN_RETIRED"
            elif result.decision in {"EXCLUDED_HISTORICAL", "EXCLUDED_UPCOMING", "EXCLUDED_DISCOVERED"}:
                disposition = result.decision
            elif owner_set is not None:
                disposition = "ELIGIBLE_ENRICH" if trim["id"] in owner_set.get("trim_ids", []) else "EXCLUDED_NON_MEMBER"
            elif result.decision == "ELIGIBLE_ENRICH" and trim["id"] in result.admitted_trim_ids:
                disposition = "ELIGIBLE_ENRICH"
            elif result.decision == "RETAIL_AUDIT_ONLY":
                disposition = "RETAIL_AUDIT_ONLY"
            elif trim.get("status") == "HISTORICAL":
                disposition = "EXCLUDED_HISTORICAL"
            else:
                disposition = "HOLD_IDENTITY"
            trim_decisions.append({"trim_id": trim["id"], "decision": disposition})
        gap_data = None
        if result.decision == "ELIGIBLE_ENRICH":
            gap_data = gaps_for_model(snapshot, result.admitted_trim_ids)
            if gap_data["groups"]:
                work_kind = "SPEC_ENRICH"
        decision = {"schema_version": "0.1", "model_id": model["id"], "eligibility": result.decision,
                    "reason_codes": list(result.reasons), "work_kind": work_kind,
                    "review_required": "OWNER_SET_CONFLICT_REVIEW_REQUIRED" in result.reasons,
                    "trim_decisions": trim_decisions}
        decisions.append(decision)
        if not work_kind:
            continue
        if work_kind == "RETAIL_AUDIT":
            score, tier, reasons = scores.get(model["id"], 0.0), "P0", list(result.reasons)
            if score >= .5: reasons.append("HIGH_MARKET_RELEVANCE")
            groups, gens = [], list(result.generation_ids)
        else:
            score, reasons = spec_score(model, gap_data, bool(model.get("shared_document_available")))
            tier = "P1" if any(x["tier"] == "P1" for x in gap_data["groups"].values()) else "P2"
            reasons += list(result.reasons)
            groups, gens = sorted(gap_data["groups"]), list(result.generation_ids)
        item = {"schema_version": "0.1", "model_id": model["id"], "generation_ids": gens,
                "work_kind": work_kind, "eligibility": result.decision, "tier": tier,
                "score": score, "reason_codes": sorted(set(reasons)), "field_groups": groups,
                "document_bundle_key": f"model:{model['id']}:official-th", "execution_mode": "MOCK",
                "status": "PLANNED", "max_queries": 0, "registration_is_evidence": False}
        item["job_key"] = _stable_key([policy["schema_version"], _stable_key([json.dumps(snapshot, sort_keys=True)]),
                                      item["model_id"], item["work_kind"], ",".join(groups), item["document_bundle_key"]])
        items.append(item)
    # P0 lineup audits first. Reserve one of every five audit slots for a cohort
    # explicitly tagged by the normalized input adapter as underrepresented.
    items.sort(key=lambda x: (0 if x["work_kind"] == "RETAIL_AUDIT" else 1,
                              -x["score"], x["model_id"], ",".join(x["field_groups"]), x["document_bundle_key"]))
    audits = [x for x in items if x["work_kind"] == "RETAIL_AUDIT"]
    other = [x for x in items if x["work_kind"] != "RETAIL_AUDIT"]
    protected = [x for x in audits if next(m for m in models if m["id"] == x["model_id"]).get("priority_cohort") == "UNDERREPRESENTED"]
    ordinary = [x for x in audits if x not in protected]
    scheduled = []
    while ordinary or protected:
        scheduled.extend(ordinary[:4])
        ordinary = ordinary[4:]
        if protected:
            scheduled.append(protected.pop(0))
        elif ordinary:
            scheduled.append(ordinary.pop(0))
    items = scheduled + other
    if budget is not None:
        items = items[:budget]
    return {"queue": items, "decisions": sorted(decisions, key=lambda x: x["model_id"]),
            "summary": {"execution_mode": "MOCK", "models_seen": len(models), "planned_items": len(items),
                        "retail_audit_items": sum(x["work_kind"] == "RETAIL_AUDIT" for x in items),
                        "spec_enrich_items": sum(x["work_kind"] == "SPEC_ENRICH" for x in items),
                        "paid_model_calls": 0, "paid_tokens": 0, "external_http_calls": 0,
                        "production_writes": 0, "cron_enabled": False}}
