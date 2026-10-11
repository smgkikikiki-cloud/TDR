"""Post-PR-#200-rev-4 comparison: the same Bootstrap engine and policy over the same M7.0 package and TDR universe, with the relation layer replaced by the pinned
rev 4 export. Measurement only. Compared against the frozen milestone-3 results in `baseline_m3/`."""
from __future__ import annotations

import collections
import csv

from identity_bootstrap import routing
from identity_bootstrap.routing import signals

from . import activity_report, calibration, ir_rev4


def _dec(run: dict) -> dict[str, dict]:
    return {d["subject"]["entity_id"]: d for d in run["decisions"]}


def relation_parity(A: dict, A0: dict, ir: dict) -> dict:
    """Does the snapshot Bootstrap saw carry exactly the rev 4 verdicts? (a) every exported pair is present with IR's relation; (b) counts per relation for the three
    corrected kinds equal IR's; (c) the unchanged kinds the stand-in supplies, compared with IR's counts, as information."""
    subj = {s["entity_id"]: s for s in A["snapshot"]["subjects"]}
    got_ii, got_it = {}, {}
    for g, s in subj.items():
        for r in s["relations"]:
            (got_ii if r["peer_kind"] == "SUBJECT" else got_it)[f"{g}|{r['peer_id']}"] = r["name_relation"]
    out = {"pr200_commit": ir["provenance"]["commit"], "sources_sha256": ir["provenance"]["sources_sha256"]}
    for name, exp, got, counts in (("ice_ice", ir["ice_ice_relation_pairs"], got_ii, ir["relation_counts"]["ice_ice"]), ("ice_tdr", ir["ice_tdr_relation_pairs"], got_it, ir["relation_counts"]["ice_tdr"])):
        mine = collections.Counter(got.values())
        out[name] = {"exported_pairs": len(exp), "exported_pairs_missing_or_relabelled": sorted(k for k, v in exp.items() if got.get(k) != v),
                     "corrected_kinds_equal": {k: [mine.get(k, 0), counts.get(k, 0)] for k in ir_rev4.EXPORTED_RELATIONS},
                     "fuzzy_or_sibling_not_in_export": sorted(k for k, v in got.items() if v in ("FUZZY", "SIBLING") and k not in exp),
                     "unchanged_kinds_standin_vs_ir": {k: [mine.get(k, 0), counts.get(k, 0)] for k in ("EQUAL", "EQUAL_VIA_TOKEN_EQUIV", "SUBJECT_COARSER", "SUBJECT_FINER")}}
    # pairs where IR's verdict replaced a DIFFERENT relation the stand-in alone had (IR is the authority); an unchanged-class relation overridden this way is a stand-in/IR disagreement
    base = {}
    for s in A0["snapshot"]["subjects"]:
        for r in s["relations"]:
            base[f"{s['entity_id']}|{r['peer_id']}"] = r["name_relation"]
    over = {}
    for name, exp in (("ice_ice", ir["ice_ice_relation_pairs"]), ("ice_tdr", ir["ice_tdr_relation_pairs"])):
        over[name] = sorted(f"{k}: stand-in {base.get(k, 'CONTRADICTION')} -> IR {v}" for k, v in exp.items() if base.get(k, "CONTRADICTION") not in (v, "FUZZY", "SIBLING", "CONTRADICTION"))
    out["unchanged_class_relations_overridden_by_ir"] = over
    return out


UNCHANGED_KINDS = ("EQUAL", "EQUAL_VIA_TOKEN_EQUIV", "SUBJECT_COARSER", "SUBJECT_FINER")


def parity_status(A: dict, A0: dict, ir: dict, par: dict) -> dict[str, dict]:
    """Per-subject IR parity. The export carries pair ids for FUZZY / SIBLING / EQUAL_VIA_MODEL_ALIAS only, so a verdict can be verified at pair level for those kinds and
    never for the others. EVERY verdict is therefore IR_PARITY_UNRESOLVED while the population-level counts of an unchanged kind disagree; the reasons say why, per subject."""
    exp_ii, exp_it = ir["ice_ice_relation_pairs"], ir["ice_tdr_relation_pairs"]
    base = {s["entity_id"]: s for s in A0["snapshot"]["subjects"]}
    pop = []
    for name in ("ice_ice", "ice_tdr"):
        pop += [f"{name}.{k}: stand-in {v[0]} vs IR {v[1]}" for k, v in par[name]["unchanged_kinds_standin_vs_ir"].items() if v[0] != v[1]]
    out = {}
    for s in A["snapshot"]["subjects"]:
        g, reasons = s["entity_id"], []
        for r in base[g]["relations"]:
            kind = "SUBJECT" if r["peer_kind"] == "SUBJECT" else "TARGET"
            key = f"{g}|{r['peer_id']}"
            exported = (exp_ii if kind == "SUBJECT" else exp_it).get(key)
            if r["name_relation"] in UNCHANGED_KINDS:
                reasons.append(f"UNCHANGED_KIND_NOT_IN_EXPORT: {r['peer_id']} {r['name_relation']}" + (f" (IR says {exported})" if exported else ""))
            elif r["name_relation"] in ("FUZZY", "SIBLING") and exported is None:
                reasons.append(f"STANDIN_RELATION_DROPPED_NOT_IN_EXPORT: {r['peer_id']} {r['name_relation']}")
        out[g] = {"status": "IR_PARITY_UNRESOLVED", "specific_reasons": reasons, "population_reasons": pop}
    return out


def structural(run: dict, base_ids: set[str]) -> dict:
    cur = {g for g, d in _dec(run).items() if "STRUCTURAL_CONFLICT" in d["reason_codes"]}
    return {"before": len(base_ids), "after": len(cur), "left": sorted(base_ids - cur), "entered": sorted(cur - base_ids)}


def baseline_structural(base: dict[str, dict], mode: str) -> set[str]:
    return {g for g, r in base.items() if "STRUCTURAL_CONFLICT" in r[f"{mode}_codes"].split("|")}


def transitions(A: dict, B: dict, base: dict[str, dict]) -> list[dict]:
    dims = {r["model_group_id"]: r for r in A["package"]["dims"]}
    status = {s["entity_id"]: s["identity_status"] for s in A["snapshot"]["subjects"]}
    dA, dB = _dec(A), _dec(B)
    rows = []
    for g in sorted(dA):
        b = base[g]
        old = (b["A_outcome"], b["A_primary"], b["B_outcome"], b["B_primary"])
        new = (dA[g]["outcome"], dA[g]["primary_reason"], dB[g]["outcome"], dB[g]["primary_reason"])
        if old != new:
            rows.append({"model_group_id": g, "brand": dims[g]["brand"], "name": dims[g]["model_name"], "identity_status": status[g], "lifetime_units": int(float(dims[g]["reg_total_all"])),
                         "A_before": f"{old[0]} / {old[1]}", "A_after": f"{new[0]} / {new[1]}", "B_before": f"{old[2]} / {old[3]}", "B_after": f"{new[2]} / {new[3]}",
                         "A_codes_after": "|".join(dA[g]["reason_codes"])})
    return rows


def released_no_candidate(A: dict, B: dict, base: dict[str, dict], ir: dict) -> dict:
    """The 177 groups PR #200 reports as released from a structural conflict while its engine decides NO_CANDIDATE. They are only candidates for Bootstrap to examine."""
    ids = ir["released_no_candidate"]["groups"]
    present = [g for g in ids if g in base]
    status = {s["entity_id"]: s["identity_status"] for s in A["snapshot"]["subjects"]}
    dA, dB = _dec(A), _dec(B)
    out = {"pr200_count": ir["released_no_candidate"]["count"], "pr200_units": ir["released_no_candidate"]["units"], "pr200_by_cause": ir["released_no_candidate"]["by_cause"],
           "present_in_bootstrap_run": len(present), "identity_status": dict(collections.Counter(status[g] for g in present))}
    for mode, d, key in (("A", dA, "A_outcome"), ("B", dB, "B_outcome")):
        out[mode] = {"before_m3": dict(collections.Counter(base[g][key] for g in present)), "after": dict(collections.Counter(d[g]["outcome"] for g in present)),
                     "after_primary": dict(collections.Counter(d[g]["primary_reason"] for g in present)),
                     "create": sorted(g for g in present if d[g]["outcome"] == "CREATE_IDENTITY")}
    out["settled_among_released"] = sorted(g for g in present if status[g] == "settled")
    return out


def new_create_risks(A: dict, B: dict, base: dict[str, dict], A0: dict) -> list[dict]:
    """Every CREATE that appeared (either mode) and the relation changes that exposed it."""
    dA, dB = _dec(A), _dec(B)
    subj, subj0 = {s["entity_id"]: s for s in A["snapshot"]["subjects"]}, {s["entity_id"]: s for s in A0["snapshot"]["subjects"]}
    dims = {r["model_group_id"]: r for r in A["package"]["dims"]}
    out = []
    for g in sorted(dA):
        if (dA[g]["outcome"] == "CREATE_IDENTITY" and base[g]["A_outcome"] != "CREATE_IDENTITY") or (dB[g]["outcome"] == "CREATE_IDENTITY" and base[g]["B_outcome"] != "CREATE_IDENTITY"):
            old = {(r["peer_kind"], r["peer_id"]): r["name_relation"] for r in subj0[g]["relations"]}
            new = {(r["peer_kind"], r["peer_id"]): r["name_relation"] for r in subj[g]["relations"]}
            out.append({"id": g, "name": dims[g]["model_name"], "units": int(float(dims[g]["reg_total_all"])), "before": f"A {base[g]['A_outcome']}/{base[g]['A_primary']}; B {base[g]['B_outcome']}/{base[g]['B_primary']}",
                        "A_after": dA[g]["outcome"], "B_after": dB[g]["outcome"],
                        "relation_changes": [f"{k[1]}: {old.get(k, 'none')} -> {new.get(k, 'none')}" for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]})
    return out


def market(A: dict, creates: list[str]) -> dict:
    res = activity_report.classify_all(A, creates)
    return {"actual": res["actual"], "what_if": res["what_if_absent_is_zero"]}


def build_routing(A: dict, creates: list[str], mk: dict, r6: dict, parity: dict[str, str] | None = None) -> dict:
    subjects = A["snapshot"]["subjects"]
    pol = signals.load_policy()
    reviews = signals.review_flags(subjects, A["catalog"], r6, creates, pol)
    general = signals.provider_id_label_evidence(subjects, A["catalog"], pol)
    dec = _dec(A)
    dispatched = routing.dispatch_all(A["decisions"], {g: v["state"] for g, v in mk["actual"].items()}, reviews, parity)
    cur = routing.current_dispatch(dispatched)
    lanes = collections.Counter(r["lane"] for r in dispatched)
    return {"reviews": reviews, "general_cross_brand_list": {g: {"bootstrap_outcome": dec[g]["outcome"], "evidence": e} for g, e in sorted(general.items())},
            "dispatch": dispatched, "lane_counts": dict(lanes), "current_dispatch_ids": sorted(r["external_id"] for r in cur)}


def build_m4(A: dict, B: dict, A0: dict, ir: dict, base: dict[str, dict], baseline_ids: set[str], creates: list[str], r6: dict | None = None) -> dict:
    mk = market(A, creates)
    ps = parity_status(A, A0, ir, relation_parity(A, A0, ir))
    summ = lambda r: {"states": dict(collections.Counter(v["state"] for v in r.values())), "lanes": dict(collections.Counter(v["lane"] for v in r.values()))}
    return {
        "pr200": ir["provenance"], "baseline": "shadow/baseline_m3 (milestone 3: policy v2, stand-in relations, same package and TDR universe)",
        "diff": calibration.diff_against_baseline(A, B, base, {}),
        "transitions": transitions(A, B, base),
        "structural": {"A": structural(A, baseline_structural(base, "A")), "B": structural(B, baseline_structural(base, "B"))},
        "parity": relation_parity(A, A0, ir),
        "released_no_candidate": released_no_candidate(A, B, base, ir),
        "new_create_risks": new_create_risks(A, B, base, A0),
        "create_sets": {"count": len(creates), "added_vs_m3": sorted(set(creates) - baseline_ids), "removed_vs_m3": sorted(baseline_ids - set(creates)), "unchanged": len(set(creates) & baseline_ids),
                        "B_subset_of_A": {d["subject"]["entity_id"] for d in B["decisions"] if d["outcome"] == "CREATE_IDENTITY"} <= set(creates),
                        "in_A_not_B": sorted(set(creates) - {d["subject"]["entity_id"] for d in B["decisions"] if d["outcome"] == "CREATE_IDENTITY"})},
        "market_activity": {"complete_through": activity_report.complete_through(A["package"]), "actual": summ(mk["actual"]), "what_if_NOT_AUTHORITATIVE": summ(mk["what_if"]),
                            "per_group": {g: {"actual": mk["actual"][g]["state"], "lane": mk["actual"][g]["lane"], "what_if": mk["what_if"][g]["state"]} for g in creates}},
        "activity_classes_informational": None,
        "routing": build_routing(A, creates, mk, r6 or {}, {g: v["status"] for g, v in ps.items()}),
        "ir_parity_status": ps,
    }


def load_baseline_ids(path) -> set[str]:
    with path.open(encoding="utf-8", newline="") as fh:
        lines = [l for l in fh if not l.startswith("#")]
    return {r["external_id"] for r in csv.DictReader(lines)}
