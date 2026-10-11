"""Milestone 3: before/after attribution and the owner-adjudication artifact.

Everything here is measurement. Analyst notes are carried through as a NOTE column and are never used to decide anything; `owner_label` is left blank for the owner.
"""
from __future__ import annotations

import collections
import copy
import csv
import json
from pathlib import Path

import yaml

from identity_bootstrap import engine
from identity_bootstrap.engine.lexical import Lexicon

from . import run as shadow_run
from .stand_in import name_relation

HERE = Path(__file__).parent
BASELINE = HERE / "baseline_m2" / "decisions.csv"
R6_FILE = HERE / "universe" / "r6_crosswalk_for_create_candidates.json"
OWNER_LABELS = ["TRUE_NEW_IDENTITY", "EXISTING_IDENTITY", "VARIANT_TRIM_CODE", "AMBIGUOUS"]
ACTIVITY_DORMANT_LAST12 = 10
ACTIVITY_RECENT_FIRST_SEEN = "2567-10"     # Buddhist era, as in the package: first seen within the last 24 months


# ---------------------------------------------------------------------------------------------------------------- one rule off at a time
def _off(rule: str, policy: dict) -> dict:
    q = copy.deepcopy(policy)
    if rule == "R1_hyphenated_code":
        q["subject"]["raw_name"]["code_segment_pattern"] = "(?!)"
    elif rule == "R2_glued_powertrain_suffix":
        q["shape"]["powertrain"]["token_patterns"] = []
    elif rule == "R4_displacement_trim_code":
        q["shape"]["model_code"]["token_patterns"] = q["shape"]["model_code"]["token_patterns"][:1]
    elif rule == "YEAR_range_and_context":
        q["shape"]["generation"]["token_patterns"] = q["shape"]["generation"]["token_patterns"] + ["^(19|20)[0-9]{2}$"]
        q["shape"]["generation"]["contextual_token_patterns"] = []
    elif rule == "TRUNCATION_soft_signal":
        q["shape"]["truncation"].update({"min_compact_chars": 0, "dangling_tokens": []})
    elif rule == "SUB_BRAND_guard":
        q["brand"]["sub_brands"] = {}
    elif rule == "BRAND_FAMILY":
        pass            # handled by the stand-in option (no family in the input)
    else:
        raise KeyError(rule)
    return q


RULES = ["R1_hyphenated_code", "R2_glued_powertrain_suffix", "R4_displacement_trim_code", "YEAR_range_and_context", "TRUNCATION_soft_signal", "SUB_BRAND_guard", "BRAND_FAMILY"]


def _outcomes(run: dict) -> dict[str, tuple]:
    return {d["subject"]["entity_id"]: (d["outcome"], d["primary_reason"], tuple(d["reason_codes"])) for d in run["decisions"]}


def rule_effects(base: dict, pkg: dict) -> dict:
    """For each new rule: switch ONLY that rule off, keep everything else as in `base` (mode A), and list every group whose outcome differs."""
    on = _outcomes(base)
    out = {}
    for rule in RULES:
        if rule == "SUB_BRAND_guard":
            # the stand-in adapter already offers only the marque's own spellings; to show what the ENGINE guard does, give both sides a naive adapter
            with_guard = _outcomes(shadow_run.run("A", pkg=pkg, naive_spellings=True))
            without = _outcomes(shadow_run.run("A", pkg=pkg, naive_spellings=True, policy=_off(rule, base["policy"])))
            before, after, note = without, with_guard, "measured with a NAIVE adapter that offers every catalog alias (sub-brands included) as a spelling"
        elif rule == "BRAND_FAMILY":
            before, after, note = _outcomes(shadow_run.run("A", pkg=pkg, families=False)), on, "family input withheld in the 'off' run"
        else:
            before, after, note = _outcomes(shadow_run.run("A", pkg=pkg, policy=_off(rule, base["policy"]))), on, ""
        changed = [(g, before[g], after[g]) for g in sorted(after) if before[g][:2] != after[g][:2] or before[g][2] != after[g][2]]
        trans = collections.Counter((b[0], a[0]) for g, b, a in changed)
        out[rule] = {"note": note, "groups_changed": len(changed), "transitions_off_to_on": {f"{k[0]} -> {k[1]}": v for k, v in sorted(trans.items())},
                     "created_off_not_created_on": sorted(g for g, b, a in changed if b[0] == "CREATE_IDENTITY" and a[0] != "CREATE_IDENTITY"),
                     "new_reviews": sorted(g for g, b, a in changed if a[0] == "IDENTITY_REVIEW" and b[0] != "IDENTITY_REVIEW"),
                     "new_holds": sorted(g for g, b, a in changed if a[0] == "HOLD" and b[0] != "HOLD"),
                     "became_create": sorted(g for g, b, a in changed if a[0] == "CREATE_IDENTITY" and b[0] != "CREATE_IDENTITY")}
    return out


# ---------------------------------------------------------------------------------------------------------------- before / after
def load_baseline(path: Path = BASELINE) -> dict[str, dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return {r["model_group_id"]: r for r in csv.DictReader(fh)}


def diff_against_baseline(A: dict, B: dict, base: dict[str, dict], notes: dict) -> dict:
    out = {}
    for mode, run, o, p in (("A", A, "A_outcome", "A_primary"), ("B", B, "B_outcome", "B_primary")):
        new = {d["subject"]["entity_id"]: d for d in run["decisions"]}
        trans = collections.Counter((base[g][o], new[g]["outcome"]) for g in new)
        changed = [g for g in new if base[g][o] != new[g]["outcome"] or base[g][p] != new[g]["primary_reason"]]
        out[mode] = {"transition_matrix": {f"{a} -> {b}": n for (a, b), n in sorted(trans.items())}, "groups_with_any_change": len(changed),
                     "create_removed": sorted(g for g in new if base[g][o] == "CREATE_IDENTITY" and new[g]["outcome"] != "CREATE_IDENTITY"),
                     "create_added": sorted(g for g in new if base[g][o] != "CREATE_IDENTITY" and new[g]["outcome"] == "CREATE_IDENTITY"),
                     "removed_detail": {g: [new[g]["outcome"], new[g]["reason_codes"]] for g in sorted(new) if base[g][o] == "CREATE_IDENTITY" and new[g]["outcome"] != "CREATE_IDENTITY"},
                     "review_added": sorted(g for g in new if base[g][o] != "IDENTITY_REVIEW" and new[g]["outcome"] == "IDENTITY_REVIEW"),
                     "review_removed": sorted(g for g in new if base[g][o] == "IDENTITY_REVIEW" and new[g]["outcome"] != "IDENTITY_REVIEW")}
    return out


def attribute_removed(removed: list[str], effects: dict) -> dict:
    """For each CREATE removed since milestone 2: which new rule(s) bring it back when switched off. 'none' = another cause (reported separately)."""
    attribution = {g: [r for r, e in effects.items() if g in e["created_off_not_created_on"]] for g in removed}
    return {g: (rules or ["none of the seven rules (see detail)"]) for g, rules in attribution.items()}


def universe_effect(A: dict, pkg: dict) -> dict:
    """Same rules, milestone-2 universe (no slug reservation) vs the verified live universe."""
    m2 = _outcomes(shadow_run.run("A", pkg=pkg, with_slugs=False))
    now = _outcomes(A)
    removed = sorted(g for g in now if m2[g][0] == "CREATE_IDENTITY" and now[g][0] != "CREATE_IDENTITY")
    return {"models_in_live_not_in_snapshot": 0, "models_in_snapshot_not_in_live": 0, "create_removed_by_the_fuller_universe": removed,
            "create_added_by_the_fuller_universe": sorted(g for g in now if m2[g][0] != "CREATE_IDENTITY" and now[g][0] == "CREATE_IDENTITY"),
            "explanation": "the live Vehicle Master is identical to the snapshot on every identity-bearing field; the only difference is that all 323 slugs are now reserved in the collision check"}


# ---------------------------------------------------------------------------------------------------------------- activity classes
def activity_class(g: str, pkg: dict) -> str:
    if pkg["last12"].get(g, 0) <= ACTIVITY_DORMANT_LAST12:
        return "DORMANT_LEGACY"
    if pkg["first_seen"][g] >= ACTIVITY_RECENT_FIRST_SEEN:
        return "RECENT_DISCOVERY"
    return "ACTIVE_ESTABLISHED"


# ---------------------------------------------------------------------------------------------------------------- the owner-adjudication artifact
def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def nearest_identities(run: dict, subject: dict, top: int = 3) -> list[str]:
    """The TDR models whose names overlap most with the subject's (token Jaccard, brand family first). Evidence for a human, not a decision."""
    lex: Lexicon = run["stand_in"].lex
    brand = subject["brand"]
    family = {brand["brand_id"], *[f["brand_id"] for f in brand.get("family", [])]}
    spell = (brand["raw"], *brand.get("spellings", []), *[s for f in brand.get("family", []) for s in f.get("spellings", [])])
    mine = lex.tokens(subject["display_name"], spell)
    scored = []
    for ident in run["catalog"]["identities"]:
        theirs = lex.tokens(ident["name_en"], spell)
        j = _jaccard(set(mine), set(theirs))
        if j > 0 or "".join(mine) == "".join(theirs):
            same = ident["brand_id"] in family
            scored.append((-(j + (0.01 if same else 0.0)), ident["canonical_id"], ident["name_en"], j, same))
    scored.sort()
    hist = set(run["catalog"].get("historical", []))
    return [f"{cid} ({name}; overlap {j:.2f}; {'same brand/family' if same else 'OTHER BRAND'}{'; HISTORICAL' if cid in hist else ''})" for _, cid, name, j, same in scored[:top]]


def adjudication_rows(A: dict, summary_creates: list[dict], notes: dict, r6: dict, redirects: list) -> list[dict]:
    pkg = A["package"]
    dims = {r["model_group_id"]: r for r in pkg["dims"]}
    subj = {s["entity_id"]: s for s in A["snapshot"]["subjects"]}
    events = A["snapshot"]["lineage"]["events"]
    dec = {d["subject"]["entity_id"]: d for d in A["decisions"]}
    rows = []
    for c in summary_creates:
        g = c["id"]
        d, s = dec[g], subj[g]
        rels = [f"{r['peer_kind']}:{r['peer_id']}={r['name_relation']}" for r in s["relations"] if r["name_relation"] not in ("CONTRADICTION", "UNAVAILABLE")]
        ev = [f"{e['event_type']}:{e['old_id']}>{e['new_id']}" for e in events if g in (e["old_id"], e["new_id"])]
        red = [f"R6_REDIRECT:{o}>{n}({t})" for o, n, t in redirects if g in (o, n)]
        alias = [a["external_id"] for a in d["write_plan"]["event"]["aliases"] if a["relation"] == "RETIRED_PREDECESSOR"]
        r6rows = r6.get(g)
        notes_row = notes.get(g)
        rows.append({
            "provider": "ice", "external_id": g, "brand": dims[g]["brand"], "name": dims[g]["model_name"],
            "proposed_canonical_id": d["identity"]["canonical_model_id"], "proposed_canonical_name": d["identity"]["canonical_name"],
            "first_seen": pkg["first_seen"][g], "last_seen": pkg["last_seen"][g], "lifetime_units": int(float(dims[g]["reg_total_all"])), "last12_units": int(pkg["last12"].get(g, 0)),
            "activity_class_informational": activity_class(g, pkg),
            "nearest_existing_identities": " || ".join(nearest_identities(A, s)) or "none above zero overlap",
            "relation_evidence": "; ".join(rels) or "none (no non-contradictory relation to any TDR model or other Ice group)",
            "legacy_r6_candidate": ("; ".join(f"{x[1]} {x[0]} ({x[2]}, score {x[3]})" for x in r6rows) if r6rows else ("none" if r6 else "not fetched")),
            "lineage_state": "; ".join(ev + red) or "no id_changes event and no R6 redirect",
            "retired_aliases_in_plan": "|".join(alias),
            "shape_flags": "|".join(c_["code"] + ":cleared_by_" + c_["cleared_by"] for c_ in d["evidence_basis"]["cleared_flags"]) or "none fired",
            "evidence_tier": d["evidence_basis"]["tier"], "evidence_kinds": "|".join(d["evidence_basis"]["kinds"]),
            "machine_decision": f"{d['outcome']} / {d['primary_reason']}", "reason_codes": "|".join(d["reason_codes"]),
            "analyst_note": (f"{notes_row['kind']}: {notes_row['why']}" if notes_row else ""),
            "owner_label": "", "owner_comment": ""})
    return rows


COLUMNS = ["provider", "external_id", "brand", "name", "proposed_canonical_id", "proposed_canonical_name", "first_seen", "last_seen", "lifetime_units", "last12_units",
           "activity_class_informational", "nearest_existing_identities", "relation_evidence", "legacy_r6_candidate", "lineage_state", "retired_aliases_in_plan",
           "shape_flags", "evidence_tier", "evidence_kinds", "machine_decision", "reason_codes", "analyst_note", "owner_label", "owner_comment"]


def write_adjudication(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("# owner_label must be one of: " + " | ".join(OWNER_LABELS) + ". analyst_note is a machine-assisted NOTE, never ground truth; do not calibrate CREATE permission from it.\n")
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in sorted(rows, key=lambda r: (-r["last12_units"], -r["lifetime_units"], r["external_id"])):
            w.writerow(r)


def load_r6() -> dict:
    """Read-only copy of the live R6 crosswalk rows for the remaining CREATE candidates: group -> [[target, status, method, score], ...] (empty list = no row)."""
    if not R6_FILE.exists():
        return {}
    return json.loads(R6_FILE.read_text(encoding="utf-8"))["rows"]
