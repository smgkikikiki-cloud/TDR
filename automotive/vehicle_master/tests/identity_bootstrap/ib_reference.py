"""REFERENCE ORACLE for the Identity Bootstrap v1 contract -- test support only, NOT the engine.

It executes SPEC.md literally so the golden corpus can be checked for self-consistency, property-tested (volume independence,
order independence, idempotency, source-version independence) and mutation-tested against policy.yaml. It reads every number,
word list and mapping from the policy; it has no Supabase client, no file I/O, no clock and no Ice knowledge.

It was written by the author of the contract and the corpus. Agreement between the two shows they are consistent with each other,
not that the rules are right. The production engine (a later milestone, own gate) must pass the same corpus; until a conformance
runner exists, an ``engine/`` directory is refused by test_ib_isolation.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import re
import unicodedata
from typing import Any

THAI_LOW, THAI_HIGH = "฀", "๿"


# ---------------------------------------------------------------------------------------------------------------- canonical hashing
def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def policy_digest(policy: dict) -> str:
    return sha({k: v for k, v in policy.items() if k != "provenance"})


# ---------------------------------------------------------------------------------------------------------------- lexical layer (SPEC §4)
def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _plain_tokens(text: str, policy: dict) -> list[str]:
    boundary = set(policy["lexical"]["token_boundary_characters"])
    folded = "".join(" " if (c in boundary or c.isspace()) else c for c in _norm(text))
    kept = "".join(c for c in folded if c == " " or c.isalnum() or THAI_LOW <= c <= THAI_HIGH)
    return kept.split()


def name_tokens(name: str, spellings: list[str], policy: dict) -> list[str]:
    tokens = _plain_tokens(name, policy)
    best: list[str] = []
    for spelling in spellings:
        lead = _plain_tokens(spelling, policy)
        if lead and len(lead) < len(tokens) and tokens[:len(lead)] == lead and len(lead) > len(best):
            best = lead
    tokens = tokens[len(best):]
    generic = {_norm(g) for g in policy["lexical"]["generic_tokens"]}
    return [t for t in tokens if t not in generic]


def compact(name: str, spellings: list[str], policy: dict) -> str:
    return "".join(name_tokens(name, spellings, policy))


def canonical_name(display_name: str, spellings: list[str], policy: dict) -> str:
    words = display_name.split()
    cfg = policy["allocation"]["canonical_name"]
    if cfg["strip_brand_prefix"]:
        best = 0
        for spelling in spellings:
            lead = _plain_tokens(spelling, policy)
            if not lead:
                continue
            seen: list[str] = []
            for count, word in enumerate(words, start=1):
                seen += _plain_tokens(word, policy)
                if seen == lead:
                    if count < len(words) and count > best:
                        best = count
                    break
                if len(seen) > len(lead) or seen != lead[:len(seen)]:
                    break
        words = words[best:]
    return " ".join(words) if cfg["collapse_whitespace"] else display_name


def _spellings(subject: dict, policy: dict) -> list[str]:
    """Spellings of the marque itself: anything the policy lists as a sub-brand of this brand is not one, whoever offered it."""
    brand = subject["brand"]
    banned = {"".join(_plain_tokens(n, policy)) for n in policy["brand"]["sub_brands"].get(brand["brand_id"] or "", [])}
    return [s for s in [brand["raw"], *brand.get("spellings", [])] if "".join(_plain_tokens(s, policy)) not in banned]


def _is_unavailable(subject: dict, policy: dict) -> bool:
    spellings = _spellings(subject, policy)
    tokens = name_tokens(subject["display_name"], spellings, policy)
    if not tokens:
        return True
    unavailable = {"".join(_plain_tokens(v, policy)) for v in policy["subject"]["unavailable_name_values"]}
    return "".join(tokens) in unavailable


def shape_codes(subject: dict, policy: dict) -> set[str]:
    shape = policy["shape"]
    tokens = name_tokens(subject["display_name"], _spellings(subject, policy), policy)
    lowered = _norm(subject["display_name"])
    out: set[str] = set()

    def has(cls: str) -> bool:
        spec = shape[cls]
        words = {_norm(t) for t in spec.get("tokens", [])}
        if any(t in words for t in tokens):
            return True
        candidates = tokens + (["".join(tokens)] if len(tokens) > 1 else [])   # 'E-300' is the code e300 however it is spaced
        if any(re.search(p, t) for p in spec.get("token_patterns", []) for t in candidates):
            return True
        if len(tokens) >= spec.get("contextual_min_tokens", 2) and any(re.search(p, t) for p in spec.get("contextual_token_patterns", []) for t in tokens):
            return True
        return any(re.search(p, lowered) for p in spec.get("name_patterns", []))

    for cls, code in shape["codes"].items():
        if has(cls):
            out.add(code)
    trunc = shape["truncation"]
    if tokens:
        compact_name = "".join(tokens)
        too_short = len(compact_name) < trunc["min_compact_chars"] and not (trunc["exempt_digit_only"] and compact_name.isdigit())
        if too_short or all(t in {_norm(w) for w in trunc["dangling_tokens"]} for t in tokens):
            out.add(trunc["code"])
    return out


# ---------------------------------------------------------------------------------------------------------------- allocation (SPEC §9)
def slug_function(policy: dict):
    module, _, attribute = policy["allocation"]["local_segment_function"].rpartition(".")
    return getattr(importlib.import_module(module), attribute)


def allocate(brand_id: str, name: str, identities: list[dict], policy: dict, slugger=None) -> dict:
    """The deterministic canonical id for (brand, canonical name). No provider id, source version, order or clock is read."""
    cfg = policy["allocation"]
    assert cfg["collision_resolution"] == "REVIEW", "v1 has no auto-suffix"
    local = (slugger or slug_function(policy))(name)
    if not local or local in cfg["forbidden_local_segments"]:
        return {"ok": False, "reason": "NAME_UNSPECIFIED"}
    canonical_id = cfg["id_format"].format(brand_id=brand_id, local=local)
    slug = f"{brand_id}-{local}".replace("_", "-")
    taken = [i for i in identities if i["canonical_id"] == canonical_id or i.get("slug") == slug]   # tombstones and deleted rows reserve ids
    return {"ok": True, "canonical_id": canonical_id, "slug": slug, "local_segment": local,
            "collision": bool(taken), "taken_by": sorted({i["canonical_id"] for i in taken})}


# ---------------------------------------------------------------------------------------------------------------- the decision procedure
INVERSE = {"SUBJECT_FINER": "SUBJECT_COARSER", "SUBJECT_COARSER": "SUBJECT_FINER"}
ROUTE_RANK = {"HOLD": 0, "REVIEW": 1, "CREATE": 2}


class Refusal(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def _class_of(relation: str, policy: dict) -> str | None:
    for cls, members in policy["relations"]["name_classes"].items():
        if relation in members:
            return None if cls == "ignored" else cls
    raise ValueError(relation)


def _peer_class(state, policy: dict) -> str:
    return policy["relations"]["peer_state_classes"]["legacy" if state is None else state]


def _sid(provider: str, entity_id: str) -> str:
    return f"{provider}:{entity_id}"


def refuse_checks(snapshot: dict, policy: dict) -> None:
    if snapshot["policy_version"] != policy["version"]:
        raise Refusal("INPUT_POLICY_VERSION_UNSUPPORTED", str(snapshot["policy_version"]))
    if not snapshot["source_version"]["label"].strip():
        raise Refusal("INPUT_SOURCE_VERSION_MISSING", "empty label")
    seen: set[str] = set()
    for s in snapshot["subjects"]:
        sid = _sid(s["provider"], s["entity_id"])
        if sid in seen:
            raise Refusal("INPUT_DUPLICATE_SUBJECT_ID", sid)
        seen.add(sid)
        if "resolution" not in s:
            raise Refusal("INPUT_RESOLUTION_MISSING", sid)
    lin = snapshot["lineage"]
    if lin["declared_identity_change"] and not lin["source_present"]:
        raise Refusal("INPUT_LINEAGE_SOURCE_MISSING", "declared identity change without a machine-readable source")


def decide(snapshot: dict, policy: dict, registry: dict, slugger=None) -> list[dict]:
    """Return one decision per subject, ordered by (provider, entity_id); raise Refusal for the whole run."""
    refuse_checks(snapshot, policy)
    codes_reg = registry["codes"]
    subjects = {_sid(s["provider"], s["entity_id"]): s for s in snapshot["subjects"]}
    identities = snapshot["identities"]
    by_id = {i["canonical_id"]: i for i in identities}
    bindings = {(b["provider"], b["external_id"]): b for b in snapshot["bindings"]}
    digest = policy_digest(policy)

    fired: dict[str, dict[str, list[dict]]] = {sid: {} for sid in subjects}     # sid -> code -> [detail]
    facts: dict[str, dict] = {}

    def fire(sid: str, code: str, **detail: Any) -> None:
        fired[sid].setdefault(code, []).append(detail)

    def blocking(sid: str) -> set[str]:
        return {c for c in fired[sid] if codes_reg[c]["route"] in ("HOLD", "REVIEW")}

    # ---- per-subject facts and gates G0-G5 -----------------------------------------------------------------------------------
    for sid, s in sorted(subjects.items()):
        spell = _spellings(s, policy)
        tokens = name_tokens(s["display_name"], spell, policy)
        brand_id = s["brand"]["brand_id"]
        key = f"{brand_id}|{''.join(tokens)}" if brand_id and tokens else None
        facts[sid] = {"spellings": spell, "tokens": tokens, "identity_key": key, "retired_aliases": [], "suggest": None,
                      "excluded_neighbors": []}

        # G0 activation
        out = s["resolution"]["outcome"]
        if out != policy["activation"]["required_ir_outcome"]:
            if out == policy["activation"]["structural_review_outcome"]:
                fire(sid, "STRUCTURAL_CONFLICT", via="IR")
            else:
                fire(sid, "NOT_ACTIVATED", ir_outcome=out)
                facts[sid]["activated"] = False
                continue
        facts[sid]["activated"] = True

        # G1 subject sanity
        if s["identity_status"] not in policy["subject"]["creatable_identity_statuses"]:
            fire(sid, policy["subject"]["status_codes"][s["identity_status"]])
        raw = policy["subject"]["raw_name"]
        if any(ch in s["entity_id"] or ch in s["display_name"] for ch in raw["separator_characters"]) \
                or any(re.search(raw["registration_code_token_pattern"], t) for t in tokens) \
                or re.search(raw["code_segment_pattern"], _norm(s["display_name"])):
            fire(sid, "PROVIDER_RAW_NAME")
        if _is_unavailable(s, policy):
            fire(sid, "NAME_UNSPECIFIED")
        rel = s["brand"]["relation"]
        if rel not in policy["brand"]["creatable_relations"]:
            fire(sid, policy["brand"]["relation_codes"][rel])
        elif not brand_id:
            fire(sid, "BRAND_UNKNOWN")

        # G2 state: the subject's own alias, then an identity with the same brand and name key
        bound = bindings.get((s["provider"], s["entity_id"]))
        if bound:
            fire(sid, "IDENTITY_ALREADY_DISCOVERED", canonical_id=bound["canonical_id"], via="binding")
        if key:
            for i in identities:
                if i["brand_id"] != brand_id or i["canonical_id"] == (bound or {}).get("canonical_id"):
                    continue
                if compact(i["name_en"], spell, policy) != "".join(tokens):
                    continue
                cls = _peer_class(i["identity_state"], policy)
                if cls == "withdrawn":
                    fire(sid, "IDENTITY_PREVIOUSLY_WITHDRAWN", canonical_id=i["canonical_id"])
                elif cls == "pending":
                    fire(sid, "IDENTITY_ALREADY_DISCOVERED", canonical_id=i["canonical_id"], via="identity_key")
                    facts[sid]["suggest"] = (i["canonical_id"], "IDENTITY_ALREADY_DISCOVERED")
                else:
                    fire(sid, "DUPLICATE_CANONICAL_SUSPECTED", canonical_id=i["canonical_id"], via="identity_key")

        # G2b brand family: compare names under the union of spellings; the family's spellings never enter this subject's own tokens
        fam_cfg = policy["brand"]["family"]
        for fam in s["brand"].get("family", []):
            union = spell + list(fam.get("spellings", []))
            mine_union = compact(s["display_name"], union, policy)
            if not mine_union:
                continue
            for i in identities:
                if i["brand_id"] != fam["brand_id"] or compact(i["name_en"], union, policy) != mine_union:
                    continue
                cls = _peer_class(i["identity_state"], policy)
                if fam["relation"] in fam_cfg["duplicate_relations"]:
                    if cls == "withdrawn":
                        fire(sid, "IDENTITY_PREVIOUSLY_WITHDRAWN", canonical_id=i["canonical_id"], via="brand_family")
                    elif cls == "pending":
                        fire(sid, "IDENTITY_ALREADY_DISCOVERED", canonical_id=i["canonical_id"], via="brand_family")
                        facts[sid]["suggest"] = (i["canonical_id"], "IDENTITY_ALREADY_DISCOVERED")
                    else:
                        fire(sid, "DUPLICATE_CANONICAL_SUSPECTED", canonical_id=i["canonical_id"], via="brand_family")
                elif fam["relation"] in fam_cfg["suspect_relations"] and cls != "withdrawn":
                    fire(sid, fam_cfg["suspect_code"], canonical_id=i["canonical_id"], via="brand_family")

        # G3 lineage
        _lineage(sid, s, snapshot, bindings, policy, fire, facts)

        # G4a relations to TARGET peers
        for r in s.get("relations", []):
            if r["peer_kind"] != "TARGET":
                continue
            cls = _class_of(r["name_relation"], policy)
            if cls is None:
                continue
            peer_cls = _peer_class(r.get("identity_state"), policy)
            table = policy["relations"][{"canonical": "canonical_codes", "pending": "pending_codes", "withdrawn": "withdrawn_codes"}[peer_cls]]
            code = table.get(cls)
            if code:
                fire(sid, code, canonical_id=r["peer_id"], name_relation=r["name_relation"])

        # G5 shape
        for code in sorted(shape_codes(s, policy)):
            fire(sid, code)

    # ---- G4b cross-subject arbitration -----------------------------------------------------------------------------------------
    ignore = set(policy["batch"]["ignore_peers_holding"])
    pairs: dict[tuple[str, str], str] = {}                      # (a, b) -> relation oriented a->b
    for sid, s in subjects.items():
        for r in s.get("relations", []):
            if r["peer_kind"] != "SUBJECT":
                continue
            pid = _sid(r.get("peer_provider", s["provider"]), r["peer_id"])
            if pid not in subjects:
                continue
            for a, b, rel in ((sid, pid, r["name_relation"]), (pid, sid, INVERSE.get(r["name_relation"], r["name_relation"]))):
                if pairs.setdefault((a, b), rel) != rel:
                    raise Refusal("INPUT_SCHEMA_INVALID", f"inconsistent relation between {a} and {b}")
    first_pass_hold = {sid: set(fired[sid]) for sid in subjects}
    group_edges: dict[str, set[str]] = {sid: set() for sid in subjects}
    cross_dups: list[tuple[str, str]] = []
    for (a, b), rel in sorted(pairs.items()):
        cls = _class_of(rel, policy)
        if cls is None or not facts[a]["activated"] or not facts[b]["activated"]:
            continue
        group_edges[a].add(b)
        if (first_pass_hold[b] & ignore) or (first_pass_hold[a] & ignore):
            continue
        same = subjects[a]["provider"] == subjects[b]["provider"]
        rules = policy["batch"]["same_provider" if same else "cross_provider"]
        if cls == "duplicate":
            if same:
                for c in rules["duplicate"]:
                    fire(a, c, peer=b, name_relation=rel)
            else:
                cross_dups.append((a, b))
        elif cls == "finer":
            for c in rules["finer"]:
                fire(a, c, peer=b, name_relation=rel)
        elif cls == "sibling":
            for c in rules["sibling"]:
                fire(a, c, peer=b, name_relation=rel)

    # ---- G6 evidence (only when nothing has held the subject yet) -----------------------------------------------------------
    ev_cfg = policy["evidence"]
    tiers = ev_cfg["kind_tiers"]
    evidence: dict[str, dict] = {}
    for sid, s in sorted(subjects.items()):
        if not facts[sid]["activated"]:
            continue
        valid = [e for e in s.get("evidence", []) if e["kind"] in tiers and e["ref"].strip()]
        prov = ev_cfg["providers"].get(s["provider"])
        base_ok = bool(prov and prov["may_create"] and any(e["kind"] == prov["base_kind"] for e in valid))
        tier = max((tiers[e["kind"]] for e in valid), default=None)
        evidence[sid] = {"valid": valid, "tier": tier, "base_ok": base_ok}
        if not any(codes_reg[c]["route"] == "HOLD" for c in fired[sid]):
            if not base_ok or tier is None or tier < ev_cfg["required_tier"]["create_clean"]:
                fire(sid, "INSUFFICIENT_IDENTITY_EVIDENCE")

    # ---- fingerprints of the review question, then clearing ---------------------------------------------------------------
    results: dict[str, dict] = {}
    for sid, s in sorted(subjects.items()):
        f = facts[sid]
        fired_codes = sorted(c for c in fired[sid] if codes_reg[c]["route"] != "NONE")
        rel_sig = sorted([("TARGET", r["peer_id"], r["name_relation"], _peer_class(r.get("identity_state"), policy))
                          for r in s.get("relations", []) if r["peer_kind"] == "TARGET" and _class_of(r["name_relation"], policy)]
                         + [("SUBJECT", b, rel, "subject") for (a, b), rel in pairs.items() if a == sid and _class_of(rel, policy)])
        review_fp = sha({"p": s["provider"], "e": s["entity_id"], "b": s["brand"]["brand_id"], "k": f["identity_key"],
                         "codes": fired_codes, "rel": rel_sig})
        f["review_fp"] = review_fp
        directive = next((d for d in snapshot.get("admin_directives", [])
                          if (d["provider"], d["entity_id"]) == (s["provider"], s["entity_id"]) and d["review_fingerprint"] == review_fp), None)
        cleared: list[dict] = []
        remaining = {c: list(d) for c, d in fired[sid].items()}
        info: list[str] = []
        if directive and directive["action"] == "DO_NOT_CREATE" and f["activated"]:
            remaining = {"ADMIN_DECLINED": [{}]}
        else:
            ev = evidence.get(sid)
            if ev:
                sc = ev_cfg["soft_clear"]
                attested = any(tiers[e["kind"]] >= sc["min_tier"] and sc["required_attestation"] in e.get("attests", []) for e in ev["valid"])
                if attested:
                    for c in sorted(remaining):
                        if codes_reg[c]["clearable"] in ("evidence", "evidence_or_admin") and codes_reg[c]["route"] in ("HOLD", "REVIEW"):
                            del remaining[c]
                            cleared.append({"code": c, "cleared_by": "evidence"})
                    if any(x["cleared_by"] == "evidence" for x in cleared):
                        info.append("FLAG_CLEARED_BY_EVIDENCE")
            if directive and directive["action"] == "CREATE_IDENTITY":
                admin_cleared = False
                for c in sorted(remaining):
                    if codes_reg[c]["clearable"] in ("admin", "evidence_or_admin") and codes_reg[c]["route"] in ("HOLD", "REVIEW"):
                        del remaining[c]
                        cleared.append({"code": c, "cleared_by": "admin"})
                        admin_cleared = True
                        for d in fired[sid][c]:
                            if "canonical_id" in d:
                                f["excluded_neighbors"].append({"canonical_id": d["canonical_id"], "name_relation": d.get("name_relation", "")})
                if admin_cleared:
                    info.append("ADMIN_STRUCTURE_DECISION_APPLIED")
                if any(codes_reg[c]["route"] in ("HOLD", "REVIEW") for c in remaining):
                    info.append("ADMIN_DECISION_CANNOT_CLEAR_HARD_FLAG")
        f["remaining"], f["cleared"], f["info"] = remaining, cleared, info

    # ---- coalescing, allocation, collisions ----------------------------------------------------------------------------------
    def creatable(sid: str) -> bool:
        return not any(codes_reg[c]["route"] in ("HOLD", "REVIEW") for c in facts[sid]["remaining"])

    parent = {sid: sid for sid in subjects}

    def find(x: str) -> str:
        while parent[x] != x:
            x = parent[x]
        return x

    for a, b in cross_dups:
        if creatable(a) and creatable(b):
            parent[find(a)] = find(b)
    groups: dict[str, list[str]] = {}
    for sid in subjects:
        if creatable(sid):
            groups.setdefault(find(sid), []).append(sid)
    rank = {p: i for i, p in enumerate(policy["batch"]["provider_priority"])}
    reps: dict[str, list[str]] = {}
    for members in groups.values():
        members.sort(key=lambda m: (rank.get(subjects[m]["provider"], len(rank)), subjects[m]["provider"], subjects[m]["entity_id"]))
        rep = members[0]
        reps[rep] = members
        for other in members[1:]:
            facts[other]["remaining"] = {"IDENTITY_COALESCED": [{"rep": rep}]}
        if len(members) > 1:
            facts[rep]["info"].append("MULTI_PROVIDER_CORROBORATION")

    allocations: dict[str, dict] = {}
    for rep in sorted(reps):
        s, f = subjects[rep], facts[rep]
        name = canonical_name(s["display_name"], f["spellings"], policy)
        a = allocate(s["brand"]["brand_id"], name, identities, policy, slugger)
        if not a["ok"]:
            f["remaining"]["NAME_UNSPECIFIED"] = [{}]
            continue
        a["name"] = name
        allocations[rep] = a
        if a["collision"]:
            f["remaining"]["CANONICAL_ID_COLLISION"] = [{"canonical_id": a["canonical_id"], "taken_by": a["taken_by"]}]
    owners: dict[str, list[str]] = {}
    for rep, a in allocations.items():
        for k in (a["canonical_id"], a["slug"], facts[rep]["identity_key"]):
            owners.setdefault(k, []).append(rep)
    for k, who in owners.items():
        if len(who) > 1:
            for rep in who:
                facts[rep]["remaining"]["CANONICAL_ID_COLLISION"] = [{"canonical_id": allocations[rep]["canonical_id"], "batch_peers": sorted(who)}]

    # ---- records ----------------------------------------------------------------------------------------------------------------------
    batch_groups = _components(group_edges)
    for sid, s in sorted(subjects.items()):
        results[sid] = _record(sid, s, facts[sid], subjects, reps, allocations, evidence.get(sid), snapshot, policy, registry, digest,
                               batch_groups, evidence)
    return [results[k] for k in sorted(results)]


def _components(edges: dict[str, set[str]]) -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}
    for start in sorted(edges):
        if start in seen:
            continue
        comp, stack = set(), [start]
        while stack:
            x = stack.pop()
            if x in comp:
                continue
            comp.add(x)
            stack += [y for y in edges.get(x, ()) if y not in comp]
            stack += [y for y, e in edges.items() if x in e and y not in comp]
        for m in comp:
            seen[m] = sorted(comp) if len(comp) > 1 else []
    return seen


def _lineage(sid, s, snapshot, bindings, policy, fire, facts) -> None:
    lin = snapshot["lineage"]
    me = s["entity_id"]
    actions = policy["lineage"]["actions"]
    edges: dict[str, set[str]] = {}
    for e in lin["events"]:
        edges.setdefault(e["old_id"], set()).add(e["new_id"])

    def reaches(a: str, b: str) -> bool:
        seen, stack = set(), [a]
        while stack:
            x = stack.pop()
            for y in edges.get(x, ()):
                if y == b:
                    return True
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        return False

    chosen: list[tuple[str, dict]] = []
    if reaches(me, me):
        chosen.append((actions["cycle"], {"event": "cycle"}))
    live = {_x["entity_id"] for _x in snapshot["subjects"]}
    for e in lin["events"]:
        if me == e["new_id"]:
            olds = [o["old_id"] for o in lin["events"] if o["new_id"] == me and o["event_type"] == e["event_type"]]
            owners = sorted({bindings[(s["provider"], o)]["canonical_id"] for o in olds if (s["provider"], o) in bindings})
            if e["event_type"] == "RENAME":
                act = actions["rename_old_bound"] if owners else actions["rename_old_unbound"]
            elif e["event_type"] == "MERGE":
                act = actions["merge_old_bound_to_one"] if len(owners) == 1 else \
                    actions["merge_old_bound_to_many"] if len(owners) > 1 else actions["merge_none_bound"]
            else:
                act = actions["split_any_role"]
            chosen.append((act, {"event": e["event_type"], "canonical_id": owners[0] if len(owners) == 1 else None,
                                 "olds": olds, "owners": owners}))
        elif me == e["old_id"]:
            if e["event_type"] == "SPLIT":
                chosen.append((actions["split_any_role"], {"event": "SPLIT"}))
            elif me in live and e["new_id"] != me:
                chosen.append((actions["split_any_role"], {"event": e["event_type"], "note": "old id still live"}))
    for act, d in chosen:
        if act == "HOLD_UNRESOLVED":
            fire(sid, "LINEAGE_UNRESOLVED")
        elif act == "HOLD_CONTINUITY":
            fire(sid, "LINEAGE_CONTINUITY_EXISTING_IDENTITY", canonical_id=d["canonical_id"])
            if d["canonical_id"]:
                facts[sid]["suggest"] = (d["canonical_id"], "LINEAGE_CONTINUITY_EXISTING_IDENTITY")
        elif act == "REVIEW_AMBIGUOUS":
            fire(sid, "PROVIDER_LINEAGE_AMBIGUOUS", **{k: v for k, v in d.items() if k == "event"})
        elif act == "PROCEED_WITH_RETIRED_ALIAS":
            facts[sid]["retired_aliases"] += d.get("olds", [])


def _record(sid, s, f, subjects, reps, allocations, ev, snapshot, policy, registry, digest, batch_groups, all_ev) -> dict:
    reg = registry["codes"]
    remaining = f["remaining"]
    routes = {reg[c]["route"] for c in remaining if reg[c]["route"] in ROUTE_RANK}
    win = min(routes, key=ROUTE_RANK.get) if routes else "CREATE"
    if win == "CREATE":
        remaining = {**remaining, "NEW_IDENTITY_CONFIRMED": [{}]}
    outcome = {"CREATE": "CREATE_IDENTITY", "REVIEW": "IDENTITY_REVIEW", "HOLD": "HOLD"}[win]
    all_codes = sorted(set(remaining) | set(f["info"]), key=lambda c: (reg[c]["primary_rank"], c))
    primary = min((c for c in remaining if reg[c]["route"] == win), key=lambda c: (reg[c]["primary_rank"], c))

    members = reps.get(sid, [sid])
    refs = sorted({e["ref"] for m in members for e in all_ev.get(m, {"valid": []})["valid"]})
    kinds = sorted({e["kind"] for m in members for e in all_ev.get(m, {"valid": []})["valid"]})
    tier = ev["tier"] if ev else None
    if len(members) > 1:
        kinds = sorted(set(kinds) | {policy["evidence"]["corroboration_kind"]})
        tier = max(tier or 0, policy["evidence"]["kind_tiers"][policy["evidence"]["corroboration_kind"]])
    basis = {"tier": tier, "kinds": kinds, "refs": refs, "cleared_flags": f["cleared"]}
    creator = ("admin" if "ADMIN_STRUCTURE_DECISION_APPLIED" in f["info"] else "machine") if outcome == "CREATE_IDENTITY" else None

    details = [d for c in remaining for d in remaining[c] if d.get("canonical_id")]
    existing = sorted({d["canonical_id"] for d in details})
    suggested = None
    if f.get("suggest") and outcome == "HOLD":
        suggested = {"canonical_id": f["suggest"][0], "provider": s["provider"], "external_id": s["entity_id"], "reason": f["suggest"][1]}

    units = s.get("units")
    band = policy["priority"]["unknown_units_band"] if units is None else \
        [b["band"] for b in policy["priority"]["bands"] if units >= b["min_units"]][-1]
    silent = outcome == "HOLD" and primary in policy["priority"]["silent_hold_codes"]
    queue = None if outcome == "CREATE_IDENTITY" or silent else policy["priority"]["queues"][{"IDENTITY_REVIEW": "IDENTITY_REVIEW", "HOLD": "HOLD"}[outcome]]
    review = {"required": outcome == "IDENTITY_REVIEW", "queue": queue, "priority_band": band,
              "alert": "HIGH_VOLUME_UNRESOLVED" if (queue and band in policy["priority"]["alert_bands"]) else None}

    identity = plan = None
    identity_key = f["identity_key"]
    if outcome == "CREATE_IDENTITY":
        a = allocations[sid]
        identity = {"canonical_model_id": a["canonical_id"], "brand_id": s["brand"]["brand_id"], "canonical_name": a["name"], "slug": a["slug"],
                    "identity_key": identity_key, "identity_state": policy["writes"]["initial_state"]["identity_state"],
                    "enrichment_state": policy["writes"]["initial_state"]["enrichment_state"],
                    "allocation": {"method": "BRAND_DOT_SLUG_OF_CANONICAL_NAME", "local_segment": a["local_segment"], "collision": False}}

    fingerprints = {
        "decision": sha({"c": 1, "policy": digest, "review": f["review_fp"], "outcome": outcome, "codes": all_codes,
                         "basis": {"tier": tier, "kinds": kinds, "cleared": f["cleared"]}, "id": identity and identity["canonical_model_id"]}),
        "review": f["review_fp"],
        "idempotency_key": sha({"idem": [s["provider"], s["entity_id"]]}),
        "identity_key": identity_key,
    }
    record = {"record_type": "decision", "contract_version": 1, "policy": {"version": policy["version"], "digest": digest},
              "provider": s["provider"], "source_version": snapshot["source_version"]["label"],
              "subject": {"provider": s["provider"], "entity_id": s["entity_id"], "display_name": s["display_name"]},
              "outcome": outcome, "primary_reason": primary, "reason_codes": all_codes, "evidence_basis": basis, "creator_type": creator,
              "identity": identity, "existing_identity": existing[0] if len(existing) == 1 else None, "suggested_binding": suggested,
              "batch_group": batch_groups.get(sid, []), "review": review, "write_plan": None, "fingerprints": fingerprints}
    if outcome == "CREATE_IDENTITY":
        record["write_plan"] = _plan(record, s, f, members, subjects, snapshot, policy)
    return record


def _plan(record, s, f, members, subjects, snapshot, policy) -> dict:
    ident, w = record["identity"], policy["writes"]
    cid, brand_id = ident["canonical_model_id"], ident["brand_id"]
    aliases = [{"provider": s["provider"], "external_id": s["entity_id"], "state": "ACTIVE", "relation": "ORIGIN"}]
    aliases += [{"provider": subjects[m]["provider"], "external_id": subjects[m]["entity_id"], "state": "ACTIVE", "relation": "ADDITIONAL"} for m in members[1:]]
    aliases += [{"provider": s["provider"], "external_id": old, "state": "RETIRED", "relation": "RETIRED_PREDECESSOR"} for old in sorted(set(f["retired_aliases"]))]
    first_seen = min(subjects[m]["first_seen_period"] for m in members)
    brand_rows = sorted([i["canonical_id"], i["identity_state"], i["deleted"]] for i in snapshot["identities"] if i["brand_id"] == brand_id)
    pre = [{"kind": "brand_exists", "brand_id": brand_id},
           {"kind": "canonical_id_absent", "canonical_id": cid},
           {"kind": "slug_absent", "slug": ident["slug"]},
           {"kind": "identity_key_absent", "brand_id": brand_id, "identity_key": ident["identity_key"]}]
    pre += [{"kind": "alias_absent_or_same", "provider": a["provider"], "external_id": a["external_id"], "canonical_id": cid} for a in aliases]
    pre.append({"kind": "brand_identity_digest", "brand_id": brand_id, "digest": sha(brand_rows)})

    def key(op: str, extra: Any = None) -> str:
        return sha({"op": op, "cid": cid, "x": extra})

    provenance = {"canonical_id": cid, "provider": s["provider"], "external_id": s["entity_id"], "source_version": record["source_version"],
                  "first_seen_period": first_seen, "reason_codes": record["reason_codes"], "decision_fingerprint": record["fingerprints"]["decision"],
                  "evidence_tier": record["evidence_basis"]["tier"], "evidence_kinds": record["evidence_basis"]["kinds"],
                  "evidence_refs": record["evidence_basis"]["refs"], "policy_version": policy["version"], "contract_version": 1,
                  "creator_type": record["creator_type"], "identity_key": ident["identity_key"], "apply_mode": w["apply_mode"],
                  "run_id": None, "created_at": None, "actor": None}
    event = {"event_type": policy["event"]["name"], "event_version": policy["event"]["version"], "event_id": sha({"event": policy["event"]["name"], "v": policy["event"]["version"], "cid": cid}),
             "canonical_model_id": cid, "canonical_name": ident["canonical_name"], "brand_id": brand_id,
             "identity_state": ident["identity_state"], "enrichment_state": ident["enrichment_state"],
             "source": {"provider": s["provider"], "external_id": s["entity_id"], "source_version": record["source_version"], "first_seen_period": first_seen},
             "aliases": [{"provider": a["provider"], "external_id": a["external_id"], "relation": a["relation"]} for a in aliases],
             "creation": {"reason_codes": record["reason_codes"], "decision_fingerprint": record["fingerprints"]["decision"], "creator_type": record["creator_type"],
                          "evidence": {"tier": record["evidence_basis"]["tier"], "kinds": record["evidence_basis"]["kinds"], "refs": record["evidence_basis"]["refs"]},
                          "policy_version": policy["version"], "contract_version": 1, "apply_mode": w["apply_mode"]},
             "enrichment_hints": {"known_names": sorted({subjects[m]["display_name"] for m in members} | {ident["canonical_name"]}),
                                  "excluded_neighbors": sorted(f["excluded_neighbors"], key=lambda x: x["canonical_id"]),
                                  "provider_hints": copy.deepcopy(s.get("provider_hints", {})) if policy["event"]["include_provider_hints"] else {}},
             "occurred_at": None}
    ops = [{"op": "RESERVE_CANONICAL_ID", "idempotency_key": key("RESERVE"), "values": {"canonical_id": cid, "slug": ident["slug"], "identity_key": ident["identity_key"], "brand_id": brand_id}},
           {"op": "INSERT_IDENTITY_SHELL", "idempotency_key": key("SHELL"), "table": "vehicle_models",
            "values": {c: ({"canonical_id": cid, "brand_id": brand_id, "slug": ident["slug"], "name_en": ident["canonical_name"],
                            "identity_state": ident["identity_state"], "enrichment_state": ident["enrichment_state"]})[c] for c in w["shell_columns"]}},
           {"op": "INSERT_EXTERNAL_ALIAS", "idempotency_key": key("ALIAS"), "table": "vehicle_identity_aliases",
            "rows": [{**a, "canonical_id": cid} for a in aliases]},
           {"op": "INSERT_PROVENANCE", "idempotency_key": key("PROVENANCE"), "table": "vehicle_identity_provenance", "values": provenance},
           {"op": "ENQUEUE_EVENT", "idempotency_key": key("EVENT"), "table": policy["event"]["outbox"], "values": {"event_id": event["event_id"]}},
           {"op": "PROPOSE_ORIGIN_MAPPING", "idempotency_key": key("MAPPING"),
            "values": {"provider": s["provider"], "subject_id": s["entity_id"], "canonical_id": cid, "state": "AUTO", "method": "ORIGIN"}}]
    plan = {"apply_mode": w["apply_mode"], "actor_kind": w["actor_kind"], "required_permission": w["required_permission"],
            "lock_key": w["lock_key"].format(brand_id=brand_id), "preconditions": pre, "operations": ops, "event": event,
            "deferred_fields": ["provenance.run_id", "provenance.created_at", "provenance.actor", "event.occurred_at", "event.creation.run_id"]}
    plan["plan_id"] = sha(plan)
    return {"plan_id": plan.pop("plan_id"), **plan}


def finalize(decision: dict, invocation: dict) -> dict:
    """Fill the deferred fields at apply time. The only place a run id or a timestamp enters."""
    out = copy.deepcopy(decision)
    plan = out["write_plan"]
    assert plan is not None
    for op in plan["operations"]:
        if op["op"] == "INSERT_PROVENANCE":
            op["values"].update({"run_id": invocation["run_id"], "created_at": invocation["created_at"], "actor": invocation["actor"]})
    plan["event"]["occurred_at"] = invocation["created_at"]
    plan["event"]["creation"]["run_id"] = invocation["run_id"]
    return out


# ---------------------------------------------------------------------------------------------------------------- write-plan semantics
class Store:
    """An in-memory model of the governed writer's constraints: PK on canonical_id, unique slug, unique (brand, identity_key) among live
    identities, unique alias, unique outbox event_id, all inside one 'transaction' that either applies fully or not at all."""

    def __init__(self, identities=None, bindings=None):
        self.identities = {i["canonical_id"]: dict(i) for i in (identities or [])}
        self.keys: dict[tuple[str, str], str] = {}
        self.aliases = {(b["provider"], b["external_id"]): (b["canonical_id"], b["state"]) for b in (bindings or [])}
        self.provenance: dict[str, dict] = {}
        self.events: dict[str, dict] = {}
        self.mappings: list[dict] = []

    def brand_digest(self, brand_id: str) -> str:
        return sha(sorted([i["canonical_id"], i["identity_state"], i["deleted"]] for i in self.identities.values() if i["brand_id"] == brand_id))

    def _violation(self, pre: dict) -> str | None:
        k = pre["kind"]
        if k == "brand_exists":
            return None
        if k == "canonical_id_absent" and pre["canonical_id"] in self.identities:
            return k
        if k == "slug_absent" and any(i.get("slug") == pre["slug"] for i in self.identities.values()):
            return k
        if k == "identity_key_absent" and (pre["brand_id"], pre["identity_key"]) in self.keys:
            return k
        if k == "alias_absent_or_same":
            have = self.aliases.get((pre["provider"], pre["external_id"]))
            if have and have[0] != pre["canonical_id"]:
                return k
        if k == "brand_identity_digest" and self.brand_digest(pre["brand_id"]) != pre["digest"]:
            return k
        return None

    def apply(self, decision: dict) -> str:
        plan = decision["write_plan"]
        cid = decision["identity"]["canonical_model_id"]
        prov = self.provenance.get(cid)
        if prov and prov["decision_fingerprint"] == decision["fingerprints"]["decision"] and prov["identity_key"] == decision["identity"]["identity_key"]:
            return "ALREADY_APPLIED"
        for pre in plan["preconditions"]:
            bad = self._violation(pre)
            if bad:
                return f"STALE:{bad}"
        values = {op["op"]: op for op in plan["operations"]}
        shell = dict(values["INSERT_IDENTITY_SHELL"]["values"])
        shell["deleted"] = False
        self.identities[cid] = shell
        self.keys[(shell["brand_id"], values["RESERVE_CANONICAL_ID"]["values"]["identity_key"])] = cid
        for row in values["INSERT_EXTERNAL_ALIAS"]["rows"]:
            self.aliases[(row["provider"], row["external_id"])] = (cid, row["state"])
        self.provenance[cid] = dict(values["INSERT_PROVENANCE"]["values"])
        self.events.setdefault(plan["event"]["event_id"], plan["event"])
        self.mappings.append(values["PROPOSE_ORIGIN_MAPPING"]["values"])
        return "APPLIED"

    def as_snapshot_parts(self) -> tuple[list[dict], list[dict]]:
        ids = [{"canonical_id": c, "brand_id": r["brand_id"], "name_en": r["name_en"], "slug": r.get("slug", ""),
                "identity_state": r["identity_state"], "deleted": r.get("deleted", False)} for c, r in sorted(self.identities.items())]
        binds = [{"provider": p, "external_id": e, "canonical_id": c, "state": st} for (p, e), (c, st) in sorted(self.aliases.items())]
        return ids, binds


# ---------------------------------------------------------------------------------------------------------------- lifecycle
def transition(lifecycle: dict, frm: list | None, to: list, actor: str) -> dict:
    pairs = [tuple(p) for p in lifecycle["allowed_state_pairs"]]
    if tuple(to) not in pairs:
        return {"allowed": False, "why": "to-pair not allowed"}
    for f in lifecycle["forbidden_transitions"]:
        if frm and frm[0] == f["from"] and to[0] == f["to"]:
            return {"allowed": False, "why": "forbidden"}
    for t in lifecycle["transitions"]:
        from_ok = (t.get("from") == frm) if "from" in t else (frm is not None and frm[0] in t["from_states"])
        to_ok = t["to"][0] == to[0] and (t["to"][1] is None or t["to"][1] == to[1] or t["to"][1] is None)
        if from_ok and to_ok and actor in t["actors"]:
            return {"allowed": True, "transition": t["id"], "proposal": actor in t.get("proposal_for", [])}
    return {"allowed": False, "why": "no transition"}
