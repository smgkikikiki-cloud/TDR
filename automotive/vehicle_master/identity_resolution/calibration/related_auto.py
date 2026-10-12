"""Rev 5 impact measurement: what changes when a RELATED brand is allowed to reach AUTO (owner decision `od_related_brand_auto_eligible`, 2026-10-12).

    cd automotive/vehicle_master
    python -m identity_resolution.calibration.related_auto collect   # needs the archived M7.0 package; writes calibration/related_auto/
    python -m identity_resolution.calibration.related_auto verify    # offline: the committed measurement is self-consistent and agrees with the committed rev 4 export

Method. The SAME snapshot (the series-carrying M7.0 package, binding false) is resolved twice by the SAME reference evaluator: once under the rev 4 baseline policy (`policy_baseline.rev4_baseline()`:
`brand_relations_auto_eligible` without ALIAS_RELATED, no `chery_jetour` class) and once under the live rev 5 policy. The rev 4 run is cross-checked against the committed rev 4 relation export
(every subject's outcome, primary code and targets), so the baseline is the accepted one and not a re-interpretation. Nothing in the rev 4 evidence is rewritten; this directory is a new, versioned file set.

What it reports: every decision that moved, every RELATED-brand candidate pair in the M7.0 pools with the first gate that stops it, the newly AUTO-eligible pairs (the false-AUTO exposure: pairs the machine
would write at AUTO that no owner has labelled), and the brand alias classes involved with their provenance. It tunes nothing and labels nothing.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import json
from pathlib import Path

from identity_resolution.contract import loader

from . import adapters as A
from . import policy_baseline as PB
from . import ref_eval_core as P
from . import ref_eval_resolve as R
from . import relation_export as E

OUT = A.CALIBRATION_DIR / "related_auto"
SCHEMA = "ir-related-auto-impact/1"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def canonical_json(obj) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def f6(x):
    return None if x is None else round(float(x), 6)


def csv_bytes(columns, rows) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        w.writerow(["" if r.get(c) is None else ("|".join(map(str, r[c])) if isinstance(r[c], (list, tuple)) else str(r[c])) for c in columns])
    return buf.getvalue().encode("utf-8")


def signature(d: dict) -> tuple:
    return (d["outcome"], d.get("primary") or "", tuple(sorted(d.get("target_ids", []) or [])), d.get("link_type") or "", tuple(sorted(c for c, _ in d["codes"])))


def first_gate(pair: dict, ev: dict | None, decision: dict) -> str:
    """The first gate, in the evaluator's own order, that keeps a candidate from AUTO; AUTO_ELIGIBLE if none does."""
    if ev is None:
        return f"NOT_EVALUATED ({decision['outcome']}/{decision.get('primary') or ''})"
    if ev["excluded"]:
        return "EXCLUDED:" + ev["excluded"][0]
    e = pair["evidence"]
    if e["name"]["relation"] not in P.NAME_AUTO:
        return "NAME_RELATION_" + e["name"]["relation"]
    if not ev["series_strong"]:
        return "SERIES_" + e["series"]["state"]
    blocks = [x for x in ev["block"] if x != "NAME_ONLY_NOT_AUTO"]
    if blocks:
        return "BLOCK:" + blocks[0]
    return "AUTO_ELIGIBLE" if ev["auto_ok"] else "NOT_AUTO:OTHER"


def run_pair(snapshot: dict) -> tuple[dict, dict]:
    live = R.resolve(snapshot)
    with PB.rev4_baseline():
        base = R.resolve(snapshot)
    return base, live


def measure(ice: dict, ext: dict) -> dict:
    snapshot = A.build_snapshot(ice, ext)
    subjects = {s["entity_id"]: s for s in snapshot["subjects"]}
    base, live = run_pair(snapshot)
    # the rev 4 run must be the accepted rev 4 outcome: cross-check against the committed export
    exported = {r["id"]: r for r in E.load_rows(E.OUT / E.FILES["ice_subjects"])}
    mismatch = []
    for gid, d in base["decisions"].items():
        x = exported[gid]["outcome"]
        if (d["outcome"], d.get("primary") or "", sorted(d.get("target_ids", []) or [])) != (x["outcome"], x["primary_code"], sorted(x["target_ids"])):
            mismatch.append(gid)
    prov = loader.load_policy()["alias_provenance"]
    changed, related, outcomes = [], [], {"rev4": collections.Counter(), "rev5": collections.Counter()}
    for gid in sorted(live["decisions"]):
        b, l = base["decisions"][gid], live["decisions"][gid]
        outcomes["rev4"][b["outcome"]] += 1
        outcomes["rev5"][l["outcome"]] += 1
        s = subjects[gid]
        if signature(b) != signature(l):
            changed.append({"group": gid, "brand": s["brand"], "name": s["display_name"], "units": int(sum(x or 0 for x in (s.get("series") or {}).get("counts", []))) if s.get("series") else None,
                            "rev4_outcome": b["outcome"], "rev4_primary": b.get("primary") or "", "rev4_targets": b.get("target_ids", []), "rev5_outcome": l["outcome"], "rev5_primary": l.get("primary") or "",
                            "rev5_targets": l.get("target_ids", []), "codes_added": sorted({c for c, _ in l["codes"]} - {c for c, _ in b["codes"]}), "codes_removed": sorted({c for c, _ in b["codes"]} - {c for c, _ in l["codes"]})})
        evals = {tuple(sorted(e["c"]["target_ids"])): e for e in (l.get("_evals") or [])}
        for pair in live["pools"].get(gid, []):
            if len(pair["target_ids"]) != 1:
                continue
            ev = pair["evidence"]
            if (ev["brand"] or {}).get("relation") != "ALIAS_RELATED":
                continue
            e = evals.get(tuple(pair["target_ids"]))
            gate = first_gate(pair, e, l)
            ser, nm = ev["series"], ev["name"]
            related.append({"group": gid, "subject_brand": s["brand"], "subject_name": s["display_name"], "target": pair["target_ids"][0], "alias_class": ev["brand"].get("alias_id") or "",
                            "alias_provenance": prov.get(ev["brand"].get("alias_id") or "", ""), "name_relation": nm["relation"], "series_state": ser["state"], "correlation": f6(ser.get("correlation")),
                            "ratio": f6(ser.get("ratio")), "common_months": ser.get("common_months"), "subject_units": ser.get("subject_units"), "target_units": ser.get("target_units"),
                            "body": (ev["attributes"] or {}).get("body"), "lifecycle": (ev["attributes"] or {}).get("lifecycle"), "first_gate_stopping_auto": gate,
                            "auto_eligible_rev5": gate == "AUTO_ELIGIBLE", "decision_rev4": b["outcome"], "decision_rev5": l["outcome"], "chosen_rev5": pair["target_ids"][0] in (l.get("target_ids") or [])})
    funnel = collections.Counter(r["first_gate_stopping_auto"] for r in related)
    classes = collections.Counter(r["alias_class"] for r in related)
    eligible = [r for r in related if r["auto_eligible_rev5"]]
    return {
        "schema": SCHEMA, "contract": {"baseline_revision": PB.rev4_policy()["policy"]["revision"], "live_revision": loader.load_policy()["policy"]["revision"], "binding": loader.load_adoption()["binding"]},
        "baseline_pins": {"policy_rev4_sha256": sha256_file(PB.REV4_POLICY), "ref_eval_core_rev4_sha256": sha256_file(PB.REV4_EVALUATOR), "policy_live_sha256": sha256_file(loader.contract_dir() / "policy.yaml"),
                          "ref_eval_core_live_sha256": sha256_file(Path(P.__file__)), "policy_delta": sorted(PB.delta(loader.load_policy(), PB.rev4_policy()))},
        "package_sha256": ice["sha256"], "subjects": len(subjects),
        "baseline_cross_check": {"export_manifest_sha256": sha256_file(E.OUT / "MANIFEST.json"), "subjects_compared": len(base["decisions"]), "mismatches": mismatch},
        "outcomes": {k: dict(sorted(v.items())) for k, v in outcomes.items()},
        "changed_decisions": changed,
        "related_pairs": {"count": len(related), "subjects_with_related_candidates": len({r["group"] for r in related}), "first_gate_funnel": dict(sorted(funnel.items())), "by_alias_class": dict(sorted(classes.items())),
                          "auto_eligible_rev5": len(eligible), "auto_eligible_units": sum(r["subject_units"] or 0 for r in eligible)},
        "false_auto_exposure": {"newly_auto_groups": [c["group"] for c in changed if c["rev5_outcome"] == "AUTO" and c["rev4_outcome"] != "AUTO"],
                                "newly_auto_eligible_pairs": [(r["group"], r["target"]) for r in eligible],
                                "auto_groups_rev4": outcomes["rev4"]["AUTO"], "auto_groups_rev5": outcomes["rev5"]["AUTO"],
                                "assumption_provenance_classes_now_auto_capable": sorted(c for c in {a["id"] for a in loader.load_policy()["aliases"]["brand"] if a["relation"] == "RELATED"} if prov.get(c) == "assumption"),
                                "owner_labels_on_these_pairs": 0},
        "_related_rows": related}


COLUMNS_REL = ["group", "subject_brand", "subject_name", "target", "alias_class", "alias_provenance", "name_relation", "series_state", "correlation", "ratio", "common_months", "subject_units", "target_units", "body",
               "lifecycle", "first_gate_stopping_auto", "auto_eligible_rev5", "decision_rev4", "decision_rev5", "chosen_rev5"]
COLUMNS_CHG = ["group", "brand", "name", "units", "rev4_outcome", "rev4_primary", "rev4_targets", "rev5_outcome", "rev5_primary", "rev5_targets", "codes_added", "codes_removed"]


def render_report(m: dict) -> str:
    c, rp, fx = m["contract"], m["related_pairs"], m["false_auto_exposure"]
    w = []
    w.append(f"# Rev {c['live_revision']} impact — a RELATED brand may reach AUTO (measured against the accepted rev {c['baseline_revision']} baseline)\n")
    w.append(f"> Owner decision `od_related_brand_auto_eligible` (2026-10-12). **Draft, `binding: {str(c['binding']).lower()}`, not frozen.** The same M7.0 snapshot ({m['subjects']} Ice model groups) was resolved by the same reference evaluator under the rev {c['baseline_revision']} baseline policy "
             f"and under the live rev {c['live_revision']} policy. The rev {c['baseline_revision']} run reproduces the committed relation export for all {m['baseline_cross_check']['subjects_compared']} subjects "
             f"({len(m['baseline_cross_check']['mismatches'])} mismatches). Nothing from rev {c['baseline_revision']} is rewritten: the export, the calibration outputs, the owner review sheet and the Owner Decision Pack stay the baseline.\n")
    w.append("## Result\n")
    w.append(f"- Decisions that changed: **{len(m['changed_decisions'])}** of {m['subjects']}. AUTO groups: **{fx['auto_groups_rev4']} → {fx['auto_groups_rev5']}**. Newly AUTO groups: **{len(fx['newly_auto_groups'])}**.")
    w.append(f"- RELATED-brand candidate pairs in the M7.0 pools: **{rp['count']}** (in {rp['subjects_with_related_candidates']} subjects). Pairs that pass every AUTO gate under rev {c['live_revision']}: **{rp['auto_eligible_rev5']}**.")
    w.append(f"- **False-AUTO exposure on the real data: {len(fx['newly_auto_eligible_pairs'])} newly AUTO-eligible pairs** (there are no owner labels on any of them: {fx['owner_labels_on_these_pairs']}). The rule is armed, but no M7.0 pair uses it yet.\n")
    w.append("### Outcomes\n")
    keys = sorted(set(m["outcomes"]["rev4"]) | set(m["outcomes"]["rev5"]))
    w.append("| outcome | rev 4 | rev 5 |\n|---|---|---|\n" + "\n".join(f"| {k} | {m['outcomes']['rev4'].get(k, 0)} | {m['outcomes']['rev5'].get(k, 0)} |" for k in keys) + "\n")
    w.append("### Decisions that changed\n")
    if m["changed_decisions"]:
        w.append("| group | brand | rev 4 | rev 5 | codes added |\n|---|---|---|---|---|\n" + "\n".join(
            f"| {x['group'].replace('|', chr(92) + '|')} | {x['brand']} | {x['rev4_outcome']} ({x['rev4_primary']}) | {x['rev5_outcome']} ({x['rev5_primary']}) | {', '.join(x['codes_added']) or '-'} |" for x in m["changed_decisions"]) + "\n")
    else:
        w.append("None.\n")
    w.append("### What stops a RELATED-brand pair from reaching AUTO (first failing gate)\n")
    w.append("| first gate | pairs |\n|---|---|\n" + "\n".join(f"| {k} | {v} |" for k, v in rp["first_gate_funnel"].items()) + "\n")
    w.append("By alias class: " + ", ".join(f"`{k}` {v}" for k, v in rp["by_alias_class"].items()) + ". Per-pair detail: `related_pairs.csv`.\n")
    w.append("## Reading the numbers\n")
    w.append("- The brand relation only removes the brand cap. Name, series, body, lifecycle, gap, lineage, margin, cardinality and state gates are unchanged (SPEC I20), so a related-brand pair is as AUTO as the same pair under an equal brand and no more.")
    w.append("- JETOUR is a separate marque related to Chery (`chery_jetour`, RELATED, owner-seed provenance). The only M7.0 JETOUR group has an unspecified name (3 units), so the new class moves it from `NO_CANDIDATE` (brand not in the pool) to `INSUFFICIENT_DATA` and creates no AUTO pair.")
    w.append(f"- Classes now AUTO-capable whose provenance is still `assumption`: {', '.join('`' + x + '`' for x in fx['assumption_provenance_classes_now_auto_capable']) or 'none'}. They are the owner's to confirm (`alias_assumptions`); an AUTO through them is only as sound as that assumption.")
    w.append("- Behaviour that changes without changing any M7.0 decision: a RELATED candidate whose target is held by another subject's APPROVED / LOCKED claim now raises `STRUCTURAL_REVIEW` (as an equal-brand candidate does) instead of being silently excluded; covered by `classify.related-brand-twin-claim-conflict-protected-target`.")
    w.append("- This is a dry run on one package; it says nothing about future packages. Whether any RELATED pair is *correct* is an owner question (R6 pair verdicts), and AUTO remains an auditable machine state, not an approval.\n")
    w.append("## Files\n\n`impact.json` (summary), `changed_decisions.csv`, `related_pairs.csv`, `MANIFEST.json`. Regenerate: `python -m identity_resolution.calibration.related_auto collect` (needs the archived M7.0 package); check offline: `... verify`.\n")
    return "\n".join(w) + "\n"


def build_files(m: dict) -> dict[str, bytes]:
    rows = m.pop("_related_rows")
    files = {"impact.json": canonical_json(m), "related_pairs.csv": csv_bytes(COLUMNS_REL, sorted(rows, key=lambda r: (r["group"], r["target"]))),
             "changed_decisions.csv": csv_bytes(COLUMNS_CHG, m["changed_decisions"]), "RELATED_AUTO_IMPACT.md": render_report(m).encode("utf-8")}
    manifest = {"schema": SCHEMA, "files": {n: {"sha256": sha256_bytes(b), "bytes": len(b)} for n, b in sorted(files.items())}, "baseline_pins": m["baseline_pins"], "package_sha256": m["package_sha256"]}
    files["MANIFEST.json"] = canonical_json(manifest)
    return files


def collect() -> dict[str, bytes]:
    files = build_files(measure(A.load_ice_package(), A.load_extracts()))
    OUT.mkdir(parents=True, exist_ok=True)
    for n, b in files.items():
        (OUT / n).write_bytes(b)
    return files


def verify() -> list[str]:
    problems = []
    manifest = json.loads((OUT / "MANIFEST.json").read_text(encoding="utf-8"))
    for n, meta in manifest["files"].items():
        data = (OUT / n).read_bytes()
        if sha256_bytes(data) != meta["sha256"] or len(data) != meta["bytes"]:
            problems.append(f"{n} does not match its manifest entry")
    pins = manifest["baseline_pins"]
    if sha256_file(PB.REV4_POLICY) != pins["policy_rev4_sha256"] or sha256_file(PB.REV4_EVALUATOR) != pins["ref_eval_core_rev4_sha256"]:
        problems.append("the archived rev 4 baseline files changed")
    impact = json.loads((OUT / "impact.json").read_text(encoding="utf-8"))
    if impact["baseline_cross_check"]["export_manifest_sha256"] != sha256_file(E.OUT / "MANIFEST.json"):
        problems.append("the committed rev 4 relation export changed since this measurement")
    if impact["baseline_cross_check"]["mismatches"]:
        problems.append("the rev 4 run did not reproduce the committed export")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["collect", "verify"])
    a = ap.parse_args(argv)
    if a.command == "collect":
        collect()
        return 0
    problems = verify()
    print("\n".join(problems) if problems else "rev 5 impact measurement is consistent")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
