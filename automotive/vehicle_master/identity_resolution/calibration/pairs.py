"""Assemble the calibration dataset: one row per (Ice group, candidate TDR target) pair worth a human look.

Three kinds of evidence sit side by side and are never mixed:

* `legacy_*`  what the first-run R6 matcher saw and stored (replayed offline; verified identical to the stored rows);
* `v1_*`      what Contract v1 (as the reference evaluator reads SPEC section 5-8, policy binding=false, i.e. a dry run) says on the
              same pair: common observation window, null != 0, name/brand relation, link type, reason codes;
* `owner_*`   left blank in the review sheet. Nothing in this module reads or writes an owner verdict.

A pair is kept when it is the legacy stored candidate, the Contract v1 decision (primary or alternative), or otherwise relevant: its
name relation is not a plain contradiction, or its common-window series is STRONG, or the legacy rules would have proposed it.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from identity_resolution.providers import base as provider_boundary

from . import adapters as A
from . import legacy as L
from . import ref_eval_core as P
from . import ref_eval_resolve as R

#: Name relations that mean "the two names are plausibly about the same or a neighbouring vehicle" (everything but CONTRADICTION / UNAVAILABLE).
RELATED_NAME_RELATIONS = ("EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV", "FUZZY", "SUBJECT_COARSER", "SUBJECT_FINER", "SIBLING")

#: Reporting conventions for "the series evidence changed materially". They are NOT policy keys and decide nothing.
MATERIAL_DELTA_CORRELATION = 0.05
MATERIAL_RATIO_CHANGE = 0.10

RECENT_END = "2026-08"        # the last month both sources cover (the end of the v1 comparison window W)


# --------------------------------------------------------------------------------------------------------------- volumes
def series_volumes(series: dict | None, months_end: str = RECENT_END) -> dict:
    if not series:
        return {"lifetime": 0, "recent12": 0, "recent24": 0, "first": None, "last": None, "months_with_rows": 0, "absent_in_coverage": 0}
    start = A.pidx(series["start"])
    end = A.pidx(months_end)
    life = r12 = r24 = 0
    first = last = None
    rows = 0
    for i, c in enumerate(series["counts"]):
        if c is None:
            continue
        idx = start + i
        life += c
        rows += 1
        first = idx if first is None else first
        last = idx
        if end - 11 <= idx <= end:
            r12 += c
        if end - 23 <= idx <= end:
            r24 += c
    absent = len((series.get("absent_rows") or {}).get("months", []))
    return {"lifetime": life, "recent12": r12, "recent24": r24, "first": None if first is None else A.pstr(first),
            "last": None if last is None else A.pstr(last), "months_with_rows": rows, "absent_in_coverage": absent}


def sum_volumes(vols: list[dict]) -> dict:
    return {k: sum(v[k] for v in vols) for k in ("lifetime", "recent12", "recent24")}


# ------------------------------------------------------------------------------------------------------------ small helpers
def fmt(x, places=None):
    if x is None:
        return ""
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, float):
        if places is not None:
            return f"{x:.{places}f}"
        return repr(x)
    return str(x)


def joined(items, sep=";"):
    return sep.join(str(i) for i in items)


def candidate_codes(e: dict, group_status: str) -> dict:
    """Per-candidate reason codes by role, composed exactly as `_classify` composes them for the chosen candidate (SPEC section 8.7)."""
    c = e["c"]
    ev = c["evidence"]
    b = ev["brand"] or {}
    n = ev["name"] or {}
    s = ev["series"] or {}
    supporting, blocking, info = [], [], []
    if b.get("relation") == "EXACT": supporting.append("BRND_EXACT")
    elif b.get("relation") == "ALIAS_SAME": supporting.append("BRND_ALIAS_SAME")
    elif b.get("relation") == "ALIAS_RELABEL": supporting.append("BRND_ALIAS_RELABEL")
    elif b.get("relation") == "ALIAS_RELATED": info.append("BRND_ALIAS_RELATED")
    support = {"EQUAL": "NAME_EQUAL", "EQUAL_VIA_MODEL_ALIAS": "NAME_EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV": "NAME_EQUAL_VIA_TOKEN_EQUIV"}
    if n.get("relation") in support: supporting.append(support[n["relation"]])
    if e["series_strong"]: supporting.append("SER_BUNDLE_STRONG" if e["link"] == "COMPOSED_OF" else "SER_STRONG")
    if e["link"] == "COMPOSED_OF": supporting.append("GRAN_PROVIDER_COARSER")
    if e["link"] == "PART_OF": supporting.append("GRAN_PROVIDER_FINER")
    for x in e["block"]:
        if x == "NAME_ONLY_NOT_AUTO" and e["series_strong"]:
            continue
        blocking.append(x)
    if e["link"] != "PART_OF":
        for x in P.series_codes_from_tuple(s):
            role = P.series_role(x, "blocking", s)
            (blocking if role == "blocking" else info).append(x)
    elif s.get("semantics_gap_months", 0) > 0:
        info.append(P.GAP_CODE)
    if n.get("relation") == "UNAVAILABLE" and "NAME_UNAVAILABLE" not in blocking: info.append("NAME_UNAVAILABLE")
    a = ev["attributes"] or {}
    if a.get("body") == "UNKNOWN": info.append("ATTR_BODY_UNKNOWN")
    if a.get("lifecycle") == "UNKNOWN": info.append("GEN_LIFECYCLE_UNKNOWN")
    if group_status == "provisional": info.append("SUBJ_PROVISIONAL")
    dedup = lambda xs: [x for i, x in enumerate(xs) if x not in xs[:i]]
    return {"supporting": dedup(supporting), "blocking": dedup(blocking), "info": dedup(info), "excluded": dedup(e["excluded"])}


def legacy_class(corr, ratio, strong) -> str:
    if strong:
        return "STRONG"
    return "UNDEFINED" if (corr is None or ratio is None) else "WEAK"


def material_change(leg_class, leg_corr, leg_ratio, v1_state, v1_corr, v1_ratio) -> list[str]:
    """Why the series evidence differs materially between the legacy zero-filled window and the v1 common window (reporting convention)."""
    why = []
    v1_class = "STRONG" if v1_state == "STRONG" else ("UNAVAILABLE" if v1_state == "UNAVAILABLE" else "WEAK")
    if (leg_class == "STRONG") != (v1_class == "STRONG"):
        why.append("STRONG_FLIPS")
    if (leg_class == "UNDEFINED") != (v1_class == "UNAVAILABLE"):
        why.append("AVAILABILITY")
    if leg_corr is not None and v1_corr is not None and abs(v1_corr - leg_corr) >= MATERIAL_DELTA_CORRELATION:
        why.append("CORRELATION")
    if leg_ratio and v1_ratio is not None and abs(v1_ratio / leg_ratio - 1) >= MATERIAL_RATIO_CHANGE:
        why.append("RATIO")
    return why



def gap_breakdown(S: dict | None, T: dict | None, max_months: int | None = None) -> tuple[int, int, int]:
    """The unconfirmed-gap months of SPEC 6.2a split by who lacks the row: (both sources, only the subject, only the target).

    Same window as `series_evidence`: the `max_months` calendar months ending at the last month of the coverage intersection. The three numbers
    add up to `evidence.series.semantics_gap_months`.
    """
    if not S or not T or not S.get("coverage_declared", True) or not T.get("coverage_declared", True):
        return (0, 0, 0)
    max_months = max_months or P.POL["series"]["window"]["max_months"]
    sa, ta = P.pidx(S["start"]), P.pidx(T["start"])
    sb, tb = sa + len(S["counts"]) - 1, ta + len(T["counts"]) - 1
    lo, hi = max(sa, ta), min(sb, tb)
    if hi < lo:
        return (0, 0, 0)
    partial = {P.pidx(x) for x in S.get("partial_periods", [])} | {P.pidx(x) for x in T.get("partial_periods", [])}
    us, ut = P._unconf(S), P._unconf(T)
    both = only_s = only_t = 0
    for i in range(lo, hi + 1):
        if i <= hi - max_months or i in partial:
            continue
        in_s, in_t = i in us, i in ut
        if in_s and in_t:
            both += 1
        elif in_s:
            only_s += 1
        elif in_t:
            only_t += 1
    return (both, only_s, only_t)


def lineage_context(gid: str, snap_events: list[dict], ops: list[dict], redirects: set[str]) -> dict:
    roles, text = [], []
    for e in snap_events:
        if e["old_id"] == gid or e["new_id"] == gid:
            share = f" {e['share_of_old_pct']:g}%" if e.get("share_of_old_pct") is not None else ""
            text.append(f"{e['event_type']}:{e['old_id']}>{e['new_id']}{share}")
            roles.append(("OLD" if e["old_id"] == gid else "NEW") + "_" + e["event_type"])
    my_ops = [f"{o['op']}:{o['primary']}" for o in ops if o.get("old_id") == gid or o.get("new_id") == gid]
    return {"roles": sorted(set(roles)), "events": text, "ops": sorted(set(my_ops)),
            "quarantined": any(o["op"] == "QUARANTINE" and o["old_id"] == gid for o in ops),
            "redirect_recorded": any(t.startswith(("MERGE:", "RENAME:")) and (f":{gid}>" in t or t.endswith(f">{gid}")) for t in redirects)}


# ------------------------------------------------------------------------------------------------------------ the assembly
def assemble(ice: dict, ext: dict) -> dict:
    """Everything the dataset, the review sheet and the report need, computed once."""
    legacy_rep = L.replay(ice, ext)
    verification = L.verify_against_stored(legacy_rep, ext["crosswalk"])
    linputs = L.legacy_inputs(ice, ext)
    snap = A.build_snapshot(ice, ext)
    provider_boundary.validate_snapshot(snap)   # record.schema.json + the capability data (I4a): the same check any adapter must pass
    res = R.resolve(snap)
    if "refusal" in res:
        raise RuntimeError(f"the reference evaluator refused the snapshot: {res['refusal']}")

    groups = {g["model_group_id"]: g for g in ice["groups"]}
    subjects = {s["entity_id"]: s for s in snap["subjects"]}
    targets = {t["target_id"]: t for t in snap["targets"]}
    brands = {b["canonical_id"]: b["name_en"] for b in ext["brands"]}
    models = {m["canonical_id"]: m for m in ext["models"]}
    stored = {(r["model_group_id"], r["canonical_model_id"]): r for r in ext["crosswalk"]}
    stored_by_group = defaultdict(list)
    for r in ext["crosswalk"]:
        stored_by_group[r["model_group_id"]].append(r)
    redirect_keys = set(snap["lineage"]["applied_event_keys"])

    ts = ext["tdr_series"]
    tdr_vol = {tid: series_volumes(t.get("series")) for tid, t in targets.items()}
    ice_vol = {gid: series_volumes(s.get("series")) for gid, s in subjects.items()}

    # who claims what (for the "shared target" columns)
    legacy_claims = defaultdict(list)
    for r in ext["crosswalk"]:
        if r["match_method"] != "ADMIN" and r["canonical_model_id"]:
            legacy_claims[r["canonical_model_id"]].append(r["model_group_id"])
    v1_claims = defaultdict(list)
    for gid, d in res["decisions"].items():
        for t in d.get("target_ids", []) or []:
            v1_claims[t].append(gid)

    pairs = []
    group_rows = {}
    for gid in sorted(groups):
        g, subj = groups[gid], subjects[gid]
        d = res["decisions"][gid]
        fp = res["first_pass"][gid]
        evals = {tuple(sorted(e["c"]["target_ids"])): e for e in fp["evals"]}
        lrep = legacy_rep[gid]
        lcands = {c["canonical_model_id"]: c for c in lrep["candidates"]}
        ice_series = ice["cells"].get(gid, {})
        chosen = lrep["chosen"]
        chosen_cid = chosen["canonical_model_id"] if chosen else None
        decision_targets = tuple(sorted(d.get("target_ids", []) or []))
        alt_keys = {tuple(sorted(a["target_ids"])) for a in d.get("alternatives", [])}
        lin = lineage_context(gid, snap["lineage"]["events"], res["operations"], redirect_keys)
        n_legacy_cands = sum(1 for c in lrep["candidates"] if c["decision"] is not None)
        proposable = [e for e in fp["evals"] if not e["excluded"] and (e["series_strong"] or e["lexical_ok"] or e["part_of"])]
        # several viable candidates: v1-proposable, or one the legacy rules scored as a strong series or a name >= the AUTO name threshold
        plausible = {tuple(sorted(e["c"]["target_ids"])) for e in proposable}
        for cid, c in lcands.items():
            if c["decision"] is not None and (c["strong"] or c["name_score"] >= L.X.NAME_AUTO_THRESHOLD):
                plausible.add((cid,))

        group_rows[gid] = {
            "model_group_id": gid, "ice_model_name": g["model_name"], "ice_brand": g["brand"], "ice_identity_status": subj["identity_status"],
            "ice_body": g["body"].strip(), "ice_segment": g["segment"].strip(),
            "ice_lifetime_units": ice_vol[gid]["lifetime"], "ice_units_last12m": ice_vol[gid]["recent12"], "ice_units_last24m": ice_vol[gid]["recent24"],
            "ice_first_month": ice_vol[gid]["first"], "ice_last_month": ice_vol[gid]["last"],
            "ice_months_with_rows": ice_vol[gid]["months_with_rows"], "ice_absent_in_coverage_months": ice_vol[gid]["absent_in_coverage"],
            "lineage_roles": joined(lin["roles"]), "lineage_events": joined(lin["events"], " | "), "lineage_ops": joined(lin["ops"]),
            "lineage_quarantined": lin["quarantined"], "lineage_redirect_recorded": lin["redirect_recorded"],
            "v1_group_outcome": d["outcome"], "v1_group_primary_code": d.get("primary") or "", "v1_group_proposed_status": d.get("proposed_status", "NONE"),
            "v1_group_link_type": d.get("link_type") or "", "v1_group_targets": joined(d.get("target_ids", []) or [], "+"),
            "v1_group_codes": joined(f"{c}:{r}" for c, r in d["codes"]),
            "v1_group_review_queue": d["review"]["queue"], "v1_pool_size": fp["pool_size"], "v1_proposable_candidates": len(proposable), "plausible_candidates": len(plausible),
            "v1_bundle_pool_size": "" if fp["bundle_pool_size"] is None else fp["bundle_pool_size"],
            "legacy_candidates_evaluated": len(lrep["candidates"]), "legacy_candidates_proposed": n_legacy_cands,
            "legacy_chosen": chosen_cid or "", "legacy_stored_rows": len(stored_by_group.get(gid, [])),
        }

        # --- which pairs to keep
        keep: dict[tuple, set] = {}
        def mark(key, origin):
            keep.setdefault(key, set()).add(origin)
        if chosen_cid:
            mark((chosen_cid,), "LEGACY_STORED")
        for r in stored_by_group.get(gid, []):
            if r["match_method"] == "ADMIN" and r["canonical_model_id"]:
                mark((r["canonical_model_id"],), "LEGACY_STORED")
        if decision_targets:
            mark(decision_targets, "V1_PRIMARY")
        for k in alt_keys:
            mark(k, "V1_ALTERNATIVE")
        for key, e in evals.items():
            n = e["c"]["evidence"]["name"] or {}
            s = e["c"]["evidence"]["series"] or {}
            ldec = lcands.get(key[0]) if len(key) == 1 else None
            if (n.get("relation") in RELATED_NAME_RELATIONS or s.get("state") == "STRONG" or (ldec is not None and ldec["decision"] is not None)
                    or e in proposable):
                mark(key, "V1_POOL")
        for cid, c in lcands.items():
            if c["decision"] is not None:
                mark((cid,), "LEGACY_CANDIDATE")

        for key, origins in sorted(keep.items()):
            members = [targets[t] for t in key]
            e = evals.get(key)
            standalone = False
            if e is None:
                # not in the v1 pool (for example a brand the legacy alias list joins but the v1 alias classes do not): evaluate it on its own
                cand = R.candidate_for(subj, members, snap, set(), [])
                cin = {"subject": {"entity_id": gid, "identity_status": subj["identity_status"], "name_available": True, "total_units": ice_vol[gid]["lifetime"],
                                   "multi_brand": False, "duplicate_display_name": False},
                       "quarantined": False, "brand_known": True, "brand_in_tdr": True, "pool_size": 1, "candidates": [cand],
                       "protected_targets": [], "stored_claims": "CONSISTENT"}
                single = P.classify(cin)
                e = single["_evals"][0]
                standalone = True
            ev = e["c"]["evidence"]
            b, n, s, a = ev["brand"] or {}, ev["name"] or {}, ev["series"] or {}, ev["attributes"] or {}
            cmpd = e["c"].get("_cmp") or {}
            excl_counts = Counter(x["reason"] for x in cmpd.get("excluded_periods", []))
            win = cmpd.get("common_window") or {}
            codes = candidate_codes(e, subj["identity_status"])
            single_cid = key[0] if len(key) == 1 else None
            lc = lcands.get(single_cid) if single_cid else None
            if lc is None and single_cid:
                lc = L.evaluate_pair(g, ice_series, single_cid, linputs)
            srow = stored.get((gid, single_cid)) if single_cid else None
            if len(key) > 1:
                # legacy never evaluated a set; show the legacy rule's series arithmetic on the summed target for comparison
                summed: dict[str, float] = defaultdict(float)
                for t in key:
                    for p, v in linputs["tdr_series"].get(t, {}).items():
                        summed[p] += v
                periods = sorted(ice_series)[-L.SERIES_WINDOW_MONTHS:]
                xs, ys = L.X.build_paired_series(periods, ice_series, summed)
                lev = L.X.evaluate_series(xs, ys)
                lc = {"correlation": lev.correlation, "ratio": lev.ratio, "strong": lev.strong, "name_score": None, "decision": None, "in_pool": False,
                      "window": {"first": A.b2g(periods[0]) if periods else None, "last": A.b2g(periods[-1]) if periods else None,
                             "periods": [A.b2g(p) for p in periods], "months": len(periods), "calendar_span": 0, "tdr_zero_filled": [A.b2g(p) for p in periods if p not in summed]}}
            ldec = lc["decision"]
            lclass = legacy_class(lc["correlation"], lc["ratio"], lc["strong"])
            why = material_change(lclass, lc["correlation"], lc["ratio"], s.get("state", "UNAVAILABLE"), s.get("correlation"), s.get("ratio"))
            tvol = sum_volumes([tdr_vol[t] for t in key])
            tseries = P.sum_series([targets[t].get("series") for t in key]) if len(key) > 1 else targets[key[0]].get("series")
            gap_both, gap_subj, gap_tgt = gap_breakdown(subj.get("series"), tseries)
            link = e["link"]
            is_primary = key == decision_targets and bool(decision_targets)
            rank = sorted(proposable, key=lambda x: (x["ser_rank"], x["name_rank"], "|".join(x["c"]["target_ids"]))).index(e) + 1 if e in proposable else ""
            pairs.append({
                **group_rows[gid],
                "candidate_canonical_model_id": "+".join(key), "candidate_target_count": len(key),
                "tdr_brand": joined(sorted({t["brand"] for t in members})), "tdr_model_name": " + ".join(t["display_name"] for t in members),
                "tdr_status": joined(sorted({t["status"] for t in members})), "tdr_body_type": joined(sorted({t["body_type"] or "" for t in members})),
                "candidate_origin": joined(sorted(origins)),
                # ---------------- legacy: what the first R6 run saw and stored
                "legacy_run_selected": bool(srow and srow["match_method"] != "ADMIN"),
                "legacy_row_id": srow["id"] if srow else "", "legacy_status": srow["status"] if srow else "", "legacy_match_method": srow["match_method"] if srow else "",
                "legacy_stored_score": srow["score"] if srow else "", "legacy_stored_reason": srow["reason"] if srow else "",
                "legacy_stored_fingerprint": srow["decision_fingerprint"] if srow else "", "legacy_stored_created_at": srow["created_at"] if srow else "",
                "legacy_in_candidate_pool": bool(lc.get("in_pool")) if len(key) == 1 else False,
                "legacy_would_decide": (f"{ldec.status}/{ldec.match_method}" if ldec else ""),
                "legacy_correlation": lc["correlation"], "legacy_ratio": lc["ratio"], "legacy_name_score": lc["name_score"],
                "legacy_series_class": lclass,
                "legacy_window_first": lc["window"]["first"], "legacy_window_last": lc["window"]["last"], "legacy_window_months": lc["window"]["months"],
                "legacy_window_calendar_span_months": lc["window"].get("calendar_span", ""),
                "legacy_window_periods": joined(lc["window"].get("periods", [])),
                "legacy_window_tdr_zero_filled_months": len(lc["window"]["tdr_zero_filled"]),
                "legacy_window_tdr_zero_filled_list": joined(lc["window"]["tdr_zero_filled"]),
                # ---------------- Contract v1: the same pair, recomputed
                "v1_link_candidate": link,
                "v1_brand_relation": b.get("relation", ""), "v1_name_relation": n.get("relation", ""), "v1_name_score": n.get("score"),
                "v1_name_subject_tokens": joined(n.get("subject_tokens", []), " "), "v1_name_target_tokens": joined(n.get("target_tokens", []), " "),
                "v1_series_state": s.get("state", ""), "v1_series_unavailable_reason": s.get("unavailable_reason") or "",
                "v1_correlation": s.get("correlation"), "v1_ratio": s.get("ratio"), "v1_monthly_fit_share": s.get("monthly_fit_share"),
                "v1_common_months": s.get("common_months"), "v1_joint_nonzero_months": s.get("joint_nonzero_months"),
                "v1_subject_units": s.get("subject_units"), "v1_target_units": s.get("target_units"),
                "v1_window_first": win.get("from", ""), "v1_window_last": win.get("to", ""), "v1_window_periods": joined(cmpd.get("periods", [])),
                "v1_semantics_gap_months": s.get("semantics_gap_months"),
                "v1_gap_months_both_absent": gap_both, "v1_gap_months_subject_only_absent": gap_subj, "v1_gap_months_target_only_absent": gap_tgt,
                "v1_excluded_unobserved_subject": excl_counts.get("unconfirmed_absent_row_in_subject", 0) + excl_counts.get("unobserved_in_subject", 0),
                "v1_excluded_unobserved_target": excl_counts.get("unconfirmed_absent_row_in_target", 0) + excl_counts.get("unobserved_in_target", 0),
                "v1_excluded_outside_common_coverage": excl_counts.get("outside_common_coverage", 0),
                "v1_excluded_inactive_edges": excl_counts.get("leading_inactive", 0) + excl_counts.get("trailing_inactive", 0),
                "v1_excluded_outside_max_window": excl_counts.get("outside_max_window", 0),
                "v1_lifecycle": a.get("lifecycle", ""), "v1_lifecycle_share": a.get("lifecycle_share"), "v1_body_relation": a.get("body", ""),
                "v1_target_status": a.get("target_status", ""),
                "v1_auto_eligible": bool(e["auto_ok"]), "v1_proposable": e in proposable, "v1_rank_among_proposable": rank,
                "v1_is_group_primary": is_primary, "v1_is_group_alternative": key in alt_keys,
                "v1_evaluated_standalone": standalone,
                "v1_codes_supporting": joined(codes["supporting"]), "v1_codes_blocking": joined(codes["blocking"]),
                "v1_codes_excluded": joined(codes["excluded"]), "v1_codes_info": joined(codes["info"]),
                # ---------------- how the two windows compare
                "series_material_change": bool(why), "series_material_change_why": joined(why),
                "delta_correlation_v1_minus_legacy": (None if lc["correlation"] is None or s.get("correlation") is None else s["correlation"] - lc["correlation"]),
                # ---------------- volumes (for prioritisation only, never evidence)
                "tdr_lifetime_units": tvol["lifetime"], "tdr_units_last12m": tvol["recent12"], "tdr_units_last24m": tvol["recent24"],
                "tdr_first_month": min((tdr_vol[t]["first"] for t in key if tdr_vol[t]["first"]), default=""),
                "tdr_last_month": max((tdr_vol[t]["last"] for t in key if tdr_vol[t]["last"]), default=""),
                # ---------------- sharing
                "legacy_groups_claiming_this_target": joined(sorted(legacy_claims.get(single_cid, []))) if single_cid else "",
                "v1_groups_claiming_this_target": joined(sorted(set(sum((v1_claims.get(t, []) for t in key), [])))),
            })
    return {"snapshot": snap, "resolution": res, "legacy": legacy_rep, "verification": verification, "pairs": pairs,
            "groups": group_rows, "ice_vol": ice_vol, "tdr_vol": tdr_vol}
