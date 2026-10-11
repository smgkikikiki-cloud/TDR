"""The decision procedure (SPEC §6-§12). Pure function of (snapshot, policy, registry); no clock, no I/O."""
from __future__ import annotations

from .allocate import allocate, slug_function
from .fingerprint import policy_digest, sha
from .lexical import Lexicon
from .lineage import lineage_findings
from .plan import build_plan

INVERSE = {"SUBJECT_FINER": "SUBJECT_COARSER", "SUBJECT_COARSER": "SUBJECT_FINER"}
ROUTE_RANK = {"HOLD": 0, "REVIEW": 1, "CREATE": 2}
OUTCOME = {"CREATE": "CREATE_IDENTITY", "REVIEW": "IDENTITY_REVIEW", "HOLD": "HOLD"}


class Refusal(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def sid_of(provider: str, entity_id: str) -> str:
    return f"{provider}:{entity_id}"


class _Subject:
    """Per-subject working state."""

    def __init__(self, raw: dict, lex: Lexicon):
        self.raw = raw
        self.sid = sid_of(raw["provider"], raw["entity_id"])
        self.spellings = (raw["brand"]["raw"], *raw["brand"].get("spellings", []))
        self.tokens = lex.tokens(raw["display_name"], self.spellings)
        brand_id = raw["brand"]["brand_id"]
        self.identity_key = f"{brand_id}|{''.join(self.tokens)}" if brand_id and self.tokens else None
        self.fired: dict[str, list[dict]] = {}
        self.activated = True
        self.suggest = None
        self.retired: list[str] = []
        self.excluded: list[dict] = []
        self.remaining: dict[str, list[dict]] = {}
        self.cleared: list[dict] = []
        self.info: list[str] = []
        self.review_fp = ""
        self.evidence = None

    def fire(self, code: str, **detail) -> None:
        self.fired.setdefault(code, []).append(detail)


def _validate(snapshot: dict, policy: dict) -> None:
    if snapshot["policy_version"] != policy["version"]:
        raise Refusal("INPUT_POLICY_VERSION_UNSUPPORTED", str(snapshot["policy_version"]))
    if not snapshot["source_version"]["label"].strip():
        raise Refusal("INPUT_SOURCE_VERSION_MISSING", "empty label")
    seen = set()
    for s in snapshot["subjects"]:
        sid = sid_of(s["provider"], s["entity_id"])
        if sid in seen:
            raise Refusal("INPUT_DUPLICATE_SUBJECT_ID", sid)
        seen.add(sid)
        if "resolution" not in s:
            raise Refusal("INPUT_RESOLUTION_MISSING", sid)
    lin = snapshot["lineage"]
    if lin["declared_identity_change"] and not lin["source_present"]:
        raise Refusal("INPUT_LINEAGE_SOURCE_MISSING", "declared identity change without a machine-readable source")


def decide(snapshot: dict, policy: dict, registry: dict, slugger=None) -> list[dict]:
    _validate(snapshot, policy)
    codes = registry["codes"]
    lex = Lexicon(policy)
    subjects = {}
    for raw in snapshot["subjects"]:
        s = _Subject(raw, lex)
        subjects[s.sid] = s
    order = sorted(subjects)
    identities = snapshot["identities"]
    bindings = {(b["provider"], b["external_id"]): b for b in snapshot["bindings"]}
    live_ids = {s.raw["entity_id"] for s in subjects.values()}
    state_class = policy["relations"]["peer_state_classes"]
    cls_of = {r: c for c, members in policy["relations"]["name_classes"].items() for r in members}

    def peer_class(state) -> str:
        return state_class["legacy" if state is None else state]

    def route(code: str) -> str:
        return codes[code]["route"]

    # ---- G0-G5 per subject ------------------------------------------------------------------------------------------------------
    by_brand: dict[str, list[dict]] = {}
    for i in identities:
        by_brand.setdefault(i["brand_id"], []).append(i)
    compact_cache: dict[tuple, str] = {}

    def compact_of(i: dict, spellings: tuple) -> str:
        k = (i["canonical_id"], spellings)
        if k not in compact_cache:
            compact_cache[k] = "".join(lex.tokens(i["name_en"], spellings))
        return compact_cache[k]

    for sid in order:
        s = subjects[sid]
        raw = s.raw
        outcome = raw["resolution"]["outcome"]
        if outcome != policy["activation"]["required_ir_outcome"]:
            if outcome == policy["activation"]["structural_review_outcome"]:
                s.fire("STRUCTURAL_CONFLICT", via="IR")
            else:
                s.fire("NOT_ACTIVATED", ir_outcome=outcome)
                s.activated = False
                continue
        if raw["identity_status"] not in policy["subject"]["creatable_identity_statuses"]:
            s.fire(policy["subject"]["status_codes"][raw["identity_status"]])
        if lex.raw_shaped(raw["entity_id"], raw["display_name"], s.tokens):
            s.fire("PROVIDER_RAW_NAME")
        if lex.unavailable_name(s.tokens):
            s.fire("NAME_UNSPECIFIED")
        relation = raw["brand"]["relation"]
        if relation not in policy["brand"]["creatable_relations"]:
            s.fire(policy["brand"]["relation_codes"][relation])
        elif not raw["brand"]["brand_id"]:
            s.fire("BRAND_UNKNOWN")
        # G2 state
        bound = bindings.get((raw["provider"], raw["entity_id"]))
        if bound:
            s.fire("IDENTITY_ALREADY_DISCOVERED", canonical_id=bound["canonical_id"], via="binding")
        if s.identity_key:
            mine = "".join(s.tokens)
            for i in by_brand.get(raw["brand"]["brand_id"], ()):
                if i["canonical_id"] == (bound or {}).get("canonical_id") or compact_of(i, s.spellings) != mine:
                    continue
                cls = peer_class(i["identity_state"])
                if cls == "withdrawn":
                    s.fire("IDENTITY_PREVIOUSLY_WITHDRAWN", canonical_id=i["canonical_id"])
                elif cls == "pending":
                    s.fire("IDENTITY_ALREADY_DISCOVERED", canonical_id=i["canonical_id"], via="identity_key")
                    s.suggest = (i["canonical_id"], "IDENTITY_ALREADY_DISCOVERED")
                else:
                    s.fire("DUPLICATE_CANONICAL_SUSPECTED", canonical_id=i["canonical_id"], via="identity_key")
        # G3 lineage
        lin = lineage_findings(raw, snapshot, bindings, live_ids, policy["lineage"]["actions"])
        for code, detail in lin["codes"]:
            s.fire(code, **detail)
        if lin["suggest"]:
            s.suggest = lin["suggest"]
        s.retired += lin["retired_aliases"]
        # G4a relations to TARGET peers
        tables = {"canonical": policy["relations"]["canonical_codes"], "pending": policy["relations"]["pending_codes"], "withdrawn": policy["relations"]["withdrawn_codes"]}
        for r in raw.get("relations", []):
            if r["peer_kind"] != "TARGET":
                continue
            cls = cls_of[r["name_relation"]]
            if cls == "ignored":
                continue
            code = tables[peer_class(r.get("identity_state"))].get(cls)
            if code:
                s.fire(code, canonical_id=r["peer_id"], name_relation=r["name_relation"])
        # G5 shape
        for code in sorted(lex.shape(raw["display_name"], s.tokens)):
            s.fire(code)

    # ---- G4b subject <-> subject ------------------------------------------------------------------------------------------------
    pairs: dict[tuple[str, str], str] = {}
    for sid in order:
        s = subjects[sid]
        for r in s.raw.get("relations", []):
            if r["peer_kind"] != "SUBJECT":
                continue
            pid = sid_of(r.get("peer_provider", s.raw["provider"]), r["peer_id"])
            if pid not in subjects:
                continue
            for a, b, rel in ((sid, pid, r["name_relation"]), (pid, sid, INVERSE.get(r["name_relation"], r["name_relation"]))):
                if pairs.setdefault((a, b), rel) != rel:
                    raise Refusal("INPUT_SCHEMA_INVALID", f"inconsistent relation between {a} and {b}")
    junk = set(policy["batch"]["ignore_peers_holding"])
    gate_codes = {sid: set(subjects[sid].fired) for sid in order}
    edges: dict[str, set[str]] = {sid: set() for sid in order}
    cross_dups: list[tuple[str, str]] = []
    for (a, b), rel in sorted(pairs.items()):
        cls = cls_of[rel]
        if cls == "ignored" or not subjects[a].activated or not subjects[b].activated:
            continue
        edges[a].add(b); edges[b].add(a)
        if (gate_codes[a] | gate_codes[b]) & junk:
            continue
        same = subjects[a].raw["provider"] == subjects[b].raw["provider"]
        rules = policy["batch"]["same_provider" if same else "cross_provider"]
        if cls == "duplicate":
            if same:
                for c in rules["duplicate"]:
                    subjects[a].fire(c, peer=b, name_relation=rel)
            else:
                cross_dups.append((a, b))
        elif cls in ("finer", "sibling"):
            for c in rules[cls]:
                subjects[a].fire(c, peer=b, name_relation=rel)

    # ---- G6 evidence --------------------------------------------------------------------------------------------------------------
    ev_cfg = policy["evidence"]
    tiers = ev_cfg["kind_tiers"]
    for sid in order:
        s = subjects[sid]
        if not s.activated:
            continue
        valid = [e for e in s.raw.get("evidence", []) if e["kind"] in tiers and e["ref"].strip()]
        prov = ev_cfg["providers"].get(s.raw["provider"])
        base_ok = bool(prov and prov["may_create"] and any(e["kind"] == prov["base_kind"] for e in valid))
        tier = max((tiers[e["kind"]] for e in valid), default=None)
        s.evidence = {"valid": valid, "tier": tier}
        if not any(route(c) == "HOLD" for c in s.fired):
            if not base_ok or tier is None or tier < ev_cfg["required_tier"]["create_clean"]:
                s.fire("INSUFFICIENT_IDENTITY_EVIDENCE")

    # ---- review fingerprints and clearing ---------------------------------------------------------------------------------------
    directives = {(d["provider"], d["entity_id"], d["review_fingerprint"]): d for d in snapshot.get("admin_directives", [])}
    for sid in order:
        s = subjects[sid]
        rel_sig = sorted([("TARGET", r["peer_id"], r["name_relation"], peer_class(r.get("identity_state")))
                          for r in s.raw.get("relations", []) if r["peer_kind"] == "TARGET" and cls_of[r["name_relation"]] != "ignored"]
                         + [("SUBJECT", b, rel, "subject") for (a, b), rel in pairs.items() if a == sid and cls_of[rel] != "ignored"])
        s.review_fp = sha({"p": s.raw["provider"], "e": s.raw["entity_id"], "b": s.raw["brand"]["brand_id"], "k": s.identity_key,
                           "codes": sorted(c for c in s.fired if route(c) != "NONE"), "rel": rel_sig})
        directive = directives.get((s.raw["provider"], s.raw["entity_id"], s.review_fp))
        remaining = {c: list(d) for c, d in s.fired.items()}
        if directive and directive["action"] == "DO_NOT_CREATE" and s.activated:
            s.remaining = {"ADMIN_DECLINED": [{}]}
            continue
        if s.evidence:
            sc = ev_cfg["soft_clear"]
            if any(tiers[e["kind"]] >= sc["min_tier"] and sc["required_attestation"] in e.get("attests", []) for e in s.evidence["valid"]):
                for c in sorted(remaining):
                    if codes[c]["clearable"] in ("evidence", "evidence_or_admin") and route(c) in ("HOLD", "REVIEW"):
                        del remaining[c]
                        s.cleared.append({"code": c, "cleared_by": "evidence"})
                if s.cleared:
                    s.info.append("FLAG_CLEARED_BY_EVIDENCE")
        if directive and directive["action"] == "CREATE_IDENTITY":
            by_admin = False
            for c in sorted(remaining):
                if codes[c]["clearable"] in ("admin", "evidence_or_admin") and route(c) in ("HOLD", "REVIEW"):
                    for d in s.fired[c]:
                        if "canonical_id" in d:
                            s.excluded.append({"canonical_id": d["canonical_id"], "name_relation": d.get("name_relation", "")})
                    del remaining[c]
                    s.cleared.append({"code": c, "cleared_by": "admin"})
                    by_admin = True
            if by_admin:
                s.info.append("ADMIN_STRUCTURE_DECISION_APPLIED")
            if any(route(c) in ("HOLD", "REVIEW") for c in remaining):
                s.info.append("ADMIN_DECISION_CANNOT_CLEAR_HARD_FLAG")
        s.remaining = remaining

    # ---- coalescing, allocation, collisions ---------------------------------------------------------------------------------------
    def creatable(sid: str) -> bool:
        return not any(route(c) in ("HOLD", "REVIEW") for c in subjects[sid].remaining)

    parent = {sid: sid for sid in order}

    def find(x: str) -> str:
        while parent[x] != x:
            x = parent[x]
        return x

    for a, b in cross_dups:
        if creatable(a) and creatable(b):
            parent[find(a)] = find(b)
    groups: dict[str, list[str]] = {}
    for sid in order:
        if creatable(sid):
            groups.setdefault(find(sid), []).append(sid)
    rank = {p: i for i, p in enumerate(policy["batch"]["provider_priority"])}
    reps: dict[str, list[str]] = {}
    for members in groups.values():
        members.sort(key=lambda m: (rank.get(subjects[m].raw["provider"], len(rank)), subjects[m].raw["provider"], subjects[m].raw["entity_id"]))
        reps[members[0]] = members
        for other in members[1:]:
            subjects[other].remaining = {"IDENTITY_COALESCED": [{"rep": members[0]}]}
        if len(members) > 1:
            subjects[members[0]].info.append("MULTI_PROVIDER_CORROBORATION")

    slugger = slugger or slug_function(policy)
    allocations: dict[str, dict] = {}
    for rep in sorted(reps):
        s = subjects[rep]
        name = lex.canonical_name(s.raw["display_name"], s.spellings)
        a = allocate(s.raw["brand"]["brand_id"], name, identities, policy, slugger)
        if not a["ok"]:
            s.remaining["NAME_UNSPECIFIED"] = [{}]
            continue
        a["name"] = name
        allocations[rep] = a
        if a["collision"]:
            s.remaining["CANONICAL_ID_COLLISION"] = [{"canonical_id": a["canonical_id"], "taken_by": a["taken_by"]}]
    owners: dict[str, list[str]] = {}
    for rep, a in allocations.items():
        for k in (a["canonical_id"], a["slug"], subjects[rep].identity_key):
            owners.setdefault(k, []).append(rep)
    for who in owners.values():
        if len(who) > 1:
            for rep in who:
                subjects[rep].remaining["CANONICAL_ID_COLLISION"] = [{"canonical_id": allocations[rep]["canonical_id"], "batch_peers": sorted(who)}]

    # ---- records ----------------------------------------------------------------------------------------------------------------------
    components = _components(edges)
    digest = policy_digest(policy)
    return [_record(subjects[sid], subjects, reps, allocations, components, snapshot, policy, registry, digest) for sid in order]


def _components(edges: dict[str, set[str]]) -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}
    for start in sorted(edges):
        if start in seen:
            continue
        comp, stack = set(), [start]
        while stack:
            x = stack.pop()
            if x not in comp:
                comp.add(x)
                stack += [y for y in edges[x] if y not in comp]
        for m in comp:
            seen[m] = sorted(comp) if len(comp) > 1 else []
    return seen


def _record(s: _Subject, subjects: dict, reps: dict, allocations: dict, components: dict, snapshot: dict, policy: dict, registry: dict, digest: str) -> dict:
    codes = registry["codes"]
    routes = {codes[c]["route"] for c in s.remaining if codes[c]["route"] in ROUTE_RANK}
    win = min(routes, key=ROUTE_RANK.get) if routes else "CREATE"
    remaining = dict(s.remaining)
    if win == "CREATE":
        remaining["NEW_IDENTITY_CONFIRMED"] = [{}]
    outcome = OUTCOME[win]
    all_codes = sorted(set(remaining) | set(s.info), key=lambda c: (codes[c]["primary_rank"], c))
    primary = min((c for c in remaining if codes[c]["route"] == win), key=lambda c: (codes[c]["primary_rank"], c))

    members = [subjects[m] for m in reps.get(s.sid, [s.sid])]
    refs = sorted({e["ref"] for m in members if m.evidence for e in m.evidence["valid"]})
    kinds = sorted({e["kind"] for m in members if m.evidence for e in m.evidence["valid"]})
    tier = s.evidence["tier"] if s.evidence else None
    if len(members) > 1:
        corroboration = policy["evidence"]["corroboration_kind"]
        kinds = sorted(set(kinds) | {corroboration})
        tier = max(tier or 0, policy["evidence"]["kind_tiers"][corroboration])
    basis = {"tier": tier, "kinds": kinds, "refs": refs, "cleared_flags": s.cleared}
    creator = ("admin" if "ADMIN_STRUCTURE_DECISION_APPLIED" in s.info else "machine") if outcome == "CREATE_IDENTITY" else None

    pointed = sorted({d["canonical_id"] for c in remaining for d in remaining[c] if d.get("canonical_id")})
    suggested = None
    if s.suggest and outcome == "HOLD":
        suggested = {"canonical_id": s.suggest[0], "provider": s.raw["provider"], "external_id": s.raw["entity_id"], "reason": s.suggest[1]}

    pri = policy["priority"]
    units = s.raw.get("units")
    band = pri["unknown_units_band"] if units is None else [b["band"] for b in pri["bands"] if units >= b["min_units"]][-1]
    silent = outcome == "HOLD" and primary in pri["silent_hold_codes"]
    queue = None if outcome == "CREATE_IDENTITY" or silent else pri["queues"][outcome if outcome != "IDENTITY_REVIEW" else "IDENTITY_REVIEW"]
    review = {"required": outcome == "IDENTITY_REVIEW", "queue": queue, "priority_band": band,
              "alert": "HIGH_VOLUME_UNRESOLVED" if (queue and band in pri["alert_bands"]) else None}

    identity = None
    if outcome == "CREATE_IDENTITY":
        a = allocations[s.sid]
        init = policy["writes"]["initial_state"]
        identity = {"canonical_model_id": a["canonical_id"], "brand_id": s.raw["brand"]["brand_id"], "canonical_name": a["name"], "slug": a["slug"],
                    "identity_key": s.identity_key, "identity_state": init["identity_state"], "enrichment_state": init["enrichment_state"],
                    "allocation": {"method": "BRAND_DOT_SLUG_OF_CANONICAL_NAME", "local_segment": a["local_segment"], "collision": False}}
    fingerprints = {
        "decision": sha({"c": 1, "policy": digest, "review": s.review_fp, "outcome": outcome, "codes": all_codes,
                         "basis": {"tier": tier, "kinds": kinds, "cleared": s.cleared}, "id": identity and identity["canonical_model_id"]}),
        "review": s.review_fp, "idempotency_key": sha({"idem": [s.raw["provider"], s.raw["entity_id"]]}), "identity_key": s.identity_key}
    record = {"record_type": "decision", "contract_version": 1, "policy": {"version": policy["version"], "digest": digest},
              "provider": s.raw["provider"], "source_version": snapshot["source_version"]["label"],
              "subject": {"provider": s.raw["provider"], "entity_id": s.raw["entity_id"], "display_name": s.raw["display_name"]},
              "outcome": outcome, "primary_reason": primary, "reason_codes": all_codes, "evidence_basis": basis, "creator_type": creator,
              "identity": identity, "existing_identity": pointed[0] if len(pointed) == 1 else None, "suggested_binding": suggested,
              "batch_group": components.get(s.sid, []), "review": review, "write_plan": None, "fingerprints": fingerprints}
    if outcome == "CREATE_IDENTITY":
        record["write_plan"] = build_plan(record, s.raw, [m.raw for m in members], s.retired, s.excluded, snapshot, policy)
    return record
