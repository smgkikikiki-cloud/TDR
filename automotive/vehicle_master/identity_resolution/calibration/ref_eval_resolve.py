"""REFERENCE EVALUATOR (resolve) - end-to-end resolve() on top of ref_eval_core, for calibration only. It is NOT the engine (see ref_eval_core)."""
from __future__ import annotations
import hashlib, json, math
from itertools import combinations

from identity_resolution.contract import loader
from . import ref_eval_core as P
from .ref_eval_core import POL, REG, pidx, pstr

ADOPTION = loader.load_adoption()
ACTIVE = ("AUTO", "APPROVED", "LOCKED")
PROTECTED = ("APPROVED", "LOCKED")

def capabilities():
    return {name: {"value": spec["series.absent_row"]["value"], "status": spec["series.absent_row"]["status"]}
            for name, spec in loader.load_capabilities()["sources"].items()}

def _compat(label, body_type):
    att = POL["attributes"]["body"]
    if not label or not body_type or body_type == "OTHER":
        return "UNKNOWN"
    allowed = att["compatibility"].get(label)
    if allowed is None:
        return "UNKNOWN"
    return "MATCH" if body_type in allowed else "MISMATCH"

def _lifecycle(subject_series, generations, as_of):
    if not generations or subject_series is None:
        return "UNKNOWN", None
    grace = POL["attributes"]["lifecycle"]["grace_months"]
    ranges = []
    for g in generations:
        lo = pidx(g["launched"]) - grace if g.get("launched") else -10**9
        hi = (pidx(g["ended"]) + grace) if g.get("ended") else pidx(as_of) + 10**6
        ranges.append((lo, hi))
    start = pidx(subject_series["start"])
    tot = inside = 0
    for i, c in enumerate(subject_series["counts"]):
        if c is None: continue
        tot += c
        if any(lo <= start + i <= hi for lo, hi in ranges): inside += c
    if tot == 0:
        return "UNKNOWN", None
    share = P.q(inside / tot)
    L = POL["attributes"]["lifecycle"]
    if share >= L["within_min_share"]: return "WITHIN", share
    if share < L["disjoint_max_share"]: return "DISJOINT", share
    return "PARTIAL", share

def _absent_refusal(sv, caps):
    blk = (sv or {}).get("absent_rows")
    if not blk:
        return None
    declared = caps.get(blk["source"])
    if declared is None or declared["value"] != blk["semantics"] or (declared["status"] == "confirmed") != blk["confirmed"]:
        return "INPUT_CAPABILITY_MISMATCH"
    zero_ok = blk["semantics"] == "ABSENT_IS_ZERO" and blk["confirmed"]
    s0 = pidx(sv["start"])
    for m in blk["months"]:
        off = pidx(m) - s0
        if 0 <= off < len(sv["counts"]) and sv["counts"][off] is not None and not zero_ok:
            return "INPUT_ABSENT_ROW_ZERO_UNCONFIRMED"
    return None

def refusal(snap):
    pv = POL["policy"]["version"]
    if snap["policy_version"] != pv: return "INPUT_POLICY_VERSION_UNSUPPORTED"
    if not snap["source_version"]["label"].strip(): return "INPUT_SOURCE_VERSION_MISSING"
    ids = [s["entity_id"] for s in snap["subjects"]]
    if len(ids) != len(set(ids)): return "INPUT_DUPLICATE_SUBJECT_ID"
    lo, hi = POL["time"]["valid_year_range"]
    series = [s.get("series") for s in snap["subjects"]] + [t.get("series") for t in snap["targets"]]
    for sv in series:
        if not sv: continue
        for p in [sv["start"], pstr(pidx(sv["start"]) + len(sv["counts"]) - 1)]:
            if not (lo <= int(p[:4]) <= hi): return "INPUT_PERIOD_CALENDAR_INVALID"
        if any(c is not None and c < 0 for c in sv["counts"]): return "INPUT_NEGATIVE_COUNT"
    caps = capabilities()
    for sv in series:
        r = _absent_refusal(sv, caps)
        if r: return r
    return None

def _name_ev(subj, tgt):
    rel, score, st, tt = P.name_relation(subj["display_name"], subj["brand"], tgt["display_name"], tgt["brand"],
                                         tuple(subj.get("brands_observed", [])))
    return {"relation": rel, "score": None if score is None else P.q(score), "subject_tokens": st, "target_tokens": tt}

# ----------------------------------------------------------------------------- claims (SPEC §7.0, §10.5)
def set_id_for(provider, subject, targets):
    payload = {"v": "link-set/1", "contract": "v1", "provider": provider, "subject": subject, "targets": sorted(targets)}
    return "ls1-" + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()[:24]

def row_type(m): return m.get("link_type", "EQUIVALENT")
def claim_key(link, target_id, set_id): return (link, set_id if link == "COMPOSED_OF" else target_id)

def claims_of(maps, sid):
    groups = {}
    for m in maps:
        if m["subject_id"] == sid:
            groups.setdefault(claim_key(row_type(m), m["target_id"], m.get("set_id")), []).append(m)
    return groups

def stored_consistent(maps, sid, provider):
    groups = claims_of(maps, sid)
    if sum(1 for rows in groups.values() if any(r["state"] in ACTIVE for r in rows)) > 1:
        return False
    # stored overlap with ANOTHER subject's active claim (C2): reported on both sides, never repaired (I18)
    for (lt, key), rows in groups.items():
        if rows[0]["state"] not in ACTIVE: continue
        for o in {m["subject_id"] for m in maps if m["subject_id"] != sid}:
            for (olt, okey), orows in claims_of(maps, o).items():
                if orows[0]["state"] in ACTIVE and conflict(lt, [r["target_id"] for r in rows], olt, [r["target_id"] for r in orows]):
                    return False
    for (lt, key), rows in groups.items():
        if lt != "COMPOSED_OF": continue
        if len({r["state"] for r in rows}) > 1: return False
        if len({r.get("set_size") for r in rows}) > 1 or len(rows) != rows[0].get("set_size"): return False
        if key != set_id_for(provider, sid, [r["target_id"] for r in rows]): return False
    return True

def conflict(a_link, a_targets, b_link, b_targets):
    """C2 for claims of different subjects."""
    return bool(set(a_targets) & set(b_targets)) and not (a_link == "PART_OF" and b_link == "PART_OF")

def held_by_others(maps, sid, link, targets):
    held = "NONE"
    others = {m["subject_id"] for m in maps if m["subject_id"] != sid}
    for o in others:
        for (lt, key), rows in claims_of(maps, o).items():
            st = rows[0]["state"]
            if st not in ACTIVE: continue
            if conflict(link, targets, lt, [r["target_id"] for r in rows]):
                if st in PROTECTED: return "PROTECTED"
                held = "UNPROTECTED"
    return held

# ----------------------------------------------------------------------------- candidates
def candidate_for(subj, members, snap, quarantined, maps):
    tgt = members[0]
    sid = subj["entity_id"]
    brel, aid = P.brand_relation(subj["brand"], tgt["brand"], tuple(subj.get("brands_observed", [])))
    brand = {"relation": brel, "subject_key": P.compact(subj["brand"]) or None, "target_key": P.compact(tgt["brand"]) or None, "alias_id": aid}
    names = [_name_ev(subj, m) for m in members]
    if len(members) == 1:
        name = names[0]
    else:
        rels = {n["relation"] for n in names}
        name = {"relation": "SUBJECT_COARSER" if "SUBJECT_COARSER" in rels else sorted(rels)[0],
                "score": min(n["score"] for n in names if n["score"] is not None),
                "subject_tokens": names[0]["subject_tokens"], "target_tokens": sorted({t for n in names for t in n["target_tokens"]})}
    ts = P.sum_series([m.get("series") for m in members]) if len(members) > 1 else tgt.get("series")
    sev, cmp_, codes = P.series_evidence(subj.get("series"), ts)
    series = {k: v for k, v in sev.items() if k != "_reason"}
    series["unavailable_reason"] = sev["_reason"]
    body = _compat((subj.get("attributes") or {}).get("body"), tgt.get("body_type"))
    gens = [g for m in members for g in m.get("generations", [])]
    life, share = _lifecycle(subj.get("series"), gens, snap["as_of_period"])
    attrs = {"body": body, "lifecycle": life, "lifecycle_share": share,
             "target_status": "UNVERIFIED" if any(m["status"] == "UNVERIFIED" for m in members) else tgt["status"]}
    tids = [m["target_id"] for m in members]
    evidence = {"brand": brand, "name": name, "series": series, "attributes": attrs,
                "structure": {"quarantined": sid in quarantined, "lineage_event_keys": []}, "margin": None}
    link = "COMPOSED_OF" if len(members) > 1 else ("PART_OF" if P.is_part_of({"name": name, "series": series}) else "EQUIVALENT")
    set_id = set_id_for(snap["provider"], sid, tids) if link == "COMPOSED_OF" else None
    held = held_by_others(maps, sid, link, tids)
    # existing state of THIS claim
    pair = "NONE"; fpu = None
    rows = claims_of(maps, sid).get(claim_key(link, tids[0], set_id))
    if rows:
        pair = rows[0]["state"]; fpu = rows[0].get("evidence_fingerprint")
    prot_rows = [m for m in maps if m["subject_id"] == sid and m["state"] in PROTECTED]
    prot_types = {row_type(m) for m in prot_rows}
    prot_targets = {m["target_id"] for m in prot_rows}
    type_conflict = bool(prot_rows) and link not in prot_types
    extends = bool(prot_rows) and not type_conflict and not (set(tids) <= prot_targets)
    stripped = any(P.name_tokens(subj["display_name"], subj["brand"], extra=(m["brand"], *subj.get("brands_observed", [])))[1] or
                   P.name_tokens(m["display_name"], m["brand"], extra=(subj["brand"], *subj.get("brands_observed", [])))[1] for m in members)
    cand = {"_stripped": stripped, "target_ids": tids, "evidence": evidence, "held_elsewhere": held, "pair_state": pair,
            "rejected_fingerprint_unchanged": True if pair == "REJECTED" and fpu == "unchanged" else (False if pair == "REJECTED" else None),
            "extends_protected": extends, "link_type_conflicts_protected": type_conflict, "_cmp": cmp_, "_codes": codes}
    if len(members) > 1:
        cand["link_type"] = "COMPOSED_OF"
        cand["set_id"] = set_id
    return cand

def resolve(snap):
    r = refusal(snap)
    if r: return {"refusal": r}
    provider = snap["provider"]
    live = [s["entity_id"] for s in snap["subjects"]]
    lin_in = snap.get("lineage") or {"source_present": True, "declared_identity_change": False, "events": []}
    ops_out = P.lineage({"live_subject_ids": live, "lineage": lin_in, "existing_mappings": snap.get("existing_mappings", [])})
    if "refusal" in ops_out: return ops_out
    ops = ops_out["operations"]
    quarantined = {o["old_id"] for o in ops if o["op"] == "QUARANTINE"}
    maps = snap.get("existing_mappings", [])
    decisions = {}
    pools = {}
    first_pass = {}   # the per-subject decision BEFORE cross-subject arbitration, with its per-candidate flags (calibration only)
    dup_names = {}
    for s in snap["subjects"]:
        dup_names.setdefault(s["display_name"], []).append(s["entity_id"])
    for subj in sorted(snap["subjects"], key=lambda s: s["entity_id"]):
        sid = subj["entity_id"]
        brand_known = bool(P.compact(subj["brand"])) and P.compact(subj["brand"]) not in {P.compact(x) for x in POL["lexical"]["unavailable_name_values"] if x}
        all_brands = [subj["brand"], *subj.get("brands_observed", [])]
        tgts = []
        brand_in_tdr = False
        false_friend = False
        for t in sorted(snap["targets"], key=lambda t: t["target_id"]):
            rel = P.brand_relation(subj["brand"], t["brand"], tuple(subj.get("brands_observed", [])))[0]
            if rel == "MISMATCH" and brand_known:
                nr = P.name_relation(subj["display_name"], subj["brand"], t["display_name"], t["brand"], tuple(subj.get("brands_observed", [])))[0]
                if nr in POL["lexical"]["name"]["candidate_relations"]: false_friend = True
            if rel not in POL["candidates"]["brand_relations_allowed"]: continue
            brand_in_tdr = True
            if t["deleted"] and POL["candidates"]["exclude_deleted_targets"]: continue
            if t["status"] not in POL["candidates"]["target_statuses_in_pool"]: continue
            tgts.append(t)
        singles = [candidate_for(subj, [t], snap, quarantined, maps) for t in tgts]
        bundle_pool_size = None     # calibration only: how many members a link-set enumeration had to choose from (None = not enumerated)
        if singles and not any(c["evidence"]["series"]["state"] == "STRONG" for c in singles) and POL["candidates"]["bundle"]["enabled"]:
            full_pool = [t for t, c in zip(tgts, singles) if c["evidence"]["name"]["relation"] in POL["candidates"]["bundle"]["member_name_relations"]]
            bundle_pool_size = len(full_pool)
            pool = full_pool[:POL["candidates"]["bundle"]["max_pool_for_enumeration"]]
            for k in range(2, POL["candidates"]["bundle"]["max_members"] + 1):
                for combo in combinations(pool, k):
                    bc = candidate_for(subj, list(combo), snap, quarantined, maps)
                    if bc["evidence"]["series"]["state"] == "STRONG":
                        singles.append(bc)
        subject_in = {"entity_id": sid,
                      "identity_status": subj["identity_status"],
                      "name_available": P.name_tokens(subj["display_name"], subj["brand"])[2],
                      "total_units": sum(c for c in (subj.get("series") or {"counts": []})["counts"] if c is not None),
                      "multi_brand": len({P.compact(b) for b in all_brands if b}) > 1,
                      "duplicate_display_name": len(dup_names[subj["display_name"]]) > 1 and subj["display_name"] != ""}
        prot = []
        for (lt, key), rows in claims_of(maps, sid).items():
            if rows[0]["state"] not in PROTECTED: continue
            tids = [m["target_id"] for m in rows]
            tg = [next((t for t in snap["targets"] if t["target_id"] == x), None) for x in tids]
            exists = all(t is not None and not t["deleted"] for t in tg)
            agrees = "INCONCLUSIVE"
            if exists:
                c = candidate_for(subj, tg, snap, quarantined, maps)
                s_ = c["evidence"]["series"]
                wrong = POL["data_sufficiency"]["series_decisively_wrong"]
                if lt == "PART_OF":
                    agrees = "CONFIRMS" if P.is_part_of(c["evidence"]) else "INCONCLUSIVE"
                elif s_["state"] == "STRONG": agrees = "CONFIRMS"
                elif s_["state"] == "WEAK" and (s_["correlation"] < wrong["correlation_below"] or not (wrong["ratio_outside"][0] <= s_["ratio"] <= wrong["ratio_outside"][1])): agrees = "CONTRADICTS"
            for m in rows:
                prot.append({"target_id": m["target_id"], "state": m["state"], "agrees": agrees, "target_exists": exists, "link_type": lt})
        cin = {"subject": subject_in, "quarantined": sid in quarantined, "brand_known": brand_known,
               "brand_in_tdr": brand_in_tdr, "pool_size": len(tgts), "candidates": singles, "protected_targets": prot,
               "stored_claims": "CONSISTENT" if stored_consistent(maps, sid, provider) else "INCONSISTENT"}
        out = P.classify(cin)
        out["_cands"] = singles
        if false_friend and ("BRND_MISMATCH", "info") not in out["codes"]:
            out["codes"].append(("BRND_MISMATCH", "info"))
        _stale_writes(out, sid, maps, provider)
        chosen = None
        if out.get("target_ids"):
            chosen = next((c for c in singles if c["target_ids"] == out["target_ids"]), None)
        elif singles and out["outcome"] in ("INSUFFICIENT_DATA",):
            chosen = singles[0]
        if chosen:
            if chosen.get("_stripped") and ("BRND_PREFIX_STRIPPED", "info") not in out["codes"]:
                out["codes"].append(("BRND_PREFIX_STRIPPED", "info"))
            out["comparison"] = chosen["_cmp"]
            for x in chosen["_codes"]:
                if x in ("SER_STRONG",): continue
                if out.get("link_type") == "PART_OF" and x != P.GAP_CODE and REG[x]["roles"] == ["blocking"]: continue
                role = P.series_role(x, "info", chosen["evidence"]["series"])
                if (x, role) not in out["codes"] and x not in [c for c, _ in out["codes"]]:
                    out["codes"].append((x, role))
        out["quarantined"] = sid in quarantined
        decisions[sid] = out
        pools[sid] = singles
        first_pass[sid] = {"evals": out.get("_evals", []), "outcome": out["outcome"], "primary": out.get("primary"), "pool_size": len(tgts), "bundle_pool_size": bundle_pool_size}
    # --- arbitration 1: parts by sum (SPEC §8.6 step 1)
    if POL["granularity"]["part_of"]["arbitration_sum_check"]:
        subs = {s["entity_id"]: s for s in snap["subjects"]}
        by_target = {}
        for sid, cands in pools.items():
            if decisions[sid]["outcome"] in ("PROTECTED_HOLD",) or (decisions[sid].get("primary") == "STRUCTURAL_STORED_CLAIMS_INCONSISTENT"): continue
            for c in cands:
                if len(c["target_ids"]) == 1 and c["evidence"]["name"]["relation"] in ("EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV", "SUBJECT_FINER"):
                    by_target.setdefault(c["target_ids"][0], {})[sid] = c
        for tid, members in by_target.items():
            # a PART_OF claim REJECTED by a human leaves the subject out
            members = {sid: c for sid, c in members.items()
                       if not (claims_of(maps, sid).get(("PART_OF", tid)) and claims_of(maps, sid)[("PART_OF", tid)][0]["state"] == "REJECTED")}
            if len(members) < 2: continue
            # a T held by a conflicting protected claim of a subject outside P(T): the rule does not apply
            if any(m["subject_id"] not in members and m["state"] in PROTECTED and m["target_id"] == tid and row_type(m) != "PART_OF" for m in maps):
                continue
            tgt = next(t for t in snap["targets"] if t["target_id"] == tid)
            # no member may be individually STRONG against T
            if any(c["evidence"]["series"]["state"] == "STRONG" for c in members.values()):
                continue
            ssum = P.sum_series([subs[x].get("series") for x in sorted(members)])
            sev, _, _ = P.series_evidence(ssum, tgt.get("series"))
            if sev["state"] != "STRONG":
                continue
            sum_ev = {k: v for k, v in sev.items() if k != "_reason"}
            sum_ev["unavailable_reason"] = sev["_reason"]
            for sid in sorted(members):
                d = decisions[sid]
                c = members[sid]
                row = claims_of(maps, sid).get(("PART_OF", tid))
                pair = row[0]["state"] if row else "NONE"
                new = {"outcome": "PROPOSE", "primary": "PROPOSE_PART_OF", "proposed_status": "PROPOSED", "method": "SERIES",
                       "codes": [("PROPOSE_PART_OF", "primary"), ("SER_PARTS_SUM_STRONG", "supporting"), ("GRAN_PROVIDER_FINER", "supporting")],
                       "target_ids": [tid], "link_type": "PART_OF", "set_id": None, "alternatives": [],
                       "evidence": {**c["evidence"], "parts": {"subject_ids": sorted(members), "series": sum_ev}},
                       "writes": [P._wr(tid, P.matrix_action(pair, "PROPOSE", "not_applicable"), "PART_OF")],
                       "review": {"required": True, "queue": "crosswalk_review", "priority": "normal", "question": None},
                       "quarantined": d["quarantined"], "comparison": c["_cmp"]}
                _stale_writes(new, sid, maps, provider)
                decisions[sid] = new
    # --- arbitration 2: contested AUTO targets
    claims = {}
    for sid, d in decisions.items():
        if d["outcome"] == "AUTO":
            claims.setdefault(d["target_ids"][0], []).append(sid)
    for tid, sids in claims.items():
        if len(sids) > 1:
            for sid in sids:
                d = decisions[sid]
                decisions[sid] = {"outcome": "AMBIGUOUS", "primary": "AMBIGUOUS_TARGET_CONTESTED",
                                  "codes": [("AMBIGUOUS_TARGET_CONTESTED", "primary")], "proposed_status": "NONE", "method": "NONE",
                                  "target_ids": [], "link_type": None, "set_id": None,
                                  "alternatives": [{"target_ids": [tid], "candidate_status": "PROPOSED", "link_type": "EQUIVALENT"}] * 2, "writes": [],
                                  "review": {"required": True, "queue": "crosswalk_review", "priority": "normal", "question": None}, "quarantined": d["quarantined"]}
    # --- arbitration 3: annotate proposals that conflict with another subject's AUTO claim
    auto_claims = [(sid, "EQUIVALENT", d["target_ids"]) for sid, d in decisions.items() if d["outcome"] == "AUTO"]
    for sid, d in decisions.items():
        if d["outcome"] != "PROPOSE": continue
        for osid, olink, otids in auto_claims:
            if osid != sid and conflict(d["link_type"], d["target_ids"], olink, otids):
                if ("CARD_CLAIM_CONFLICTS_AUTO", "info") not in d["codes"]:
                    d["codes"].append(("CARD_CLAIM_CONFLICTS_AUTO", "info"))
    for d in decisions.values():
        d["policy_binding"] = ADOPTION["binding"]
    return {"decisions": decisions, "operations": ops, "pools": pools, "first_pass": first_pass}

def _stale_writes(out, sid, maps, provider):
    """Stored PROPOSED/AUTO claims the decision no longer produces are ABSENT for the write matrix (SPEC §10.1, §10.2)."""
    produced = set()
    def add(link, tids, set_id):
        if link == "COMPOSED_OF":
            produced.add(("COMPOSED_OF", set_id or set_id_for(provider, sid, tids)))
        else:
            for t in tids: produced.add((link, t))
    if out.get("target_ids") and out.get("link_type"):
        add(out["link_type"], out["target_ids"], out.get("set_id"))
    for a in out.get("alternatives", []):
        add(a.get("link_type", "EQUIVALENT"), a["target_ids"], None)
    if out.get("outcome") in ("PROTECTED_HOLD", "STRUCTURAL_REVIEW") and out.get("primary") == "STRUCTURAL_STORED_CLAIMS_INCONSISTENT":
        return
    for (lt, key), rows in claims_of(maps, sid).items():
        st = rows[0]["state"]
        if st not in ("PROPOSED", "AUTO") or (lt, key) in produced:
            continue
        action = P.matrix_action(st, "ABSENT", "not_applicable")
        for m in rows:
            out["writes"].append(P._wr(m["target_id"], action, lt, m.get("set_id")))
        code = {"DEMOTE_TO_PROPOSED": "STATE_AUTO_DEMOTED", "MARK_STALE": "STATE_CANDIDATE_STALE"}.get(action)
        if code and (code, "info") not in out["codes"]: out["codes"].append((code, "info"))
