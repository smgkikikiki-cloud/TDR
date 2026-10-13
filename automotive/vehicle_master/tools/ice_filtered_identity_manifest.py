"""Build the filtered M7.0 identity manifest without database or writer access.

The source package, shadow crosswalk and owner-decision ledger are immutable
inputs. Outputs are an auditable effective market-analysis manifest, not
production crosswalk instructions or Vehicle Master writes.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

try:
    from ice_scoped_m7_acceptance import (
        EXPECTED_M7_SHA, EXPECTED_OVERLAY_SHA, M7_ZIP, PACKAGE, ROOT, normalize_name,
        read_csv, read_m7_facts, sha256, verify_frozen_decisions,
    )
except ModuleNotFoundError:  # import as tools.* from the Vehicle Master test suite
    from tools.ice_scoped_m7_acceptance import (
        EXPECTED_M7_SHA, EXPECTED_OVERLAY_SHA, M7_ZIP, PACKAGE, ROOT, normalize_name,
        read_csv, read_m7_facts, sha256, verify_frozen_decisions,
    )


EXCLUDED_BRANDS = {"FERRARI", "LAMBORGHINI", "LANCIA", "ALFA ROMEO", "DAIHATSU"}
# Owner-stated model-identity locks: a current catalog alias alone cannot
# collapse suffix/number variants for these marques.
IDENTITY_LOCK_BRANDS = {"AUDI", "BMW", "VOLVO", "LEXUS", "PEUGEOT", "MG", "ZEEKR", "MAZDA"}
EXISTING_LINK_DISPOSITIONS = {
    "OWNER_APPROVED_LINK", "OWNER_APPROVED_AUTO", "DETERMINISTIC_EXACT_EXISTING_LINK",
    "DETERMINISTIC_REJECTED_CANDIDATE_RECOVERY", "PICKUP_RY_SPLIT_SHADOW",
}
UNRESOLVED_DISPOSITIONS = {
    "GENUINELY_AMBIGUOUS", "INVALID_OR_UNSPECIFIED", "EXISTING_CROSSWALK_PROPOSED",
    "PICKUP_SPLIT_UNAPPROVED_OR_AMBIGUOUS", "OWNER_REJECTED_CANDIDATE", "LOW_VOLUME",
}
FROZEN_ARTIFACTS = {
    "owner_decision_ledger_244.csv": "9f251b6120d88e52c33215c5127fb6f87cd8c6cc334c39dc227bb540860ae1a8",
    "owner_identity_targets.json": "d1cd1319d737496362fecfd21176b872ec7a632519e501e8f3dca2b15383010b",
    "shadow_crosswalk_rows.csv": "9d46cad597dba3bbe83369bd9f95cfe6d10b3f6d19e0f46b69e70f10bfab5450",
}


def load_catalog(path: Path) -> tuple[dict, dict[str, dict], dict[str, set[str]]]:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    relations = snapshot["relations"]
    brands = relations["vehicle_brands"]["rows"]
    models = relations["vehicle_models"]["rows"]
    payload = json.dumps(models, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    actual = hashlib.sha256(payload).hexdigest()
    expected = relations["vehicle_models"]["canonical_rows_sha256"]
    if actual != expected:
        raise ValueError(f"Vehicle Master model snapshot hash mismatch: {actual} != {expected}")
    brand_names: dict[str, set[str]] = defaultdict(set)
    for brand in brands:
        for value in [brand.get("canonical_id"), brand.get("slug"), brand.get("name_en"),
                      brand.get("name_th"), *flatten_aliases(brand.get("aliases"))]:
            if value:
                brand_names[normalize_name(value)].add(brand["canonical_id"])
    return snapshot, {row["canonical_id"]: row for row in models}, brand_names


def flatten_aliases(value) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[|,;]", value) if part.strip()]
    if isinstance(value, list):
        return [part for item in value for part in flatten_aliases(item)]
    if isinstance(value, dict):
        return [part for item in value.values() for part in flatten_aliases(item)]
    return []


def group_catalog_matches(brand: str, name: str, models: dict[str, dict],
                          brand_names: dict[str, set[str]]) -> tuple[list[dict], list[dict]]:
    known_brands = brand_names.get(normalize_name(brand), set())
    exact, aliases = [], []
    wanted = normalize_name(name)
    for model in models.values():
        model_brand = model.get("brand_id") or ""
        nested = model.get("brand") or {}
        model_brand_names = {normalize_name(value) for value in
                             [model_brand, nested.get("name_en"), nested.get("name_th"), nested.get("slug")] if value}
        same_brand = model_brand in known_brands or (not known_brands and normalize_name(model_brand) == normalize_name(brand))
        same_brand = same_brand or normalize_name(brand) in model_brand_names
        if not same_brand:
            continue
        names = [model.get("name_en"), model.get("name_th"), model.get("slug")]
        if any(normalize_name(value or "") == wanted for value in names):
            exact.append(model)
        if any(normalize_name(alias) == wanted for alias in flatten_aliases(model.get("aliases"))):
            aliases.append(model)
    return exact, aliases


def lifecycle(model: dict | None) -> str:
    if not model:
        return "UNKNOWN"
    status = (model.get("status") or "UNKNOWN").upper()
    return "DISCONTINUED" if status in {"HISTORICAL", "DISCONTINUED", "INACTIVE"} else status


def row_model_fields(model: dict | None) -> dict:
    if not model:
        return {"catalog_brand_id": "", "catalog_model_name": "", "catalog_generation": "UNKNOWN",
                "lifecycle_status": "UNKNOWN", "segment": "UNKNOWN", "body_type": "UNKNOWN",
                "powertrains": "UNKNOWN"}
    return {"catalog_brand_id": model.get("brand_id") or "",
            "catalog_model_name": model.get("name_en") or "",
            "catalog_generation": model.get("generation") or "UNKNOWN",
            "lifecycle_status": lifecycle(model),
            "segment": model.get("segment") or "UNKNOWN",
            "body_type": model.get("body_type") or "UNKNOWN",
            "powertrains": model.get("powertrains") or "UNKNOWN"}


def below_registration_threshold(registrations: int, minimum: int = 40) -> bool:
    """Threshold is inclusive at 40 and is applied to all classes together."""
    return registrations < minimum


def coalesce_candidate_targets(items: list[dict]) -> tuple[dict[str, list[dict]], dict[str, str]]:
    """Group several Ice groups under one proposed target; reject conflicting names."""
    by_target: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        by_target[item["canonical_model_id"]].append(item)
    conflicts = {}
    for target_id, group in by_target.items():
        if (len({normalize_name(x["canonical_name_en"]) for x in group}) != 1
                or len({normalize_name(x["brand"]) for x in group}) != 1):
            conflicts[target_id] = "DUPLICATE_CANONICAL_TARGET_CONFLICT"
    return dict(by_target), conflicts


def find_duplicate_candidate_names(by_target: dict[str, list[dict]]) -> dict[str, str]:
    """Flag same-brand/name candidates with different IDs when generation is not evidenced."""
    natural_targets: dict[tuple[str, str], set[str]] = defaultdict(set)
    for target_id, items in by_target.items():
        if items:
            natural_targets[(normalize_name(items[0]["brand"]),
                             normalize_name(items[0]["canonical_name_en"]))].add(target_id)
    duplicates = {}
    for target_ids in natural_targets.values():
        if len(target_ids) > 1:
            for target_id in target_ids:
                duplicates[target_id] = "DUPLICATE_CANONICAL_NAME_WITHOUT_GENERATION_EVIDENCE"
    return duplicates


def csv_write(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                             if isinstance(value, (dict, list, set)) else value for key, value in row.items()})


def write_manifest(m7_zip: Path, package: Path, catalog_path: Path, output_dir: Path) -> dict:
    if sha256(m7_zip) != EXPECTED_M7_SHA:
        raise ValueError("M7.0 source hash is not the frozen owner-declared package")
    if sha256(package / "source/owner_overlay_original.csv") != EXPECTED_OVERLAY_SHA:
        raise ValueError("Recovered original owner overlay hash mismatch")
    artifact_manifest = json.loads((package / "artifact_manifest.json").read_text(encoding="utf-8"))
    artifact_hashes = {item["path"]: item["sha256"] for item in artifact_manifest["files"]}
    for name, expected_hash in FROZEN_ARTIFACTS.items():
        actual = sha256(package / name)
        if actual != expected_hash or artifact_hashes.get(name) != expected_hash:
            raise ValueError(f"Frozen artifact hash mismatch: {name}")
    ledger = read_csv(package / "owner_decision_ledger_244.csv")
    shadow = read_csv(package / "shadow_crosswalk_rows.csv")
    targets_doc = json.loads((package / "owner_identity_targets.json").read_text(encoding="utf-8"))
    target_rows = targets_doc["identities"]
    catalog_snapshot, models, brand_names = load_catalog(catalog_path)
    frozen = verify_frozen_decisions(ledger, shadow)
    if len(ledger) != 244 or len(shadow) != 1407 or len(target_rows) != 114:
        raise ValueError("Frozen input row count mismatch (expected 244 / 1,407 / 114)")

    facts = read_m7_facts(m7_zip)
    by_group: dict[str, dict] = {}
    classes: dict[tuple[str, str], int] = Counter()
    for fact in facts:
        group = by_group.setdefault(fact.model_group_id, {"brands": Counter(), "model": fact.model_name,
                                                            "units": 0, "classes": Counter()})
        if group["model"] != fact.model_name:
            raise ValueError(f"M7 source group has inconsistent model name: {fact.model_group_id}")
        group["units"] += fact.registrations
        group["brands"][fact.brand] += fact.registrations
        group["classes"][fact.reg_type] += fact.registrations
        classes[(fact.model_group_id, fact.reg_type)] += fact.registrations
    for group in by_group.values():
        group["brand"] = sorted(group["brands"], key=lambda name: (-group["brands"][name], name))[0]
    if len(by_group) != 1200 or sum(x["units"] for x in by_group.values()) != 4_141_987:
        raise ValueError("M7 frozen source total does not match 1,200 groups / 4,141,987 registrations")

    shadow_by_key = {(r["model_group_id"], r["reg_type"]): r for r in shadow}
    shadow_by_group: dict[str, list[dict]] = defaultdict(list)
    for row in shadow:
        shadow_by_group[row["model_group_id"]].append(row)
        if classes.get((row["model_group_id"], row["reg_type"])) != int(row["reg_count"]):
            raise ValueError(f"M7 source scope does not reconcile to frozen shadow: {row['model_group_id']} {row['reg_type']}")
    if set(classes) != set(shadow_by_key):
        raise ValueError("M7 source scopes and shadow scopes have different keys")

    target_by_group: dict[str, list[dict]] = defaultdict(list)
    for item in target_rows:
        target_by_group[item["model_group_id"]].append(item)
    ledger_by_group: dict[str, list[dict]] = defaultdict(list)
    for item in ledger:
        ledger_by_group[item["model_group_id"]].append(item)
    scoped_pickup_groups = {row["model_group_id"] for row in shadow
                            if row["disposition"] in {"PICKUP_RY_SPLIT_SHADOW", "PICKUP_SPLIT_UNAPPROVED_OR_AMBIGUOUS"}}

    owner_excluded = {r["model_group_id"] for r in shadow if r["disposition"] == "OWNER_EXCLUDED"}
    low_volume = {g for g, x in by_group.items() if below_registration_threshold(x["units"])}
    excluded_brand = {g for g, x in by_group.items() if x["brand"].strip().upper() in EXCLUDED_BRANDS}
    all_excluded = low_volume | excluded_brand | owner_excluded
    eligible_ids = set(by_group) - all_excluded

    excluded_rows = []
    for group_id in sorted(all_excluded):
        value = by_group[group_id]
        reasons = []
        if group_id in low_volume:
            reasons.append("LOW_VOLUME_LT_40")
        if group_id in excluded_brand:
            reasons.append("EXCLUDED_BRAND")
        if group_id in owner_excluded:
            reasons.append("PRESERVED_OWNER_EXCLUSION")
        excluded_rows.append({"model_group_id": group_id, "brand": value["brand"], "ice_model_name": value["model"],
                              "ice_brand_values": dict(sorted(value["brands"].items())),
                              "registrations_removed": value["units"], "exclusion_reasons": reasons,
                              "registrations_by_reg_type": dict(sorted(value["classes"].items())),
                              "evidence_refs": ["M7.0:reg_trend", *[f"shadow:{r['reg_type']}:{r['disposition']}"
                                  for r in shadow_by_group[group_id] if r["disposition"] == "OWNER_EXCLUDED"]],
                              "source_package_sha256": EXPECTED_M7_SHA})

    # Recompute each previously shadow-proposed identity against the real catalog.
    # Compatible duplicate candidates coalesce by target ID. Any identity collision
    # or incompatible duplicate is unresolved; none becomes create authority.
    eligible_target_rows = []
    for item in target_rows:
        group_id = item["model_group_id"]
        if group_id not in eligible_ids:
            continue
        eligible_target_rows.append(item)
    candidate_by_target, candidate_issue = coalesce_candidate_targets(eligible_target_rows)
    candidate_issue.update(find_duplicate_candidate_names(candidate_by_target))
    proposal_by_group: dict[str, dict] = {}
    proposal_records: dict[str, dict] = {}
    for target_id, items in sorted(candidate_by_target.items()):
        if target_id in candidate_issue:
            continue
        item = items[0]
        exact, aliases = group_catalog_matches(item["brand"], item["canonical_name_en"], models, brand_names)
        exact_id = models.get(target_id)
        if exact_id:
            catalog_match = exact_id
            if normalize_name(exact_id.get("name_en") or "") != normalize_name(item["canonical_name_en"]):
                candidate_issue[target_id] = "CANONICAL_ID_COLLISION_DIFFERENT_MODEL"
                continue
            known_brands = brand_names.get(normalize_name(item["brand"]), set())
            if known_brands and exact_id.get("brand_id") not in known_brands:
                candidate_issue[target_id] = "CANONICAL_ID_COLLISION_DIFFERENT_BRAND"
                continue
            resolved_target = target_id
            kind = "CANONICAL_ID_AND_NAME_EXIST"
        elif exact:
            ids = {x["canonical_id"] for x in exact}
            if len(ids) != 1:
                candidate_issue[target_id] = "MULTIPLE_EXACT_EXISTING_IDENTITIES"
                continue
            catalog_match = exact[0]
            resolved_target = catalog_match["canonical_id"]
            kind = "EXACT_EXISTING_IDENTITY"
        elif aliases:
            frozen_create = any(d["owner_action"] == "OWNER_CREATE_IDENTITY"
                                for item2 in items for d in ledger_by_group.get(item2["model_group_id"], []))
            owner_distinct = any(item2.get("distinct_from") for item2 in items)
            alias_ids = {x["canonical_id"] for x in aliases}
            locked_brand = item["brand"].strip().upper() in IDENTITY_LOCK_BRANDS
            if frozen_create or owner_distinct or locked_brand or len(alias_ids) != 1:
                candidate_issue[target_id] = "OWNER_NEW_IDENTITY_CONFLICTS_WITH_EXISTING_ALIAS"
                continue
            catalog_match = aliases[0]
            resolved_target = catalog_match["canonical_id"]
            kind = "EXACT_EXISTING_CATALOG_ALIAS"
        else:
            catalog_match = None
            resolved_target = target_id
            kind = "NO_EXACT_OR_ALIAS_COLLISION"
        groups = sorted({x["model_group_id"] for x in items})
        for item2 in items:
            proposal_by_group[item2["model_group_id"]] = {
                "target_id": resolved_target, "candidate_target_id": target_id,
                "candidate_name": item2["canonical_name_en"], "candidate_brand": item2["brand"],
                "candidate": item2, "catalog_match": catalog_match, "collision_check": kind,
            }
        if catalog_match is None:
            registration_units = sum(by_group[g]["units"] for g in groups)
            known_brand_ids = brand_names.get(normalize_name(item["brand"]), set())
            proposal_records[target_id] = {
                "canonical_id": target_id, "brand_id": next(iter(known_brand_ids)) if len(known_brand_ids) == 1 else "UNKNOWN",
                "brand": item["brand"], "model": item["canonical_name_en"],
                "generation": "UNKNOWN", "lifecycle_status": item.get("lifecycle_status") or "UNKNOWN",
                "segment": "UNKNOWN", "body_type": "UNKNOWN", "powertrain": "UNKNOWN",
                "source_references": sorted({f"owner_identity_targets:{g}" for g in groups} |
                                             {f"owner_decision:{d['decision_id']}" for g in groups for d in ledger_by_group.get(g, [])}),
                "ice_model_group_ids": groups,
                "registration_units": registration_units,
                "source_reg_type_scopes": sorted({row["reg_type"] for g in groups for row in shadow_by_group[g]}),
                "collision_check": kind,
                "proposal_status": "CANDIDATE_ONLY_NOT_CREATE_AUTHORITY",
                "writer_dependency": "Vehicle Master Phase 1 structural governed writer and authorization",
                "source_package_sha256": EXPECTED_M7_SHA,
                "vehicle_master_snapshot_sha256": catalog_snapshot["relations"]["vehicle_models"]["canonical_rows_sha256"],
            }

    # Validate all proposed target IDs globally against the catalog, and retain
    # source decision refs as provenance rather than treating them as new approvals.
    proposals = list(proposal_records.values())
    proposals.sort(key=lambda x: x["canonical_id"])
    proposal_target_ids = {row["canonical_id"] for row in proposals}

    link_rows = []
    unresolved_rows = []
    eligible_rows = []
    category_units = Counter()
    category_groups = Counter()
    effective_link_units = 0
    for group_id in sorted(eligible_ids):
        value = by_group[group_id]
        group_scopes = sorted(shadow_by_group[group_id], key=lambda r: r["reg_type"])
        scope_results = []
        for row in group_scopes:
            disposition = row["disposition"]
            target_id = row["target_canonical_id"] or ""
            resolution = None
            match_kind = ""
            reason = row["reason"]
            if disposition in EXISTING_LINK_DISPOSITIONS:
                candidate = models.get(target_id)
                if candidate:
                    resolution, match_kind = candidate, disposition
                else:
                    resolution = None
                    reason = f"FROZEN_OR_SHADOW_TARGET_ABSENT_FROM_VEHICLE_MASTER:{target_id}"
            elif disposition == "OWNER_APPROVED_SHADOW_IDENTITY":
                proposal = proposal_by_group.get(group_id)
                if group_id in proposal_issue_for_group(candidate_issue, target_by_group.get(group_id, [])):
                    reason = proposal_issue_for_group(candidate_issue, target_by_group.get(group_id, []))[group_id]
                elif proposal and proposal["catalog_match"]:
                    resolution, match_kind = proposal["catalog_match"], "CANDIDATE_RECONCILED_TO_EXISTING_IDENTITY"
                    target_id = resolution["canonical_id"]
                elif proposal and proposal["candidate_target_id"] in proposal_target_ids:
                    resolution = {"canonical_id": proposal["target_id"], "name_en": proposal["candidate_name"],
                                  "brand_id": "", "status": proposal["candidate"].get("lifecycle_status") or "UNKNOWN",
                                  "generation": None, "segment": None, "body_type": None, "powertrains": None}
                    target_id, match_kind = proposal["target_id"], "NEW_BASIC_IDENTITY_CANDIDATE"
                else:
                    reason = reason or "NO_VALID_IDENTITY_TARGET_AFTER_COLLISION_CHECK"
            elif disposition in UNRESOLVED_DISPOSITIONS:
                # Never use a group-level name/alias to fill a pickup class that
                # lacks an explicit scoped decision.
                if group_id in scoped_pickup_groups:
                    reason = reason or "SCOPED_PICKUP_CLASS_NOT_RESOLVED"
                else:
                    # A unique exact same-brand catalog match is safe evidence
                    # for non-split groups even if the historical scorer had no
                    # final disposition.
                    exact, aliases = group_catalog_matches(value["brand"], value["model"], models, brand_names)
                    matches = exact or aliases
                    if len({x["canonical_id"] for x in matches}) == 1:
                        resolution, match_kind = matches[0], "UNIQUE_SAME_BRAND_EXACT" if exact else "UNIQUE_SAME_BRAND_ALIAS"
                        target_id = resolution["canonical_id"]
                    else:
                        reason = reason or disposition
            if resolution:
                fields = row_model_fields(resolution)
                if target_id in models:
                    link = {"model_group_id": group_id, "reg_type": row["reg_type"], "brand": value["brand"],
                            "ice_model_name": value["model"], "registrations": int(row["reg_count"]),
                            "canonical_id": target_id, **fields, "match_evidence": match_kind,
                            "decision_ref": row["decision_ref"], "source_disposition": disposition,
                            "mapping_authority": "OFFLINE_MANIFEST_EVIDENCE_ONLY",
                            "source_package_sha256": EXPECTED_M7_SHA}
                    link_rows.append(link)
                    scope_results.append(("MATCH_EXISTING", row, target_id))
                else:
                    scope_results.append(("NEW_BASIC_IDENTITY_NEEDED", row, target_id))
            else:
                unresolved_rows.append({"model_group_id": group_id, "reg_type": row["reg_type"],
                                       "brand": value["brand"], "ice_model_name": value["model"],
                                       "registrations": int(row["reg_count"]), "evidence_status": "UNRESOLVED_EVIDENCE",
                                       "reason": reason or disposition, "shadow_disposition": disposition,
                                       "candidate_target_id": target_id,
                                       "decision_ref": row["decision_ref"],
                                       "source_package_sha256": EXPECTED_M7_SHA})
                scope_results.append(("UNRESOLVED_EVIDENCE", row, ""))
        states = {item[0] for item in scope_results}
        category = "UNRESOLVED_EVIDENCE" if "UNRESOLVED_EVIDENCE" in states else (
            "NEW_BASIC_IDENTITY_NEEDED" if "NEW_BASIC_IDENTITY_NEEDED" in states else "MATCH_EXISTING")
        category_groups[category] += 1
        category_units[category] += value["units"]
        if category == "MATCH_EXISTING":
            effective_link_units += value["units"]
        candidate_refs = sorted({
            item.get("decision_ref") or "" for item in group_scopes if item.get("decision_ref")
        } | {f"owner_decision:{d['decision_id']}" for d in ledger_by_group.get(group_id, [])})
        linked_ids = sorted({item[2] for item in scope_results if item[2]})
        eligible_rows.append({"model_group_id": group_id, "brand": value["brand"], "ice_model_name": value["model"],
                              "ice_brand_values": dict(sorted(value["brands"].items())),
                              "registrations": value["units"], "registrations_by_reg_type": dict(sorted(value["classes"].items())),
                              "identity_status": category, "canonical_identity_ids": linked_ids,
                              "source_references": candidate_refs,
                              "frozen_owner_decision_refs": [d["decision_id"] for d in ledger_by_group.get(group_id, [])],
                              "owner_decisions_changed": False, "source_package_sha256": EXPECTED_M7_SHA})

    # Groups marked NEW must point only at proposal targets, and no duplicate
    # canonical IDs may survive as two distinct proposed records.
    if len({row["canonical_id"] for row in proposals}) != len(proposals):
        raise ValueError("Duplicate canonical target proposals remain after coalescing")
    proposal_group_ids = {g for row in proposals for g in row["ice_model_group_ids"]}
    actual_new_groups = {row["model_group_id"] for row in eligible_rows if row["identity_status"] == "NEW_BASIC_IDENTITY_NEEDED"}
    if not actual_new_groups <= proposal_group_ids:
        raise ValueError(f"NEW identity groups lack proposal: {sorted(actual_new_groups - proposal_group_ids)}")
    if set(eligible_ids) != {r["model_group_id"] for r in eligible_rows}:
        raise ValueError("Eligible group output is not a one-row-per-group partition")

    original_units = sum(row["units"] for row in by_group.values())
    excluded_units = sum(by_group[group]["units"] for group in all_excluded)
    effective_units = sum(by_group[group]["units"] for group in eligible_ids)
    if original_units != excluded_units + effective_units:
        raise ValueError("Source / excluded / effective registration reconciliation failed")
    if sum(category_units.values()) != effective_units or sum(category_groups.values()) != len(eligible_ids):
        raise ValueError("Eligible identity category partition does not reconcile")

    csv_write(output_dir / "eligible_model_groups.csv", ["model_group_id", "brand", "ice_brand_values", "ice_model_name", "registrations",
              "registrations_by_reg_type", "identity_status", "canonical_identity_ids", "source_references",
              "frozen_owner_decision_refs", "owner_decisions_changed", "source_package_sha256"], eligible_rows)
    csv_write(output_dir / "excluded_model_groups.csv", ["model_group_id", "brand", "ice_brand_values", "ice_model_name", "registrations_removed",
              "exclusion_reasons", "registrations_by_reg_type", "evidence_refs", "source_package_sha256"], excluded_rows)
    csv_write(output_dir / "existing_identity_links.csv", ["model_group_id", "reg_type", "brand", "ice_model_name", "registrations",
              "canonical_id", "catalog_brand_id", "catalog_model_name", "catalog_generation", "lifecycle_status", "segment",
              "body_type", "powertrains", "match_evidence", "decision_ref", "source_disposition", "mapping_authority",
              "source_package_sha256"], link_rows)
    csv_write(output_dir / "new_basic_identity_proposals.csv", ["canonical_id", "brand_id", "brand", "model", "generation", "lifecycle_status",
              "segment", "body_type", "powertrain", "source_references", "ice_model_group_ids", "registration_units",
              "source_reg_type_scopes", "collision_check", "proposal_status", "writer_dependency", "source_package_sha256",
              "vehicle_master_snapshot_sha256"], proposals)
    csv_write(output_dir / "unresolved_identity_evidence.csv", ["model_group_id", "reg_type", "brand", "ice_model_name", "registrations",
              "evidence_status", "reason", "shadow_disposition", "candidate_target_id", "decision_ref", "source_package_sha256"],
              unresolved_rows)

    output_files = ["eligible_model_groups.csv", "excluded_model_groups.csv", "existing_identity_links.csv",
                    "new_basic_identity_proposals.csv", "unresolved_identity_evidence.csv"]

    qa = {
        "schema": "tdr.ice-filtered-identity-manifest.qa.v1",
        "offline_only": True,
        "no_database_write_or_writer_invocation": True,
        "governance_provenance": {"portfolio_roadmap": {"version": "approved v1.0", "commit": "42be6b6a803727086b404b2cb46f75593bb2c1d4"},
                                  "roadmap_base_main": "c2715cbee494ae076b2582ef99f2bbc590b5dd99",
                                  "ice_market_roadmap_commit": "847fef43",
                                  "vehicle_db_v3_current_commit": "a7007a7c2d43222d1d4d35342f891c832cbcea77",
                                  "issue_228_recovery_pr_head": "872a1117b163feac42e0ce55314cd7a7408896b5",
                                  "scoped_resolver_pr_head": "3050beb1cdad4530808177de7b9d66abb21364f3"},
        "source": {"package": str(m7_zip.relative_to(ROOT)) if m7_zip.is_relative_to(ROOT) else m7_zip.name,
                   "master_version": "7.0", "sha256": EXPECTED_M7_SHA,
                   "raw_registration_rows": len(facts), "model_groups": len(by_group), "registrations": original_units},
        "source_artifacts": {"owner_decision_ledger_244.csv": FROZEN_ARTIFACTS["owner_decision_ledger_244.csv"],
                             "owner_identity_targets.json": FROZEN_ARTIFACTS["owner_identity_targets.json"],
                             "shadow_crosswalk_rows.csv": FROZEN_ARTIFACTS["shadow_crosswalk_rows.csv"],
                             "original_owner_overlay.csv": EXPECTED_OVERLAY_SHA},
        "vehicle_master_snapshot": {"captured_at_utc": catalog_snapshot["captured_at_utc"],
                                    "models": len(models), "models_sha256": catalog_snapshot["relations"]["vehicle_models"]["canonical_rows_sha256"],
                                    "brands": catalog_snapshot["relations"]["vehicle_brands"]["observed_rows"],
                                    "generations": catalog_snapshot["relations"]["vehicle_generations"]["observed_rows"],
                                    "read_only_select_snapshot": catalog_snapshot["read_only"]},
        "filters": {"minimum_registrations_inclusive": 40, "low_volume_groups": len(low_volume),
                    "low_volume_registrations": sum(by_group[g]["units"] for g in low_volume),
                    "excluded_brands": sorted(EXCLUDED_BRANDS), "excluded_brand_groups": len(excluded_brand),
                    "excluded_brand_registrations": sum(by_group[g]["units"] for g in excluded_brand),
                    "preserved_owner_excluded_groups": len(owner_excluded),
                    "preserved_owner_excluded_registrations": sum(by_group[g]["units"] for g in owner_excluded),
                    "unique_excluded_groups": len(all_excluded), "unique_excluded_registrations": excluded_units,
                    "excluded_group_overlap_counts": {"low_and_brand": len(low_volume & excluded_brand),
                        "low_and_owner": len(low_volume & owner_excluded), "brand_and_owner": len(excluded_brand & owner_excluded),
                        "all_three": len(low_volume & excluded_brand & owner_excluded)},
                    "eligible_groups": len(eligible_ids), "eligible_registrations": effective_units,
                    "registration_reconciliation": {"source": original_units, "removed": excluded_units,
                        "effective": effective_units, "reconciles": original_units == excluded_units + effective_units}},
        "frozen_owner_decisions": {"total": len(ledger), "action_counts": dict(sorted(Counter(x["owner_action"] for x in ledger).items())),
                                   **frozen, "decisions_changed": 0, "decisions_reopened": 0,
                                   "original_overlay_sha256": EXPECTED_OVERLAY_SHA},
        "identity_classification": {"group_counts": dict(sorted(category_groups.items())),
                                    "registration_units": dict(sorted(category_units.items())),
                                    "eligible_groups_reconciled": sum(category_groups.values()) == len(eligible_ids),
                                    "eligible_registrations_reconciled": sum(category_units.values()) == effective_units,
                                    "existing_link_scope_rows": len(link_rows), "unresolved_scope_rows": len(unresolved_rows),
                                    "crosswalk_coverage": {"existing_identity_registrations": effective_link_units,
                                        "effective_denominator": effective_units,
                                        "existing_identity_pct": round(100 * effective_link_units / effective_units, 6),
                                        "classified_with_existing_or_new_identity_registrations": category_units["MATCH_EXISTING"] + category_units["NEW_BASIC_IDENTITY_NEEDED"],
                                        "classified_identity_pct": round(100 * (category_units["MATCH_EXISTING"] + category_units["NEW_BASIC_IDENTITY_NEEDED"]) / effective_units, 6),
                                        "unresolved_registrations": category_units["UNRESOLVED_EVIDENCE"]}},
        "identity_proposals": {"filtered_shadow_identity_groups": sum(1 for x in target_rows if x["model_group_id"] in eligible_ids),
                               "filtered_shadow_identity_units": sum(by_group[x["model_group_id"]]["units"] for x in target_rows if x["model_group_id"] in eligible_ids),
                               "candidate_proposal_count_after_catalog_collision_checks": len(proposals),
                               "candidate_registration_units": sum(x["registration_units"] for x in proposals),
                               "duplicate_canonical_targets_after_coalescing": 0,
                               "candidate_target_conflicts_requiring_resolution": len(candidate_issue),
                               "proposal_authority": "CANDIDATE_ONLY_NOT_CREATE_AUTHORITY",
                               "unresolved_candidate_targets": candidate_issue},
        "output_files": output_files,
    }
    qa["output_sha256"] = {name: sha256(output_dir / name) for name in output_files}
    (output_dir / "identity_manifest_qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return qa


def proposal_issue_for_group(issues: dict[str, str], targets: list[dict]) -> dict[str, str]:
    return {target["model_group_id"]: issues[target["canonical_model_id"]]
            for target in targets if target["canonical_model_id"] in issues}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--m7-zip", type=Path, default=M7_ZIP)
    parser.add_argument("--package-dir", type=Path, default=PACKAGE)
    parser.add_argument("--catalog-snapshot", type=Path, default=PACKAGE / "qa/vehicle_master_identity_snapshot_2026-10-13.json")
    parser.add_argument("--output-dir", type=Path, default=PACKAGE / "qa/filtered_identity_manifest")
    args = parser.parse_args()
    report = write_manifest(args.m7_zip, args.package_dir, args.catalog_snapshot, args.output_dir)
    print(json.dumps({"output_dir": str(args.output_dir), "filters": report["filters"],
                      "identity_classification": report["identity_classification"],
                      "identity_proposals": report["identity_proposals"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
