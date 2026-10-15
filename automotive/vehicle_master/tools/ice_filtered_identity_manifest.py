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
import io
import json
from pathlib import Path
import re
import zipfile

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
UNRESOLVED_BASELINE_SHA = "53c3bb45fe4cadceb2a2984ddec65533fdfb2ece81bb86b623fc2e4bb7b7f63a"


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


def basic_identity_candidate(brand: str, source_model_name: str, brand_id: str) -> tuple[str, str]:
    """Make a name-only basic candidate from source text; never infer specs/generation."""
    name = source_model_name.strip()
    name = re.sub(rf"^{re.escape(brand.strip())}[\s:-]+", "", name, flags=re.IGNORECASE).strip()
    # Ice names sometimes use the expanded OEM spelling rather than the brand cell.
    if brand.strip().upper() == "BMW":
        name = re.sub(r"^BMW\s+", "", name, flags=re.IGNORECASE).strip()
    if brand.strip().upper() == "MERCEDES BENZ":
        name = re.sub(r"^Mercedes[- ]Benz\s+", "", name, flags=re.IGNORECASE).strip()
    slug = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
    if not slug:
        raise ValueError(f"Cannot derive a basic identity slug from source model name {source_model_name!r}")
    return f"{brand_id}.{slug}", name


def brand_id_for_source(brand: str, brand_names: dict[str, set[str]]) -> tuple[str, bool]:
    known = brand_names.get(normalize_name(brand), set())
    if len(known) == 1:
        return next(iter(known)), True
    slug = re.sub(r"[^a-z0-9]+", "_", brand.casefold()).strip("_")
    return slug, False


def read_m7_dimensions(path: Path) -> dict[str, dict[str, str]]:
    """Read only the package's declared model-group market classifications."""
    with zipfile.ZipFile(path) as outer:
        members = [name for name in outer.namelist() if name.startswith("panels/dims_") and name.endswith(".zip")]
        if len(members) != 1:
            raise ValueError(f"Expected one M7.0 dims panel, found {members}")
        with zipfile.ZipFile(io.BytesIO(outer.read(members[0]))) as panel:
            files = [name for name in panel.namelist() if name.endswith("dims/model_group.csv")]
            if len(files) != 1:
                raise ValueError(f"Expected one dims/model_group.csv, found {files}")
            with io.TextIOWrapper(panel.open(files[0]), encoding="utf-8-sig", newline="") as handle:
                rows = {}
                for row in csv.DictReader(handle):
                    group_id = row["model_group_id"]
                    if group_id in rows:
                        raise ValueError(f"Duplicate M7.0 dimension group: {group_id}")
                    rows[group_id] = {"segment": row.get("segment", "").strip() or "UNKNOWN",
                                      "body": row.get("body", "").strip() or "UNKNOWN",
                                      "model_name": row.get("model_name", "").strip()}
                return rows


def evidenced_classification(groups: list[str], field: str, dimensions: dict[str, dict[str, str]]) -> str:
    values = {dimensions[group][field] for group in groups
              if dimensions[group][field] and dimensions[group][field] != "UNKNOWN"
              and dimensions[group][field] != "ไม่ระบุ"}
    return next(iter(values)) if len(values) == 1 else "UNKNOWN"


def raw_ice_classification(groups: list[str], dimensions: dict[str, dict[str, str]]) -> dict[str, str]:
    """Keep Ice DIMS classifications as source evidence, never as Vehicle Master facts."""
    def raw_value(field: str) -> str:
        values = sorted({dimensions[group].get(field, "").strip() or "UNKNOWN" for group in groups})
        return values[0] if len(values) == 1 else json.dumps(values, ensure_ascii=False)
    return {
        "ice_source_segment": raw_value("segment"),
        "ice_source_body_type": raw_value("body"),
    }


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
    unresolved_baseline_path = package / "qa/filtered_identity_manifest/unresolved_identity_evidence_baseline_59.csv"
    if sha256(unresolved_baseline_path) != UNRESOLVED_BASELINE_SHA:
        raise ValueError("Frozen 59-scope unresolved-evidence baseline hash mismatch")
    unresolved_baseline = read_csv(unresolved_baseline_path)
    targets_doc = json.loads((package / "owner_identity_targets.json").read_text(encoding="utf-8"))
    target_rows = targets_doc["identities"]
    catalog_snapshot, models, brand_names = load_catalog(catalog_path)
    frozen = verify_frozen_decisions(ledger, shadow)
    if len(ledger) != 244 or len(shadow) != 1407 or len(target_rows) != 114:
        raise ValueError("Frozen input row count mismatch (expected 244 / 1,407 / 114)")

    facts = read_m7_facts(m7_zip)
    dimensions = read_m7_dimensions(m7_zip)
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
    if set(dimensions) != set(by_group):
        raise ValueError("M7.0 dimension groups and registration groups have different keys")
    if any(dimensions[group]["model_name"] != by_group[group]["model"] for group in by_group):
        raise ValueError("M7.0 dimension names and registration model names disagree")

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
                              **raw_ice_classification([group_id], dimensions),
                              "ice_brand_values": dict(sorted(value["brands"].items())),
                              "registrations_removed": value["units"], "exclusion_reasons": reasons,
                              "registrations_by_reg_type": dict(sorted(value["classes"].items())),
                              "evidence_refs": ["M7.0:reg_trend", *[f"shadow:{r['reg_type']}:{r['disposition']}"
                                  for r in shadow_by_group[group_id] if r["disposition"] == "OWNER_EXCLUDED"]],
                              "source_package_sha256": EXPECTED_M7_SHA})

    scope_rows = [{
        "model_group_id": group_id, "reg_type": row["reg_type"], "brand": by_group[group_id]["brand"],
        "ice_model_name": by_group[group_id]["model"], "registrations": int(row["reg_count"]),
        **raw_ice_classification([group_id], dimensions),
        "eligibility": "EXCLUDED", "disposition": "EXCLUDED", "disposition_detail": ";".join(
            reason for reason, applies in [("LOW_VOLUME_LT_40", group_id in low_volume),
                                            ("EXCLUDED_BRAND", group_id in excluded_brand),
                                            ("PRESERVED_OWNER_EXCLUSION", group_id in owner_excluded)] if applies),
        "canonical_id": "", "approval_state": "EXCLUDED_FROM_EFFECTIVE_MARKET_ANALYSIS",
        "reason": ";".join(reason for reason, applies in [("LOW_VOLUME_LT_40", group_id in low_volume),
                                                            ("EXCLUDED_BRAND", group_id in excluded_brand),
                                                            ("PRESERVED_OWNER_EXCLUSION", group_id in owner_excluded)] if applies),
        "decision_ref": row["decision_ref"], "source_package_sha256": EXPECTED_M7_SHA,
    } for group_id in sorted(all_excluded) for row in shadow_by_group[group_id]]

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
        ice_classification = raw_ice_classification(groups, dimensions)
        for item2 in items:
            proposal_by_group[item2["model_group_id"]] = {
                "target_id": resolved_target, "candidate_target_id": target_id,
                "candidate_name": item2["canonical_name_en"], "candidate_brand": item2["brand"],
                "candidate": item2, "catalog_match": catalog_match, "collision_check": kind,
            }
        if catalog_match is None:
            registration_units = sum(by_group[g]["units"] for g in groups)
            known_brand_ids = brand_names.get(normalize_name(item["brand"]), set())
            proposed_brand_id = next(iter(known_brand_ids)) if len(known_brand_ids) == 1 else re.sub(
                r"[^a-z0-9]+", "_", item["brand"].casefold()).strip("_")
            proposal_records[target_id] = {
                "canonical_id": target_id, "brand_id": proposed_brand_id,
                "brand_record_status": "PRESENT_IN_SNAPSHOT" if len(known_brand_ids) == 1 else "BRAND_CREATE_OR_RECONCILIATION_REQUIRED",
                "brand": item["brand"], "model": item["canonical_name_en"],
                "generation": "UNKNOWN", "lifecycle_status": item.get("lifecycle_status") or "UNKNOWN",
                # No Vehicle Master row exists for a create candidate. Ice DIMS
                # is retained below as raw evidence and must not populate TDR facts.
                "segment": "UNKNOWN", "body_type": "UNKNOWN", "powertrain": "UNKNOWN",
                **ice_classification,
                "ice_source_classification_evidence": {g: {"segment": dimensions[g]["segment"],
                    "body": dimensions[g]["body"]} for g in groups},
                "source_references": sorted({f"owner_identity_targets:{g}" for g in groups} |
                                             {f"owner_decision:{d['decision_id']}" for g in groups for d in ledger_by_group.get(g, [])} |
                                             {f"M7.0:dims/model_group.csv:{g}" for g in groups}),
                "ice_model_group_ids": groups,
                "registration_units": registration_units,
                "source_reg_type_scopes": sorted({row["reg_type"] for g in groups for row in shadow_by_group[g]}),
                "collision_check": kind,
                "proposal_status": "CANDIDATE_ONLY_NOT_CREATE_AUTHORITY",
                "writer_dependency": "Vehicle Master Phase 1 structural governed writer and authorization",
                "source_package_sha256": EXPECTED_M7_SHA,
                "vehicle_master_snapshot_sha256": catalog_snapshot["relations"]["vehicle_models"]["canonical_rows_sha256"],
            }

    # Recover actionable unmatched groups at model/class grain. The source name
    # supports only a basic candidate; DIMS remains raw evidence only.
    # Generation/lifecycle/powertrain stay unknown unless independently
    # evidenced. Pickup splits and legacy proposed scopes remain held unless an
    # exact owner-approved RY target is already present above.
    alias_repairs: list[dict] = []
    repaired_candidate_issues: set[str] = set()
    source_unknown_groups = {group_id for group_id, value in by_group.items()
                             if value["model"].strip() in {"", "ไม่ระบุ"}}
    for group_id in sorted(eligible_ids):
        group_scopes = shadow_by_group[group_id]
        unresolved_scopes = [row for row in group_scopes if row["disposition"] in UNRESOLVED_DISPOSITIONS]
        issue_targets = {item["canonical_model_id"] for item in target_by_group.get(group_id, [])
                         if item["canonical_model_id"] in candidate_issue}
        if (not unresolved_scopes and not issue_targets) or group_id in source_unknown_groups or group_id in scoped_pickup_groups:
            continue
        # A legacy target is deliberately not promoted by this offline report.
        if any(row["disposition"] == "EXISTING_CROSSWALK_PROPOSED" for row in unresolved_scopes):
            continue
        value = by_group[group_id]
        brand_id, brand_exists = brand_id_for_source(value["brand"], brand_names)
        _, source_model_candidate = basic_identity_candidate(value["brand"], value["model"], brand_id)
        owner_target_names = [item.get("canonical_name_en") or "" for item in target_by_group.get(group_id, [])]
        alias_probe = next((name for name in owner_target_names if name), source_model_candidate)
        exact, aliases = group_catalog_matches(value["brand"], alias_probe, models, brand_names)
        exact_ids, alias_ids = {m["canonical_id"] for m in exact}, {m["canonical_id"] for m in aliases}
        if exact_ids and len(exact_ids) == 1:
            # The normal scope loop will record the exact match.
            continue
        locked = value["brand"].strip().upper() in IDENTITY_LOCK_BRANDS
        alias_conflict = bool(aliases) and (locked or len(alias_ids) != 1)
        if aliases and not alias_conflict:
            # Unique same-brand aliases are checked again in the scope loop.
            continue

        source_name = value["model"]
        canonical_id, canonical_name = basic_identity_candidate(value["brand"], source_name, brand_id)
        if canonical_id in models:
            existing = models[canonical_id]
            if normalize_name(existing.get("name_en") or "") != normalize_name(canonical_name):
                continue
            # An existing canonical ID is not a create proposal.
            continue
        collision_names = [m for m in models.values()
                           if (m.get("brand_id") == brand_id and
                               normalize_name(m.get("name_en") or "") == normalize_name(canonical_name))]
        if collision_names:
            continue
        if canonical_id in proposal_records:
            combined_groups = sorted(
                set(proposal_records[canonical_id]["ice_model_group_ids"]) | {group_id})
            proposal_records[canonical_id]["ice_model_group_ids"] = combined_groups
            proposal_records[canonical_id]["registration_units"] += value["units"]
            proposal_records[canonical_id]["source_reg_type_scopes"] = sorted(
                set(proposal_records[canonical_id]["source_reg_type_scopes"]) |
                {row["reg_type"] for row in group_scopes})
            proposal_records[canonical_id].update(raw_ice_classification(combined_groups, dimensions))
            proposal_records[canonical_id].setdefault("ice_source_classification_evidence", {})[group_id] = {
                "segment": dimensions[group_id]["segment"], "body": dimensions[group_id]["body"]}
            proposal_records[canonical_id]["source_references"] = sorted(
                set(proposal_records[canonical_id]["source_references"]) |
                {f"M7.0:dims/model_group.csv:{group}" for group in combined_groups})
        else:
            ice_classification = raw_ice_classification([group_id], dimensions)
            proposal_records[canonical_id] = {
                "canonical_id": canonical_id, "brand_id": brand_id,
                "brand_record_status": "PRESENT_IN_SNAPSHOT" if brand_exists else "BRAND_CREATE_OR_RECONCILIATION_REQUIRED",
                "brand": value["brand"], "model": canonical_name, "generation": "UNKNOWN",
                "lifecycle_status": "UNKNOWN", "segment": "UNKNOWN", "body_type": "UNKNOWN",
                **ice_classification,
                "ice_source_classification_evidence": {group_id: {"segment": dimensions[group_id]["segment"],
                    "body": dimensions[group_id]["body"]}},
                "powertrain": "UNKNOWN", "source_references": sorted(
                    {"M7.0:reg_trend:model_name", f"owner_identity_targets:{group_id}",
                     f"M7.0:dims/model_group.csv:{group_id}"} |
                    {f"shadow:{row['reg_type']}:{row['disposition']}" for row in group_scopes}),
                "ice_model_group_ids": [group_id], "registration_units": value["units"],
                "source_reg_type_scopes": sorted({row["reg_type"] for row in group_scopes}),
                "collision_check": "NO_EXISTING_SAME_BRAND_IDENTITY_OR_ALIAS",
                "proposal_status": "CANDIDATE_ONLY_NOT_CREATE_AUTHORITY",
                "writer_dependency": "Vehicle Master Phase 1 structural governed writer and owner authorization",
                "source_package_sha256": EXPECTED_M7_SHA,
                "vehicle_master_snapshot_sha256": catalog_snapshot["relations"]["vehicle_models"]["canonical_rows_sha256"],
            }
        proposal_by_group[group_id] = {
            "target_id": canonical_id, "candidate_target_id": canonical_id,
            "candidate_name": canonical_name, "candidate_brand": value["brand"],
            "candidate": {"canonical_model_id": canonical_id, "canonical_name_en": canonical_name,
                          "brand": value["brand"], "brand_id": brand_id,
                          "lifecycle_status": "UNKNOWN", "generation": "UNKNOWN"},
            "catalog_match": None, "collision_check": "NO_EXISTING_SAME_BRAND_IDENTITY_OR_ALIAS",
        }
        if alias_conflict:
            repaired_candidate_issues.update(issue_targets)
            for aliased in aliases:
                for alias in flatten_aliases(aliased.get("aliases")):
                    if normalize_name(alias) in {normalize_name(source_name), normalize_name(alias_probe)}:
                        alias_repairs.append({
                            "source_model_group_id": group_id, "source_model_name": source_name,
                            "existing_canonical_id": aliased["canonical_id"], "existing_canonical_name": aliased.get("name_en") or "",
                            "alias_to_remove": alias, "proposed_canonical_id": canonical_id,
                            "proposed_model_name": canonical_name,
                            "repair_reason": "FROZEN_OWNER_IDENTITY_LOCK_REQUIRES_DISTINCT_MODEL",
                            "repair_status": "PROPOSAL_ONLY_NOT_CATALOG_MUTATION",
                            "registration_units": value["units"], "owner_decision_changed": False,
                            "source_package_sha256": EXPECTED_M7_SHA,
                        })

    for target_id in repaired_candidate_issues:
        candidate_issue.pop(target_id, None)

    # Validate all proposed target IDs globally against the catalog, and retain
    # source decision refs as provenance rather than treating them as new approvals.
    proposals = list(proposal_records.values())
    alias_repair_targets = {row["proposed_canonical_id"] for row in alias_repairs}
    proposal_names: dict[tuple[str, str], set[str]] = defaultdict(set)
    for proposal in proposals:
        proposal_names[(normalize_name(proposal["brand"]), normalize_name(proposal["model"]))].add(proposal["canonical_id"])
    duplicate_names = {target_id for ids in proposal_names.values() if len(ids) > 1 for target_id in ids}
    # A candidate is safe for later governed materialization only when the brand
    # exists, no catalog alias must first be repaired, and the collision checks
    # preserved a single canonical model target. These remain non-authoritative.
    for proposal in proposals:
        hold_reasons = []
        if proposal["brand_record_status"] != "PRESENT_IN_SNAPSHOT":
            hold_reasons.append("BRAND_RECORD_CREATE_OR_RECONCILIATION_REQUIRED")
        if proposal["canonical_id"] in alias_repair_targets:
            hold_reasons.append("CATALOG_ALIAS_REPAIR_REQUIRED_BEFORE_CREATE")
        if proposal["canonical_id"] in duplicate_names:
            hold_reasons.append("DUPLICATE_CANONICAL_NAME_WITHOUT_GENERATION_EVIDENCE")
        if proposal["collision_check"] not in {"NO_EXACT_OR_ALIAS_COLLISION", "NO_EXISTING_SAME_BRAND_IDENTITY_OR_ALIAS"}:
            hold_reasons.append("CANONICAL_COLLISION_REVIEW_REQUIRED")
        proposal["candidate_safety"] = "REVIEW_HOLD" if hold_reasons else "SAFE_CANDIDATE"
        proposal["review_hold_reasons"] = hold_reasons
        proposal["canonical_granularity_check"] = (
            "OWNER_IDENTITY_LOCK_PRESERVED_AND_NO_ALIAS_COLLAPSE"
            if proposal["brand"].strip().upper() in IDENTITY_LOCK_BRANDS
            else "UNIQUE_CANONICAL_TARGET_WITHIN_BRAND"
        )
    for proposal in proposals:
        if proposal["candidate_safety"] == "REVIEW_HOLD":
            proposal["priority_rank"] = ""
            proposal["priority_registrations_cumulative"] = ""
            proposal["priority_tier"] = "HELD_PENDING_REVIEW"
    proposal_target_ids = {row["canonical_id"] for row in proposals}

    link_rows = []
    unresolved_rows = []
    eligible_rows = []
    category_units = Counter()
    category_groups = Counter()
    effective_link_units = 0
    scope_status_units = Counter()
    scope_status_counts = Counter()
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
                if group_id in source_unknown_groups:
                    reason = "UNIDENTIFIABLE_SOURCE_DATA: Ice model name is unspecified; units stay in denominator."
                elif group_id in scoped_pickup_groups:
                    reason = reason or "SCOPED_PICKUP_CLASS_NOT_RESOLVED"
                else:
                    proposal = proposal_by_group.get(group_id)
                    if proposal and proposal["candidate_target_id"] in proposal_target_ids:
                        resolution = {"canonical_id": proposal["target_id"], "name_en": proposal["candidate_name"],
                                      "brand_id": proposal["candidate"].get("brand_id") or "",
                                      "status": "UNKNOWN", "generation": None, "segment": None,
                                      "body_type": None, "powertrains": None}
                        target_id, match_kind = proposal["target_id"], "NEW_BASIC_IDENTITY_CANDIDATE"
                    else:
                        # A unique exact same-brand catalog match is safe evidence
                        # for non-split groups even if the historical scorer had no
                        # final disposition.
                        source_brand_id, _ = brand_id_for_source(value["brand"], brand_names)
                        _, source_identity_name = basic_identity_candidate(value["brand"], value["model"], source_brand_id)
                        exact, aliases = group_catalog_matches(value["brand"], source_identity_name, models, brand_names)
                        matches = exact or aliases
                        locked_alias = bool(aliases) and value["brand"].strip().upper() in IDENTITY_LOCK_BRANDS
                        if not locked_alias and len({x["canonical_id"] for x in matches}) == 1:
                            resolution, match_kind = matches[0], "UNIQUE_SAME_BRAND_EXACT" if exact else "UNIQUE_SAME_BRAND_ALIAS"
                            target_id = resolution["canonical_id"]
                        else:
                            reason = reason or disposition
            if resolution:
                fields = row_model_fields(resolution)
                if target_id in models:
                    link = {"model_group_id": group_id, "reg_type": row["reg_type"], "brand": value["brand"],
                            "ice_model_name": value["model"], "registrations": int(row["reg_count"]),
                            **raw_ice_classification([group_id], dimensions),
                            "canonical_id": target_id, **fields, "match_evidence": match_kind,
                            "decision_ref": row["decision_ref"], "source_disposition": disposition,
                            "mapping_authority": "OFFLINE_MANIFEST_EVIDENCE_ONLY",
                            "source_package_sha256": EXPECTED_M7_SHA}
                    link_rows.append(link)
                    scope_results.append(("MATCH_EXISTING", row, target_id))
                else:
                    scope_results.append(("NEW_BASIC_IDENTITY_NEEDED", row, target_id))
                scope_status = scope_results[-1][0]
            else:
                unresolved_entry = {"model_group_id": group_id, "reg_type": row["reg_type"],
                                       "brand": value["brand"], "ice_model_name": value["model"],
                                       **raw_ice_classification([group_id], dimensions),
                                       "registrations": int(row["reg_count"]), "evidence_status": "UNRESOLVED_EVIDENCE",
                                       "reason": reason or disposition, "shadow_disposition": disposition,
                                       "candidate_target_id": target_id,
                                       "decision_ref": row["decision_ref"],
                                       "source_package_sha256": EXPECTED_M7_SHA}
                unresolved_rows.append(unresolved_entry)
                scope_results.append(("UNRESOLVED_EVIDENCE", row, ""))
                scope_status = "UNRESOLVED_EVIDENCE"
            scope_status_counts[scope_status] += 1
            scope_status_units[scope_status] += int(row["reg_count"])
            matched_scope = next((entry for entry in link_rows if entry["model_group_id"] == group_id
                                  and entry["reg_type"] == row["reg_type"]), None)
            new_candidate = proposal_by_group.get(group_id) if scope_status == "NEW_BASIC_IDENTITY_NEEDED" else None
            candidate_record = proposal_records.get(new_candidate["target_id"]) if new_candidate else None
            scope_rows.append({
                "model_group_id": group_id, "reg_type": row["reg_type"], "brand": value["brand"],
                "ice_model_name": value["model"], "registrations": int(row["reg_count"]),
                **raw_ice_classification([group_id], dimensions),
                "eligibility": "ELIGIBLE", "disposition": scope_status,
                "disposition_detail": ("UNIDENTIFIABLE_SOURCE_DATA" if group_id in source_unknown_groups else
                    "EXISTING_CANONICAL_IDENTITY" if scope_status == "MATCH_EXISTING" else
                    "BASIC_IDENTITY_CANDIDATE_REQUIRES_GOVERNED_WRITER" if scope_status == "NEW_BASIC_IDENTITY_NEEDED" else
                    "ACTIONABLE_EVIDENCE_OR_OWNER_AUTHORIZATION_REQUIRED"),
                "canonical_id": matched_scope["canonical_id"] if matched_scope else
                    (new_candidate["target_id"] if new_candidate else ""),
                "materialization_review": candidate_record["candidate_safety"] if candidate_record else
                    ("EXISTING_IDENTITY_CANDIDATE" if scope_status == "MATCH_EXISTING" else "UNRESOLVED"),
                "priority_tier": "",
                "approval_state": "OFFLINE_CANDIDATE_ONLY" if scope_status in {"MATCH_EXISTING", "NEW_BASIC_IDENTITY_NEEDED"} else "UNRESOLVED",
                "reason": unresolved_rows[-1]["reason"] if scope_status == "UNRESOLVED_EVIDENCE" else
                    (matched_scope["match_evidence"] if matched_scope else "Basic identity proposal; not an approved writer instruction."),
                "decision_ref": row["decision_ref"], "source_package_sha256": EXPECTED_M7_SHA,
            })
        states = {item[0] for item in scope_results}
        if states == {"MATCH_EXISTING"}:
            category = "MATCH_EXISTING"
        elif "UNRESOLVED_EVIDENCE" in states and len(states) > 1:
            category = "PARTIALLY_MAPPED"
        elif states == {"UNRESOLVED_EVIDENCE"}:
            category = "UNRESOLVED_EVIDENCE"
        elif "NEW_BASIC_IDENTITY_NEEDED" in states:
            category = "NEW_BASIC_IDENTITY_NEEDED"
        else:
            category = "PARTIALLY_MAPPED"
        category_groups[category] += 1
        category_units[category] += value["units"]
        effective_link_units += sum(int(row["reg_count"]) for state, row, _ in scope_results if state == "MATCH_EXISTING")
        candidate_refs = sorted({
            item.get("decision_ref") or "" for item in group_scopes if item.get("decision_ref")
        } | {f"owner_decision:{d['decision_id']}" for d in ledger_by_group.get(group_id, [])})
        linked_ids = sorted({item[2] for item in scope_results if item[2]})
        eligible_rows.append({"model_group_id": group_id, "brand": value["brand"], "ice_model_name": value["model"],
                              **raw_ice_classification([group_id], dimensions),
                              "ice_brand_values": dict(sorted(value["brands"].items())),
                              "registrations": value["units"], "registrations_by_reg_type": dict(sorted(value["classes"].items())),
                              "identity_status": category, "canonical_identity_ids": linked_ids,
                              "source_references": candidate_refs,
                              "frozen_owner_decision_refs": [d["decision_id"] for d in ledger_by_group.get(group_id, [])],
                              "owner_decisions_changed": False, "source_package_sha256": EXPECTED_M7_SHA})

    # Re-rank against the actual class-scope result, so P0 means these safe
    # candidates are needed to cross 99.1% weighted identity readiness.
    denominator_for_priority = sum(by_group[group]["units"] for group in eligible_ids)
    target_units = (denominator_for_priority * 991 + 999) // 1000
    additional_units_for_target = max(0, target_units - scope_status_units["MATCH_EXISTING"])
    safe_order = sorted((p for p in proposals if p["candidate_safety"] == "SAFE_CANDIDATE"),
                        key=lambda p: (-int(p["registration_units"]), p["canonical_id"]))
    cumulative = 0
    for rank, proposal in enumerate(safe_order, 1):
        proposal["priority_rank"] = rank
        proposal["priority_registrations_cumulative"] = cumulative + int(proposal["registration_units"])
        proposal["priority_tier"] = "P0_99_1_COVERAGE_TARGET" if cumulative < additional_units_for_target else "P1_AFTER_TARGET"
        cumulative += int(proposal["registration_units"])
    priority_by_id = {row["canonical_id"]: row["priority_tier"] for row in proposals}
    for row in scope_rows:
        row["priority_tier"] = priority_by_id.get(row["canonical_id"], "")

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
    if sum(scope_status_units.values()) != effective_units:
        raise ValueError("Eligible per-scope classifications do not reconcile to the effective denominator")
    all_scope_units = sum(int(row["reg_count"]) for rows in shadow_by_group.values() for row in rows)
    if len(scope_rows) != len(shadow) or sum(row["registrations"] for row in scope_rows) != original_units:
        raise ValueError("Final per-scope manifest does not reconcile to all original M7.0 scopes and units")
    baseline_keys = {(row["model_group_id"], row["reg_type"]): int(row["registrations"])
                     for row in unresolved_baseline}
    final_scope_by_key = {(row["model_group_id"], row["reg_type"]): row for row in scope_rows}
    if len(baseline_keys) != 59 or sum(baseline_keys.values()) != 8_638:
        raise ValueError("Frozen starting unresolved evidence must remain 59 scopes / 8,638 registrations")
    if not set(baseline_keys) <= set(final_scope_by_key):
        raise ValueError("A scope from the starting unresolved file is missing in the final manifest")
    if any(baseline_keys[key] != final_scope_by_key[key]["registrations"] for key in baseline_keys):
        raise ValueError("Starting unresolved scope registration units changed during recovery")
    baseline_recovery_counts = Counter(final_scope_by_key[key]["disposition"] for key in baseline_keys)
    baseline_recovery_units = Counter()
    for key, units in baseline_keys.items():
        baseline_recovery_units[final_scope_by_key[key]["disposition"]] += units

    csv_write(output_dir / "eligible_model_groups.csv", ["model_group_id", "brand", "ice_brand_values", "ice_model_name", "ice_source_segment", "ice_source_body_type", "registrations",
              "registrations_by_reg_type", "identity_status", "canonical_identity_ids", "source_references",
              "frozen_owner_decision_refs", "owner_decisions_changed", "source_package_sha256"], eligible_rows)
    csv_write(output_dir / "excluded_model_groups.csv", ["model_group_id", "brand", "ice_brand_values", "ice_model_name", "ice_source_segment", "ice_source_body_type", "registrations_removed",
              "exclusion_reasons", "registrations_by_reg_type", "evidence_refs", "source_package_sha256"], excluded_rows)
    csv_write(output_dir / "existing_identity_links.csv", ["model_group_id", "reg_type", "brand", "ice_model_name", "ice_source_segment", "ice_source_body_type", "registrations",
              "canonical_id", "catalog_brand_id", "catalog_model_name", "catalog_generation", "lifecycle_status", "segment",
              "body_type", "powertrains", "match_evidence", "decision_ref", "source_disposition", "mapping_authority",
              "source_package_sha256"], link_rows)
    csv_write(output_dir / "new_basic_identity_proposals.csv", ["canonical_id", "brand_id", "brand_record_status", "brand", "model", "generation", "lifecycle_status",
              "segment", "body_type", "powertrain", "ice_source_segment", "ice_source_body_type",
              "ice_source_classification_evidence", "candidate_safety", "review_hold_reasons", "canonical_granularity_check", "priority_rank",
              "priority_registrations_cumulative", "priority_tier", "source_references", "ice_model_group_ids", "registration_units",
              "source_reg_type_scopes", "collision_check", "proposal_status", "writer_dependency", "source_package_sha256",
              "vehicle_master_snapshot_sha256"], proposals)
    csv_write(output_dir / "unresolved_identity_evidence.csv", ["model_group_id", "reg_type", "brand", "ice_model_name", "ice_source_segment", "ice_source_body_type", "registrations",
              "evidence_status", "reason", "shadow_disposition", "candidate_target_id", "decision_ref", "source_package_sha256"],
              unresolved_rows)
    residual_rows = []
    for row in unresolved_rows:
        reason = row["reason"]
        if reason.startswith("UNIDENTIFIABLE_SOURCE_DATA"):
            next_evidence = "Corrected Ice model identity for this registration class; source units remain in denominator until then."
            blocker = "SOURCE_IDENTITY_MISSING"
        elif row["shadow_disposition"] == "EXISTING_CROSSWALK_PROPOSED":
            next_evidence = "Class-specific source proof or explicit owner authorization for the preserved proposed target."
            blocker = "LEGACY_SCOPE_TARGET_UNAPPROVED"
        else:
            next_evidence = "Evidence naming the actual cab/body identity for this registration class; no parent or adjacent-class fallback."
            blocker = "PICKUP_CLASS_TARGET_UNPROVEN"
        residual_rows.append({**row, "blocker_type": blocker, "next_evidence_or_authorization": next_evidence,
                              "included_in_effective_denominator": True, "counts_as_canonical_mapping": False})
    csv_write(output_dir / "residual_exceptions.csv", ["model_group_id", "reg_type", "brand", "ice_model_name",
              "registrations", "blocker_type", "reason", "next_evidence_or_authorization",
              "included_in_effective_denominator", "counts_as_canonical_mapping", "decision_ref",
              "source_package_sha256"], residual_rows)
    scope_rows.sort(key=lambda row: (row["model_group_id"], row["reg_type"]))
    csv_write(output_dir / "final_scope_dispositions.csv", ["model_group_id", "reg_type", "brand", "ice_model_name", "ice_source_segment", "ice_source_body_type",
              "registrations", "eligibility", "disposition", "disposition_detail", "canonical_id", "approval_state",
              "materialization_review", "priority_tier", "reason", "decision_ref", "source_package_sha256"], scope_rows)
    csv_write(output_dir / "identity_alias_repair_proposals.csv", ["source_model_group_id", "source_model_name",
              "existing_canonical_id", "existing_canonical_name", "alias_to_remove", "proposed_canonical_id",
              "proposed_model_name", "repair_reason", "repair_status", "registration_units", "owner_decision_changed",
              "source_package_sha256"], sorted(alias_repairs, key=lambda row: (row["source_model_group_id"], row["alias_to_remove"])))

    output_files = ["eligible_model_groups.csv", "excluded_model_groups.csv", "existing_identity_links.csv",
                    "new_basic_identity_proposals.csv", "unresolved_identity_evidence.csv",
                    "final_scope_dispositions.csv", "identity_alias_repair_proposals.csv",
                    "residual_exceptions.csv"]

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
                             "original_owner_overlay.csv": EXPECTED_OVERLAY_SHA,
                             "unresolved_identity_evidence_baseline_59.csv": UNRESOLVED_BASELINE_SHA},
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
        "identity_classification": {"group_rollup_counts": dict(sorted(category_groups.items())),
                                    "scope_counts": dict(sorted(scope_status_counts.items())),
                                    "scope_registration_units": dict(sorted(scope_status_units.items())),
                                    "eligible_group_count_reconciled": sum(category_groups.values()) == len(eligible_ids),
                                    "eligible_scope_registration_units_reconciled": sum(scope_status_units.values()) == effective_units,
                                    "starting_unresolved_59_scope_recovery": {"scope_count": len(baseline_keys),
                                        "registration_units": sum(baseline_keys.values()),
                                        "final_scope_dispositions": dict(sorted(baseline_recovery_counts.items())),
                                        "final_registration_units_by_disposition": dict(sorted(baseline_recovery_units.items())),
                                        "resolved_scope_count": sum(v for k, v in baseline_recovery_counts.items() if k != "UNRESOLVED_EVIDENCE"),
                                        "resolved_registration_units": sum(v for k, v in baseline_recovery_units.items() if k != "UNRESOLVED_EVIDENCE")},
                                    "existing_link_scope_rows": len(link_rows), "unresolved_scope_rows": len(unresolved_rows),
                                    "source_unidentifiable_scope_count": sum(1 for row in scope_rows if row["eligibility"] == "ELIGIBLE" and row["disposition_detail"] == "UNIDENTIFIABLE_SOURCE_DATA"),
                                    "source_unidentifiable_registrations": sum(row["registrations"] for row in scope_rows if row["eligibility"] == "ELIGIBLE" and row["disposition_detail"] == "UNIDENTIFIABLE_SOURCE_DATA"),
                                    "actionable_unresolved_registrations": sum(row["registrations"] for row in unresolved_rows if not row["reason"].startswith("UNIDENTIFIABLE_SOURCE_DATA")),
                                    "registration_weighted_readiness_simulation": {"existing_identity_candidate_registrations": scope_status_units["MATCH_EXISTING"],
                                        "new_basic_identity_candidate_registrations": scope_status_units["NEW_BASIC_IDENTITY_NEEDED"],
                                        "simulated_candidate_ready_registrations": scope_status_units["MATCH_EXISTING"] + scope_status_units["NEW_BASIC_IDENTITY_NEEDED"],
                                        "effective_denominator": effective_units,
                                        "simulated_candidate_ready_pct": round(100 * (scope_status_units["MATCH_EXISTING"] + scope_status_units["NEW_BASIC_IDENTITY_NEEDED"]) / effective_units, 6),
                                        "unresolved_including_unidentifiable_registrations": scope_status_units["UNRESOLVED_EVIDENCE"]},
                                    "production_approved_servable": {"gate": "BLOCKED_R6_PRODUCTION_CROSSWALK_ALLOWED_FALSE",
                                        "newly_approved_or_servable_registrations_from_this_manifest": 0,
                                        "prior_full_m7_read_only_baseline": {"approved_plus_retained_auto_registrations": 3976556,
                                            "fixed_full_m7_denominator": 4141987, "coverage_pct": 96.006,
                                            "source": "qa/acceptance_report.md; not recalculated on the filtered denominator"},
                                        "coverage_claim": "No offline candidate is counted as production approved or servable; see the frozen R6 acceptance baseline separately."},
                                    "crosswalk_coverage": {"existing_identity_registrations": effective_link_units,
                                        "effective_denominator": effective_units,
                                        "existing_identity_pct": round(100 * effective_link_units / effective_units, 6),
                                        "classified_with_existing_or_new_identity_registrations": scope_status_units["MATCH_EXISTING"] + scope_status_units["NEW_BASIC_IDENTITY_NEEDED"],
                                        "classified_identity_pct": round(100 * (scope_status_units["MATCH_EXISTING"] + scope_status_units["NEW_BASIC_IDENTITY_NEEDED"]) / effective_units, 6),
                                        "unresolved_registrations": scope_status_units["UNRESOLVED_EVIDENCE"]}},
        "identity_proposals": {"filtered_shadow_identity_groups": sum(1 for x in target_rows if x["model_group_id"] in eligible_ids),
                               "filtered_shadow_identity_units": sum(by_group[x["model_group_id"]]["units"] for x in target_rows if x["model_group_id"] in eligible_ids),
                               "candidate_proposal_count_after_catalog_collision_checks": len(proposals),
                               "safe_candidate_count": sum(row["candidate_safety"] == "SAFE_CANDIDATE" for row in proposals),
                               "safe_candidate_registrations": sum(int(row["registration_units"]) for row in proposals if row["candidate_safety"] == "SAFE_CANDIDATE"),
                               "review_hold_count": sum(row["candidate_safety"] == "REVIEW_HOLD" for row in proposals),
                               "review_hold_registrations": sum(int(row["registration_units"]) for row in proposals if row["candidate_safety"] == "REVIEW_HOLD"),
                               "duplicate_name_without_generation_review_count": len(duplicate_names),
                               "p0_99_1_coverage_target_candidate_count": sum(row["priority_tier"] == "P0_99_1_COVERAGE_TARGET" for row in proposals),
                               "p0_99_1_coverage_target_registrations": sum(int(row["registration_units"]) for row in proposals if row["priority_tier"] == "P0_99_1_COVERAGE_TARGET"),
                               "weighted_coverage_target_pct": 99.1,
                               "weighted_coverage_target_registrations": target_units,
                               "existing_identity_candidate_registrations": scope_status_units["MATCH_EXISTING"],
                               "simulated_existing_plus_p0_registrations": scope_status_units["MATCH_EXISTING"] + sum(int(row["registration_units"]) for row in proposals if row["priority_tier"] == "P0_99_1_COVERAGE_TARGET"),
                               "simulated_existing_plus_p0_pct": round(100 * (scope_status_units["MATCH_EXISTING"] + sum(int(row["registration_units"]) for row in proposals if row["priority_tier"] == "P0_99_1_COVERAGE_TARGET")) / effective_units, 6),
                               "safe_candidates_alone_can_reach_99_1": scope_status_units["MATCH_EXISTING"] + sum(int(row["registration_units"]) for row in proposals if row["candidate_safety"] == "SAFE_CANDIDATE") >= target_units,
                               "classification_authority": {"canonical_segment_and_body_type": "Vehicle Master snapshot only; UNKNOWN for proposed identities absent from the catalog", "ice_segment_and_body_type": "raw source evidence only"},
                               "new_basic_identity_candidate_scope_registrations": scope_status_units["NEW_BASIC_IDENTITY_NEEDED"],
                               "duplicate_canonical_targets_after_coalescing": 0,
                               "candidate_target_conflicts_requiring_resolution": len(candidate_issue),
                               "identity_alias_repair_proposals": len(alias_repairs),
                               "proposals_with_unverified_brand_record": sum(1 for row in proposals if row.get("brand_record_status") != "PRESENT_IN_SNAPSHOT"),
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
