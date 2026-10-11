"""Numbers for the calibration report, and the report itself.

Everything here is a pure function of (assembled pairs, owner sheet, sensitivity results, adoption entries): no I/O except
`write_outputs`. The report states what the data shows and what it cannot show; it settles nothing (adoption `binding` stays false).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from identity_resolution.contract import loader

from . import pairs as PR
from . import review as RV
from . import ref_eval_core as P


# ----------------------------------------------------------------------------------------------------------------- helpers
def hist(values, edges, labels=None, undefined_label="undefined"):
    """Counts per half-open bin [edges[i], edges[i+1]); values below edges[0] and at/above edges[-1] get their own bins."""
    labels = labels or ([f"< {edges[0]}"] + [f"{a} .. < {b}" for a, b in zip(edges, edges[1:])] + [f">= {edges[-1]}"])
    out = Counter()
    for v in values:
        if v is None or v == "":
            out[undefined_label] += 1
            continue
        out[labels[sum(1 for e in edges if v >= e)]] += 1
    return {k: out.get(k, 0) for k in labels + ([undefined_label] if undefined_label in out else [])}


def pct(a, b):
    return round(100.0 * a / b, 1) if b else 0.0


def share_rows(rows, pred):
    sel = [r for r in rows if pred(r)]
    return len(sel), sel


def example_list(rows, value_fn, limit=8):
    rows = sorted(rows, key=lambda r: (-r["ice_units_last24m"], -r["ice_lifetime_units"], r["model_group_id"]))
    return [f"{r['model_group_id']} -> {r['candidate_canonical_model_id'] or '(none)'} [{value_fn(r)}]" for r in rows[:limit]]


def _min_units(r):
    return min(r["v1_subject_units"] or 0, r["v1_target_units"] or 0)


def _usable(r):
    return r["v1_series_state"] in ("STRONG", "WEAK")


def _strong_ish(r):
    """corr and ratio pass the strong gate: what is left to decide is the monthly fit and the minimums."""
    return (_usable(r) and r["v1_correlation"] is not None and r["v1_correlation"] >= 0.98 and 0.9 <= r["v1_ratio"] <= 1.1)


def near_miss_fuzzy(r) -> bool:
    """Subject and target names differ by exactly one token pair that is one edit apart but shorter than the fuzzy minimum."""
    if r["v1_name_relation"] not in ("CONTRADICTION", "SIBLING", "SUBJECT_COARSER", "SUBJECT_FINER"):
        return False
    a, b = set(r["v1_name_subject_tokens"].split()), set(r["v1_name_target_tokens"].split())
    only_a, only_b = a - b, b - a
    if len(only_a) != 1 or len(only_b) != 1:
        return False
    x, y = next(iter(only_a)), next(iter(only_b))
    return P._lev1(x, y) and x != y and min(len(x), len(y)) < loader.load_policy()["lexical"]["fuzzy_token"]["min_token_length"] and min(len(x), len(y)) >= 4


BOUNDARIES = [
    ("series.strong.correlation_min = 0.98", "series_strong", "pairs with a usable series and ratio inside 0.9..1.1 whose correlation is within 0.97 .. < 0.99",
     lambda r: _usable(r) and r["v1_ratio"] is not None and 0.9 <= r["v1_ratio"] <= 1.1 and 0.97 <= r["v1_correlation"] < 0.99, lambda r: f"corr {r['v1_correlation']:.4f}"),
    ("series.strong.ratio_min = 0.9", "series_strong", "pairs with correlation >= 0.98 whose ratio is within 0.85 .. < 0.95",
     lambda r: _usable(r) and r["v1_correlation"] >= 0.98 and 0.85 <= r["v1_ratio"] < 0.95, lambda r: f"ratio {r['v1_ratio']:.4f}"),
    ("series.strong.ratio_max = 1.1", "series_strong", "pairs with correlation >= 0.98 whose ratio is within 1.05 .. < 1.15",
     lambda r: _usable(r) and r["v1_correlation"] >= 0.98 and 1.05 <= r["v1_ratio"] < 1.15, lambda r: f"ratio {r['v1_ratio']:.4f}"),
    ("series.monthly_fit.min_share_of_months = 0.75", "series_monthly_fit", "pairs whose correlation and ratio pass and whose monthly fit share is within 0.65 .. < 0.85",
     lambda r: _strong_ish(r) and 0.65 <= (r["v1_monthly_fit_share"] or 0) < 0.85, lambda r: f"fit {r['v1_monthly_fit_share']:.3f}"),
    ("series.minimums.auto.common_months = 12", "series_minimums", "STRONG pairs with 9 .. < 15 common months",
     lambda r: r["v1_series_state"] == "STRONG" and 9 <= r["v1_common_months"] < 15, lambda r: f"{r['v1_common_months']} months"),
    ("series.minimums.auto.joint_nonzero_months = 10", "series_minimums", "STRONG pairs with 7 .. < 13 joint non-zero months",
     lambda r: r["v1_series_state"] == "STRONG" and 7 <= r["v1_joint_nonzero_months"] < 13, lambda r: f"{r['v1_joint_nonzero_months']} months"),
    ("series.minimums.auto.units_each_side = 120", "series_minimums", "STRONG pairs whose smaller side has 60 .. < 240 units in the window",
     lambda r: r["v1_series_state"] == "STRONG" and 60 <= _min_units(r) < 240, lambda r: f"{_min_units(r):g} units"),
    ("series.minimums.propose.common_months = 6", "series_minimums", "pairs with 4 .. < 9 common months (some are UNAVAILABLE because of this minimum)",
     lambda r: r["v1_series_state"] != "" and 4 <= (r["v1_common_months"] or 0) < 9 and r["v1_name_relation"] != "CONTRADICTION", lambda r: f"{r['v1_common_months']} months, {r['v1_series_state']}"),
    ("series.minimums.propose.units_each_side = 30", "series_minimums", "pairs whose smaller side has 15 .. < 60 units in the window",
     lambda r: r["v1_series_state"] != "" and 15 <= _min_units(r) < 60 and (r["v1_common_months"] or 0) >= 6 and r["v1_name_relation"] != "CONTRADICTION", lambda r: f"{_min_units(r):g} units, {r['v1_series_state']}"),
    ("series.absent_row.auto_max_unconfirmed_gap_months = 0", "series_absent_row_gap", "STRONG pairs with 1 .. 24 unconfirmed-gap months in the window",
     lambda r: r["v1_series_state"] == "STRONG" and (r["v1_semantics_gap_months"] or 0) > 0, lambda r: f"gap {r['v1_semantics_gap_months']} months"),
    ("lexical.fuzzy_token.min_token_length = 6", "lexical_fuzzy_min_length", "name pairs that differ by exactly one one-edit token pair shorter than 6 letters (and >= 4)",
     near_miss_fuzzy, lambda r: f"{r['v1_name_subject_tokens']!r} vs {r['v1_name_target_tokens']!r}"),
    ("data_sufficiency.series_decisively_wrong.correlation_below = 0.5", "data_sufficiency_wrong_series", "usable pairs with correlation within 0.4 .. < 0.6 and a non-candidate name",
     lambda r: _usable(r) and 0.4 <= r["v1_correlation"] < 0.6 and r["v1_name_relation"] not in ("EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV", "FUZZY"), lambda r: f"corr {r['v1_correlation']:.3f}"),
    ("data_sufficiency.series_decisively_wrong.ratio_outside = [0.5, 2.0]", "data_sufficiency_wrong_series", "usable pairs with ratio within 0.4 .. < 0.6 or 1.6 .. < 2.5 and a non-candidate name",
     lambda r: _usable(r) and (0.4 <= r["v1_ratio"] < 0.6 or 1.6 <= r["v1_ratio"] < 2.5) and r["v1_name_relation"] not in ("EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV", "FUZZY"), lambda r: f"ratio {r['v1_ratio']:.3f}"),
    ("granularity.part_of.min_ratio_above = 1.1", "granularity_part_of_ratio", "SUBJECT_FINER pairs with a usable series and ratio within 1.0 .. < 1.4",
     lambda r: r["v1_name_relation"] == "SUBJECT_FINER" and _usable(r) and 1.0 <= r["v1_ratio"] < 1.4, lambda r: f"ratio {r['v1_ratio']:.3f}"),
    ("attributes.lifecycle.within_min_share = 0.8", "attributes_lifecycle", "pairs with a lifecycle share within 0.7 .. < 0.9",
     lambda r: r["v1_lifecycle_share"] not in (None, "") and 0.7 <= r["v1_lifecycle_share"] < 0.9, lambda r: f"share {r['v1_lifecycle_share']:.3f}"),
    ("attributes.lifecycle.disjoint_max_share = 0.2", "attributes_lifecycle", "pairs with a lifecycle share within 0.1 .. < 0.3",
     lambda r: r["v1_lifecycle_share"] not in (None, "") and 0.1 <= r["v1_lifecycle_share"] < 0.3, lambda r: f"share {r['v1_lifecycle_share']:.3f}"),
]


# ------------------------------------------------------------------------------------------------------------------ compute
def compute(assembled: dict, sheet: list[dict], sensitivity: dict | None, ext: dict, ice: dict) -> dict:
    pairs, groups = assembled["pairs"], assembled["groups"]
    stored = [r for r in ext["crosswalk"] if r["match_method"] != "ADMIN"]
    stored_pairs = [p for p in pairs if p["legacy_run_selected"]]
    total_units = sum(g["ice_lifetime_units"] for g in groups.values())
    s: dict = {}

    # ---- recovery
    kinds = Counter((r["status"], r["match_method"]) for r in ext["crosswalk"])
    row_groups = {r["model_group_id"] for r in stored}
    s["recovery"] = {
        "rows_total": len(ext["crosswalk"]), "matcher_rows": len(stored), "admin_structure_rows": len(ext["crosswalk"]) - len(stored),
        "by_status_method": {f"{k[0]}/{k[1]}": v for k, v in sorted(kinds.items())},
        "redirects": len(ext["redirects"]), "redirects_by_type": dict(Counter(r["change_type"] for r in ext["redirects"])),
        "groups_total": len(groups), "groups_with_a_row": len(row_groups), "groups_without_a_row": len(groups) - len(row_groups),
        "ice_units_total": total_units, "ice_units_in_groups_with_a_row": sum(groups[g]["ice_lifetime_units"] for g in row_groups),
        "ice_units_in_legacy_auto_groups": sum(groups[r["model_group_id"]]["ice_lifetime_units"] for r in stored if r["status"] == "AUTO"),
        "verification": {k: (v if k != "mismatches" else len(v)) for k, v in assembled["verification"].items()},
        "extract_meta": ext["meta"],
    }

    # ---- windows
    spans = Counter()
    for p in stored_pairs:
        spans["window_ends_2026-09"] += p["legacy_window_last"] == "2026-09"
        spans["with_a_tdr_zero_filled_month"] += p["legacy_window_tdr_zero_filled_months"] > 0
        spans["calendar_span_over_24"] += bool(p["legacy_window_calendar_span_months"]) and p["legacy_window_calendar_span_months"] > 24
        spans["fewer_than_24_months"] += p["legacy_window_months"] < 24
    s["legacy_window"] = {
        "stored_rows": len(stored_pairs), **dict(spans),
        "tdr_zero_filled_months_distribution": hist([p["legacy_window_tdr_zero_filled_months"] for p in stored_pairs], [1, 2, 4, 7, 13, 24],
                                                    ["0", "1", "2..3", "4..6", "7..12", "13..23", "24"]),
    }
    why = Counter()
    for p in stored_pairs:
        for w in (p["series_material_change_why"].split(";") if p["series_material_change_why"] else []):
            why[w] += 1
    flows = Counter((p["legacy_series_class"], p["v1_series_state"]) for p in stored_pairs)
    all_flows = Counter((p["legacy_series_class"], p["v1_series_state"]) for p in pairs)
    mat_stored = sum(1 for p in stored_pairs if p["series_material_change"])
    mat_auto = sum(1 for p in stored_pairs if p["legacy_status"] == "AUTO" and p["series_material_change"])
    s["material_change"] = {
        "definition": (f"the series evidence differs materially between the legacy zero-filled window and the v1 common window: STRONG flips, OR availability differs, "
                       f"OR |delta correlation| >= {PR.MATERIAL_DELTA_CORRELATION}, OR the ratio moves by >= {int(PR.MATERIAL_RATIO_CHANGE * 100)} % (a reporting convention, not a policy value)"),
        "stored_rows": len(stored_pairs), "stored_rows_material": mat_stored, "stored_rows_material_pct": pct(mat_stored, len(stored_pairs)),
        "legacy_auto_rows": sum(1 for p in stored_pairs if p["legacy_status"] == "AUTO"), "legacy_auto_rows_material": mat_auto,
        "by_reason_not_exclusive": dict(why),
        "legacy_class_to_v1_state_stored_rows": {f"{a} -> {b}": n for (a, b), n in sorted(flows.items())},
        "legacy_class_to_v1_state_all_pairs": {f"{a} -> {b}": n for (a, b), n in sorted(all_flows.items())},
        "all_pairs": len(pairs), "all_pairs_material": sum(1 for p in pairs if p["series_material_change"]),
        "legacy_strong_but_v1_not_strong_stored": sum(1 for p in stored_pairs if p["legacy_series_class"] == "STRONG" and p["v1_series_state"] != "STRONG"),
        "legacy_not_strong_but_v1_strong_stored": sum(1 for p in stored_pairs if p["legacy_series_class"] != "STRONG" and p["v1_series_state"] == "STRONG"),
        "legacy_group_status_to_v1_outcome": {f"{a} -> {b}": n for (a, b), n in sorted(Counter((p["legacy_status"], p["v1_group_outcome"]) for p in stored_pairs).items())},
    }

    # ---- distributions
    corr_edges = [0.0, 0.5, 0.8, 0.9, 0.95, 0.98]
    ratio_edges = [0.5, 0.9, 1.1, 2.0]
    def dist(rows, prefix):
        return {"correlation": hist([r[f"{prefix}correlation"] for r in rows], corr_edges), "ratio": hist([r[f"{prefix}ratio"] for r in rows], ratio_edges)}
    s["distributions"] = {
        "stored_rows_legacy": dist(stored_pairs, "legacy_"), "stored_rows_v1": dist(stored_pairs, "v1_"),
        "stored_rows_legacy_name_score": hist([p["legacy_name_score"] for p in stored_pairs], [0.5, 0.8, 1.0], ["0.35 .. < 0.5", "0.5 .. < 0.8", "0.8 .. < 1.0", "1.0"]),
        "stored_rows_v1_name_relation": dict(Counter(p["v1_name_relation"] for p in stored_pairs).most_common()),
        "stored_rows_v1_brand_relation": dict(Counter(p["v1_brand_relation"] for p in stored_pairs).most_common()),
        "stored_rows_v1_link_candidate": dict(Counter(p["v1_link_candidate"] for p in stored_pairs).most_common()),
        "all_pairs_v1_name_relation": dict(Counter(p["v1_name_relation"] for p in pairs).most_common()),
        "all_pairs_v1_series_state": dict(Counter(p["v1_series_state"] for p in pairs).most_common()),
        "all_pairs_v1_link_candidate": dict(Counter(p["v1_link_candidate"] for p in pairs).most_common()),
        "stored_rows_name_relation_by_legacy_status": {f"{st} / {rel}": n for (st, rel), n in sorted(Counter((p["legacy_status"], p["v1_name_relation"]) for p in stored_pairs).items())},
        "stored_rows_v1_common_months": hist([p["v1_common_months"] for p in stored_pairs], [1, 6, 12, 18, 24], ["0", "1..5", "6..11", "12..17", "18..23", "24"]),
        "stored_rows_v1_semantics_gap_months": hist([p["v1_semantics_gap_months"] for p in stored_pairs], [1, 2, 4, 7, 13], ["0", "1", "2..3", "4..6", "7..12", "13..24"]),
        "contradiction_vs_strong_series": {
            "pairs_STRONG_series_but_name_CONTRADICTION_or_SIBLING": sum(1 for p in pairs if p["v1_series_state"] == "STRONG" and p["v1_name_relation"] in ("CONTRADICTION", "SIBLING")),
            "of_which_in_legacy_rows": sum(1 for p in stored_pairs if p["v1_series_state"] == "STRONG" and p["v1_name_relation"] in ("CONTRADICTION", "SIBLING")),
            "examples": example_list([p for p in pairs if p["v1_series_state"] == "STRONG" and p["v1_name_relation"] in ("CONTRADICTION", "SIBLING")],
                                     lambda r: f"{r['v1_name_relation']}: {r['v1_name_subject_tokens']!r} vs {r['v1_name_target_tokens']!r}; corr {r['v1_correlation']:.3f} ratio {r['v1_ratio']:.3f}", 10),
        },
    }

    # ---- boundaries
    bounds = []
    group_ids_in_sheet = {r["model_group_id"] for r in sheet}
    for name, entry, desc, pred, val in BOUNDARIES:
        sel = [p for p in pairs if pred(p)]
        bounds.append({"key": name, "adoption_entry": entry, "band": desc, "pairs": len(sel), "legacy_rows": sum(1 for p in sel if p["legacy_run_selected"]),
                       "in_review_sheet": sum(1 for p in sel if p["model_group_id"] in group_ids_in_sheet and p["candidate_origin"] != "NONE"),
                       "groups": len({p["model_group_id"] for p in sel}), "examples": example_list(sel, val)})
    # margin and discovery are group-level
    margin_pairs = []
    by_group = defaultdict(list)
    for p in pairs:
        if p["v1_proposable"]:
            by_group[p["model_group_id"]].append(p)
    for gid, ps in by_group.items():
        ps = [p for p in ps if p["v1_correlation"] is not None]
        ps.sort(key=lambda p: (p["v1_rank_among_proposable"] or 99))
        if len(ps) >= 2:
            a, b = ps[0], ps[1]
            dc = abs(a["v1_correlation"] - b["v1_correlation"])
            dr = abs(abs(math.log(a["v1_ratio"])) - abs(math.log(b["v1_ratio"]))) if a["v1_ratio"] and b["v1_ratio"] else None
            if 0.005 <= dc < 0.02 or (dr is not None and 0.02 <= dr < 0.1):
                margin_pairs.append((a, b, dc, dr))
    bounds.append({"key": "candidates.margin (correlation_delta_min 0.01, abs_ln_ratio_delta_min 0.05)", "adoption_entry": "candidates_margin",
                   "band": "groups whose two best proposable candidates differ by 0.005 .. < 0.02 in correlation or 0.02 .. < 0.1 in |ln ratio|",
                   "pairs": len(margin_pairs) * 2, "legacy_rows": 0, "in_review_sheet": 0, "groups": len(margin_pairs),
                   "examples": [f"{a['model_group_id']}: {a['candidate_canonical_model_id']} vs {b['candidate_canonical_model_id']} [dcorr {dc:.4f}, dln {0 if dr is None else dr:.4f}]" for a, b, dc, dr in margin_pairs[:8]]})
    disc = [g for g in groups.values() if g["v1_group_outcome"] == "NO_CANDIDATE" and 250 <= g["ice_lifetime_units"] < 1000]
    bounds.append({"key": "subject_quality.discovery.catalog_gap_min_units = 500", "adoption_entry": "subject_discovery_thresholds",
                   "band": "NO_CANDIDATE groups with 250 .. < 1000 lifetime units", "pairs": 0, "legacy_rows": 0, "in_review_sheet": 0, "groups": len(disc),
                   "examples": [f"{g['model_group_id']} [{g['ice_lifetime_units']} units]" for g in sorted(disc, key=lambda g: -g["ice_lifetime_units"])[:8]]})
    enumerated = [g["v1_bundle_pool_size"] for g in groups.values() if g["v1_bundle_pool_size"] != ""]
    cap = loader.load_policy()["candidates"]["bundle"]["max_pool_for_enumeration"]
    set_sizes = Counter(len(g["v1_group_targets"].split("+")) for g in groups.values() if g["v1_group_link_type"] == "COMPOSED_OF")
    bounds.append({"key": "candidates.bundle.max_members = 3, max_pool_for_enumeration = 12", "adoption_entry": "candidates_bundle_bounds",
                   "band": "groups with >= 2 members eligible for a link set (enumeration runs when no single candidate is strong); examples show the eligible-pool sizes and the sizes of the sets chosen",
                   "pairs": 0, "legacy_rows": 0, "in_review_sheet": 0, "groups": sum(1 for n in enumerated if n >= 2),
                   "examples": [f"enumeration ran for {len(enumerated)} groups; eligible members per group: " + ", ".join(f"{k}x{v}" for k, v in sorted(Counter(enumerated).items())),
                                f"groups whose eligible pool exceeded the cap of {cap}: {sum(1 for n in enumerated if n > cap)}",
                                "COMPOSED_OF decisions by number of members: " + (", ".join(f"{k} members x{v}" for k, v in sorted(set_sizes.items())) or "none")]})
    s["boundaries"] = bounds

    # ---- what the unconfirmed-gap cap is made of
    def gap_kind(p):
        kinds = []
        if p["v1_gap_months_both_absent"]: kinds.append("both sources lack the row")
        if p["v1_gap_months_subject_only_absent"]: kinds.append("only Ice lacks it")
        if p["v1_gap_months_target_only_absent"]: kinds.append("only TDR lacks it")
        return " + ".join(kinds)
    gap_pairs = [p for p in pairs if p["v1_series_state"] == "STRONG" and (p["v1_semantics_gap_months"] or 0) > 0]
    auto_to_propose = [p for p in stored_pairs if p["legacy_status"] == "AUTO" and p["v1_group_outcome"] == "PROPOSE"]
    s["gap_composition"] = {
        "strong_pairs_with_a_gap": len(gap_pairs),
        "by_composition": dict(Counter(gap_kind(p) for p in gap_pairs).most_common()),
        "gap_months": {"both_sources_absent": sum(p["v1_gap_months_both_absent"] for p in gap_pairs),
                       "only_ice_absent": sum(p["v1_gap_months_subject_only_absent"] for p in gap_pairs),
                       "only_tdr_absent": sum(p["v1_gap_months_target_only_absent"] for p in gap_pairs)},
        "strong_pairs_whose_gap_has_no_ice_only_month": sum(1 for p in gap_pairs if not p["v1_gap_months_subject_only_absent"]),
        "strong_pairs_whose_gap_has_no_tdr_only_month": sum(1 for p in gap_pairs if not p["v1_gap_months_target_only_absent"]),
        "legacy_auto_rows": sum(1 for p in stored_pairs if p["legacy_status"] == "AUTO"),
        "legacy_auto_rows_now_propose": len(auto_to_propose),
        "legacy_auto_rows_now_propose_with_the_gap_as_a_blocker": sum(1 for p in auto_to_propose if "SER_MISSING_ROW_SEMANTICS_UNCONFIRMED" in p["v1_codes_blocking"].split(";")),
        "sum_of_parts_equals_gap_everywhere": all(p["v1_gap_months_both_absent"] + p["v1_gap_months_subject_only_absent"] + p["v1_gap_months_target_only_absent"] == (p["v1_semantics_gap_months"] or 0)
                                                  for p in pairs if p["v1_semantics_gap_months"] is not None),
    }

    # ---- outcomes under the current non-binding rules
    gs = list(groups.values())
    s["v1_outcomes"] = {
        "binding": loader.load_adoption()["binding"],
        "groups_all": dict(Counter(g["v1_group_outcome"] for g in gs).most_common()),
        "groups_all_primary_code": dict(Counter(g["v1_group_primary_code"] for g in gs).most_common()),
        "groups_all_review_queue": dict(Counter(g["v1_group_review_queue"] for g in gs).most_common()),
        "groups_with_legacy_row": dict(Counter(groups[r["model_group_id"]]["v1_group_outcome"] for r in stored).most_common()),
        "legacy_rows_by_legacy_status_and_v1_outcome": s["material_change"]["legacy_group_status_to_v1_outcome"],
        "v1_auto_units_share_of_total": round(sum(g["ice_lifetime_units"] for g in gs if g["v1_group_outcome"] == "AUTO") / total_units, 4),
        "v1_propose_units_share_of_total": round(sum(g["ice_lifetime_units"] for g in gs if g["v1_group_outcome"] == "PROPOSE") / total_units, 4),
        "legacy_auto_units_share_of_total": round(s["recovery"]["ice_units_in_legacy_auto_groups"] / total_units, 4),
        "v1_propose_capped_only_by_gap": sum(1 for g in gs if g["v1_group_primary_code"] == "PROPOSE_SERIES_STRONG_CAPPED"
                                              and g["v1_group_codes"].count(":blocking") == 1 and "SER_MISSING_ROW_SEMANTICS_UNCONFIRMED:blocking" in g["v1_group_codes"]),
        "v1_propose_strong_capped": sum(1 for g in gs if g["v1_group_primary_code"] == "PROPOSE_SERIES_STRONG_CAPPED"),
        "v1_link_types_of_decided_groups": dict(Counter(g["v1_group_link_type"] for g in gs if g["v1_group_link_type"]).most_common()),
        "sheet_rows": len(sheet),
    }

    # ---- sheet
    tiers = Counter(r["review_tier"] for r in sheet)
    last_of_tier = {}
    for r in sheet:
        last_of_tier[r["review_tier"]] = r
    brand_rows = Counter(r["ice_brand"] for r in sheet if r["review_tier"] <= 2)
    s["review_sheet"] = {
        "rows": len(sheet), "rows_by_tier": {f"{t} {RV.TIER_LABELS[t]}": tiers.get(t, 0) for t in sorted(RV.TIER_LABELS)},
        "cumulative_unique_group_units_share_at_end_of_tier": {t: last_of_tier[t]["cumulative_unique_group_units_share"] for t in sorted(last_of_tier)},
        "rows_with_no_candidate": sum(1 for r in sheet if not r["candidate_canonical_model_id"]),
        "groups_not_in_sheet": len(groups) - len({r["model_group_id"] for r in sheet}),
        "units_not_in_sheet_share": round(sum(g["ice_lifetime_units"] for gid, g in groups.items() if gid not in {r["model_group_id"] for r in sheet}) / total_units, 4),
        "brands_in_tiers_1_2": len(brand_rows), "brands_with_5_or_more_rows_in_tiers_1_2": sum(1 for v in brand_rows.values() if v >= 5),
        "top_brands_in_tiers_1_2": dict(brand_rows.most_common(12)),
        "suspicious_case_rows": dict(Counter(c for r in sheet for c in r["suspicious_cases"].split(";") if c)),
        "cutoffs": {"high_volume_lifetime_units": RV.HIGH_VOLUME_LIFETIME_UNITS, "high_volume_last24m_units": RV.HIGH_VOLUME_LAST24M_UNITS,
                    "no_candidate_min_lifetime_units": RV.NO_CANDIDATE_MIN_LIFETIME_UNITS},
    }

    # ---- biggest groups with nothing to review (potential catalog gaps)
    nc = [g for g in gs if g["v1_group_outcome"] in ("NO_CANDIDATE", "INSUFFICIENT_DATA") and g["legacy_chosen"] == ""]
    s["uncovered_groups_top"] = [{"model_group_id": g["model_group_id"], "name": g["ice_model_name"], "brand": g["ice_brand"], "lifetime_units": g["ice_lifetime_units"],
                                  "last24m_units": g["ice_units_last24m"], "v1": g["v1_group_primary_code"]} for g in sorted(nc, key=lambda g: -g["ice_lifetime_units"])[:15]]

    # ---- data observations used as caveats
    gens_ended = sum(1 for g in ext["generations"] if g["ended"])
    s["data_observations"] = {
        "tdr_models": len(ext["models"]), "tdr_models_with_series": len(ext["tdr_series"]["rows"]), "tdr_models_without_series": len(ext["models"]) - len(ext["tdr_series"]["rows"]),
        "tdr_models_body_type_populated": sum(1 for m in ext["models"] if m["body_type"]),
        "tdr_generations": len(ext["generations"]), "tdr_generations_with_ended_date": gens_ended,
        "tdr_generations_without_launch_date": sum(1 for g in ext["generations"] if not g["launched"]),
        "tdr_registration_months": f"{ext['tdr_series']['start']} .. {ext['tdr_series']['end']}",
        "ice_coverage_months": f"{ice['coverage_buddhist']['from']} .. {ice['coverage_buddhist']['to']} (Buddhist era)",
        "ice_groups_with_absent_in_coverage_months": sum(1 for g in gs if g["ice_absent_in_coverage_months"] > 0),
        "ice_groups_absent_months_median": sorted(g["ice_absent_in_coverage_months"] for g in gs)[len(gs) // 2],
        "tdr_period_rows_units_last3": ext["tdr_period_totals"][-3:],
    }

    # ---- sensitivity (from the committed results file)
    if sensitivity:
        s["sensitivity"] = {"groups": sensitivity["groups"], "baseline_outcomes": sensitivity["baseline_outcomes"],
                            "variants": [{k: v[k] for k in ("id", "adoption_entry", "description", "hypothetical", "groups_changed", "groups_changed_in_legacy_rows",
                                                            "auto_gained", "auto_lost", "outcomes", "moves", "examples_changed") if k in v} for v in sensitivity["variants"]]}
    return s


# --------------------------------------------------------------------------------------------- what still needs owner labels
#: What the real data adds to an entry that the two numeric columns cannot say. Only statements the data supports.
ENTRY_NOTES = {
    "fingerprint_bands": "Not measurable on one package: it needs the same pairs in a second package, and M7.0 is the only one.",
    "series_monthly_fit": "No pair that passes correlation and ratio sits near the fit boundary, and moving the key moves nothing: on this data it cannot be placed.",
    "candidates_margin": "No group has two close rivals, and moving either margin moves nothing: on this data it cannot be placed.",
    "granularity_part_of_ratio": "Few pairs read as PART_OF at all (a handful of SUBJECT_FINER names); moving the ratio to 1.3 or 2.0 moves nothing.",
    "subject_discovery_thresholds": "Changes the size of the discovery queue, never an outcome.",
    "series_absent_row_gap": "Most gap months are months in which BOTH sources have no row (before a launch, after a withdrawal); Ice's answer alone lifts almost nothing (see the gap section).",
    "lexical_fuzzy_min_length": "The near-miss pairs mix real typos (Binguo/Bingo) with look-alike model codes (EX30/EX40, XC60/XC90): the length rule cannot tell them apart, labels can.",
    "data_sufficiency_wrong_series": "Many pairs sit near the bounds, but few of them decide a group (the name relation usually decides first).",
    "attributes_lifecycle": "Only launch dates can act (almost no generation has an end date); the grace and share values move up to ~10 groups.",
    "series_minimums": "The AUTO volume minimum is the one that moves AUTO (240 units removes 6 AUTO groups); the month minimums move none on this data.",
}

LABEL_NEEDS = {
    "calibration": "OWNER LABELS",
    "design_choice": "OWNER DECISION",
    "representation": "OWNER SIGN-OFF",
}


def pending_entries() -> list[dict]:
    return [e for e in loader.load_adoption()["entries"] if e["status"] == "pending"]


def entry_table(summary: dict) -> list[dict]:
    """One row per pending adoption entry: what kind of input settles it, and what the real data already says about it."""
    sens = defaultdict(list)
    for v in (summary.get("sensitivity") or {}).get("variants", []):
        sens[v["adoption_entry"].split(" (")[0]].append(v)
    bounds = defaultdict(list)
    for b in summary["boundaries"]:
        bounds[b["adoption_entry"]].append(b)
    rows = []
    for e in pending_entries():
        needs = LABEL_NEEDS[e["class"]]
        if e["id"] == "series_absent_row_gap":
            needs = "ICE ANSWER (Q-ICE-ABSENT-ROW) + TDR GUARANTEE, THEN OWNER LABELS"
        vs = [v for v in sens.get(e["id"], []) if not v["hypothetical"]]
        rows.append({
            "id": e["id"], "class": e["class"], "keys": e["keys"], "needs": needs,
            "settles_with": e.get("settles_with") or e.get("decision"),
            "max_groups_changed_by_one_step": max((v["groups_changed"] for v in vs), default=None),
            "max_auto_gained": max((v["auto_gained"] for v in vs), default=None), "max_auto_lost": max((v["auto_lost"] for v in vs), default=None),
            "note": ENTRY_NOTES.get(e["id"], ""),
            "boundary_pairs": sum(b["pairs"] for b in bounds.get(e["id"], [])) if bounds.get(e["id"]) else None,
            "boundary_groups": sum(b["groups"] for b in bounds.get(e["id"], [])) if bounds.get(e["id"]) else None,
        })
    return rows
