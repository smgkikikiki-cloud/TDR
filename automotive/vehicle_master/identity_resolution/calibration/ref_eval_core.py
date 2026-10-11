"""REFERENCE EVALUATOR (core) of the Identity Resolution v1 SPEC, for calibration only. It is NOT the engine.

What it is: a stdlib-only, no-I/O transcription of SPEC sections 5-9 (brand/name relations, the common-window series evidence,
the per-subject decision procedure, lineage). It reads the committed policy, so a run under it is a dry run (adoption.yaml
says binding: false, invariant I16). It exists so that the calibration dataset can state what Contract v1 *would* say about real
data, and so that anyone can reproduce those statements.

What it is not: there is no persistence, no adapter, no CLI and no production wiring; nothing outside the identity_resolution
package imports it (a test enforces that), and the engine gate (README section 5) is unchanged. It shares an author with the SPEC, so
agreement with the golden corpus (tests/identity_resolution/test_ir_reference_evaluator.py) proves consistency, not correctness.
"""
from __future__ import annotations
import hashlib, json, math, re, unicodedata
from decimal import Decimal, ROUND_HALF_EVEN
from itertools import combinations

from identity_resolution.contract import loader

POL = loader.load_policy()
REG = loader.load_reason_codes()["codes"]

# ----------------------------------------------------------------------------- quantize / bands
def q(x, places=None):
    places = POL["quantization"]["places"] if places is None else places
    if x is None:
        return None
    return float(Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-places), ROUND_HALF_EVEN))

def qstr(x, places=None):
    places = POL["quantization"]["places"] if places is None else places
    return format(Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-places), ROUND_HALF_EVEN), "f")

def band(dim, value):
    edges = POL["fingerprint"]["bands"][dim]
    v = q(value) if dim != "common_months" else value
    labels = [f"<{edges[0]}"]
    for a, b in zip(edges, edges[1:]):
        labels.append(f"[{a},{b})")
    labels.append(f">={edges[-1]}")
    idx = sum(1 for e in edges if v >= e)
    return labels[idx]

# ----------------------------------------------------------------------------- brand
_THAI = "฀-๿"
def compact(s):
    s = unicodedata.normalize("NFKC", s or "").casefold()
    return re.sub(rf"[^a-z0-9{_THAI}]", "", s)

BRAND_CLASS = {}      # compact key -> (class id, relation)
RELATED = []          # list of (alias id, set(class ids/keys))
for a in POL["aliases"]["brand"]:
    if a["relation"] in ("SAME", "RELABEL"):
        for m in a["members"]:
            k = compact(m)
            assert k not in BRAND_CLASS, k
            BRAND_CLASS[k] = (a["id"], a["relation"])
def _cls(key):
    return "class:" + BRAND_CLASS[key][0] if key in BRAND_CLASS else key
for a in POL["aliases"]["brand"]:
    if a["relation"] == "RELATED":
        RELATED.append((a["id"], {_cls(compact(m)) for m in a["members"]}))

_RANK = {"EXACT": 0, "ALIAS_SAME": 1, "ALIAS_RELABEL": 2, "ALIAS_RELATED": 3, "MISMATCH": 4}
def _rel1(sb, tb):
    s, t = compact(sb), compact(tb)
    if not s or not t or s in {compact(x) for x in POL["lexical"]["unavailable_name_values"] if x}:
        return ("UNKNOWN", None)
    if s == t:
        return ("EXACT", None)
    cs, ct = _cls(s), _cls(t)
    if cs == ct and cs.startswith("class:"):
        cid = cs[6:]
        rel = next(v[1] for v in BRAND_CLASS.values() if v[0] == cid)
        return ("ALIAS_SAME" if rel == "SAME" else "ALIAS_RELABEL", cid)
    for aid, members in RELATED:
        if cs in members and ct in members:
            return ("ALIAS_RELATED", aid)
    return ("MISMATCH", None)

def brand_relation(subject_brand, target_brand, observed=()):
    best = None
    for sb in [subject_brand, *observed]:
        r = _rel1(sb, target_brand)
        if r[0] == "UNKNOWN":
            continue
        if best is None or _RANK[r[0]] < _RANK[best[0]]:
            best = r
    if best is None:
        return ("UNKNOWN", None)
    return best

# ----------------------------------------------------------------------------- names
def _tokens_raw(s):
    s = unicodedata.normalize("NFKC", s or "").casefold()
    bound = POL["lexical"]["token_boundary_characters"]
    s = "".join(" " if (ch in bound or ch.isspace()) else ch for ch in s)
    s = re.sub(rf"[^a-z0-9{_THAI} ]", "", s)
    return s.split()

def brand_spellings(*brands):
    out = []
    for brand in brands:
        k = compact(brand)
        out.append(brand)
        if k in BRAND_CLASS:
            cid = BRAND_CLASS[k][0]
            for a in POL["aliases"]["brand"]:
                if a["id"] == cid:
                    out += a["members"]
    return [_tokens_raw(x) for x in out if _tokens_raw(x)]

def name_tokens(name, brand, extra=()):
    toks = _tokens_raw(name)
    stripped = False
    for sp in sorted(brand_spellings(brand, *extra), key=len, reverse=True):
        if len(toks) > len(sp) and toks[:len(sp)] == sp:
            toks = toks[len(sp):]
            stripped = True
            break
    toks = [t for t in toks if t not in POL["lexical"]["generic_tokens"]]
    unavailable = {compact(x) for x in POL["lexical"]["unavailable_name_values"]}
    available = bool(toks) and compact(" ".join(toks)) not in unavailable and compact(name) not in unavailable
    return toks, stripped, available

def _equiv_rep(t):
    for grp in POL["lexical"]["token_equivalences"]:
        if t in grp:
            return grp[0]
    return t

def _lev1(a, b):
    if abs(len(a) - len(b)) > 1:
        return False
    if a == b:
        return True
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return a[i + 1:] == b[i + 1:] or a[i:] == b[i + 1:] or a[i + 1:] == b[i:]

def name_relation(sname, sbrand, tname, tbrand, observed=()):
    st, _, sav = name_tokens(sname, sbrand, extra=(tbrand, *observed))
    tt, _, tav = name_tokens(tname, tbrand, extra=(sbrand, *observed))
    if not sav or not tav:
        return "UNAVAILABLE", None, st, tt
    if "".join(st) == "".join(tt):
        return "EQUAL", 1.0, st, tt
    brel, aid = brand_relation(sbrand, tbrand, observed)
    for m in POL["aliases"]["model"]:
        if aid in m["brand_alias_ids"]:
            for a, b in m["pairs"]:
                at, bt = _tokens_raw(a), _tokens_raw(b)
                if ("".join(st) == "".join(at) and "".join(tt) == "".join(bt)) or \
                   ("".join(st) == "".join(bt) and "".join(tt) == "".join(at)):
                    return "EQUAL_VIA_MODEL_ALIAS", 1.0, st, tt
    sr, tr = [_equiv_rep(t) for t in st], [_equiv_rep(t) for t in tt]
    if "".join(sr) == "".join(tr) or set(sr) == set(tr):
        return "EQUAL_VIA_TOKEN_EQUIV", 1.0, st, tt
    SA, SB = set(sr), set(tr)
    fz = POL["lexical"]["fuzzy_token"]
    only_a, only_b = SA - SB, SB - SA
    matched = 0
    if fz["enabled"]:
        pairs = [(a, b) for a in sorted(only_a) for b in sorted(only_b)
                 if len(a) >= fz["min_token_length"] and len(b) >= fz["min_token_length"] and _lev1(a, b)]
        used_a, used_b = set(), set()
        for a, b in pairs:
            if a not in used_a and b not in used_b:
                used_a.add(a); used_b.add(b); matched += 1
        if matched and len(used_a) == len(only_a) and len(used_b) == len(only_b):
            return "FUZZY", 1.0, st, tt
    inter = len(SA & SB) + matched
    dice = 2 * inter / (len(SA) + len(SB))
    if SA < SB:
        return "SUBJECT_COARSER", dice, st, tt
    if SA > SB:
        return "SUBJECT_FINER", dice, st, tt
    if SA & SB:
        return "SIBLING", dice, st, tt
    return "CONTRADICTION", dice, st, tt

# ----------------------------------------------------------------------------- series
def pidx(p):
    y, m = p.split("-")
    return int(y) * 12 + int(m) - 1
def pstr(i):
    return f"{i // 12:04d}-{i % 12 + 1:02d}"

def _unconf(s):
    b = (s or {}).get("absent_rows")
    return set() if (not b or b["confirmed"]) else {pidx(m) for m in b["months"]}

def _ref(s):
    b = (s or {}).get("absent_rows")
    return None if not b else {"source": b["source"], "semantics": b["semantics"], "confirmed": b["confirmed"]}

def series_evidence(S, T, max_months=None):
    P = POL["series"]
    max_months = max_months or P["window"]["max_months"]
    cmp_ = {"requested_max_months": max_months, "subject_coverage": None, "target_coverage": None,
            "common_window": None, "periods": [], "excluded_periods": [], "engine_zero_filled_periods": [],
            "absent_rows": {"subject": _ref(S), "target": _ref(T), "unconfirmed_gap_months": 0}}
    codes = []
    ev = {"state": "UNAVAILABLE", "correlation": None, "ratio": None, "monthly_fit_share": None,
          "common_months": 0, "joint_nonzero_months": 0, "subject_units": 0, "target_units": 0, "semantics_gap_months": 0, "_reason": None}
    def unavail(code):
        ev["_reason"] = code
        codes.append(code)
        return ev, cmp_, codes
    if S is None or T is None:
        return unavail("SER_NO_COMMON_WINDOW")
    if not S.get("coverage_declared", True) or not T.get("coverage_declared", True):
        return unavail("SER_COVERAGE_UNDECLARED")
    def span(s):
        a = pidx(s["start"]); return a, a + len(s["counts"]) - 1
    sa, sb = span(S); ta, tb = span(T)
    cmp_["subject_coverage"] = {"from": pstr(sa), "to": pstr(sb)}
    cmp_["target_coverage"] = {"from": pstr(ta), "to": pstr(tb)}
    if (sa, sb) != (ta, tb):
        codes.append("SER_COVERAGE_ASYMMETRIC")
    partial = ({pidx(p) for p in S.get("partial_periods", [])} | {pidx(p) for p in T.get("partial_periods", [])}) if P["window"]["exclude_partial_periods"] else set()
    obsS = {sa + i: c for i, c in enumerate(S["counts"]) if c is not None}
    obsT = {ta + i: c for i, c in enumerate(T["counts"]) if c is not None}
    both = set(range(max(sa, ta), min(sb, tb) + 1))
    US, UT = _unconf(S), _unconf(T)
    excl = []
    nulls = False
    for i in sorted(set(range(sa, sb + 1)) | set(range(ta, tb + 1))):
        if i in partial and (i in obsS or i in obsT):
            excl.append((i, "partial_period"))
        elif i not in both:
            excl.append((i, "outside_common_coverage"))
        elif i not in obsS:
            excl.append((i, "unconfirmed_absent_row_in_subject" if i in US else "unobserved_in_subject")); nulls = True
        elif i not in obsT:
            excl.append((i, "unconfirmed_absent_row_in_target" if i in UT else "unobserved_in_target")); nulls = True
    if any(r == "partial_period" for _, r in excl):
        codes.append("SER_PARTIAL_PERIOD_EXCLUDED")
    if nulls:
        codes.append("SER_UNOBSERVED_NOT_ZERO")
    if both:
        end = max(both)
        gap = sum(1 for i in both if i > end - max_months and i not in partial and (i in US or i in UT))
        ev["semantics_gap_months"] = gap
        cmp_["absent_rows"]["unconfirmed_gap_months"] = gap
        if gap > 0:
            codes.append("SER_MISSING_ROW_SEMANTICS_UNCONFIRMED")
    C = sorted(i for i in both if i in obsS and i in obsT and i not in partial)
    if not C:
        cmp_["excluded_periods"] = [{"period": pstr(i), "reason": r} for i, r in excl]
        return unavail("SER_NO_COMMON_WINDOW")
    lo, hi = 0, len(C)
    if P["window"]["trim_inactive_edges"]:
        while lo < hi and obsS[C[lo]] == 0 and obsT[C[lo]] == 0:
            excl.append((C[lo], "leading_inactive")); lo += 1
        while hi > lo and obsS[C[hi - 1]] == 0 and obsT[C[hi - 1]] == 0:
            excl.append((C[hi - 1], "trailing_inactive")); hi -= 1
        if lo > 0 or hi < len(C):
            codes.append("SER_WINDOW_TRIMMED_INACTIVE")
    Ct = C[lo:hi]
    if not Ct:
        cmp_["excluded_periods"] = [{"period": pstr(i), "reason": r} for i, r in sorted(excl)]
        return unavail("SER_ZERO_TOTAL")
    anchor = Ct[-1]
    Pn = [i for i in Ct if i > anchor - max_months]
    for i in Ct:
        if i not in Pn:
            excl.append((i, "outside_max_window"))
    cmp_["periods"] = [pstr(i) for i in Pn]
    cmp_["excluded_periods"] = [{"period": pstr(i), "reason": r} for i, r in sorted(excl)]
    cmp_["common_window"] = {"from": pstr(Pn[0]), "to": pstr(Pn[-1]), "months": len(Pn)}
    xs = [float(obsS[i]) for i in Pn]; ys = [float(obsT[i]) for i in Pn]
    n = len(Pn)
    ev.update(common_months=n, joint_nonzero_months=sum(1 for x, y in zip(xs, ys) if x > 0 and y > 0),
              subject_units=sum(xs), target_units=sum(ys))
    mn = P["minimums"]["propose"]
    if ev["subject_units"] == 0:
        return unavail("SER_ZERO_TOTAL")
    if n < mn["common_months"] or ev["joint_nonzero_months"] < mn["joint_nonzero_months"]:
        return unavail("SER_OVERLAP_BELOW_PROPOSE_MIN")
    if ev["subject_units"] < mn["units_each_side"] or ev["target_units"] < mn["units_each_side"]:
        return unavail("SER_VOLUME_BELOW_PROPOSE_MIN")
    mx, my = sum(xs) / n, sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs); vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return unavail("SER_ZERO_VARIANCE")
    corr = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(vx * vy)
    ratio = sum(ys) / sum(xs)
    f = P["monthly_fit"]
    fit = sum(1 for x, y in zip(xs, ys) if abs(y - x) <= max(f["abs_tolerance_units"], f["rel_tolerance"] * x)) / n
    corr_q, ratio_q, fit_q = q(corr), q(ratio), q(fit)
    ev.update(correlation=corr_q, ratio=ratio_q, monthly_fit_share=fit_q)
    st = P["strong"]
    c_ok = corr_q >= st["correlation_min"]
    r_ok = st["ratio_min"] <= ratio_q <= st["ratio_max"]
    f_ok = fit_q >= f["min_share_of_months"]
    if not c_ok: codes.append("SER_CORRELATION_BELOW_STRONG")
    if not r_ok: codes.append("SER_RATIO_OUT_OF_BAND")
    if c_ok and r_ok and not f_ok: codes.append("SER_MONTHLY_FIT_FAIL")
    ev["state"] = "STRONG" if (c_ok and r_ok and f_ok) else "WEAK"
    if ev["state"] == "STRONG":
        codes.append("SER_STRONG")
    am = P["minimums"]["auto"]
    if n < am["common_months"] or ev["joint_nonzero_months"] < am["joint_nonzero_months"]:
        codes.append("SER_OVERLAP_BELOW_AUTO_MIN")
    if ev["subject_units"] < am["units_each_side"] or ev["target_units"] < am["units_each_side"]:
        codes.append("SER_VOLUME_BELOW_AUTO_MIN")
    return ev, cmp_, codes

def sum_series(list_of_series):
    """Sum several target series over their common coverage (all must be declared)."""
    if any(s is None for s in list_of_series):
        return None
    if not all(s.get("coverage_declared", True) for s in list_of_series):
        return {"start": list_of_series[0]["start"], "counts": [None], "coverage_declared": False}
    lo = max(pidx(s["start"]) for s in list_of_series)
    hi = min(pidx(s["start"]) + len(s["counts"]) - 1 for s in list_of_series)
    if hi < lo:
        return None
    counts = []
    part = set()
    for s in list_of_series:
        part |= {pidx(p) for p in s.get("partial_periods", [])}
    for i in range(lo, hi + 1):
        vals = [s["counts"][i - pidx(s["start"])] for s in list_of_series]
        counts.append(None if any(v is None for v in vals) else sum(vals))
    out = {"start": pstr(lo), "counts": counts, "partial_periods": [pstr(i) for i in sorted(part)],
           "coverage_declared": True}
    blocks = [s["absent_rows"] for s in list_of_series if s.get("absent_rows")]
    if blocks:
        out["absent_rows"] = {"source": blocks[0]["source"], "semantics": blocks[0]["semantics"],
                              "confirmed": all(b["confirmed"] for b in blocks),
                              "months": sorted({m for b in blocks for m in b["months"]})}
    return out

# ----------------------------------------------------------------------------- classification
def role_for(code, preferred):
    roles = REG[code]["roles"]
    if preferred in roles:
        return preferred
    return next(r for r in roles if r != "primary")

GAP_CODE = "SER_MISSING_ROW_SEMANTICS_UNCONFIRMED"
GAP_LIMIT = POL["series"]["absent_row"]["auto_max_unconfirmed_gap_months"]

def series_role(code, preferred, sv):
    """The gap code is blocking exactly when the gap exceeds the policy limit (SPEC §6.2a); every other code keeps its preferred role."""
    if code == GAP_CODE:
        return "blocking" if (sv or {}).get("semantics_gap_months", 0) > GAP_LIMIT else "info"
    return role_for(code, preferred)

def series_codes_from_tuple(sv):
    out = []
    if sv is None:
        return out
    st = POL["series"]["strong"]
    if sv.get("semantics_gap_months", 0) > 0:
        out.append(GAP_CODE)
    if sv["state"] == "UNAVAILABLE" and sv.get("unavailable_reason"):
        out.append(sv["unavailable_reason"])
    if sv["state"] == "WEAK":
        c_ok = sv["correlation"] >= st["correlation_min"]
        r_ok = st["ratio_min"] <= sv["ratio"] <= st["ratio_max"]
        if not c_ok: out.append("SER_CORRELATION_BELOW_STRONG")
        if not r_ok: out.append("SER_RATIO_OUT_OF_BAND")
        if c_ok and r_ok and sv["monthly_fit_share"] < POL["series"]["monthly_fit"]["min_share_of_months"]:
            out.append("SER_MONTHLY_FIT_FAIL")
    return out

NAME_AUTO = POL["lexical"]["name"]["auto_relations"]
NAME_CAND = POL["lexical"]["name"]["candidate_relations"]
NAME_VETO = POL["lexical"]["name"]["veto_relations"]
NAME_ORDER = POL["candidates"]["ranking"]["name_relation_order"]
LIFE_ORDER = POL["candidates"]["ranking"]["lifecycle_order"]
SER_ORDER = POL["candidates"]["ranking"]["series_state_order"]

def meets_auto_min(s):
    am = POL["series"]["minimums"]["auto"]
    return (s["common_months"] >= am["common_months"] and s["joint_nonzero_months"] >= am["joint_nonzero_months"]
            and s["subject_units"] >= am["units_each_side"] and s["target_units"] >= am["units_each_side"])

def matrix_action(state, decision, fp):
    row = POL["state"]["write_matrix"][state][decision]
    if isinstance(row, dict):
        return row["fingerprint_unchanged" if fp == "unchanged" else "fingerprint_changed"]
    return row

def is_part_of(ev):
    """granularity.part_of single-subject rule (SPEC §7.4): a narrower subject name, a usable series and a clearly bigger target."""
    n = ev["name"] or {"relation": "UNAVAILABLE"}
    s = ev["series"] or {"state": "UNAVAILABLE"}
    cfg = POL["granularity"]["part_of"]
    return (n["relation"] in cfg["subject_name_relations"] and s["state"] != "UNAVAILABLE"
            and s.get("ratio") is not None and s["ratio"] > cfg["min_ratio_above"])

def claim_link_type(c):
    if c.get("link_type") == "COMPOSED_OF":
        return "COMPOSED_OF"
    return "PART_OF" if is_part_of(c["evidence"]) else "EQUIVALENT"

def _wr(tid, action, link, set_id=None):
    return {"target_id": tid, "action": action, "link_type": link, "set_id": set_id}

def _classify(inp):
    subj = inp["subject"]
    codes = []        # (code, role)
    def add(c, role):
        if (c, role) not in codes: codes.append((c, role))
    out = {"alternatives": [], "writes": [], "review": {"required": False, "queue": "none", "priority": "normal", "question": None},
           "target_ids": [], "method": "NONE", "proposed_status": "NONE", "evidence": None, "link_type": None, "set_id": None}
    st = subj["identity_status"]
    sflags = []
    if st == "provisional": sflags.append("SUBJ_PROVISIONAL")
    if st == "unmapped_name": sflags.append("SUBJ_UNMAPPED_NAME")
    if not subj["name_available"]: add("SUBJ_UNSPECIFIED_NAME", "info")
    if subj.get("duplicate_display_name"): add("SUBJ_DUPLICATE_DISPLAY_NAME", "info")
    if subj.get("multi_brand"): add("SUBJ_MULTI_BRAND", "info")

    # ---------------------------------------------------------------- step 0: stored claims must be readable (SPEC §8.2)
    if inp.get("stored_claims") == "INCONSISTENT":
        out["outcome"] = "STRUCTURAL_REVIEW"
        out["primary"] = "STRUCTURAL_STORED_CLAIMS_INCONSISTENT"
        add(out["primary"], "primary")
        out["review"] = {"required": True, "queue": "structure_review", "priority": "normal", "question": None}
        out["codes"] = codes
        return out

    prot = inp.get("protected_targets", [])
    cands = inp["candidates"]
    gap_limit = POL["series"]["absent_row"]["auto_max_unconfirmed_gap_months"]

    def evaluate(c):
        ev = c["evidence"]
        b = ev["brand"] or {"relation": "EXACT"}
        n = ev["name"] or {"relation": "UNAVAILABLE", "score": None}
        s = ev["series"] or {"state": "UNAVAILABLE"}
        a = ev["attributes"] or {"body": "UNKNOWN", "lifecycle": "UNKNOWN", "target_status": "CURRENT"}
        d = {"c": c, "codes": [], "excluded": [], "block": []}
        # exclusions (affirmative)
        if n["relation"] in NAME_VETO and not (POL["lexical"]["series_only"]["allow_with_name_veto"] and s["state"] == "STRONG"):
            d["excluded"].append("NAME_SIBLING_VARIANT" if n["relation"] == "SIBLING" else "NAME_CONTRADICTION")
        if a["lifecycle"] == "DISJOINT": d["excluded"].append("GEN_LIFECYCLE_DISJOINT")
        if c.get("bundle_overshoot"): d["excluded"].append("SER_BUNDLE_OVERSHOOT")
        held = c.get("held_elsewhere", "NONE")
        d["series_strong"] = s["state"] == "STRONG"
        d["lexical_ok"] = n["relation"] in NAME_CAND
        d["link"] = claim_link_type(c)
        d["part_of"] = d["link"] == "PART_OF"
        wrong = POL["data_sufficiency"]["series_decisively_wrong"]
        d["decisively_wrong"] = (s["state"] == "WEAK" and not d["lexical_ok"] and
                                 ((s["correlation"] is not None and s["correlation"] < wrong["correlation_below"]) or
                                  (s["ratio"] is not None and not (wrong["ratio_outside"][0] <= s["ratio"] <= wrong["ratio_outside"][1]))))
        if d["decisively_wrong"] and not d["part_of"]: d["excluded"].append("SERIES_DECISIVELY_WRONG")
        d["held"] = held
        d["name_rank"] = NAME_ORDER.index(n["relation"]) if n["relation"] in NAME_ORDER else 99
        d["life_rank"] = LIFE_ORDER.index(a["lifecycle"]) if a["lifecycle"] in LIFE_ORDER else 99
        d["ser_rank"] = SER_ORDER.index(s["state"])
        # blocking codes for AUTO
        blk = []
        if b["relation"] == "ALIAS_RELATED" and b["relation"] not in POL["candidates"]["brand_relations_auto_eligible"]: blk.append("BRND_ALIAS_RELATED")
        if n["relation"] == "FUZZY": blk.append("NAME_FUZZY_TOKEN")
        if n["relation"] == "SUBJECT_COARSER": blk.append("NAME_CONTAINMENT_SUBJECT_COARSER")
        if n["relation"] == "SUBJECT_FINER": blk.append("NAME_CONTAINMENT_SUBJECT_FINER")
        if not d["series_strong"] and not d["part_of"]: blk.append("NAME_ONLY_NOT_AUTO")
        if n["relation"] == "UNAVAILABLE" and d["series_strong"]: blk.append("NAME_UNAVAILABLE")
        if s["state"] != "UNAVAILABLE":
            if s["state"] == "STRONG" and not meets_auto_min(s):
                am = POL["series"]["minimums"]["auto"]
                if s["common_months"] < am["common_months"] or s["joint_nonzero_months"] < am["joint_nonzero_months"]:
                    blk.append("SER_OVERLAP_BELOW_AUTO_MIN")
                if s["subject_units"] < am["units_each_side"] or s["target_units"] < am["units_each_side"]:
                    blk.append("SER_VOLUME_BELOW_AUTO_MIN")
        if s.get("semantics_gap_months", 0) > gap_limit: blk.append(GAP_CODE)
        if a["body"] == "MISMATCH": blk.append("ATTR_BODY_MISMATCH")
        if a["lifecycle"] == "PARTIAL": blk.append("GEN_LIFECYCLE_PARTIAL")
        if a["target_status"] in POL["attributes"]["target_status"]["cap_proposed"]: blk.append("ATTR_TARGET_UNVERIFIED")
        if st == "provisional" and st in POL["subject_quality"]["never_auto_identity_statuses"]: blk.append("SUBJ_PROVISIONAL")
        if st == "unmapped_name" and st in POL["subject_quality"]["never_auto_identity_statuses"]: blk.append("SUBJ_UNMAPPED_NAME")
        if inp.get("quarantined"): blk.append("LIN_EVIDENCE_QUARANTINE")
        if c.get("extends_protected"): blk.append("CARD_EXTENDS_PROTECTED")
        if c.get("link_type_conflicts_protected"): blk.append("CARD_LINK_TYPE_CONFLICTS_PROTECTED")
        if c.get("pair_state") == "REJECTED": blk.append("STATE_REJECTED_REOPENED")
        d["block"] = blk
        auto_ok = (b["relation"] in POL["candidates"]["brand_relations_auto_eligible"] and d["series_strong"]
                   and n["relation"] in NAME_AUTO and d["link"] == "EQUIVALENT"
                   and not [x for x in blk if x != "NAME_ONLY_NOT_AUTO" or not d["series_strong"]])
        d["auto_ok"] = bool(auto_ok)
        return d

    evals = [evaluate(c) for c in cands]
    out["_evals"] = evals   # per-candidate flags, kept for the calibration dataset (not part of the decision record)

    # ---------------------------------------------------------------- protected subject
    if prot:
        locked = any(p["state"] == "LOCKED" for p in prot)
        out["outcome"] = "PROTECTED_HOLD"
        out["primary"] = "PROTECTED_HOLD_LOCKED" if locked else "PROTECTED_HOLD_APPROVED"
        add(out["primary"], "primary"); add("AUTH_HUMAN_OVER_ENGINE", "info")
        agree = {p["agrees"] for p in prot}
        missing = any(p.get("target_exists", True) is False for p in prot)
        if "CONTRADICTS" in agree: add("STATE_EVIDENCE_CONTRADICTS", "info")
        elif agree == {"CONFIRMS"}: add("STATE_EVIDENCE_CONFIRMS", "supporting")
        if missing: add("CARD_TARGET_MISSING", "blocking")
        if "CONTRADICTS" in agree or missing:
            out["review"] = {"required": True, "queue": "structure_review", "priority": "normal", "question": None}
        for e in evals:
            c = e["c"]
            if (c.get("extends_protected") or c.get("link_type_conflicts_protected")) and not e["excluded"] and (e["series_strong"] or e["lexical_ok"] or e["part_of"]):
                out["alternatives"].append({"target_ids": c["target_ids"], "candidate_status": "PROPOSED", "link_type": e["link"]})
                if c.get("link_type_conflicts_protected"):
                    add("CARD_LINK_TYPE_CONFLICTS_PROTECTED", "blocking")
                    out["review"] = {"required": True, "queue": "structure_review", "priority": "normal", "question": None}
                else:
                    add("CARD_EXTENDS_PROTECTED", "blocking")
                for tid in c["target_ids"]:
                    out["writes"].append(_wr(tid, matrix_action(c.get("pair_state", "NONE"), "PROPOSE", "not_applicable"), e["link"], c.get("set_id")))
        out["codes"] = codes
        return out

    # ---------------------------------------------------------------- no candidates at all
    if not cands:
        out["outcome"] = "NO_CANDIDATE"
        if not inp["brand_known"]: out["primary"] = "BRND_UNKNOWN"
        elif not inp["brand_in_tdr"]: out["primary"] = "BRND_NOT_IN_TDR"
        elif inp["pool_size"] == 0: out["primary"] = "NO_CANDIDATE_EMPTY_POOL"
        else: out["primary"] = "NO_CANDIDATE_ALL_EXCLUDED"
        add(out["primary"], "primary")
        _discovery(inp, out, add, sflags)
        out["codes"] = codes
        return out

    # ---------------------------------------------------------------- claim conflict / suppression
    def claim_conflict(e):
        ev = e["c"]["evidence"]
        b = ev["brand"] or {"relation": "EXACT"}
        n = ev["name"] or {"relation": "UNAVAILABLE", "score": None}
        return (e["held"] == "PROTECTED" and e["series_strong"] and n["relation"] in NAME_AUTO
                and b["relation"] in POL["candidates"]["brand_relations_auto_eligible"] and not e["excluded"])
    live = []
    suppressed = []
    conflicts = [e for e in evals if claim_conflict(e)]
    for e in evals:
        if e["held"] == "PROTECTED":
            e["excluded"].append("CARD_TARGET_ACTIVE_ELSEWHERE")
        if e["c"].get("pair_state") == "REJECTED" and e["c"].get("rejected_fingerprint_unchanged"):
            suppressed.append(e); continue
        live.append(e)
    proposable = [e for e in live if not e["excluded"] and (e["series_strong"] or e["lexical_ok"] or e["part_of"])]
    if not proposable:
        if conflicts:
            out["outcome"] = "STRUCTURAL_REVIEW"; out["primary"] = "STRUCTURAL_APPROVED_CLAIM_CONFLICT"
            add(out["primary"], "primary"); add("CARD_TARGET_ACTIVE_ELSEWHERE", "info")
            out["review"] = {"required": True, "queue": "structure_review", "priority": "normal", "question": None}
            out["codes"] = codes
            return out
        if suppressed and not [e for e in live if not e["excluded"]]:
            out["outcome"] = "SUPPRESSED"; out["primary"] = "SUPPRESSED_REJECTED_UNCHANGED"
            add(out["primary"], "primary")
            out["codes"] = codes
            return out
        survivors = [e for e in live if not e["excluded"]]
        if survivors:
            out["outcome"] = "INSUFFICIENT_DATA"; out["primary"] = "INSUFFICIENT_DATA_NO_BASIS"
            survivors.sort(key=lambda e: (e["ser_rank"], e["name_rank"], "|".join(e["c"]["target_ids"])))
            for x in series_codes_from_tuple(survivors[0]["c"]["evidence"]["series"]):
                add(x, series_role(x, "info", survivors[0]["c"]["evidence"]["series"]))
        else:
            out["outcome"] = "NO_CANDIDATE"; out["primary"] = "NO_CANDIDATE_ALL_EXCLUDED"
            for e in live:
                for x in e["excluded"]:
                    if x in REG: add(x, role_for(x, "info"))
                if "SERIES_DECISIVELY_WRONG" in e["excluded"]:
                    for x in series_codes_from_tuple(e["c"]["evidence"]["series"]):
                        add(x, series_role(x, "blocking", e["c"]["evidence"]["series"]))
        add(out["primary"], "primary")
        for sflag in sflags: add(sflag, "info")
        _discovery(inp, out, add, sflags)
        out["codes"] = codes
        return out

    # ---------------------------------------------------------------- rank + margin
    import math as _m
    def key(e):
        s = e["c"]["evidence"]["series"] or {}
        parts = {"auto_eligible": not e["auto_ok"], "series_state": e["ser_rank"], "lifecycle_relation": e["life_rank"], "name_relation": e["name_rank"],
                 "abs_ln_ratio_ascending": abs(_m.log(s["ratio"])) if s.get("ratio") else 99,
                 "correlation_descending": -(s.get("correlation") if s.get("correlation") is not None else -2)}
        return tuple(parts[t] for t in POL["candidates"]["ranking"]["tier_order"]) + ("|".join(e["c"]["target_ids"]),)
    proposable.sort(key=key)
    best = proposable[0]
    ties = [best]
    for e in proposable[1:]:
        if (e["auto_ok"], e["ser_rank"], e["life_rank"], e["name_rank"]) != (best["auto_ok"], best["ser_rank"], best["life_rank"], best["name_rank"]):
            continue
        sb = best["c"]["evidence"]["series"] or {}; se = e["c"]["evidence"]["series"] or {}
        if sb.get("correlation") is not None and se.get("correlation") is not None:
            mg = POL["candidates"]["margin"]
            dc = abs(sb["correlation"] - se["correlation"])
            dr = abs(abs(_m.log(sb["ratio"])) - abs(_m.log(se["ratio"])))
            if dc < mg["correlation_delta_min"] and dr < mg["abs_ln_ratio_delta_min"]:
                ties.append(e)
        else:
            ties.append(e)
    if len(ties) > 1:
        out["outcome"] = "AMBIGUOUS"; out["primary"] = "AMBIGUOUS_CANDIDATES_WITHIN_MARGIN"
        add(out["primary"], "primary")
        out["alternatives"] = [{"target_ids": x["c"]["target_ids"], "candidate_status": "PROPOSED", "link_type": x["link"]} for x in ties]
        out["review"] = {"required": True, "queue": "crosswalk_review", "priority": "normal", "question": None}
        for x in ties:
            for tid in x["c"]["target_ids"]:
                out["writes"].append(_wr(tid, matrix_action(x["c"].get("pair_state", "NONE"), "PROPOSE", "not_applicable"), x["link"], x["c"].get("set_id")))
        out["codes"] = codes
        return out

    c = best["c"]; ev = c["evidence"]
    out["evidence"] = ev
    out["target_ids"] = c["target_ids"]
    out["link_type"] = best["link"]
    out["set_id"] = c.get("set_id") if best["link"] == "COMPOSED_OF" else None
    b = ev["brand"] or {}
    if b.get("relation") == "EXACT": add("BRND_EXACT", "supporting")
    elif b.get("relation") == "ALIAS_SAME": add("BRND_ALIAS_SAME", "supporting")
    elif b.get("relation") == "ALIAS_RELABEL": add("BRND_ALIAS_RELABEL", "supporting")
    n = ev["name"] or {}
    support = {"EQUAL": "NAME_EQUAL", "EQUAL_VIA_MODEL_ALIAS": "NAME_EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV": "NAME_EQUAL_VIA_TOKEN_EQUIV"}
    if n.get("relation") in support: add(support[n["relation"]], "supporting")
    if best["series_strong"]: add("SER_BUNDLE_STRONG" if best["link"] == "COMPOSED_OF" else "SER_STRONG", "supporting")
    if best["link"] == "COMPOSED_OF": add("GRAN_PROVIDER_COARSER", "supporting")
    if best["link"] == "PART_OF": add("GRAN_PROVIDER_FINER", "supporting")
    if best["auto_ok"]:
        out["outcome"] = "AUTO"; out["proposed_status"] = "AUTO"; out["method"] = "SERIES"
        out["primary"] = "AUTO_ALL_GATES_PASSED"; add(out["primary"], "primary")
    else:
        out["outcome"] = "PROPOSE"; out["proposed_status"] = "PROPOSED"
        out["method"] = "SERIES" if (best["series_strong"] and best["link"] != "PART_OF") else "NAME"
        if best["link"] == "COMPOSED_OF": out["primary"] = "PROPOSE_COMPOSED_OF"
        elif best["link"] == "PART_OF": out["primary"] = "PROPOSE_PART_OF"
        elif best["series_strong"]: out["primary"] = "PROPOSE_SERIES_STRONG_CAPPED"
        else: out["primary"] = "PROPOSE_NAME_MATCH_SERIES_NOT_STRONG"
        add(out["primary"], "primary")
        for x in best["block"]:
            if x == "NAME_ONLY_NOT_AUTO" and best["series_strong"]: continue
            add(x, "blocking")
        out["review"] = {"required": True, "queue": "crosswalk_review", "priority": "normal", "question": None}
    if best["link"] != "PART_OF":
        for x in series_codes_from_tuple(ev["series"]):
            add(x, series_role(x, "blocking", ev["series"]))
    elif (ev["series"] or {}).get("semantics_gap_months", 0) > 0:
        add(GAP_CODE, series_role(GAP_CODE, "info", ev["series"]))
    if n.get("relation") == "UNAVAILABLE": add("NAME_UNAVAILABLE", "info")
    a = ev["attributes"] or {}
    if a.get("body") == "UNKNOWN": add("ATTR_BODY_UNKNOWN", "info")
    if a.get("lifecycle") == "UNKNOWN": add("GEN_LIFECYCLE_UNKNOWN", "info")
    pair = c.get("pair_state", "NONE")
    for tid in c["target_ids"]:
        out["writes"].append(_wr(tid, matrix_action(pair, "AUTO" if best["auto_ok"] else "PROPOSE", "changed" if pair == "REJECTED" else "not_applicable"),
                                 best["link"], out["set_id"]))
    out["codes"] = codes
    return out

def _discovery(inp, out, add, sflags):
    pol = POL["subject_quality"]["discovery"]
    units = inp["subject"]["total_units"]
    if out["outcome"] == "NO_CANDIDATE" and out["primary"] != "BRND_UNKNOWN" and units >= pol["catalog_gap_min_units"]:
        add("DISCOVERY_CATALOG_GAP", "info")
        out["review"] = {"required": True, "queue": "discovery", "priority": "normal", "question": None}
    elif [f for f in sflags if f in POL["review"]["discovery_subject_flags"]] and out["outcome"] in ("NO_CANDIDATE", "INSUFFICIENT_DATA") and units >= pol["provisional_min_units"]:
        out["review"] = {"required": True, "queue": "discovery", "priority": "normal", "question": None}
    for f in sflags: add(f, "info")

# ----------------------------------------------------------------------------- lineage
def lineage(inp):
    live = set(inp["live_subject_ids"])
    L = inp["lineage"]
    ops = []
    if L["declared_identity_change"] and not L["source_present"]:
        return {"refusal": "LIN_SOURCE_MISSING"}
    events = L["events"]
    applied = set(L.get("applied_event_keys", []))
    maps = inp.get("existing_mappings", [])
    olds = {e["old_id"] for e in events}; news = {e["new_id"] for e in events}
    both = olds & news
    by_old = {}
    for e in events: by_old.setdefault(e["old_id"], []).append(e)
    def key(e): return f"{e['event_type']}:{e['old_id']}>{e['new_id']}"
    def op(o, e, primary, include=(), **kw):
        d = {"op": o, "old_id": e["old_id"] if e else kw.get("old_id"), "new_id": e["new_id"] if e else kw.get("new_id"), "primary": primary,
             "codes": [primary, *include], "requires_owner_ack": False, "hint_target_ids": [], "affects_protected": {"approved": 0, "locked": 0}}
        d.update({k: v for k, v in kw.items() if k not in ("old_id", "new_id")})
        ops.append(d); return d
    # retired redirect resolution
    redirect_of = {}
    for old, evs in by_old.items():
        if old in live: continue
        splits = [e for e in evs if e["event_type"] == "SPLIT"]
        explicit = [e for e in evs if e.get("successor_id")]
        if len(evs) == 1 and evs[0]["event_type"] in ("RENAME", "MERGE"):
            redirect_of[old] = (evs[0], None)
        elif explicit:
            tgt = explicit[0]["successor_id"]
            redirect_of[old] = (next((e for e in evs if e["new_id"] == tgt), evs[0]), "explicit")
        elif splits:
            best = sorted(splits, key=lambda e: (-(e.get("share_of_old_pct") or 0), e["new_id"]))
            tie = len(best) > 1 and (best[0].get("share_of_old_pct") == best[1].get("share_of_old_pct"))
            redirect_of[old] = (best[0], "tie" if tie else None)
    # cycle detection among retired ids
    cyc = set()
    for old in list(redirect_of):
        path, cur = [], old
        while cur in redirect_of and cur not in live:
            if cur in path:
                cyc |= set(path[path.index(cur):]); break
            path.append(cur); cur = redirect_of[cur][0]["new_id"]
    for old in sorted(cyc):
        op("ERROR", redirect_of[old][0], "LIN_CYCLE_NO_REDIRECT"); del redirect_of[old]
    for old, (e, flag) in redirect_of.items():
        if key(e) in applied:
            op("NOOP", e, "LIN_ALREADY_APPLIED"); continue
        if e["new_id"] not in live:
            op("ERROR", e, "LIN_TARGET_NOT_LIVE"); continue
        etype = e["event_type"]
        pcode = {"RENAME": "LIN_RENAME_FOLLOWED", "MERGE": "LIN_MERGE_FOLLOWED", "SPLIT": "LIN_REDIRECT_RETIRED_SPLIT"}[etype]
        inc = []
        if flag == "tie": inc.append("LIN_TIE_BREAK_ID_ASC")
        if old.endswith("__provisional"): inc.append("LIN_PROVISIONAL_PROMOTED")
        if old in both: inc.append("LIN_NO_CHAIN")
        op("REDIRECT", e, pcode, inc)
        rows = [m for m in maps if m["subject_id"] == old]
        if etype == "SPLIT":
            if rows:
                op("FLAG_MAPPING_REVIEW", e, "LIN_PARENT_MAPPING_REVIEW")
            continue
        pp = POL["lineage"]["protected"]
        ack_states = {s for s, setting in (("APPROVED", pp["approved"]), ("LOCKED", pp["locked"])) if setting == "require_owner_ack"}
        waiting = [m for m in rows if m["state"] in ack_states]
        locked = [m for m in waiting if m["state"] == "LOCKED"]
        approved = [m for m in waiting if m["state"] == "APPROVED"]
        if waiting:
            op("FLAG_MAPPING_REVIEW", e, "LIN_PROTECTED_NEEDS_OWNER_ACK", requires_owner_ack=True,
               affects_protected={"approved": len(approved), "locked": len(locked)})
        movable = [m for m in rows if m["state"] not in ack_states]
        # a claim moves as a unit (a COMPOSED_OF set is one claim); "two active subjects" is the C1/C2 test of SPEC §7.0
        def _ckey(m):
            lt = m.get("link_type", "EQUIVALENT")
            return (lt, m.get("set_id") if lt == "COMPOSED_OF" else m["target_id"])
        groups = {}
        for m in movable: groups.setdefault(_ckey(m), []).append(m)
        others = {}
        for o in maps:
            if o["subject_id"] not in (old, e["new_id"]) and o["state"] in ("AUTO", "APPROVED", "LOCKED"):
                others.setdefault((o["subject_id"], _ckey(o)), []).append(o)
        conflicts = []
        for ck, grp in list(groups.items()):
            if grp[0]["state"] not in ("AUTO", "APPROVED"): continue
            tset = {r["target_id"] for r in grp}
            for (osub, okey), orows in others.items():
                if tset & {r["target_id"] for r in orows} and not (ck[0] == "PART_OF" and okey[0] == "PART_OF"):
                    conflicts.extend(grp); del groups[ck]; break
        movable = [m for grp in groups.values() for m in grp]
        if conflicts:
            op("FLAG_MAPPING_REVIEW", e, "LIN_MOVE_TARGET_CONFLICT")
        if movable:
            inc2 = ["LIN_PROTECTED_FOLLOWED_WITH_LINEAGE"] if any(m["state"] == "APPROVED" for m in movable) else []
            op("MOVE_MAPPINGS", e, pcode, inc2, affects_protected={"approved": sum(1 for grp in groups.values() if grp[0]["state"] == "APPROVED"), "locked": 0})
    # live split parents / children + quarantine
    for e in events:
        if e["event_type"] != "SPLIT": continue
        if e["old_id"] in live:
            if key(e) in applied:
                op("NOOP", e, "LIN_ALREADY_APPLIED"); continue
            inc = ["LIN_NO_CHAIN"] if e["old_id"] in both else []
            op("NOOP", e, "LIN_SPLIT_PARENT_RETAINED", inc)
            if POL["lineage"]["quarantine"]["split_parent"] and not any(o["op"] == "QUARANTINE" and o["old_id"] == e["old_id"] for o in ops):
                op("QUARANTINE", None, "LIN_EVIDENCE_QUARANTINE", old_id=e["old_id"], new_id=None)
            rows = [m for m in maps if m["subject_id"] == e["old_id"] and m["state"] in ("AUTO", "APPROVED", "LOCKED")]
            if rows:
                op("FLAG_MAPPING_REVIEW", e, "LIN_PARENT_MAPPING_REVIEW")
        if POL["lineage"]["quarantine"]["split_child"] and e["new_id"] in live and key(e) not in applied:
            if not any(o["op"] == "QUARANTINE" and o["old_id"] == e["new_id"] for o in ops):
                op("QUARANTINE", None, "LIN_EVIDENCE_QUARANTINE", old_id=e["new_id"], new_id=None)
            hints = sorted({m["target_id"] for m in maps if m["subject_id"] == e["old_id"] and m["state"] in ("AUTO", "APPROVED", "LOCKED") and m["target_id"]})
            if hints and POL["lineage"]["split_child_structure_card"]:
                op("CANDIDATE_HINT", e, "LIN_SPLIT_CHILD_INHERITED_CANDIDATE", hint_target_ids=hints, old_id=e["old_id"], new_id=e["new_id"])
    for etype, flag in (("MERGE", "merge_target"), ("RENAME", "rename_target")):
        if not POL["lineage"]["quarantine"][flag]: continue
        for e in events:
            if e["event_type"] == etype and e["new_id"] in live and key(e) not in applied:
                if not any(o["op"] == "QUARANTINE" and o["old_id"] == e["new_id"] for o in ops):
                    op("QUARANTINE", None, "LIN_EVIDENCE_QUARANTINE", old_id=e["new_id"], new_id=None)
    return {"operations": ops}

if __name__ == "__main__":
    print(band("correlation", 0.97), band("ratio", 1.1), band("common_months", 12), band("name_score", 0.5))


def classify(inp):
    out = _classify(inp)
    codes = out["codes"]
    # review routing is policy-driven (SPEC §8.5): base queue from the outcome, then the specific rules
    rv = out["review"]
    base = POL["review"]["routing"][out["outcome"]]
    explicit = rv["queue"] != "none" or rv["required"]
    if not explicit:
        rv["queue"] = base
        rv["required"] = base != "none"
    def add(c, role):
        if (c, role) not in codes and c not in [x for x, _ in codes]:
            codes.append((c, role))
    # same nameplate across candidates
    toks = {}
    for c in inp["candidates"]:
        n = c["evidence"]["name"]
        if n and n["target_tokens"]:
            toks.setdefault(tuple(n["target_tokens"]), []).append(c["target_ids"])
    if any(len(v) > 1 for v in toks.values()):
        add("GEN_SAME_NAMEPLATE_MULTI_TARGET", "info")
    # structure over statistics
    if inp.get("quarantined") and out["outcome"] == "PROPOSE" and out.get("evidence") and out["evidence"]["series"]["state"] == "STRONG":
        add("AUTH_STRUCTURE_OVER_STATISTICS", "info")
    # writes: demote / stale codes
    for w in out["writes"]:
        if w["action"] == "DEMOTE_TO_PROPOSED": add("STATE_AUTO_DEMOTED", "info")
        if w["action"] == "MARK_STALE": add("STATE_CANDIDATE_STALE", "info")
    present = {c for c, _ in codes}
    if present & set(POL["review"]["high_priority_codes"]):
        rv["priority"] = "high"
    for a in inp.get("absent_existing", []):
        action = matrix_action(a["pair_state"], "ABSENT", "not_applicable")
        out["writes"].append(_wr(a["target_id"], action, a.get("link_type", "EQUIVALENT"), a.get("set_id")))
        if action == "DEMOTE_TO_PROPOSED": add("STATE_AUTO_DEMOTED", "info")
        if action == "MARK_STALE": add("STATE_CANDIDATE_STALE", "info")
    return out
