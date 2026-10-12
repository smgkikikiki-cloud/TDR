"""Model/document-level queues with independent ranked priorities."""
from __future__ import annotations

import hashlib
import json

from .eligibility import evaluate_model
from .gap_inventory import gaps_for_model
from .prioritizer import audit_scores, registration_relevance, spec_score
from .validation import validate_fixture, validate_plan, validate_policy


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _job_key(policy: dict, model: dict, work_kind: str, generations: list[str],
             field_plan: dict, trim_ids: tuple[str, ...], owner_set: dict | None,
             trim_scope: list[dict]) -> str:
    """Hash only the semantic inputs of this job, never the full catalog snapshot."""
    identity = {
        "contract_version": policy["schema_version"],
        "model_id": model["id"],
        "model_status": model.get("status"),
        "work_kind": work_kind,
        "generation_ids": sorted(generations),
        "trim_ids": sorted(trim_ids),
        "trim_scope": sorted(trim_scope, key=lambda x: x["id"]),
        "field_plan": field_plan if work_kind == "SPEC_ENRICH" else {},
        "owner_set": ({"trim_ids":sorted(owner_set.get("trim_ids", [])),"revision":owner_set.get("revision")}
                      if owner_set else None),
        "lineup_evidence": model.get("lineup_evidence"),
        "source_bundle_hash": model.get("document_bundle_hash"),
        "field_registry_version": model.get("field_registry_version", "fixture-registry"),
    }
    return _canonical_hash(identity)


def _rank_retail(rows: list[dict], models: dict[str, dict], policy: dict) -> list[dict]:
    rows.sort(key=lambda x: (-x["score"], x["model_id"]))
    q = policy["queue_policy"]
    audit_cycle = int(q["audit_anti_starvation_cycle_size"])
    quota = int(q["audit_anti_starvation_slots_per_cycle"])
    if quota == 0: return rows
    field = q["underrepresented_cohort_field"]
    protected = [r for r in rows if models[r["model_id"]].get(field) == "UNDERREPRESENTED"]
    ordinary = [r for r in rows if models[r["model_id"]].get(field) != "UNDERREPRESENTED"]
    out = []
    while ordinary or protected:
        # Reserve the configured number of positions in each audit cycle.
        out.extend(ordinary[:audit_cycle - quota])
        ordinary = ordinary[audit_cycle - quota:]
        out.extend(protected[:quota])
        protected = protected[quota:]
        if not protected and ordinary and len(ordinary) < audit_cycle - quota:
            out.extend(ordinary)
            ordinary = []
    return out


def _fair_merge(retail: list[dict], spec: list[dict], policy: dict) -> list[dict]:
    """Merge ranked queues in finite cycles so either work kind gets service."""
    cycle = int(policy["queue_policy"]["cycle_size"])
    spec_slots = int(policy["queue_policy"]["spec_enrich_slots_per_cycle"])
    out, ri, si = [], 0, 0
    while ri < len(retail) or si < len(spec):
        cycle_spec = min(spec_slots, len(spec) - si, cycle)
        cycle_retail = min(cycle - cycle_spec, len(retail) - ri)
        leftover = cycle - cycle_spec - cycle_retail
        if leftover > 0:
            add_spec = min(leftover, len(spec) - si - cycle_spec)
            cycle_spec += add_spec
            leftover -= add_spec
        if leftover > 0:
            cycle_retail += min(leftover, len(retail) - ri - cycle_retail)
        # Retail audit P0 entries lead each cycle; an eligible spec P1 is still
        # scheduled in the same finite cycle under any size of audit backlog.
        out.extend(retail[ri:ri + cycle_retail]); ri += cycle_retail
        out.extend(spec[si:si + cycle_spec]); si += cycle_spec
    return out


def plan(snapshot: dict, policy: dict, *, budget: int | None = None) -> dict:
    validate_policy(policy)
    validate_fixture(snapshot)
    if budget is not None and budget < 0:
        raise ValueError("budget must be >= 0")
    models = sorted(snapshot["models"], key=lambda x: x["id"])
    by_model = {m["id"]: m for m in models}
    scores = audit_scores(models, snapshot.get("registration_signals", []), policy)
    relevance = registration_relevance(models, snapshot.get("registration_signals", []))
    decisions, retail_queue, spec_queue = [], [], []

    for model in models:
        result = evaluate_model(snapshot, model)
        owner_set = next((s for s in snapshot.get("current_retail_sets", [])
                          if s.get("model_id") == model["id"]), None)
        trim_decisions = []
        for trim in sorted((t for t in snapshot["trims"] if t.get("model_id") == model["id"]), key=lambda t: t["id"]):
            if trim["id"] in result.conflicting_trim_ids:
                if trim.get("deleted_at"): reason = "OWNER_SET_DELETED_CONFLICT"
                elif trim.get("status") == "HISTORICAL": reason = "OWNER_SET_HISTORICAL_CONFLICT"
                elif trim.get("admin_retired") or trim.get("owner_retired"): reason = "OWNER_SET_RETIRED_CONFLICT"
                else: reason = "OWNER_SET_UNVERIFIED_CONFLICT"
                disposition = "REVIEW"
            elif trim.get("admin_retired") or trim.get("owner_retired"):
                reason, disposition = "ADMIN_LIFECYCLE_WINS", "EXCLUDED_ADMIN_RETIRED"
            elif result.decision in {"EXCLUDED_HISTORICAL", "EXCLUDED_UPCOMING", "EXCLUDED_DISCOVERED", "EXCLUDED_ADMIN_RETIRED"}:
                reason, disposition = result.decision, result.decision
            elif owner_set is not None:
                reason = "OWNER_CURRENT_SET" if trim["id"] in owner_set.get("trim_ids", []) else "NOT_IN_OWNER_SET"
                disposition = "ELIGIBLE_ENRICH" if trim["id"] in result.admitted_trim_ids else "EXCLUDED_NON_MEMBER"
                if trim.get("status") == "HISTORICAL":
                    reason, disposition = "HISTORICAL_NOT_ENRICHED", "EXCLUDED_HISTORICAL"
                elif trim.get("status") == "UNVERIFIED":
                    reason, disposition = "RETAIL_UNVERIFIED", "RETAIL_AUDIT_ONLY"
            elif result.decision == "ELIGIBLE_ENRICH" and trim["id"] in result.admitted_trim_ids:
                reason, disposition = "COMPLETE_LINEUP_EVIDENCE", "ELIGIBLE_ENRICH"
            elif result.decision == "RETAIL_AUDIT_ONLY":
                reason, disposition = result.reasons[0], "RETAIL_AUDIT_ONLY"
            elif trim.get("status") == "HISTORICAL":
                reason, disposition = "HISTORICAL_EXCLUDED", "EXCLUDED_HISTORICAL"
            elif trim.get("status") == "UNVERIFIED":
                reason, disposition = "RETAIL_UNVERIFIED", "RETAIL_AUDIT_ONLY"
            else:
                reason, disposition = "NOT_ADMITTED", "HOLD_IDENTITY"
            trim_decisions.append({"trim_id": trim["id"], "decision": disposition, "reason_code": reason})

        work_kind = "RETAIL_AUDIT" if result.decision == "RETAIL_AUDIT_ONLY" else None
        gap_data = None
        if result.decision == "ELIGIBLE_ENRICH":
            gap_data = gaps_for_model(snapshot, result.admitted_trim_ids)
            if gap_data["groups"]: work_kind = "SPEC_ENRICH"
        decisions.append({"schema_version":"0.1","model_id":model["id"],"eligibility":result.decision,
                          "reason_codes":list(result.reasons),"work_kind":work_kind,
                          "review_required":"MODEL_REVIEW_REQUIRED" in result.reasons,
                          "trim_decisions":trim_decisions})
        if not work_kind: continue

        groups = sorted(gap_data["groups"]) if work_kind == "SPEC_ENRICH" else []
        field_plan = gap_data["groups"] if work_kind == "SPEC_ENRICH" else {}
        if work_kind == "RETAIL_AUDIT":
            score, tier = scores.get(model["id"], 0.0), "P0"
            reasons = list(result.reasons)
            if relevance.get(model["id"], 0) >= policy["priority_policy"]["high_market_relevance_threshold"]:
                reasons.append("HIGH_MARKET_RELEVANCE")
            if model.get("registration_series") and model["id"] in relevance:
                reasons.append(f"REGISTRATION_PRIORITY_{model['registration_series']}")
        else:
            score, reasons = spec_score(model, gap_data, bool(model.get("shared_document_available")), policy)
            all_tiers = {tier for group in field_plan.values() for tier in group["tiers"]}
            tier = "P1" if "P1" in all_tiers else "P2"
            reasons.extend(result.reasons)
            if result.conflicting_trim_ids: reasons.append("MODEL_REVIEW_REQUIRED")
        item = {"schema_version":"0.1","model_id":model["id"],"generation_ids":list(result.generation_ids),
                "work_kind":work_kind,"eligibility":result.decision,"tier":tier,"score":score,
                "reason_codes":sorted(set(reasons)),"field_groups":groups,"field_plan":field_plan,
                "document_bundle_key":f"model:{model['id']}:official-th",
                "execution_mode":"MOCK","status":"PLANNED","max_queries":0,
                "registration_is_evidence":False}
        task_trims = result.admitted_trim_ids if work_kind == "SPEC_ENRICH" else tuple(sorted(
            t["id"] for t in snapshot["trims"] if t.get("model_id") == model["id"]
            and t.get("generation_id") in result.generation_ids and not t.get("deleted_at")))
        trim_scope = [{key:t.get(key) for key in ("id","generation_id","status","powertrain","variant_id","revision","admin_retired","owner_retired")}
                      for t in snapshot["trims"] if t["id"] in set(task_trims)]
        item["job_key"] = _job_key(policy, model, work_kind, list(result.generation_ids), field_plan,
                                   task_trims, owner_set, trim_scope)
        (retail_queue if work_kind == "RETAIL_AUDIT" else spec_queue).append(item)

    retail_queue = _rank_retail(retail_queue, by_model, policy)
    tier_order = {"P1":0,"P2":1,"P0":2}
    spec_queue.sort(key=lambda x:(tier_order[x["tier"]],-x["score"],x["model_id"],x["document_bundle_key"]))
    # --budget caps each independent queue. It does not let backlog in one queue
    # consume the other queue's allowance.
    if budget is not None:
        retail_queue, spec_queue = retail_queue[:budget], spec_queue[:budget]
    queues = {"RETAIL_AUDIT":retail_queue,"SPEC_ENRICH":spec_queue}
    queue = _fair_merge(retail_queue, spec_queue, policy)
    result = {"queue":queue,"queues":queues,
              "decisions":sorted(decisions,key=lambda x:x["model_id"]),
              "summary":{"execution_mode":"MOCK","models_seen":len(models),"planned_items":len(queue),
                         "retail_audit_items":len(retail_queue),"spec_enrich_items":len(spec_queue),
                         "paid_model_calls":0,"paid_tokens":0,"external_http_calls":0,
                         "production_writes":0,"cron_enabled":False}}
    validate_plan(result)
    return result
