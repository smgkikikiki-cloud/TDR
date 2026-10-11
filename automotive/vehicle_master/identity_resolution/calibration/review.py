"""The owner-adjudication sheet: machine evidence prefilled, owner columns blank, ordered so the first rows matter most.

Rules this module keeps (a test enforces them):

* the four owner columns (`owner_verdict`, `owner_link_type`, `owner_canonical_model_id`, `owner_notes`) are always empty here;
* the legacy R6 decision lives in its own columns (`legacy_r6_status`, `legacy_r6_match_method`) and is never copied into an owner column;
* the tier of a row is the FIRST of the owner's seven priorities it matches; every matching tier is listed in `review_tiers_matched`;
* volumes order rows inside a tier and say how much of the market a row covers. They are never evidence.
"""
from __future__ import annotations

from collections import defaultdict

from . import ref_eval_core as P

OWNER_COLUMNS = ["owner_verdict", "owner_link_type", "owner_canonical_model_id", "owner_notes"]
OWNER_VERDICTS = ["CORRECT_EQUIVALENT", "CORRECT_PART_OF", "CORRECT_COMPOSED_OF", "WRONG_TARGET", "NO_TDR_TARGET", "INSUFFICIENT_EVIDENCE"]
OWNER_LINK_TYPES = ["EQUIVALENT", "PART_OF", "COMPOSED_OF"]

TIER_LABELS = {
    1: "legacy AUTO row",
    2: "high-volume legacy PROPOSED row",
    3: "suspicious known case",
    4: "outcome changes materially under the common-overlap window",
    5: "PART_OF / COMPOSED_OF candidate",
    6: "ambiguous / several viable candidates",
    7: "low-volume tail, and groups with no candidate in the sheet",
}

#: "High volume" is a prioritisation cutoff, not a policy value: >= this many lifetime units, or >= this many in the newest 24 months.
HIGH_VOLUME_LIFETIME_UNITS = 10_000
HIGH_VOLUME_LAST24M_UNITS = 1_000
#: A group with no candidate under either method gets a sheet row only when it carries at least this many lifetime units.
NO_CANDIDATE_MIN_LIFETIME_UNITS = 100

#: Known suspicious cases. `ice` are Ice model_group_id prefixes, `tdr` TDR canonical_id prefixes; a row is in the case when its Ice group OR
#: its candidate target matches. `source` says where the case comes from (the owner's list, or the same pattern).
SUSPICIOUS_CASES = [
    {"id": "dmax_vs_mux", "source": "owner-named", "label": "Isuzu D-Max vs MU-X",
     "ice": ["isuzu-isuzu-d-max", "isuzu-isuzu-mu-x"], "tdr": ["isuzu.dmax", "isuzu.mux"]},
    {"id": "ranger_granularity", "source": "owner-named", "label": "Ford Ranger granularity (cab / double cab / Raptor)",
     "ice": ["ford-ford-ranger"], "tdr": ["ford.ranger"]},
    {"id": "hilux_granularity", "source": "owner-named", "label": "Toyota Hilux granularity (Revo / Travo / Champ, cab / double cab)",
     "ice": ["toyota-hilux"], "tdr": ["toyota.hilux"]},
    {"id": "pickup_cab_granularity", "source": "same pattern as the owner-named cases", "label": "Pickups that TDR splits by cab (Triton, Navara, BT-50)",
     "ice": ["mitsubishi-triton", "nissan-navara", "mazda-mazda-bt-50"], "tdr": ["mitsubishi.triton", "nissan.navara", "mazda.bt50"]},
    {"id": "city_hatchback", "source": "README defect table", "label": "Honda City vs City Hatchback",
     "ice": ["honda-city"], "tdr": ["honda.city"]},
    {"id": "maxus_mifa_under_mg", "source": "README defect table", "label": "Maxus Mifa registered under MG",
     "ice": ["maxus-"], "tdr": ["mg.mg_maxus"]},
    {"id": "deepal_under_changan", "source": "README defect table", "label": "Deepal models filed under Changan",
     "ice": ["changan-deepal"], "tdr": ["deepal."]},
]


def suspicious_ids(group_id: str, candidate_ids: str) -> list[str]:
    cands = [c for c in candidate_ids.split("+") if c]
    out = []
    for case in SUSPICIOUS_CASES:
        if any(group_id.startswith(p) for p in case["ice"]) or any(c.startswith(p) for c in cands for p in case["tdr"]):
            out.append(case["id"])
    return out


def is_high_volume(row: dict) -> bool:
    return row["ice_lifetime_units"] >= HIGH_VOLUME_LIFETIME_UNITS or row["ice_units_last24m"] >= HIGH_VOLUME_LAST24M_UNITS


def legacy_outcome_class(row: dict) -> str:
    """The legacy GROUP outcome in the vocabulary the sheet compares against (the stored row, or none)."""
    if row["legacy_chosen"] == "":
        return "NONE"
    return "AUTO" if row["_legacy_group_status"] == "AUTO" else "PROPOSED"


def outcome_changed(row: dict) -> bool:
    """AUTO-ness or existence of a decision differs between the legacy run and Contract v1 (reporting convention, decides nothing)."""
    leg = row["_legacy_group_status"]
    v1 = row["v1_group_outcome"]
    if leg == "AUTO":
        return v1 != "AUTO"
    if leg == "PROPOSED":
        return v1 in ("AUTO", "NO_CANDIDATE", "INSUFFICIENT_DATA")
    return v1 in ("AUTO", "PROPOSE", "AMBIGUOUS")


def tiers_matched(row: dict) -> list[int]:
    tiers = []
    legacy_selected = row["legacy_run_selected"]
    if legacy_selected and row["legacy_status"] == "AUTO":
        tiers.append(1)
    if legacy_selected and row["legacy_status"] == "PROPOSED" and is_high_volume(row):
        tiers.append(2)
    if row["suspicious_cases"]:
        tiers.append(3)
    if row["series_material_change"] or outcome_changed(row):
        tiers.append(4)
    if row["v1_link_candidate"] in ("PART_OF", "COMPOSED_OF"):
        tiers.append(5)
    if row["plausible_candidates"] >= 2 or row["v1_proposable_candidates"] >= 2 or row["v1_group_outcome"] == "AMBIGUOUS":
        tiers.append(6)
    if not tiers:
        tiers.append(7)
    return tiers


def in_sheet(row: dict) -> bool:
    """Which dataset pairs the owner is asked to judge."""
    origin = row["candidate_origin"].split(";")
    if "LEGACY_STORED" in origin or "V1_PRIMARY" in origin or "V1_ALTERNATIVE" in origin:
        return True
    if row["v1_series_state"] == "STRONG":
        return True        # a strong common-window series is exactly what the owner's label is needed for, even when a name veto removed the pair
    return row["v1_link_candidate"] in ("PART_OF", "COMPOSED_OF") and row["v1_proposable"]


def other_candidates(pairs: list[dict], row: dict, limit: int = 3) -> str:
    """The best other pairs of the same group, so the owner can name the right target when the shown one is wrong."""
    mine = row["candidate_canonical_model_id"]
    others = [p for p in pairs if p["model_group_id"] == row["model_group_id"] and p["candidate_canonical_model_id"] != mine]
    others.sort(key=lambda p: (0 if p["v1_proposable"] else 1, 0 if p["v1_series_state"] == "STRONG" else 1,
                               -(p["legacy_name_score"] or 0), p["candidate_canonical_model_id"]))
    parts = []
    for p in others[:limit]:
        bits = [p["v1_name_relation"], p["v1_series_state"]]
        if p["v1_correlation"] is not None:
            bits.append(f"corr {p['v1_correlation']:.3f} ratio {p['v1_ratio']:.3f}")
        parts.append(f"{p['candidate_canonical_model_id']} ({', '.join(bits)})")
    return " | ".join(parts)


def question(row: dict) -> str:
    unspecified = row["ice_model_name"].strip().lower() in {x.lower() for x in P.POL["lexical"]["unavailable_name_values"] if x}
    if not row["candidate_canonical_model_id"] and unspecified:
        return (f"Ice group {row['model_group_id']} ({row['ice_brand']}) has no model name at all (Ice's own 'unspecified' bucket for this brand). "
                f"Expected answer: NO_TDR_TARGET, unless TDR keeps a brand-level bucket for it (then give owner_canonical_model_id).")
    if not row["candidate_canonical_model_id"]:
        return (f"Neither the legacy matcher nor Contract v1 proposes a TDR model for Ice '{row['ice_model_name']}' ({row['ice_brand']}, {row['model_group_id']}) "
                f"(pairs that were considered and excluded are in other_candidates). Is there a TDR model for it (give owner_canonical_model_id), or NO_TDR_TARGET?")
    link = {"EQUIVALENT": "the same vehicle as", "PART_OF": "a part of (narrower than)", "COMPOSED_OF": "made up of"}[row["v1_link_candidate"]]
    return (f"Is Ice '{row['ice_model_name']}' ({row['ice_brand']}, {row['model_group_id']}) {link} TDR '{row['tdr_model_name']}' "
            f"({row['candidate_canonical_model_id']})? Verdict applies to the candidate shown on this row.")


SHEET_COLUMNS = [
    "review_rank", "review_tier", "review_tier_label", "review_tiers_matched", "suspicious_cases", "cumulative_unique_group_units_share",
    "question",
    # --- identity of the pair
    "model_group_id", "ice_model_name", "ice_brand", "ice_identity_status", "ice_body",
    "candidate_canonical_model_id", "tdr_model_name", "tdr_brand", "tdr_status", "tdr_body_type", "candidate_origin",
    # --- legacy R6 (the first run; kept apart from the owner columns)
    "legacy_r6_status", "legacy_r6_match_method", "legacy_r6_row_id", "legacy_correlation", "legacy_ratio", "legacy_name_score",
    "legacy_window_first", "legacy_window_last", "legacy_window_months", "legacy_window_tdr_zero_filled_months", "legacy_window_tdr_zero_filled_list",
    # --- Contract v1, recomputed on the common observation window (dry run: binding=false)
    "v1_link_candidate", "v1_brand_relation", "v1_name_relation", "v1_name_score",
    "v1_series_state", "v1_series_unavailable_reason", "v1_correlation", "v1_ratio", "v1_monthly_fit_share",
    "v1_common_months", "v1_joint_nonzero_months", "v1_subject_units", "v1_target_units", "v1_window_first", "v1_window_last", "v1_semantics_gap_months",
    "v1_codes_supporting", "v1_codes_blocking", "v1_codes_excluded", "v1_codes_info",
    "v1_group_outcome", "v1_group_primary_code", "v1_group_targets", "v1_group_link_type",
    "series_material_change", "series_material_change_why", "outcome_changed_vs_legacy",
    # --- context
    "lineage_roles", "lineage_events", "lineage_ops",
    "ice_lifetime_units", "ice_units_last12m", "ice_units_last24m", "ice_first_month", "ice_last_month",
    "tdr_lifetime_units", "tdr_units_last12m", "tdr_units_last24m",
    "legacy_groups_claiming_this_target", "v1_groups_claiming_this_target", "other_candidates",
] + OWNER_COLUMNS


def build_sheet(pairs: list[dict], groups: dict, stored_by_group: dict) -> list[dict]:
    """Rows of the owner sheet, ordered by (tier, newest-24-month units, lifetime units, ids)."""
    legacy_status = {}
    for gid, rows in stored_by_group.items():
        main = [r for r in rows if r["match_method"] != "ADMIN"]
        legacy_status[gid] = main[0]["status"] if main else ("PROPOSED" if rows else "NONE")
    rows = []
    for p in pairs:
        if not in_sheet(p):
            continue
        r = dict(p)
        r["_legacy_group_status"] = legacy_status.get(p["model_group_id"], "NONE")
        r["suspicious_cases"] = joined_ids(suspicious_ids(p["model_group_id"], p["candidate_canonical_model_id"]))
        r["outcome_changed_vs_legacy"] = outcome_changed(r)
        rows.append(r)
    covered = {r["model_group_id"] for r in rows}
    for gid, g in groups.items():
        if gid in covered or g["ice_lifetime_units"] < NO_CANDIDATE_MIN_LIFETIME_UNITS:
            continue
        r = {k: "" for k in pairs[0]}
        r.update(g)
        r.update({"candidate_canonical_model_id": "", "candidate_origin": "NONE", "plausible_candidates": g.get("plausible_candidates", 0), "legacy_run_selected": False, "series_material_change": False,
                  "series_material_change_why": "", "v1_link_candidate": "", "v1_proposable": False, "v1_series_state": "",
                  "_legacy_group_status": legacy_status.get(gid, "NONE"), "suspicious_cases": joined_ids(suspicious_ids(gid, "")),
                  "outcome_changed_vs_legacy": False})
        rows.append(r)
    for r in rows:
        r["review_tiers_matched"] = ";".join(str(t) for t in tiers_matched(r))
        r["review_tier"] = int(r["review_tiers_matched"].split(";")[0])
        r["review_tier_label"] = TIER_LABELS[r["review_tier"]]
        r["legacy_r6_status"] = r["legacy_status"]
        r["legacy_r6_match_method"] = r["legacy_match_method"]
        r["legacy_r6_row_id"] = r["legacy_row_id"]
        r["question"] = question(r)
    rows.sort(key=lambda r: (r["review_tier"], -r["ice_units_last24m"], -r["ice_lifetime_units"], r["model_group_id"], r["candidate_canonical_model_id"]))
    total = sum(g["ice_lifetime_units"] for g in groups.values()) or 1
    seen, cum = set(), 0
    for i, r in enumerate(rows, 1):
        r["review_rank"] = i
        if r["model_group_id"] not in seen:
            seen.add(r["model_group_id"])
            cum += groups[r["model_group_id"]]["ice_lifetime_units"]
        r["cumulative_unique_group_units_share"] = round(cum / total, 4)
        r["other_candidates"] = other_candidates(pairs, r)
        for c in OWNER_COLUMNS:
            r[c] = ""
    return rows


def joined_ids(ids: list[str]) -> str:
    return ";".join(ids)
