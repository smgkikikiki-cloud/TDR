"""Write plan, provenance and the VEHICLE_IDENTITY_CREATED event (SPEC §12.2, §14); finalize fills the deferred fields (SPEC §12.2)."""
from __future__ import annotations

import copy

from .fingerprint import sha


def build_plan(record: dict, subject: dict, members: list[dict], retired: list[str], extra_neighbors: list[dict], snapshot: dict, policy: dict) -> dict:
    ident, w = record["identity"], policy["writes"]
    cid, brand_id = ident["canonical_model_id"], ident["brand_id"]
    aliases = [{"provider": subject["provider"], "external_id": subject["entity_id"], "state": "ACTIVE", "relation": "ORIGIN"}]
    aliases += [{"provider": m["provider"], "external_id": m["entity_id"], "state": "ACTIVE", "relation": "ADDITIONAL"} for m in members[1:]]
    aliases += [{"provider": subject["provider"], "external_id": old, "state": "RETIRED", "relation": "RETIRED_PREDECESSOR"} for old in sorted(set(retired))]
    first_seen = min(m["first_seen_period"] for m in members)
    brand_rows = sorted([i["canonical_id"], i["identity_state"], i["deleted"]] for i in snapshot["identities"] if i["brand_id"] == brand_id)
    pre = [{"kind": "brand_exists", "brand_id": brand_id}, {"kind": "canonical_id_absent", "canonical_id": cid},
           {"kind": "slug_absent", "slug": ident["slug"]}, {"kind": "identity_key_absent", "brand_id": brand_id, "identity_key": ident["identity_key"]}]
    pre += [{"kind": "alias_absent_or_same", "provider": a["provider"], "external_id": a["external_id"], "canonical_id": cid} for a in aliases]
    pre.append({"kind": "brand_identity_digest", "brand_id": brand_id, "digest": sha(brand_rows)})

    def key(op: str) -> str:
        return sha({"op": op, "cid": cid, "x": None})

    basis = record["evidence_basis"]
    provenance = {"canonical_id": cid, "provider": subject["provider"], "external_id": subject["entity_id"], "source_version": record["source_version"],
                  "first_seen_period": first_seen, "reason_codes": record["reason_codes"], "decision_fingerprint": record["fingerprints"]["decision"],
                  "evidence_tier": basis["tier"], "evidence_kinds": basis["kinds"], "evidence_refs": basis["refs"], "policy_version": policy["version"],
                  "contract_version": 1, "creator_type": record["creator_type"], "identity_key": ident["identity_key"], "apply_mode": w["apply_mode"],
                  "run_id": None, "created_at": None, "actor": None}
    ev = policy["event"]
    event = {"event_type": ev["name"], "event_version": ev["version"], "event_id": sha({"event": ev["name"], "v": ev["version"], "cid": cid}),
             "canonical_model_id": cid, "canonical_name": ident["canonical_name"], "brand_id": brand_id,
             "identity_state": ident["identity_state"], "enrichment_state": ident["enrichment_state"],
             "source": {"provider": subject["provider"], "external_id": subject["entity_id"], "source_version": record["source_version"], "first_seen_period": first_seen},
             "aliases": [{"provider": a["provider"], "external_id": a["external_id"], "relation": a["relation"]} for a in aliases],
             "creation": {"reason_codes": record["reason_codes"], "decision_fingerprint": record["fingerprints"]["decision"], "creator_type": record["creator_type"],
                          "evidence": {"tier": basis["tier"], "kinds": basis["kinds"], "refs": basis["refs"]}, "policy_version": policy["version"],
                          "contract_version": 1, "apply_mode": w["apply_mode"]},
             "enrichment_hints": {"known_names": sorted({m["display_name"] for m in members} | {ident["canonical_name"]}),
                                  "excluded_neighbors": sorted(extra_neighbors, key=lambda x: x["canonical_id"]),
                                  "provider_hints": copy.deepcopy(subject.get("provider_hints", {})) if ev["include_provider_hints"] else {}},
             "occurred_at": None}
    values = {c: {"canonical_id": cid, "brand_id": brand_id, "slug": ident["slug"], "name_en": ident["canonical_name"],
                  "identity_state": ident["identity_state"], "enrichment_state": ident["enrichment_state"]}[c] for c in w["shell_columns"]}
    ops = [{"op": "RESERVE_CANONICAL_ID", "idempotency_key": key("RESERVE"), "values": {"canonical_id": cid, "slug": ident["slug"], "identity_key": ident["identity_key"], "brand_id": brand_id}},
           {"op": "INSERT_IDENTITY_SHELL", "idempotency_key": key("SHELL"), "table": "vehicle_models", "values": values},
           {"op": "INSERT_EXTERNAL_ALIAS", "idempotency_key": key("ALIAS"), "table": "vehicle_identity_aliases", "rows": [{**a, "canonical_id": cid} for a in aliases]},
           {"op": "INSERT_PROVENANCE", "idempotency_key": key("PROVENANCE"), "table": "vehicle_identity_provenance", "values": provenance},
           {"op": "ENQUEUE_EVENT", "idempotency_key": key("EVENT"), "table": ev["outbox"], "values": {"event_id": event["event_id"]}},
           {"op": "PROPOSE_ORIGIN_MAPPING", "idempotency_key": key("MAPPING"),
            "values": {"provider": subject["provider"], "subject_id": subject["entity_id"], "canonical_id": cid, "state": "AUTO", "method": "ORIGIN"}}]
    plan = {"apply_mode": w["apply_mode"], "actor_kind": w["actor_kind"], "required_permission": w["required_permission"],
            "lock_key": w["lock_key"].format(brand_id=brand_id), "preconditions": pre, "operations": ops, "event": event,
            "deferred_fields": ["provenance.run_id", "provenance.created_at", "provenance.actor", "event.occurred_at", "event.creation.run_id"]}
    return {"plan_id": sha(plan), **plan}


def finalize(decision: dict, invocation: dict) -> dict:
    """The only place a run id or timestamp enters. Fills the deferred fields and nothing else."""
    out = copy.deepcopy(decision)
    plan = out["write_plan"]
    if plan is None:
        raise ValueError("only a CREATE_IDENTITY has a plan to finalize")
    for op in plan["operations"]:
        if op["op"] == "INSERT_PROVENANCE":
            op["values"].update({"run_id": invocation["run_id"], "created_at": invocation["created_at"], "actor": invocation["actor"]})
    plan["event"]["occurred_at"] = invocation["created_at"]
    plan["event"]["creation"]["run_id"] = invocation["run_id"]
    return out
