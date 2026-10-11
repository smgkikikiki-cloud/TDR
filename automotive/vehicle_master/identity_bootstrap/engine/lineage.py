"""Provider lineage (SPEC §9): maps a subject's identity-change events to codes through policy.lineage.actions."""
from __future__ import annotations


def lineage_findings(subject: dict, snapshot: dict, bindings: dict, live_ids: set[str], actions: dict) -> dict:
    """Return {'codes': [(code, detail)], 'suggest': (canonical_id, code) | None, 'retired_aliases': [old ids]}."""
    me, provider = subject["entity_id"], subject["provider"]
    events = snapshot["lineage"]["events"]
    successors: dict[str, set[str]] = {}
    for e in events:
        successors.setdefault(e["old_id"], set()).add(e["new_id"])

    def on_cycle() -> bool:
        seen, stack = set(), [me]
        while stack:
            for nxt in successors.get(stack.pop(), ()):
                if nxt == me:
                    return True
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return False

    chosen: list[tuple[str, dict]] = []
    if on_cycle():
        chosen.append((actions["cycle"], {}))
    for e in events:
        kind = e["event_type"]
        if e["new_id"] == me:
            olds = [o["old_id"] for o in events if o["new_id"] == me and o["event_type"] == kind]
            owners = sorted({bindings[(provider, o)]["canonical_id"] for o in olds if (provider, o) in bindings})
            if kind == "RENAME":
                act = actions["rename_old_bound" if owners else "rename_old_unbound"]
            elif kind == "MERGE":
                act = actions["merge_old_bound_to_one"] if len(owners) == 1 else \
                    actions["merge_old_bound_to_many"] if len(owners) > 1 else actions["merge_none_bound"]
            else:
                act = actions["split_any_role"]
            chosen.append((act, {"canonical_id": owners[0] if len(owners) == 1 else None, "olds": olds}))
        elif e["old_id"] == me and (kind == "SPLIT" or (me in live_ids and e["new_id"] != me)):
            chosen.append((actions["split_any_role"], {}))

    out = {"codes": [], "suggest": None, "retired_aliases": []}
    for act, d in chosen:
        if act == "HOLD_UNRESOLVED":
            out["codes"].append(("LINEAGE_UNRESOLVED", {}))
        elif act == "HOLD_CONTINUITY":
            out["codes"].append(("LINEAGE_CONTINUITY_EXISTING_IDENTITY", {"canonical_id": d["canonical_id"]}))
            if d["canonical_id"]:
                out["suggest"] = (d["canonical_id"], "LINEAGE_CONTINUITY_EXISTING_IDENTITY")
        elif act == "REVIEW_AMBIGUOUS":
            out["codes"].append(("PROVIDER_LINEAGE_AMBIGUOUS", {}))
        elif act == "PROCEED_WITH_RETIRED_ALIAS":
            out["retired_aliases"] += d.get("olds", [])
    return out
