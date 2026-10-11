"""Replay of the first-run R6 matcher (legacy `vehreg.ice_crosswalk` / `tools.ice_crosswalk_match`), offline.

The replay calls the legacy module's own pure functions, unchanged, on the same inputs the 2026-10-10 run read (the live M7.0 data,
which is the archived package, and the TDR `registrations` / `vehicle_models` tables, committed under `inputs/`). It reproduces the
stored `ice_model_crosswalk` rows exactly (candidate, status, method, reason text and the full sha256 decision fingerprint) -- see
`verify_against_stored` -- so the legacy numbers and windows reported in the calibration dataset are not a re-interpretation.

It differs from `tools.ice_crosswalk_match.match_one_group` only in that it keeps EVERY candidate the legacy rules evaluated (the
legacy run stored the single best one per group), so the dataset can show what the other candidates looked like.
"""
from __future__ import annotations

from collections import defaultdict

from vehreg import ice_crosswalk as X

from . import adapters as A

SERIES_WINDOW_MONTHS = 24    # tools.ice_crosswalk_match.SERIES_WINDOW_MONTHS (a literal there too)
MASTER_VERSION = "7.0"


def legacy_inputs(ice: dict, ext: dict) -> dict:
    """The legacy run's inputs in the legacy run's own shapes (Buddhist-era periods, zero for nothing)."""
    ts = ext["tdr_series"]
    months = A.month_range(ts["start"], ts["end"])
    series = {}
    for cid, cells in ts["rows"].items():
        series[cid] = {X.gregorian_date_to_buddhist_period(m + "-01"): float(v) for m, v in zip(months, cells.split(",")) if v != ""}
    models = {m["canonical_id"]: {"canonical_id": m["canonical_id"], "name_en": m["name_en"], "brand_id": m["brand_id"]} for m in ext["models"]}
    brands = {b["canonical_id"]: b["name_en"] for b in ext["brands"]}
    alias_map = {" ".join(a["brand"].strip().lower().split()): a["alias_group"] for a in ext["brand_aliases"]}
    return {"tdr_series": series, "models": models, "brands": brands, "alias_map": alias_map}


def evaluate_pair(group: dict, ice_series: dict[str, float], cid: str, inputs: dict, group_brand_key: str | None = None) -> dict:
    """The legacy evaluation of one (Ice group, TDR model) pair: series (zero-filled over the group's newest 24 Ice months), name, decision."""
    alias_map = inputs["alias_map"]
    group_brand_key = group_brand_key or X.normalize_brand(group["brand"], alias_map)
    model = inputs["models"][cid]
    candidate_brand = inputs["brands"].get(model["brand_id"], "")
    periods = sorted(ice_series)[-SERIES_WINDOW_MONTHS:]      # _recent_periods: the group's own newest 24 months WITH a row
    tdr = inputs["tdr_series"].get(cid, {})
    xs, ys = X.build_paired_series(periods, ice_series, tdr)
    series = X.evaluate_series(xs, ys)
    cand_name = X.apply_model_name_alias(X.normalize_model_name(model["name_en"], candidate_brand), group_brand_key)
    grp_name = X.apply_model_name_alias(X.normalize_model_name(group["model_name"], group["brand"]), group_brand_key)
    name_score = X.name_similarity(cand_name, grp_name)
    missing = [A.b2g(p) for p in periods if p not in tdr]
    return {
        "canonical_model_id": cid,
        "in_pool": X.normalize_brand(candidate_brand, alias_map) == group_brand_key,
        "correlation": series.correlation, "ratio": series.ratio, "strong": series.strong, "name_score": name_score,
        "decision": X.decide_match(series=series, name_score=name_score),
        "window": {
            "periods": [A.b2g(p) for p in periods],
            "first": A.b2g(periods[0]) if periods else None,
            "last": A.b2g(periods[-1]) if periods else None,
            "months": len(periods),
            "calendar_span": (A.pidx(A.b2g(periods[-1])) - A.pidx(A.b2g(periods[0])) + 1) if periods else 0,
            "tdr_zero_filled": missing,
            "ice_units": sum(xs), "tdr_units": sum(ys),
        },
    }


def evaluate_group(group: dict, ice_series: dict[str, float], inputs: dict) -> list[dict]:
    """Every brand-matching TDR model evaluated by the legacy rules for one Ice group, with the legacy decision (or None)."""
    group_brand_key = X.normalize_brand(group["brand"], inputs["alias_map"])
    return [c for c in (evaluate_pair(group, ice_series, cid, inputs, group_brand_key) for cid in inputs["models"]) if c["in_pool"]]


def choose(candidates: list[dict]) -> dict | None:
    """The legacy choice: the strongest decision by `decision_rank`; the first in iteration order wins an exact tie."""
    best = None
    for c in candidates:
        if c["decision"] is None:
            continue
        if best is None or X.decision_rank(c["decision"]) > X.decision_rank(best["decision"]):
            best = c
    return best


def replay(ice: dict, ext: dict) -> dict:
    """{model_group_id: {"candidates": [...], "chosen": candidate | None}} for every Ice group (the legacy iteration order)."""
    inputs = legacy_inputs(ice, ext)
    out = {}
    for g in ice["groups"]:
        gid = g["model_group_id"]
        series = {p: v for p, v in ice["cells"].get(gid, {}).items()}
        cands = evaluate_group(g, series, inputs)
        out[gid] = {"candidates": cands, "chosen": choose(cands)}
    return out


def fingerprint(gid: str, cand: dict) -> str:
    d = cand["decision"]
    return X.decision_fingerprint(model_group_id=gid, canonical_model_id=cand["canonical_model_id"], correlation=d.correlation,
                                  ratio=d.ratio, name_score=d.name_score, master_version=MASTER_VERSION)


def verify_against_stored(replayed: dict, stored_rows: list[dict]) -> dict:
    """Compare the replay with the stored rows. Every matcher row must reproduce exactly; the ADMIN row is a STRUCTURE proposal."""
    by_group = defaultdict(list)
    for r in stored_rows:
        by_group[r["model_group_id"]].append(r)
    exact, mismatches, no_candidate = 0, [], 0
    for gid, rep in replayed.items():
        rows = [r for r in by_group.get(gid, []) if r["match_method"] != "ADMIN"]
        chosen = rep["chosen"]
        if chosen is None:
            if rows:
                mismatches.append({"model_group_id": gid, "problem": "stored row but the replay found no candidate"})
            else:
                no_candidate += 1
            continue
        if not rows:
            mismatches.append({"model_group_id": gid, "problem": "replay found a candidate but nothing is stored"})
            continue
        r, d = rows[0], chosen["decision"]
        ok = (r["canonical_model_id"] == chosen["canonical_model_id"] and r["status"] == d.status and r["match_method"] == d.match_method
              and r["decision_fingerprint"] == fingerprint(gid, chosen) and r["reason"] == d.reason)
        if ok:
            exact += 1
        else:
            mismatches.append({"model_group_id": gid, "problem": "differs from the stored row"})
    return {"groups": len(replayed), "stored_rows": len(stored_rows),
            "stored_matcher_rows": sum(1 for r in stored_rows if r["match_method"] != "ADMIN"),
            "stored_admin_rows": sum(1 for r in stored_rows if r["match_method"] == "ADMIN"),
            "reproduced_exactly": exact, "no_candidate_and_nothing_stored": no_candidate, "mismatches": mismatches}
