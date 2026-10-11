"""Market-activity routing over the M7 shadow run. Measurement only: reads the run, never feeds back into any Bootstrap decision."""
from __future__ import annotations

import collections
import json
from pathlib import Path

from identity_bootstrap.market_activity import classify, load_policy

from . import run as shadow_run

REPRESENTATIVE = ["toyota-toyota-sienta", "honda-jazz", "toyota-vios", "nissan-note", "nissan-nissan-march"]
# Ice's absent-row capability is UNKNOWN until Q-ICE-ABSENT-ROW is confirmed (PR #200 provider_capabilities). This is the ONLY authoritative scenario.
CAP_ACTUAL = {"absent_row": "UNKNOWN"}


def cap_hypothetical(periods: list[str]) -> dict:
    """NOT AUTHORITATIVE: what the numbers would be if Ice confirmed ABSENT_IS_ZERO for the whole package. Labelled as a what-if wherever it appears."""
    return {"absent_row": "ABSENT_IS_ZERO", "coverage_guarantee": "WHAT-IF ONLY (not confirmed)", "covered_from": periods[0], "covered_to": periods[-1]}


def classify_all(run_a: dict, ids: list[str], pol: dict | None = None) -> dict:
    pkg = run_a["package"]
    pol = pol or load_policy()
    periods = pkg["all_periods"]
    out = {}
    for scen, cap in (("actual", CAP_ACTUAL), ("what_if_absent_is_zero", cap_hypothetical(periods))):
        out[scen] = {g: classify(pkg["monthly"].get(g, {}), periods, cap, pol) for g in ids}
    return out


def summarise(res: dict[str, dict]) -> dict:
    return {"states": dict(collections.Counter(r["state"] for r in res.values())), "lanes": dict(collections.Counter(r["lane"] for r in res.values()))}


def build(run_a: dict, pol: dict | None = None) -> dict:
    creates = sorted(d["subject"]["entity_id"] for d in run_a["decisions"] if d["outcome"] == "CREATE_IDENTITY")
    allids = sorted(d["subject"]["entity_id"] for d in run_a["decisions"])
    res = classify_all(run_a, creates, pol)
    pkg = run_a["package"]
    periods = pkg["all_periods"]
    names = {r["model_group_id"]: r["model_name"] for r in pkg["dims"]}
    rep = {}
    for g in REPRESENTATIVE:
        rep[g] = {"name": names.get(g), "in_create_set": g in creates, "last_24_months": {p: pkg["monthly"].get(g, {}).get(p) for p in periods[-24:]},
                  "actual": {k: res["actual"][g][k] for k in ("state", "reason", "lane")} if g in res["actual"] else None,
                  "what_if_absent_is_zero": {k: res["what_if_absent_is_zero"][g][k] for k in ("state", "reason", "lane")} if g in res["what_if_absent_is_zero"] else None}
    return {"policy": pol or load_policy(), "package_periods": [periods[0], periods[-1], len(periods)],
            "explicit_zero_rows_in_package": 0, "create_candidates": len(creates),
            "actual": {"scenario": "Ice absent-row semantics UNKNOWN (Q-ICE-ABSENT-ROW open): a missing row is never a zero", **summarise(res["actual"])},
            "what_if_absent_is_zero": {"scenario": "NOT AUTHORITATIVE: assumes every missing row in 2564-01..2569-09 is a guaranteed zero", **summarise(res["what_if_absent_is_zero"])},
            "per_group": {g: {"actual": res["actual"][g]["state"], "what_if": res["what_if_absent_is_zero"][g]["state"], "reason_actual": res["actual"][g]["reason"],
                              "inactive_since_what_if": res["what_if_absent_is_zero"][g]["inactive_since"]} for g in creates},
            "representative": rep, "all_groups_actual": summarise(classify_all(run_a, allids, pol)["actual"])}


def render_md(s: dict) -> str:
    L = ["# Market-activity routing of the M7.0 CREATE candidates (routing only)\n",
         "> Separate step before current-market Bootstrap activation. It does not change any CREATE / REVIEW / HOLD outcome and does not say whether an identity exists; "
         "`INACTIVE_INFERRED` identities keep their canonical identity and are routed to a historical/inactive lane. Parameters are proposals (`market_activity/policy.yaml`).\n",
         f"- Package months: {s['package_periods'][0]} … {s['package_periods'][1]} ({s['package_periods'][2]}). **Explicit zero rows in the package: {s['explicit_zero_rows_in_package']}** — a zero month only ever appears as a missing row, so no true zero can be established until Ice's `ABSENT_IS_ZERO` is confirmed.",
         f"- CREATE candidates classified: **{s['create_candidates']}**.\n",
         "## Result", f"**Actual (authoritative): {s['actual']['scenario']}** — states {s['actual']['states']}; lanes {s['actual']['lanes']}.\n",
         f"**What-if (non-authoritative): {s['what_if_absent_is_zero']['scenario']}** — states {s['what_if_absent_is_zero']['states']}; lanes {s['what_if_absent_is_zero']['lanes']}.\n",
         "## Representative dormant models — monthly registrations, last 24 months (`·` = no row)\n"]
    ps = list(next(iter(s["representative"].values()))["last_24_months"])
    L.append("| Group | " + " | ".join(p[2:] for p in ps) + " | Actual | What-if |")
    L.append("|---|" + "---|" * (len(ps) + 2))
    for g, r in s["representative"].items():
        cells = ["·" if r["last_24_months"][p] is None else str(int(r["last_24_months"][p])) for p in ps]
        L.append(f"| {g} | " + " | ".join(cells) + f" | {r['actual']['state'] if r['actual'] else 'not a CREATE'} | {r['what_if_absent_is_zero']['state'] if r['what_if_absent_is_zero'] else 'not a CREATE'} |")
    L.append("\nWhy: " + "; ".join(f"{g}: {r['actual']['reason']}" for g, r in s["representative"].items() if r["actual"]) + "\n")
    L.append("## Per CREATE candidate\n")
    L.append("| Group | Actual | What-if | Last inferred-inactive spell began (what-if) |\n|---|---|---|---|")
    for g, r in s["per_group"].items():
        L.append(f"| {g} | {r['actual']} | {r['what_if']} | {r['inactive_since_what_if'] or ''} |")
    return "\n".join(L) + "\n"


def main(out: Path) -> None:
    a = shadow_run.run("A")
    s = build(a)
    out.mkdir(parents=True, exist_ok=True)
    (out / "market_activity.json").write_text(json.dumps(s, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "market_activity.md").write_text(render_md(s), encoding="utf-8")
    print(json.dumps({k: s[k] for k in ("actual", "what_if_absent_is_zero")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    import sys
    main(Path(sys.argv[1]))
