"""Policy sensitivity on the real R6 data: move ONE provisional value at a time and count what changes.

Every run happens in a child process that patches the in-memory policy (or, for the what-if rows, the in-memory capability declaration)
before the reference evaluator is imported. No contract file is read for writing, and the hypotheses are NOT contract values:
the `what-if` rows ("Ice confirms absent = zero") exist only to size an effect.

    python -m identity_resolution.calibration.sensitivity run  [--workers 4] [--out sensitivity_results.json]
    python -m identity_resolution.calibration.sensitivity worker '<json>'      (internal)
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CALIBRATION_DIR = Path(__file__).resolve().parent
RESULTS = CALIBRATION_DIR / "sensitivity_results.json"

#: (variant id, adoption entry it belongs to, policy path, new value, one-line description)
VARIANTS = [
    ("strong.correlation_min=0.97", "series_strong (calibration; accepted in 14.2, value still pending)", "series.strong.correlation_min", 0.97, "AUTO/strong gate: correlation >= 0.97"),
    ("strong.correlation_min=0.99", "series_strong", "series.strong.correlation_min", 0.99, "correlation >= 0.99"),
    ("strong.ratio_min=0.85", "series_strong", "series.strong.ratio_min", 0.85, "ratio lower bound 0.85"),
    ("strong.ratio_min=0.95", "series_strong", "series.strong.ratio_min", 0.95, "ratio lower bound 0.95"),
    ("strong.ratio_max=1.15", "series_strong", "series.strong.ratio_max", 1.15, "ratio upper bound 1.15"),
    ("strong.ratio_max=1.05", "series_strong", "series.strong.ratio_max", 1.05, "ratio upper bound 1.05"),
    ("monthly_fit.min_share=0.6", "series_monthly_fit", "series.monthly_fit.min_share_of_months", 0.6, "monthly fit share >= 0.60"),
    ("monthly_fit.min_share=0.9", "series_monthly_fit", "series.monthly_fit.min_share_of_months", 0.9, "monthly fit share >= 0.90"),
    ("monthly_fit.rel_tolerance=0.15", "series_monthly_fit", "series.monthly_fit.rel_tolerance", 0.15, "relative tolerance 15 %"),
    ("monthly_fit.rel_tolerance=0.35", "series_monthly_fit", "series.monthly_fit.rel_tolerance", 0.35, "relative tolerance 35 %"),
    ("auto.common_months=9", "series_minimums", "series.minimums.auto.common_months", 9, "AUTO needs 9 common months (was 12)"),
    ("auto.common_months=18", "series_minimums", "series.minimums.auto.common_months", 18, "AUTO needs 18 common months"),
    ("auto.joint_nonzero=7", "series_minimums", "series.minimums.auto.joint_nonzero_months", 7, "AUTO needs 7 joint non-zero months (was 10)"),
    ("auto.joint_nonzero=14", "series_minimums", "series.minimums.auto.joint_nonzero_months", 14, "AUTO needs 14 joint non-zero months"),
    ("auto.units=60", "series_minimums", "series.minimums.auto.units_each_side", 60, "AUTO needs 60 units each side (was 120)"),
    ("auto.units=240", "series_minimums", "series.minimums.auto.units_each_side", 240, "AUTO needs 240 units each side"),
    ("propose.common_months=4", "series_minimums", "series.minimums.propose.common_months", 4, "a series is usable from 4 common months (was 6)"),
    ("propose.common_months=9", "series_minimums", "series.minimums.propose.common_months", 9, "usable from 9 common months"),
    ("propose.units=15", "series_minimums", "series.minimums.propose.units_each_side", 15, "usable from 15 units each side (was 30)"),
    ("propose.units=60", "series_minimums", "series.minimums.propose.units_each_side", 60, "usable from 60 units each side"),
    ("gap.cap=1", "series_absent_row_gap", "series.absent_row.auto_max_unconfirmed_gap_months", 1, "AUTO tolerates 1 unconfirmed-gap month (was 0)"),
    ("gap.cap=3", "series_absent_row_gap", "series.absent_row.auto_max_unconfirmed_gap_months", 3, "AUTO tolerates 3 unconfirmed-gap months"),
    ("gap.cap=24", "series_absent_row_gap", "series.absent_row.auto_max_unconfirmed_gap_months", 24, "no cap at all (every gap tolerated): the upper bound of what Ice/TDR confirmation could unlock"),
    ("fuzzy.min_token_length=4", "lexical_fuzzy_min_length", "lexical.fuzzy_token.min_token_length", 4, "one-edit tolerance from 4-letter tokens (was 6)"),
    ("fuzzy.min_token_length=5", "lexical_fuzzy_min_length", "lexical.fuzzy_token.min_token_length", 5, "one-edit tolerance from 5-letter tokens"),
    ("fuzzy.min_token_length=8", "lexical_fuzzy_min_length", "lexical.fuzzy_token.min_token_length", 8, "one-edit tolerance only from 8-letter tokens"),
    ("fuzzy.enabled=false", "lexical_fuzzy_switch", "lexical.fuzzy_token.enabled", False, "no one-edit typo tolerance at all"),
    ("series_only.allow_with_name_veto=true", "lexical_name_relation_roles", "lexical.series_only.allow_with_name_veto", True, "a STRONG series rescues a contradicting / sibling name"),
    ("wrong.correlation_below=0.3", "data_sufficiency_wrong_series", "data_sufficiency.series_decisively_wrong.correlation_below", 0.3, "decisively wrong only below correlation 0.3 (was 0.5)"),
    ("wrong.correlation_below=0.7", "data_sufficiency_wrong_series", "data_sufficiency.series_decisively_wrong.correlation_below", 0.7, "decisively wrong below correlation 0.7"),
    ("wrong.ratio_outside=[0.33,3]", "data_sufficiency_wrong_series", "data_sufficiency.series_decisively_wrong.ratio_outside", [0.33, 3.0], "decisively wrong outside ratio 0.33..3 (was 0.5..2)"),
    ("wrong.ratio_outside=[0.67,1.5]", "data_sufficiency_wrong_series", "data_sufficiency.series_decisively_wrong.ratio_outside", [0.67, 1.5], "decisively wrong outside ratio 0.67..1.5"),
    ("margin.correlation_delta=0.005", "candidates_margin", "candidates.margin.correlation_delta_min", 0.005, "rivals are tied when correlation differs by < 0.005 (was 0.01)"),
    ("margin.correlation_delta=0.03", "candidates_margin", "candidates.margin.correlation_delta_min", 0.03, "rivals are tied when correlation differs by < 0.03"),
    ("margin.abs_ln_ratio_delta=0.02", "candidates_margin", "candidates.margin.abs_ln_ratio_delta_min", 0.02, "tied when |ln ratio| differs by < 0.02 (was 0.05)"),
    ("margin.abs_ln_ratio_delta=0.15", "candidates_margin", "candidates.margin.abs_ln_ratio_delta_min", 0.15, "tied when |ln ratio| differs by < 0.15"),
    ("part_of.min_ratio_above=1.3", "granularity_part_of_ratio", "granularity.part_of.min_ratio_above", 1.3, "PART_OF needs a target >= 1.3x the subject (was 1.1)"),
    ("part_of.min_ratio_above=2.0", "granularity_part_of_ratio", "granularity.part_of.min_ratio_above", 2.0, "PART_OF needs a target >= 2x the subject"),
    ("part_of.arbitration_sum_check=false", "granularity_part_of_rules", "granularity.part_of.arbitration_sum_check", False, "no sum rule: several subjects are never grouped as parts"),
    ("lifecycle.grace_months=3", "attributes_lifecycle", "attributes.lifecycle.grace_months", 3, "generation grace 3 months (was 6)"),
    ("lifecycle.grace_months=12", "attributes_lifecycle", "attributes.lifecycle.grace_months", 12, "generation grace 12 months"),
    ("lifecycle.within_min_share=0.9", "attributes_lifecycle", "attributes.lifecycle.within_min_share", 0.9, "WITHIN needs 90 % of units inside the lifetime (was 80 %)"),
    ("lifecycle.disjoint_max_share=0.4", "attributes_lifecycle", "attributes.lifecycle.disjoint_max_share", 0.4, "DISJOINT below 40 % inside (was 20 %)"),
    ("discovery.catalog_gap_min_units=250", "subject_discovery_thresholds", "subject_quality.discovery.catalog_gap_min_units", 250, "catalog-gap flag from 250 units (was 500)"),
    ("discovery.catalog_gap_min_units=2000", "subject_discovery_thresholds", "subject_quality.discovery.catalog_gap_min_units", 2000, "catalog-gap flag from 2000 units"),
    ("bundle.max_members=2", "candidates_bundle_bounds", "candidates.bundle.max_members", 2, "link sets of at most 2 members (was 3)"),
    ("bundle.max_members=4", "candidates_bundle_bounds", "candidates.bundle.max_members", 4, "link sets of at most 4 members"),
    ("bundle.enabled=false", "candidates_bundle_enabled (owner_accepted)", "candidates.bundle.enabled", False, "no COMPOSED_OF link sets at all (the owner accepted them; shown for size only)"),
    ("window.max_months=12", "series_window (not an adoption entry: SPEC 14.2 text)", "series.window.max_months", 12, "compare the newest 12 common months (was 24)"),
    ("window.max_months=36", "series_window", "series.window.max_months", 36, "compare the newest 36 common months"),
    ("window.trim_inactive_edges=false", "series_window_switches", "series.window.trim_inactive_edges", False, "do not trim both-zero edge months"),
]

#: Hypotheses about the capability data, to size what an answer would unlock. NOT contract values; the contract keeps both UNKNOWN.
WHAT_IFS = [
    ("what-if: Ice confirms absent = zero", "ice_zero", "HYPOTHESIS (Q-ICE-ABSENT-ROW is open): the Ice side zero-fills its absent in-coverage months"),
    ("what-if: Ice and TDR confirm absent = zero", "ice_tdr_zero", "HYPOTHESIS (Q-ICE-ABSENT-ROW open; TDR trace says UNKNOWN): both sides zero-fill"),
]


# ------------------------------------------------------------------------------------------------------------------ worker
def _set_path(policy: dict, dotted: str, value) -> None:
    node = policy
    parts = dotted.split(".")
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    last = parts[-1]
    node[int(last) if isinstance(node, list) else last] = value


def worker(spec: dict) -> dict:
    from identity_resolution.contract import loader
    original_policy, original_caps = loader.load_policy, loader.load_capabilities

    def patched_policy(version="v1"):
        policy = copy.deepcopy(original_policy(version))
        for dotted, value in spec.get("policy", []):
            _set_path(policy, dotted, value)
        return policy

    def patched_caps(version="v1"):
        caps = copy.deepcopy(original_caps(version))
        sources = {"ice_zero": ["ice"], "ice_tdr_zero": ["ice", "tdr_registrations"]}.get(spec.get("whatif"), [])
        for name in sources:
            caps["sources"][name]["series.absent_row"].update(
                {"value": "ABSENT_IS_ZERO", "status": "confirmed", "confirmed_by": "WHAT-IF", "confirmed_on": "2000-01-01",
                 "reference": "hypothetical", "coverage_guarantee": "hypothetical"})
        return caps

    loader.load_policy, loader.load_capabilities = patched_policy, patched_caps
    from identity_resolution.calibration import adapters as A, ref_eval_resolve as R
    ice, ext = A.load_ice_package(), A.load_extracts()
    res = R.resolve(A.build_snapshot(ice, ext))
    if "refusal" in res:
        return {"refusal": res["refusal"]}
    out = {}
    for gid, d in res["decisions"].items():
        out[gid] = [d["outcome"], d.get("primary") or "", "+".join(d.get("target_ids", []) or []), d.get("link_type") or "", d["review"]["queue"]]
    return {"decisions": out}


# ------------------------------------------------------------------------------------------------------------------ driver
def _run_child(spec: dict) -> dict:
    proc = subprocess.run([sys.executable, "-m", "identity_resolution.calibration.sensitivity", "worker", json.dumps(spec)],
                          capture_output=True, text=True, cwd=str(CALIBRATION_DIR.parents[1]))
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])
    return json.loads(proc.stdout)


def _diff(base: dict, other: dict, stored_groups: set[str]) -> dict:
    changed, auto_gain, auto_loss, outcome_moves = [], [], [], {}
    for gid, b in base.items():
        o = other[gid]
        if (b[0], b[2], b[3]) != (o[0], o[2], o[3]):
            changed.append(gid)
            outcome_moves[f"{b[0]}->{o[0]}"] = outcome_moves.get(f"{b[0]}->{o[0]}", 0) + 1
            if o[0] == "AUTO" and b[0] != "AUTO":
                auto_gain.append(gid)
            if b[0] == "AUTO" and o[0] != "AUTO":
                auto_loss.append(gid)
    counts = {}
    for v in other.values():
        counts[v[0]] = counts.get(v[0], 0) + 1
    queues = {}
    for v in other.values():
        queues[v[4]] = queues.get(v[4], 0) + 1
    return {"outcomes": dict(sorted(counts.items())), "review_queues": dict(sorted(queues.items())),
            "groups_changed": len(changed), "groups_changed_in_legacy_rows": len([g for g in changed if g in stored_groups]),
            "auto_gained": len(auto_gain), "auto_lost": len(auto_loss), "moves": dict(sorted(outcome_moves.items())),
            "examples_changed": sorted(changed)[:12], "examples_auto_gained": sorted(auto_gain)[:12], "examples_auto_lost": sorted(auto_loss)[:12]}


def run(workers: int, out_path: Path) -> dict:
    from . import adapters as A
    stored_groups = {r["model_group_id"] for r in A.load_extracts()["crosswalk"] if r["match_method"] != "ADMIN"}
    specs = [("baseline", {})]
    specs += [(v[0], {"policy": [[v[2], v[3]]]}) for v in VARIANTS]
    specs += [(w[0], {"whatif": w[1]}) for w in WHAT_IFS]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda s: _run_child(s[1]), specs))
    base = results[0]["decisions"]
    doc = {"baseline_outcomes": _diff(base, base, stored_groups)["outcomes"], "baseline_review_queues": _diff(base, base, stored_groups)["review_queues"],
           "groups": len(base), "legacy_row_groups": len(stored_groups), "variants": []}
    for (vid, _), res in list(zip(specs, results))[1:]:
        meta = next((v for v in VARIANTS if v[0] == vid), None)
        wi = next((w for w in WHAT_IFS if w[0] == vid), None)
        entry = {"id": vid, "adoption_entry": meta[1] if meta else "capability what-if (not a contract value)",
                 "key": meta[2] if meta else None, "value": meta[3] if meta else None,
                 "description": meta[4] if meta else wi[2], "hypothetical": bool(wi)}
        entry.update({"refusal": res["refusal"]} if "refusal" in res else _diff(base, res["decisions"], stored_groups))
        doc["variants"].append(entry)
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--out", type=Path, default=RESULTS)
    w = sub.add_parser("worker")
    w.add_argument("spec")
    args = ap.parse_args(argv)
    if args.cmd == "worker":
        sys.stdout.write(json.dumps(worker(json.loads(args.spec)), ensure_ascii=False))
        return 0
    run(args.workers, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
