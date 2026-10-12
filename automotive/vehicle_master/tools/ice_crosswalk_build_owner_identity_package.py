"""Build a deterministic package for owner-approved M7.0 new identities.

This does not create catalog models or write the crosswalk. It converts already
adjudicated new-identity decisions into stable targets for the identity bootstrap
path and reports their registration-weighted effect. After those targets exist in
vehicle_models, pass this JSON to ice_crosswalk_match.py --deterministic-identity-overrides.
Groups listed in owner_approved_identity_overrides retain APPROVED status regardless
of series threshold; series values remain diagnostic evidence. Other deterministic
targets stay under the original series/name acceptance scoring.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any
import glob

from vehreg.ice_crosswalk import normalize_model_name
from vehreg.normalize import fold
from vehreg.normalize import slug


def _nested_csv(package: zipfile.ZipFile, panel: str, member: str) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(package.read(panel))) as nested:
        with nested.open(member) as stream:
            return list(csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")))


def build_package(audit_csv: Path, package_zip: Path, review_csv: Path,
                  model_dir: Path) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[3]

    def source_ref(path: Path) -> str:
        try:
            return str(path.resolve().relative_to(repo_root))
        except ValueError:
            return path.name
    with audit_csv.open(encoding="utf-8-sig", newline="") as stream:
        audit = list(csv.DictReader(stream))
    recovery_path = audit_csv.parent / "ice-crosswalk-32-recovery-M7.0.csv"
    if not recovery_path.exists():
        recovery_path = audit_csv.parent / "recovery_decisions_original.csv"
    recovery_rows: list[dict[str, str]] = []
    if recovery_path.exists():
        with recovery_path.open(encoding="utf-8-sig", newline="") as stream:
            recovery_rows = list(csv.DictReader(stream))
    with zipfile.ZipFile(package_zip) as package:
        dims = _nested_csv(package, "panels/dims_2569-09_v3.zip", "dims/model_group.csv")
    weights = {row["model_group_id"]: int(row["reg_total_all"] or 0) for row in dims}
    source_total_units = sum(weights.values())
    with review_csv.open(encoding="utf-8-sig", newline="") as stream:
        live_review = list(csv.DictReader(stream))
    live_by_group = {row["ice_model_group_id"]: row for row in live_review}
    excluded_rows = [row for row in audit if row["effective_action"] == "OWNER_EXCLUDE_FROM_COUNT"]
    excluded_groups = {row["model_group_id"] for row in excluded_rows}
    held_rows = [row for row in audit if row["effective_action"] == "OWNER_HOLD_UNTOUCHED"]
    held_groups = {row["model_group_id"] for row in held_rows}
    excluded_units = sum(weights.get(group_id, 0) for group_id in excluded_groups)
    total_units = source_total_units - excluded_units
    baseline_units = sum(
        weights.get(group_id, 0) for group_id, row in live_by_group.items()
        if row["status"] in {"AUTO", "PROPOSED"} and group_id not in excluded_groups
    )

    # Build a collision-safe, exact same-brand catalog index. This is deliberately
    # name equality after the matcher's punctuation/case normalization, never fuzzy.
    brands_by_alias: dict[str, tuple[str, list[str]]] = {}
    exact_catalog: dict[tuple[str, str], list[dict[str, str]]] = {}
    catalog_model_ids: set[str] = set()
    for path in sorted(glob.glob(str(model_dir / "*.json"))):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        brand = data["brand"]["name_en"]
        brand_id = data["brand"]["id"]
        prefixes = [brand, brand_id, *data["brand"].get("aliases", [])]
        for alias in prefixes:
            brands_by_alias[fold(alias, split_digits=False)] = (brand_id, prefixes)
        for model in data.get("models", []):
            canonical_id = f"{brand_id}.{model['id']}"
            catalog_model_ids.add(canonical_id)
            labels = [model["name_en"]]
            if brand_id not in {"audi", "bmw", "volvo", "lexus", "peugeot", "ferrari", "zeekr", "mazda", "mg"}:
                labels.extend(model.get("aliases", []))
            for label in labels:
                normalized = normalize_model_name(label, brand)
                for prefix in prefixes:
                    prefix_key = normalize_model_name(prefix, "")
                    if prefix_key and normalized.startswith(prefix_key + " "):
                        normalized = normalized[len(prefix_key) + 1:]
                key = (brand_id, normalized)
                exact_catalog.setdefault(key, []).append({
                    "canonical_model_id": canonical_id,
                    "canonical_name_en": model["name_en"],
                    "brand_name_en": brand,
                })
    decisions = [row for row in audit if row["effective_action"] == "OWNER_CREATE_IDENTITY"]
    if not decisions:
        raise ValueError("audit contains no OWNER_CREATE_IDENTITY decisions")

    identities = []
    overrides: dict[str, str] = {}
    used_targets: set[str] = set()
    for row in decisions:
        brand_info = brands_by_alias.get(fold(row["brand"], split_digits=False))
        brand_id = brand_info[0] if brand_info else slug(row["brand"])
        identity_name = row["owner_new_canonical_name"].strip()
        if not brand_id or not identity_name:
            raise ValueError(f"missing stable brand/name for {row['model_group_id']}")
        # Names in the overlay are the owner's chosen identity label; stripping only
        # a repeated leading make gives a stable canonical id without fuzzy matching.
        local_name = identity_name
        brand_prefix = row["brand"].strip()
        if local_name.lower().startswith(brand_prefix.lower() + " "):
            local_name = local_name[len(brand_prefix):].strip()
        target_id = f"{brand_id}.{slug(local_name)}"
        if target_id in catalog_model_ids:
            raise ValueError(f"owner identity target collides with existing canonical model: {target_id}")
        if target_id in used_targets:
            raise ValueError(f"duplicate canonical target generated: {target_id}")
        used_targets.add(target_id)
        group_id = row["model_group_id"]
        overrides[group_id] = target_id
        identities.append({
            "model_group_id": group_id,
            "brand": row["brand"],
            "canonical_model_id": target_id,
            "canonical_name_en": identity_name,
            "registration_units_m7_0": weights.get(group_id, 0),
            "owner_verdict": row["owner_verdict"],
            "registration_type": row.get("owner_registration_type", ""),
            "lifecycle_status": row.get("owner_lifecycle_status", ""),
            "distinct_from": [value for value in row.get("owner_distinct_from", "").split("|") if value],
            "materialization_required": True,
        })

    # One recovery row reuses an earlier owner-adjudicated Lotus Emira identity, but
    # the canonical model is not in the current catalog yet. Carry that prior decision
    # forward as an explicit bootstrap target instead of emitting an empty mapping.
    prior_owner_targets = {
        "lotus-emira-v6__provisional": ("lotus", "lotus.emira", "Emira"),
    }
    for group_id, (brand_id, target_id, identity_name) in prior_owner_targets.items():
        if target_id in catalog_model_ids:
            continue
        recovery_row = next((row for row in recovery_rows if row["model_group_id"] == group_id), None)
        if recovery_row is None:
            continue
        existing_shadow = next((item for item in identities if item["canonical_model_id"] == target_id), None)
        if existing_shadow:
            # Two owner-approved Lotus groups resolve to the same already-approved
            # Emira identity. Keep one shadow identity and express the second group as
            # a deterministic link, with the prior recovery row as its provenance.
            overrides[group_id] = target_id
            continue
        overrides[group_id] = target_id
        identities.append({
            "model_group_id": group_id,
            "brand": "LOTUS",
            "canonical_model_id": target_id,
            "canonical_name_en": identity_name,
            "registration_units_m7_0": weights.get(group_id, 0),
            "owner_verdict": "REUSE_PRIOR_OWNER_DECISION",
            "registration_type": "",
            "lifecycle_status": "",
            "distinct_from": [],
            "materialization_required": True,
        })

    created_target_ids = {item["canonical_model_id"] for item in identities}
    owner_link_overrides = {}
    for row in audit:
        if row["effective_action"] != "OWNER_LINK_EXISTING":
            continue
        target_id = row.get("owner_target_canonical_id") or row.get("owner_existing_canonical_id")
        if target_id and target_id in catalog_model_ids | created_target_ids:
            owner_link_overrides[row["model_group_id"]] = target_id

    # Lifecycle instructions can refer to an existing catalog identity or a target
    # created in this same package. Keep these as explicit directives so they are
    # reviewable without silently modifying the catalog during package generation.
    lifecycle_directives_by_target: dict[tuple[str, str], dict[str, str]] = {}
    for row in audit:
        lifecycle = row.get("owner_lifecycle_status", "").strip()
        if not lifecycle:
            continue
        target_id = (row.get("owner_target_canonical_id")
                     or row.get("owner_existing_canonical_id"))
        if not target_id:
            brand_info = brands_by_alias.get(fold(row["brand"], split_digits=False))
            brand_id = brand_info[0] if brand_info else slug(row["brand"])
            identity_name = row.get("owner_new_canonical_name", "").strip()
            local_name = identity_name
            brand_prefix = row["brand"].strip()
            if local_name.lower().startswith(brand_prefix.lower() + " "):
                local_name = local_name[len(brand_prefix):].strip()
            if local_name:
                target_id = f"{brand_id}.{slug(local_name)}"
        if target_id:
            lifecycle_directives_by_target[(target_id, lifecycle)] = {
                "canonical_model_id": target_id,
                "lifecycle_status": lifecycle,
                "source_model_group_id": row["model_group_id"],
            }

    identity_units = sum(item["registration_units_m7_0"] for item in identities)
    exact_existing_matches = []
    decisions_by_group = {row["model_group_id"]: row for row in audit}
    for group_id, live in live_by_group.items():
        if live["status"] != "UNMATCHED":
            continue
        if group_id in excluded_groups:
            continue
        # Explicit owner decisions outrank general aliases (e.g. J5 remains distinct
        # even though the catalog lists it as an alias of Jaecoo 5 EV).
        if decisions_by_group.get(group_id, {}).get("effective_action") != "UNMATCHED_NO_CANDIDATE":
            continue
        brand_info = brands_by_alias.get(fold(live["ice_brand"], split_digits=False))
        if brand_info is None:
            continue
        brand_id, prefixes = brand_info
        normalized = normalize_model_name(live["ice_model_name"], live["ice_brand"])
        for prefix in prefixes:
            prefix_key = normalize_model_name(prefix, "")
            if prefix_key and normalized.startswith(prefix_key + " "):
                normalized = normalized[len(prefix_key) + 1:]
        key = (brand_id, normalized)
        matches = exact_catalog.get(key, [])
        unique_targets = {row["canonical_model_id"]: row for row in matches}
        if len(unique_targets) != 1:
            continue
        target = next(iter(unique_targets.values()))
        # An identity may already be actively assigned to a different Ice group.
        if any(row["canonical_model_id"] == target["canonical_model_id"]
               and row["status"] in {"AUTO", "PROPOSED"}
               for other_id, row in live_by_group.items() if other_id != group_id):
            continue
        exact_existing_matches.append({
            "model_group_id": group_id,
            "canonical_model_id": target["canonical_model_id"],
            "canonical_name_en": target["canonical_name_en"],
            "registration_units_m7_0": weights.get(group_id, 0),
            "rule": "SAME_BRAND_EXACT_NORMALIZED_MODEL_NAME",
        })
    exact_units = sum(row["registration_units_m7_0"] for row in exact_existing_matches)
    owner_confirmed_auto_matches = []
    for row in audit:
        if row.get("owner_verdict") != "OWNER_APPROVED" or row.get("effective_action") != "KEEP_EXISTING_AUTO":
            continue
        live = live_by_group.get(row["model_group_id"])
        if not live or live.get("status") != "AUTO" or not live.get("canonical_model_id"):
            continue
        owner_confirmed_auto_matches.append({
            "model_group_id": row["model_group_id"],
            "canonical_model_id": live["canonical_model_id"],
            "canonical_name_en": live.get("canonical_model_name", ""),
            "registration_units_m7_0": weights.get(row["model_group_id"], 0),
            "owner_verdict": "OWNER_APPROVED_AUTO_MATCH",
        })
    owner_approved_identity_overrides: dict[str, str] = {}
    for row in audit:
        group_id = row["model_group_id"]
        action = row["effective_action"]
        if action == "OWNER_LINK_EXISTING":
            target_id = (row.get("owner_target_canonical_id") or row.get("owner_existing_canonical_id")
                         or row.get("target_canonical_id"))
            if target_id:
                owner_approved_identity_overrides[group_id] = target_id
        elif action == "OWNER_CREATE_IDENTITY" and group_id in overrides:
            owner_approved_identity_overrides[group_id] = overrides[group_id]
    for row in owner_confirmed_auto_matches:
        owner_approved_identity_overrides[row["model_group_id"]] = row["canonical_model_id"]
    for group_id, target_id in owner_approved_identity_overrides.items():
        deterministic_target = {
            **owner_link_overrides, **overrides,
        }.get(group_id)
        if deterministic_target and deterministic_target != target_id:
            raise ValueError(f"owner-approved target conflicts with deterministic target for {group_id}")
    # A rejected candidate remains covered only when the packaged recovery has a
    # concrete existing target. Identity-discovery rows and owner holds stay out.
    recoveries = []
    unresolved_recovery_units = 0
    owner_hold_units = 0
    for row in recovery_rows:
        owner_resolution = decisions_by_group.get(row["model_group_id"], {}).get("effective_action", "")
        if owner_resolution in {"OWNER_CREATE_IDENTITY", "OWNER_LINK_EXISTING", "OWNER_EXCLUDE_FROM_COUNT"}:
            # The owner overlay now supplies the identity/link/exclusion that the
            # original recovery sheet left open. Do not keep subtracting it as an
            # unresolved discovery or rejection hold.
            continue
        if row["recovery_action"] in {"EXACT_EXISTING", "EXACT_NAME_EQUIVALENT"}:
            recoveries.append({
                "model_group_id": row["model_group_id"],
                "canonical_model_id": row["target_canonical_id"],
                "rule": row["recovery_action"],
                "materialization_required": row["target_canonical_id"] not in catalog_model_ids,
            })
        elif row["recovery_action"] == "IDENTITY_DISCOVERY":
            unresolved_recovery_units += weights.get(row["model_group_id"], 0)
        elif row["recovery_action"] == "OWNER_REJECTION_HOLD":
            owner_hold_units += weights.get(row["model_group_id"], 0)
    # The owner-new identities that were already PROPOSED do not add coverage;
    # only previously UNMATCHED source groups increase this denominator's result.
    newly_matched_identity_units = sum(
        item["registration_units_m7_0"] for item in identities
        if live_by_group.get(item["model_group_id"], {}).get("status") == "UNMATCHED"
    )
    newly_matched_owner_link_units = sum(
        weights.get(group_id, 0) for group_id in owner_link_overrides
        if live_by_group.get(group_id, {}).get("status") == "UNMATCHED"
        and group_id not in excluded_groups
    )
    after_units = (baseline_units + exact_units + newly_matched_identity_units
                   + newly_matched_owner_link_units
                   - owner_hold_units - unresolved_recovery_units)
    owner_identity_count = len(decisions)
    return {
        "schema_version": 1,
        "kind": "ICE_OWNER_IDENTITY_BOOTSTRAP_TARGETS",
        "master_version": "7.0",
        "source": source_ref(audit_csv),
        "registration_weight_source": source_ref(package_zip),
        "live_match_source": source_ref(review_csv),
        "coverage_basis": "M7.0 model_group.reg_total_all, unique model groups",
        "current_match_coverage_pct": round(100 * baseline_units / total_units, 3),
        "after_identity_materialization_pct": round(100 * after_units / total_units, 3),
        "target_pct": 99.1,
        "total_registration_units": total_units,
        "source_total_registration_units": source_total_units,
        "owner_excluded_registration_units": excluded_units,
        "owner_excluded_groups": [
            {"model_group_id": row["model_group_id"],
             "registration_units_m7_0": weights.get(row["model_group_id"], 0),
             "owner_reason": row.get("recovery_basis", "")}
            for row in excluded_rows
        ],
        "owner_held_groups": [
            {"model_group_id": row["model_group_id"],
             "registration_units_m7_0": weights.get(row["model_group_id"], 0),
             "owner_reason": row.get("recovery_basis", "")}
            for row in held_rows
        ],
        "baseline_mapped_units": baseline_units,
        "identity_registration_units": identity_units,
        "newly_matched_identity_units": newly_matched_identity_units,
        "newly_matched_owner_link_units": newly_matched_owner_link_units,
        "exact_existing_matches": exact_existing_matches,
        "owner_confirmed_auto_matches": owner_confirmed_auto_matches,
        "exact_existing_registration_units": exact_units,
        "concrete_rejected_candidate_recoveries": recoveries,
        "unresolved_recovery_groups": [
            row["model_group_id"] for row in recovery_rows
            if row["recovery_action"] == "IDENTITY_DISCOVERY"
            and decisions_by_group.get(row["model_group_id"], {}).get("effective_action")
            not in {"OWNER_CREATE_IDENTITY", "OWNER_LINK_EXISTING", "OWNER_EXCLUDE_FROM_COUNT"}
            and row["model_group_id"] not in excluded_groups
        ],
        "deterministic_identity_overrides": {
            **owner_link_overrides,
            **overrides,
            **{row["model_group_id"]: row["canonical_model_id"] for row in exact_existing_matches},
            **{row["model_group_id"]: row["canonical_model_id"] for row in recoveries},
        },
        "owner_approved_identity_overrides": owner_approved_identity_overrides,
        "owner_hold_registration_units": owner_hold_units,
        "owner_unmapped_hold_registration_units": sum(
            weights.get(group_id, 0) for group_id in held_groups
        ),
        "identity_discovery_hold_registration_units": unresolved_recovery_units,
        "owner_identity_count": owner_identity_count,
        "identity_target_count": len(identities),
        "owner_adjudicated_new_identity_count": owner_identity_count,
        "owner_identity_overrides": overrides,
        "identities": identities,
        "lifecycle_directives": list(lifecycle_directives_by_target.values()),
        "limitations": [
            "Targets are derived from explicit owner decisions; they are not catalog writes.",
            "Each canonical model must be materialized and validated before the matcher can use its override.",
            "The 99.1% figure is a projected registration-weighted result, not a production run result.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-csv", required=True, type=Path)
    parser.add_argument("--package-zip", required=True, type=Path)
    parser.add_argument("--review-csv", required=True, type=Path)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = build_package(args.audit_csv, args.package_zip, args.review_csv, args.model_dir)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "owner_identity_count", "identity_target_count", "identity_registration_units", "total_registration_units",
        "current_match_coverage_pct", "after_identity_materialization_pct", "target_pct",
    )}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
