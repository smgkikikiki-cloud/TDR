"""Shared loaders and the corpus case runner for the Identity Bootstrap contract tests (no fixtures; no conftest)."""
from __future__ import annotations

import copy
import functools
from pathlib import Path

from identity_bootstrap.contract import loader, schema_subset

import ib_reference as ref

IB_ROOT = Path(__file__).resolve().parents[2] / "identity_bootstrap"
CONTRACT_DIR = IB_ROOT / "contract" / "v1"
OUTCOMES = ["CREATE_IDENTITY", "IDENTITY_REVIEW", "HOLD"]


@functools.lru_cache(maxsize=None)
def policy() -> dict:
    return loader.load_policy()


@functools.lru_cache(maxsize=None)
def registry() -> dict:
    return loader.load_reason_codes()


@functools.lru_cache(maxsize=None)
def taxonomy() -> dict:
    return loader.load_taxonomy()


@functools.lru_cache(maxsize=None)
def lifecycle() -> dict:
    return loader.load_lifecycle()


@functools.lru_cache(maxsize=None)
def schemas() -> dict:
    return loader.load_schema_registry()


@functools.lru_cache(maxsize=None)
def cases() -> list:
    return loader.load_cases()


def case_by_id(case_id: str) -> dict:
    return next(c for c in cases() if c["id"] == case_id)


def kind(name: str) -> list:
    return [c for c in cases() if c["kind"] == name]


def codes() -> dict:
    return registry()["codes"]


def spec_text() -> str:
    return (CONTRACT_DIR / "SPEC.md").read_text(encoding="utf-8")


def validate_input(snapshot: dict) -> list[str]:
    return schema_subset.validate(snapshot, schemas()["input.schema.json"], registry=schemas())


def validate_decision(record: dict) -> list[str]:
    return schema_subset.validate(record, schemas()["decision.schema.json"], registry=schemas())


def run_decide(snapshot: dict, pol: dict | None = None) -> list[dict]:
    return ref.decide(snapshot, pol or policy(), registry())


def by_subject(decisions: list[dict]) -> dict[str, dict]:
    return {f"{d['subject']['provider']}:{d['subject']['entity_id']}": d for d in decisions}


def project(decision: dict) -> dict:
    """The observable fields a corpus expectation may assert, in the corpus's own vocabulary."""
    plan = decision["write_plan"]
    ident = decision["identity"]
    event = plan["event"] if plan else None
    return {
        "outcome": decision["outcome"], "primary_reason": decision["primary_reason"], "reason_codes": decision["reason_codes"],
        "canonical_model_id": ident and ident["canonical_model_id"], "canonical_name": ident and ident["canonical_name"],
        "slug": ident and ident["slug"], "identity_state": ident and ident["identity_state"],
        "enrichment_state": ident and ident["enrichment_state"], "creator_type": decision["creator_type"],
        "evidence_tier": decision["evidence_basis"]["tier"], "queue": decision["review"]["queue"],
        "priority_band": decision["review"]["priority_band"], "alert": decision["review"]["alert"],
        "aliases": event and [[a["provider"], a["external_id"], a["relation"]] for a in event["aliases"]],
        "first_seen_period": event and event["source"]["first_seen_period"],
        "existing_identity": decision["existing_identity"],
        "suggested_binding_reason": decision["suggested_binding"] and decision["suggested_binding"]["reason"],
        "cleared_flags": [[c["code"], c["cleared_by"]] for c in decision["evidence_basis"]["cleared_flags"]],
        "excluded_neighbors": event and [n["canonical_id"] for n in event["enrichment_hints"]["excluded_neighbors"]],
        "batch_group_size": len(decision["batch_group"]),
        "write_plan": plan is not None,
        "event_type": event and event["event_type"],
        "outbox_table": plan and next(o["table"] for o in plan["operations"] if o["op"] == "ENQUEUE_EVENT"),
        "apply_mode": plan and plan["apply_mode"],
        "lock_key": plan and plan["lock_key"],
        "shell_columns": plan and sorted(next(o["values"] for o in plan["operations"] if o["op"] == "INSERT_IDENTITY_SHELL")),
        "provider_hints": event and event["enrichment_hints"]["provider_hints"],
        "precondition_kinds": plan and [p["kind"] for p in plan["preconditions"]],
    }


def check_decide_case(case: dict) -> list[str]:
    problems: list[str] = []
    exp = case["expect"]
    try:
        out = by_subject(run_decide(case["input"]))
    except ref.Refusal as refusal:
        return [] if exp.get("refusal") == refusal.code else [f"{case['id']}: refused with {refusal.code}, expected {exp}"]
    if "refusal" in exp:
        return [f"{case['id']}: expected refusal {exp['refusal']}, got decisions"]
    if set(out) != set(exp["decisions"]):
        return [f"{case['id']}: subjects {sorted(out)} != expected {sorted(exp['decisions'])}"]
    for sid, want in exp["decisions"].items():
        got = project(out[sid])
        for key, value in want.items():
            if got[key] != value:
                problems.append(f"{case['id']} {sid} {key}: expected {value!r}, got {got[key]!r}")
    return problems


def snapshot_after(base: dict, store: ref.Store) -> dict:
    snap = copy.deepcopy(base)
    snap["identities"], snap["bindings"] = store.as_snapshot_parts()
    return snap


def run_apply_case(case: dict) -> list[str]:
    base = case_by_id(case["input"]["base"])["input"]
    store = ref.Store(base["identities"], base["bindings"])
    results: list[str | None] = []
    for step in case["input"]["steps"]:
        if step["do"] == "insert_identity":
            store.identities[step["identity"]["canonical_id"]] = dict(step["identity"])
            results.append(None)
        elif step["do"] == "insert_alias":
            a = step["alias"]
            store.aliases[(a["provider"], a["external_id"])] = (a["canonical_id"], a["state"])
            results.append(None)
        elif step["do"] == "apply":
            decision = by_subject(run_decide(case_by_id(step["case"])["input"]))[step["subject"]]
            assert decision["outcome"] == "CREATE_IDENTITY", f"{case['id']}: {step['case']} {step['subject']} is not a CREATE"
            results.append(store.apply(ref.finalize(decision, {"run_id": "run-1", "created_at": "2026-10-10T00:00:00Z", "actor": "bootstrap"})))
    problems = []
    exp = case["expect"]
    if results != exp["results"]:
        problems.append(f"{case['id']}: results {results} != {exp['results']}")
    counts = {"identities": len(store.identities), "events": len(store.events), "aliases": len(store.aliases),
              "provenance": len(store.provenance), "mappings": len(store.mappings)}
    for key, value in exp.get("counts", {}).items():
        if counts[key] != value:
            problems.append(f"{case['id']}: {key} {counts[key]} != {value}")
    for sid, want in exp.get("redecide", {}).items():
        snap = snapshot_after(base, store)
        got = project(by_subject(run_decide(snap))[sid])
        for key, value in want.items():
            if got[key] != value:
                problems.append(f"{case['id']} redecide {sid} {key}: expected {value!r}, got {got[key]!r}")
    return problems


def run_allocate_case(case: dict) -> list[str]:
    inp, exp = case["input"], case["expect"]
    name = ref.canonical_name(inp["display_name"], inp["spellings"], policy())
    got = ref.allocate(inp["brand_id"], name, inp["identities"], policy())
    got["canonical_name"] = name
    return [f"{case['id']} {k}: expected {v!r}, got {got.get(k)!r}" for k, v in exp.items() if got.get(k) != v]


def run_lifecycle_case(case: dict) -> list[str]:
    inp, exp = case["input"], case["expect"]
    got = ref.transition(lifecycle(), inp["from"], inp["to"], inp["actor"])
    return [f"{case['id']} {k}: expected {v!r}, got {got.get(k)!r}" for k, v in exp.items() if got.get(k) != v]


RUNNERS = {"decide": check_decide_case, "apply": run_apply_case, "allocate": run_allocate_case, "lifecycle": run_lifecycle_case}
