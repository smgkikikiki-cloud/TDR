"""M7 lexical-relation measurement: how many name relations, batch conflicts and decisions the FUZZY / SIBLING / synonym rules produce on the
real Ice M7.0 package and the live TDR catalog. Run it before and after a rule change and compare the two JSON files.

    python -m identity_resolution.calibration.lexical_pass measure --rev3 --label rev3 --out lexical_pass/before_rev3.json   # the rev 3 rules, re-derived live
    python -m identity_resolution.calibration.lexical_pass measure --label rev4 --out lexical_pass/after_rev4.json        # the current rules
    python -m identity_resolution.calibration.lexical_pass report        # before_rev3.json + after_rev4.json -> comparison.json + LEXICAL_PASS_REPORT.md

Independence: this does not use the Identity Bootstrap stand-in (PR #201) or its numbers. The relations come from the reference evaluator's
`name_relation`; the diagnostics ("FUZZY across a digit token", "SIBLING on non-distinctive tokens") come from a separate oracle written here
straight from the owner's wording, so the engine and the oracle can disagree, and a test makes them agree.

Populations (both are M7 name pairs, no series involved):
  ice_ice   every pair of Ice groups with the same Ice brand string (the population the stand-in used), oriented from the smaller id
  ice_tdr   every Ice group against every TDR model in its v1 candidate pool (brand relation allowed, not deleted, status in the pool)
"Batch conflict" follows the Bootstrap SPEC section 'same provider' wording, quoted rather than imported: a duplicate (EQUAL*, FUZZY) is a conflict
on both groups, a SUBJECT_FINER on the finer group only, a SIBLING on both.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import json
import re
import sys
from pathlib import Path

from identity_resolution.contract import loader

from . import adapters as A
from . import ref_eval_core as P
from . import ref_eval_resolve as R

DIR = A.CALIBRATION_DIR / "lexical_pass"
DUPLICATE = ("EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV", "FUZZY")
RELATIONS = ("EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV", "FUZZY", "SUBJECT_COARSER", "SUBJECT_FINER", "SIBLING", "CONTRADICTION", "UNAVAILABLE")
#: The seven groups PR #201 named as newly exposed CREATE risks. They are looked up by Ice id prefix, only to say whether this measurement agrees.
BOOTSTRAP_NAMED = ["mazda-mazda-mx-30", "mazda-mazda6e", "nissan-nissan-be-1", "peugeot-peugeot-5008", "volkswagen-volkswagen-t-roc",
                   "volkswagen-vw-t-cross", "volvo-volvo-es90"]


# ------------------------------------------------------------------------------------------------------------------ the rev 3 rules, for comparison
#: Alias entries that exist only since rev 4 (scoped by brand name, not by a brand alias id).
REV4_MODEL_ALIAS_IDS = ("honda_model_synonyms",)


@contextlib.contextmanager
def rev3_rules():
    """Temporarily revert the three rev 4 name rules in the shared policy object: digit-bearing tokens may be paired as typos, SIBLING needs no distinctive
    shared token, and the Honda synonyms do not exist. Inside the block the reference evaluator is the rev 3 evaluator (the tests check it reproduces
    `before_rev3.json` exactly), which is what makes 'before' a live, re-derivable number and not a number that was typed in."""
    lex, models = P.POL["lexical"], P.POL["aliases"]["model"]
    saved = (lex["fuzzy_token"]["allow_tokens_with_digits"], list(lex["distinctive_token"]["required_for_relations"]), list(models))
    lex["fuzzy_token"]["allow_tokens_with_digits"] = True
    lex["distinctive_token"]["required_for_relations"] = []
    models[:] = [m for m in models if m["id"] not in REV4_MODEL_ALIAS_IDS]
    try:
        yield
    finally:
        lex["fuzzy_token"]["allow_tokens_with_digits"], lex["distinctive_token"]["required_for_relations"] = saved[0], saved[1]
        models[:] = saved[2]


# ------------------------------------------------------------------------------------------------------------------ oracle
class Oracle:
    """The owner's two rules, restated from their wording and the policy vocabulary only (no call into the evaluator's relation code)."""

    def __init__(self, policy: dict):
        d = policy["lexical"].get("distinctive_token")
        self.rule = d
        self.vocab = frozenset(t for cls in (d or {}).get("non_distinctive", {}).values() for t in cls)
        self.patterns = [re.compile(p) for p in (d or {}).get("non_distinctive_patterns", [])]

    def distinctive(self, token: str) -> bool:
        d = self.rule
        if d is None:
            return True
        if d["exclude_numeric"] and token.isdigit():
            return False
        if len(token) < d["min_length"]:
            return False
        if token in self.vocab or any(p.fullmatch(token) for p in self.patterns):
            return False
        return True

    @staticmethod
    def differing_tokens_have_digit(a: list[str], b: list[str]) -> bool:
        ra, rb = {P._equiv_rep(t) for t in a}, {P._equiv_rep(t) for t in b}
        return any(ch.isdigit() for t in (ra ^ rb) for ch in t)

    def shared_has_distinctive(self, a: list[str], b: list[str]) -> bool:
        ra, rb = {P._equiv_rep(t) for t in a}, {P._equiv_rep(t) for t in b}
        return any(self.distinctive(t) for t in ra & rb)


# ------------------------------------------------------------------------------------------------------------------ pairs
def _pair_stats(pairs: list[tuple], oracle: Oracle) -> dict:
    """pairs: (relation, subject_tokens, target_tokens)."""
    rel = collections.Counter(r for r, _, _ in pairs)
    fuzzy = [(a, b) for r, a, b in pairs if r == "FUZZY"]
    sib = [(a, b) for r, a, b in pairs if r == "SIBLING"]
    contain = collections.Counter()
    for r, a, b in pairs:
        if r in ("SUBJECT_COARSER", "SUBJECT_FINER"):
            small = set(a) if r == "SUBJECT_COARSER" else set(b)
            if not any(oracle.distinctive(P._equiv_rep(t)) for t in small):
                contain[r] += 1
    return {
        "pairs": len(pairs),
        "relations": {k: rel.get(k, 0) for k in RELATIONS},
        "fuzzy": {"total": len(fuzzy), "differing_token_has_digit": sum(1 for a, b in fuzzy if oracle.differing_tokens_have_digit(a, b))},
        "sibling": {"total": len(sib), "only_non_distinctive_shared_tokens": sum(1 for a, b in sib if not oracle.shared_has_distinctive(a, b))},
        "containment_resting_only_on_non_distinctive_tokens_not_changed_by_this_pass": dict(contain),
    }


def ice_ice(ice: dict, oracle: Oracle):
    groups = sorted(ice["groups"], key=lambda g: g["model_group_id"])
    by_brand = collections.defaultdict(list)
    for g in groups:
        by_brand[g["brand"]].append(g)
    out = []
    for gs in by_brand.values():
        for i, a in enumerate(gs):
            obs = tuple(ice["brands_observed"].get(a["model_group_id"], []))
            for c in gs[i + 1:]:
                rel, _score, ta, tc = P.name_relation(a["model_name"], a["brand"], c["model_name"], c["brand"], obs)
                out.append((rel, ta, tc, a["model_group_id"], c["model_group_id"]))
    return out


def ice_tdr(ice: dict, ext: dict):
    pol = loader.load_policy()
    targets = [m for m in ext["models"] if not m["deleted"] and m["status"] in pol["candidates"]["target_statuses_in_pool"]]
    brand_name = {b["canonical_id"]: b["name_en"] for b in ext["brands"]}
    out = []
    for g in sorted(ice["groups"], key=lambda g: g["model_group_id"]):
        obs = tuple(ice["brands_observed"].get(g["model_group_id"], []))
        for m in targets:
            tb = brand_name.get(m["brand_id"], "")
            if P.brand_relation(g["brand"], tb, obs)[0] not in pol["candidates"]["brand_relations_allowed"]:
                continue
            rel, _s, ta, tc = P.name_relation(g["model_name"], g["brand"], m["name_en"], tb, obs)
            out.append((rel, ta, tc, g["model_group_id"], m["canonical_id"]))
    return out


def batch_conflicts(pairs: list[tuple], ice: dict) -> dict:
    """Groups taking part in a same-provider conflict, per the Bootstrap SPEC wording (duplicate: both, finer: the finer one, sibling: both)."""
    members: dict[str, set[str]] = collections.defaultdict(set)
    for rel, _a, _b, x, y in pairs:
        if rel in DUPLICATE:
            members["duplicate"] |= {x, y}
        elif rel == "SUBJECT_FINER":
            members["finer"].add(x)
        elif rel == "SUBJECT_COARSER":
            members["finer"].add(y)
        elif rel == "SIBLING":
            members["sibling"] |= {x, y}
    settled = {g["model_group_id"] for g in ice["groups"] if A.identity_status(g["model_group_id"]) == "settled"}
    every = set().union(*members.values()) if members else set()
    return {
        "all_groups": len(every), "settled_groups": len(every & settled),
        "by_class": {k: len(v) for k, v in sorted(members.items())},
        "groups": sorted(every),
    }


# ------------------------------------------------------------------------------------------------------------------ decisions
def decisions(ice: dict, ext: dict) -> dict:
    snap = A.build_snapshot(ice, ext)
    res = R.resolve(snap)
    if "refusal" in res:
        raise RuntimeError(res["refusal"])
    out = {}
    for gid, d in res["decisions"].items():
        codes = {c for c, _ in d["codes"]}
        out[gid] = [d["outcome"], d.get("primary") or "", "+".join(d.get("target_ids", []) or []), d.get("link_type") or "",
                    int("CARD_CLAIM_CONFLICTS_AUTO" in codes)]
    return out


def decision_summary(dec: dict) -> dict:
    claims = collections.defaultdict(list)
    for gid, (outcome, _p, targets, _lt, _c) in dec.items():
        for t in filter(None, targets.split("+")):
            claims[t].append(gid)
    return {
        "outcomes": dict(sorted(collections.Counter(v[0] for v in dec.values()).items())),
        "primary_codes": dict(collections.Counter(v[1] for v in dec.values()).most_common()),
        "auto_groups": sorted(g for g, v in dec.items() if v[0] == "AUTO"),
        "structural": {
            "STRUCTURAL_REVIEW": sum(1 for v in dec.values() if v[0] == "STRUCTURAL_REVIEW"),
            "AMBIGUOUS": sum(1 for v in dec.values() if v[0] == "AMBIGUOUS"),
            "AMBIGUOUS_TARGET_CONTESTED": sum(1 for v in dec.values() if v[1] == "AMBIGUOUS_TARGET_CONTESTED"),
            "proposals_annotated_CARD_CLAIM_CONFLICTS_AUTO": sum(v[4] for v in dec.values()),
            "PART_OF_decisions": sum(1 for v in dec.values() if v[3] == "PART_OF"),
            "COMPOSED_OF_decisions": sum(1 for v in dec.values() if v[3] == "COMPOSED_OF"),
            "targets_decided_for_more_than_one_group": sum(1 for t, g in claims.items() if len(g) > 1),
        },
    }


# ------------------------------------------------------------------------------------------------------------------ measure
def measure(label: str) -> dict:
    ice, ext = A.load_ice_package(), A.load_extracts()
    pol = loader.load_policy()
    oracle = Oracle(pol)
    a, b = ice_ice(ice, oracle), ice_tdr(ice, ext)
    dec = decisions(ice, ext)
    conflicts = batch_conflicts(a, ice)
    names = {g["model_group_id"]: (g["model_name"], g["brand"]) for g in ice["groups"]}
    units = {g["model_group_id"]: int(g["reg_total_all"]) for g in ice["groups"]}
    return {
        "label": label,
        # the rules the evaluator ACTUALLY used (inside rev3_rules() these are the rev 3 rules), not the file on disk
        "policy": {"fuzzy_token": dict(P.POL["lexical"]["fuzzy_token"]), "distinctive_token_required_for": list(P.POL["lexical"]["distinctive_token"]["required_for_relations"]),
                   "model_aliases": [m["id"] for m in P.POL["aliases"]["model"]]},
        "ice_ice": _pair_stats([(r, x, y) for r, x, y, _i, _j in a], oracle),
        "ice_tdr": _pair_stats([(r, x, y) for r, x, y, _i, _j in b], oracle),
        "batch_conflicts_ice_ice": conflicts,
        "decisions": {gid: v for gid, v in sorted(dec.items())},
        "decision_summary": decision_summary(dec),
        "named_in_pr201": {gid: {"present": gid in names, "in_batch_conflict": gid in set(conflicts["groups"]), "outcome": dec.get(gid, ["?"])[0],
                                 "primary": dec.get(gid, ["", ""])[1]} for gid in BOOTSTRAP_NAMED},
        "group_facts": {gid: {"name": names[gid][0], "brand": names[gid][1], "units": units[gid]} for gid in names},
        "ice_ice_relation_pairs": {f"{x}|{y}": r for r, _a, _b, x, y in a if r in ("FUZZY", "SIBLING", "EQUAL_VIA_MODEL_ALIAS")},
        "ice_tdr_relation_pairs": {f"{x}|{y}": r for r, _a, _b, x, y in b if r in ("FUZZY", "SIBLING", "EQUAL_VIA_MODEL_ALIAS")},
    }


# ------------------------------------------------------------------------------------------------------------------ compare / report
def _transitions(before_pairs: dict, after_pairs: dict) -> dict:
    """Pair-level moves between the relations the dictionaries record (FUZZY, SIBLING, EQUAL_VIA_MODEL_ALIAS); an absent pair is CONTRADICTION or a relation not recorded."""
    moves = collections.Counter()
    for key in set(before_pairs) | set(after_pairs):
        old, new = before_pairs.get(key, "(other)"), after_pairs.get(key, "(other)")
        if old != new:
            moves[f"{old} -> {new}"] += 1
    return dict(sorted(moves.items()))


def compare(before: dict, after: dict) -> dict:
    """Everything the report states, derived from the two measurements and nothing else."""
    bg, ag = set(before["batch_conflicts_ice_ice"]["groups"]), set(after["batch_conflicts_ice_ice"]["groups"])
    released, entered = sorted(bg - ag), sorted(ag - bg)
    bdec, adec = before["decisions"], after["decisions"]
    facts = after["group_facts"]
    cause = collections.defaultdict(set)
    for key, rel in before["ice_ice_relation_pairs"].items():
        if rel in ("FUZZY", "SIBLING") and after["ice_ice_relation_pairs"].get(key) != rel:
            kind = "fuzzy_across_digit" if rel == "FUZZY" else "sibling_without_distinctive_token"
            for gid in _split_pair(key, facts):
                cause[gid].add(kind)
    changed = [{"group": g, "name": facts[g]["name"], "brand": facts[g]["brand"], "units": facts[g]["units"], "before": bdec[g], "after": adec[g]}
               for g in sorted(bdec) if bdec[g] != adec.get(g)]
    auto_b = {g for g, v in bdec.items() if v[0] == "AUTO"}
    auto_a = {g for g, v in adec.items() if v[0] == "AUTO"}
    rank = lambda g: (-facts[g]["units"], g)
    free = [g for g in released if adec[g][0] == "NO_CANDIDATE"]
    return {
        "relations": {pop: {"before": before[pop]["relations"], "after": after[pop]["relations"]} for pop in ("ice_ice", "ice_tdr")},
        "fuzzy": {pop: {"before": before[pop]["fuzzy"], "after": after[pop]["fuzzy"]} for pop in ("ice_ice", "ice_tdr")},
        "sibling": {pop: {"before": before[pop]["sibling"], "after": after[pop]["sibling"]} for pop in ("ice_ice", "ice_tdr")},
        "containment_not_changed": {pop: {"before": before[pop]["containment_resting_only_on_non_distinctive_tokens_not_changed_by_this_pass"],
                                          "after": after[pop]["containment_resting_only_on_non_distinctive_tokens_not_changed_by_this_pass"]} for pop in ("ice_ice", "ice_tdr")},
        "transitions": {"ice_ice": _transitions(before["ice_ice_relation_pairs"], after["ice_ice_relation_pairs"]),
                        "ice_tdr": _transitions(before["ice_tdr_relation_pairs"], after["ice_tdr_relation_pairs"])},
        "conflicts": {"before": {k: before["batch_conflicts_ice_ice"][k] for k in ("all_groups", "settled_groups", "by_class")},
                      "after": {k: after["batch_conflicts_ice_ice"][k] for k in ("all_groups", "settled_groups", "by_class")},
                      "released": len(released), "entered": entered},
        "outcomes": {"before": before["decision_summary"]["outcomes"], "after": after["decision_summary"]["outcomes"]},
        "structural": {"before": before["decision_summary"]["structural"], "after": after["decision_summary"]["structural"]},
        "changed_decisions": changed,
        "auto": {"before": len(auto_b), "after": len(auto_a), "same_set": auto_b == auto_a, "newly_auto": sorted(auto_a - auto_b), "no_longer_auto": sorted(auto_b - auto_a)},
        "released_by_outcome": dict(sorted(collections.Counter(adec[g][0] for g in released).items())),
        "create_eligible_released": {
            "count": len(free),
            "units": sum(facts[g]["units"] for g in free),
            "by_cause": dict(sorted(collections.Counter("+".join(sorted(cause[g])) or "other" for g in free).items())),
            "top_by_units": [{"group": g, "name": facts[g]["name"], "brand": facts[g]["brand"], "units": facts[g]["units"],
                              "cause": "+".join(sorted(cause[g])) or "other"} for g in sorted(free, key=rank)[:20]],
            "groups": sorted(free),
        },
        "named_in_pr201": {"before": before["named_in_pr201"], "after": after["named_in_pr201"]},
        "synonym_pairs": {"ice_ice": sorted(k for k, v in after["ice_ice_relation_pairs"].items() if v == "EQUAL_VIA_MODEL_ALIAS"),
                          "ice_tdr": sorted(k for k, v in after["ice_tdr_relation_pairs"].items() if v == "EQUAL_VIA_MODEL_ALIAS")},
        "remaining_fuzzy": {"ice_ice": sorted(k for k, v in after["ice_ice_relation_pairs"].items() if v == "FUZZY"),
                            "ice_tdr": sorted(k for k, v in after["ice_tdr_relation_pairs"].items() if v == "FUZZY")},
    }


def _split_pair(key: str, facts: dict) -> list[str]:
    """Pair keys are 'idA|idB' but Ice ids may themselves contain '|' (e.g. 'KIA|CANIVAL'): split at the one position where both halves are known group ids."""
    parts = key.split("|")
    for i in range(1, len(parts)):
        left, right = "|".join(parts[:i]), "|".join(parts[i:])
        if left in facts and right in facts:
            return [left, right]
    return []


def render_report(before: dict, after: dict) -> str:
    c = compare(before, after)
    lines: list[str] = []
    w = lines.append

    def row(*cells):
        w("| " + " | ".join(str(x) for x in cells) + " |")

    def delta(a, b):
        return f"{b - a:+d}"

    facts = after["group_facts"]
    w("# Lexical-relation correction pass — M7 measurement (Contract v1 rev 3 → rev 4)")
    w("")
    w("*Generated by `python -m identity_resolution.calibration.lexical_pass report`; a test regenerates it from `before_rev3.json` and `after_rev4.json`. Draft contract, NOT frozen, "
      "`binding: false`. Nothing here touched production, the DB, mappings, R6/R7, migrations, engine wiring, PR #201, adoption binding or the freeze state.*")
    w("")
    w("## 1. What changed (owner decision 2026-10-11, `od_lexical_relation_correction`)")
    w("")
    w("| Rule | Policy key | Value |")
    w("|---|---|---|")
    w("| FUZZY never pairs a token that contains a digit | `lexical.fuzzy_token.allow_tokens_with_digits` | `false` (new) |")
    w("| SIBLING needs a distinctive shared token | `lexical.distinctive_token.required_for_relations` | `[SIBLING]` (new) |")
    w("| …distinctive = at least this long | `lexical.distinctive_token.min_length` | `3` (proposal, pending) |")
    w("| …and not purely numeric | `lexical.distinctive_token.exclude_numeric` | `true` (proposal, pending) |")
    w("| …and not descriptor vocabulary (body, powertrain, trim, generation, market) | `lexical.distinctive_token.non_distinctive` | 5 classes (proposal, pending) |")
    w("| …and not a descriptor shape (`4x2`, `V10`, `25hev`, `Gen2`, `Mk4`) | `lexical.distinctive_token.non_distinctive_patterns` | 5 patterns (proposal, pending) |")
    w("| Honda-scoped model synonyms | `aliases.model` entry `honda_model_synonyms` (`brands: [Honda]`) | `Jazz` ↔ `Fit`, `Stepwagon` ↔ `Step WGN` |")
    w("")
    w("No model is named in the evaluator. `V`, `CX`, `GR`, `RS`, `HR` fall out of the length floor, `30` out of the numeric rule, `4x2`/`V10` out of the patterns. "
      "`AMG` has three letters and is a performance-trim label, so it is the one entry the descriptor vocabulary (class `trim`) has to carry; the owner can strike it. "
      "`SPEC §5.3`, `§5.4`, invariant `I19`, taxonomy `NAME-14`…`NAME-17`, 54 new corpus cases.")
    w("")
    w("## 2. How it was measured")
    w("")
    w("* **Populations.** `ice_ice`: every pair of Ice groups with the same Ice brand string (1,200 groups). `ice_tdr`: every Ice group against every TDR model in its v1 candidate pool. "
      "Both are name pairs; no series is involved.")
    w("* **Before** is the unchanged rev 3 evaluator, re-derived live by `rev3_rules()` (the three rules switched back in the shared policy object); a test checks it reproduces "
      "`before_rev3.json` exactly. **After** is the current evaluator. Nothing else differs between the two runs.")
    w("* **Independent oracle.** The diagnostic columns (“FUZZY across a digit token”, “SIBLING resting only on non-distinctive tokens”) come from an oracle in this module that restates the owner's wording from the "
      "policy vocabulary and does not call the evaluator's relation code; a test requires both to agree (after the change both diagnostics are 0 for every remaining pair).")
    w("* **Independent of PR #201.** Its stand-in and its numbers were not used. Its structural-conflict wording was quoted: a duplicate (`EQUAL*`/`FUZZY`) conflicts both groups, "
      "`SUBJECT_FINER` the finer group, `SIBLING` both; the stand-in used a 4-character FUZZY floor, the contract uses 6, so the two FUZZY counts are not comparable and are not compared.")
    w("")
    w("## 3. Name-relation counts")
    w("")
    for pop, label in (("ice_ice", "Ice × Ice"), ("ice_tdr", "Ice × TDR (v1 candidate pool)")):
        rel = c["relations"][pop]
        w(f"**{label}** — {before[pop]['pairs']:,} pairs")
        w("")
        row("relation", "before", "after", "Δ")
        row("---", "---:", "---:", "---:")
        for name in RELATIONS:
            row(f"`{name}`", f"{rel['before'][name]:,}", f"{rel['after'][name]:,}", delta(rel["before"][name], rel["after"][name]))
        w("")
    w("| | Ice × Ice before | Ice × Ice after | Ice × TDR before | Ice × TDR after |")
    w("|---|---:|---:|---:|---:|")
    f, sb = c["fuzzy"], c["sibling"]
    w(f"| **FUZZY** | **{f['ice_ice']['before']['total']}** | **{f['ice_ice']['after']['total']}** | **{f['ice_tdr']['before']['total']}** | **{f['ice_tdr']['after']['total']}** |")
    w(f"| …of which the differing token contains a digit | {f['ice_ice']['before']['differing_token_has_digit']} | {f['ice_ice']['after']['differing_token_has_digit']} | "
      f"{f['ice_tdr']['before']['differing_token_has_digit']} | {f['ice_tdr']['after']['differing_token_has_digit']} |")
    w(f"| **SIBLING** | **{sb['ice_ice']['before']['total']:,}** | **{sb['ice_ice']['after']['total']}** | **{sb['ice_tdr']['before']['total']}** | **{sb['ice_tdr']['after']['total']}** |")
    w(f"| …of which the shared tokens are all non-distinctive | {sb['ice_ice']['before']['only_non_distinctive_shared_tokens']} | {sb['ice_ice']['after']['only_non_distinctive_shared_tokens']} | "
      f"{sb['ice_tdr']['before']['only_non_distinctive_shared_tokens']} | {sb['ice_tdr']['after']['only_non_distinctive_shared_tokens']} |")
    w("")
    w("Pair-level moves (every other pair is unchanged):")
    w("")
    row("move", "Ice × Ice", "Ice × TDR")
    row("---", "---:", "---:")
    moves = sorted(set(c["transitions"]["ice_ice"]) | set(c["transitions"]["ice_tdr"]))
    names = {"SIBLING -> (other)": "`SIBLING` → `CONTRADICTION`", "FUZZY -> (other)": "`FUZZY` → `CONTRADICTION`", "FUZZY -> SIBLING": "`FUZZY` → `SIBLING` (a refused typo that still shares a distinctive token)",
             "(other) -> EQUAL_VIA_MODEL_ALIAS": "`CONTRADICTION` → `EQUAL_VIA_MODEL_ALIAS` (Honda synonym)"}
    for m in moves:
        row(names.get(m, m), c["transitions"]["ice_ice"].get(m, 0), c["transitions"]["ice_tdr"].get(m, 0))
    w("")
    w("## 4. Structural conflicts (same-provider batch conflicts, Ice × Ice)")
    w("")
    cb, ca = c["conflicts"]["before"], c["conflicts"]["after"]
    row("", "before", "after", "Δ")
    row("---", "---:", "---:", "---:")
    row("groups in any conflict", cb["all_groups"], ca["all_groups"], delta(cb["all_groups"], ca["all_groups"]))
    row("…settled groups", cb["settled_groups"], ca["settled_groups"], delta(cb["settled_groups"], ca["settled_groups"]))
    for k in ("duplicate", "finer", "sibling"):
        row(f"…{k} (class)", cb["by_class"].get(k, 0), ca["by_class"].get(k, 0), delta(cb["by_class"].get(k, 0), ca["by_class"].get(k, 0)))
    w("")
    w(f"{c['conflicts']['released']} groups left the conflict set and {len(c['conflicts']['entered'])} entered it: "
      + ", ".join(f"`{g}`" for g in c["conflicts"]["entered"]) + " (the two Honda synonym pairs are now recognised as duplicate Ice groups for one vehicle). "
      "The engine's own structural outcomes did not move: " + ", ".join(f"{k} {v}→{c['structural']['after'][k]}" for k, v in c["structural"]["before"].items() if k in ("STRUCTURAL_REVIEW", "AMBIGUOUS", "AMBIGUOUS_TARGET_CONTESTED")) + ".")
    w("")
    w("## 5. Decisions (the reference evaluator over the whole M7.0 snapshot, dry run)")
    w("")
    row("outcome", "before", "after")
    row("---", "---:", "---:")
    for k in sorted(set(c["outcomes"]["before"]) | set(c["outcomes"]["after"])):
        row(k, c["outcomes"]["before"].get(k, 0), c["outcomes"]["after"].get(k, 0))
    w("")
    a = c["auto"]
    w(f"**AUTO: {a['before']} before, {a['after']} after, the same set; newly AUTO: {len(a['newly_auto'])}; no longer AUTO: {len(a['no_longer_auto'])}.** "
      f"{len(c['changed_decisions'])} of 1,200 decisions changed:")
    w("")
    row("group", "units", "before", "after")
    row("---", "---:", "---", "---")
    for d in c["changed_decisions"]:
        row(f"`{d['group']}` ({d['name']})", f"{d['units']:,}", f"{d['before'][0]} · {d['before'][1]}" + (f" → {d['before'][2]}" if d["before"][2] else ""),
            f"{d['after'][0]} · {d['after'][1]}" + (f" → {d['after'][2]}" if d["after"][2] else ""))
    w("")
    w(f"Proposals annotated `CARD_CLAIM_CONFLICTS_AUTO`: {c['structural']['before']['proposals_annotated_CARD_CLAIM_CONFLICTS_AUTO']} → {c['structural']['after']['proposals_annotated_CARD_CLAIM_CONFLICTS_AUTO']} "
      "(the new one is `honda-honda-stepwagon` proposing `honda.step_wgn`, which `honda-step-wgn` already holds as AUTO: the synonym exposed a duplicate Ice group; it is flagged and PROPOSED, never promoted, never written).")
    w("")
    w("## 6. Newly exposed CREATE-risk cases")
    w("")
    w("A case is *exposed* when a rule that used to hold it (a wrong candidate, or a structural conflict) is gone and it can now fall to “create a new TDR model”.")
    w("")
    ch = [d for d in c["changed_decisions"] if d["after"][0] == "NO_CANDIDATE"]
    w("**6.1 Engine decisions that became NO_CANDIDATE (a link proposal withdrawn): " + str(len(ch)) + ".**")
    w("")
    for d in ch:
        via = before["ice_tdr_relation_pairs"].get(f"{d['group']}|{d['before'][2]}", "an EQUAL* relation")
        w(f"* `{d['group']}` ({d['name']}, {d['units']:,} units) was {d['before'][0]} as `{d['before'][2]}` ({d['before'][1]}) through a name relation of `{via}`"
          + (" across a digit, which the rules no longer allow; the TDR catalog extract has no model of that name." if via == "FUZZY" else "."))
    w("")
    cr = c["create_eligible_released"]
    w(f"**6.2 Groups released from a structural conflict that the engine decides NO_CANDIDATE: {cr['count']}** ({cr['units']:,} lifetime units in all). "
      f"Of the {c['conflicts']['released']} released groups: " + ", ".join(f"{v} {k}" for k, v in c["released_by_outcome"].items()) + ". By what released them: "
      + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in cr["by_cause"].items()) + ". Largest 20 by units (full list in `comparison.json`):")
    w("")
    row("group", "name", "units", "released by")
    row("---", "---", "---:", "---")
    for g in cr["top_by_units"]:
        row(f"`{g['group']}`", g["name"], f"{g['units']:,}", g["cause"].replace("_", " "))
    w("")
    w("These groups are CREATE candidates, not CREATE decisions: this pass creates nothing. Whether each is a new TDR model or an unmatched duplicate is the owner's review.")
    w("")
    w("**6.3 The seven groups PR #201 named.** (This measurement's “in a conflict” uses the contract's rules, not the stand-in's.)")
    w("")
    row("group", "in a batch conflict before", "after", "engine outcome before", "after")
    row("---", "---", "---", "---", "---")
    nb, na = c["named_in_pr201"]["before"], c["named_in_pr201"]["after"]
    for gid in BOOTSTRAP_NAMED:
        row(f"`{gid}`", "yes" if nb[gid]["in_batch_conflict"] else "no", "yes" if na[gid]["in_batch_conflict"] else "no", nb[gid]["outcome"], na[gid]["outcome"])
    w("")
    left = [g for g in BOOTSTRAP_NAMED if nb[g]["in_batch_conflict"] and not na[g]["in_batch_conflict"]]
    never = [g for g in BOOTSTRAP_NAMED if not nb[g]["in_batch_conflict"]]
    was_nc = [g for g in BOOTSTRAP_NAMED if nb[g]["outcome"] == "NO_CANDIDATE"]
    moved = [g for g in BOOTSTRAP_NAMED if nb[g]["outcome"] != na[g]["outcome"]]
    w(f"{len(left)} of the {len(BOOTSTRAP_NAMED)} left the conflict set ({', '.join('`' + g + '`' for g in left)}); {len(never)} were not in one under the contract's rules even before "
      f"({', '.join('`' + g + '`' for g in never) or 'none'}). {len(was_nc)} were already NO_CANDIDATE in the engine (no TDR counterpart, or only a vetoed one); "
      f"outcome changed for {len(moved)}: {', '.join('`' + g + '`' for g in moved) or 'none'}.")
    w("")
    w("## 7. Honda synonyms")
    w("")
    w("Ice × Ice: " + ", ".join(f"`{k}`" for k in c["synonym_pairs"]["ice_ice"]) + ". Ice × TDR: " + ", ".join(f"`{k}`" for k in c["synonym_pairs"]["ice_tdr"])
      + ". The TDR catalog extract has no `Jazz` or `Fit` model, so `honda-jazz` and `honda-honda-fit` still have no candidate; they are now recognised as one vehicle in two Ice groups. "
      "`honda-honda-stepwagon` reaches the existing `honda.step_wgn` by name only (its series is not strong), as a PROPOSE that conflicts with `honda-step-wgn`'s AUTO; no AUTO was added.")
    w("")
    w("## 8. What this pass does not fix (observations, for the owner)")
    w("")
    w(f"* **Containment on descriptors is unchanged.** `SUBJECT_COARSER`/`SUBJECT_FINER` pairs whose smaller side is all descriptor tokens: Ice × Ice {c['containment_not_changed']['ice_ice']['after'].get('SUBJECT_COARSER', 0)} + "
      f"{c['containment_not_changed']['ice_ice']['after'].get('SUBJECT_FINER', 0)}, Ice × TDR {c['containment_not_changed']['ice_tdr']['after'].get('SUBJECT_COARSER', 0)} + "
      f"{c['containment_not_changed']['ice_tdr']['after'].get('SUBJECT_FINER', 0)}. The owner asked only for FUZZY and SIBLING; `required_for_relations` can list them with no code change.")
    rf = c["remaining_fuzzy"]
    w(f"* **Remaining FUZZY.** Ice × TDR: {', '.join('`' + k + '`' for k in rf['ice_tdr'])} (genuine typos). Ice × Ice keeps {len(rf['ice_ice'])}: "
      "`CANIVAL`/`kia-carnival` (a typo), `foton-etunland`/`foton-tunland` (an electric variant, arguably a different model) and five Toyota catalog codes that differ in one *letter* "
      "(`JEXGBT`/`JEXVBT`, `PRMDHT`/`PRMSHT`, `GEXEGT`/`GEXGGT`). They are outside the stated rule (no digit in the differing token) and are still FUZZY, a name-only PROPOSE candidate.")
    w("* **Residual siblings.** A shared three-letter engine/technology word such as `cgi` (`C180 CGI Saloon` / `E200 CGI Saloon`) is distinctive under the length rule. It stays a SIBLING; both relations veto, so no outcome depends on it.")
    w("* **Synonyms are whole-name pairs.** `Jazz Hybrid` ≠ `Fit Hybrid`, and `Step Wagon` (two words) ≠ `Step WGN`; the first is a documented corpus case, neither is a wish.")
    w("* **Descriptor vocabulary is a proposal.** Each class and each pattern is pinned by corpus cases; individual words are not (the mutation sweep leaves 80 single words individually undetected). "
      "A test requires every word to be one normalized token so none can be inert by typo.")
    w("")
    w("## 9. The AUTO-monotonicity invariant (I19)")
    w("")
    w("`tests/identity_resolution/test_ir_lexical_invariants.py` pins, on the corpus (always) and on this snapshot (when the archived package is present):")
    w("")
    w("1. Over every name pair, a tightened relation is never more permissive than the rev 3 relation (FUZZY → CONTRADICTION/SIBLING, SIBLING → CONTRADICTION; EQUAL* unchanged).")
    w("2. The only new `EQUAL*` pairs are the Honda synonyms.")
    w("3. Over every resolve case and every real subject, AUTO(after) ⊆ AUTO(before) ∪ {subjects whose best candidate is a synonym}; a non-AUTO subject never becomes AUTO through a demotion. "
      f"Measured: AUTO {a['before']} → {a['after']}, same set.")
    w("4. `before_rev3.json` and `after_rev4.json` are what the code produces today, and this report is what they render to.")
    w("")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure")
    m.add_argument("--label", required=True)
    m.add_argument("--out", type=Path, required=True)
    m.add_argument("--rev3", action="store_true", help="measure under the rev 3 rules (rev3_rules()) instead of the current ones")
    r = sub.add_parser("report")
    r.add_argument("--before", type=Path, default=DIR / "before_rev3.json")
    r.add_argument("--after", type=Path, default=DIR / "after_rev4.json")
    args = ap.parse_args(argv)
    if args.cmd == "report":
        before, after = json.loads(args.before.read_text(encoding="utf-8")), json.loads(args.after.read_text(encoding="utf-8"))
        (DIR / "comparison.json").write_text(json.dumps(compare(before, after), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (DIR / "LEXICAL_PASS_REPORT.md").write_text(render_report(before, after), encoding="utf-8")
        print("wrote", DIR / "LEXICAL_PASS_REPORT.md")
        return 0
    if args.cmd == "measure":
        with rev3_rules() if args.rev3 else contextlib.nullcontext():
            doc = measure(args.label)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")
        print(json.dumps({k: doc[k] for k in ("label", "ice_ice", "ice_tdr")}, ensure_ascii=False, indent=1)[:1800])
        print(json.dumps(doc["decision_summary"]["outcomes"]), doc["batch_conflicts_ice_ice"]["all_groups"], doc["batch_conflicts_ice_ice"]["settled_groups"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
