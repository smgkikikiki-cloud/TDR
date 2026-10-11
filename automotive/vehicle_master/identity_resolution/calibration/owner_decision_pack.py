"""Owner Decision & Calibration Preparation Pack: what the owner has to decide, in what order, with the evidence next to it.

    cd automotive/vehicle_master
    python -m identity_resolution.calibration.owner_decision_pack collect   # needs the archived M7.0 package; writes owner_decision_pack/inputs/series_evidence.json
    python -m identity_resolution.calibration.owner_decision_pack build     # offline: committed files only; writes the pack
    python -m identity_resolution.calibration.owner_decision_pack verify    # offline: the committed pack is what `build` produces

Scope. Preparation only. It reads committed files: this PR's R6 owner sheet and calibration data, the accepted relation export (`relation_export/`), the
production extracts under `calibration/inputs/`, the repository's catalog brand records (`vehreg/data/2026/models/`) and a byte-pinned copy of four accepted PR #201
artifacts (`owner_decision_pack/inputs/pr201_*`). It changes no rule, no policy value, no export, no label and no sheet; it writes no owner field (every
`owner_*` column is blank) and every machine suggestion is in a column that says `NON_AUTHORITATIVE`. Nothing here is an approval, a CREATE authorisation or a
calibrated value. `adoption.binding` stays `false`.

Two verdict vocabularies are kept apart on purpose (see `verdict_crosswalk.csv`): the R6 sheet's verdicts are about a PAIR (is this Ice group this TDR model?), the PR #201 adjudication
verdicts are about a GROUP's missing canonical identity (should TDR have a model for it?). A pair verdict never implies a missing-identity verdict or the reverse; `check_label_consistency`
only flags labels that contradict each other.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import json
import math
import re
import subprocess
from pathlib import Path

from identity_resolution.contract import loader

from . import adapters as A
from . import ref_eval_core as P
from . import ref_eval_resolve as R
from . import relation_export as E
from . import report as RP
from . import sensitivity as SENS

PACK_ID = "ir-owner-decision-pack/1"
REF_SEP = " ;; "   # evidence references are joined with this, because group ids and pair keys contain "|"
PR201_COMMIT = "30d2618a48b830b4afdbcf1299475f368bd9d214"
OUT = A.CALIBRATION_DIR / "owner_decision_pack"
IN201 = OUT / "inputs" / "pr201_30d2618a4"
SERIES_JSON = OUT / "inputs" / "series_evidence.json"
CATALOG_DIR = A.REPO_ROOT / "automotive" / "vehicle_master" / "vehreg" / "data" / "2026" / "models"
PR201_SOURCES = OUT / "inputs" / "pr201_sources.json"
PR201_FILES = json.loads(PR201_SOURCES.read_text(encoding="utf-8"))["files"]
#: Triage conventions for ORDERING the owner's work (like the tier cutoffs in review.py): not policy, not thresholds of the contract.
TRIAGE = {"current_market_units_last12": 100, "high_volume_lifetime_units": 500, "very_low_volume_lifetime_units": 10, "legacy_strong_name_score": 0.6,
          "series_coincide_min_common_months": 9, "folds": 5, "negative_sample_per_stratum": {"NO_CANDIDATE_ALL_EXCLUDED": 8, "BRND_NOT_IN_TDR": 4},
          "negative_unit_strata": [1000, 100, 10]}
CREATE_VERDICTS = ["VALID_MISSING_CANONICAL", "EXISTING_IDENTITY", "VARIANT_TRIM_CODE", "AMBIGUOUS"]
DISCOVERY_CLASSES = ["RECENT_NEW_MODEL", "ACTIVE_CATALOG_GAP", "HISTORICAL_BACKFILL"]
R6_VERDICTS = ["CORRECT_EQUIVALENT", "CORRECT_PART_OF", "CORRECT_COMPOSED_OF", "WRONG_TARGET", "NO_TDR_TARGET", "INSUFFICIENT_EVIDENCE"]
ALIAS_CLASSES = ["IDENTITY_EQUIVALENT", "SEARCH_DISPLAY_SYNONYM", "BROADER_MODEL_FAMILY", "MISLEADING_ALIAS", "UNRESOLVED"]
RELATED_BRAND_GROUPS = {"MERCEDES AMG": "mercedes_amg_maybach", "MERCEDESBENZ MAYBACH": "mercedes_amg_maybach", "RANGE ROVER": "land_range_rover"}


# ----------------------------------------------------------------------------------------------------------------------------- io helpers
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_csv(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if lines and lines[0].startswith("#"):
        text = "\n".join(lines[1:])
    return list(csv.DictReader(io.StringIO(text, newline="")))


def cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:.6f}".rstrip("0").rstrip(".") if v == v else ""
    if isinstance(v, (list, tuple, set)):
        return "|".join(cell(x) for x in v)
    return str(v)


def csv_bytes(columns: list[str], rows: list[dict]) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        extra = set(r) - set(columns)
        if extra:
            raise KeyError(f"columns not declared: {sorted(extra)}")
        w.writerow([cell(r.get(c)) for c in columns])
    return buf.getvalue().encode("utf-8")


def canonical_json(obj, indent=1) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=indent) + "\n").encode("utf-8")


def ref(file: str, key: str) -> str:
    return f"{file}#{key}"


# ----------------------------------------------------------------------------------------------------------------------------- vendoring PR #201's accepted artifacts
def vendor_pr201(repo: Path = A.REPO_ROOT, commit: str = PR201_COMMIT) -> dict:
    """Copy four accepted PR #201 artifacts, byte for byte, from a git OBJECT (no checkout of PR #201, nothing in PR #201 is touched) and record where they came from."""
    IN201.mkdir(parents=True, exist_ok=True)
    prov = {"what": "byte-pinned copies of accepted PR #201 artifacts; data only, no PR #201 code", "pr": 201, "commit": commit, "files": {}}
    for name, path in PR201_FILES.items():
        raw = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{path}"], check=True, capture_output=True).stdout
        blob = subprocess.run(["git", "-C", str(repo), "rev-parse", f"{commit}:{path}"], check=True, capture_output=True, text=True).stdout.strip()
        (IN201 / name).write_bytes(raw)
        prov["files"][name] = {"source_path": path, "git_blob": blob, "sha256": sha256_bytes(raw), "bytes": len(raw)}
    (IN201 / "PROVENANCE.json").write_bytes(canonical_json(prov))
    return prov


# ----------------------------------------------------------------------------------------------------------------------------- inputs
class Inputs:
    """Everything the pack reads, loaded once. All of it is committed; none of it needs the archived package."""

    def __init__(self):
        cal = A.CALIBRATION_DIR
        self.r6 = read_csv(cal / "r6_owner_review.csv")
        self.groups = {r["model_group_id"]: r for r in read_csv(cal / "r6_calibration_groups.csv")}
        self.summary = json.loads((cal / "calibration_summary.json").read_text(encoding="utf-8"))
        self.sensitivity = json.loads((cal / "sensitivity_results.json").read_text(encoding="utf-8"))
        self.subjects = {r["id"]: r for r in E.load_rows(E.OUT / E.FILES["ice_subjects"])}
        self.pairs_tdr = {(r["a"], r["b"]): r for r in E.load_rows(E.OUT / E.FILES["pairs_ice_tdr"])}
        self.pairs_ice = {(r["a"], r["b"]): r for r in E.load_rows(E.OUT / E.FILES["pairs_ice_ice"])}
        self.export_manifest = json.loads((E.OUT / "MANIFEST.json").read_text(encoding="utf-8"))
        self.models = {m["canonical_id"]: m for m in json.loads((A.INPUTS_DIR / "tdr_models.json").read_text(encoding="utf-8"))}
        self.brands = {b["canonical_id"]: b for b in json.loads((A.INPUTS_DIR / "tdr_brands.json").read_text(encoding="utf-8"))}
        self.crosswalk = {r["model_group_id"]: r for r in json.loads((A.INPUTS_DIR / "r6_crosswalk_rows.json").read_text(encoding="utf-8")) if r["match_method"] != "ADMIN"}
        self.policy = loader.load_policy()
        self.adoption = loader.load_adoption()
        self.adj = read_csv(IN201 / "create_adjudication.csv")
        self.unresolved = read_csv(IN201 / "parity_unresolved.csv")
        self.cross_brand = read_csv(IN201 / "cross_brand_review.csv")
        self.bootstrap = {r["model_group_id"]: r for r in read_csv(IN201 / "decisions.csv")}
        self.series = json.loads(SERIES_JSON.read_text(encoding="utf-8")) if SERIES_JSON.exists() else None
        self.brand_files = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(CATALOG_DIR.glob("*.json"))}
        self.r6_by_group = collections.defaultdict(list)
        for r in self.r6:
            self.r6_by_group[r["model_group_id"]].append(r)
        self.create_ids = [r["external_id"] for r in self.adj]
        self.adj_by_id = {r["external_id"]: r for r in self.adj}


def tdr_brand_record(inp: Inputs, brand_id: str) -> dict:
    """The catalog's own brand record (id, English name, aliases, OEM group) from vehreg/data/2026/models/<brand>.json."""
    b = (inp.brand_files.get(brand_id) or {}).get("brand") or {}
    return {k: b.get(k) for k in ("id", "name_en", "oem_group", "aliases")}


# ----------------------------------------------------------------------------------------------------------------------------- series evidence (needs the package, once)
def _ev(s: dict) -> dict:
    return {"state": s["state"], "correlation": s["correlation"], "ratio": s["ratio"], "common_months": s["common_months"], "subject_units": s["subject_units"],
            "target_units": s["target_units"]}


def collect_series_evidence(ice: dict | None = None, ext: dict | None = None) -> dict:
    """Registration-series evidence the pack quotes, taken from the reference evaluator's own candidate pools over the series-carrying M7.0 snapshot (unchanged evaluator, no rule touched)."""
    inp = Inputs()
    ice, ext = ice or A.load_ice_package(), ext or A.load_extracts()
    snapshot = A.build_snapshot(ice, ext)
    res = R.resolve(snapshot)
    subjects = {s["entity_id"]: s for s in snapshot["subjects"]}
    targets = {t["target_id"]: t for t in snapshot["targets"]}
    wanted = sorted(set(inp.create_ids) | {r["external_id"] for r in inp.unresolved} | {r["external_id"] for r in inp.cross_brand})
    pairs: dict[str, dict] = {}
    for sid in wanted:
        for c in res["pools"][sid]:
            if len(c["target_ids"]) == 1:
                pairs[f"{sid}|{c['target_ids'][0]}"] = _ev(c["evidence"]["series"])
    # for each catalog-alias collision: the series of the target's existing Ice claimants alone and with the provider group added
    sums: dict[str, dict] = {}
    for r in inp.adj:
        if "POSSIBLE_EXISTING_IDENTITY_CATALOG_ALIAS" not in r["review_routing_flags"].split("|"):
            continue
        g = r["external_id"]
        for ev in alias_hits(r):
            t = ev["existing_identity"]
            claimants = sorted(a for (a, b), p in inp.pairs_tdr.items() if b == t and a != g and p["r"] in ("EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV"))
            entry = {"claimants": claimants}
            if claimants:
                alone, _, _ = P.series_evidence(P.sum_series([subjects[a].get("series") for a in claimants]), targets[t].get("series"))
                with_, _, _ = P.series_evidence(P.sum_series([subjects[a].get("series") for a in claimants + [g]]), targets[t].get("series"))
                entry["alone"], entry["with_provider"] = _ev(alone), _ev(with_)
            sums[f"{g}|{t}"] = entry
    return {"schema": "ir-owner-pack-series-evidence/1", "package_sha256": ice["sha256"], "export_manifest_sha256": sha256_file(E.OUT / "MANIFEST.json"),
            "evaluator": "calibration.ref_eval_resolve.resolve()['pools'] and calibration.ref_eval_core.series_evidence (unchanged)", "subjects": wanted, "pairs": pairs, "claimant_sums": sums}


def parse_routing_evidence(text: str) -> list[dict]:
    """PR #201's `review_routing_evidence` column: 'KIND(k=v, k=v); KIND(k=v, ...)'. Values contain no '(' ')' or ', ' in the accepted file (a test pins that)."""
    out = []
    for kind, body in re.findall(r"([A-Z][A-Z0-9_]+)\(([^)]*)\)", text or ""):
        item = {"kind": kind}
        for part in body.split(", "):
            if "=" in part:
                k, v = part.split("=", 1)
                item[k.strip()] = v.strip()
        out.append(item)
    return out


def alias_hits(adj_row: dict) -> list[dict]:
    return [i for i in parse_routing_evidence(adj_row["review_routing_evidence"]) if i["kind"] == "TDR_CATALOG_ALIAS_EQUALS_PROVIDER_NAME"]


# ----------------------------------------------------------------------------------------------------------------------------- small derivations
STATE_RANK = {"STRONG": 0, "WEAK": 1, "UNAVAILABLE": 2}


def f6(x):
    return None if x is None else round(float(x), 6)


def code_like(tokens: list[str]) -> bool:
    """A generic shape test (no brand, no model named): the provider's own name tokens look like a type code rather than a model name."""
    return any(re.fullmatch(r"(?=.*[a-z])(?=.*\d)[a-z0-9]{4,}", t) for t in tokens) or (len(tokens) == 1 and len(tokens[0]) <= 2)


def series_for(inp: Inputs, group: str, target: str) -> dict | None:
    return (inp.series or {"pairs": {}})["pairs"].get(f"{group}|{target}")


def pool_series(inp: Inputs, group: str) -> list[dict]:
    """The group's candidate-pool series evidence, strongest first (STRONG before WEAK before UNAVAILABLE; then higher correlation)."""
    out = []
    for t in inp.subjects[group]["pool"]:
        s = series_for(inp, group, t)
        if s:
            out.append({"target": t, **s, "relation": inp.pairs_tdr[(group, t)]["r"]})
    out.sort(key=lambda x: (STATE_RANK[x["state"]], -(x["correlation"] if x["correlation"] is not None else -2), x["target"]))
    return out


def coincides(s: dict | None) -> bool:
    return bool(s) and s["state"] == "STRONG" and (s["common_months"] or 0) >= TRIAGE["series_coincide_min_common_months"]


def legacy_text(row: dict | None) -> str:
    if not row:
        return "none (no legacy R6 row for this group)"
    return f"{row['status']} {row['canonical_model_id']} ({row['match_method']}, score {round(float(row['score']), 4)})" if row.get("canonical_model_id") else "no-candidate row"


def legacy_strong(row: dict | None) -> bool:
    if not row or not row.get("canonical_model_id"):
        return False
    return row["status"] == "AUTO" or row["match_method"] == "SERIES" or float(row["score"] or 0) >= TRIAGE["legacy_strong_name_score"]


def int0(x) -> int:
    return int(float(x)) if x not in ("", None) else 0


def tdr_record(inp: Inputs, tid: str) -> dict:
    m = inp.models[tid]
    return {"id": tid, "brand_id": m["brand_id"], "name_en": m["name_en"], "name_th": m["name_th"], "status": m["status"], "body_type": m["body_type"], "segment": m["segment"],
            "launch_year": m["launch_year"], "retail_status": m["retail_status"], "market_scope": m["market_scope"], "production_type": m["production_type"], "aliases": list(m["aliases"])}


# ----------------------------------------------------------------------------------------------------------------------------- section A: catalog-alias collisions
ALIAS_COLUMNS = [
    "decision_id", "priority_rank", "priority_basis", "provider_group_id", "provider_name", "provider_brand", "provider_body", "provider_segment", "provider_units_lifetime",
    "provider_units_last12", "provider_activity_state_actual", "provider_first_seen", "provider_last_seen", "matching_alias_strings", "existing_identity_id", "existing_identity_name_en", "existing_identity_name_th",
    "existing_identity_status", "existing_identity_body_type", "existing_identity_segment", "existing_identity_launch_year", "existing_identity_retail_status",
    "existing_identity_market_scope", "existing_identity_production_type", "existing_identity_all_aliases", "export_name_relation", "export_tokens_provider|existing",
    "series_state", "series_correlation", "series_ratio", "series_common_months", "provider_units_in_window", "existing_units_in_window", "other_ice_claimants_equal",
    "other_ice_claimants_granular", "claimants_alone_series", "claimants_plus_provider_series", "legacy_r6", "r6_sheet_ranks", "signals",
    "machine_suggested_alias_class_NON_AUTHORITATIVE", "suggestion_basis_NON_AUTHORITATIVE", "evidence_sufficiency", "also_series_coincident_without_alias_hit", "evidence_refs",
    "owner_alias_class", "owner_provider_verdict", "owner_canonical_model_id", "owner_notes"]


def _fmt_series(s: dict | None) -> str:
    if not s:
        return ""
    return f"{s['state']} corr={f6(s['correlation'])} ratio={f6(s['ratio'])} months={s['common_months']}"


def alias_class_suggestion(sig: set[str]) -> tuple[str, str]:
    """Transparent rules over the signals below; a SEARCH_DISPLAY_SYNONYM is never suggested because the data cannot tell a lookup convenience from an identity assertion."""
    if "SERIES_COINCIDES" in sig and "OTHER_EQUAL_CLAIMANT" not in sig:
        return "IDENTITY_EQUIVALENT", "registrations coincide with the existing model over >= 9 common months and no other Ice group is already EQUAL to it"
    if "OTHER_EQUAL_CLAIMANT" in sig and "ADDING_PROVIDER_IMPROVES_MATCH" in sig:
        return "BROADER_MODEL_FAMILY", "the existing model's other Ice claimant leaves its registrations unexplained and adding this group closes the gap (TDR counts this group's registrations under the model)"
    if "OTHER_EQUAL_CLAIMANT" in sig and "CLAIMANT_ALONE_ALREADY_STRONG" in sig and "SERIES_DOES_NOT_COINCIDE" in sig:
        return "MISLEADING_ALIAS", "the existing model's registrations are already explained by another Ice group and this group's series does not match the model"
    if "BODY_OR_SEGMENT_MISMATCH" in sig and "MANY_GRANULAR_CLAIMANTS" in sig:
        return "MISLEADING_ALIAS", "body and segment differ from the model and the model already has several finer Ice claimants"
    return "UNRESOLVED", "the pack's evidence does not decide between the classes"


def build_alias_table(inp: Inputs) -> list[dict]:
    base = []
    for adj in inp.adj:
        hits = alias_hits(adj)
        if not hits:
            continue
        g = adj["external_id"]
        targets = sorted({h["existing_identity"] for h in hits})
        assert len(targets) == 1, (g, targets)
        base.append((g, targets[0], hits, adj))
    base.sort(key=lambda x: (-int0(x[3]["lifetime_units"]), x[0]))
    grp = inp.groups
    rows = []
    for rank, (g, t, hits, adj) in enumerate(base, start=1):
        m, sub = inp.models[t], inp.subjects[g]
        s = series_for(inp, g, t)
        sums = ((inp.series or {}).get("claimant_sums") or {}).get(f"{g}|{t}", {})
        equal_claim = sorted(a for (a, b), p in inp.pairs_tdr.items() if b == t and a != g and p["r"] in ("EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV"))
        granular = sorted(f"{a}({p['r']})" for (a, b), p in inp.pairs_tdr.items() if b == t and a != g and p["r"] in ("SUBJECT_COARSER", "SUBJECT_FINER"))
        sig = set()
        if coincides(s):
            sig.add("SERIES_COINCIDES")
        elif s and s["state"] != "UNAVAILABLE":
            sig.add("SERIES_DOES_NOT_COINCIDE")
        else:
            sig.add("SERIES_UNAVAILABLE")
        if equal_claim:
            sig.add("OTHER_EQUAL_CLAIMANT")
        alone, withp = sums.get("alone"), sums.get("with_provider")
        if alone and withp:
            if alone["state"] == "STRONG":
                sig.add("CLAIMANT_ALONE_ALREADY_STRONG")
            if (alone["state"] != "STRONG" and withp["state"] == "STRONG") or (alone["correlation"] is not None and withp["correlation"] is not None and withp["correlation"] > alone["correlation"] and abs(1 - (withp["ratio"] or 0)) < abs(1 - (alone["ratio"] or 0))):
                sig.add("ADDING_PROVIDER_IMPROVES_MATCH")
        if len(granular) >= 3:
            sig.add("MANY_GRANULAR_CLAIMANTS")
        ice_body = (grp[g]["ice_body"] or "").lower()
        if ice_body and m["body_type"] and ice_body not in (m["body_type"].lower(), "suv" if m["body_type"] == "CROSSOVER" else "", "pickup" if m["body_type"] == "PICKUP" else ""):
            sig.add("BODY_OR_SEGMENT_MISMATCH")
        if s and s["target_units"] and s["subject_units"] is not None and s["target_units"] >= 10 * max(s["subject_units"], 1):
            sig.add("TARGET_UNITS_AT_LEAST_10X_PROVIDER")
        cls, basis = alias_class_suggestion(sig)
        months = (s or {}).get("common_months") or 0
        sufficiency = "STRONG_PACK_EVIDENCE" if cls in ("IDENTITY_EQUIVALENT", "BROADER_MODEL_FAMILY", "MISLEADING_ALIAS") and (coincides(s) or "ADDING_PROVIDER_IMPROVES_MATCH" in sig or "CLAIMANT_ALONE_ALREADY_STRONG" in sig) \
            else ("THIN" if int0(adj["lifetime_units"]) < TRIAGE["very_low_volume_lifetime_units"] or months < TRIAGE["series_coincide_min_common_months"] else "CONTEXT_ONLY")
        rr = [r["review_rank"] for r in inp.r6_by_group.get(g, [])]
        pr = inp.pairs_tdr[(g, t)]
        refs = [ref("create_adjudication.csv(PR201)", f"external_id={g}"), ref("relation_export/pairs_ice_tdr.jsonl", f"pair={g} -> {t}"), ref("inputs/tdr_models.json", f"canonical_id={t}"),
                ref(f"vehreg/data/2026/models/{m['brand_id']}.json", f"models[id={t.split('.', 1)[1]}]"), ref("owner_decision_pack/inputs/series_evidence.json", f"pairs[{g}|{t}]")] + \
               [ref("r6_owner_review.csv", f"review_rank={x}") for x in rr]
        rows.append({
            "decision_id": f"OD-A{rank:02d}", "priority_rank": rank, "priority_basis": "lifetime units of the provider group, descending (the alias decides how many registrations are counted twice or lost)",
            "provider_group_id": g, "provider_name": adj["provider_model_name"], "provider_brand": adj["provider_brand"], "provider_body": grp[g]["ice_body"], "provider_segment": grp[g]["ice_segment"],
            "provider_units_lifetime": adj["lifetime_units"], "provider_units_last12": adj["last12_units"], "provider_activity_state_actual": adj["market_activity_state_actual"], "provider_first_seen": adj["first_seen"], "provider_last_seen": adj["last_seen"],
            "matching_alias_strings": sorted({h["alias"] for h in hits}), "existing_identity_id": t, "existing_identity_name_en": m["name_en"], "existing_identity_name_th": m["name_th"],
            "existing_identity_status": m["status"], "existing_identity_body_type": m["body_type"], "existing_identity_segment": m["segment"], "existing_identity_launch_year": m["launch_year"],
            "existing_identity_retail_status": m["retail_status"], "existing_identity_market_scope": m["market_scope"], "existing_identity_production_type": m["production_type"],
            "existing_identity_all_aliases": m["aliases"], "export_name_relation": pr["r"], "export_tokens_provider|existing": f"{' '.join(pr['ta'])}|{' '.join(pr['tb'])}",
            "series_state": (s or {}).get("state", ""), "series_correlation": f6((s or {}).get("correlation")), "series_ratio": f6((s or {}).get("ratio")), "series_common_months": (s or {}).get("common_months", ""),
            "provider_units_in_window": (s or {}).get("subject_units", ""), "existing_units_in_window": (s or {}).get("target_units", ""), "other_ice_claimants_equal": equal_claim,
            "other_ice_claimants_granular": granular, "claimants_alone_series": _fmt_series(alone), "claimants_plus_provider_series": _fmt_series(withp), "legacy_r6": legacy_text(inp.crosswalk.get(g)),
            "r6_sheet_ranks": rr, "signals": sorted(sig), "machine_suggested_alias_class_NON_AUTHORITATIVE": cls, "suggestion_basis_NON_AUTHORITATIVE": basis, "evidence_sufficiency": sufficiency,
            "also_series_coincident_without_alias_hit": "", "evidence_refs": refs,
            "owner_alias_class": "", "owner_provider_verdict": "", "owner_canonical_model_id": "", "owner_notes": ""})
    return rows


# ----------------------------------------------------------------------------------------------------------------------------- section D: the 82 provisional CREATE candidates
CREATE_COLUMNS = [
    "decision_id", "priority_rank", "risk_tier", "risk_categories", "provider_group_id", "provider_name", "provider_brand", "brand_family", "fold", "proposed_canonical_id", "proposed_canonical_name",
    "units_lifetime", "units_last12", "first_seen", "last_seen", "pr201_activity_state_actual", "pr201_machine_discovery_class_NON_AUTHORITATIVE", "pr201_routing_flags",
    "pool_size", "best_pool_series", "series_coincident_targets", "legacy_r6", "r6_sheet_ranks", "r6_sheet_tiers", "r6_pair_question_open", "alias_decision_id", "brand_case_id",
    "machine_triage_NON_AUTHORITATIVE", "triage_basis_NON_AUTHORITATIVE", "evidence_sufficiency", "p3_spot_check_sample", "evidence_refs",
    "owner_verdict", "owner_canonical_model_id", "owner_discovery_class", "owner_notes"]
RISK_TIER_ORDER = {"P1_CONTRADICTING_EVIDENCE": 0, "P2_HIGH_IMPACT_OR_AMBIGUOUS": 1, "P3_HISTORICAL_BULK": 2}


def build_create_table(inp: Inputs, alias_rows: list[dict], brand_rows: list[dict]) -> list[dict]:
    alias_of = {r["provider_group_id"]: r["decision_id"] for r in alias_rows}
    brand_of = {r["provider_group_id"]: r["decision_id"] for r in brand_rows}
    cross_create = {r["external_id"] for r in inp.cross_brand if r["bootstrap_outcome"] == "CREATE_IDENTITY" and "CROSS_BRAND" in r["flag"]}
    out = []
    for adj in inp.adj:
        g = adj["external_id"]
        sub = inp.subjects[g]
        lt, l12 = int0(adj["lifetime_units"]), int0(adj["last12_units"])
        legacy = inp.crosswalk.get(g)
        series = pool_series(inp, g)
        coinc = sorted(s["target"] for s in series if coincides(s))
        cats = []
        if g in alias_of:
            cats.append("CATALOG_ALIAS_COLLISION")
        if g in cross_create:
            cats.append("CROSS_BRAND_COLLISION")
        if coinc:
            cats.append("SERIES_COINCIDES_WITH_POOL_MODEL")
        if legacy_strong(legacy):
            cats.append("LEGACY_R6_STRONG_PROPOSAL")
        if l12 >= TRIAGE["current_market_units_last12"] or adj["market_activity_state_actual"] == "ACTIVE":
            cats.append("CURRENT_MARKET")
        if lt >= TRIAGE["high_volume_lifetime_units"]:
            cats.append("HIGH_VOLUME")
        if code_like(sub["tokens"]):
            cats.append("CODE_LIKE_NAME")
        if lt < TRIAGE["very_low_volume_lifetime_units"]:
            cats.append("VERY_LOW_VOLUME")
        if l12 == 0:
            cats.append("NO_REGISTRATIONS_LAST_12_MONTHS")
        contradicting = {"CATALOG_ALIAS_COLLISION", "CROSS_BRAND_COLLISION", "SERIES_COINCIDES_WITH_POOL_MODEL", "LEGACY_R6_STRONG_PROPOSAL"}
        if contradicting & set(cats):
            tier = "P1_CONTRADICTING_EVIDENCE"
        elif {"CURRENT_MARKET", "HIGH_VOLUME", "CODE_LIKE_NAME"} & set(cats):
            tier = "P2_HIGH_IMPACT_OR_AMBIGUOUS"
        else:
            tier = "P3_HISTORICAL_BULK"
        if coinc and g not in alias_of:
            triage, basis = "CHECK_EXISTING_IDENTITY", "a pooled TDR model's registrations coincide with this group's (STRONG, >= 9 common months) although no name relation was found"
        elif g in alias_of:
            triage, basis = "SEE_ALIAS_DECISION", f"a TDR catalog alias equals the provider name ({alias_of[g]})"
        elif g in cross_create:
            triage, basis = "SEE_BRAND_DECISION", "the group sits in a brand/filing collision"
        elif "LEGACY_R6_STRONG_PROPOSAL" in cats:
            triage, basis = "NEEDS_OWNER_JUDGEMENT", "the legacy R6 run proposed a TDR model for this group and the export finds no non-contradictory relation"
        elif tier == "P3_HISTORICAL_BULK":
            triage, basis = "LIKELY_VALID_MISSING_CANONICAL", "no pool candidate with a non-contradictory relation, no series coincidence, no alias or legacy signal, no registrations in the last 12 months or low volume"
        else:
            triage, basis = "LIKELY_VALID_MISSING_CANONICAL_CHECK_NAME", "no contradicting evidence, but current-market volume or a code-like name makes a wrong CREATE costly"
        if tier == "P1_CONTRADICTING_EVIDENCE":
            suff = "NEEDS_ROW_REVIEW"
        elif tier == "P2_HIGH_IMPACT_OR_AMBIGUOUS":
            suff = "NEEDS_ROW_REVIEW"
        else:
            suff = "SUFFICIENT_FOR_SPOT_CHECK_CONFIRMATION" if lt >= TRIAGE["very_low_volume_lifetime_units"] else "THIN_VOLUME_SPOT_CHECK"
        rr = inp.r6_by_group.get(g, [])
        pair_open = [f"{r['review_rank']}:{r['candidate_canonical_model_id'] or 'none'}" for r in rr if r["candidate_canonical_model_id"]]
        best = series[0] if series else None
        refs = [ref("create_adjudication.csv(PR201)", f"external_id={g}"), ref("relation_export/ice_subjects.jsonl", f"id={g}"), ref("owner_decision_pack/inputs/series_evidence.json", f"subjects[{g}]")] + \
               [ref("r6_owner_review.csv", f"review_rank={r['review_rank']}") for r in rr]
        out.append({
            "decision_id": "", "priority_rank": 0, "risk_tier": tier, "risk_categories": cats, "provider_group_id": g, "provider_name": adj["provider_model_name"], "provider_brand": adj["provider_brand"], "brand_family": "", "fold": "",
            "proposed_canonical_id": adj["proposed_canonical_id"], "proposed_canonical_name": adj["proposed_canonical_name"], "units_lifetime": lt, "units_last12": l12, "first_seen": adj["first_seen"],
            "last_seen": adj["last_seen"], "pr201_activity_state_actual": adj["market_activity_state_actual"], "pr201_machine_discovery_class_NON_AUTHORITATIVE": adj["machine_suggested_discovery_class_NON_AUTHORITATIVE"],
            "pr201_routing_flags": adj["review_routing_flags"].split("|"), "pool_size": len(sub["pool"]),
            "best_pool_series": f"{best['target']} {best['state']} corr={f6(best['correlation'])} months={best['common_months']} ({best['relation']})" if best else "",
            "series_coincident_targets": coinc, "legacy_r6": legacy_text(legacy), "r6_sheet_ranks": [r["review_rank"] for r in rr], "r6_sheet_tiers": sorted({r["review_tier"] for r in rr}),
            "r6_pair_question_open": pair_open, "alias_decision_id": alias_of.get(g, ""), "brand_case_id": brand_of.get(g, ""), "machine_triage_NON_AUTHORITATIVE": triage,
            "triage_basis_NON_AUTHORITATIVE": basis, "evidence_sufficiency": suff, "p3_spot_check_sample": "", "evidence_refs": refs, "owner_verdict": "", "owner_canonical_model_id": "", "owner_discovery_class": "", "owner_notes": ""})
    out.sort(key=lambda r: (RISK_TIER_ORDER[r["risk_tier"]], -len(set(r["risk_categories"]) & {"CATALOG_ALIAS_COLLISION", "CROSS_BRAND_COLLISION", "SERIES_COINCIDES_WITH_POOL_MODEL", "LEGACY_R6_STRONG_PROPOSAL"}),
                            -r["units_lifetime"], r["provider_group_id"]))
    for i, r in enumerate(out, start=1):
        r["priority_rank"], r["decision_id"] = i, f"OD-C{i:02d}"
    p3 = sorted((r for r in out if r["risk_tier"].startswith("P3")), key=lambda r: sha256_bytes(f"{PACK_ID}|spot|{r['provider_group_id']}".encode()))
    for r in p3[:SPOT_CHECK_N]:
        r["p3_spot_check_sample"] = "yes"
    return out


RECON_COLUMNS = ["provider_group_id", "units_lifetime", "in_r6_sheet", "r6_review_rank", "r6_review_tier", "r6_candidate", "r6_legacy_status", "r6_v1_outcome", "relationship", "what_each_verdict_would_mean",
                 "create_decision_id", "r6_pair_verdict_field", "create_verdict_field"]


def build_reconciliation(inp: Inputs, create_rows: list[dict]) -> list[dict]:
    """One row per (CREATE candidate, R6 sheet row) pair, or one row for a candidate that is not in the sheet. Both verdict fields stay blank and live in their own files."""
    out = []
    for c in sorted(create_rows, key=lambda r: r["provider_group_id"]):
        g = c["provider_group_id"]
        rr = inp.r6_by_group.get(g, [])
        if not rr:
            out.append({"provider_group_id": g, "units_lifetime": c["units_lifetime"], "in_r6_sheet": "no", "r6_review_rank": "", "r6_review_tier": "", "r6_candidate": "", "r6_legacy_status": "", "r6_v1_outcome": "",
                        "relationship": "CREATE_ONLY_NO_PAIR_QUESTION", "what_each_verdict_would_mean": "no pair is under review for this group: only the missing-identity question (r6 = not applicable)",
                        "create_decision_id": c["decision_id"], "r6_pair_verdict_field": "", "create_verdict_field": "owner_verdict in create_candidates.csv"})
            continue
        for r in rr:
            cand = r["candidate_canonical_model_id"]
            if not cand:
                rel, mean = "IN_SHEET_WITHOUT_CANDIDATE", "the sheet row has no TDR candidate: only the missing-identity question applies"
            elif r["legacy_r6_status"] in ("AUTO", "PROPOSED"):
                rel = "LEGACY_PAIR_OPEN_AND_CREATE_OPEN"
                mean = (f"R6 pair verdict about {cand}: CORRECT_* means the group already has that identity (a VALID_MISSING_CANONICAL CREATE verdict would then conflict); WRONG_TARGET / NO_TDR_TARGET says only that "
                        f"{cand} is not the identity and leaves the missing-identity question to the CREATE verdict")
            else:
                rel, mean = "V1_ONLY_PAIR_OPEN_AND_CREATE_OPEN", f"the sheet row is a v1 pool candidate ({cand}) that the legacy run did not propose; same reading as above"
            out.append({"provider_group_id": g, "units_lifetime": c["units_lifetime"], "in_r6_sheet": "yes", "r6_review_rank": r["review_rank"], "r6_review_tier": r["review_tier"], "r6_candidate": cand,
                        "r6_legacy_status": r["legacy_r6_status"], "r6_v1_outcome": r["v1_group_outcome"], "relationship": rel, "what_each_verdict_would_mean": mean, "create_decision_id": c["decision_id"],
                        "r6_pair_verdict_field": f"owner_verdict at review_rank={r['review_rank']} in r6_owner_review.csv", "create_verdict_field": "owner_verdict in create_candidates.csv"})
    return out


# ----------------------------------------------------------------------------------------------------------------------------- verdict crosswalk and the consistency check
CROSSWALK_COLUMNS = ["r6_pair_verdict", "create_group_verdict", "reading", "consistent"]


def verdict_crosswalk() -> list[dict]:
    rows = []
    for p in R6_VERDICTS:
        for c in CREATE_VERDICTS:
            rows.append({"r6_pair_verdict": p, "create_group_verdict": c, "reading": _crosswalk_reading(p, c)[1], "consistent": _crosswalk_reading(p, c)[0]})
    return rows


def _crosswalk_reading(p: str, c: str) -> tuple[str, str]:
    if p == "CORRECT_EQUIVALENT":
        if c == "VALID_MISSING_CANONICAL":
            return "CONFLICT", "the pair says the group IS that TDR model; the group cannot also lack a canonical identity"
        if c == "EXISTING_IDENTITY":
            return "CONSISTENT_IF_SAME_TARGET", "both say the identity exists; the owner_canonical_model_id of the CREATE row must be the pair's candidate"
        if c == "VARIANT_TRIM_CODE":
            return "CONSISTENT_IF_SAME_TARGET", "the group is a variant of the pair's model; no new model"
        return "CONSISTENT", "ambiguity on the missing-identity side does not contradict a correct pair"
    if p in ("CORRECT_PART_OF", "CORRECT_COMPOSED_OF"):
        if c == "VALID_MISSING_CANONICAL":
            return "REVIEW", "the pair says the group is part of / composed of TDR models; a new model for the group is possible only if the owner wants the finer identity: say so in the notes"
        return "CONSISTENT", "the group is expressed through existing models"
    if p == "WRONG_TARGET":
        if c == "EXISTING_IDENTITY":
            return "CONSISTENT_IF_DIFFERENT_TARGET", "the candidate shown is wrong; an existing identity is acceptable only if it is another model than the candidate"
        return "CONSISTENT", "the candidate is wrong; the missing-identity question is independent"
    if p == "NO_TDR_TARGET":
        if c in ("EXISTING_IDENTITY", "VARIANT_TRIM_CODE"):
            return "CONFLICT", "the pair says no TDR model is the target; the group cannot also be an existing identity or a variant of one"
        return "CONSISTENT", "no TDR target; a missing canonical identity is the expected companion verdict"
    return "CONSISTENT", "no pair verdict to contradict" if p == "INSUFFICIENT_EVIDENCE" else "CONSISTENT"


def check_label_consistency(r6_labels: dict[str, list[dict]], create_labels: dict[str, dict], model_ids: set[str] | None = None) -> list[dict]:
    """Flag labels that contradict each other. `r6_labels[group]` = [{candidate, verdict, link_type, canonical}], `create_labels[group]` = {verdict, canonical}.
    A pair verdict never implies a group verdict and the reverse (see verdict_crosswalk.csv); only labels that cannot both be true are CONFLICTs, the rest are REVIEW prompts."""
    out = []

    def add(g, sev, kind, detail):
        out.append({"group": g, "severity": sev, "kind": kind, "detail": detail})

    for g in sorted(set(r6_labels) | set(create_labels)):
        pairs = r6_labels.get(g, [])
        cl = create_labels.get(g)
        eq = sorted({p["candidate"] for p in pairs if p["verdict"] == "CORRECT_EQUIVALENT"})
        if len(eq) > 1:
            add(g, "CONFLICT", "TWO_EQUIVALENT_TARGETS", f"CORRECT_EQUIVALENT on more than one candidate ({', '.join(eq)}); a group has at most one EQUIVALENT target (C1)")
        for p in pairs:
            if p["verdict"] not in R6_VERDICTS:
                add(g, "CONFLICT", "UNKNOWN_PAIR_VERDICT", p["verdict"])
            if p["verdict"] == "CORRECT_EQUIVALENT" and p.get("link_type") not in (None, "", "EQUIVALENT"):
                add(g, "CONFLICT", "LINK_TYPE_CONTRADICTS_VERDICT", f"{p['candidate']}: CORRECT_EQUIVALENT with owner_link_type {p['link_type']}")
            if p["verdict"] == "CORRECT_PART_OF" and p.get("link_type") not in (None, "", "PART_OF"):
                add(g, "CONFLICT", "LINK_TYPE_CONTRADICTS_VERDICT", f"{p['candidate']}: CORRECT_PART_OF with owner_link_type {p['link_type']}")
            if p["verdict"] == "CORRECT_COMPOSED_OF" and p.get("link_type") not in (None, "", "COMPOSED_OF"):
                add(g, "CONFLICT", "LINK_TYPE_CONTRADICTS_VERDICT", f"{p['candidate']}: CORRECT_COMPOSED_OF with owner_link_type {p['link_type']}")
            if p["verdict"] == "WRONG_TARGET" and p.get("canonical") and p["canonical"] == p["candidate"]:
                add(g, "CONFLICT", "WRONG_TARGET_NAMES_ITSELF", f"{p['candidate']} is called the wrong target and also given as the owner's model")
            if p.get("canonical") and model_ids is not None and p["canonical"] not in model_ids:
                add(g, "CONFLICT", "UNKNOWN_TDR_MODEL", f"pair label names {p['canonical']}, which is not a catalog model")
        if cl:
            if cl["verdict"] not in CREATE_VERDICTS:
                add(g, "CONFLICT", "UNKNOWN_GROUP_VERDICT", cl["verdict"])
            if cl["verdict"] == "EXISTING_IDENTITY" and not cl.get("canonical"):
                add(g, "CONFLICT", "EXISTING_IDENTITY_WITHOUT_MODEL", "EXISTING_IDENTITY needs owner_canonical_model_id")
            if cl.get("canonical") and model_ids is not None and cl["verdict"] in ("EXISTING_IDENTITY", "VARIANT_TRIM_CODE") and cl["canonical"] not in model_ids:
                add(g, "CONFLICT", "UNKNOWN_TDR_MODEL", f"group label names {cl['canonical']}, which is not a catalog model")
            for p in pairs:
                sev, reading = _crosswalk_reading(p["verdict"], cl["verdict"])
                if sev == "CONFLICT":
                    add(g, "CONFLICT", "PAIR_AND_GROUP_VERDICT_CONTRADICT", f"{p['candidate']}: {p['verdict']} with {cl['verdict']}: {reading}")
                elif sev == "REVIEW":
                    add(g, "REVIEW", "PAIR_AND_GROUP_VERDICT_NEED_NOTE", f"{p['candidate']}: {p['verdict']} with {cl['verdict']}: {reading}")
                elif sev == "CONSISTENT_IF_SAME_TARGET" and cl.get("canonical") and cl["canonical"] != p["candidate"]:
                    add(g, "CONFLICT", "GROUP_TARGET_DIFFERS_FROM_CORRECT_PAIR", f"{p['candidate']} is CORRECT but the group verdict names {cl['canonical']}")
                elif sev == "CONSISTENT_IF_DIFFERENT_TARGET" and cl.get("canonical") == p["candidate"]:
                    add(g, "CONFLICT", "GROUP_TARGET_IS_THE_WRONG_TARGET", f"{p['candidate']} is WRONG_TARGET but the group verdict names it as the existing identity")
    return out


# ----------------------------------------------------------------------------------------------------------------------------- section B: brand-resolution cases
def ck(s) -> str:
    return P.compact(s)


def catalog_label_resolution(inp: Inputs, provider_brand: str) -> list[dict]:
    """Which catalog brand records carry the provider's brand label as their id, English name, or one of their `aliases` (compact-key match). This is the catalog-label lookup a consumer
    can do; it is re-derived here from vehreg/data/2026/models/*.json and is not PR #201 code."""
    key, hits = ck(provider_brand), []
    for bid, rec in sorted(inp.brand_files.items()):
        b = rec.get("brand") or {}
        for how, val in [("id", b.get("id")), ("name_en", b.get("name_en"))] + [("alias", a) for a in (b.get("aliases") or [])]:
            if val and ck(val) == key:
                hits.append({"brand_id": bid, "via": how, "label": val})
    return hits


def producer_brand_relations(inp: Inputs, provider_brand: str, observed: list[str]) -> list[dict]:
    """The reference evaluator's brand relation from the provider's label(s) to every TDR brand, keeping the non-MISMATCH ones (`calibration.ref_eval_core.brand_relation`, unchanged)."""
    out = []
    prov = inp.policy.get("alias_provenance") or {}
    for bid, b in sorted(inp.brands.items()):
        rel, aid = P.brand_relation(provider_brand, b["name_en"], tuple(observed))
        if rel not in ("MISMATCH", "UNKNOWN"):
            out.append({"brand_id": bid, "relation": rel, "alias_class": aid, "provenance": prov.get(aid, "") if aid else ""})
    return out


BRAND_COLUMNS = [
    "decision_id", "case_kind", "provider_group_id", "provider_name", "provider_brand_label", "brands_observed", "units_lifetime", "units_last12", "pr201_outcome", "pr201_parity_reason",
    "producer_brand_relations", "producer_pool_size", "producer_pool_brands", "producer_best_relation", "consumer_catalog_label_resolution", "catalog_brand_records", "disagreement_kind",
    "policy_alias_classes_involved", "candidate_pool_provenance", "other_groups_with_same_label", "catalog_precedent", "contract_level_options_NON_AUTHORITATIVE", "recommended_resolution_NON_AUTHORITATIVE",
    "evidence_refs", "owner_decision", "owner_notes"]


def _policy_classes_for(inp: Inputs, label: str) -> list[str]:
    k = ck(label)
    out = []
    for a in inp.policy["aliases"]["brand"]:
        if any(ck(m) == k for m in a["members"]):
            out.append(f"{a['id']}:{a['relation']}")
    return sorted(out)


def build_brand_cases(inp: Inputs) -> list[dict]:
    """The eight unresolved parity rows and the cross-brand rows PR #201 flagged, compared along four axes: the producer's brand relations, the catalog's own brand records,
    the provider's labels, and the provenance of the candidate pool. Recommendations are contract-level (a rule about brand relations) -- no brand or model is named in a rule."""
    rows = []
    reasons = {r["external_id"]: r["reasons"] for r in inp.unresolved}
    cross = {r["external_id"]: r for r in inp.cross_brand if "CROSS_BRAND" in r["flag"]}
    cases = [(g, "UNRESOLVED_PARITY") for g in sorted(reasons)] + [(g, "CROSS_BRAND_FILING") for g in sorted(cross) if g not in reasons]
    # label census: how many Ice groups carry each provider brand label, and what happened to them
    by_label = collections.defaultdict(list)
    for sid, s in inp.subjects.items():
        by_label[ck(s["brand"])].append(sid)
    for i, (g, kind) in enumerate(cases, start=1):
        s = inp.subjects[g]
        bs = inp.bootstrap.get(g, {})
        label = s["brand"]
        prod = producer_brand_relations(inp, label, s["brands_observed"])
        pool_brands = sorted({inp.models[t]["brand_id"] for t in s["pool"]})
        cat = catalog_label_resolution(inp, label)
        reason = reasons.get(g, "")
        if reason.startswith("BRAND_RESOLUTION_VS_POOL: the export has a pool but the shadow does not resolve"):
            disagreement = "PRODUCER_ADMITS_RELATED_BRAND__CATALOG_LABEL_LOOKUP_FINDS_NONE"
        elif "the shadow resolves the brand to a TDR brand but the export pool is empty" in reason:
            disagreement = "CATALOG_ALIAS_RESOLVES__PRODUCER_HAS_NO_BRAND_RELATION"
        else:
            disagreement = "FILING_OF_A_SUB_BRAND_THE_CATALOG_HOLDS_UNDER_ANOTHER_BRAND"
        classes = sorted({c for lab in [label, *s["brands_observed"]] for c in _policy_classes_for(inp, lab)})
        same = [x for x in by_label[ck(label)] if x != g]
        same_units = sum(int0(inp.groups[x]["ice_lifetime_units"]) for x in same if x in inp.groups)
        precedent = ""
        mg_maxus = [m for m in sorted(inp.models) if "maxus" in m]
        if g.startswith("maxus-"):
            maxus_groups = sorted(x for x in inp.groups if x.startswith("maxus-"))
            precedent = (f"catalog models {', '.join(mg_maxus)} are filed under brand mg; the catalog has no Maxus brand record; Ice groups with a maxus- id: "
                         f"{', '.join(f'{x} ({inp.groups[x]['ice_lifetime_units']} units)' for x in maxus_groups)}; policy classes: {', '.join(classes) or 'none'}")
        refs = [ref("owner_decision_pack/inputs/pr201_30d2618a4/" + ("parity_unresolved.csv" if g in reasons else "cross_brand_review.csv"), f"external_id={g}"), ref("relation_export/ice_subjects.jsonl", f"id={g}"),
                ref("contract/v1/policy.yaml", "aliases.brand"), ref("owner_decision_pack/inputs/pr201_30d2618a4/decisions.csv", f"model_group_id={g}")]
        rows.append({
            "decision_id": f"OD-B{i:02d}", "case_kind": kind, "provider_group_id": g, "provider_name": s["name"], "provider_brand_label": label, "brands_observed": s["brands_observed"],
            "units_lifetime": int0(bs.get("units_total")), "units_last12": int0(bs.get("units_last12")), "pr201_outcome": f"{bs.get('A_outcome', '')} / {bs.get('A_primary', '')}", "pr201_parity_reason": reason,
            "producer_brand_relations": [f"{p['brand_id']}:{p['relation']}:{p['alias_class'] or ''}:{p['provenance'] or ''}" for p in prod], "producer_pool_size": len(s["pool"]), "producer_pool_brands": pool_brands,
            "producer_best_relation": s["best_relation"] or "", "consumer_catalog_label_resolution": [f"{c['brand_id']} via {c['via']}({c['label']})" for c in cat] or "none",
            "catalog_brand_records": [json.dumps(tdr_brand_record(inp, b), ensure_ascii=False, sort_keys=True) for b in sorted({c['brand_id'] for c in cat} | set(pool_brands)) if b in inp.brand_files],
            "disagreement_kind": disagreement, "policy_alias_classes_involved": classes,
            "candidate_pool_provenance": (f"pool of {len(s['pool'])} model(s) of brand(s) {', '.join(pool_brands)}, admitted because the producer's brand relation to those brand(s) is "
                                          f"{', '.join(sorted({p['relation'] for p in prod if p['brand_id'] in pool_brands}))}") if s["pool"] else "empty pool: the producer admits no brand relation from this label to any TDR brand",
            "other_groups_with_same_label": f"{len(same)} other Ice group(s), {same_units} lifetime units" if same else "none", "catalog_precedent": precedent,
            "contract_level_options_NON_AUTHORITATIVE": "", "recommended_resolution_NON_AUTHORITATIVE": "", "evidence_refs": refs, "owner_decision": "", "owner_notes": ""})
    for r in rows:
        r["contract_level_options_NON_AUTHORITATIVE"], r["recommended_resolution_NON_AUTHORITATIVE"] = brand_options(r["disagreement_kind"])
    return rows


def brand_options(kind: str) -> tuple[str, str]:
    if kind == "PRODUCER_ADMITS_RELATED_BRAND__CATALOG_LABEL_LOOKUP_FINDS_NONE":
        return ("(1) a consumer takes its candidate set from the producer's pool and brand relation instead of resolving the brand itself; (2) a consumer resolves brands with the producer's typed alias classes "
                "in addition to catalog labels; (3) add the sub-brand label to the catalog brand record's aliases (catalog change, outside this contract)",
                "(1): relation-first. The producer's typed relation (here RELATED, capped at PROPOSE, never AUTO) is the one place a brand relation is decided; a consumer that cannot find a catalog label "
                "for the provider's brand must follow it rather than report BRAND_NOT_IN_TDR.")
    if kind == "CATALOG_ALIAS_RESOLVES__PRODUCER_HAS_NO_BRAND_RELATION":
        return ("(1) catalog brand aliases are never an input to a brand relation until the owner types them (SAME / RELABEL / RELATED) in policy with a provenance; (2) a catalog brand alias counts as RELATED by default; "
                "(3) the owner types this label now",
                "(1) with (3) for this label: a catalog `aliases` entry is a registration-attribution label, not a statement of identity; the owner decides the class (RELATED is the cautious reading). "
                "Until typed, the consumer must report the case as unresolved, not resolve it silently.")
    return ("(1) file Maxus-badged models under the brand the registrations use (as the catalog does today); (2) create a separate Maxus catalog brand and refile the existing models; (3) keep the existing filing "
            "and treat the label as a RELATED brand (policy already says so)",
            "decide the filing first (a catalog decision), then the contract needs no change: policy already types the two labels RELATED and a Maxus label RELABEL to 'MG Maxus'. "
            "The CREATE for V80 and the identity reviews for Mifa 7 / 9 follow that one decision.")


# ----------------------------------------------------------------------------------------------------------------------------- section C: R6 priority view, brand folds, starter batch
def brand_families(inp: Inputs) -> dict[str, str]:
    """Union-find over compact brand keys: the policy's typed brand alias classes (SAME / RELABEL / RELATED), the catalog brand records' own `aliases`, and Ice brand labels observed together on one group.
    Everything in a family goes to ONE fold, so no held-out brand shares a brand relation with a training brand (a relation is how one brand's label leaks into another's evidence)."""
    parent: dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for a in inp.policy["aliases"]["brand"]:
        ks = [ck(m) for m in a["members"]]
        for k in ks[1:]:
            union(ks[0], k)
    for bid, rec in inp.brand_files.items():
        b = rec.get("brand") or {}
        for val in [b.get("id"), b.get("name_en"), *(b.get("aliases") or [])]:
            if val:
                union(ck(b.get("id") or bid), ck(val))
    for s in inp.subjects.values():
        obs = [ck(x) for x in s["brands_observed"]]
        for k in obs[1:]:
            union(obs[0], k)
    return {k: find(k) for k in list(parent)}


def assign_folds(items: dict[str, float], n_folds: int) -> dict[str, int]:
    """Longest-processing-time balancing: biggest family first, always into the currently lightest fold; ties broken by name. Deterministic."""
    load = [0.0] * n_folds
    out = {}
    for k, w in sorted(items.items(), key=lambda kv: (-kv[1], kv[0])):
        f = min(range(n_folds), key=lambda i: (load[i], i))
        out[k] = f
        load[f] += w
    return out


def fold_for(meta: dict, family: str) -> int:
    """Families with R6 rows are balanced by `assign_folds`; a family that only has CREATE candidates or negative-sample groups takes a fold from a fixed hash, so it never moves."""
    f = meta["fold_of_family"].get(family)
    return f if f is not None else int(sha256_bytes(f"{PACK_ID}|fold|{family}".encode())[:8], 16) % TRIAGE["folds"]


def cover_prefix(rows: list[dict], frac: float, key) -> list[dict]:
    rows = sorted(rows, key=lambda r: (-key(r), int(r["review_rank"])))
    total, run, out = sum(key(r) for r in rows), 0, []
    for r in rows:
        out.append(r)
        run += key(r)
        if run >= frac * total:
            break
    return out


R6_VIEW_COLUMNS = [
    "review_rank", "review_tier", "in_first_176", "model_group_id", "ice_brand", "brand_family", "fold", "candidate_canonical_model_id", "candidate_is_v1_primary", "legacy_r6_status", "legacy_r6_match_method",
    "v1_group_outcome", "v1_name_relation", "v1_series_state", "v1_correlation", "v1_common_months", "ice_lifetime_units", "ice_units_last12m", "risk_categories", "interacts_with", "starter_batch", "starter_reason",
    "machine_expectation_NON_AUTHORITATIVE", "evidence_refs"]
STARTER_FRACTION = 0.8
SPOT_CHECK_N = 8


def build_r6_view(inp: Inputs, alias_rows: list[dict], create_rows: list[dict], brand_rows: list[dict]) -> tuple[list[dict], dict]:
    rows = inp.r6
    cut = inp.summary["review_sheet"]["cutoffs"]
    fam = brand_families(inp)
    fam_weight = collections.Counter()
    for r in rows:
        fam_weight[fam.get(ck(r["ice_brand"]), ck(r["ice_brand"]))] += 1
    fold_of = assign_folds({k: float(v) for k, v in fam_weight.items()}, TRIAGE["folds"])
    alias_of = {r["provider_group_id"]: r["decision_id"] for r in alias_rows}
    create_of = {r["provider_group_id"]: r["decision_id"] for r in create_rows}
    brand_of = {r["provider_group_id"]: r["decision_id"] for r in brand_rows}

    def u(r):
        return int(float(r["ice_lifetime_units"] or 0))

    primary = lambda r: "V1_PRIMARY" in r["candidate_origin"]
    auto_pairs = [r for r in rows if r["v1_group_outcome"] == "AUTO" and primary(r)]
    legacy_auto_lost = [r for r in rows if r["legacy_r6_status"] == "AUTO" and r["v1_group_outcome"] != "AUTO"]
    families = {}
    for r in rows:
        if r["suspicious_cases"]:
            c = r["suspicious_cases"]
            if c not in families or (u(r), -int(r["review_rank"])) > (u(families[c]), -int(families[c]["review_rank"])):
                families[c] = r
    structural = [r for r in rows if r["review_tier"] in ("5", "6")]
    starter: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    s1 = cover_prefix(auto_pairs, STARTER_FRACTION, u)
    s2 = cover_prefix(legacy_auto_lost, STARTER_FRACTION, u)
    for r in s1:
        starter[r["review_rank"]].append(("S1_AUTO_PAIRS", f"v1 AUTO pair; with the other S1 rows covers >= {int(STARTER_FRACTION * 100)}% of the units of all {len(auto_pairs)} AUTO pairs"))
    for r in s2:
        starter[r["review_rank"]].append(("S2_LEGACY_AUTO_NOT_AUTO", f"legacy AUTO, v1 {r['v1_group_outcome']}; with the other S2 rows covers >= {int(STARTER_FRACTION * 100)}% of those {len(legacy_auto_lost)} rows' units"))
    for c, r in sorted(families.items()):
        starter[r["review_rank"]].append(("S3_KNOWN_FAMILY", f"largest row of the known-case family {c}"))
    for r in structural:
        starter[r["review_rank"]].append(("S4_STRUCTURAL", f"tier {r['review_tier']}: {r['review_tier_label']}"))
    out = []
    for r in rows:
        g = r["model_group_id"]
        cats = []
        if r["v1_group_outcome"] == "AUTO" and primary(r):
            cats.append("V1_AUTO_PAIR_FALSE_AUTO_EXPOSURE")
        if r["legacy_r6_status"] == "AUTO" and r["v1_group_outcome"] != "AUTO":
            cats.append("LEGACY_AUTO_NOT_AUTO_IN_V1")
        if r["legacy_r6_status"] == "PROPOSED" and r["v1_group_outcome"] == "AUTO":
            cats.append("LEGACY_PROPOSED_AUTO_IN_V1")
        if r["series_material_change"] == "true":
            cats.append("SERIES_MATERIAL_CHANGE")
        if r["suspicious_cases"]:
            cats.append("KNOWN_FAMILY:" + r["suspicious_cases"])
        if r["review_tier"] == "5":
            cats.append("PART_OF_OR_COMPOSED_OF_CANDIDATE")
        if r["review_tier"] == "6":
            cats.append("SEVERAL_VIABLE_CANDIDATES")
        if r["v1_name_relation"] in ("CONTRADICTION", "SIBLING") and r["v1_series_state"] == "STRONG":
            cats.append("SERIES_STRONG_NAME_CONTRADICTS")
        if r["v1_name_relation"] == "FUZZY":
            cats.append("FUZZY_NAME_RELATION")
        if u(r) >= cut["high_volume_lifetime_units"]:
            cats.append("HIGH_VOLUME")
        inter = [x for x in (alias_of.get(g), create_of.get(g), brand_of.get(g)) if x]
        if inter:
            cats.append("INTERACTS_WITH_OTHER_DECISION")
        st = starter.get(r["review_rank"], [])
        fm = fam.get(ck(r["ice_brand"]), ck(r["ice_brand"]))
        if r["v1_group_outcome"] == "AUTO":
            exp = "the contract would write this pair at AUTO: a wrong label here is a false-AUTO"
        elif r["v1_group_outcome"] == "PROPOSE":
            exp = "the contract would queue this pair for review (PROPOSE)"
        else:
            exp = f"the contract would not propose this pair ({r['v1_group_outcome']})"
        out.append({
            "review_rank": r["review_rank"], "review_tier": r["review_tier"], "in_first_176": "yes" if int(r["review_rank"]) <= 176 else "no", "model_group_id": g, "ice_brand": r["ice_brand"], "brand_family": fm,
            "fold": fold_of[fm], "candidate_canonical_model_id": r["candidate_canonical_model_id"], "candidate_is_v1_primary": "yes" if primary(r) else "no", "legacy_r6_status": r["legacy_r6_status"],
            "legacy_r6_match_method": r["legacy_r6_match_method"], "v1_group_outcome": r["v1_group_outcome"], "v1_name_relation": r["v1_name_relation"], "v1_series_state": r["v1_series_state"],
            "v1_correlation": f6(float(r["v1_correlation"])) if r["v1_correlation"] not in ("", None) else "", "v1_common_months": r["v1_common_months"], "ice_lifetime_units": u(r), "ice_units_last12m": int0(r["ice_units_last12m"]),
            "risk_categories": cats, "interacts_with": inter, "starter_batch": sorted({a for a, _ in st}), "starter_reason": "; ".join(b for _, b in st), "machine_expectation_NON_AUTHORITATIVE": exp,
            "evidence_refs": [ref("r6_owner_review.csv", f"review_rank={r['review_rank']}"), ref("r6_calibration_groups.csv", f"model_group_id={g}")] +
                             ([ref("relation_export/pairs_ice_tdr.jsonl", f"pair={g} -> {m}") for m in r["candidate_canonical_model_id"].split("+")] if r["candidate_canonical_model_id"]
                              else [ref("relation_export/ice_subjects.jsonl", f"id={g}")])})
    meta = {"families": len(fam_weight), "fold_weights": [sum(w for k, w in fam_weight.items() if fold_of[k] == i) for i in range(TRIAGE["folds"])], "auto_pairs": len(auto_pairs),
            "auto_pair_units": sum(u(r) for r in auto_pairs), "s1": len(s1), "s1_units": sum(u(r) for r in s1), "legacy_auto_not_auto": len(legacy_auto_lost), "s2": len(s2), "s3": len(families), "s4": len(structural),
            "fold_of_family": fold_of, "families_of_brand": fam}
    return out, meta


FOLD_COLUMNS = ["brand_family", "fold", "r6_rows", "r6_lifetime_units", "ice_brand_labels", "create_candidates", "negative_sample_groups", "basis"]


def build_folds(inp: Inputs, view: list[dict], meta: dict, create_rows: list[dict], neg_rows: list[dict]) -> list[dict]:
    members = collections.defaultdict(set)
    rows_n, units, cr, ng = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    for r in view:
        members[r["brand_family"]].add(r["ice_brand"])
        rows_n[r["brand_family"]] += 1
        units[r["brand_family"]] += r["ice_lifetime_units"]
    for c in create_rows:
        members[c["brand_family"]].add(c["provider_brand"])
        cr[c["brand_family"]] += 1
    for n in neg_rows:
        members[n["brand_family"]].add(n["provider_brand"])
        ng[n["brand_family"]] += 1
    return [{"brand_family": f, "fold": fold_for(meta, f), "r6_rows": rows_n[f], "r6_lifetime_units": units[f], "ice_brand_labels": sorted(members[f]), "create_candidates": cr[f], "negative_sample_groups": ng[f],
             "basis": ("balanced by R6 row count over the sheet's families" if f in meta["fold_of_family"] else "no R6 row: fixed hash of the family key")
             + "; family = brands tied by a policy brand alias class, a catalog brand alias or labels observed together on one group; one fold per family"}
            for f in sorted(members, key=lambda f: (fold_for(meta, f), f))]


# ----------------------------------------------------------------------------------------------------------------------------- negative sample (phase 2: needed for recall, not for the first decisions)
NEG_COLUMNS = ["sample_id", "provider_group_id", "provider_name", "provider_brand", "brand_family", "fold", "stratum", "stratum_population", "stratum_sample_size", "sampling_weight", "units_lifetime",
               "pr201_class", "export_best_relation", "pool_size", "question", "evidence_refs", "owner_has_tdr_counterpart", "owner_canonical_model_id", "owner_link_type", "owner_notes"]


def unit_bucket(u: int) -> str:
    cuts = TRIAGE["negative_unit_strata"]
    for i, cut in enumerate(cuts):
        if u >= cut:
            return f">={cut}" if i == 0 else f"{cut}..{cuts[i - 1] - 1}"
    return f"<{cuts[-1]}"


def build_negative_sample(inp: Inputs, meta: dict) -> tuple[list[dict], dict]:
    """Groups the contract says have NO candidate and that no other list in this pack asks about. Recall of PROPOSE / AUTO cannot be measured from labelled positives alone: a labelled sample of the
    rest is the denominator. Deterministic: inside a stratum the groups are ordered by sha256(pack id | group id) and the first n are taken; each carries weight = population / n."""
    r6g = {r["model_group_id"] for r in inp.r6}
    skip = set(inp.create_ids) | r6g
    strata = collections.defaultdict(list)
    for g, s in sorted(inp.subjects.items()):
        if s["outcome"]["outcome"] != "NO_CANDIDATE" or g in skip:
            continue
        code = s["outcome"]["primary_code"]
        strata[(code, unit_bucket(int0(inp.groups[g]["ice_lifetime_units"])))].append(g)
    per = TRIAGE["negative_sample_per_stratum"]
    out, summary = [], {}
    for (code, bucket), members in sorted(strata.items()):
        n = min(per.get(code, 2), len(members))
        # a stratum whose units are all tiny still gets a draw; a population smaller than n is taken whole
        ordered = sorted(members, key=lambda g: sha256_bytes(f"{PACK_ID}|{g}".encode()))[:n]
        summary[f"{code}|{bucket}"] = {"population": len(members), "sample": n, "population_units": sum(int0(inp.groups[g]["ice_lifetime_units"]) for g in members)}
        for g in sorted(ordered):
            s = inp.subjects[g]
            fm = meta["families_of_brand"].get(ck(s["brand"]), ck(s["brand"]))
            out.append({"sample_id": "", "provider_group_id": g, "provider_name": s["name"], "provider_brand": s["brand"], "brand_family": fm,
                        "fold": fold_for(meta, fm), "stratum": f"{code}|{bucket}", "stratum_population": len(members), "stratum_sample_size": n,
                        "sampling_weight": round(len(members) / n, 6), "units_lifetime": int0(inp.groups[g]["ice_lifetime_units"]), "pr201_class": code, "export_best_relation": s["best_relation"] or "",
                        "pool_size": len(s["pool"]), "question": f"Does '{s['brand']} {s['name']}' have a TDR model, or a PART_OF / COMPOSED_OF relation to one, although the contract found none?",
                        "evidence_refs": [ref("relation_export/ice_subjects.jsonl", f"id={g}"), ref("r6_calibration_groups.csv", f"model_group_id={g}")],
                        "owner_has_tdr_counterpart": "", "owner_canonical_model_id": "", "owner_link_type": "", "owner_notes": ""})
    out.sort(key=lambda r: (r["stratum"], r["provider_group_id"]))
    for i, r in enumerate(out, start=1):
        r["sample_id"] = f"NS-{i:03d}"
    return out, summary


# ----------------------------------------------------------------------------------------------------------------------------- pending thresholds: what the sweep says moves, and which labels would settle it
THRESH_COLUMNS = ["adoption_entry", "settles_with", "variants_run", "max_groups_changed", "max_auto_gained", "max_auto_lost", "moves_seen", "example_groups_listed", "example_groups_in_starter_batch",
                  "label_need", "labels_that_decide_it"]


def build_threshold_table(inp: Inputs, starter_groups: set[str]) -> list[dict]:
    entries = {e["id"]: e for e in inp.adoption["entries"] if e["class"] == "calibration" and e["status"] != "owner_accepted"}
    by_entry = collections.defaultdict(list)
    for v in inp.sensitivity["variants"]:
        if v.get("hypothetical"):
            continue
        by_entry[v["adoption_entry"].split(" ")[0]].append(v)
    # variants whose entry is not an adoption entry (the strong-series gate and the window are named in SPEC 14.2 and carry their own "value still pending" note)
    extra = {k: vs for k, vs in by_entry.items() if k not in {e["id"] for e in inp.adoption["entries"]}}
    out = []
    for eid, e in sorted(entries.items()):
        out.append(_threshold_row(eid, e.get("settles_with", ""), by_entry.get(eid, []), starter_groups))
    for eid, vs in sorted(extra.items()):
        note = vs[0]["adoption_entry"].replace(eid, "", 1).strip(" ()") or "named in SPEC 14.2"
        out.append(_threshold_row(eid, f"not an adoption entry: {note}", vs, starter_groups))
    return out


def _threshold_row(eid: str, settles: str, vs: list[dict], starter_groups: set[str]) -> dict:
    ex = sorted({g for v in vs for g in (v.get("examples_changed") or [])})
    moves = collections.Counter()
    for v in vs:
        moves.update(v.get("moves") or {})
    mg = max((v["groups_changed"] for v in vs), default=0)
    need = ("no variant of this entry was swept" if not vs else
            "none from the sweep: no tested value moves a group (a decision with no data on the sheet)" if mg == 0 else
            f"labels on the {mg} group(s) the largest swing moves; the sweep lists {len(ex)} example group(s)")
    return {"adoption_entry": eid, "settles_with": settles, "variants_run": [v["id"] for v in vs], "max_groups_changed": mg, "max_auto_gained": max((v["auto_gained"] for v in vs), default=0),
            "max_auto_lost": max((v["auto_lost"] for v in vs), default=0), "moves_seen": [f"{k}={n}" for k, n in sorted(moves.items())], "example_groups_listed": len(ex),
            "example_groups_in_starter_batch": sorted(set(ex) & starter_groups), "label_need": need,
            "labels_that_decide_it": "pair verdicts (r6_owner_review.csv) on the groups the largest swing moves, plus the negative sample for groups it would add" if mg else ""}


# ----------------------------------------------------------------------------------------------------------------------------- calibration entry requirements and the procedure
def rule_of_three(n: int) -> float | None:
    """Upper 95% bound on a rate observed 0 times in n independent trials."""
    return None if n <= 0 else round(3.0 / n, 6)


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (round(max(0.0, c - h), 6), round(min(1.0, c + h), 6))


ENTRY_COLUMNS = ["requirement_id", "what", "needs", "computed_from", "value", "meaning"]


def build_entry_requirements(inp: Inputs, view: list[dict], meta: dict, neg_summary: dict) -> list[dict]:
    auto_n = meta["auto_pairs"]
    out = [
        ("ER-01", "AUTO pairs that exist to be labelled", "labelled v1-AUTO pairs", "count of rows with v1_group_outcome=AUTO and a primary candidate", auto_n,
         "the whole AUTO universe on the sheet; no bound on false-AUTO can be tighter than 3/n even if every one is labelled and correct"),
        ("ER-02", "best demonstrable false-AUTO bound", "all ER-01 pairs labelled, none wrong", "rule of three, upper 95%", rule_of_three(auto_n), "the 95% upper bound on the false-AUTO rate if all AUTO pairs are labelled and none is wrong"),
        ("ER-03", "false-AUTO bound from the starter batch", "S1 rows labelled, none wrong", "rule of three, upper 95%", rule_of_three(meta["s1"]),
         f"the starter batch labels {meta['s1']} AUTO pairs ({round(100 * meta['s1_units'] / meta['auto_pair_units'], 1)}% of AUTO-pair units): enough to find a systematic failure, not to certify a rate"),
    ]
    for tol in (0.10, 0.05, 0.02, 0.01):
        n = math.ceil(round(3.0 / tol, 9))
        out.append((f"ER-T{int(tol * 100):02d}", f"labelled AUTO pairs needed to show false-AUTO <= {int(tol * 100)}% (zero errors)", "labelled correct AUTO pairs", "ceil(3 / tolerance)", n,
                    "reachable from the AUTO universe" if n <= auto_n else f"NOT reachable: only {auto_n} AUTO pairs exist on the sheet; a tolerance this tight needs structural argument, more packages, or a wider AUTO set"))
    folds = TRIAGE["folds"]
    out += [
        ("ER-F1", "brand-separated folds", f"labelled rows in >= {folds} brand families", "brand_folds.csv", meta["families"], "families are never split across folds"),
        ("ER-F2", "held-out coverage per fold", "at least one labelled AUTO pair per fold used for evaluation", "S1 rows by fold",
         sorted({r["fold"] for r in view if "S1_AUTO_PAIRS" in r["starter_batch"]}), "folds that hold an S1 AUTO pair (a fold without one cannot report AUTO precision); the folds are 0.." + str(TRIAGE["folds"] - 1)),
        ("ER-N1", "recall denominator", "labelled negative sample", "negative_sample.csv strata", sum(v["sample"] for v in neg_summary.values()), "weights make the sample estimate the NO_CANDIDATE population"),
    ]
    return [dict(zip(ENTRY_COLUMNS, r)) for r in out]


CALIBRATION_PROCEDURE = {
    "schema": "ir-owner-pack-calibration-procedure/1",
    "status": "NON_AUTHORITATIVE preparation; nothing here is calibrated and no value is chosen",
    "labels_used": {
        "pair": "r6_owner_review.csv verdicts. positive for the shown link type: CORRECT_EQUIVALENT (EQUIVALENT), CORRECT_PART_OF (PART_OF), CORRECT_COMPOSED_OF (COMPOSED_OF); negative: WRONG_TARGET, NO_TDR_TARGET; excluded and counted: INSUFFICIENT_EVIDENCE",
        "group": "create_candidates.csv verdicts: VALID_MISSING_CANONICAL makes every pooled candidate of the group a negative; EXISTING_IDENTITY / VARIANT_TRIM_CODE make owner_canonical_model_id a positive; AMBIGUOUS is excluded and counted",
        "negative_sample": "negative_sample.csv: owner_has_tdr_counterpart, weighted by sampling_weight",
        "consistency": "check_label_consistency() runs first; a CONFLICT is resolved by the owner before any metric is computed"},
    "design": {
        "folds": "brand_folds.csv: five folds of brand families; every row of a family sits in one fold",
        "loop": "for each fold k: choose among the candidate values (the swept grid in sensitivity_results.json) on the other four folds, evaluate once on fold k; report pooled out-of-fold predictions",
        "selection_rule": "the loosest value whose training false-AUTO count is zero and whose pooled held-out false-AUTO upper bound is within the tolerance the owner sets (open question); a tie goes to the stricter value",
        "no_leakage": "no threshold, class or alias list is tuned on a row of the held-out fold's brand family; the owner's seed brand classes are inputs, not tuned values"},
    "metrics": {
        "auto_precision": "labelled-correct AUTO pairs / labelled AUTO pairs, Wilson 95% interval; with zero errors the rule-of-three upper bound on false-AUTO is reported instead",
        "auto_recall": "labelled-correct pairs the contract writes at AUTO / labelled-correct pairs (EQUIVALENT only)",
        "propose_precision": "labelled-correct among PROPOSE pairs",
        "propose_or_better_recall": "labelled-correct pairs the contract proposes or writes / labelled-correct pairs, with the weighted negative sample adding the correct pairs the contract missed (NO_CANDIDATE)",
        "unit_weighted": "each of the above is also reported weighted by lifetime units, because a wrong high-volume pair costs more registrations than a wrong tail pair"},
    "false_auto_analysis": [
        "every false-AUTO is listed with its supporting codes, series state, name relation, brand relation and lineage roles",
        "classify the root cause: series coincidence of different models, granularity (finer or coarser model), lineage (rename / replacement), brand relation, label noise in the owner's verdict",
        "a root cause that the contract can express as a gate is a proposal for a rule change in a later round, never applied in the same pass as the measurement",
        "report false-AUTO by brand family and by fold: a single family accounting for the errors means a missing rule, not a miscalibrated threshold"],
    "pending_threshold_sensitivity": [
        "each pending calibration entry (pending_threshold_sensitivity.csv) is re-evaluated at every swept value on the labelled rows",
        "report the change in held-out AUTO precision, AUTO recall and false-AUTO count per value; a value that creates a labelled false-AUTO is rejected regardless of recall",
        "an entry that moves no labelled row stays pending and is reported as not constrained by the labels"],
    "stop_rules": [
        "fewer labelled AUTO pairs than ER-T tolerance requires: report the bound that the labels do support and keep the threshold pending",
        "any CONFLICT from check_label_consistency: stop and return the conflicts to the owner",
        "any false-AUTO in a held-out fold: stop, analyse (false_auto_analysis), do not tune around it",
        "nothing is bound until the owner accepts a calibrated value in adoption.yaml; adoption.binding stays false"]}


# ----------------------------------------------------------------------------------------------------------------------------- the smallest first set, and the whole queue
INIT_COLUMNS = ["item_id", "wave", "kind", "question", "resolves", "units_at_stake", "why_first", "where_the_answer_goes", "owner_answer", "owner_notes"]
QUEUE_COLUMNS = ["queue_position", "wave", "item_kind", "item_id", "detail_file", "units_at_stake", "why_in_this_wave"]
FIRST_WAVE = {"p1_min_units": 100, "p2_min_units": 1000}


def build_initial(inp: Inputs, alias_rows, brand_rows, create_rows, view, meta) -> tuple[list[dict], dict]:
    brand_ids = lambda kind: [r["decision_id"] for r in brand_rows if r["disagreement_kind"] == kind]
    units = lambda ids, rows, key="units_lifetime": sum(r[key] for r in rows if r["decision_id"] in ids)
    rel = brand_ids("PRODUCER_ADMITS_RELATED_BRAND__CATALOG_LABEL_LOOKUP_FINDS_NONE")
    jet = brand_ids("CATALOG_ALIAS_RESOLVES__PRODUCER_HAS_NO_BRAND_RELATION")
    mx = brand_ids("FILING_OF_A_SUB_BRAND_THE_CATALOG_HOLDS_UNDER_ANOTHER_BRAND")
    items = [
        ("INIT-01", "CONTRACT", "When the producer's brand relation to a TDR brand is RELATED (capped at PROPOSE), must a consumer take its candidate set from the producer instead of resolving the brand itself from catalog labels?",
         rel, units(rel, brand_rows), "one rule closes seven of the eight unresolved parity cases", "adoption.yaml (candidates_pool_rules) / a PR #201 consumer note"),
        ("INIT-02", "CONTRACT", "May a catalog brand `aliases` entry ever be a brand relation, and if so as which typed class (SAME / RELABEL / RELATED) and with which provenance? Decide the one label in the pack (JETOUR under Chery).",
         jet, units(jet, brand_rows), "closes the one case where the consumer resolves a brand the producer does not relate", "policy.yaml aliases.brand + alias_provenance"),
        ("INIT-03", "CATALOG", "Where are Maxus-badged models filed: under the registration brand MG (as mg.mg_maxus_7 / mg.mg_maxus_9 are today) or under a Maxus brand?",
         mx + ["OD-C11"], units(mx, brand_rows), "blocks the V80 CREATE, two Mifa identity reviews and the EPC1A parity case", "catalog brand records / PR #201 identity review"),
        ("INIT-04", "CONTRACT", "What does a TDR catalog model `aliases` entry assert: the same model, a registration-attribution label that may cover a broader family, or a lookup convenience? "
         "(The nine alias rows show all three readings occur.)", [r["decision_id"] for r in alias_rows], sum(r["provider_units_lifetime"] if isinstance(r["provider_units_lifetime"], int) else int0(r["provider_units_lifetime"]) for r in alias_rows),
         "the answer is the rule for all nine alias rows and for any alias the catalog gains later", "policy / VEHICLE_DB_V3 note"),
    ]
    out = [{"item_id": i, "wave": 1, "kind": k, "question": q, "resolves": ids, "units_at_stake": u, "why_first": w, "where_the_answer_goes": g, "owner_answer": "", "owner_notes": ""} for i, k, q, ids, u, w, g in items]
    strong = [r for r in alias_rows if r["evidence_sufficiency"] == "STRONG_PACK_EVIDENCE"]
    for r in strong:
        out.append({"item_id": f"INIT-{r['decision_id']}", "wave": 1, "kind": "ALIAS_VERDICT", "question": f"{r['provider_name']} ({r['provider_group_id']}) vs catalog alias on {r['existing_identity_id']}: which alias class, and is the group that model?",
                    "resolves": [r["decision_id"]], "units_at_stake": int0(r["provider_units_lifetime"]), "why_first": "alias with decisive registration-series evidence and real volume", "where_the_answer_goes": "catalog_alias_collisions.csv owner_* and create_candidates.csv",
                    "owner_answer": "", "owner_notes": ""})
    alias_groups = {r["provider_group_id"] for r in alias_rows}
    brand_groups = {r["provider_group_id"] for r in brand_rows}
    first_create = [c for c in create_rows if c["provider_group_id"] not in alias_groups | brand_groups and
                    ((c["risk_tier"].startswith("P1") and c["units_lifetime"] >= FIRST_WAVE["p1_min_units"]) or (c["risk_tier"].startswith("P2") and c["units_lifetime"] >= FIRST_WAVE["p2_min_units"]))]
    for c in first_create:
        out.append({"item_id": f"INIT-{c['decision_id']}", "wave": 1, "kind": "CREATE_VERDICT", "question": f"Should TDR have a canonical model for {c['provider_brand']} {c['provider_name']} ({c['proposed_canonical_id']})?",
                    "resolves": [c["decision_id"]], "units_at_stake": c["units_lifetime"], "why_first": "; ".join(c["risk_categories"][:3]), "where_the_answer_goes": "create_candidates.csv owner_verdict (+ owner_discovery_class)", "owner_answer": "", "owner_notes": ""})
    starter = [r for r in view if r["starter_batch"]]
    decided_elsewhere = {r["model_group_id"] for r in starter if r["interacts_with"]}
    for b, label in (("S1_AUTO_PAIRS", "v1 AUTO pairs that carry 80% of AUTO-pair units"), ("S2_LEGACY_AUTO_NOT_AUTO", "legacy AUTO rows that v1 does not AUTO (the units-heaviest 80%)"),
                     ("S3_KNOWN_FAMILY", "the largest row of each known-case family"), ("S4_STRUCTURAL", "PART_OF / COMPOSED_OF and several-viable-candidate rows")):
        rows = [r for r in starter if b in r["starter_batch"]]
        out.append({"item_id": f"INIT-R6-{b.split('_')[0]}", "wave": 1, "kind": "R6_PAIR_VERDICTS", "question": f"Pair verdicts for review ranks {', '.join(r['review_rank'] for r in sorted(rows, key=lambda x: int(x['review_rank'])))} ({label}).",
                    "resolves": [f"R6-{r['review_rank']}" for r in rows], "units_at_stake": sum(r["ice_lifetime_units"] for r in rows), "why_first": label,
                    "where_the_answer_goes": "r6_owner_review.csv owner_verdict / owner_link_type / owner_canonical_model_id (not this pack)", "owner_answer": "", "owner_notes": ""})
    distinct = sorted({r["review_rank"] for r in starter}, key=int)
    create_units = sum(c["units_lifetime"] for c in create_rows)
    stats = {"contract_questions": 3 + 1, "alias_verdicts": len(strong), "create_verdicts": len(first_create), "r6_rows_distinct": len(distinct), "r6_rows_also_decided_elsewhere": len(decided_elsewhere),
             "r6_rows_alone": len(distinct) - len(decided_elsewhere), "owner_actions": 4 + len(strong) + len(first_create) + len(distinct) - len(decided_elsewhere),
             "create_units_first_wave": sum(c["units_lifetime"] for c in first_create) + sum(r["units_lifetime"] for r in brand_rows if r["provider_group_id"] in {c["provider_group_id"] for c in create_rows}) + sum(int0(r["provider_units_lifetime"]) for r in strong),
             "create_units_total": create_units, "r6_units_first_wave": sum(r["ice_lifetime_units"] for r in starter), "starter_ranks": distinct}
    return out, stats


def build_queue(inp: Inputs, init: list[dict], alias_rows, brand_rows, create_rows, view, neg_rows) -> list[dict]:
    done = set()
    rows = []

    def add(wave, kind, item, file, units, why):
        if (kind, item) in done:
            return
        done.add((kind, item))
        rows.append({"queue_position": len(rows) + 1, "wave": wave, "item_kind": kind, "item_id": item, "detail_file": file, "units_at_stake": units, "why_in_this_wave": why})

    for i in init:
        add(1, i["kind"], i["item_id"], "initial_owner_decisions.csv", i["units_at_stake"], i["why_first"])
    init_ids = {i["item_id"] for i in init}
    first = {x for i in init for x in i["resolves"]}
    for r in alias_rows:
        w1 = f"INIT-{r['decision_id']}" in init_ids
        add(1 if w1 else 2, "ALIAS_ROW", r["decision_id"], "catalog_alias_collisions.csv", int0(r["provider_units_lifetime"]), "decisive series evidence and real volume" if w1 else "thin volume: follows from the INIT-04 rule")
    for r in brand_rows:
        add(1, "BRAND_CASE", r["decision_id"], "brand_resolution_cases.csv", r["units_lifetime"], "closed by the contract-level answer (INIT-01..03)")
    for c in create_rows:
        w1 = f"INIT-{c['decision_id']}" in init_ids or c["decision_id"] in first or f"INIT-{c['alias_decision_id']}" in init_ids
        tier3 = c["risk_tier"].startswith("P3")
        spot = c["p3_spot_check_sample"] == "yes"
        add(1 if w1 else (2 if (spot or not tier3) else 3), "CREATE_ROW", c["decision_id"], "create_candidates.csv", c["units_lifetime"],
            "first wave" if w1 else (("P3 bulk, in the spot-check sample" if spot else "P3 bulk: confirm after the spot check, escalate if it finds one wrong") if tier3 else "P1/P2: needs a row review"))
    starter_ranks = set(first)
    for r in view:
        rid = f"R6-{r['review_rank']}"
        add(1 if rid in starter_ranks else (2 if r["in_first_176"] == "yes" else 3), "R6_ROW", rid, "r6_priority_view.csv", r["ice_lifetime_units"], "starter batch" if rid in starter_ranks else ("first 176 rows, not in the starter batch" if r["in_first_176"] == "yes" else "tiers 3-7"))
    for n in neg_rows:
        add(3, "NEGATIVE_SAMPLE", n["sample_id"], "negative_sample.csv", n["units_lifetime"], "recall denominator: needed after labels exist")
    rows.sort(key=lambda r: (r["wave"], r["queue_position"]))
    for i, r in enumerate(rows, start=1):
        r["queue_position"] = i
    return rows


# ----------------------------------------------------------------------------------------------------------------------------- assembling the pack
FILES = {
    "catalog_alias_collisions.csv": (ALIAS_COLUMNS, "alias"), "brand_resolution_cases.csv": (BRAND_COLUMNS, "brand"), "create_candidates.csv": (CREATE_COLUMNS, "create"),
    "r6_create_reconciliation.csv": (RECON_COLUMNS, "recon"), "verdict_crosswalk.csv": (CROSSWALK_COLUMNS, "crosswalk"), "r6_priority_view.csv": (R6_VIEW_COLUMNS, "view"),
    "brand_folds.csv": (FOLD_COLUMNS, "folds"), "negative_sample.csv": (NEG_COLUMNS, "neg"), "pending_threshold_sensitivity.csv": (THRESH_COLUMNS, "thresh"),
    "calibration_entry_requirements.csv": (ENTRY_COLUMNS, "entry"), "initial_owner_decisions.csv": (INIT_COLUMNS, "init"), "decision_queue.csv": (QUEUE_COLUMNS, "queue")}
OWNER_FIELDS = {"catalog_alias_collisions.csv": ["owner_alias_class", "owner_provider_verdict", "owner_canonical_model_id", "owner_notes"],
                "brand_resolution_cases.csv": ["owner_decision", "owner_notes"], "create_candidates.csv": ["owner_verdict", "owner_canonical_model_id", "owner_discovery_class", "owner_notes"],
                "negative_sample.csv": ["owner_has_tdr_counterpart", "owner_canonical_model_id", "owner_link_type", "owner_notes"], "initial_owner_decisions.csv": ["owner_answer", "owner_notes"]}


def build_tables(inp: Inputs) -> dict:
    if inp.series is None:
        raise SystemExit("owner_decision_pack/inputs/series_evidence.json is missing: run `collect` once with the archived M7.0 package")
    alias = build_alias_table(inp)
    brand = build_brand_cases(inp)
    create = build_create_table(inp, alias, brand)
    for r in alias:   # the two series-coincident CREATE candidates that carry no alias hit are listed on every alias row, so the owner sees the whole family at once
        r["also_series_coincident_without_alias_hit"] = sorted(c["provider_group_id"] for c in create if c["series_coincident_targets"] and not c["alias_decision_id"])
    view, meta = build_r6_view(inp, alias, create, brand)
    for r in create:
        r["brand_family"] = meta["families_of_brand"].get(ck(r["provider_brand"]), ck(r["provider_brand"]))
        r["fold"] = fold_for(meta, r["brand_family"])
    starter_groups = {r["model_group_id"] for r in view if r["starter_batch"]}
    neg, neg_summary = build_negative_sample(inp, meta)
    init, istats = build_initial(inp, alias, brand, create, view, meta)
    for rows_ in (alias, brand, create, view, neg):
        for r in rows_:
            r["evidence_refs"] = REF_SEP.join(r["evidence_refs"])
    return {"alias": alias, "brand": brand, "create": create, "recon": build_reconciliation(inp, create), "crosswalk": verdict_crosswalk(), "view": view, "folds": build_folds(inp, view, meta, create, neg),
            "neg": neg, "thresh": build_threshold_table(inp, starter_groups), "entry": build_entry_requirements(inp, view, meta, neg_summary), "init": init, "queue": build_queue(inp, init, alias, brand, create, view, neg),
            "meta": meta, "neg_summary": neg_summary, "istats": istats}


def span(ids: list[str]) -> str:
    return " ".join(ids) if len(ids) <= 3 else f"{ids[0]} .. {ids[-1]} ({len(ids)})"


def md_table(cols: list[str], rows: list[list]) -> str:
    esc = lambda x: cell(x).replace("|", "\\|").replace("\n", " ")
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"] + ["| " + " | ".join(esc(x) for x in r) + " |" for r in rows])


def alias_reading(r: dict) -> str:
    sig = set(r["signals"])
    t, g = r["existing_identity_id"], r["provider_name"]
    if "SERIES_COINCIDES" in sig:
        return (f"{g} and {t} register together (corr {r['series_correlation']}, ratio {r['series_ratio']}, {r['series_common_months']} common months) and no other Ice group is EQUAL to {t}: "
                f"the registrations behind the catalog model are this group's. The alias reads as the same model.")
    if "OTHER_EQUAL_CLAIMANT" in sig and "ADDING_PROVIDER_IMPROVES_MATCH" in sig:
        return (f"{t} already has Ice claimant(s) {', '.join(r['other_ice_claimants_equal'])}; adding {g} moves their combined series toward {t} ({r['claimants_alone_series']} -> {r['claimants_plus_provider_series']}). "
                f"TDR files this group's registrations under {t} while its body/segment differ ({r['provider_body'] or '-'} / {r['provider_segment'] or '-'} vs {r['existing_identity_body_type']} / {r['existing_identity_segment']}): a broader-family label, not a same-model alias.")
    if "OTHER_EQUAL_CLAIMANT" in sig and "CLAIMANT_ALONE_ALREADY_STRONG" in sig:
        return (f"{t}'s registrations are already explained by {', '.join(r['other_ice_claimants_equal'])} ({r['claimants_alone_series']}); {g} does not match them ({r['series_state']} corr {r['series_correlation']}) and "
                f"the model sells about {r['existing_units_in_window']} units to the group's {r['provider_units_in_window']} in the window. "
                f"The group was registered from {r['provider_first_seen']} (catalog launch year of {t}: {r['existing_identity_launch_year']}), so it reads as a misleading alias; whether it is a predecessor, a rename or a separate model is the owner's call (the pack holds no lineage evidence).")
    if "MANY_GRANULAR_CLAIMANTS" in sig:
        return (f"{t} has {len(r['other_ice_claimants_granular'])} finer or coarser Ice groups and a different body/segment ({r['provider_body'] or '-'} vs {r['existing_identity_body_type']}); the alias reads as a trim/variant label inside a larger family. No series ({r['series_state']}).")
    return f"No registration series decides this ({r['series_state']}); {r['provider_units_lifetime']} lifetime units. Left to the owner."


def render_report(inp: Inputs, T: dict) -> str:
    alias, brand, create, view, meta, init, ist = T["alias"], T["brand"], T["create"], T["view"], T["meta"], T["init"], T["istats"]
    n_create, n_r6 = len(create), len(view)
    first = [r for r in view if r["in_first_176"] == "yes"]
    rec = T["recon"]
    in_sheet = {r["provider_group_id"] for r in rec if r["in_r6_sheet"] == "yes"}
    create_in_176 = {r["model_group_id"] for r in first} & {c["provider_group_id"] for c in create}
    c = collections.Counter
    tier = c(r["risk_tier"] for r in create)
    triage = c(r["machine_triage_NON_AUTHORITATIVE"] for r in create)
    cats176 = c(x for r in first for x in r["risk_categories"] if not x.startswith("KNOWN_FAMILY"))
    legacy_auto = [r for r in inp.r6 if r["legacy_r6_status"] == "AUTO"]
    la_not_auto = [r for r in legacy_auto if r["v1_group_outcome"] != "AUTO"]
    lp_auto = [r for r in inp.r6 if r["legacy_r6_status"] == "PROPOSED" and r["v1_group_outcome"] == "AUTO"]
    wave1_rows = sum(1 for q in T["queue"] if q["item_kind"] == "CREATE_ROW" and q["wave"] == 1)
    wave1_units = sum(q["units_at_stake"] for q in T["queue"] if q["item_kind"] == "CREATE_ROW" and q["wave"] == 1)
    total_units = sum(r["units_lifetime"] for r in create)
    out = []
    w = out.append
    w("# Owner Decision & Calibration Preparation Pack\n")
    w(f"> **Preparation only. Nothing here is decided, calibrated, approved or bound.** Pack `{PACK_ID}`, branch `claude/wizardly-keller-0ixbhj`, PR #200 (draft), `adoption.binding = false`. "
      f"Built from the accepted relation export (`ir-relation-export/1`, manifest sha256 `{sha256_file(E.OUT / 'MANIFEST.json')[:12]}`) and four byte-pinned PR #201 artifacts @`{PR201_COMMIT[:9]}`. "
      "No rule, policy value, export or sheet was changed. Every `owner_*` field in every file is blank; every column named `*_NON_AUTHORITATIVE` is a machine suggestion the owner may ignore.\n")
    w("Two kinds of verdict are kept apart (`verdict_crosswalk.csv`): the R6 sheet asks **is this Ice group this TDR model?** (a pair); PR #201's adjudication asks **should TDR have a model for this group at all?** (a group). "
      "A pair verdict never implies a group verdict or the reverse; `check_label_consistency()` only flags answers that cannot both be true.\n")
    w("## 1. The smallest first set\n")
    w(f"Nothing here requires all {n_r6} R6 rows to be labelled. The first wave is **{ist['owner_actions']} owner actions**: {ist['contract_questions']} rule/filing questions, {ist['alias_verdicts']} alias verdicts, {ist['create_verdicts']} CREATE verdicts and "
      f"{ist['r6_rows_alone']} R6 pair verdicts ({ist['r6_rows_distinct']} starter rows; {ist['r6_rows_also_decided_elsewhere']} of them is answered together with an alias or CREATE verdict). "
      f"It covers {round(100 * meta['s1_units'] / meta['auto_pair_units'], 1)}% of the lifetime units of all {meta['auto_pairs']} AUTO pairs, every known suspicious-case family, every PART_OF / COMPOSED_OF and several-candidate row, "
      f"and {round(100 * wave1_units / total_units, 1)}% of the lifetime units of the {n_create} CREATE candidates ({wave1_rows} rows). "
      "It is built to find a systematic failure early, not to certify a rate (see §7).\n")
    w(md_table(["item", "kind", "question", "resolves", "units"], [[i["item_id"], i["kind"], i["question"], span(i["resolves"]), i["units_at_stake"]] for i in init]))
    w("\nThe full order, with later waves, is `decision_queue.csv`.\n")
    w("## 2. R6 owner sheet vs PR #201's 82 provisional CREATE candidates\n")
    w(f"- {len(in_sheet)} of the {n_create} candidates appear in `r6_owner_review.csv` ({len(rec) - c(r['in_r6_sheet'] for r in rec)['no']} sheet rows): "
      f"{c(r['relationship'] for r in rec)['LEGACY_PAIR_OPEN_AND_CREATE_OPEN']} legacy-proposed pairs, {c(r['relationship'] for r in rec)['V1_ONLY_PAIR_OPEN_AND_CREATE_OPEN']} v1-only pairs, "
      f"{c(r['relationship'] for r in rec)['IN_SHEET_WITHOUT_CANDIDATE']} without a candidate. The other {n_create - len(in_sheet)} have only the missing-identity question.")
    w(f"- {len(create_in_176)} of the first 176 prioritised rows are CREATE candidates ({', '.join(sorted(create_in_176))}): for them a pair verdict and a group verdict are two questions about one group. "
      "`r6_create_reconciliation.csv` lists every (candidate, sheet row) pair with the owner field each verdict goes into.")
    w("- Readings: a CORRECT_EQUIVALENT pair contradicts VALID_MISSING_CANONICAL; WRONG_TARGET leaves the group question open; NO_TDR_TARGET contradicts EXISTING_IDENTITY / VARIANT_TRIM_CODE; PART_OF / COMPOSED_OF with a new model is a REVIEW prompt, not a conflict.\n")
    w(md_table(["pair verdict \\ group verdict"] + CREATE_VERDICTS, [[p] + [_crosswalk_reading(p, g_)[0] for g_ in CREATE_VERDICTS] for p in R6_VERDICTS]))
    w("\n## 3. Section A: nine TDR catalog-alias collisions (`catalog_alias_collisions.csv`)\n")
    w("A catalog model `aliases` entry equals the provider group's name. The machine class is not EQUAL by default: it is read from the registration series of the group and of the model's existing Ice claimants. "
      "A SEARCH_DISPLAY_SYNONYM is never suggested (the data cannot tell a lookup convenience from an identity claim); that distinction is the owner's.\n")
    w(md_table(["id", "provider group (units)", "alias -> catalog model", "series", "other EQUAL claimants", "suggested class (non-auth.)", "evidence"],
               [[r["decision_id"], f"{r['provider_group_id']} ({r['provider_units_lifetime']})", f"{'/'.join(r['matching_alias_strings'])} -> {r['existing_identity_id']} ({r['existing_identity_name_en']}, {r['existing_identity_body_type']}, aliases: {len(r['existing_identity_all_aliases'])})",
                 f"{r['series_state']} {r['series_correlation']} / {r['series_common_months']}m", r["other_ice_claimants_equal"], r["machine_suggested_alias_class_NON_AUTHORITATIVE"], r["evidence_sufficiency"]] for r in alias]))
    w("")
    for r in alias:
        w(f"- **{r['decision_id']}** {alias_reading(r)}")
    extra = alias[0]["also_series_coincident_without_alias_hit"]
    w(f"\nTwo further CREATE candidates have registrations that coincide with a catalog model although no alias matched: {', '.join(extra)} (`create_candidates.csv`, tier P1). Full catalog records, token lists and source references are in the CSV.\n")
    w("## 4. Section B: brand resolution and the Maxus filing question (`brand_resolution_cases.csv`)\n")
    w(md_table(["id", "group (units)", "label", "producer relation", "catalog label lookup", "disagreement"],
               [[r["decision_id"], f"{r['provider_group_id']} ({r['units_lifetime']})", r["provider_brand_label"], "; ".join(x.split(":")[0] + " " + x.split(":")[1] for x in r["producer_brand_relations"]) or "none",
                 r["consumer_catalog_label_resolution"], r["disagreement_kind"].replace("__", " / ").replace("_", " ").lower()] for r in brand]))
    w("\nThe eight unresolved parity rows are one of two things. Seven (Mercedes AMG, Maybach, Range Rover, Maxus EPC1A) are brands the producer admits as **RELATED** (pool allowed, never AUTO) and no catalog brand record carries the label, "
      "so a consumer that looks the label up itself finds nothing. One (JETOUR) is the opposite: a catalog brand `aliases` entry (Chery: omoda, jetour) resolves it and the producer has no relation. "
      "Neither is a matching-rule defect; both are about **who decides a brand relation**. Contract-level options, none naming a brand or model:\n")
    w("1. **Relation-first** (recommended, INIT-01): the producer's typed relation is the one place a brand relation is decided; a consumer takes its pool from it and never reports BRAND_NOT_IN_TDR for a brand the producer relates.")
    w("2. **Catalog aliases are not brand relations until typed** (recommended, INIT-02): a catalog brand `aliases` entry is a registration-attribution label; the owner types it (SAME / RELABEL / RELATED) with a provenance before it counts. JETOUR is the one label to type now.")
    w("3. **Maxus filing** (INIT-03, a catalog decision): the catalog files Maxus models under brand `mg` (mg.mg_maxus_7, mg.mg_maxus_9) and has no Maxus brand; Ice registers V80 and Mifa 7/9 under MG; policy already types MAXUS/MG RELATED and MAXUS/'MG Maxus' RELABEL. "
      "The V80 CREATE (OD-C11, proposed `mg.maxus_v80`) and the two Mifa identity reviews follow that one decision.\n")
    w(f"## 5. Section C: R6 calibration cases, first 176 rows (`r6_priority_view.csv`)\n")
    w(f"The first 176 rows are tier 1 (82 legacy AUTO rows) and tier 2 (94 high-volume legacy PROPOSED rows). Risk categories in them: " + ", ".join(f"{k} {v}" for k, v in sorted(cats176.items(), key=lambda kv: -kv[1])) + ".\n")
    w(f"- Of {len(legacy_auto)} legacy AUTO rows, **{len(la_not_auto)}** are not AUTO under the current contract ({c(r['v1_group_outcome'] for r in la_not_auto).most_common()}); {len(lp_auto)} legacy PROPOSED rows become AUTO. "
      "Which side is right is exactly what the labels decide, so S2 and S1 are the two ends of one question.")
    w(f"- Starter batch (`starter_batch` column): S1 {meta['s1']} v1-AUTO pairs (≥{int(STARTER_FRACTION * 100)}% of AUTO-pair units); S2 {meta['s2']} legacy-AUTO rows that v1 does not AUTO (≥{int(STARTER_FRACTION * 100)}% of their units); "
      f"S3 {meta['s3']} known-family representatives; S4 {meta['s4']} structural rows; {ist['r6_rows_distinct']} distinct rows. Rows are assigned to {TRIAGE['folds']} brand-separated folds over {meta['families']} brand families (rows per fold {meta['fold_weights']}).\n")
    w("## 6. Section D: all 82 CREATE candidates, grouped by risk (`create_candidates.csv`)\n")
    w(md_table(["tier", "rows", "units", "evidence", "suggested triage (non-auth.)"],
               [[t, tier[t], sum(r["units_lifetime"] for r in create if r["risk_tier"] == t), "needs a row review" if not t.startswith("P3") else f"spot-check {SPOT_CHECK_N}, then confirm or escalate",
                 ", ".join(f"{k} {v}" for k, v in c(r["machine_triage_NON_AUTHORITATIVE"] for r in create if r["risk_tier"] == t).most_common())] for t in sorted(tier)]))
    w(f"\nP1 = contradicting evidence (alias, brand collision, coinciding series, strong legacy proposal). P2 = high volume, current market or a code-like name with no contradicting evidence. P3 = historical bulk. "
      f"Age and volume never make a candidate false (PR #201's rule); they only order the work. The spot-check sample is the first {SPOT_CHECK_N} P3 rows by a fixed hash.\n")
    w("## 7. Calibration after labels exist (`calibration_procedure.json`)\n")
    w("- **Labels → ground truth**: pair labels give positives (per link type) and negatives; group labels make every pooled candidate of a VALID_MISSING_CANONICAL group a negative; AMBIGUOUS / INSUFFICIENT_EVIDENCE are excluded and counted. `check_label_consistency()` runs first.")
    w(f"- **Brand-separated evaluation**: {TRIAGE['folds']} folds of brand families (`brand_folds.csv`); tune on four, evaluate once on the fifth, report pooled out-of-fold predictions. No threshold is tuned on a family it is evaluated on.")
    w("- **Metrics**: AUTO precision and false-AUTO count (Wilson interval; rule of three when zero), AUTO recall, PROPOSE precision, PROPOSE-or-better recall using the weighted negative sample for the pairs the contract missed; each also unit-weighted.")
    w("- **False-AUTO analysis**: each false-AUTO is listed with its codes and classified (series coincidence, granularity, lineage, brand relation, label noise); a root cause that a gate could express is a proposal for a later round, never applied in the same pass.")
    w("- **Pending thresholds**: each is re-run at its swept values on the labelled rows (`pending_threshold_sensitivity.csv`); an entry that moves no labelled row stays pending.\n")
    w(md_table(["requirement", "value", "meaning"], [[r["requirement_id"], r["value"], r["meaning"]] for r in T["entry"]]))
    w(f"\nThe honest limit: only {meta['auto_pairs']} AUTO pairs exist, so even a fully labelled, error-free set bounds false-AUTO at {round(100 * 3 / meta['auto_pairs'], 1)}% (95%); the starter batch bounds it at {round(100 * 3 / meta['s1'], 1)}%. "
      "A tolerance tighter than that cannot be shown from this sheet; it needs structural argument, more packages, or a different AUTO scope.\n")
    th = [r for r in T["thresh"] if r["max_groups_changed"]]
    w("Pending calibration entries whose swept values move at least one group (the rest are not constrained by the sheet): " + "; ".join(f"`{r['adoption_entry']}` ({r['max_groups_changed']} groups, AUTO +{r['max_auto_gained']}/−{r['max_auto_lost']})" for r in th) + ".\n")
    w("## 8. Outstanding owner questions\n")
    qs = [
        "**Q1 (INIT-01)** Relation-first: may a consumer take its candidate set from the producer's RELATED brand relation instead of resolving the brand itself?",
        "**Q2 (INIT-02)** Are catalog brand `aliases` ever a brand relation? If so, which typed class for JETOUR (and the Chery `omoda` alias), with which provenance?",
        "**Q3 (INIT-03)** Are Maxus-badged models filed under MG or a Maxus brand? (Decides V80's canonical id.)",
        "**Q4 (INIT-04)** What does a catalog model alias assert? Which of A01–A05 are the same model, a broader family, or a misleading alias?",
        "**Q5** CREATE verdicts for the first-wave rows, including the two series-coincident candidates that carry no alias (OD-C04 volt, OD-C06 j6).",
        "**Q6** Pair verdicts for the starter rows, led by the v1-AUTO pairs and the legacy-AUTO rows v1 does not AUTO.",
        "**Q7** What false-AUTO rate would you accept as AUTO's bar? It fixes how many AUTO labels are needed (ER-T rows) and whether the answer is reachable.",
        "**Q8** Is a spot-check-then-confirm rule acceptable for the P3 historical bulk, or must every row be reviewed?",
        "**Q9** Do you want the negative sample (24 groups) labelled now, or only after the starter batch shows whether recall is a concern?"]
    for q in qs:
        w(f"- {q}")
    w("\n## 9. Inventory and reproduction\n")
    w("`catalog_alias_collisions.csv`, `brand_resolution_cases.csv`, `create_candidates.csv`, `r6_create_reconciliation.csv`, `verdict_crosswalk.csv`, `r6_priority_view.csv`, `brand_folds.csv`, `negative_sample.csv`, "
      "`pending_threshold_sensitivity.csv`, `calibration_entry_requirements.csv`, `initial_owner_decisions.csv`, `decision_queue.csv`, `calibration_procedure.json`, `MANIFEST.json`, and `inputs/` (four byte-pinned PR #201 files with `PROVENANCE.json`, `series_evidence.json`).\n")
    w("```\ncd automotive/vehicle_master\npython -m identity_resolution.calibration.owner_decision_pack collect   # once; needs the archived M7.0 package\npython -m identity_resolution.calibration.owner_decision_pack build     # offline\npython -m identity_resolution.calibration.owner_decision_pack verify    # offline\n```\n")
    return "\n".join(out) + "\n"


def build_files(inp: Inputs) -> dict[str, bytes]:
    T = build_tables(inp)
    files = {name: csv_bytes(cols, T[key]) for name, (cols, key) in FILES.items()}
    files["calibration_procedure.json"] = canonical_json(CALIBRATION_PROCEDURE)
    files["OWNER_DECISION_PACK.md"] = render_report(inp, T).encode("utf-8")
    manifest = {"schema": "ir-owner-decision-pack-manifest/1", "pack": PACK_ID, "binding": inp.adoption["binding"], "pr201_commit": PR201_COMMIT,
                "export_manifest_sha256": sha256_file(E.OUT / "MANIFEST.json"), "r6_owner_review_sha256": sha256_file(A.CALIBRATION_DIR / "r6_owner_review.csv"),
                "series_evidence_sha256": sha256_file(SERIES_JSON), "pr201_inputs": json.loads((IN201 / "PROVENANCE.json").read_text(encoding="utf-8"))["files"],
                "counts": {"alias_rows": len(T["alias"]), "brand_cases": len(T["brand"]), "create_rows": len(T["create"]), "r6_view_rows": len(T["view"]), "starter_rows": T["istats"]["r6_rows_distinct"],
                           "negative_sample": len(T["neg"]), "first_wave_owner_actions": T["istats"]["owner_actions"], "queue": len(T["queue"])},
                "files": {n: {"sha256": sha256_bytes(b), "bytes": len(b)} for n, b in sorted(files.items())}}
    files["MANIFEST.json"] = canonical_json(manifest)
    return files


def build() -> dict[str, bytes]:
    files = build_files(Inputs())
    OUT.mkdir(parents=True, exist_ok=True)
    for n, b in files.items():
        (OUT / n).write_bytes(b)
    return files


def verify() -> list[str]:
    files = build_files(Inputs())
    return [n for n, b in files.items() if not (OUT / n).exists() or (OUT / n).read_bytes() != b]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["vendor", "collect", "build", "verify"])
    a = ap.parse_args(argv)
    if a.command == "vendor":
        vendor_pr201()
    elif a.command == "collect":
        SERIES_JSON.parent.mkdir(parents=True, exist_ok=True)
        SERIES_JSON.write_bytes(canonical_json(collect_series_evidence()))
    elif a.command == "build":
        build()
    else:
        bad = verify()
        if bad:
            print("stale:", ", ".join(bad))
            return 1
        print("pack is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
