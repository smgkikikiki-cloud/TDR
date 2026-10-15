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

from . import calibration, ir_export, post_ir, run as shadow_run

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

    # ---- suspected false REVIEW / HOLD (relations are PR #200's; nothing here judges a name)
    review_rows = [g for g, d in dA.items() if d["outcome"] == "IDENTITY_REVIEW"]
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
        "review_total": len(review_rows),
        "not_activated_by_fuzzy_or_equiv_only": sorted(notact),
        "unsettled_raw_ids": len(pipes), "unsettled_raw_ids_with_clean_looking_name": len(clean_pipes),
        "clean_looking_raw_top": [[g, dims[g]["model_name"], int(units[g])] for g in sorted(clean_pipes, key=lambda g: -units[g])[:25]],
        "provisional": sum(1 for s in subj.values() if s["identity_status"] == "provisional"),
        "settled_ids_with_registration_code_tokens": sorted(g for g, d in dA.items() if d["primary_reason"] == "PROVIDER_RAW_NAME" and subj[g]["identity_status"] == "settled")}

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
    """Everything the committed results derive from: runs A and B with every relation read from the verified PR #200 full export, the reconciliation against the frozen
    b132a86 baseline, the market-activity routing, and the PROVISIONAL adjudication rows."""
    export = ir_export.load()
    A = shadow_run.run("A", package_path, export=export)
    B = shadow_run.run("B", package_path, pkg=A["package"], export=export)
    summary = analyse(A, B)
    notes = yaml.safe_load((Path(__file__).with_name("analyst_notes.yaml")).read_text(encoding="utf-8"))["create_verdicts"]
    base = post_ir.load_baseline()
    creates = sorted(c["id"] for c in summary["creates"])
    r6 = calibration.load_r6()
    m5 = post_ir.build_m5(A, B, export, base, creates, r6)
    m5["activity_classes_informational"] = _activity(summary["creates"], A["package"])
    summary["m5"] = m5
    mk = post_ir.market(A, creates)
    rows = calibration.adjudication_rows(A, creates, notes, r6, A["catalog"]["verification"]["redirects"], base["creates"], base["relations"], mk, m5)
    return A, B, summary, rows


def write_transitions(rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["model_group_id"])
        w.writeheader()
        w.writerows(rows)


def write_routing(summary: dict, out: Path) -> None:
    m = summary["m5"]
    rt, par = m["routing"], m["ir_parity_status"]
    with (out / "dispatch_manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["external_id", "bootstrap_outcome", "activity_state", "review_flags", "lane", "activation_authorized", "activation_blockers", "why"])
        for r in rt["dispatch"]:
            if r["bootstrap_outcome"] == "CREATE_IDENTITY":
                w.writerow([r["external_id"], r["bootstrap_outcome"], r["activity_state"], "|".join(r["review_flags"]), r["lane"], "NO" if not r["activation_authorized"] else "YES", "|".join(r["activation_blockers"]), r["why"]])
    with (out / "cross_brand_review.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["external_id", "bootstrap_outcome", "flag", "mandatory_owner_review", "evidence"])
        for g, v in rt["general_cross_brand_list"].items():
            w.writerow([g, v["bootstrap_outcome"], "POSSIBLE_EXISTING_IDENTITY_CROSS_BRAND", "YES" if rt["reviews"].get(g, {}).get("mandatory_owner_review") else "no (not a CREATE)", json.dumps(v["evidence"], sort_keys=True)])
        for g, v in rt["reviews"].items():
            if g not in rt["general_cross_brand_list"] and v["flags"]:
                w.writerow([g, "CREATE_IDENTITY", "|".join(v["flags"]), "no (advisory)", json.dumps(v["evidence"], sort_keys=True)])
    with (out / "parity_unresolved.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["external_id", "status", "reasons"])
        for g in sorted(par):
            if par[g]["status"] != "IR_PARITY_RESOLVED":
                w.writerow([g, par[g]["status"], " ; ".join(par[g]["reasons"])])
    with (out / "dry_run_vs_bootstrap.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["external_id", "ir_dry_run_outcome", "ir_primary_code", "ir_target_ids", "bootstrap_mode_A"])
        for x in m["dry_run_vs_bootstrap"]["divergent"]:
            w.writerow([x["id"], x["ir_outcome"], x["ir_primary"], "|".join(x["ir_targets"]), x["bootstrap"]])
    (out / "collision_analysis.json").write_text(json.dumps(m["collisions"], ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


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
    write_transitions(summary["m5"]["transitions"], args.out / "transitions_vs_b132a86.csv")
    write_transitions(summary["m5"]["round_delta"]["moved"], args.out / "transitions_vs_30d2618a.csv")
    write_market(A, summary, args.out)
    write_routing(summary, args.out)
    print((args.review_dir or Path(__file__).with_name("review")) / "create_adjudication.csv")
    return 0


# ---------------------------------------------------------------------------------------------------------------- markdown
def _table(head: list[str], rows: list[list]) -> str:
    esc = lambda x: str(x).replace("|", "\\|")
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]) + "\n"



def _m5_md(s: dict, m: dict) -> str:
    pr, par = m["pr200"], m["parity"]
    lx, pp, sub = par["lexical_relations"], par["candidate_pools"], par["subjects"]
    L = ["## 0. Final reconciliation against PR #200's full pair-level relation export\n",
         f"- Producer: PR #200 commit `{pr['commit']}`; export `{pr['export_id']}`, schema `{pr['schema_version']}`, consumer contract `{pr['consumer_contract_version']}`; `MANIFEST.json` sha256 `{pr['manifest_sha256']}`; producer contract {pr['contract']} (draft, not frozen).",
         "- **Every relation Bootstrap saw is a direct lookup in the verified export** (all nine kinds, both populations). The stand-in matcher is gone: there is no relation generator, no `adjudicate`, and no default for a pair the export lacks. "
         "Ice×Ice orientation (smaller id first; COARSER/FINER flipped on reversal) and ids containing `|` are handled by whole-key lookup.",
         f"- Baseline: {m['baseline']}. Same engine, policy v{m['policy_version']}, package, TDR universe and market-activity policy.\n", "### 0.1 Counts\n"]
    rows = []
    for mode in ("A", "B"):
        for o in ("CREATE_IDENTITY", "IDENTITY_REVIEW", "HOLD"):
            u = m["units_by_bucket_after"][mode][o]
            rows.append([mode, o, m["counts"]["before"][mode].get(o, 0), m["counts"]["after"][mode].get(o, 0), f"{u['lifetime_units']:,}", f"{u['last12_units']:,}"])
    L.append(_table(["Mode", "Outcome", "Before (b132a86)", "After", "Registrations all time (after, info)", "Registrations last 12 m (after, info)"], rows))
    cs = m["create_sets"]
    L.append(f"**{m['groups']} groups. CREATE set: {cs['before']} → {cs['after']}** (added {len(cs['added'])}: {cs['added']}; removed {len(cs['removed'])}: {cs['removed']}; unchanged {cs['unchanged']}). "
             f"Added CREATEs carry {m['units_create_added']['lifetime_units']:,} lifetime / {m['units_create_added']['last12_units']:,} last-12-month registrations; removed {m['units_create_removed']['lifetime_units']:,} / {m['units_create_removed']['last12_units']:,} (information only; volume decides nothing). "
             f"Mode B (force-activate-all stress scenario, not an upper bound) CREATEs: {len(cs['B_creates'])}; in A not B: {cs['in_A_not_B']}; in B not A: {cs['in_B_not_A']}.\n")
    L.append(f"REVIEW/HOLD moves — mode A: {m['review_hold_moves']['A']}; mode B: {m['review_hold_moves']['B']}.\n")
    L.append("### 0.2 Routing of the CREATE set (projection only)\n")
    L.append(_table(["Lane", "Before", "After"], [[l, m["routing_counts"]["before"].get(l, 0), m["routing_counts"]["after"].get(l, 0)] for l in ("CURRENT_DISCOVERY", "ACTIVITY_UNCLASSIFIED", "HISTORICAL_INACTIVE", "OWNER_REVIEW")]))
    ma = m["market_activity"]
    L.append(f"Market activity (Ice absent rows UNKNOWN; complete through {ma['complete_through']}): states {ma['actual']['states']}. What-if, NOT AUTHORITATIVE (assumes ABSENT_IS_ZERO): {ma['what_if_NOT_AUTHORITATIVE']['states']}. "
             "Every record has `activation_authorized = NO`; blockers are listed per record (`IR_PARITY_UNRESOLVED` only where it still applies, always `OWNER_APPROVAL_PENDING`, `GOVERNED_WRITER_NOT_BUILT`).\n")
    L.append("### 0.3 Parity with the export\n")
    L.append(_table(["Population", "Evaluated pairs", "Pairs read by the shadow", "All read", "Relations passed to Bootstrap", "Snapshot relations not in export / relabelled", "Counts equal manifest (all 9 kinds)"],
                    [[k, lx[k]["evaluated_pairs"], lx[k]["pairs_read_by_the_shadow"], lx[k]["all_pairs_read"], lx[k]["relations_passed_to_bootstrap"], len(lx[k]["snapshot_relations_not_in_export_or_relabelled"]), lx[k]["counts_equal_manifest_for_all_nine_kinds"]] for k in ("ice_ice", "ice_tdr")]))
    L.append(f"**Candidate-pool parity:** subjects {pp['subjects']}; shadow candidates outside the export pool: {len(pp['shadow_candidates_outside_pool'])}; pool members not read: {len(pp['pool_members_not_read'])}; empty pools {pp['subjects_with_empty_pool']} (no TDR relation exists; not a CREATE authorization). "
             f"The consumer's own brand/catalog-alias candidate set (every TDR model of the locally hinted brand family; a diagnostic that never decides a pool) differed from the export pool for {pp['old_brand_family_candidates_differing_from_pool']} subjects: {pp['old_vs_pool_by_kind']}.\n")
    L.append(f"**Subjects:** {sub['resolved']} meet every consumer-contract requirement and clear `IR_PARITY_UNRESOLVED` (the owner and governed-writer blockers are untouched); **{sub['unresolved']} remain unresolved**: {sub['unresolved_ids_and_reasons'] or 'none'}.\n")
    rd = m["round_delta"]
    L.append(f"**Relation-first brand parity (this round).** Bootstrap's brand, brand relation and brand family now come from the producer's pool and typed brand relation (`br`) only; the local brand/catalog-alias table is a diagnostic and a spelling source and can neither add a pool member nor change a relation. "
             f"Against the accepted 30d2618a head {len(rd['moved'])} subject rows moved (`transitions_vs_30d2618a.csv`); Bootstrap outcomes (CREATE / REVIEW / HOLD) did not move.\n")
    L.append(_table(["Subject", "Producer pool (brand × n)", "Typed relation", "Local hint vs producer", "Before → after parity", "Verifiable?", "Why"],
                    [[g, f"{', '.join(c['producer_pool_brands']) or 'none'} × {c['producer_pool_size']}", c["producer_typed_brand_relation"], c["local_hint_vs_producer"], f"UNRESOLVED → {c['after_status'].replace('IR_PARITY_', '')}",
                      "yes" if c["parity_verifiable"] else "NO (INSUFFICIENT_DATA)", c["why"]] for g, c in rd["brand_parity_cases"].items()]))
    dr = m["dry_run_vs_bootstrap"]
    L.append("**Reference evaluator's dry-run vs Bootstrap (mode A)** — different questions (link vs existence), reported separately: " + "; ".join(f"{k} {n}" for k, n in dr["cross_tab"].items()) + ". "
             f"Divergences to inspect ({len(dr['divergent'])}, `dry_run_vs_bootstrap.csv`); CREATEs for which IR's dry run found a candidate: {[x['id'] for x in dr['divergent'] if x['bootstrap'] == 'CREATE_IDENTITY']}.\n")
    L.append("### 0.4 Structural conflicts\n")
    st = m["structural"]
    L.append(_table(["Mode", "Before", "After", "Left", "Entered"], [[k, v["before"], v["after"], len(v["left"]), f"{len(v['entered'])}: {', '.join(v['entered'][:15])}"] for k, v in st.items()]))
    L.append("Of the conflicts after, " + "; ".join(f"mode {k}: {len(v['of_which_brand_level_alias_related'])} are BRAND-level (the producer's typed brand relation is ALIAS_RELATED, a suspicion, not a name-structure conflict)" for k, v in st.items()) + ".\n")
    L.append(f"### 0.5 Every changed subject ({len(m['transitions'])}; full table with TDR candidate ids, relation evidence and codes: `transitions_vs_b132a86.csv`)\n")
    L.append(_table(["Group", "Name", "Units (info)", "A before", "A after", "B before", "B after", "TDR ids involved", "Relation changes"],
                    [[t["model_group_id"], t["name"], t["lifetime_units"], t["A_before"], t["A_after"], t["B_before"], t["B_after"], t["tdr_candidate_ids_involved"], t["relation_changes"]]
                     for t in sorted(m["transitions"], key=lambda t: -t["lifetime_units"])[:80]]))
    L.append("### 0.6 CREATEs added and removed\n")
    L.append(_table(["Group", "Change", "A before → after", "TDR ids involved", "Relation evidence", "Codes after"],
                    [[g, "ADDED", f"{d['A_before']} → {d['A_after']}", d["tdr_candidate_ids_involved"], d["relation_changes"], d["A_codes_after"]] for g, d in m["added_detail"].items() if d]
                    + [[g, "REMOVED", f"{d['A_before']} → {d['A_after']}", d["tdr_candidate_ids_involved"], d["relation_changes"], d["A_codes_after"]] for g, d in m["removed_detail"].items() if d]))
    L.append("### 0.7 Existing-identity collision analysis of the CREATE set (closest pool members by the export's own score; IR dry run; routing flags)\n")
    flagged = [c for c in m["collisions"] if c["collision_signal"]]
    L.append(f"{len(flagged)} of {len(m['collisions'])} CREATEs carry a collision signal (a non-CONTRADICTION relation to a pooled TDR model, an IR dry-run link outcome, or a mandatory owner review). Full list: `collision_analysis.json`.\n")
    L.append(_table(["Group", "Name", "Pool", "Non-CONTRADICTION relations", "IR dry run", "Flags"], [[c["id"], c["name"], c["pool_size"], ", ".join(c["non_contradiction_relations"]) or "none", " / ".join(str(x) for x in c["ir_dry_run"] if x), "|".join(c["review_flags"]) or "-"] for c in flagged]))
    rt = m["routing"]
    L.append("Mandatory `OWNER_REVIEW` (POSSIBLE_EXISTING_IDENTITY_CROSS_BRAND): " + (", ".join(g for g, r in rt["reviews"].items() if r["mandatory_owner_review"]) or "none") + ". General evidence-driven list: " + ", ".join(f"{g} ({v['bootstrap_outcome']})" for g, v in rt["general_cross_brand_list"].items()) + ".\n")
    L.append("Provisional owner-adjudication set: `shadow/review/create_adjudication.csv` (owner fields blank; QA pending; not a truth set).\n")
    return "\n".join(L)


def render_md(s: dict) -> str:
    i, b = s["inputs"], s["buckets"]
    L = [f"# Identity Bootstrap shadow run — Ice `{i['package_index']['period']}` v{i['package_index']['version']} M{i['package_index']['master_version']}\n",
         "> Generated by `python -m identity_bootstrap.shadow`. **Read-only offline evaluation. Nothing was written; no identity was created.** Registration volume is informational only.\n",
         f"- Package sha256 `{i['package_sha256']}` (pinned). {i['groups']} model groups; {i['units_total']:,} registrations in total ({i['units_last12']:,} in the last 12 months).",
         f"- Status mix (adapter): {i['status_mix']}. Policy v{i['policy_version']} `{i['policy_digest'][:23]}…`. TDR side: **{i['tdr_catalog']['models']} models / {i['tdr_catalog']['brands']} brands from {i['tdr_catalog']['source']}**.",
         "- Mode **A**: a lexical stand-in for Identity Resolution lets duplicates of a TDR model stop at the resolver (`NOT_ACTIVATED`). Mode **B** (force-activate-all STRESS scenario, not an upper bound): every group is offered to Bootstrap as `NO_CANDIDATE`.\n",
         ]
    if s.get("m5"):
        L.append(_m5_md(s, s["m5"]))
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
    L.append(f"- Review decisions (mode A): {r['review_total']}.")
    L.append(f"- `NOT_ACTIVATED` only because of a FUZZY / token-equivalence / alias relation (no EQUAL match), i.e. export matches worth a human look: {r['not_activated_by_fuzzy_or_equiv_only']}.")
    L.append(f"- Unsettled raw ids held: {r['unsettled_raw_ids']} (`BRAND|MODEL`), of which **{r['unsettled_raw_ids_with_clean_looking_name']}** have a clean-looking name (held correctly by contract; they become CREATE candidates only after Ice settles them). Provisional: {r['provisional']}. Settled ids that are registration codes: {len(r['settled_ids_with_registration_code_tokens'])}.")
    L.append(_table(["Raw id", "Name", "Units"], r["clean_looking_raw_top"]))
    L.append("## 6. Structural conflicts (every group carrying `STRUCTURAL_CONFLICT`)\n")
    for mode in ("A", "B"):
        L.append(f"**Mode {mode}: {len(s['structural_conflicts'][mode])} groups**\n")
        L.append(_table(["Group", "Name", "Outcome", "Codes", "Batch group", "Units"],
                        [[c["id"], c["name"], c["outcome"], " ".join(c["codes"]), ", ".join(c["group"]), f"{c['units_total']:,}"] for c in s["structural_conflicts"][mode]]))
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
