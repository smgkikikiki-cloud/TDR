"""Prepare frozen PR #235 inputs for the TypeScript structural writer. Read-only.
No credentials/network/production writer; generate evidence outside source artifacts.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

try:
    from ice_scoped_m7_acceptance import (ROOT, PACKAGE, M7_ZIP, EXPECTED_M7_SHA, read_csv,
                                         read_m7_facts, verify_frozen_decisions, sha256)
except ModuleNotFoundError:
    from tools.ice_scoped_m7_acceptance import (ROOT, PACKAGE, M7_ZIP, EXPECTED_M7_SHA, read_csv,
                                               read_m7_facts, verify_frozen_decisions, sha256)

SOURCE_HEAD = "b5a6bcff2870afb8d81d672dd284e7935e3cb4ac"
# Verified against git show at implementation; portable to shallow CI checkouts.
FROZEN_SOURCE_SHA256 = {'data/packages/ice_crosswalk_r6_offline_recovery_M7.0/owner_decision_ledger_244.csv': '9f251b6120d88e52c33215c5127fb6f87cd8c6cc334c39dc227bb540860ae1a8', 'data/packages/ice_crosswalk_r6_offline_recovery_M7.0/qa/filtered_identity_manifest/final_scope_dispositions.csv': '8355e3378e90106769d293ed503bfc1e97cc04421332f8feee315ab92a90e80c', 'data/packages/ice_crosswalk_r6_offline_recovery_M7.0/qa/filtered_identity_manifest/identity_manifest_qa.json': '1897709aa04fe54f69ba124141542824cd85d50aa4a385cb26e299dc90ae9460', 'data/packages/ice_crosswalk_r6_offline_recovery_M7.0/qa/filtered_identity_manifest/new_basic_identity_proposals.csv': '3a0e08efb3618c08b9beb569c7d4fe276f9ddc8bdeed1eb0352bffe350551cd9', 'data/packages/ice_crosswalk_r6_offline_recovery_M7.0/qa/vehicle_master_identity_snapshot_2026-10-13.json': 'cf991264ada90efb0ff69a754cdee11fb0d13cc98fbe9fc60879de4eb7a2eb62', 'data/packages/ice_crosswalk_r6_offline_recovery_M7.0/shadow_crosswalk_rows.csv': '9d46cad597dba3bbe83369bd9f95cfe6d10b3f6d19e0f46b69e70f10bfab5450', 'data/packages/ice_crosswalk_r6_offline_recovery_M7.0/source/owner_overlay_original.csv': 'e660cf9133cd0a99ffe8c87d1ba06dc0c72ef89b8a313a0a7285f54da1332430'}
CATALOG = PACKAGE / "qa/vehicle_master_identity_snapshot_2026-10-13.json"
MANIFEST = PACKAGE / "qa/filtered_identity_manifest"
TARGETS = ["honda.jazz", "ford.ranger_raptor_double_cab", "jaecoo.j6", "toyota.vios", "gwm.ora_5",
           "nissan.march", "nissan.note", "zeekr.7x", "toyota.sienta"]


def prepare(output: Path) -> dict:
    paths = [CATALOG, MANIFEST / "new_basic_identity_proposals.csv", MANIFEST / "final_scope_dispositions.csv",
             MANIFEST / "identity_manifest_qa.json", PACKAGE / "owner_decision_ledger_244.csv",
             PACKAGE / "shadow_crosswalk_rows.csv", PACKAGE / "source/owner_overlay_original.csv"]
    pinned = {}
    for path in paths:
        relative = str(path.relative_to(ROOT))
        expected = FROZEN_SOURCE_SHA256[relative]
        if sha256(path) != expected:
            raise ValueError(f"Frozen PR #235 source changed: {relative}")
        pinned[relative] = expected
    if sha256(M7_ZIP) != EXPECTED_M7_SHA:
        raise ValueError("Frozen M7.0 ZIP hash changed")
    facts = read_m7_facts(M7_ZIP)
    source_scope = Counter()
    for fact in facts:
        source_scope[(fact.model_group_id, fact.reg_type)] += fact.registrations
    scopes = read_csv(MANIFEST / "final_scope_dispositions.csv")
    if len(scopes) != 1407 or len({(r["model_group_id"], r["reg_type"]) for r in scopes}) != 1407:
        raise ValueError("Duplicate or missing final manifest scopes")
    actual = {(r["model_group_id"], r["reg_type"]): int(r["registrations"]) for r in scopes}
    if actual != source_scope or sum(actual.values()) != 4_141_987:
        raise ValueError("Final scope manifest differs from genuine M7.0 class scope/units")
    eligible = sum(int(r["registrations"]) for r in scopes if r["eligibility"] == "ELIGIBLE")
    if eligible != 4_123_704:
        raise ValueError("Fixed filtered denominator changed")
    ledger = read_csv(PACKAGE / "owner_decision_ledger_244.csv")
    frozen_check = verify_frozen_decisions(ledger, read_csv(PACKAGE / "shadow_crosswalk_rows.csv"))
    if len(ledger) != 244 or frozen_check["mismatches"]:
        raise ValueError("Frozen owner ledger does not reconcile")
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    for name in ["vehicle_brands", "vehicle_models"]:
        relation = catalog["relations"][name]
        canonical = json.dumps(relation["rows"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        if hashlib.sha256(canonical).hexdigest() != relation["canonical_rows_sha256"]:
            raise ValueError(f"Catalog snapshot relation hash changed: {name}")
    proposals = {r["canonical_id"]: r for r in read_csv(MANIFEST / "new_basic_identity_proposals.csv")}
    candidates = []
    for canonical_id in TARGETS:
        proposal = proposals[canonical_id]
        group_ids = json.loads(proposal["ice_model_group_ids"])
        selected = [r for r in scopes if r["model_group_id"] in group_ids]
        if any(r["eligibility"] != "ELIGIBLE" or r["canonical_id"] != canonical_id for r in selected):
            raise ValueError("Candidate source mappings changed")
        units = sum(int(r["registrations"]) for r in selected)
        if units != int(proposal["registration_units"]):
            raise ValueError("Candidate scope units do not reconcile")
        create = {"operation": "CREATE_MODEL_BASIC", "canonical_id": canonical_id, "brand_id": proposal["brand_id"],
                  "name_en": proposal["model"], "expected_revision": 0,
                  "identity_evidence": {"granularity": "MODEL_REGISTRATION_CLASS" if canonical_id == "ford.ranger_raptor_double_cab" else "MODEL",
                                        "model_name": proposal["model"], "references": json.loads(proposal["source_references"])}}
        source_scopes = [{"model_group_id": r["model_group_id"], "reg_type_scope": r["reg_type"], "master_version": "7.0",
                          "decision_ref": r["decision_ref"] or f"manifest:{r['model_group_id']}:{r['reg_type']}", "source_hash": EXPECTED_M7_SHA} for r in selected]
        links = [{"operation": "LINK_ICE_MODEL_GROUP_BY_REG_TYPE", "canonical_id": canonical_id,
                  "model_group_id": s["model_group_id"], "reg_type_scope": s["reg_type_scope"], "master_version": "7.0",
                  "decision_ref": s["decision_ref"], "source_hash": EXPECTED_M7_SHA, "expected_revision": 0} for s in source_scopes]
        candidates.append({"canonical_id": canonical_id, "name": proposal["model"], "registrations": units,
                           "create_intent": create, "link_intents": links, "source_scopes": source_scopes,
                           "raw_ice_evidence": json.loads(proposal["ice_source_classification_evidence"]),
                           "source_proposal_status": proposal["proposal_status"], "source_safe_candidate_is_not_approval": True})
    if len(candidates) != 9 or sum(c["registrations"] for c in candidates) != 59_948:
        raise ValueError("Nine-identity frozen registration total changed")
    result = {"source_pr": 235, "source_commit": SOURCE_HEAD, "catalog_path": str(CATALOG.relative_to(ROOT)),
              "source_files_sha256": pinned, "m7_package_sha256": EXPECTED_M7_SHA,
              "catalog_captured_at_utc": catalog["captured_at_utc"], "catalog_model_rows_sha256": catalog["relations"]["vehicle_models"]["canonical_rows_sha256"],
              "frozen_owner_decisions": {**frozen_check, "total": 244, "changed": 0, "reopened": 0},
              "source_reconciliation": {"source_scopes": 1407, "source_registrations": 4_141_987,
                                        "effective_registrations": eligible, "excluded_registrations": 4_141_987 - eligible,
                                        "exact_class_scope_and_units_equal_m7_zip": True},
              "existing_identity_candidate_registrations": 4_027_896, "candidates": candidates,
              "offline_only": True, "production_approved_or_servable_additions": 0}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/vehicle-db/structural-writer/nine_identity_inputs.json")
    args = parser.parse_args()
    result = prepare(args.output)
    print(json.dumps({"output": str(args.output), "candidate_identities": len(result["candidates"]),
                      "candidate_registrations": sum(c["registrations"] for c in result["candidates"]),
                      "source_reconciliation": result["source_reconciliation"], "owner_decisions_changed": 0}, indent=2))
