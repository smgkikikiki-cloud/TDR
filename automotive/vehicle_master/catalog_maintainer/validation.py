"""Runtime validation for normalized offline inputs and simulator outputs."""
from __future__ import annotations

from datetime import date
import re

VALUE_STATES = {"KNOWN", "UNKNOWN", "NOT_AVAILABLE", "NOT_APPLICABLE", "ABSENT", None}
TIERS = {"P0", "P1", "P2", "P3"}
HEX64 = re.compile(r"^[a-f0-9]{64}$")


def validate_policy(policy: dict) -> None:
    p = policy.get("priority_policy", {})
    for key in ("audit_weights", "spec_weights"):
        weights = p.get(key, {})
        if not weights or any(float(v) < 0 for v in weights.values()) or abs(sum(weights.values()) - 1) > 1e-9:
            raise ValueError(f"policy priority_policy.{key} must be nonnegative weights summing to 1")
    if abs(sum(p.get("spec_missingness_weights", {}).values()) - 1) > 1e-9:
        raise ValueError("policy spec_missingness_weights must sum to 1")
    q = policy.get("queue_policy", {})
    if int(q.get("cycle_size", 0)) < 2:
        raise ValueError("queue_policy.cycle_size must be >= 2 to serve both queues")
    slots = int(q.get("spec_enrich_slots_per_cycle", -1))
    if slots < 1 or slots >= q["cycle_size"]:
        raise ValueError("spec_enrich_slots_per_cycle must leave at least one slot for each queue")
    audit_cycle = int(q.get("audit_anti_starvation_cycle_size", 0))
    audit_slots = int(q.get("audit_anti_starvation_slots_per_cycle", -1))
    if audit_cycle <= 0 or audit_slots < 0 or audit_slots >= audit_cycle:
        raise ValueError("invalid Retail Audit anti-starvation cycle/slot policy")
    for path in ("allow_external_http", "allow_paid_ai", "allow_paid_search", "enable_prod_writer", "enable_cron"):
        if policy["autonomy"].get(path) is not False:
            raise ValueError(f"autonomy.{path} must remain false in MOCK")
    for path in ("max_paid_tokens", "max_paid_model_calls", "max_paid_spend_thb"):
        if policy["autonomy"].get(path) != 0:
            raise ValueError(f"autonomy.{path} must remain zero in MOCK")


def validate_fixture(snapshot: dict) -> None:
    required = {"schema_version", "as_of", "models", "generations", "trims", "facts", "field_registry"}
    missing = required - snapshot.keys()
    if missing: raise ValueError(f"fixture missing required keys: {sorted(missing)}")
    if snapshot["schema_version"] != "0.1": raise ValueError("unsupported fixture schema_version")
    date.fromisoformat(snapshot["as_of"])
    for name in ("models", "generations", "trims", "facts", "field_registry", "current_retail_sets", "variants", "registration_signals"):
        if name in snapshot and not isinstance(snapshot[name], list): raise ValueError(f"{name} must be an array")
    _unique(snapshot["models"], "model")
    _unique(snapshot["generations"], "generation")
    _unique(snapshot["trims"], "trim")
    _unique(snapshot.get("variants", []), "variant")
    models = {m["id"]: m for m in snapshot["models"]}
    generations = {g["id"]: g for g in snapshot["generations"]}
    trims = {t["id"]: t for t in snapshot["trims"]}
    for model in models.values():
        if model.get("status") not in {"CURRENT", "HISTORICAL", "UPCOMING", "DISCOVERED", "UNVERIFIED"}:
            raise ValueError(f"invalid model status for {model['id']}")
        e = model.get("lineup_evidence")
        if e:
            if e.get("market") != "TH" or e.get("source_authority") != "OFFICIAL":
                raise ValueError(f"lineup evidence must be official Thai-market evidence: {model['id']}")
            if e.get("completeness") not in {"COMPLETE_LINEUP", "PARTIAL_TRIM_LIST", "INDIVIDUAL_TRIM"}:
                raise ValueError(f"invalid lineup completeness: {model['id']}")
            if not HEX64.fullmatch(str(e.get("document_sha256", ""))):
                raise ValueError(f"lineup evidence needs SHA-256: {model['id']}")
            date.fromisoformat(e.get("captured_at", ""))
            if not isinstance(e.get("trim_ids"), list) or any(tid not in trims for tid in e["trim_ids"]):
                raise ValueError(f"lineup evidence trim_ids must reference existing trims: {model['id']}")
            if e.get("completeness") == "COMPLETE_LINEUP":
                manifest, proof = e.get("capture_manifest"), e.get("completeness_evidence")
                if not isinstance(manifest, dict) or not isinstance(proof, dict):
                    raise ValueError(f"complete lineup requires capture_manifest and completeness_evidence: {model['id']}")
                if (manifest.get("pagination_complete") is not True or type(manifest.get("source_page_count")) is not int
                        or manifest.get("source_page_count", 0) < 1 or type(manifest.get("row_count")) is not int
                        or manifest.get("row_count", 0) < 1 or manifest.get("row_count") != len(e["trim_ids"])
                        or manifest.get("listed_trim_ids") != e["trim_ids"]):
                    raise ValueError(f"complete lineup capture manifest is incomplete or inconsistent: {model['id']}")
                if (proof.get("publisher_declared_complete") is not True or not proof.get("quote")
                        or not str(proof.get("locator", "")).startswith("line:")
                        or proof.get("capture_status") != "COMPLETE"
                        or type(proof.get("expected_page_count")) is not int
                        or proof.get("expected_page_count", 0) < 1
                        or proof.get("expected_page_count") != proof.get("captured_page_count")):
                    raise ValueError(f"complete lineup requires explicit publisher completeness evidence: {model['id']}")
        if model.get("registration_series") and (model.get("registration_series") not in {"RY1", "RY3"}
                                                  or not model.get("registration_stratum")):
            raise ValueError("registration series requires an RY1/RY3 series and a comparable stratum")
    for gen in generations.values():
        if gen.get("model_id") not in models: raise ValueError(f"generation has unknown model: {gen['id']}")
    for trim in trims.values():
        if trim.get("model_id") not in models or trim.get("generation_id") not in generations:
            raise ValueError(f"trim has unknown parent: {trim['id']}")
        if generations[trim["generation_id"]].get("model_id") != trim["model_id"]:
            raise ValueError(f"trim model/generation mismatch: {trim['id']}")
        if trim.get("status") not in {"CURRENT", "UNVERIFIED", "HISTORICAL"}:
            raise ValueError(f"invalid trim status: {trim['id']}")
    for retail_set in snapshot.get("current_retail_sets", []):
        if retail_set.get("model_id") not in models or not isinstance(retail_set.get("trim_ids"), list):
            raise ValueError("invalid current_retail_set shape")
        if any(tid not in trims or trims[tid].get("model_id") != retail_set["model_id"] for tid in retail_set["trim_ids"]):
            raise ValueError("current_retail_set references an unknown or foreign trim")
    _unique(snapshot["field_registry"], "field", key="key")
    for field in snapshot["field_registry"]:
        if field.get("tier") not in TIERS or not field.get("group"):
            raise ValueError(f"invalid field registry row: {field}")
    for fact in snapshot["facts"]:
        if fact.get("trim_id") not in trims: raise ValueError("fact references unknown trim")
        if fact.get("value_state") not in VALUE_STATES: raise ValueError("invalid Vehicle Master value_state")
        if fact.get("verification_status") not in {"VERIFIED", "PROVISIONAL", None}:
            raise ValueError("verification_status is distinct and must be VERIFIED or PROVISIONAL")
        if fact.get("value_state") == "KNOWN" and fact.get("value") is None:
            raise ValueError("KNOWN facts require a non-null value")
        if fact.get("value_state") is None and not (fact.get("locked") and fact.get("value") is None):
            raise ValueError("null value_state is reserved for locked null tombstones")
        for d in (fact.get("effective_from"), fact.get("effective_to")):
            if d: date.fromisoformat(d)
    for signal in snapshot.get("registration_signals", []):
        if signal.get("model_id") not in models: raise ValueError("registration signal has unknown model")
        if signal.get("series") not in {"RY1", "RY3"}: raise ValueError("registration series must be RY1 or RY3")
        if signal.get("source_class", "MODEL") not in {"MODEL", "*"}: raise ValueError("invalid registration source_class")
        date.fromisoformat(signal.get("period", "") + "-01")


def validate_plan(result: dict) -> None:
    required = {"queue", "queues", "decisions", "summary"}
    if required - result.keys(): raise ValueError("plan output is missing contract sections")
    for kind in ("RETAIL_AUDIT", "SPEC_ENRICH"):
        for row in result["queues"][kind]:
            if row.get("work_kind") != kind or not HEX64.fullmatch(str(row.get("job_key", ""))) or row.get("registration_is_evidence") is not False:
                raise ValueError(f"invalid queue item contract: {kind}")
            if row.get("execution_mode") != "MOCK" or row.get("max_queries") != 0:
                raise ValueError("queue item escaped MOCK zero-query policy")
            if row.get("tier") not in {"P0", "P1", "P2"} or not 0 <= row.get("score", -1) <= 1:
                raise ValueError("queue item priority is out of contract")
            if row.get("status") != "PLANNED" or row.get("field_plan") is None:
                raise ValueError("queue item status/field_plan is invalid")
            if kind == "SPEC_ENRICH":
                for group in row["field_plan"].values():
                    if not set(group.get("tiers", [])) <= {"P1", "P2"}:
                        raise ValueError("Spec Enrichment may contain only P1/P2 fields")
    seen = {item["job_key"] for kind in result["queues"].values() for item in kind}
    if len(seen) != sum(len(kind) for kind in result["queues"].values()):
        raise ValueError("duplicate job_key in queue output")
    merged_keys = [x["job_key"] for x in result["queue"]]
    queue_keys = [x["job_key"] for kind in result["queues"].values() for x in kind]
    if len(merged_keys) != len(queue_keys) or set(merged_keys) != set(queue_keys):
        raise ValueError("merged queue does not preserve independent queue items")
    model_ids = [x.get("model_id") for x in result["decisions"]]
    if len(model_ids) != len(set(model_ids)):
        raise ValueError("decision output must contain one model decision per model")
    for decision in result["decisions"]:
        if not isinstance(decision.get("review_required"), bool) or not isinstance(decision.get("trim_decisions"), list):
            raise ValueError("decision output contract is invalid")
        if decision.get("eligibility") not in {"ELIGIBLE_ENRICH","RETAIL_AUDIT_ONLY","EXCLUDED_HISTORICAL",
                                                 "EXCLUDED_UPCOMING","EXCLUDED_DISCOVERED","EXCLUDED_ADMIN_RETIRED","HOLD_IDENTITY"}:
            raise ValueError("unknown model eligibility outcome")
        for trim in decision["trim_decisions"]:
            if not trim.get("trim_id") or not trim.get("reason_code") or trim.get("decision") not in {
                "ELIGIBLE_ENRICH","RETAIL_AUDIT_ONLY","EXCLUDED_HISTORICAL","EXCLUDED_UPCOMING",
                "EXCLUDED_DISCOVERED","EXCLUDED_ADMIN_RETIRED","EXCLUDED_NON_MEMBER","HOLD_IDENTITY","REVIEW"}:
                raise ValueError("invalid trim decision contract")
    if result["summary"].get("retail_audit_items") != len(result["queues"]["RETAIL_AUDIT"]):
        raise ValueError("Retail Audit summary count mismatch")
    if result["summary"].get("spec_enrich_items") != len(result["queues"]["SPEC_ENRICH"]):
        raise ValueError("Spec Enrichment summary count mismatch")
    if result["summary"].get("production_writes") != 0 or result["summary"].get("paid_tokens") != 0:
        raise ValueError("unsafe output budget values")


def _unique(rows: list[dict], label: str, *, key: str = "id") -> None:
    ids = [row.get(key) for row in rows]
    if None in ids or len(ids) != len(set(ids)):
        raise ValueError(f"{label} identifiers must be present and unique")


