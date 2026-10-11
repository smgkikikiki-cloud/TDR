"""Final reconciliation of the M7.0 shadow against PR #200's full relation export: parity, transitions, collisions, routing. Measurement only."""
from __future__ import annotations

import collections
import csv
import json
from pathlib import Path

from identity_bootstrap import routing
from identity_bootstrap.routing import signals

from . import activity_report, calibration, ir_export

BASELINE = calibration.HERE / "baseline_b132a86"
LINKING = ("EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV", "FUZZY")


def _dec(run: dict) -> dict[str, dict]:
    return {d["subject"]["entity_id"]: d for d in run["decisions"]}


def load_baseline() -> dict:
    with (BASELINE / "decisions.csv").open(encoding="utf-8", newline="") as fh:
        dec = {r["model_group_id"]: r for r in csv.DictReader(fh)}
    with (BASELINE / "create_adjudication.csv").open(encoding="utf-8", newline="") as fh:
        creates = {r["external_id"] for r in csv.DictReader(l for l in fh if not l.startswith("#"))}
    with (BASELINE / "dispatch_manifest.csv").open(encoding="utf-8", newline="") as fh:
        lanes = {r["external_id"]: r["lane"] for r in csv.DictReader(fh)}
    rel = json.loads((BASELINE / "relations.json").read_text(encoding="utf-8"))["relations"]
    return {"decisions": dec, "creates": creates, "lanes": lanes, "relations": rel, "summary": json.loads((BASELINE / "summary.json").read_text(encoding="utf-8"))}


# ---------------------------------------------------------------------------------------------------------------- parity
def relation_parity(A: dict, export: ir_export.RelationExport) -> dict:
    """Lexical relation parity: every relation in the snapshot Bootstrap saw IS the export's; the whole evaluated population was read; counts equal the manifest for all nine kinds."""
    subj = {s["entity_id"]: s for s in A["snapshot"]["subjects"]}
    seen_ii, seen_it, wrong = {}, {}, []
    for g, s in subj.items():
        for r in s["relations"]:
            if r["peer_kind"] == "SUBJECT":
                key = f"{g}|{r['peer_id']}"
                seen_ii[key] = r["name_relation"]
                want = export.ice_ice.get(key)
            else:
                key = f"{g}|{r['peer_id']}"
                seen_it[key] = r["name_relation"]
                want = export.ice_tdr.get(key)
            if want is None or want["r"] != r["name_relation"]:
                wrong.append(key)
    out = {"export_id": export.manifest["export_id"], "producer_commit": ir_export.PIN["producer_commit"]}
    for name, rows, seen, consulted in (("ice_ice", export.ice_ice, seen_ii, export.consulted_ice_ice), ("ice_tdr", export.ice_tdr, seen_it, export.consulted_ice_tdr)):
        passed_on = {k: r for k, r in rows.items() if r["r"] not in ("CONTRADICTION", "UNAVAILABLE")}
        counts = collections.Counter(r["r"] for r in rows.values())
        out[name] = {"evaluated_pairs": len(rows), "pairs_read_by_the_shadow": len(consulted), "all_pairs_read": consulted == set(rows),
                     "relations_passed_to_bootstrap": len(seen), "export_relations_not_passed_on": sorted(set(passed_on) - set(seen)),
                     "snapshot_relations_not_in_export_or_relabelled": sorted(k for k in seen if k not in rows or rows[k]["r"] != seen[k]),
                     "relation_counts_export": {k: counts.get(k, 0) for k in ir_export.RELATIONS},
                     "relation_counts_manifest": {k: export.manifest["populations"][name]["relation_counts"].get(k, 0) for k in ir_export.RELATIONS}}
        out[name]["counts_equal_manifest_for_all_nine_kinds"] = out[name]["relation_counts_export"] == out[name]["relation_counts_manifest"]
    out["snapshot_relations_wrong"] = sorted(set(wrong))
    return out


def pool_parity(A: dict, export: ir_export.RelationExport, si) -> dict:
    """Candidate-pool parity: the TDR candidates the shadow compared are exactly the export's pools, and the old stand-in candidate set (brand-family models) is reported against them."""
    subj = {s["entity_id"]: s for s in A["snapshot"]["subjects"]}
    used_not_in_pool, pool_not_read, brand_vs_pool = [], [], []
    for g, s in subj.items():
        pool = set(export.pool(g))
        used = {r["peer_id"] for r in s["relations"] if r["peer_kind"] == "TARGET"}
        if used - pool:
            used_not_in_pool.append(g)
        read = {k.rsplit("|", 1)[1] for k in export.consulted_ice_tdr if k.startswith(g + "|") and k.rsplit("|", 1)[0] == g}
        if read != pool:
            pool_not_read.append(g)
        brand = s["brand"]
        old = set(si.brand_family_candidates(brand))
        if old != pool:
            brand_vs_pool.append({"id": g, "stand_in_brand_id": brand.get("brand_id"), "stand_in_candidates": len(old), "export_pool": len(pool),
                                  "kind": ("BRAND_NOT_ALLOWED_IN_POOL" if old and not pool else "POOL_WITHOUT_RESOLVED_BRAND" if pool and not old else "DIFFERENT_MEMBERS")})
    return {"subjects": len(subj), "subjects_with_empty_pool": sum(1 for g in subj if not export.pool(g)), "shadow_candidates_outside_pool": used_not_in_pool,
            "pool_members_not_read": pool_not_read, "old_brand_family_candidates_differing_from_pool": len(brand_vs_pool),
            "old_vs_pool_by_kind": dict(collections.Counter(x["kind"] for x in brand_vs_pool)), "old_vs_pool_examples": brand_vs_pool[:25]}


def parity_status(A: dict, export: ir_export.RelationExport, si, dims: dict) -> dict[str, dict]:
    """Per-subject consumer-contract section 6. A subject is `IR_PARITY_RESOLVED` only when every requirement holds; otherwise `IR_PARITY_UNRESOLVED` with the exact reasons."""
    subj = {s["entity_id"]: s for s in A["snapshot"]["subjects"]}
    out = {}
    for g, s in subj.items():
        reasons = []
        e = export.subjects.get(g)
        if e is None:
            reasons.append("SUBJECT_NOT_IN_EXPORT")
        elif not (e["name"] == dims[g]["model_name"] and e["brand"] == dims[g]["brand"] and dims[g]["brand"] in e["brands_observed"]):
            reasons.append("SUBJECT_DIFFERS")
        if e is not None:
            pool = set(export.pool(g))
            used = {r["peer_id"] for r in s["relations"] if r["peer_kind"] == "TARGET"}
            if used - pool:
                reasons.append("POOL_MISMATCH: relation to a TDR id outside the export pool")
            if any(f"{g}|{t}" not in export.consulted_ice_tdr for t in pool):
                reasons.append("PAIR_NOT_EVALUATED: a pool member was not read")
            brand_id = s["brand"].get("brand_id")
            if brand_id and not pool:
                reasons.append("BRAND_RESOLUTION_VS_POOL: the shadow resolves the brand to a TDR brand but the export pool is empty (brand relation not allowed)")
            if not brand_id and pool:
                reasons.append("BRAND_RESOLUTION_VS_POOL: the export has a pool but the shadow does not resolve the brand")
            peers = export.peers(g)
            if len(export.rows_by_subject_ice.get(g, [])) != len(peers) or any(f"{min(g, p)}|{max(g, p)}" not in export.consulted_ice_ice for p in peers):
                reasons.append("PAIR_NOT_EVALUATED: an Ice x Ice peer pair was not read")
            for r in s["relations"]:
                key = f"{g}|{r['peer_id']}"
                row = (export.ice_ice if r["peer_kind"] == "SUBJECT" else export.ice_tdr).get(key)
                if row is None or row["r"] != r["name_relation"]:
                    reasons.append(f"RELATION_NOT_FROM_EXPORT: {key}")
        out[g] = {"status": "IR_PARITY_UNRESOLVED" if reasons else "IR_PARITY_RESOLVED", "reasons": reasons, "empty_pool": bool(e is not None and not export.pool(g))}
    return out


# ---------------------------------------------------------------------------------------------------------------- decisions, transitions, collisions
def baseline_counts(base: dict, mode: str) -> dict:
    key = f"{mode}_outcome"
    return dict(collections.Counter(r[key] for r in base["decisions"].values()))


def transitions(A: dict, B: dict, base: dict, export: ir_export.RelationExport) -> list[dict]:
    dims = {r["model_group_id"]: r for r in A["package"]["dims"]}
    subj = {s["entity_id"]: s for s in A["snapshot"]["subjects"]}
    dA, dB = _dec(A), _dec(B)
    rows = []
    for g in sorted(dA):
        b = base["decisions"][g]
        old = (b["A_outcome"], b["A_primary"], b["A_codes"], b["B_outcome"], b["B_primary"], b["B_codes"])
        new = (dA[g]["outcome"], dA[g]["primary_reason"], "|".join(dA[g]["reason_codes"]), dB[g]["outcome"], dB[g]["primary_reason"], "|".join(dB[g]["reason_codes"]))
        if old[:2] + old[3:5] != new[:2] + new[3:5] or old[2] != new[2] or old[5] != new[5]:
            old_rel = {(k, p): r for k, p, r in base["relations"].get(g, [])}
            new_rel = {(r["peer_kind"], r["peer_id"]): r["name_relation"] for r in subj[g]["relations"]}
            changes = [f"{k[1]}: {old_rel.get(k, 'none')} -> {new_rel.get(k, 'none')}" for k in sorted(set(old_rel) | set(new_rel)) if old_rel.get(k) != new_rel.get(k)]
            tdr_ids = sorted({p for (k, p) in set(old_rel) | set(new_rel) if k == "TARGET"})
            rows.append({"model_group_id": g, "brand": dims[g]["brand"], "name": dims[g]["model_name"], "identity_status": subj[g]["identity_status"], "lifetime_units": int(float(dims[g]["reg_total_all"])),
                         "last12_units": int(A["package"]["last12"].get(g, 0)),
                         "A_before": f"{old[0]} / {old[1]}", "A_after": f"{new[0]} / {new[1]}", "B_before": f"{old[3]} / {old[4]}", "B_after": f"{new[3]} / {new[4]}",
                         "A_codes_before": old[2], "A_codes_after": new[2], "tdr_candidate_ids_involved": "|".join(tdr_ids), "relation_changes": "; ".join(changes) or "none (batch / Bootstrap effect)",
                         "ir_dry_run_outcome": export.subjects[g]["outcome"]["outcome"], "ir_pool_size": len(export.pool(g))})
    return rows


def dry_run_vs_bootstrap(A: dict, export: ir_export.RelationExport) -> dict:
    """The reference evaluator's dry-run outcome next to Bootstrap's own mode-A classification, reported separately: they answer different questions (link vs existence)."""
    dA = _dec(A)
    cross = collections.Counter((export.subjects[g]["outcome"]["outcome"], dA[g]["outcome"]) for g in dA)
    divergent = []
    for g, d in dA.items():
        ir = export.subjects[g]["outcome"]
        if d["outcome"] == "CREATE_IDENTITY" and ir["outcome"] != "NO_CANDIDATE":
            divergent.append({"id": g, "ir_outcome": ir["outcome"], "ir_primary": ir["primary_code"], "ir_targets": ir["target_ids"], "bootstrap": "CREATE_IDENTITY"})
        if d["primary_reason"] == "NOT_ACTIVATED" and ir["outcome"] == "NO_CANDIDATE":
            divergent.append({"id": g, "ir_outcome": ir["outcome"], "ir_primary": ir["primary_code"], "ir_targets": ir["target_ids"], "bootstrap": "HOLD / NOT_ACTIVATED (mode-A lexical duplicate)"})
    return {"cross_tab": {f"IR {a} -> Bootstrap {b}": n for (a, b), n in sorted(cross.items())}, "divergent": sorted(divergent, key=lambda x: x["id"]),
            "note": "IR's outcome is a dry run on series-carrying data (invariant I16); Bootstrap's mode A diverts only lexical duplicates. A CREATE with an IR link outcome is a collision to inspect, never a decision."}


def collisions(A: dict, export: ir_export.RelationExport, creates: list[str], reviews: dict) -> list[dict]:
    """For each CREATE: its closest pool members by the export's own score (not recomputed), any non-CONTRADICTION relation, IR's dry-run outcome and the routing flags."""
    dims = {r["model_group_id"]: r for r in A["package"]["dims"]}
    out = []
    for g in creates:
        rows = sorted((export.ice_tdr[f"{g}|{t}"] for t in export.pool(g)), key=lambda r: (-(r["s"] if r["s"] is not None else -1), r["b"]))
        top = [{"tdr": r["b"], "relation": r["r"], "score": r["s"], "tdr_tokens": r["tb"]} for r in rows[:3]]
        related = [r["b"] + "=" + r["r"] for r in rows if r["r"] not in ("CONTRADICTION", "UNAVAILABLE")]
        ir = export.subjects[g]["outcome"]
        out.append({"id": g, "name": dims[g]["model_name"], "brand": dims[g]["brand"], "pool_size": len(rows), "top_pool_candidates": top, "non_contradiction_relations": related,
                    "ir_dry_run": [ir["outcome"], ir["primary_code"], ir["target_ids"]], "review_flags": reviews[g]["flags"],
                    "collision_signal": bool(related or ir["outcome"] != "NO_CANDIDATE" or reviews[g]["mandatory_owner_review"])})
    return out


def structural(run: dict, base_ids: set[str]) -> dict:
    cur = {g for g, d in _dec(run).items() if "STRUCTURAL_CONFLICT" in d["reason_codes"]}
    return {"before": len(base_ids), "after": len(cur), "left": sorted(base_ids - cur), "entered": sorted(cur - base_ids)}


def units(run: dict, ids) -> dict:
    dims = {r["model_group_id"]: r for r in run["package"]["dims"]}
    return {"groups": len(list(ids)), "lifetime_units": int(sum(float(dims[g]["reg_total_all"]) for g in ids)), "last12_units": int(sum(run["package"]["last12"].get(g, 0) for g in ids))}


def market(A: dict, creates: list[str]) -> dict:
    res = activity_report.classify_all(A, creates)
    return {"actual": res["actual"], "what_if": res["what_if_absent_is_zero"]}


def build_routing(A: dict, creates: list[str], mk: dict, r6: dict, parity: dict[str, str]) -> dict:
    subjects = A["snapshot"]["subjects"]
    pol = signals.load_policy()
    reviews = signals.review_flags(subjects, A["catalog"], r6, creates, pol, pool_of=A["export"].pool, tokens=A["stand_in"].lex.tokens)
    general = signals.provider_id_label_evidence(subjects, A["catalog"], pol)
    dec = _dec(A)
    dispatched = routing.dispatch_all(A["decisions"], {g: v["state"] for g, v in mk["actual"].items()}, reviews, parity)
    lanes = collections.Counter(r["lane"] for r in dispatched)
    return {"reviews": reviews, "general_cross_brand_list": {g: {"bootstrap_outcome": dec[g]["outcome"], "evidence": e} for g, e in sorted(general.items())},
            "dispatch": dispatched, "lane_counts": dict(lanes), "current_dispatch_ids": sorted(r["external_id"] for r in routing.current_dispatch(dispatched))}


def build_m5(A: dict, B: dict, export: ir_export.RelationExport, base: dict, creates: list[str], r6: dict) -> dict:
    si = A["stand_in"]
    dims = {r["model_group_id"]: r for r in A["package"]["dims"]}
    parity = relation_parity(A, export)
    pstat = parity_status(A, export, si, dims)
    mk = market(A, creates)
    rt = build_routing(A, creates, mk, r6, {g: v["status"] for g, v in pstat.items()})
    dA, dB = _dec(A), _dec(B)
    prev_creates = base["creates"]
    removed, added = sorted(prev_creates - set(creates)), sorted(set(creates) - prev_creates)
    changes = transitions(A, B, base, export)
    by_id = {t["model_group_id"]: t for t in changes}
    summ = lambda r: {"states": dict(collections.Counter(v["state"] for v in r.values())), "lanes": dict(collections.Counter(v["lane"] for v in r.values()))}
    cnt = lambda d, k: dict(collections.Counter(r[k] for r in d.values()))
    new_counts = {"A": dict(collections.Counter(d["outcome"] for d in dA.values())), "B": dict(collections.Counter(d["outcome"] for d in dB.values()))}
    old_counts = {"A": cnt(base["decisions"], "A_outcome"), "B": cnt(base["decisions"], "B_outcome")}
    prev_lanes = collections.Counter(l for g, l in base["lanes"].items() if g in prev_creates)
    unresolved = {g: v for g, v in pstat.items() if v["status"] == "IR_PARITY_UNRESOLVED"}
    return {
        "pr200": {"commit": ir_export.PIN["producer_commit"], "export_id": export.manifest["export_id"], "schema_version": export.manifest["schema_version"], "consumer_contract_version": export.manifest["consumer_contract_version"],
                  "manifest_sha256": ir_export.PIN_MANIFEST_SHA256, "files": export.manifest["files"], "contract": export.manifest["contract"], "evaluator_and_contract_sources": export.manifest["sources"]["evaluator_and_contract"]},
        "baseline": "shadow/baseline_b132a86 (commit b132a86c: stand-in population + the partial PR #200 rev-4 pair export)",
        "counts": {"before": old_counts, "after": new_counts}, "groups": len(dA),
        "units_by_bucket_after": {m: {o: units(A, [g for g, d in (dA if m == "A" else dB).items() if d["outcome"] == o]) for o in ("CREATE_IDENTITY", "IDENTITY_REVIEW", "HOLD")} for m in ("A", "B")},
        "units_create_added": units(A, added), "units_create_removed": units(A, removed),
        "create_sets": {"before": len(prev_creates), "after": len(creates), "added": added, "removed": removed, "unchanged": len(set(creates) & prev_creates),
                        "B_creates": sorted(g for g, d in dB.items() if d["outcome"] == "CREATE_IDENTITY"), "in_A_not_B": sorted(set(creates) - {g for g, d in dB.items() if d["outcome"] == "CREATE_IDENTITY"}),
                        "in_B_not_A": sorted({g for g, d in dB.items() if d["outcome"] == "CREATE_IDENTITY"} - set(creates))},
        "added_detail": {g: by_id.get(g) for g in added}, "removed_detail": {g: by_id.get(g) for g in removed},
        "transitions": changes,
        "review_hold_moves": {"A": dict(collections.Counter(f"{t['A_before'].split(' / ')[0]} -> {t['A_after'].split(' / ')[0]}" for t in changes if t["A_before"].split(" / ")[0] != t["A_after"].split(" / ")[0])),
                              "B": dict(collections.Counter(f"{t['B_before'].split(' / ')[0]} -> {t['B_after'].split(' / ')[0]}" for t in changes if t["B_before"].split(" / ")[0] != t["B_after"].split(" / ")[0]))},
        "structural": {"A": structural(A, {g for g, r in base["decisions"].items() if "STRUCTURAL_CONFLICT" in r["A_codes"].split("|")}),
                       "B": structural(B, {g for g, r in base["decisions"].items() if "STRUCTURAL_CONFLICT" in r["B_codes"].split("|")})},
        "parity": {"lexical_relations": parity, "candidate_pools": pool_parity(A, export, si),
                   "subjects": {"resolved": len(pstat) - len(unresolved), "unresolved": len(unresolved), "unresolved_ids_and_reasons": {g: v["reasons"] for g, v in sorted(unresolved.items())},
                                "empty_pool_subjects": sum(1 for v in pstat.values() if v["empty_pool"])}},
        "ir_parity_status": pstat,
        "dry_run_vs_bootstrap": dry_run_vs_bootstrap(A, export),
        "collisions": collisions(A, export, creates, rt["reviews"]),
        "routing": rt,
        "routing_counts": {"before": dict(prev_lanes), "after": {l: n for l, n in rt["lane_counts"].items() if l != "NOT_DISPATCHED"}},
        "market_activity": {"complete_through": activity_report.complete_through(A["package"]), "actual": summ(mk["actual"]), "what_if_NOT_AUTHORITATIVE": summ(mk["what_if"]),
                            "per_group": {g: {"actual": mk["actual"][g]["state"], "lane": mk["actual"][g]["lane"], "what_if": mk["what_if"][g]["state"]} for g in creates}},
        "activity_classes_informational": None,
        "universe_verification": A["catalog"]["verification"]["comparison_with_file_snapshot"], "policy_version": A["policy"]["version"],
    }
