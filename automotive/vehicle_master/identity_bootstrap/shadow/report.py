"""Turn shadow-run results into numbers, tables and files. Deterministic: the same inputs give byte-identical output. Writes only under `out_dir`."""
from __future__ import annotations

import collections
import copy
import csv
import json
import re
from pathlib import Path

import yaml

from identity_bootstrap import engine
from identity_bootstrap.engine.lexical import Lexicon
from identity_bootstrap.engine.fingerprint import canonical_json

from . import calibration, ir_rev4, post_ir, run as shadow_run

RULE_FLAGS = {"R1_HYPHENATED_REGISTRATION_CODE", "R2_GLUED_POWERTRAIN_SUFFIX", "R4_DISPLACEMENT_TRIM_CODE"}
CLASSES = ("model_code", "trim", "powertrain", "body", "generation")
OUTCOMES = ("CREATE_IDENTITY", "IDENTITY_REVIEW", "HOLD")
DORMANT_LAST12 = 10          # informational: a CREATE candidate with <= this many registrations in the last 12 months
RECENT_FIRST_SEEN = "2567-10"  # informational: first seen within the last 24 months of the package


# ---------------------------------------------------------------------------------------------------------------- helpers
def _units(pkg: dict) -> dict[str, float]:
    return {r["model_group_id"]: float(r["reg_total_all"]) for r in pkg["dims"]}


def _share(n: float, total: float) -> float:
    return round(100.0 * n / total, 2) if total else 0.0


def _bucket(decisions: list[dict], units: dict[str, float], last12: dict[str, float]) -> dict:
    total, total12 = sum(units.values()), sum(last12.values())
    out = {}
    for o in OUTCOMES:
        ds = [d for d in decisions if d["outcome"] == o]
        u = sum(units[d["subject"]["entity_id"]] for d in ds)
        u12 = sum(last12.get(d["subject"]["entity_id"], 0.0) for d in ds)
        out[o] = {"groups": len(ds), "units_total": int(u), "units_share_pct": _share(u, total), "units_last12": int(u12), "units_last12_share_pct": _share(u12, total12)}
    return out


def _causes(decisions: list[dict], units: dict[str, float]) -> dict:
    out = {}
    for o in OUTCOMES:
        ds = [d for d in decisions if d["outcome"] == o]
        primary = collections.Counter(d["primary_reason"] for d in ds)
        anyc = collections.Counter(c for d in ds for c in d["reason_codes"])
        vol = collections.Counter()
        for d in ds:
            vol[d["primary_reason"]] += units[d["subject"]["entity_id"]]
        out[o] = {"primary": [[c, n, int(vol[c])] for c, n in primary.most_common()], "any_code": [[c, n] for c, n in anyc.most_common()]}
    return out


def _weak_shared(a: list[str], b: list[str], lexicon_words: frozenset[str]) -> bool:
    """True when every shared token is non-distinctive: digits, <=2 letters, or a trim/body/powertrain/generation word (GR, RS, AMG, EV, ...)."""
    shared = set(a) & set(b)
    return bool(shared) and all(t.isdigit() or len(t) <= 2 or t in lexicon_words for t in shared)


def _creates(snapshot: dict, policy: dict, registry: dict) -> set[str]:
    return {d["subject"]["entity_id"] for d in engine.decide(snapshot, policy, registry) if d["outcome"] == "CREATE_IDENTITY"}


def _drop_class(policy: dict, cls: str) -> dict:
    q = copy.deepcopy(policy)
    spec = q["shape"][cls]
    for key in ("tokens", "token_patterns", "name_patterns"):
        if key in spec:
            spec[key] = []
    return q


# ---------------------------------------------------------------------------------------------------------------- analysis
def analyse(A: dict, B: dict, notes_path: Path | None = None) -> dict:
    pkg, policy, registry = A["package"], A["policy"], A["registry"]
    units, last12 = _units(pkg), pkg["last12"]
    dims = {r["model_group_id"]: r for r in pkg["dims"]}
    lex = Lexicon(policy)
    notes = yaml.safe_load((notes_path or Path(__file__).with_name("analyst_notes.yaml")).read_text(encoding="utf-8"))["create_verdicts"]
    snap = A["snapshot"]
    subj = {s["entity_id"]: s for s in snap["subjects"]}
    dA = {d["subject"]["entity_id"]: d for d in A["decisions"]}
    dB = {d["subject"]["entity_id"]: d for d in B["decisions"]}

    def toks(g: str) -> list[str]:
        s = subj[g]
        return lex.tokens(s["display_name"], (s["brand"]["raw"], *s["brand"].get("spellings", [])))

    out: dict = {"inputs": {
        "package_sha256": pkg["sha256"], "package_index": pkg["index"], "periods": list(pkg["periods"]), "groups": len(pkg["dims"]),
        "units_total": int(sum(units.values())), "units_last12": int(sum(last12.values())),
        "tdr_catalog": {"brands": len(A["catalog"]["brands"]), "models": len(A["catalog"]["identities"]), "source": "vehreg/data/2026/models/*.json (repo file catalog, verified identical to the live Vehicle Master on 2026-10-11 by a read-only SELECT)"},
        "policy_digest": A["decisions"][0]["policy"]["digest"], "policy_version": policy["version"],
        "status_mix": dict(collections.Counter(s["identity_status"] for s in snap["subjects"])),
        "engine_seconds": {"A": A["seconds"], "B": B["seconds"]}}}

    # ---- buckets and causes
    out["buckets"] = {"A": _bucket(A["decisions"], units, last12), "B": _bucket(B["decisions"], units, last12)}
    out["causes"] = {"A": _causes(A["decisions"], units), "B": _causes(B["decisions"], units)}
    out["write_plans"] = {"A": sum(1 for d in A["decisions"] if d["write_plan"]), "B": sum(1 for d in B["decisions"] if d["write_plan"]),
                          "writes_executed": 0}
    out["create_sets_equal"] = {d for d in dA if dA[d]["outcome"] == "CREATE_IDENTITY"} == {d for d in dB if dB[d]["outcome"] == "CREATE_IDENTITY"}

    # ---- CREATE candidates with audit overlays
    # R1 (proposal, evaluated here, NOT in the contract): a hyphen-joined chassis/registration code segment such as FG8JJ1A-JJT or KUN51R-NKPSYT.
    # The contract's per-token rule cannot see it because the hyphen splits the code into short tokens. (Checked on all 495 settled names: 16 hits, all chassis codes.)
    code_re = re.compile(r"(?<![a-z0-9])(?=[a-z0-9]*[0-9])[a-z0-9]{4,}-[a-z0-9]{3,}(?![a-z0-9])", re.I)
    glued_ev = re.compile(r"[0-9](ev|hev|phev)$")
    # R4 (proposal): a displacement-style trim code, three digits + 1-3 letters (BMW 630i, 530e, Volvo 264GL). False positive on the real name McLaren 750S.
    trim_code = re.compile(r"^[0-9]{3}[a-z]{1,3}$")
    creates = []
    for g, d in dA.items():
        if d["outcome"] != "CREATE_IDENTITY":
            continue
        t = toks(g)
        flags = []
        if code_re.search(dims[g]["model_name"]):
            flags.append("R1_HYPHENATED_REGISTRATION_CODE")
        if any(glued_ev.search(x) for x in t):
            flags.append("R2_GLUED_POWERTRAIN_SUFFIX")
        if any(trim_code.search(x) for x in t):
            flags.append("R4_DISPLACEMENT_TRIM_CODE")
        if last12.get(g, 0) <= DORMANT_LAST12:
            flags.append("DORMANT")
        if pkg["first_seen"][g] >= RECENT_FIRST_SEEN:
            flags.append("RECENT")
        creates.append({"id": g, "brand": dims[g]["brand"], "name": dims[g]["model_name"], "canonical_id": d["identity"]["canonical_model_id"],
                        "canonical_name": d["identity"]["canonical_name"], "units_total": int(units[g]), "units_last12": int(last12.get(g, 0)),
                        "first_seen": pkg["first_seen"][g], "last_seen": pkg["last_seen"][g], "flags": flags,
                        "analyst": notes.get(g), "in_B": dB[g]["outcome"] == "CREATE_IDENTITY"})
    creates.sort(key=lambda r: (-r["units_total"], r["id"]))
    out["creates"] = creates
    suspects = [c for c in creates if c["analyst"] and c["analyst"]["kind"] != "LIKELY_REAL"]
    out["suspected_false_creates"] = {
        "analyst_count": len(suspects), "by_kind": dict(collections.Counter(c["analyst"]["kind"] for c in suspects)),
        "units_total": sum(c["units_total"] for c in suspects),
        "caught_by_R1": sorted(c["id"] for c in creates if "R1_HYPHENATED_REGISTRATION_CODE" in c["flags"]),
        "caught_by_R2": sorted(c["id"] for c in creates if "R2_GLUED_POWERTRAIN_SUFFIX" in c["flags"]),
        "caught_by_R4": sorted(c["id"] for c in creates if "R4_DISPLACEMENT_TRIM_CODE" in c["flags"]),
        "analyst_suspects_missed_by_R1_R2": sorted(c["id"] for c in suspects if not (RULE_FLAGS & set(c["flags"]))),
        "r1_r2_flags_not_in_analyst_list": sorted(c["id"] for c in creates if (RULE_FLAGS & set(c["flags"])) and not (c["analyst"] and c["analyst"]["kind"] != "LIKELY_REAL")),
        "dormant": sum(1 for c in creates if "DORMANT" in c["flags"]), "dormant_units_total": sum(c["units_total"] for c in creates if "DORMANT" in c["flags"]),
        "recent": sum(1 for c in creates if "RECENT" in c["flags"]), "creates": len(creates)}

    # ---- suspected false REVIEW / HOLD
    words = frozenset(w.casefold() for cls in ("trim", "powertrain", "body", "generation") for w in policy["shape"][cls]["tokens"])
    weak, review_rows = [], []
    for g, d in dA.items():
        if d["outcome"] != "IDENTITY_REVIEW":
            continue
        s = subj[g]
        relation_codes = {"EXISTING_IDENTITY_SUSPECTED", "PROVIDER_FINER_THAN_TDR", "STRUCTURAL_CONFLICT"} & set(d["reason_codes"])
        other_blocking = set(d["reason_codes"]) - relation_codes - {"POSSIBLE_TRIM_NOT_MODEL", "POSSIBLE_POWERTRAIN_DERIVATIVE", "POSSIBLE_BODY_VARIANT", "POSSIBLE_GENERATION_VARIANT"}
        rels = [r for r in s.get("relations", []) if r["name_relation"] == "SIBLING"]
        peer_tokens = []
        for r in rels:
            if r["peer_kind"] == "SUBJECT":
                peer_tokens.append(toks(r["peer_id"]))
            else:
                ident = next((i for i in A["catalog"]["identities"] if i["canonical_id"] == r["peer_id"]), None)
                if ident:
                    peer_tokens.append(lex.tokens(ident["name_en"], (s["brand"]["raw"], *s["brand"].get("spellings", []))))
        only_sibling = relation_codes == {"EXISTING_IDENTITY_SUSPECTED"} and not other_blocking
        if only_sibling and peer_tokens and all(_weak_shared(toks(g), p, words) for p in peer_tokens):
            weak.append(g)
        review_rows.append(g)
    notact = []
    for g, d in dA.items():
        if d["primary_reason"] == "NOT_ACTIVATED":
            rel = [r["name_relation"] for r in subj[g]["relations"] if r["peer_kind"] == "TARGET" and r["name_relation"] in ("FUZZY", "EQUAL_VIA_TOKEN_EQUIV", "EQUAL_VIA_MODEL_ALIAS")]
            exact = [r for r in subj[g]["relations"] if r["peer_kind"] == "TARGET" and r["name_relation"] == "EQUAL"]
            if rel and not exact:
                notact.append(g)
    pipes = [g for g, s in subj.items() if s["identity_status"] == "unmapped_name"]
    clean_pipes = []
    for g in pipes:
        t = toks(g)
        if dims[g]["model_name"] != "ไม่ระบุ" and not lex.shape(dims[g]["model_name"], t) and not lex.raw_shaped("", dims[g]["model_name"], t) and 1 <= len(t) <= 3:
            clean_pipes.append(g)
    out["suspected_false_review_hold"] = {
        "review_total": len(review_rows), "weak_token_sibling_only": sorted(weak), "weak_units": int(sum(units[g] for g in weak)),
        "not_activated_by_fuzzy_or_equiv_only": sorted(notact),
        "unsettled_raw_ids": len(pipes), "unsettled_raw_ids_with_clean_looking_name": len(clean_pipes),
        "clean_looking_raw_top": [[g, dims[g]["model_name"], int(units[g])] for g in sorted(clean_pipes, key=lambda g: -units[g])[:25]],
        "provisional": sum(1 for s in subj.values() if s["identity_status"] == "provisional"),
        "settled_ids_with_registration_code_tokens": sorted(g for g, d in dA.items() if d["primary_reason"] == "PROVIDER_RAW_NAME" and subj[g]["identity_status"] == "settled")}

    # relation quality over ALL relations the stand-in produced (informational; this is the quality of the IR layer, not of Bootstrap)
    weak_sib = fuzzy_digit = fuzzy_total = sib_total = 0
    weak_sib_examples, fuzzy_digit_examples = [], []
    for g, s in subj.items():
        for r in s.get("relations", []):
            if r["peer_kind"] != "SUBJECT":
                continue
            a, b2 = toks(g), toks(r["peer_id"])
            if r["name_relation"] == "SIBLING":
                sib_total += 1
                if _weak_shared(a, b2, words):
                    weak_sib += 1
                    if len(weak_sib_examples) < 12:
                        weak_sib_examples.append([dims[g]["model_name"], dims[r["peer_id"]]["model_name"], sorted(set(a) & set(b2))])
            if r["name_relation"] == "FUZZY":
                fuzzy_total += 1
                diff = [x for x in set(a) ^ set(b2)]
                if any(any(ch.isdigit() for ch in x) for x in diff):
                    fuzzy_digit += 1
                    if len(fuzzy_digit_examples) < 12:
                        fuzzy_digit_examples.append([dims[g]["model_name"], dims[r["peer_id"]]["model_name"]])
    out["relation_quality"] = {"subject_pairs_sibling": sib_total, "sibling_on_non_distinctive_token_only": weak_sib, "sibling_examples": weak_sib_examples,
                               "subject_pairs_fuzzy": fuzzy_total, "fuzzy_where_the_differing_token_has_a_digit": fuzzy_digit, "fuzzy_digit_examples": fuzzy_digit_examples}

    # ---- structural conflicts (every subject carrying STRUCTURAL_CONFLICT, per mode)
    def conflicts(decisions: dict) -> list[dict]:
        rows = []
        for g, d in decisions.items():
            if "STRUCTURAL_CONFLICT" in d["reason_codes"]:
                rows.append({"id": g, "name": dims[g]["model_name"], "outcome": d["outcome"], "codes": d["reason_codes"], "group": [x.split(":", 1)[1] for x in d["batch_group"]],
                             "units_total": int(units[g])})
        return sorted(rows, key=lambda r: (-r["units_total"], r["id"]))
    out["structural_conflicts"] = {"A": conflicts(dA), "B": conflicts(dB)}
    lineage_codes = ("LINEAGE_UNRESOLVED", "PROVIDER_LINEAGE_AMBIGUOUS", "LINEAGE_CONTINUITY_EXISTING_IDENTITY")
    out["lineage"] = {"events": len(snap["lineage"]["events"]), "by_type": dict(collections.Counter(e["event_type"] for e in snap["lineage"]["events"])),
                      "subjects_with_lineage_codes": sorted([[g, [c for c in d["reason_codes"] if c in lineage_codes]] for g, d in dA.items() if any(c in lineage_codes for c in d["reason_codes"])]),
                      "events_whose_new_id_is_not_a_subject": sum(1 for e in snap["lineage"]["events"] if e["new_id"] not in subj)}

    # ---- word rules
    out["word_rules"] = _word_rules(A, B, subj, dA, toks, policy, registry, lex, units)
    return out


def _word_rules(A: dict, B: dict, subj: dict, dA: dict, toks, policy: dict, registry: dict, lex: Lexicon, units: dict) -> dict:
    snapA, snapB = A["snapshot"], B["snapshot"]
    baseA, baseB = _creates(snapA, policy, registry), _creates(snapB, policy, registry)
    classes = {}
    for cls in CLASSES:
        q = _drop_class(policy, cls)
        newA, newB = _creates(snapA, q, registry) - baseA, _creates(snapB, q, registry) - baseB
        classes[cls] = {"new_creates_if_removed": {"A": sorted(newA), "B": sorted(newB)}}
    allq = copy.deepcopy(policy)
    for cls in CLASSES:
        allq = _drop_class(allq, cls)
    allA = _creates(snapA, allq, registry) - baseA
    per_word = {}
    for cls in ("trim", "powertrain", "body", "generation"):
        for w in policy["shape"][cls]["tokens"]:
            q = copy.deepcopy(policy)
            q["shape"][cls]["tokens"].remove(w)
            new = _creates(snapA, q, registry) - baseA
            if new:
                per_word[f"{cls}.{w}"] = sorted(new)
    # hits: which words/patterns fire on which subjects, split by whether the id is settled
    hits: dict[str, dict] = {}
    for g, s in subj.items():
        t = toks(g)
        low = s["display_name"].casefold()
        for cls in ("trim", "powertrain", "body", "generation"):
            spec = policy["shape"][cls]
            words = {w.casefold() for w in spec["tokens"]}
            keys = [f"{cls}.{x}" for x in t if x in words]
            keys += [f"{cls}.pattern" for p in spec.get("token_patterns", []) if any(re.search(p, x) for x in t)]
            keys += [f"{cls}.name_pattern" for p in spec.get("name_patterns", []) if re.search(p, low)]
            for k in set(keys):
                h = hits.setdefault(k, {"subjects": 0, "settled": 0, "settled_names": []})
                h["subjects"] += 1
                if s["identity_status"] == "settled":
                    h["settled"] += 1
                    h["settled_names"].append(s["display_name"])
        joined = ["".join(t)] if len(t) > 1 else []
        if any(re.search(p, x) for p in policy["shape"]["model_code"]["token_patterns"] for x in t + joined):
            h = hits.setdefault("model_code.pattern", {"subjects": 0, "settled": 0, "settled_names": []})
            h["subjects"] += 1
            if s["identity_status"] == "settled":
                h["settled"] += 1
                h["settled_names"].append(s["display_name"])
    for h in hits.values():
        h["settled_names"] = sorted(set(h["settled_names"]))[:12]
    legit = ["Pajero Sport", "Aion Y Plus", "MG4 EV", "MG S5 EV", "Wuling Air EV", "Wuling Porta EV", "Mini Aceman EV", "Mini Cooper EV", "Mercedes-Benz GT-Class", "Karba NEW", "Peugeot 2008", "Honda S660", "Mazda Roadster"]
    names = {s["display_name"] for s in subj.values()}
    return {"classes": classes, "all_classes_removed_new_creates_A": sorted(allA), "per_word_new_creates_A": per_word, "hits": dict(sorted(hits.items())),
            "legitimate_model_names_hit_by_a_word": [{"name": n, "outcome": next(dA[g]["outcome"] + "/" + dA[g]["primary_reason"] for g, s in subj.items() if s["display_name"] == n)} for n in legit if n in names]}


# ---------------------------------------------------------------------------------------------------------------- files
def write_files(summary: dict, A: dict, B: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    dims = {r["model_group_id"]: r for r in A["package"]["dims"]}
    dA = {d["subject"]["entity_id"]: d for d in A["decisions"]}
    dB = {d["subject"]["entity_id"]: d for d in B["decisions"]}
    paths = []
    p = out_dir / "decisions.csv"
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["model_group_id", "brand", "model_name", "units_total", "units_last12", "first_seen", "last_seen", "identity_status",
                    "A_outcome", "A_primary", "A_codes", "B_outcome", "B_primary", "B_codes", "canonical_model_id_if_create", "priority_band"])
        for g in sorted(dA):
            a, b = dA[g], dB[g]
            w.writerow([g, dims[g]["brand"], dims[g]["model_name"], int(float(dims[g]["reg_total_all"])), int(A["package"]["last12"].get(g, 0)),
                        A["package"]["first_seen"][g], A["package"]["last_seen"][g], A["snapshot"]["subjects"][[s["entity_id"] for s in A["snapshot"]["subjects"]].index(g)]["identity_status"],
                        a["outcome"], a["primary_reason"], "|".join(a["reason_codes"]), b["outcome"], b["primary_reason"], "|".join(b["reason_codes"]),
                        a["identity"]["canonical_model_id"] if a["identity"] else "", a["review"]["priority_band"]])
    paths.append(p)
    p = out_dir / "summary.json"
    p.write_text(json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    paths.append(p)
    p = out_dir / "REPORT.md"
    p.write_text(render_md(summary), encoding="utf-8")
    paths.append(p)
    p = out_dir / "plans_sample.json"      # three complete CREATE write plans (a plan is data; none was executed)
    sample = [dA[c["id"]] for c in summary["creates"][:3]]
    p.write_text(json.dumps(sample, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    paths.append(p)
    return paths


def build_all(package_path: Path = shadow_run.DEFAULT_PACKAGE) -> tuple[dict, dict, dict, list[dict]]:
    """Everything the committed results derive from: runs A and B with the pinned PR #200 rev 4 relations, the comparison with the frozen milestone-3 results,
    the market-activity routing, and the PROVISIONAL adjudication rows. `A0` (same run, stand-in relations only) exists only to name the relation changes."""
    ir = ir_rev4.load()
    A = shadow_run.run("A", package_path, ir=ir)
    B = shadow_run.run("B", package_path, pkg=A["package"], ir=ir)
    A0 = shadow_run.run("A", package_path, pkg=A["package"])
    summary = analyse(A, B)
    notes = yaml.safe_load((Path(__file__).with_name("analyst_notes.yaml")).read_text(encoding="utf-8"))["create_verdicts"]
    base = calibration.load_baseline(calibration.HERE / "baseline_m3" / "decisions.csv")
    baseline_ids = post_ir.load_baseline_ids(calibration.HERE / "baseline_m3" / "create_adjudication.csv")
    creates = sorted(c["id"] for c in summary["creates"])
    m4 = post_ir.build_m4(A, B, A0, ir, base, baseline_ids, creates)
    m4["activity_classes_informational"] = _activity(summary["creates"], A["package"])
    m4["policy_version"] = A["policy"]["version"]
    m4["universe_verification"] = A["catalog"]["verification"]["comparison_with_file_snapshot"]
    summary["m4"] = m4
    mk = post_ir.market(A, creates)
    rows = calibration.adjudication_rows(A, A0, creates, notes, calibration.load_r6(), A["catalog"]["verification"]["redirects"], baseline_ids, mk)
    return A, B, summary, rows


def write_transitions(rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["model_group_id"])
        w.writeheader()
        w.writerows(rows)


def write_market(A: dict, summary: dict, out: Path) -> None:
    from . import activity_report
    s = activity_report.build(A)
    (out / "market_activity.json").write_text(json.dumps(s, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "market_activity.md").write_text(activity_report.render_md(s), encoding="utf-8")


def _activity(creates: list[dict], pkg: dict) -> dict:
    out: dict = {}
    for c in creates:
        cls = calibration.activity_class(c["id"], pkg)
        slot = out.setdefault(cls, {"groups": 0, "lifetime_units": 0, "last12_units": 0, "ids": []})
        slot["groups"] += 1
        slot["lifetime_units"] += c["units_total"]
        slot["last12_units"] += c["units_last12"]
        slot["ids"].append(c["id"])
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m identity_bootstrap.shadow", description="Read-only shadow evaluation on the pinned Ice package.")
    ap.add_argument("--package", type=Path, default=shadow_run.DEFAULT_PACKAGE)
    ap.add_argument("--out", type=Path, required=True, help="directory for decisions.csv, summary.json, REPORT.md, plans_sample.json")
    ap.add_argument("--review-dir", type=Path, default=None, help="where create_adjudication.csv goes (default: <shadow>/review)")
    args = ap.parse_args(argv)
    A, B, summary, rows = build_all(args.package)
    for path in write_files(summary, A, B, args.out):
        print(path)
    calibration.write_adjudication(rows, (args.review_dir or Path(__file__).with_name("review")) / "create_adjudication.csv")
    write_transitions(summary["m4"]["transitions"], args.out / "transitions_vs_m3.csv")
    write_market(A, summary, args.out)
    print((args.review_dir or Path(__file__).with_name("review")) / "create_adjudication.csv")
    return 0


# ---------------------------------------------------------------------------------------------------------------- markdown
def _table(head: list[str], rows: list[list]) -> str:
    esc = lambda x: str(x).replace("|", "\\|")
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]) + "\n"



def _m4_md(s: dict, m: dict) -> str:
    d, par, rel, st = m["diff"], m["parity"], m["released_no_candidate"], m["structural"]
    L = ["## 0. Post-PR-#200-rev-4 rerun (relations consumed from the pinned export, not re-implemented)\n",
         f"- PR #200 commit `{m['pr200']['commit']}` (`{m['pr200']['label']}`); source blobs sha256 {m['pr200']['sources_sha256']}. Policy keys in force there: {m['pr200']['policy']}.",
         "- The stand-in supplies only the pair population and the relations rev 4 did not touch; every FUZZY / SIBLING / EQUAL_VIA_MODEL_ALIAS verdict comes from the export. Same engine, policy v" + str(m["policy_version"]) + ", package and TDR universe as milestone 3.",
         f"- Baseline: {m['baseline']}.\n", "### 0.1 Counts (before = milestone 3)\n"]
    rows = []
    for mode in ("A", "B"):
        old, new = collections.Counter(), collections.Counter()
        for k, n in d[mode]["transition_matrix"].items():
            a, b = k.split(" -> ")
            old[a] += n
            new[b] += n
        for o in ("CREATE_IDENTITY", "IDENTITY_REVIEW", "HOLD"):
            v = s["buckets"][mode][o]
            rows.append([mode, o, old[o], new[o], f"{v['units_total']:,}", f"{v['units_last12']:,}"])
    L.append(_table(["Mode", "Outcome", "Before", "After", "Units all time (after, info)", "Units last 12 m (after, info)"], rows))
    for mode in ("A", "B"):
        L.append(f"**Mode {mode} transitions:** " + "; ".join(f"{k} {n}" for k, n in sorted(d[mode]["transition_matrix"].items() if False else d[mode]["transition_matrix"].items())) + f". CREATE added {d[mode]['create_added']}; CREATE removed {d[mode]['create_removed']}.\n")
    cs = m["create_sets"]
    L.append(f"**CREATE set: {cs['count']}** (added vs milestone 3: {cs['added_vs_m3']}; removed: {cs['removed_vs_m3']}; unchanged {cs['unchanged']}). Worst-case mode B creates a subset of mode A: **{cs['B_subset_of_A']}**; in A but not B: {cs['in_A_not_B']} (a sibling that the resolver stand-in diverted in A forms no batch conflict there).\n")
    L.append("### 0.2 Per-subject decision transitions (any mode; first 60 by units)\n")
    L.append(_table(["Group", "Name", "Status", "Units (info)", "A before", "A after", "B before", "B after"],
                    [[t["model_group_id"], t["name"], t["identity_status"], t["lifetime_units"], t["A_before"], t["A_after"], t["B_before"], t["B_after"]] for t in sorted(m["transitions"], key=lambda t: -t["lifetime_units"])[:60]]))
    L.append(f"{len(m['transitions'])} groups changed in total (full list: `transitions_vs_m3.csv`).\n")
    L.append("### 0.3 Structural conflicts\n")
    L.append(_table(["Mode", "Before", "After", "Left the set", "Entered the set"], [[k, v["before"], v["after"], len(v["left"]), f"{len(v['entered'])}: {', '.join(v['entered'][:12])}"] for k, v in st.items()]))
    L.append("### 0.4 Newly exposed CREATE-risk cases\n")
    L.append(_table(["Group", "Name", "Before (M3)", "A after", "B after", "Relation changes that exposed it"],
                    [[r["id"], r["name"], r["before"], r["A_after"], r["B_after"], "; ".join(r["relation_changes"]) or "none (batch effect)"] for r in m["new_create_risks"]]))
    L.append(f"### 0.5 The {rel['pr200_count']} NO_CANDIDATE groups PR #200 released from structural conflict ({rel['pr200_units']:,} lifetime units, info)\n")
    L.append(f"Present in this run: {rel['present_in_bootstrap_run']}; identity status {rel['identity_status']}. **Not all are Bootstrap candidates**: unsettled raw ids (`BRAND|MODEL`) and provisional ids are HOLD by contract.\n")
    L.append(_table(["Mode", "Outcomes before (M3)", "Outcomes after", "Primary reasons after", "CREATE"], [[mo, rel[mo]["before_m3"], rel[mo]["after"], rel[mo]["after_primary"], rel[mo]["create"]] for mo in ("A", "B")]))
    L.append("### 0.6 Relation parity with the pinned export\n")
    L.append(_table(["Population", "Exported pairs", "Missing / relabelled", "FUZZY/SIBLING not in export", "Corrected kinds [stand-in, IR]", "Unchanged kinds [stand-in, IR]"],
                    [[k, par[k]["exported_pairs"], len(par[k]["exported_pairs_missing_or_relabelled"]), len(par[k]["fuzzy_or_sibling_not_in_export"]), par[k]["corrected_kinds_equal"], par[k]["unchanged_kinds_standin_vs_ir"]] for k in ("ice_ice", "ice_tdr")]))
    ov = par["unchanged_class_relations_overridden_by_ir"]
    L.append(f"Stand-in relation of an unchanged kind overridden by IR's verdict (IR is the authority; a stand-in/IR population disagreement, not a rev 4 rule): ice×ice {len(ov['ice_ice'])}, ice×tdr {len(ov['ice_tdr'])} — {ov['ice_tdr']}\n")
    ma = m["market_activity"]
    L.append("### 0.7 Market-activity routing of the CREATE candidates (routing only; absent rows UNKNOWN)\n")
    L.append(f"**Actual:** states {ma['actual']['states']}; lanes {ma['actual']['lanes']}. **What-if (NOT AUTHORITATIVE, assumes ABSENT_IS_ZERO):** states {ma['what_if_NOT_AUTHORITATIVE']['states']}; lanes {ma['what_if_NOT_AUTHORITATIVE']['lanes']}.\n")
    L.append("Informational activity classes of the CREATE set: " + "; ".join(f"{c} {v['groups']}" for c, v in m["activity_classes_informational"].items()) + ". Age or low volume never decides an outcome; dormant legacy models are valid HISTORICAL_BACKFILL candidates, not false CREATEs.\n")
    L.append("Provisional owner-adjudication set: `shadow/review/create_adjudication.csv` (owner fields blank; QA pending).\n")
    return "\n".join(L)


def render_md(s: dict) -> str:
    i, b = s["inputs"], s["buckets"]
    L = [f"# Identity Bootstrap shadow run — Ice `{i['package_index']['period']}` v{i['package_index']['version']} M{i['package_index']['master_version']}\n",
         "> Generated by `python -m identity_bootstrap.shadow`. **Read-only offline evaluation. Nothing was written; no identity was created.** Registration volume is informational only.\n",
         f"- Package sha256 `{i['package_sha256']}` (pinned). {i['groups']} model groups; {i['units_total']:,} registrations in total ({i['units_last12']:,} in the last 12 months).",
         f"- Status mix (adapter): {i['status_mix']}. Policy v{i['policy_version']} `{i['policy_digest'][:23]}…`. TDR side: **{i['tdr_catalog']['models']} models / {i['tdr_catalog']['brands']} brands from {i['tdr_catalog']['source']}**.",
         "- Mode **A**: a lexical stand-in for Identity Resolution lets duplicates of a TDR model stop at the resolver (`NOT_ACTIVATED`). Mode **B** (worst case): every group is offered to Bootstrap as `NO_CANDIDATE`.\n",
         ]
    if s.get("m4"):
        L.append(_m4_md(s, s["m4"]))
    L.append("## 1. Decisions and registration-volume coverage (informational)\n")
    for mode in ("A", "B"):
        L.append(f"**Mode {mode}**\n")
        L.append(_table(["Outcome", "Groups", "Units (all time)", "Share", "Units (last 12 m)", "Share"],
                        [[o, v["groups"], f"{v['units_total']:,}", f"{v['units_share_pct']}%", f"{v['units_last12']:,}", f"{v['units_last12_share_pct']}%"] for o, v in b[mode].items()]))
    L.append(f"CREATE sets identical in A and B: **{s['create_sets_equal']}**. Write plans produced: A {s['write_plans']['A']}, B {s['write_plans']['B']}; writes executed: **{s['write_plans']['writes_executed']}**.\n")
    L.append("## 2. Top REVIEW / HOLD causes\n")
    for mode in ("A", "B"):
        for o in ("IDENTITY_REVIEW", "HOLD"):
            L.append(f"**Mode {mode} — {o}, by primary reason**\n")
            L.append(_table(["Primary reason", "Groups", "Units (all time)"], [[c, n, f"{u:,}"] for c, n, u in s["causes"][mode][o]["primary"]]))
    L.append("**Mode A — every code that fired (any position)**\n")
    L.append(_table(["Outcome", "Codes (count)"], [[o, ", ".join(f"{c} {n}" for c, n in s["causes"]["A"][o]["any_code"])] for o in ("IDENTITY_REVIEW", "HOLD")]))
    L.append("## 3. CREATE candidates (mode A; every one is a plan, none was executed)\n")
    L.append(_table(["Group", "Name", "→ canonical id", "Units", "Last 12 m", "First seen", "Flags", "Analyst"],
                    [[c["id"], c["name"], c["canonical_id"], f"{c['units_total']:,}", c["units_last12"], c["first_seen"], " ".join(c["flags"]) or "-",
                      (c["analyst"]["kind"] + ": " + c["analyst"]["why"]) if c["analyst"] else "-"] for c in s["creates"]]))
    f = s["suspected_false_creates"]
    L.append(f"## 4. Suspected false CREATEs\n\nAnalyst judgement (`shadow/analyst_notes.yaml`, not ground truth): **{f['analyst_count']} of {f['creates']}** ({f['units_total']:,} units) — {f['by_kind']}.\n")
    L.append("- The milestone-2 proposals R1/R2/R4 are now policy v2 rules (section 0.3); the lists below show what they still catch among the remaining CREATEs (empty = all already removed).")
    L.append(f"- R1 (hyphenated registration code) still catches {len(f['caught_by_R1'])}: {', '.join(f['caught_by_R1'])}.")
    L.append(f"- R2 (powertrain suffix glued to a digit token) still catches {len(f['caught_by_R2'])}: {', '.join(f['caught_by_R2'])}.")
    L.append(f"- R4 (displacement/trim code) still catches {len(f['caught_by_R4'])}: {', '.join(f['caught_by_R4']) or 'none'}.")
    L.append(f"- Analyst-suspected, not caught by any rule ({len(f['analyst_suspects_missed_by_R1_R2'])}): {', '.join(f['analyst_suspects_missed_by_R1_R2'])}.")
    L.append(f"- Rule flags the analyst did not list (false positives of the proposals): {f['r1_r2_flags_not_in_analyst_list'] or 'none'}.")
    L.append(f"- Dormant (≤{DORMANT_LAST12} registrations in the last 12 months): **{f['dormant']} of {f['creates']}** ({f['dormant_units_total']:,} units all-time); first seen in the last 24 months: **{f['recent']}**.\n")
    r = s["suspected_false_review_hold"]
    L.append("## 5. Suspected false REVIEW / HOLD\n")
    L.append(f"- Review decisions (mode A): {r['review_total']}. REVIEWs caused only by a SIBLING relation on a weak shared token (digits or ≤2 letters): **{len(r['weak_token_sibling_only'])}** {r['weak_token_sibling_only']}.")
    L.append(f"- `NOT_ACTIVATED` only because of a FUZZY / token-equivalence / alias relation (no EQUAL match), i.e. stand-in matches worth a human look: {r['not_activated_by_fuzzy_or_equiv_only']}.")
    L.append(f"- Unsettled raw ids held: {r['unsettled_raw_ids']} (`BRAND|MODEL`), of which **{r['unsettled_raw_ids_with_clean_looking_name']}** have a clean-looking name (held correctly by contract; they become CREATE candidates only after Ice settles them). Provisional: {r['provisional']}. Settled ids that are registration codes: {len(r['settled_ids_with_registration_code_tokens'])}.")
    L.append(_table(["Raw id", "Name", "Units"], r["clean_looking_raw_top"]))
    L.append("## 6. Structural conflicts (every group carrying `STRUCTURAL_CONFLICT`)\n")
    for mode in ("A", "B"):
        L.append(f"**Mode {mode}: {len(s['structural_conflicts'][mode])} groups**\n")
        L.append(_table(["Group", "Name", "Outcome", "Codes", "Batch group", "Units"],
                        [[c["id"], c["name"], c["outcome"], " ".join(c["codes"]), ", ".join(c["group"]), f"{c['units_total']:,}"] for c in s["structural_conflicts"][mode]]))
    q = s["relation_quality"]
    L.append(f"**Relation quality (stand-in for the IR layer, subject↔subject pairs):** SIBLING pairs {q['subject_pairs_sibling']}, of which {q['sibling_on_non_distinctive_token_only']} share only a non-distinctive token (digits, ≤2 letters, or a trim/powertrain/body/generation word) — e.g. {q['sibling_examples'][:6]}; FUZZY pairs {q['subject_pairs_fuzzy']}, of which {q['fuzzy_where_the_differing_token_has_a_digit']} differ in a token that contains a digit (a different version/code, not a typo) — e.g. {q['fuzzy_digit_examples'][:6]}.\n")
    ln = s["lineage"]
    L.append(f"## 7. Lineage\n\n{ln['events']} `id_changes` events {ln['by_type']}; subjects affected: {len(ln['subjects_with_lineage_codes'])}.\n")
    L.append(_table(["Group", "Lineage codes"], [[g, " ".join(c)] for g, c in ln["subjects_with_lineage_codes"]]))
    w = s["word_rules"]
    L.append("## 8. Effect of the lexical word rules\n")
    L.append(_table(["Class removed", "New CREATEs in A", "New CREATEs in B"], [[c, ", ".join(v["new_creates_if_removed"]["A"]) or "none", ", ".join(v["new_creates_if_removed"]["B"]) or "none"] for c, v in w["classes"].items()]))
    L.append(f"All shape classes removed → new CREATEs in A: {w['all_classes_removed_new_creates_A']}. Single words whose removal changes a CREATE: {w['per_word_new_creates_A'] or 'none'}.\n")
    L.append(_table(["Class.word", "Groups hit", "Of which settled ids", "Settled names (≤12)"], [[k, v["subjects"], v["settled"], "; ".join(v["settled_names"])] for k, v in w["hits"].items()]))
    L.append("Legitimate model names a word rule hits: " + "; ".join(f"{x['name']} → {x['outcome']}" for x in w["legitimate_model_names_hit_by_a_word"]) + "\n")
    return "\n".join(L)
