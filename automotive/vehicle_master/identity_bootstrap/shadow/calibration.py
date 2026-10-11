"""The owner-adjudication artifact (PROVISIONAL candidate set) and the informational activity classes.

Everything here is measurement. Analyst notes are carried through as a NOTE column and are never used to decide anything; `owner_label` is left blank for the owner.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

HERE = Path(__file__).parent
R6_FILE = HERE / "universe" / "r6_crosswalk_for_create_candidates.json"
OWNER_LABELS = ["TRUE_NEW_IDENTITY", "EXISTING_IDENTITY", "VARIANT_TRIM_CODE", "AMBIGUOUS"]
ACTIVITY_DORMANT_LAST12 = 10
ACTIVITY_RECENT_FIRST_SEEN = "2567-10"     # Buddhist era, as in the package: first seen within the last 24 months


# ---------------------------------------------------------------------------------------------------------------- activity classes
def activity_class(g: str, pkg: dict) -> str:
    if pkg["last12"].get(g, 0) <= ACTIVITY_DORMANT_LAST12:
        return "DORMANT_LEGACY"
    if pkg["first_seen"][g] >= ACTIVITY_RECENT_FIRST_SEEN:
        return "RECENT_DISCOVERY"
    return "ACTIVE_ESTABLISHED"


# ---------------------------------------------------------------------------------------------------------------- the owner-adjudication artifact
def nearest_identities(export, gid: str, top: int = 3) -> list[str]:
    """The closest members of the subject's candidate pool by the EXPORT's own score and relation (nothing is recomputed). Evidence for a human, not a decision."""
    rows = sorted((export.ice_tdr[f"{gid}|{t}"] for t in export.pool(gid)), key=lambda r: (-(r["s"] if r["s"] is not None else -1.0), r["b"]))
    return [f"{r['b']} ({r['r']}; export score {r['s']}; tdr tokens {' '.join(r['tb'])})" for r in rows[:top] if r["s"] not in (None, 0.0)]


OWNER_VERDICTS = ["VALID_MISSING_CANONICAL", "EXISTING_IDENTITY", "VARIANT_TRIM_CODE", "AMBIGUOUS"]
OWNER_DISCOVERY_CLASSES = ["RECENT_NEW_MODEL", "ACTIVE_CATALOG_GAP", "HISTORICAL_BACKFILL"]
OWNER_FIELDS = ["owner_verdict", "owner_canonical_model_id", "owner_discovery_class", "owner_notes"]
#: Machine-only context. Never copied into an owner field, never read by a test as truth, never an input to any decision.
SUGGESTED_DISCOVERY = {"RECENT_DISCOVERY": "RECENT_NEW_MODEL", "ACTIVE_ESTABLISHED": "ACTIVE_CATALOG_GAP", "DORMANT_LEGACY": "HISTORICAL_BACKFILL"}


def adjudication_rows(A: dict, creates: list[str], notes: dict, r6: dict, redirects: list, baseline_ids: set[str], baseline_relations: dict, market: dict, m5: dict) -> list[dict]:
    """PROVISIONAL candidate rows for the owner. Every machine field is filled; every owner field is blank. Relations are read from the PR #200 export held by the run."""
    pkg = A["package"]
    export = A["export"]
    dims = {r["model_group_id"]: r for r in pkg["dims"]}
    subj = {s["entity_id"]: s for s in A["snapshot"]["subjects"]}
    events = A["snapshot"]["lineage"]["events"]
    dec = {d["subject"]["entity_id"]: d for d in A["decisions"]}
    lex_codes = {c for c, v in A["registry"]["codes"].items() if v.get("area") == "SHAPE"}
    rows = []
    for g in creates:
        d, s = dec[g], subj[g]
        rels = [f"{r['peer_kind']}:{r['peer_id']}={r['name_relation']}" for r in s["relations"] if r["name_relation"] not in ("CONTRADICTION", "UNAVAILABLE")]
        old = {(k, p): r for k, p, r in baseline_relations.get(g, [])}
        new = {(r["peer_kind"], r["peer_id"]): r["name_relation"] for r in s["relations"]}
        changes = [f"{k[1]}: {old.get(k, 'none')} -> {new.get(k, 'none')}" for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]
        ev = [f"{e['event_type']}:{e['old_id']}>{e['new_id']}" for e in events if g in (e["old_id"], e["new_id"])]
        red = [f"R6_REDIRECT:{o}>{n}({t})" for o, n, t in redirects if g in (o, n)]
        alias = [a["external_id"] for a in d["write_plan"]["event"]["aliases"] if a["relation"] == "RETIRED_PREDECESSOR"]
        r6rows = r6.get(g)
        notes_row = notes.get(g)
        cls = activity_class(g, pkg)
        fam = s["brand"].get("family") or []
        ir = export.subjects[g]["outcome"]
        pool = export.pool(g)
        pstat = m5["ir_parity_status"][g]
        disp = next(r for r in m5["routing"]["dispatch"] if r["external_id"] == g)
        rows.append({
            "provider": "ice", "external_id": g, "provider_model_name": dims[g]["model_name"], "provider_brand": dims[g]["brand"],
            "proposed_canonical_name": d["identity"]["canonical_name"], "proposed_canonical_id": d["identity"]["canonical_model_id"],
            "first_seen": pkg["first_seen"][g], "last_seen": pkg["last_seen"][g], "lifetime_units": int(float(dims[g]["reg_total_all"])), "last12_units": int(pkg["last12"].get(g, 0)),
            "identity_status": s["identity_status"], "lineage_state": "; ".join(ev + red) or "no id_changes event and no R6 redirect",
            "retired_aliases_in_plan": "|".join(alias),
            "nearest_existing_canonical_identities": " || ".join(nearest_identities(export, g)) or ("none (empty candidate pool: the brand is not an allowed TDR brand)" if not pool else "none above zero export score"),
            "candidate_pool_size": len(pool),
            "relation_evidence": "; ".join(rels) or "none (no non-contradictory relation to any pooled TDR model or other Ice group in the export)",
            "ir_dry_run_outcome": f"{ir['outcome']} / {ir['primary_code']}" + (f" -> {','.join(ir['target_ids'])}" if ir["target_ids"] else ""),
            "brand_relation": f"{s['brand'].get('relation')} brand_id={s['brand'].get('brand_id')}" + (" family=" + ",".join(f"{f['brand_id']}({f['relation']})" for f in fam) if fam else ""),
            "shape_flags": "|".join(c_["code"] + ":cleared_by_" + c_["cleared_by"] for c_ in d["evidence_basis"]["cleared_flags"]) or "none fired",
            "lexical_flags": "|".join(c for c in d["reason_codes"] if c in lex_codes) or "none fired",
            "evidence_tier": d["evidence_basis"]["tier"], "evidence_kinds": "|".join(d["evidence_basis"]["kinds"]),
            "bootstrap_decision": f"{d['outcome']} / {d['primary_reason']}", "bootstrap_reason_codes": "|".join(d["reason_codes"]),
            "legacy_r6_candidate_status": ("; ".join(f"{x[1]} {x[0]} ({x[2]}, score {x[3]})" for x in r6rows) if r6rows else ("none (no legacy R6 row for this group)" if r6 else "not available")),
            "changed_by_full_export_relations": "YES" if changes else "no", "full_export_relation_changes": "; ".join(changes),
            "in_previous_set_b132a86": "yes" if g in baseline_ids else "NO (added in the full-export rerun)",
            "ir_parity_status": pstat["status"], "ir_parity_reasons": "; ".join(pstat["reasons"]) or "all consumer-contract requirements met",
            "review_routing_flags": "|".join(m5["routing"]["reviews"][g]["flags"]) or "none",
            "review_routing_evidence": "; ".join(_ev(e) for e in m5["routing"]["reviews"][g]["evidence"]) or "none",
            "mandatory_owner_review": "YES" if m5["routing"]["reviews"][g]["mandatory_owner_review"] else "no",
            "dispatch_lane": disp["lane"],
            "current_discovery_activation_authorized": "NO (projection only; blocked by " + "|".join(disp["activation_blockers"]) + ")",
            "market_activity_state_actual": market["actual"][g]["state"], "market_activity_lane_actual": market["actual"][g]["lane"],
            "market_activity_state_what_if_NON_AUTHORITATIVE": market["what_if"][g]["state"],
            "activity_class_informational": cls,
            "machine_suggested_discovery_class_NON_AUTHORITATIVE": SUGGESTED_DISCOVERY[cls],
            "analyst_note_NON_AUTHORITATIVE": (f"{notes_row['kind']}: {notes_row['why']}" if notes_row else ""),
            **{f: "" for f in OWNER_FIELDS}})
    return rows


def _ev(e: dict) -> str:
    return e["kind"] + "(" + ", ".join(f"{k}={v}" for k, v in e.items() if k != "kind") + ")"


COLUMNS = ["provider", "external_id", "provider_model_name", "provider_brand", "proposed_canonical_name", "proposed_canonical_id", "first_seen", "last_seen", "lifetime_units", "last12_units",
           "identity_status", "lineage_state", "retired_aliases_in_plan", "nearest_existing_canonical_identities", "candidate_pool_size", "relation_evidence", "ir_dry_run_outcome", "brand_relation",
           "shape_flags", "lexical_flags", "evidence_tier", "evidence_kinds", "bootstrap_decision", "bootstrap_reason_codes", "legacy_r6_candidate_status",
           "changed_by_full_export_relations", "full_export_relation_changes", "in_previous_set_b132a86", "ir_parity_status", "ir_parity_reasons", "review_routing_flags",
           "review_routing_evidence", "mandatory_owner_review", "dispatch_lane", "current_discovery_activation_authorized", "market_activity_state_actual", "market_activity_lane_actual",
           "market_activity_state_what_if_NON_AUTHORITATIVE", "activity_class_informational", "machine_suggested_discovery_class_NON_AUTHORITATIVE", "analyst_note_NON_AUTHORITATIVE", *OWNER_FIELDS]
HEADER = ("# PROVISIONAL candidate set (not the final truth set; QA pending). Owner fields are blank and must be filled only by the owner: "
          "owner_verdict in " + " | ".join(OWNER_VERDICTS) + "; owner_discovery_class (only when VALID_MISSING_CANONICAL) in " + " | ".join(OWNER_DISCOVERY_CLASSES) + ". "
          "Columns ending _NON_AUTHORITATIVE and analyst notes are machine context, never owner truth, never copied into an owner field and never an input to a decision. "
          "Age, dormancy and volume do not make a candidate false: a discontinued model with no TDR identity is a valid HISTORICAL_BACKFILL.\n")


def write_adjudication(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(HEADER)
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in sorted(rows, key=lambda r: r["external_id"]):
            w.writerow(r)


def load_r6() -> dict:
    """Read-only copy of the live R6 crosswalk rows for the remaining CREATE candidates: group -> [[target, status, method, score], ...] (empty list = no row)."""
    if not R6_FILE.exists():
        return {}
    return json.loads(R6_FILE.read_text(encoding="utf-8"))["rows"]
