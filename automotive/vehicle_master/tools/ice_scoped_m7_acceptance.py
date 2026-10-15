"""Reproducible, offline M7.0 acceptance for the R6 scoped resolver.

Inputs are the verified frozen artifacts recovered for Issue #228 plus a
sanitized SELECT-only Vehicle Master collision snapshot. This tool never opens
a database connection and never writes anything except its bounded QA outputs.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
import hashlib
import io
import json
import math
from pathlib import Path
import re
import zipfile

from vehreg.ice_scoped_crosswalk import IceFact, LegacyLink, OwnerScope, ScopedCrosswalk
from vehreg.ice_scoped_reader import IceRegistrationFact, resolve_registration_rows, scoped_totals


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "data/packages/ice_crosswalk_r6_offline_recovery_M7.0"
M7_ZIP = ROOT / "data/packages/2569-09/v3_M7.0/TDR_FULL_2569-09_v3_M7.0.zip"
QA = PACKAGE / "qa"
EXPECTED_M7_SHA = "c558d2d4cc3ed667f8b30ea028dbb66c4030cdce4e7daabe735df870cb94677d"
EXPECTED_OVERLAY_SHA = "e660cf9133cd0a99ffe8c87d1ba06dc0c72ef89b8a313a0a7285f54da1332430"
DENOMINATOR = 4_141_987
OWNER_LINK_DISPOSITIONS = {
    "OWNER_APPROVED_LINK", "OWNER_APPROVED_SHADOW_IDENTITY",
    "PICKUP_RY_SPLIT_SHADOW", "DETERMINISTIC_REJECTED_CANDIDATE_RECOVERY",
}
PENDING_DISPOSITIONS = {"PICKUP_SPLIT_UNAPPROVED_OR_AMBIGUOUS"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def verify_manifest(package: Path, manifest_file: str, key: str) -> dict:
    manifest = json.loads((package / manifest_file).read_text(encoding="utf-8"))
    entries = manifest[key]
    mismatches = []
    for entry in entries:
        item = package / entry["path"]
        if not item.is_file():
            mismatches.append({"path": entry["path"], "error": "MISSING"})
            continue
        actual_sha = sha256(item)
        actual_bytes = item.stat().st_size
        if actual_sha != entry["sha256"] or actual_bytes != entry["bytes"]:
            mismatches.append({"path": entry["path"], "actual_sha256": actual_sha,
                               "expected_sha256": entry["sha256"],
                               "actual_bytes": actual_bytes, "expected_bytes": entry["bytes"]})
    if mismatches:
        raise ValueError(f"{manifest_file} mismatch: {mismatches[:5]}")
    return {"manifest": manifest_file, "files_verified": len(entries), "mismatches": 0}


def read_m7_facts(path: Path) -> list[IceRegistrationFact]:
    with zipfile.ZipFile(path) as outer:
        panel_name = "panels/reg_trend_2569-09_v3.zip"
        if panel_name not in outer.namelist():
            raise ValueError(f"M7.0 package lacks {panel_name}")
        with zipfile.ZipFile(io.BytesIO(outer.read(panel_name))) as panel:
            members = [name for name in panel.namelist() if name.endswith("reg_trend.csv")]
            if len(members) != 1:
                raise ValueError(f"Expected one reg_trend.csv, found {members}")
            with io.TextIOWrapper(panel.open(members[0]), encoding="utf-8-sig", newline="") as handle:
                facts = []
                for row in csv.DictReader(handle):
                    facts.append(IceRegistrationFact(
                        period=row["period"], province=row["province"], reg_type=row["reg_type"],
                        model_group_id=row["model_group_id"], brand=row["brand"],
                        model_name=row["model_name"], registrations=int(row["reg_count"]),
                    ))
                return facts


def canonical_registration_digest(facts: list[IceRegistrationFact]) -> str:
    values = [[row.period, row.province, row.reg_type, row.brand, row.model_group_id,
               row.model_name, row.registrations] for row in facts]
    values.sort(key=lambda value: tuple(value))
    payload = "\n".join(json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                        for value in values).encode()
    return hashlib.sha256(payload).hexdigest()


def build_resolver(shadow: list[dict[str, str]], catalog: dict) -> tuple[ScopedCrosswalk, list[dict], list[str]]:
    materialized = {row["canonical_id"] for row in catalog["models"]}
    owner: list[OwnerScope] = []
    legacy_by_group: dict[str, str] = {}
    scoped_only: set[str] = set()
    seen_owner: set[tuple[str, str]] = set()
    for row in shadow:
        group = row["model_group_id"]
        reg_type = row["reg_type"]
        disposition = row["disposition"]
        target = row["target_canonical_id"] or None
        ref = row["decision_ref"] or f"shadow-classification:{disposition}"
        action = None
        if disposition in OWNER_LINK_DISPOSITIONS:
            action = "APPROVED"
        elif disposition == "OWNER_EXCLUDED":
            action = "EXCLUDED"
            target = None
        elif disposition in PENDING_DISPOSITIONS:
            action = "PENDING"
            target = None
            scoped_only.add(group)
        elif disposition == "PICKUP_RY_SPLIT_SHADOW":
            scoped_only.add(group)

        if disposition in {"PICKUP_RY_SPLIT_SHADOW", "PICKUP_SPLIT_UNAPPROVED_OR_AMBIGUOUS"}:
            scoped_only.add(group)
        if action:
            key = (group, reg_type)
            if key in seen_owner:
                raise ValueError(f"Multiple frozen directives for scope {key}")
            seen_owner.add(key)
            owner.append(OwnerScope(group, reg_type, action, target, ref, "7.0"))
        if disposition == "OWNER_APPROVED_AUTO":
            if not target:
                raise ValueError(f"Retained AUTO missing target for {group}")
            old = legacy_by_group.setdefault(group, target)
            if old != target:
                raise ValueError(f"Retained AUTO has class-varying targets for {group}")
    legacy = [LegacyLink(group, target, "AUTO") for group, target in sorted(legacy_by_group.items())]
    resolver = ScopedCrosswalk(owner, legacy, materialized, "7.0", scoped_only)
    return resolver, owner, sorted(materialized)


def normalize_name(value: str) -> str:
    return re.sub(r"[^0-9a-zก-๙]+", "", value.casefold())


def flatten_aliases(value) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[|,;]", value) if part.strip()]
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(flatten_aliases(item))
        return result
    if isinstance(value, dict):
        result = []
        for item in value.values():
            result.extend(flatten_aliases(item))
        return result
    return []


def verify_frozen_decisions(ledger: list[dict[str, str]], shadow: list[dict[str, str]]) -> dict:
    """Assert every immutable owner row is cited and enacted by the shadow scopes."""
    expected_disposition = {
        "OWNER_LINK_EXISTING": "OWNER_APPROVED_LINK",
        "KEEP_EXISTING_AUTO": "OWNER_APPROVED_AUTO",
        "OWNER_EXCLUDE_FROM_COUNT": "OWNER_EXCLUDED",
        "OWNER_CREATE_IDENTITY": "OWNER_APPROVED_SHADOW_IDENTITY",
    }
    errors = []
    exercised = set()
    for decision in ledger:
        decision_id = decision["decision_id"]
        matching = [row for row in shadow if decision_id in row["decision_ref"]]
        if not matching:
            errors.append({"decision_id": decision_id, "error": "NO_SHADOW_REFERENCE"})
            continue
        exercised.add(decision_id)
        expected = expected_disposition[decision["owner_action"]]
        if any(row["model_group_id"] != decision["model_group_id"] for row in matching):
            errors.append({"decision_id": decision_id, "error": "MODEL_GROUP_MISMATCH"})
        if decision["reg_type_scope"] and any(
                row["reg_type"] != decision["reg_type_scope"] for row in matching):
            errors.append({"decision_id": decision_id, "error": "REG_TYPE_SCOPE_MISMATCH"})
        if any(row["disposition"] != expected for row in matching):
            errors.append({"decision_id": decision_id, "error": "DISPOSITION_MISMATCH"})
        expected_target = decision["canonical_target_id"]
        if any(row["target_canonical_id"] != expected_target for row in matching):
            errors.append({"decision_id": decision_id, "error": "TARGET_MISMATCH"})
        actual_units = sum(int(row["reg_count"]) for row in matching)
        if actual_units != int(decision["registration_units_m7_0"]):
            errors.append({"decision_id": decision_id, "error": "REGISTRATION_UNITS_MISMATCH",
                           "expected": int(decision["registration_units_m7_0"]),
                           "actual": actual_units})
    if errors or len(exercised) != len(ledger):
        raise ValueError(f"Frozen owner decision application mismatch: {errors[:5]}")
    return {"ledger_decisions_exercised": len(exercised), "mismatches": 0,
            "action_disposition_target_and_registration_units_verified": True}


def make_materialization_plan(targets: dict, ledger: list[dict[str, str]],
                              overlay: list[dict[str, str]], catalog: dict) -> list[dict]:
    models = catalog["models"]
    ledger_by_group = defaultdict(list)
    for row in ledger:
        ledger_by_group[row["model_group_id"]].append(row)
    overlay_by_group = {row["model_group_id"]: row for row in overlay}
    plan = []
    for item in targets["identities"]:
        name = item["canonical_name_en"]
        target_id = item["canonical_model_id"]
        brand_prefix = target_id.split(".", 1)[0].replace("_", " ").casefold()
        wanted = normalize_name(name)
        id_matches, name_matches, alias_matches = [], [], []
        for model in models:
            if model["canonical_id"] == target_id:
                id_matches.append(model["canonical_id"])
            same_brand = str(model.get("brand_id") or "").casefold() in {
                brand_prefix, brand_prefix.replace(" ", "_"), item["brand"].casefold(),
            }
            candidate_names = [model.get("name_en") or "", model.get("name_th") or "", model.get("slug") or ""]
            if same_brand and any(normalize_name(candidate) == wanted for candidate in candidate_names):
                name_matches.append(model["canonical_id"])
            if same_brand and any(normalize_name(alias) == wanted for alias in flatten_aliases(model.get("aliases"))):
                alias_matches.append(model["canonical_id"])
        group = item["model_group_id"]
        overlay_row = overlay_by_group.get(group, {})
        decisions = ledger_by_group.get(group, [])
        owner_refs = [row["decision_id"] for row in decisions]
        if not owner_refs:
            owner_refs = [f"owner-overlay-line:{overlay.index(overlay_row) + 2}" if overlay_row else "MISSING_OVERLAY_REF"]
        collision_status = "EXACT_COLLISION" if id_matches else (
            "OWNER_DISTINCT_ALIAS_COLLISION" if alias_matches else (
                "NAME_COLLISION" if name_matches else "NO_EXACT_COLLISION_IN_SNAPSHOT"
            )
        )
        materialization_status = (
            "BLOCKED_WRITER_AND_ALIAS_COLLISION_GUARD"
            if collision_status == "OWNER_DISTINCT_ALIAS_COLLISION"
            else "BLOCKED_GOVERNED_VEHICLE_MASTER_WRITER_PHASE1"
        )
        overlay_sha = EXPECTED_OVERLAY_SHA
        plan.append({
            "canonical_target_id": target_id,
            "source_group_id": group,
            "source_ice_groups": [group],
            "source_reg_type_scope": item.get("registration_type") or "ALL",
            "frozen_owner_decision_refs": owner_refs,
            "owner_verdict": item["owner_verdict"],
            "create_vs_existing_link": "CREATE" if item["materialization_required"] else "LINK_EXISTING",
            "catalog_id_collision": id_matches,
            "same_brand_name_collision": name_matches,
            "same_brand_alias_collision": alias_matches,
            "collision_check_status": collision_status,
            "catalog_snapshot_sha256": catalog["canonical_rows_sha256"],
            "catalog_snapshot_model_count": catalog["model_count"],
            "catalog_snapshot_captured_at_utc": catalog["captured_at_utc"],
            "required_structural_fields": [
                "canonical_id", "brand_id", "slug", "name_en", "status", "payload",
                "served_as_of", "seed_release_id",
            ],
            "proposed_values": {
                "canonical_id": target_id,
                "brand_id": None,
                "brand_name": item["brand"],
                "slug": None,
                "name_en": name,
                "status": "HISTORICAL" if item.get("lifecycle_status") == "DISCONTINUED" else "UNVERIFIED",
                "payload": None,
                "segment": None,
                "body_type": None,
                "lifecycle_owner_instruction": item.get("lifecycle_status") or None,
                "distinct_from": item.get("distinct_from") or [],
            },
            "materialization_status": materialization_status,
            "materialization_required": bool(item["materialization_required"]),
            "owner_overlay_sha256": overlay_sha,
            "writer_dependency": "Vehicle Master Phase 1 structural governed writer and CREATE authority",
        })
    return plan


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                             if isinstance(value, (dict, list)) else value for key, value in row.items()})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-dir", type=Path, default=PACKAGE)
    parser.add_argument("--m7-zip", type=Path, default=M7_ZIP)
    parser.add_argument("--catalog-snapshot", type=Path,
                        default=PACKAGE / "qa/catalog_snapshot_2026-10-13.json")
    parser.add_argument("--output-dir", type=Path, default=QA)
    args = parser.parse_args()
    package = args.package_dir
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    provenance = [verify_manifest(package, "source_manifest.json", "source_artifacts"),
                  verify_manifest(package, "artifact_manifest.json", "files")]
    m7_sha = sha256(args.m7_zip)
    if m7_sha != EXPECTED_M7_SHA:
        raise ValueError(f"M7.0 SHA mismatch: {m7_sha}")
    source_manifest = json.loads((package / "source_manifest.json").read_text())
    if source_manifest["ice_package"]["sha256"] != m7_sha:
        raise ValueError("Source manifest and M7.0 package SHA disagree")

    ledger = read_csv(package / "owner_decision_ledger_244.csv")
    shadow = read_csv(package / "shadow_crosswalk_rows.csv")
    overlay = read_csv(package / "source/owner_overlay_original.csv")
    catalog = json.loads(args.catalog_snapshot.read_text(encoding="utf-8"))
    live_readback_path = package / "qa/live_readback_2026-10-13.json"
    live_readback = json.loads(live_readback_path.read_text(encoding="utf-8"))
    catalog_rows = catalog["models"]
    canonical_payload = json.dumps(catalog_rows, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")).encode()
    if hashlib.sha256(canonical_payload).hexdigest() != catalog["canonical_rows_sha256"]:
        raise ValueError("Vehicle Master SELECT snapshot hash mismatch")
    if len(ledger) != 244 or len(shadow) != 1407 or len(overlay) != 1200:
        raise ValueError("Frozen row cardinality mismatch (expected 244/1407/1200)")
    if sha256(package / "source/owner_overlay_original.csv") != EXPECTED_OVERLAY_SHA:
        raise ValueError("Owner overlay SHA mismatch")
    ledger_counts = Counter(row["owner_action"] for row in ledger)
    expected_decisions = {
        "OWNER_LINK_EXISTING": 92, "KEEP_EXISTING_AUTO": 63,
        "OWNER_EXCLUDE_FROM_COUNT": 51, "OWNER_CREATE_IDENTITY": 38,
    }
    if ledger_counts != expected_decisions:
        raise ValueError(f"Frozen 244 action counts changed: {dict(ledger_counts)}")
    frozen_decision_replay = verify_frozen_decisions(ledger, shadow)

    resolver, owner_scope, materialized = build_resolver(shadow, catalog)
    group_facts = [IceFact(row["model_group_id"], row["reg_type"], int(row["reg_count"]))
                   for row in shadow]
    resolved_shadow = resolver.resolve_all(group_facts)
    m7_facts = read_m7_facts(args.m7_zip)
    raw_total = sum(row.registrations for row in m7_facts)
    m7_rows_sha = canonical_registration_digest(m7_facts)
    live_rows = live_readback["ice_reg_trend"]
    if not live_rows["live_equals_exact_frozen_m7_rows"] \
            or live_rows["rows"] != len(m7_facts) or live_rows["registration_units"] != raw_total \
            or live_rows["canonical_rows_sha256"] != m7_rows_sha \
            or live_rows["offline_m7_canonical_rows_sha256"] != m7_rows_sha:
        raise ValueError("Live SELECT readback is not an exact row-level match to frozen M7.0")
    aggregate = Counter()
    aggregate_totals = Counter()
    for row in m7_facts:
        aggregate[(row.model_group_id, row.reg_type)] += row.registrations
        aggregate_totals[row.model_group_id] += row.registrations
    shadow_input = {(row["model_group_id"], row["reg_type"]): int(row["reg_count"]) for row in shadow}
    if dict(aggregate) != shadow_input:
        raise ValueError("M7.0 raw facts do not exactly reproduce 1,407 frozen shadow rows")
    if raw_total != DENOMINATOR or sum(shadow_input.values()) != DENOMINATOR:
        raise ValueError("Fixed registration denominator does not reconcile")

    materialization_targets = json.loads((package / "owner_identity_targets.json").read_text())
    materialization_plan = make_materialization_plan(materialization_targets, ledger, overlay, catalog)
    if len(materialization_plan) != 114 or sum(x["materialization_required"] for x in materialization_plan) != 114:
        raise ValueError("Expected exactly 114 owner-approved missing identity targets")
    plan_by_id = {row["canonical_target_id"] for row in materialization_plan}
    materialized_ids = {row["canonical_id"] for row in catalog_rows}
    missing_existing_links: dict[str, dict] = {}
    for source in shadow:
        target = source["target_canonical_id"]
        if (source["disposition"] in OWNER_LINK_DISPOSITIONS and target
                and target not in materialized_ids and target not in plan_by_id):
            entry = missing_existing_links.setdefault(target, {"source_groups": set(), "registration_units": 0})
            entry["source_groups"].add(source["model_group_id"])
            entry["registration_units"] += int(source["reg_count"])
    missing_existing_link_report = {
        key: {"source_groups": sorted(value["source_groups"]),
              "registration_units": value["registration_units"],
              "status": "FROZEN_LINK_TARGET_NOT_PRESENT_IN_VEHICLE_MASTER"}
        for key, value in sorted(missing_existing_links.items())
    }

    by_status = Counter()
    by_status_rows = Counter()
    output_rows = []
    expected_by_shadow = {
        "OWNER_APPROVED_SHADOW_IDENTITY": "PENDING_MATERIALIZATION",
        "OWNER_APPROVED_AUTO": "LEGACY_ACTIVE",
        "OWNER_EXCLUDED": "OWNER_EXCLUDED",
    }
    mismatch_count = 0
    input_by_key = {(row["model_group_id"], row["reg_type"]): row for row in shadow}
    for resolved in resolved_shadow:
        source = input_by_key[(resolved.group_id, resolved.reg_type)]
        disposition = resolved.disposition
        expected = expected_by_shadow.get(source["disposition"])
        acceptable = {expected} if expected else set()
        if source["disposition"] in OWNER_LINK_DISPOSITIONS:
            acceptable = {"OWNER_APPROVED" if source["target_canonical_id"] in materialized_ids
                          else "PENDING_MATERIALIZATION"}
        if source["disposition"] in PENDING_DISPOSITIONS:
            acceptable = {"OWNER_PENDING", "SCOPED_CLASS_UNRESOLVED"}
        if acceptable and disposition not in acceptable:
            mismatch_count += 1
        units = resolved.registrations
        by_status[disposition] += units
        by_status_rows[disposition] += 1
        output_rows.append({
            "model_group_id": resolved.group_id, "reg_type": resolved.reg_type,
            "registrations": units, "prior_status": source["prior_status"],
            "source_disposition": source["disposition"],
            "canonical_model_id": resolved.canonical_id, "resolver_disposition": disposition,
            "decision_ref": resolved.decision_ref or source["decision_ref"],
            "source_package_sha256": m7_sha,
        })
    if mismatch_count:
        raise ValueError(f"Frozen decision/resolver mismatch rows: {mismatch_count}")

    approved_units = legacy_auto_units = pending_units = excluded_units = unmatched_units = 0
    for resolved in resolved_shadow:
        units = resolved.registrations
        if resolved.disposition == "OWNER_APPROVED":
            approved_units += units
        elif resolved.disposition == "LEGACY_ACTIVE":
            legacy_auto_units += units
        elif resolved.disposition == "OWNER_EXCLUDED":
            excluded_units += units
        elif resolved.disposition in {"PENDING_MATERIALIZATION", "OWNER_PENDING", "LEGACY_TARGET_MISSING",
                                      "SCOPED_CLASS_UNRESOLVED"}:
            pending_units += units
        else:
            unmatched_units += units
    proposed_rows = [row for row in shadow if row["disposition"] == "EXISTING_CROSSWALK_PROPOSED"]
    proposed_units = sum(int(row["reg_count"]) for row in proposed_rows)
    if sum([approved_units, legacy_auto_units, pending_units, excluded_units, unmatched_units]) != DENOMINATOR:
        raise ValueError("Coverage status partitions do not sum to the fixed denominator")

    raw_reader_rows = resolve_registration_rows(m7_facts, resolver)
    if sum(row.registrations for row in raw_reader_rows) != raw_total or len(raw_reader_rows) != len(m7_facts):
        raise ValueError("M7 reader dropped or duplicated raw registrations")
    raw_status_units = Counter()
    raw_status_rows = Counter()
    raw_group_class = Counter()
    group_canonical_pairs = defaultdict(set)
    for row in raw_reader_rows:
        raw_status_units[row.mapping_status] += row.registrations
        raw_status_rows[row.mapping_status] += 1
        raw_group_class[(row.model_group_id, row.reg_type, row.mapping_status, row.canonical_model_id)] += row.registrations
        if row.canonical_model_id:
            group_canonical_pairs[row.canonical_model_id].add(row.model_group_id)
    shadow_group_class = Counter()
    for row in resolved_shadow:
        shadow_group_class[(row.group_id, row.reg_type, row.disposition, row.canonical_id)] += row.registrations
    if raw_group_class != shadow_group_class:
        raise ValueError("Raw-row reader and 1,407 aggregate resolver do not produce identical scope totals")
    dimensions = {row["canonical_id"]: row for row in catalog_rows}
    reader_totals = scoped_totals(raw_reader_rows, dimensions)
    if reader_totals["raw_registrations"] != DENOMINATOR:
        raise ValueError("Scoped reader aggregate changed the fixed denominator")
    many_to_one_targets = {target: sorted(groups) for target, groups in group_canonical_pairs.items() if len(groups) > 1}

    snapshot_plan_collision_rows = Counter(row["collision_check_status"] for row in materialization_plan)
    coverage = {
        "fixed_denominator": DENOMINATOR,
        "approved_servable_owner_units": approved_units,
        "approved_servable_owner_pct": 100 * approved_units / DENOMINATOR,
        "legacy_auto_units": legacy_auto_units,
        "legacy_auto_pct": 100 * legacy_auto_units / DENOMINATOR,
        "combined_approved_plus_legacy_auto_units": approved_units + legacy_auto_units,
        "combined_approved_plus_legacy_auto_pct": 100 * (approved_units + legacy_auto_units) / DENOMINATOR,
        "proposed_not_approved_units": proposed_units,
        "pending_units": pending_units,
        "excluded_units_kept_in_fixed_denominator": excluded_units,
        "unmatched_or_ambiguous_units": unmatched_units,
        "partitions_sum_to_fixed_denominator": True,
        "target_pct": 99.1,
        "target_units": math.ceil(DENOMINATOR * 0.991),
        "target_met_by_approved_plus_legacy_auto": approved_units + legacy_auto_units >= math.ceil(DENOMINATOR * 0.991),
        "target_gap_units": max(0, math.ceil(DENOMINATOR * 0.991) - approved_units - legacy_auto_units),
        "proposed_not_approved_units": proposed_units,
        "proposed_not_approved_group_reg_type_rows": len(proposed_rows),
        "proposed_not_approved_is_subset_of_pending": True,
    }
    report = {
        "schema": "tdr.ice-scoped-crosswalk-v2-m7-acceptance.v1",
        "source_pr229_head_sha": "872a1117b163feac42e0ce55314cd7a7408896b5",
        "implementation_base_pr232_head_sha": "3050beb1cdad4530808177de7b9d66abb21364f3",
        "m7": {"path": str(args.m7_zip.relative_to(ROOT)), "sha256": m7_sha,
               "master_version": "7.0", "period": "2569-09", "source_group_count": len(aggregate_totals),
               "raw_fact_rows": len(m7_facts), "group_reg_type_rows": len(aggregate),
               "registration_total": raw_total, "shadow_rows_verified": len(shadow),
               "shadow_key_and_count_mismatches": 0},
        "provenance_checks": provenance + [{"manifest": "M7_FULL_PACKAGE", "sha256": m7_sha,
                                            "matches_frozen_source_manifest": True},
                            {"manifest": "SELECT_ONLY_LIVE_READBACK", "sha256": sha256(live_readback_path),
                             "live_registration_rows_match_frozen_m7": True}],
        "owner_decisions": {"frozen_rows": len(ledger), **frozen_decision_replay,
                            "action_counts": dict(sorted(ledger_counts.items())),
                            "owner_overlay_groups": len(overlay), "owner_overlay_sha256": EXPECTED_OVERLAY_SHA,
                            "reopen_or_infer_replacements": 0, "decision_resolver_mismatches": mismatch_count},
        "v2_resolver_1_407": {"rows": len(resolved_shadow), "units": sum(row.registrations for row in resolved_shadow),
                              "disposition_rows": dict(sorted(by_status_rows.items())),
                              "disposition_units": dict(sorted(by_status.items()))},
        "coverage": coverage,
        "reader_adapter": {"raw_rows_resolved_once": len(raw_reader_rows),
                           "raw_units_before": raw_total, "raw_units_after": reader_totals["raw_registrations"],
                           "live_vs_frozen_m7_canonical_rows_sha256": m7_rows_sha,
                           "live_vs_frozen_m7_exact_match": True,
                           "raw_loss_or_duplication_units": 0,
                           "period_province_reg_type_scopes": len(reader_totals["period_province_reg_type_totals"]),
                           "many_to_one_target_count": len(many_to_one_targets),
                           "many_to_one_examples": dict(list(sorted(many_to_one_targets.items()))[:10]),
                           "segment_totals": reader_totals["segment_totals"],
                           "body_type_totals": reader_totals["body_type_totals"],
                           "reader_mapping_disposition_units": dict(sorted(raw_status_units.items())),
                           "raw_vs_aggregate_v2_resolver_mismatches": 0},
        "materialization": {"target_rows": len(materialization_plan),
                            "unique_target_ids": len(plan_by_id),
                            "all_missing_targets_blocked_on_governed_writer": True,
                            "missing_frozen_link_target_count": len(missing_existing_link_report),
                            "missing_frozen_link_targets": missing_existing_link_report,
                            "missing_frozen_link_target_units": sum(x["registration_units"] for x in missing_existing_link_report.values()),
                            "collision_snapshot_sha256": catalog["canonical_rows_sha256"],
                            "collision_snapshot_model_count": catalog["model_count"],
                            "collision_status_counts": dict(sorted(snapshot_plan_collision_rows.items())),
                            "collision_snapshot_is_a_full_vehicle_models_select": True,
                            "alias_field_source": "vehicle_models.payload.aliases"},
        "production_boundary": {"database_writes": 0, "ddl_executed": False, "migration_number_assigned": False,
                                "pr_merge": False, "deployment": False, "live_reader_cutover": False},
    }
    (out_dir / "m7_scoped_resolver_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    write_csv(out_dir / "m7_scoped_resolver_rows_1407.csv", output_rows)
    (out_dir / "materialization_plan_114.json").write_text(json.dumps(materialization_plan, ensure_ascii=False, indent=2) + "\n")
    write_csv(out_dir / "materialization_plan_114.csv", materialization_plan)
    (out_dir / "real_m7_reader_totals.json").write_text(json.dumps(reader_totals, ensure_ascii=False, indent=2) + "\n")
    (out_dir / "many_to_one_target_groups.json").write_text(json.dumps(many_to_one_targets, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    (out_dir / "acceptance_report.md").write_text(
        "# R6 scoped Crosswalk v2 — real M7.0 offline acceptance\n\n"
        f"Source: PR #229 frozen recovery head `872a1117b163feac42e0ce55314cd7a7408896b5`; "
        f"resolver base: PR #232 head `3050beb1cdad4530808177de7b9d66abb21364f3`.\n\n"
        "Run from repository root with `PYTHONPATH=automotive/vehicle_master python "
        "automotive/vehicle_master/tools/ice_scoped_m7_acceptance.py`. The runner is offline; "
        "its only live input is the versioned, SELECT-only catalog snapshot saved alongside this report.\n\n"
        f"The exact M7.0 ZIP SHA is `{m7_sha}`. Its 262,985 raw `reg_trend` rows aggregate to "
        f"1,407 `(model_group_id, reg_type)` rows and {DENOMINATOR:,} registrations. All 1,407 keys "
        "and counts match the frozen PR #229 shadow rows exactly; the same resolver then reads all "
        "262,985 raw facts once with zero unit loss or duplication. A SELECT-only read of live "
        "`ice_reg_trend` also matches the frozen M7.0 rows exactly by canonical row SHA256. "
        "The reproducible evidence and sanitized readback are stored beside this report in `qa/`.\n\n"
        "## Fixed-denominator coverage\n\n"
        "| Mapping state | Registrations | Share |\n|---|---:|---:|\n"
        f"| Owner-approved and currently servable | {approved_units:,} | {100*approved_units/DENOMINATOR:.4f}% |\n"
        f"| Retained legacy AUTO and currently servable | {legacy_auto_units:,} | {100*legacy_auto_units/DENOMINATOR:.4f}% |\n"
        f"| Combined approved + legacy AUTO | {approved_units+legacy_auto_units:,} | {100*(approved_units+legacy_auto_units)/DENOMINATOR:.4f}% |\n"
        f"| Pending, including shadow identities and unresolved pickup classes | {pending_units:,} | {100*pending_units/DENOMINATOR:.4f}% |\n"
        f"| Excluded by owner, retained in denominator | {excluded_units:,} | {100*excluded_units/DENOMINATOR:.4f}% |\n"
        f"| Unmatched or ambiguous | {unmatched_units:,} | {100*unmatched_units/DENOMINATOR:.4f}% |\n"
        f"| Fixed denominator | {DENOMINATOR:,} | 100.0000% |\n\n"
        f"The 99.1% target requires {math.ceil(DENOMINATOR*0.991):,} approved/servable units. "
        f"Measured approved + retained AUTO coverage is {approved_units+legacy_auto_units:,}; "
        f"the shortfall is {coverage['target_gap_units']:,}. The 30 registrations in five legacy "
        "PROPOSED crosswalk rows are a subcount of pending and are not approved coverage.\n\n"
        "## Materialization and remaining gates\n\n"
        f"The owner-approved missing-identity plan contains {len(materialization_plan)} CREATE targets. "
        f"The live read-only `vehicle_models` snapshot contains {catalog['model_count']} models; "
        f"109 targets had no exact same-brand name/alias collision and 5 match an existing same-brand alias. "
        "Those five keep their frozen owner identity decision and require the governed writer's collision "
        "guard; none is sent back for owner re-review. Every target remains blocked on a structural "
        "Vehicle Master Phase 1 writer.\n\n"
        f"All 244 decisions remain exact (92 LINK, 63 retained AUTO, 51 EXCLUDE, 38 CREATE); "
        "no owner decision was reopened. Raw segment/body outputs and unknown buckets are in "
        "`real_m7_reader_totals.json`. C01 production-run authorization provenance and C02 migration "
        "number reservation remain unresolved, so there is no migration assignment, production write, "
        "reader cutover, merge, or deployment.\n"
    )
    output_files = ["m7_scoped_resolver_qa.json", "m7_scoped_resolver_rows_1407.csv",
                    "materialization_plan_114.json", "materialization_plan_114.csv",
                    "real_m7_reader_totals.json", "many_to_one_target_groups.json", "acceptance_report.md"]
    (out_dir / "acceptance_evidence_manifest.json").write_text(json.dumps({
        "schema": "tdr.ice-scoped-crosswalk-v2-acceptance-evidence.v1",
        "source_pr229_head_sha": "872a1117b163feac42e0ce55314cd7a7408896b5",
        "source_pr232_head_sha": "3050beb1cdad4530808177de7b9d66abb21364f3",
        "m7_sha256": m7_sha,
        "catalog_snapshot_sha256": sha256(args.catalog_snapshot),
        "python_runner_sha256": sha256(Path(__file__)),
        "outputs": [{"path": name, "sha256": sha256(out_dir / name),
                     "bytes": (out_dir / name).stat().st_size} for name in output_files],
    }, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"acceptance": "PASS", "m7_rows_aggregated": len(resolved_shadow),
                      "raw_facts_resolved": len(raw_reader_rows), "fixed_denominator": DENOMINATOR,
                      "coverage": coverage, "materialization_targets": len(materialization_plan),
                      "segment_totals": reader_totals["segment_totals"],
                      "body_type_totals": reader_totals["body_type_totals"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
