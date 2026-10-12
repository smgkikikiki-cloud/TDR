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
    "owner_alias_class", "owner_notes"]


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
            "owner_alias_class": "", "owner_notes": ""})
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
    "evidence_refs", "owner_case_override", "owner_notes"]


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
            "contract_level_options_NON_AUTHORITATIVE": "", "recommended_resolution_NON_AUTHORITATIVE": "", "evidence_refs": refs, "owner_case_override": "", "owner_notes": ""})
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


# ----------------------------------------------------------------------------------------------------------------------------- ground truth per link type (ODP-1)
LINKS = ("EQUIVALENT", "PART_OF", "COMPOSED_OF")
PAIR_LINK = {"CORRECT_EQUIVALENT": "EQUIVALENT", "CORRECT_PART_OF": "PART_OF", "CORRECT_COMPOSED_OF": "COMPOSED_OF"}
TRUTH_STATES = ("POSITIVE", "NEGATIVE", "UNKNOWN", "EXCLUDED", "CONFLICT")


def derive_truth(pool: list[str], pair_labels: list[dict], group_label: dict | None, proposed_link: dict[str, str] | None = None) -> tuple[dict, list[dict]]:
    """Per-(candidate, link type) ground truth for one group, from the owner's labels. Nothing is inferred across link types.

    * a pair label speaks for the link type it names: CORRECT_EQUIVALENT / CORRECT_PART_OF / CORRECT_COMPOSED_OF are POSITIVE for that link type; WRONG_TARGET / NO_TDR_TARGET are NEGATIVE for the
      link type the sheet row proposed (default EQUIVALENT) and say nothing about the others; INSUFFICIENT_EVIDENCE excludes the candidate;
    * a group label speaks only about EQUIVALENT identity: VALID_MISSING_CANONICAL = no exact canonical identity = EQUIVALENT NEGATIVE for every pooled candidate, and nothing about PART_OF /
      COMPOSED_OF (a group may have no model of its own and still be part of, or composed of, existing ones); EXISTING_IDENTITY names the one EQUIVALENT target (every other candidate is EQUIVALENT
      NEGATIVE by cardinality rule C1); VARIANT_TRIM_CODE and AMBIGUOUS assert no pair relation at all (a variant is not an EQUIVALENT pair until the owner labels the link);
    * an explicit pair label always wins over a group-derived value only when they agree; a disagreement on the same cell is a CONFLICT (returned, and the cell is unusable until resolved).
    Returns ({(candidate, link): state}, [conflicts and review notes])."""
    proposed_link = proposed_link or {}
    cells = {(c, l): "UNKNOWN" for c in pool for l in LINKS}
    notes: list[dict] = []
    explicit: set = set()

    def put(cell, state, source):
        cur = cells[cell]
        if cur in ("UNKNOWN",):
            cells[cell] = state
        elif cur == "CONFLICT" or cur == state:
            pass
        elif state == "EXCLUDED" or cur == "EXCLUDED":
            cells[cell] = "EXCLUDED"
        else:
            cells[cell] = "CONFLICT"
            notes.append({"severity": "CONFLICT", "kind": "TRUTH_CELL_DISAGREES", "cell": cell, "detail": f"{cur} vs {state} ({source})"})

    for p in pair_labels:
        c, v = p["candidate"], p["verdict"]
        if c not in pool:
            notes.append({"severity": "REVIEW", "kind": "LABEL_CANDIDATE_OUTSIDE_POOL", "cell": (c, ""), "detail": v})
            continue
        if v in PAIR_LINK:
            put((c, PAIR_LINK[v]), "POSITIVE", "pair")
            explicit.add((c, PAIR_LINK[v]))
        elif v in ("WRONG_TARGET", "NO_TDR_TARGET"):
            put((c, proposed_link.get(c, "EQUIVALENT")), "NEGATIVE", "pair")
            explicit.add((c, proposed_link.get(c, "EQUIVALENT")))
        elif v == "INSUFFICIENT_EVIDENCE":
            for l in LINKS:
                cells[(c, l)] = "EXCLUDED"
    if group_label:
        gv, canon = group_label["verdict"], group_label.get("canonical")
        if gv == "VALID_MISSING_CANONICAL":
            for c in pool:
                put((c, "EQUIVALENT"), "NEGATIVE", "group")
            for p in pair_labels:
                if p["verdict"] in ("CORRECT_PART_OF", "CORRECT_COMPOSED_OF"):
                    notes.append({"severity": "REVIEW", "kind": "MISSING_IDENTITY_WITH_STRUCTURAL_RELATION", "cell": (p["candidate"], PAIR_LINK[p["verdict"]]),
                                  "detail": "no exact canonical identity, valid structural relation: kept as a positive for that link type only"})
        elif gv == "EXISTING_IDENTITY":
            if canon in pool:
                put((canon, "EQUIVALENT"), "POSITIVE", "group")
                for c in pool:
                    if c != canon:
                        put((c, "EQUIVALENT"), "NEGATIVE", "group (C1)")
            else:
                notes.append({"severity": "REVIEW", "kind": "GROUP_TARGET_OUTSIDE_POOL", "cell": (canon or "", "EQUIVALENT"), "detail": "the owner's model is not a pooled candidate: a recall miss, not a pair label"})
        # VARIANT_TRIM_CODE and AMBIGUOUS: no pair truth is inferred
    # C1: a CORRECT_EQUIVALENT candidate makes every other candidate EQUIVALENT-negative
    for c, l in sorted(explicit):
        if l == "EQUIVALENT" and cells[(c, l)] == "POSITIVE":
            for o in pool:
                if o != c:
                    put((o, "EQUIVALENT"), "NEGATIVE", "pair (C1)")
    return cells, notes


def metric_rows(link: str, cells: dict, predictions: dict) -> tuple[list[dict], dict]:
    """The rows one link type's metrics may use: only POSITIVE / NEGATIVE cells of THAT link type. `predictions[(candidate, link)]` is AUTO / PROPOSE / NONE. Everything else is counted, not scored."""
    rows, skipped = [], collections.Counter()
    for (c, l), st in sorted(cells.items()):
        if l != link:
            continue
        if st in ("POSITIVE", "NEGATIVE"):
            rows.append({"cell": (c, l), "truth": st, "predicted": predictions.get((c, l), "NONE")})
        else:
            skipped[st] += 1
    return rows, dict(skipped)


def confusion(rows: list[dict]) -> dict:
    n = collections.Counter()
    for r in rows:
        pos, auto, prop = r["truth"] == "POSITIVE", r["predicted"] == "AUTO", r["predicted"] in ("AUTO", "PROPOSE")
        n["tp_auto"] += pos and auto
        n["fp_auto"] += (not pos) and auto
        n["fn_auto"] += pos and not auto
        n["tp_prop"] += pos and prop
        n["fp_prop"] += (not pos) and prop
        n["fn_prop"] += pos and not prop
    return dict(n)


# ----------------------------------------------------------------------------------------------------------------------------- threshold selection on training folds only (ODP-2)
def select_threshold(grid: list, train_rows: list[dict]) -> dict:
    """Choose one value from `grid` (ordered loosest -> strictest, registered before any label is read) using TRAINING rows only. Row: {"truth": POSITIVE | NEGATIVE, "auto_at": {value: bool}}.
    Eligible = zero training false-AUTO; among eligible, most training true-AUTO; a tie goes to the stricter value; if nothing is eligible the strictest value is chosen and flagged. The function is handed
    no held-out row and no tolerance: it cannot depend on them."""
    stats = {}
    for v in grid:
        fa = sum(1 for r in train_rows if r["truth"] == "NEGATIVE" and r["auto_at"][v])
        tp = sum(1 for r in train_rows if r["truth"] == "POSITIVE" and r["auto_at"][v])
        stats[v] = {"train_false_auto": fa, "train_true_auto": tp}
    eligible = [v for v in grid if stats[v]["train_false_auto"] == 0]
    if not eligible:
        return {"selected": grid[-1], "flag": "NO_VALUE_WITHOUT_TRAINING_FALSE_AUTO", "train": stats}
    best = max(stats[v]["train_true_auto"] for v in eligible)
    chosen = [v for v in eligible if stats[v]["train_true_auto"] == best][-1]
    return {"selected": chosen, "flag": "", "train": stats}


def calibrate_by_fold(grid: list, rows: list[dict], n_folds: int) -> dict:
    """Pass 1 selects one value per fold from the other folds' rows and freezes it; pass 2 evaluates each frozen value ONCE on its own held-out fold. Nothing from pass 2 flows back."""
    selections = {k: select_threshold(grid, [r for r in rows if r["fold"] != k]) for k in range(n_folds)}
    folds = {}
    for k in range(n_folds):
        held = [r for r in rows if r["fold"] == k]
        v = selections[k]["selected"]
        folds[k] = {"selected": v, "flag": selections[k]["flag"], "heldout_rows": len(held),
                    "heldout_false_auto": sum(1 for r in held if r["truth"] == "NEGATIVE" and r["auto_at"][v]), "heldout_true_auto": sum(1 for r in held if r["truth"] == "POSITIVE" and r["auto_at"][v]),
                    "heldout_positives": sum(1 for r in held if r["truth"] == "POSITIVE"), "heldout_auto_predictions": sum(1 for r in held if r["auto_at"][v])}
    pooled = {key: sum(f[key] for f in folds.values()) for key in ("heldout_rows", "heldout_false_auto", "heldout_true_auto", "heldout_positives", "heldout_auto_predictions")}
    return {"selections": {k: v["selected"] for k, v in selections.items()}, "folds": folds, "pooled": pooled}


def acceptance_gate(pooled: dict, tolerance: float) -> dict:
    """Final acceptance / failure evidence from the pooled held-out counts. It reads results; it is never an input to `select_threshold`. A failure means: report 'not calibrated' and plan a separately versioned experiment."""
    n, fa = pooled["heldout_auto_predictions"], pooled["heldout_false_auto"]
    upper = rule_of_three(n) if fa == 0 else wilson(fa, n)[1]
    precision = None if n == 0 else round((n - fa) / n, 6)
    recall = None if pooled["heldout_positives"] == 0 else round(pooled["heldout_true_auto"] / pooled["heldout_positives"], 6)
    ok = upper is not None and upper <= tolerance
    return {"false_auto_upper_95": upper, "auto_precision": precision, "auto_recall": recall, "tolerance": tolerance,
            "verdict": "ACCEPTANCE_EVIDENCE_MET" if ok else "FAILED_REPORT_NOT_CALIBRATED", "retune_allowed": False}


CALIBRATION_PROCEDURE = {
    "schema": "ir-owner-pack-calibration-procedure/2",
    "status": "NON_AUTHORITATIVE preparation; nothing here is calibrated and no value is chosen",
    "labels_used": {
        "pair": "r6_owner_review.csv verdicts, per link type. POSITIVE for the link type named: CORRECT_EQUIVALENT (EQUIVALENT), CORRECT_PART_OF (PART_OF), CORRECT_COMPOSED_OF (COMPOSED_OF). NEGATIVE for the link type the sheet row proposed: WRONG_TARGET, NO_TDR_TARGET; "
                "nothing is said about the other link types. INSUFFICIENT_EVIDENCE excludes the candidate (counted, not scored)",
        "group": "create_candidates.csv verdicts speak about EQUIVALENT identity only. VALID_MISSING_CANONICAL: EQUIVALENT NEGATIVE for every pooled candidate; PART_OF / COMPOSED_OF are NOT inferred (a group with no model of its own can still be part of, or composed of, existing models: "
                 "that combination is a REVIEW prompt, and the structural pair label stays a positive for its own link type). EXISTING_IDENTITY: the named model is EQUIVALENT POSITIVE and every other pooled candidate EQUIVALENT NEGATIVE (cardinality C1). "
                 "VARIANT_TRIM_CODE: no pair truth is inferred - a variant is not an EQUIVALENT pair until the owner gives an explicit, correct link label. AMBIGUOUS: excluded and counted",
        "disagreement": "a pair-derived and a group-derived value for the same (candidate, link type) cell that disagree make the cell a CONFLICT: unusable until the owner resolves it (derive_truth, check_label_consistency)",
        "scoring": "each link type is scored on its own: only POSITIVE and NEGATIVE cells of that link type enter its metrics (metric_rows); UNKNOWN, EXCLUDED and CONFLICT cells are counted and not scored",
        "negative_sample": "negative_sample.csv: owner_has_tdr_counterpart (+ owner_link_type), weighted by sampling_weight; a counterpart under another link type is not a negative for EQUIVALENT-only metrics by default",
        "consistency": "check_label_consistency() runs first; a CONFLICT is resolved by the owner before any metric is computed"},
    "design": {
        "folds": "brand_folds.csv: five folds of brand families; every row of a family sits in one fold",
        "registration": "before any label is read, the candidate grid per pending entry (ordered loosest to strictest, from the swept values in sensitivity_results.json), the tie-break and the selection rule are registered (this file + the sha256 of sensitivity_results.json in MANIFEST.json)",
        "loop": "pass 1: for each fold k, select one value from the grid using the OTHER four folds only (select_threshold is handed no held-out row and no tolerance) and freeze it; pass 2: evaluate each frozen value ONCE on its own held-out fold (calibrate_by_fold)",
        "selection_rule": "among grid values with zero TRAINING false-AUTO, the one with the most TRAINING true-AUTO pairs; a tie goes to the stricter value; if no value has zero training false-AUTO the strictest is chosen and flagged. Held-out results, pooled or per fold, are never an input",
        "acceptance_gate": "AFTER selection: the pooled held-out false-AUTO upper bound (rule of three when zero, Wilson otherwise), precision and recall are reported against the tolerance the owner sets (acceptance_gate). They are acceptance / failure evidence only",
        "failure_handling": "a failed gate freezes the result as 'not calibrated' and is reported. Any further attempt is a separately versioned experiment with a new registration; the held-out outcomes of this experiment are never used to retune it",
        "no_leakage": "no threshold, class or alias list is tuned on a row of the held-out fold's brand family; the owner's seed brand classes are inputs, not tuned values"},
    "metrics": {
        "auto_precision": "labelled-correct AUTO pairs / labelled AUTO pairs, Wilson 95% interval; with zero errors the rule-of-three upper bound on false-AUTO is reported instead",
        "auto_recall": "labelled-correct pairs the contract writes at AUTO / labelled-correct pairs (EQUIVALENT only)",
        "propose_precision": "labelled-correct among PROPOSE pairs",
        "propose_or_better_recall": "labelled-correct pairs the contract proposes or writes / labelled-correct pairs, with the weighted negative sample adding the correct pairs the contract missed (NO_CANDIDATE)",
        "per_link_type": "every metric above is computed separately for EQUIVALENT, PART_OF and COMPOSED_OF on that link type's scored cells",
        "unit_weighted": "each of the above is also reported weighted by lifetime units, because a wrong high-volume pair costs more registrations than a wrong tail pair"},
    "false_auto_analysis": [
        "every false-AUTO is listed with its supporting codes, series state, name relation, brand relation and lineage roles",
        "classify the root cause: series coincidence of different models, granularity (finer or coarser model), lineage (rename / replacement), brand relation, label noise in the owner's verdict",
        "a root cause that the contract can express as a gate is a proposal for a rule change in a later round, never applied in the same pass as the measurement",
        "report false-AUTO by brand family and by fold: a single family accounting for the errors means a missing rule, not a miscalibrated threshold"],
    "pending_threshold_sensitivity": [
        "each pending calibration entry (pending_threshold_sensitivity.csv) is evaluated at every registered grid value on the labelled rows; selection per fold uses training folds only",
        "report the change in held-out AUTO precision, AUTO recall and false-AUTO count per value as evidence; a value with a TRAINING false-AUTO is not eligible",
        "an entry that moves no labelled row stays pending and is reported as not constrained by the labels"],
    "stop_rules": [
        "fewer labelled AUTO pairs than ER-T tolerance requires: report the bound that the labels do support and keep the threshold pending",
        "any CONFLICT from check_label_consistency / derive_truth: stop and return the conflicts to the owner",
        "any false-AUTO in a held-out fold: stop, analyse (false_auto_analysis), do not tune around it",
        "nothing is bound until the owner accepts a calibrated value in adoption.yaml; adoption.binding stays false"]}


# ----------------------------------------------------------------------------------------------------------------------------- the smallest first set, and the whole queue (ODP-3)
# One queue row per underlying record. A row is either an ACTION_REQUIRED (one owner decision, counted once) or a SUPPORTING_ROW (evidence or a companion field: it is settled by exactly one action,
# named in `resolved_by_action_id`, and does not ask for a second decision). The 65 of the first wave are the ACTION_REQUIRED rows of wave 1.
INIT_COLUMNS = ["item_id", "wave", "kind", "question", "resolves", "units_at_stake", "why_first", "where_the_answer_goes", "owner_answer", "owner_notes"]
QUEUE_COLUMNS = ["queue_position", "wave", "queue_role", "item_kind", "item_id", "session_id", "required_for_session_completion", "atomic_verdict_fields", "answer_destination", "related_sessions_informational", "detail_file",
                 "group_tag", "units_at_stake", "why_in_this_wave"]
SESSION_COLUMNS = ["session_id", "wave", "kind", "title", "units_at_stake", "own_cells", "child_decision_ids", "child_cells", "evidence_row_ids", "atomic_verdicts_own", "atomic_verdicts_children", "atomic_verdicts_total",
                   "conditional_fields", "completion_rule"]
FIRST_WAVE = {"p1_min_units": 100, "p2_min_units": 1000}
SESSION, CHILD, EVIDENCE = "REVIEW_SESSION", "CHILD_DECISION", "EVIDENCE_ROW"


def build_initial(inp: Inputs, alias_rows, brand_rows, create_rows, view, meta) -> tuple[list[dict], dict]:
    """The four rule / filing questions (the only rows of initial_owner_decisions.csv: they are decisions that have no row of their own elsewhere), and the plan of the other first-wave actions."""
    brand_ids = lambda kind: [r["decision_id"] for r in brand_rows if r["disagreement_kind"] == kind]
    units = lambda ids: sum(r["units_lifetime"] for r in brand_rows if r["decision_id"] in ids)
    rel = brand_ids("PRODUCER_ADMITS_RELATED_BRAND__CATALOG_LABEL_LOOKUP_FINDS_NONE")
    jet = brand_ids("CATALOG_ALIAS_RESOLVES__PRODUCER_HAS_NO_BRAND_RELATION")
    mx = brand_ids("FILING_OF_A_SUB_BRAND_THE_CATALOG_HOLDS_UNDER_ANOTHER_BRAND")
    items = [
        ("INIT-01", "CONTRACT", "When the producer's brand relation to a TDR brand is RELATED (capped at PROPOSE), must a consumer take its candidate set from the producer instead of resolving the brand itself from catalog labels?",
         rel, units(rel), "one rule closes seven of the eight unresolved parity cases; settles no group or pair verdict", "adoption.yaml (candidates_pool_rules) / a PR #201 consumer note"),
        ("INIT-02", "CONTRACT", "May a catalog brand `aliases` entry ever be a brand relation, and if so as which typed class (SAME / RELABEL / RELATED) and with which provenance? Decide the one label in the pack (JETOUR under Chery).",
         jet, units(jet), "closes the one case where the consumer resolves a brand the producer does not relate; settles no group or pair verdict", "policy.yaml aliases.brand + alias_provenance"),
        ("INIT-03", "CATALOG", "Where are Maxus-badged models filed: under the registration brand MG (as mg.mg_maxus_7 / mg.mg_maxus_9 are today) or under a Maxus brand?",
         mx, units(mx), "the filing question; the same sitting separately collects the V80 CREATE verdict and the pair verdicts of the three Maxus groups (child cells in review_sessions.csv), which the filing answer does not settle", "catalog brand records / PR #201 identity review"),
        ("INIT-04", "CONTRACT", "What does a TDR catalog model `aliases` entry assert: the same model, a registration-attribution label that may cover a broader family, or a lookup convenience? "
         "(The nine alias rows show all three readings occur.)", [r["decision_id"] for r in alias_rows], sum(int0(r["provider_units_lifetime"]) for r in alias_rows),
         "a rule for reading catalog aliases; it fills no alias class, group verdict or pair verdict (each alias session collects its own)", "policy / VEHICLE_DB_V3 note"),
    ]
    out = [{"item_id": i, "wave": 1, "kind": k, "question": q, "resolves": ids, "units_at_stake": u, "why_first": w, "where_the_answer_goes": g, "owner_answer": "", "owner_notes": ""} for i, k, q, ids, u, w, g in items]
    alias_groups = {r["provider_group_id"] for r in alias_rows}
    brand_groups = {r["provider_group_id"] for r in brand_rows}
    first_alias = [r["decision_id"] for r in alias_rows if r["evidence_sufficiency"] == "STRONG_PACK_EVIDENCE"]
    first_create = [c["decision_id"] for c in create_rows if c["provider_group_id"] not in alias_groups | brand_groups and
                    ((c["risk_tier"].startswith("P1") and c["units_lifetime"] >= FIRST_WAVE["p1_min_units"]) or (c["risk_tier"].startswith("P2") and c["units_lifetime"] >= FIRST_WAVE["p2_min_units"]))]
    starter = sorted({r["review_rank"] for r in view if r["starter_batch"]}, key=int)
    return out, {"alias": first_alias, "create": first_create, "starter_ranks": starter}


def brand_resolver(r: dict) -> str:
    return {"PRODUCER_ADMITS_RELATED_BRAND__CATALOG_LABEL_LOOKUP_FINDS_NONE": "INIT-01", "CATALOG_ALIAS_RESOLVES__PRODUCER_HAS_NO_BRAND_RELATION": "INIT-02"}.get(r["disagreement_kind"], "INIT-03")


def cell_addr(file: str, key: str, field: str) -> str:
    return f"{file}#{key}@{field}"


CONDITIONAL_FIELDS = ("create_candidates.csv owner_verdict: EXISTING_IDENTITY / VARIANT_TRIM_CODE also need owner_canonical_model_id; VALID_MISSING_CANONICAL also needs owner_discovery_class; "
                      "r6_owner_review.csv owner_verdict: CORRECT_* also need owner_link_type (matching the verdict) and owner_canonical_model_id")
COMPLETION_RULE = ("complete only when EVERY own cell and EVERY child cell is explicitly filled with an allowed value (and its conditional fields), and no answer contradicts another; "
                   "no cell is inferred from another answer (validate_session)")


def build_queue(inp: Inputs, init: list[dict], plan: dict, alias_rows, brand_rows, create_rows, view, neg_rows) -> tuple[list[dict], list[dict]]:
    """Returns (queue rows, review sessions). A REVIEW_SESSION is one sitting with the owner; it owns explicit cells (owner-field addresses) and may bundle CHILD_DECISIONs, each an independent verdict with its own
    cell that the session's own answer does NOT settle. An EVIDENCE_ROW asks for nothing. Nothing is inferred: a child is only ever answered by filling its own cell."""
    rows: list[dict] = []
    sessions: dict[str, dict] = {}
    first_alias, first_create, starter = set(plan["alias"]), set(plan["create"]), set(plan["starter_ranks"])
    alias_of = {r["provider_group_id"]: r for r in alias_rows}
    brand_of = {r["provider_group_id"]: r for r in brand_rows}
    create_of = {r["provider_group_id"]: r for r in create_rows}
    r6_of = collections.defaultdict(list)
    for r in view:
        r6_of[r["model_group_id"]].append(r)

    def session(sid, wave, kind, title, units, own_cells, dest, file, tag="", why="", related=""):
        sessions[sid] = {"session_id": sid, "wave": wave, "kind": kind, "title": title, "units_at_stake": units, "own_cells": list(own_cells), "child_decision_ids": [], "child_cells": [], "evidence_row_ids": []}
        rows.append({"queue_position": 0, "wave": wave, "queue_role": SESSION, "item_kind": kind, "item_id": sid, "session_id": sid, "required_for_session_completion": "yes", "atomic_verdict_fields": len(own_cells),
                     "answer_destination": dest, "related_sessions_informational": related, "detail_file": file, "group_tag": tag, "units_at_stake": units, "why_in_this_wave": why})

    def child(sid, kind, item, cell, dest, file, units, tag="", why=""):
        s_ = sessions[sid]
        s_["child_decision_ids"].append(item)
        s_["child_cells"].append(cell)
        rows.append({"queue_position": 0, "wave": s_["wave"], "queue_role": CHILD, "item_kind": kind, "item_id": item, "session_id": sid, "required_for_session_completion": "yes", "atomic_verdict_fields": 1,
                     "answer_destination": dest, "related_sessions_informational": "", "detail_file": file, "group_tag": tag, "units_at_stake": units,
                     "why_in_this_wave": why or f"independent verdict bundled into {sid}; {sid}'s own answer does not settle it"})

    def create_child(sid, c):
        child(sid, "CREATE_ROW", c["decision_id"], cell_addr("create_candidates.csv", c["decision_id"], "owner_verdict"),
              "create_candidates.csv owner_verdict (+ owner_canonical_model_id / owner_discovery_class as the verdict requires)", "create_candidates.csv", c["units_lifetime"])

    def r6_child(sid, r):
        child(sid, "R6_ROW", f"R6-{r['review_rank']}", cell_addr("r6_owner_review.csv", f"review_rank={r['review_rank']}", "owner_verdict"),
              f"r6_owner_review.csv owner_verdict (+ owner_link_type, owner_canonical_model_id as the verdict requires) at review_rank={r['review_rank']}", "r6_priority_view.csv", r["ice_lifetime_units"], ",".join(r["starter_batch"]))

    bundled_create, bundled_r6 = set(), set()
    for i in init:
        session(i["item_id"], 1, i["kind"], i["question"], i["units_at_stake"], [cell_addr("initial_owner_decisions.csv", i["item_id"], "owner_answer")],
                "initial_owner_decisions.csv owner_answer", "initial_owner_decisions.csv", why=i["why_first"])
    for r in alias_rows:
        d, g = r["decision_id"], r["provider_group_id"]
        w = 1 if d in first_alias else 2
        c = create_of.get(g)
        session(d, w, "ALIAS_ROW", f"Alias class of '{r['provider_name']}' against {r['existing_identity_id']}, then its independent group verdict and pair verdicts", int0(r["provider_units_lifetime"]),
                [cell_addr("catalog_alias_collisions.csv", d, "owner_alias_class")], "catalog_alias_collisions.csv owner_alias_class", "catalog_alias_collisions.csv",
                why="decisive series evidence and real volume" if w == 1 else "thin volume")
        if c:
            create_child(d, c)
            bundled_create.add(c["decision_id"])
        for v in r6_of.get(g, []):
            r6_child(d, v)
            bundled_r6.add(v["review_rank"])
    for r in brand_rows:
        sid = brand_resolver(r)
        g = r["provider_group_id"]
        rows.append({"queue_position": 0, "wave": 1, "queue_role": EVIDENCE, "item_kind": "BRAND_CASE", "item_id": r["decision_id"], "session_id": sid, "required_for_session_completion": "no", "atomic_verdict_fields": 0,
                     "answer_destination": f"none required (optional owner_case_override in brand_resolution_cases.csv if {sid}'s answer should not apply to this case)", "related_sessions_informational": "",
                     "detail_file": "brand_resolution_cases.csv", "group_tag": "", "units_at_stake": r["units_lifetime"], "why_in_this_wave": f"evidence for {sid}"})
        sessions[sid]["evidence_row_ids"].append(r["decision_id"])
        c = create_of.get(g)
        if c and c["decision_id"] not in bundled_create:
            create_child(sid, c)
            bundled_create.add(c["decision_id"])
        for v in r6_of.get(g, []):
            if v["review_rank"] not in bundled_r6:
                r6_child(sid, v)
                bundled_r6.add(v["review_rank"])
    for c in create_rows:
        if c["decision_id"] in bundled_create:
            continue
        spot, tier3 = c["p3_spot_check_sample"] == "yes", c["risk_tier"].startswith("P3")
        w1 = c["decision_id"] in first_create
        w = 1 if w1 else (2 if (spot or not tier3) else 3)
        rel = ",".join(f"R6-{v['review_rank']}" for v in r6_of.get(c["provider_group_id"], []))
        session(c["decision_id"], w, "CREATE_ROW", f"Should TDR have a canonical model for {c['provider_brand']} {c['provider_name']} ({c['proposed_canonical_id']})?", c["units_lifetime"],
                [cell_addr("create_candidates.csv", c["decision_id"], "owner_verdict")], "create_candidates.csv owner_verdict (+ owner_canonical_model_id, owner_discovery_class as the verdict requires)", "create_candidates.csv",
                why="first wave" if w1 else (("P3 bulk, in the spot-check sample" if spot else "P3 bulk: confirm after the spot check, escalate if it finds one wrong") if tier3 else "P1/P2: needs a row review"),
                related=rel)
    for v in view:
        if v["review_rank"] in bundled_r6:
            continue
        rid = f"R6-{v['review_rank']}"
        w = 1 if v["review_rank"] in starter else (2 if v["in_first_176"] == "yes" else 3)
        c = create_of.get(v["model_group_id"])
        session(rid, w, "R6_ROW", f"Pair verdict at review_rank {v['review_rank']}: {v['model_group_id']} -> {v['candidate_canonical_model_id'] or '(no candidate)'}", v["ice_lifetime_units"],
                [cell_addr("r6_owner_review.csv", f"review_rank={v['review_rank']}", "owner_verdict")],
                f"r6_owner_review.csv owner_verdict (+ owner_link_type, owner_canonical_model_id as the verdict requires) at review_rank={v['review_rank']}", "r6_priority_view.csv", ",".join(v["starter_batch"]),
                "starter batch" if w == 1 else ("first 176 rows, not in the starter batch" if w == 2 else "tiers 3-7"), related=c["decision_id"] if c else "")
    for n in neg_rows:
        session(n["sample_id"], 3, "NEGATIVE_SAMPLE", n["question"], n["units_lifetime"], [cell_addr("negative_sample.csv", n["sample_id"], "owner_has_tdr_counterpart")],
                "negative_sample.csv owner_has_tdr_counterpart (+ owner_canonical_model_id, owner_link_type)", "negative_sample.csv", why="recall denominator: needed after labels exist")
    # keep sessions first inside a wave, each session followed by its own children and evidence
    by_wave = collections.defaultdict(list)
    for r in rows:
        by_wave[r["wave"]].append(r)
    out = []
    for w in sorted(by_wave):
        sess = [r for r in by_wave[w] if r["queue_role"] == SESSION]
        for sr in sess:
            out.append(sr)
        for sr in sess:
            out += [r for r in by_wave[w] if r["queue_role"] != SESSION and r["session_id"] == sr["session_id"]]
    for i, r in enumerate(out, start=1):
        r["queue_position"] = i
    srows = []
    for sid, s_ in sorted(sessions.items(), key=lambda kv: (kv[1]["wave"], [x["queue_position"] for x in out if x["item_id"] == kv[0] and x["queue_role"] == SESSION][0])):
        s_["atomic_verdicts_own"], s_["atomic_verdicts_children"] = len(s_["own_cells"]), len(s_["child_cells"])
        s_["atomic_verdicts_total"] = s_["atomic_verdicts_own"] + s_["atomic_verdicts_children"]
        s_["conditional_fields"], s_["completion_rule"] = CONDITIONAL_FIELDS, COMPLETION_RULE
        srows.append(s_)
    return out, srows


NEG_ANSWERS = ("YES", "NO", "UNSURE")
CROSS_ANSWER_CONFLICTS = ("PAIR_AND_GROUP_VERDICT_CONTRADICT", "GROUP_TARGET_DIFFERS_FROM_CORRECT_PAIR", "GROUP_TARGET_IS_THE_WRONG_TARGET", "TWO_EQUIVALENT_TARGETS", "LINK_TYPE_CONTRADICTS_VERDICT",
                          "WRONG_TARGET_NAMES_ITSELF")


def cell_meta(alias_rows, create_rows, view) -> dict:
    """What each cell address is about: used by the validator to group answers for the contradiction check. Not an owner field."""
    meta = {}
    for r in alias_rows:
        meta[cell_addr("catalog_alias_collisions.csv", r["decision_id"], "owner_alias_class")] = {"kind": "ALIAS", "group": r["provider_group_id"], "target": r["existing_identity_id"]}
    for c in create_rows:
        meta[cell_addr("create_candidates.csv", c["decision_id"], "owner_verdict")] = {"kind": "CREATE", "group": c["provider_group_id"], "key": c["decision_id"]}
    for v in view:
        meta[cell_addr("r6_owner_review.csv", f"review_rank={v['review_rank']}", "owner_verdict")] = {"kind": "R6", "group": v["model_group_id"], "candidate": v["candidate_canonical_model_id"], "key": f"review_rank={v['review_rank']}"}
    return meta


def validate_session(session: dict, answers: dict, meta: dict, model_ids: set | None = None) -> list[dict]:
    """Is this review session COMPLETE? `answers` maps a cell address (file#key@field) to what the owner explicitly wrote; nothing is inferred from any other answer. Returns problems; [] means complete.
    Checks: every own cell and every child cell is filled (UNANSWERED_MANDATORY_CELL); each value is allowed (and its conditional fields are filled); the answers do not contradict each other."""
    problems: list[dict] = []

    def add(kind, cell, detail):
        problems.append({"kind": kind, "cell": cell, "detail": detail})

    def val(cell):
        return str(answers.get(cell, "") or "").strip()

    def sibling(cell, field):
        file, rest = cell.split("#", 1)
        return cell_addr(file, rest.rsplit("@", 1)[0], field)

    pair_labels, create_labels, alias_answers = collections.defaultdict(list), {}, []
    for cell in session["own_cells"] + session["child_cells"]:
        file, rest = cell.split("#", 1)
        field = rest.rsplit("@", 1)[1]
        v = val(cell)
        if not v:
            add("UNANSWERED_MANDATORY_CELL", cell, f"{'child' if cell in session['child_cells'] else 'own'} cell of {session['session_id']} is empty")
            continue
        m = meta.get(cell, {})
        if file == "initial_owner_decisions.csv":
            continue
        if file == "catalog_alias_collisions.csv":
            if v not in ALIAS_CLASSES:
                add("VALUE_NOT_ALLOWED", cell, v)
            else:
                alias_answers.append((v, m))
        elif file == "create_candidates.csv":
            if v not in CREATE_VERDICTS:
                add("VALUE_NOT_ALLOWED", cell, v)
                continue
            canon = val(sibling(cell, "owner_canonical_model_id"))
            if v in ("EXISTING_IDENTITY", "VARIANT_TRIM_CODE") and not canon:
                add("CONDITIONAL_FIELD_MISSING", sibling(cell, "owner_canonical_model_id"), f"{v} needs the model")
            if v == "VALID_MISSING_CANONICAL" and val(sibling(cell, "owner_discovery_class")) not in DISCOVERY_CLASSES:
                add("CONDITIONAL_FIELD_MISSING", sibling(cell, "owner_discovery_class"), "VALID_MISSING_CANONICAL needs a discovery class")
            if canon and model_ids is not None and canon not in model_ids:
                add("UNKNOWN_TDR_MODEL", sibling(cell, "owner_canonical_model_id"), canon)
            create_labels[m.get("group")] = {"verdict": v, "canonical": canon}
        elif file == "r6_owner_review.csv":
            if v not in R6_VERDICTS:
                add("VALUE_NOT_ALLOWED", cell, v)
                continue
            link, canon = val(sibling(cell, "owner_link_type")), val(sibling(cell, "owner_canonical_model_id"))
            if v in PAIR_LINK and (link != PAIR_LINK[v] or not canon):
                add("CONDITIONAL_FIELD_MISSING", sibling(cell, "owner_link_type"), f"{v} needs owner_link_type={PAIR_LINK[v]} and owner_canonical_model_id")
            if canon and model_ids is not None and not all(x in model_ids for x in canon.split("+")):
                add("UNKNOWN_TDR_MODEL", sibling(cell, "owner_canonical_model_id"), canon)
            pair_labels[m.get("group")].append({"candidate": m.get("candidate"), "verdict": v, "link_type": link, "canonical": canon})
        elif file == "negative_sample.csv":
            if v not in NEG_ANSWERS:
                add("VALUE_NOT_ALLOWED", cell, v)
            elif v == "YES" and not val(sibling(cell, "owner_canonical_model_id")):
                add("CONDITIONAL_FIELD_MISSING", sibling(cell, "owner_canonical_model_id"), "YES needs the model")
    # contradictions between the answers actually given (the checks never fill a missing answer)
    for g in sorted(set(pair_labels) | set(create_labels), key=str):
        for r in check_label_consistency({g: pair_labels.get(g, [])}, {g: create_labels[g]} if g in create_labels else {}, model_ids):
            if r["severity"] == "CONFLICT" and r["kind"] in CROSS_ANSWER_CONFLICTS:   # value / missing-field / unknown-model problems are reported above, once
                add("CONTRADICTORY_ANSWERS", str(g), f"{r['kind']}: {r['detail']}")
    for cls, m in alias_answers:
        cl = create_labels.get(m.get("group"))
        if not cl:
            continue
        if cls == "IDENTITY_EQUIVALENT" and cl["verdict"] == "VALID_MISSING_CANONICAL":
            add("CONTRADICTORY_ANSWERS", m["group"], "alias class IDENTITY_EQUIVALENT but the group verdict says no canonical identity exists")
        if cls == "IDENTITY_EQUIVALENT" and cl["verdict"] == "EXISTING_IDENTITY" and cl["canonical"] and cl["canonical"] != m["target"]:
            add("CONTRADICTORY_ANSWERS", m["group"], f"alias class IDENTITY_EQUIVALENT with {m['target']} but the group verdict names {cl['canonical']}")
        if cls == "MISLEADING_ALIAS" and cl["verdict"] == "EXISTING_IDENTITY" and cl["canonical"] == m["target"]:
            add("CONTRADICTORY_ANSWERS", m["group"], f"alias class MISLEADING_ALIAS but the group verdict names the alias target {m['target']}")
    return problems


def session_is_complete(session: dict, answers: dict, meta: dict, model_ids: set | None = None) -> bool:
    return not validate_session(session, answers, meta, model_ids)


def wave1_stats(queue: list[dict], sessions: list[dict]) -> dict:
    w1 = [q for q in queue if q["wave"] == 1]
    ss = [s_ for s_ in sessions if s_["wave"] == 1]
    kinds = collections.Counter(s_["kind"] for s_ in ss)
    ch = [q for q in w1 if q["queue_role"] == CHILD]
    r6_rows = [q for q in w1 if q["item_kind"] == "R6_ROW"]
    return {"queue_rows_wave1": len(w1), "review_sessions": len(ss), "child_decisions": len(ch), "evidence_rows": sum(1 for q in w1 if q["queue_role"] == EVIDENCE),
            "atomic_verdicts_own": sum(s_["atomic_verdicts_own"] for s_ in ss), "atomic_verdicts_children": sum(s_["atomic_verdicts_children"] for s_ in ss), "atomic_verdicts_total": sum(s_["atomic_verdicts_total"] for s_ in ss),
            "contract_questions": kinds["CONTRACT"] + kinds["CATALOG"], "alias_sessions": kinds["ALIAS_ROW"], "create_sessions": kinds["CREATE_ROW"], "r6_sessions": kinds["R6_ROW"],
            "children_by_kind": dict(collections.Counter(q["item_kind"] for q in ch)), "r6_rows_wave1": len(r6_rows), "r6_standalone_sessions_wave1": kinds["R6_ROW"],
            "evidence_by_kind": dict(collections.Counter(q["item_kind"] for q in w1 if q["queue_role"] == EVIDENCE)),
            # kept for the report text and older callers
            "owner_actions": len(ss), "supporting_rows_wave1": len(w1) - len(ss)}


# ----------------------------------------------------------------------------------------------------------------------------- assembling the pack
FILES = {
    "catalog_alias_collisions.csv": (ALIAS_COLUMNS, "alias"), "brand_resolution_cases.csv": (BRAND_COLUMNS, "brand"), "create_candidates.csv": (CREATE_COLUMNS, "create"),
    "r6_create_reconciliation.csv": (RECON_COLUMNS, "recon"), "verdict_crosswalk.csv": (CROSSWALK_COLUMNS, "crosswalk"), "r6_priority_view.csv": (R6_VIEW_COLUMNS, "view"),
    "brand_folds.csv": (FOLD_COLUMNS, "folds"), "negative_sample.csv": (NEG_COLUMNS, "neg"), "pending_threshold_sensitivity.csv": (THRESH_COLUMNS, "thresh"),
    "calibration_entry_requirements.csv": (ENTRY_COLUMNS, "entry"), "initial_owner_decisions.csv": (INIT_COLUMNS, "init"), "decision_queue.csv": (QUEUE_COLUMNS, "queue"), "review_sessions.csv": (SESSION_COLUMNS, "sessions")}
OWNER_FIELDS = {"catalog_alias_collisions.csv": ["owner_alias_class", "owner_notes"],
                "brand_resolution_cases.csv": ["owner_case_override", "owner_notes"], "create_candidates.csv": ["owner_verdict", "owner_canonical_model_id", "owner_discovery_class", "owner_notes"],
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
    init, plan = build_initial(inp, alias, brand, create, view, meta)
    queue, sessions = build_queue(inp, init, plan, alias, brand, create, view, neg)
    istats = wave1_stats(queue, sessions)
    for rows_ in (alias, brand, create, view, neg):
        for r in rows_:
            r["evidence_refs"] = REF_SEP.join(r["evidence_refs"])
    return {"alias": alias, "brand": brand, "create": create, "recon": build_reconciliation(inp, create), "crosswalk": verdict_crosswalk(), "view": view, "folds": build_folds(inp, view, meta, create, neg),
            "neg": neg, "thresh": build_threshold_table(inp, starter_groups), "entry": build_entry_requirements(inp, view, meta, neg_summary), "init": init, "queue": queue, "sessions": sessions, "cell_meta": cell_meta(alias, create, view),
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
    wq = [q for q in T["queue"] if q["wave"] == 1]
    sess1 = [x for x in T["sessions"] if x["wave"] == 1]
    own_by_kind = collections.Counter()
    child_by_kind = collections.Counter()
    for x in sess1:
        own_by_kind[x["kind"]] += x["atomic_verdicts_own"]
    for q in wq:
        if q["queue_role"] == CHILD:
            child_by_kind[q["item_kind"]] += 1
    kind_rows = [["rule / filing questions", ist["contract_questions"], own_by_kind["CONTRACT"] + own_by_kind["CATALOG"], 0],
                 ["alias sessions", ist["alias_sessions"], own_by_kind["ALIAS_ROW"], 0],
                 ["CREATE sessions", ist["create_sessions"], own_by_kind["CREATE_ROW"], 0],
                 ["R6 pair-verdict sessions", ist["r6_sessions"], own_by_kind["R6_ROW"], 0],
                 ["child CREATE verdicts (inside INIT-03 / alias sessions)", "-", 0, child_by_kind["CREATE_ROW"]],
                 ["child R6 pair verdicts (inside INIT-03 / alias sessions)", "-", 0, child_by_kind["R6_ROW"]]]
    w(f"Nothing here requires all {n_r6} R6 rows to be labelled. The first wave is **{ist['review_sessions']} review sessions** (one sitting each) that together require **{ist['atomic_verdicts_total']} independent owner verdict cells**: "
      f"{ist['atomic_verdicts_own']} cells owned by the sessions themselves plus {ist['atomic_verdicts_children']} child verdicts that a session bundles. A child verdict is **never** settled by its session's own answer: "
      "an alias class, a brand-filing answer or a rule decision does not fill a group verdict or a pair verdict, and a session is complete only when every own cell and every child cell is explicitly filled "
      "(`review_sessions.csv`: `own_cells`, `child_cells`; `validate_session` refuses an incomplete or contradictory session). "
      f"`decision_queue.csv` lists {ist['queue_rows_wave1']} first-wave rows = {ist['review_sessions']} `REVIEW_SESSION` + {ist['child_decisions']} `CHILD_DECISION` + {ist['evidence_rows']} `EVIDENCE_ROW` (the brand cases: evidence for INIT-01..03, nothing required). "
      f"Of the {ist['r6_rows_wave1']} R6 rows in the first wave, {ist['r6_standalone_sessions_wave1']} are stand-alone sessions and {ist['children_by_kind'].get('R6_ROW', 0)} are children (one of them a starter row, the others group-linked rows that the same sittings must answer); "
      f"all 48 starter rows are in the first wave. All {n_create} CREATE candidates and all {n_r6} R6 rows stay in their files and in the queue. "
      f"The first wave covers {round(100 * meta['s1_units'] / meta['auto_pair_units'], 1)}% of the lifetime units of all {meta['auto_pairs']} AUTO pairs, every known suspicious-case family, every PART_OF / COMPOSED_OF and several-candidate row, "
      f"and {round(100 * wave1_units / total_units, 1)}% of the lifetime units of the {n_create} CREATE candidates ({wave1_rows} rows). It is built to find a systematic failure early, not to certify a rate (see §7).\n")
    w(md_table(["first-wave component", "review sessions", "atomic cells owned by sessions", "atomic child cells"], kind_rows + [["**total**", ist["review_sessions"], ist["atomic_verdicts_own"], ist["atomic_verdicts_children"]]]))
    w(f"\nReconciliation: {ist['review_sessions']} sessions = {ist['atomic_verdicts_own']} own cells; {ist['atomic_verdicts_own']} + {ist['atomic_verdicts_children']} child cells = **{ist['atomic_verdicts_total']} atomic verdict cells**. "
      "Each session's own and child cell addresses (`file#row@field`) are listed in `review_sessions.csv`; the conditional fields a verdict needs (model id, discovery class, link type) are in `conditional_fields`.\n")
    w(md_table(["session", "own cell", "bundled child verdicts (each answered on its own)"], [[x["session_id"], x["own_cells"][0].split("#", 1)[1], ", ".join(x["child_decision_ids"])] for x in sess1 if x["child_decision_ids"]]))
    w("\nThe four rule / filing questions:\n")
    w(md_table(["item", "kind", "question", "related rows (informational; none is settled by this answer)", "units"], [[i["item_id"], i["kind"], i["question"], span(i["resolves"]), i["units_at_stake"]] for i in init]))
    w("\nThe full order, with later waves, is `decision_queue.csv` (`queue_role`, `session_id`, `required_for_session_completion`, `atomic_verdict_fields`, `answer_destination`).\n")
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
      f"S3 {meta['s3']} known-family representatives; S4 {meta['s4']} structural rows; {len({r['review_rank'] for r in view if r['starter_batch']})} distinct rows. Rows are assigned to {TRIAGE['folds']} brand-separated folds over {meta['families']} brand families (rows per fold {meta['fold_weights']}).\n")
    w("## 6. Section D: all 82 CREATE candidates, grouped by risk (`create_candidates.csv`)\n")
    w(md_table(["tier", "rows", "units", "evidence", "suggested triage (non-auth.)"],
               [[t, tier[t], sum(r["units_lifetime"] for r in create if r["risk_tier"] == t), "needs a row review" if not t.startswith("P3") else f"spot-check {SPOT_CHECK_N}, then confirm or escalate",
                 ", ".join(f"{k} {v}" for k, v in c(r["machine_triage_NON_AUTHORITATIVE"] for r in create if r["risk_tier"] == t).most_common())] for t in sorted(tier)]))
    w(f"\nP1 = contradicting evidence (alias, brand collision, coinciding series, strong legacy proposal). P2 = high volume, current market or a code-like name with no contradicting evidence. P3 = historical bulk. "
      f"Age and volume never make a candidate false (PR #201's rule); they only order the work. The spot-check sample is the first {SPOT_CHECK_N} P3 rows by a fixed hash.\n")
    w("## 7. Calibration after labels exist (`calibration_procedure.json`)\n")
    w("- **Labels → ground truth, per link type**: a pair label speaks for the link type it names (CORRECT_EQUIVALENT / PART_OF / COMPOSED_OF positive; WRONG_TARGET / NO_TDR_TARGET negative for the link type the row proposed). A group label speaks only about EQUIVALENT identity: "
      "VALID_MISSING_CANONICAL is EQUIVALENT-negative and says nothing about PART_OF / COMPOSED_OF (a group with no model of its own can still be part of existing ones: a REVIEW prompt, not a negative); VARIANT_TRIM_CODE infers no pair at all until the owner gives an explicit link label. "
      "Each link type is scored on its own POSITIVE / NEGATIVE cells; UNKNOWN, EXCLUDED and CONFLICT cells are counted, not scored (`derive_truth`, `metric_rows`). `check_label_consistency()` runs first.")
    w(f"- **Brand-separated evaluation, selection on training folds only**: {TRIAGE['folds']} folds of brand families (`brand_folds.csv`). The candidate grid, tie-break and selection rule are registered before any label is read. Pass 1 selects one value per fold from the other four folds and freezes it "
      "(`select_threshold` is handed no held-out row and no tolerance); pass 2 evaluates each frozen value once on its own fold. Pooled held-out precision, recall and the false-AUTO bound are **acceptance / failure evidence only** (`acceptance_gate`): a failure is reported as 'not calibrated' and any further attempt is a separately versioned experiment, never a retune on the same held-out outcomes.")
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
                "series_evidence_sha256": sha256_file(SERIES_JSON), "sensitivity_results_sha256": sha256_file(A.CALIBRATION_DIR / "sensitivity_results.json"), "pr201_inputs": json.loads((IN201 / "PROVENANCE.json").read_text(encoding="utf-8"))["files"],
                "counts": {"alias_rows": len(T["alias"]), "brand_cases": len(T["brand"]), "create_rows": len(T["create"]), "r6_view_rows": len(T["view"]), "starter_rows": len({r["review_rank"] for r in T["view"] if r["starter_batch"]}),
                           "negative_sample": len(T["neg"]), "first_wave_review_sessions": T["istats"]["review_sessions"], "first_wave_child_decisions": T["istats"]["child_decisions"], "first_wave_atomic_verdicts": T["istats"]["atomic_verdicts_total"], "queue": len(T["queue"]), "sessions": len(T["sessions"])},
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
