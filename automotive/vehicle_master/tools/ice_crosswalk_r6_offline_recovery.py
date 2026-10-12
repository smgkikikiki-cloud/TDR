"""Freeze owner decisions and run a reproducible, shadow-only M7.0 recovery.

The live capture mode performs SELECT requests only. The build mode is entirely
offline: it reads the exact Ice Full Package, frozen owner artifacts, and the
read-only Vehicle Master/crosswalk snapshot, then writes audit and shadow outputs
under data/packages/ice_crosswalk_r6_offline_recovery_M7.0/.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import zipfile
import glob
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vehreg import ice_crosswalk as xwalk
from vehreg.normalize import slug

try:
    from tools import ice_crosswalk_match as matcher
except ImportError:  # direct script invocation from repository root
    from automotive.vehicle_master.tools import ice_crosswalk_match as matcher


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data/packages/ice_crosswalk_r6_offline_recovery_M7.0"
SOURCE = OUT / "source"
PACKAGE = ROOT / "data/packages/2569-09/v3_M7.0/TDR_FULL_2569-09_v3_M7.0.zip"
OVERLAY = SOURCE / "owner_overlay_original.csv"
ORIGINAL_PACKAGE = SOURCE / "owner_identity_overrides_original.json"
RULE_AUDIT = SOURCE / "kept_candidate_rule_audit_original.csv"
RECOVERY = SOURCE / "recovery_decisions_original.csv"
PICKUP_SPLITS = SOURCE / "pickup_identity_class_split_original.csv"
OWNER_TARGETS = OUT / "owner_identity_targets.json"
LIVE_REVIEW = SOURCE / "live_review_original.csv"
CLASSIFICATION_COLUMNS = [
    "model_group_id", "source_package_model_group_id", "reg_type", "brand",
    "source_model_name", "reg_count", "prior_status", "prior_canonical_id",
    "prior_canonical_name", "decision_ref", "target_canonical_id",
    "target_name", "disposition", "classification_category", "coverage_eligible", "reason",
    "owner_overlay_sha256", "source_package_sha256",
]

LEDGER_COLUMNS = [
    "decision_id", "model_group_id", "reg_type_scope", "brand", "source_model_name",
    "registration_units_m7_0", "prior_canonical_id", "prior_canonical_name",
    "prior_status", "rule_flags", "owner_action", "owner_verdict",
    "canonical_target_id", "canonical_target_name", "lifecycle_status",
    "excluded_from_coverage", "decision_provenance", "owner_decided_at",
    "timestamp_limit", "technical_contradiction", "owner_overlay_line",
    "owner_overlay_sha256", "rule_audit_line", "source_package_sha256",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_reg_type_scope(value: str) -> str:
    aliases = {"RY1": "รย.1", "RY2": "รย.2", "RY3": "รย.3"}
    cleaned = value.strip().upper()
    return aliases.get(cleaned, value.strip())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def nested_csv(package: zipfile.ZipFile, panel: str, member: str) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(package.read(panel))) as nested:
        with nested.open(member) as raw:
            return list(csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")))


def source_rows_with_lines(path: Path) -> list[tuple[int, dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return [(line, row) for line, row in enumerate(csv.DictReader(stream), start=2)]


def build_owner_ledger() -> list[dict[str, Any]]:
    overlay_lines = source_rows_with_lines(OVERLAY)
    overlay = {row["model_group_id"]: (line, row) for line, row in overlay_lines}
    rule_lines = source_rows_with_lines(RULE_AUDIT)
    rules = {row["model_group_id"]: (line, row) for line, row in rule_lines}
    owner_package = json.loads(ORIGINAL_PACKAGE.read_text(encoding="utf-8"))
    target_overrides = owner_package["deterministic_identity_overrides"]
    confirmed_auto = {
        item["model_group_id"]: item for item in owner_package["owner_confirmed_auto_matches"]
    }
    with zipfile.ZipFile(PACKAGE) as package:
        weights = {
            row["model_group_id"]: int(row["reg_total_all"] or 0)
            for row in nested_csv(package, "panels/dims_2569-09_v3.zip", "dims/model_group.csv")
        }
    overlay_hash = sha256(OVERLAY)
    package_hash = sha256(PACKAGE)
    explicit_technical_flags = {
        "BMW|530I LIMOUSINE RHD": "BMW code-sensitive rule conflicts with explicit owner link to BMW 3 Series; retain owner target.",
        "audi-audi-rs-q8": "Source RS Q8 conflicts with owner-specified new target RS Q7; preserve the exact target and flag for engineering traceability.",
        "subaru-levorg-sti-sport-r__provisional": "Owner-specified canonical spelling 'Subaru levorge' differs from source nameplate Levorg; preserve spelling.",
    }
    result: list[dict[str, Any]] = []
    for row in read_csv(RULE_AUDIT):
        group_id = row["model_group_id"]
        if group_id not in overlay:
            raise ValueError(f"244-row audit group absent from owner overlay: {group_id}")
        overlay_line, decision = overlay[group_id]
        action = decision["effective_action"]
        if action not in {
            "OWNER_LINK_EXISTING", "KEEP_EXISTING_AUTO",
            "OWNER_EXCLUDE_FROM_COUNT", "OWNER_CREATE_IDENTITY",
        }:
            raise ValueError(f"unresolved 244-row disposition for {group_id}: {action}")
        target_id = ""
        target_name = ""
        if action == "OWNER_LINK_EXISTING":
            target_id = decision.get("owner_target_canonical_id") or decision.get("owner_existing_canonical_id", "")
            target_name = decision.get("owner_target_canonical_name") or decision.get("scorer_candidate_name", "")
        elif action == "OWNER_CREATE_IDENTITY":
            target_id = target_overrides.get(group_id, "")
            target_name = decision.get("owner_new_canonical_name", "")
        elif action == "KEEP_EXISTING_AUTO":
            auto = confirmed_auto.get(group_id)
            target_id = auto["canonical_model_id"] if auto else row["canonical_model_id"]
            target_name = auto["canonical_name_en"] if auto else row["canonical_model_name"]
        if action in {"OWNER_LINK_EXISTING", "OWNER_CREATE_IDENTITY", "KEEP_EXISTING_AUTO"} and not target_id:
            raise ValueError(f"decision target missing for {group_id}: {action}")
        provenance = (
            "OWNER_APPROVED_BY_EXCLUSION: the owner supplied the complete wrong-pair list; the remaining 63 AUTO rows were explicitly retained."
            if action == "KEEP_EXISTING_AUTO"
            else decision.get("recovery_basis") or "Explicit owner adjudication recorded in the source overlay."
        )
        rule_line, _ = rules[group_id]
        result.append({
            "decision_id": hashlib.sha256(group_id.encode()).hexdigest()[:16],
            "model_group_id": group_id,
            "reg_type_scope": decision.get("owner_registration_type", ""),
            "brand": decision.get("brand", row["brand"]),
            "source_model_name": decision.get("ice_model_name", row["ice_model_name"]),
            "registration_units_m7_0": weights.get(group_id, 0),
            "prior_canonical_id": row["canonical_model_id"],
            "prior_canonical_name": row["canonical_model_name"],
            "prior_status": row["live_status"],
            "rule_flags": row["rule_flags"],
            "owner_action": action,
            "owner_verdict": decision["owner_verdict"],
            "canonical_target_id": target_id,
            "canonical_target_name": target_name,
            "lifecycle_status": decision.get("owner_lifecycle_status", ""),
            "excluded_from_coverage": action == "OWNER_EXCLUDE_FROM_COUNT",
            "decision_provenance": provenance,
            "owner_decided_at": "",
            "timestamp_limit": "No per-row timestamp exists in the recovered source; original batch chronology remains in WORK_STATE and is not synthesized.",
            "technical_contradiction": explicit_technical_flags.get(group_id, ""),
            "owner_overlay_line": overlay_line,
            "owner_overlay_sha256": overlay_hash,
            "rule_audit_line": rule_line,
            "source_package_sha256": package_hash,
        })
    ids = [row["model_group_id"] for row in result]
    if len(result) != 244 or len(ids) != len(set(ids)):
        raise ValueError(f"244 owner decisions not unique/complete: rows={len(result)} unique={len(set(ids))}")
    expected = Counter({
        "OWNER_LINK_EXISTING": 92,
        "KEEP_EXISTING_AUTO": 63,
        "OWNER_EXCLUDE_FROM_COUNT": 51,
        "OWNER_CREATE_IDENTITY": 38,
    })
    actual = Counter(row["owner_action"] for row in result)
    if actual != expected:
        raise ValueError(f"owner decision split changed: expected {expected}, got {actual}")
    return result


def build_exception_review(ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Exception-only evidence; preserves owner outcomes and does not reopen them."""
    rejected = read_csv(SOURCE / "rejected_candidates_original.csv")
    rows: list[dict[str, Any]] = []
    for item in ledger:
        if item["technical_contradiction"] or item["rule_flags"]:
            rows.append({
                "model_group_id": item["model_group_id"],
                "source_model_name": item["source_model_name"],
                "prior_candidate_id": item["prior_canonical_id"],
                "owner_action": item["owner_action"],
                "owner_target_id": item["canonical_target_id"],
                "technical_contradiction": item["technical_contradiction"],
                "rule_flags": item["rule_flags"],
                "re_review_required": False,
            })
    for item in rejected:
        rows.append({
            "model_group_id": item["model_group_id"],
            "source_model_name": item["ice_model_name"],
            "prior_candidate_id": item["rejected_candidate_id"],
            "owner_action": "OWNER_REJECTED_CANDIDATE",
            "owner_target_id": "",
            "technical_contradiction": "Owner rejected this candidate; no replacement decision is inferred here.",
            "rule_flags": "",
            "re_review_required": False,
        })
    return rows


def build_live_snapshot(output: Path, expected_master_version: str = "7.0") -> dict[str, Any]:
    """SELECT-only snapshot of live R6 dependencies; this function never POSTs."""
    from tools.canonical_input_worker import _request

    imported = matcher.check_live_import(_request, master_version=expected_master_version)
    if imported.get("period") != "2569-09" or imported.get("package_version") != 3:
        raise ValueError(f"wrong live Ice release for M7.0 recovery: {imported}")
    live_groups = matcher.fetch_ice_groups(_request)
    models = matcher._fetch_all(_request,
        "vehicle_models?select=canonical_id,name_en,brand_id,slug,payload")
    brands = matcher._fetch_all(_request, "vehicle_brands?select=canonical_id,name_en,slug")
    aliases = matcher._fetch_all(_request, "ice_brand_aliases?select=brand,alias_group")
    crosswalk = matcher.fetch_existing_crosswalk(_request)
    legacy = matcher.fetch_legacy_monthly_series(_request)
    snapshot = {
        "schema": "tdr.ice-crosswalk-r6-live-readonly-snapshot.v1",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "ice_package_import": imported,
        "live_group_count": len(live_groups),
        "live_groups": live_groups,
        "vehicle_models": models,
        "vehicle_brands": brands,
        "ice_brand_aliases": aliases,
        "crosswalk_rows": list(crosswalk.values()),
        "legacy_monthly_series": legacy,
        "side_effects": {"GET": "performed", "POST": 0, "PATCH": 0, "DELETE": 0},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return snapshot


def package_rows() -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], int]]:
    """Return the immutable M7.0 dimension rows and registration units by group/type."""
    with zipfile.ZipFile(PACKAGE) as package:
        dims_rows = nested_csv(package, "panels/dims_2569-09_v3.zip", "dims/model_group.csv")
        trend_rows = nested_csv(package, "panels/reg_trend_2569-09_v3.zip", "data/reg_trend.csv")
    dims = {row["model_group_id"]: row for row in dims_rows}
    by_group_type: dict[tuple[str, str], int] = defaultdict(int)
    for row in trend_rows:
        by_group_type[(row["model_group_id"], row["reg_type"])] += int(row["reg_count"] or 0)
    totals: dict[str, int] = defaultdict(int)
    for (group_id, _), units in by_group_type.items():
        totals[group_id] += units
    mismatches = [group for group, row in dims.items() if totals[group] != int(row["reg_total_all"] or 0)]
    if len(dims) != 1200 or mismatches or sum(totals.values()) != 4_141_987:
        raise ValueError(
            f"M7.0 fixed denominator integrity failed: groups={len(dims)}, "
            f"mismatched_groups={len(mismatches)}, trend_total={sum(totals.values())}"
        )
    return dims, dict(by_group_type)


def _target_from_pickup(row: dict[str, str], reg_type: str) -> tuple[str, str, str]:
    """Apply the frozen RY split only where its target is explicit and safe."""
    status = row.get("class_split_status", "")
    context = row.get("current_r6_candidate_context_unapproved", "")
    target = re.search(r"\[([^\]]+)\]", context)
    target_id = target.group(1) if target else ""
    if status == "OWNER_REDIRECTED_TO_RY3":
        return "", "", "OWNER_REDIRECT_TO_RY3_ONLY; this source registration class remains intentionally unmapped"
    if status == "OWNER_LINK_EXISTING":
        note = row.get("notes", "")
        explicit = re.search(r"\(([a-z0-9_.-]+)\)", note)
        return (explicit.group(1) if explicit else target_id), "", "Explicit owner pickup identity link"
    if status == "SINGLE_CLASS_ONLY":
        # The source has only one registration class. Keep its saved candidate as
        # evidence, but don't promote an explicitly unapproved candidate to a link.
        return "", "", "SINGLE_CLASS_ONLY; saved candidate is unapproved"
    if status == "SPLIT_BY_REG_TYPE":
        source_brand = row.get("ice_brand", row.get("brand", ""))
        source_model = row.get("ice_model_name", "")
        if reg_type in {"รย.1", "รย.2"}:
            target = _pickup_catalog_target(source_brand, source_model, double_cab=True)
            if target:
                return target[0], target[1], "RY1/RY2 pickup policy resolves to the unique matching Double Cab catalog identity; shadow only"
        if reg_type == "รย.3":
            target = _pickup_catalog_target(source_brand, source_model, double_cab=False)
            if target:
                return target[0], target[1], "RY3 other-cab policy resolves to the unique non-Double-Cab pickup identity; shadow only"
            return "", "", "RY3 exact parent identity lookup required"
        return "", "", "Registration class is outside the explicit pickup split policy"
    return "", "", "No frozen pickup split action"


def _pickup_catalog_target(brand: str, model_name: str, *, double_cab: bool) -> tuple[str, str] | None:
    """Resolve a pickup cab-class label from one same-brand exact catalog family."""
    wanted = xwalk.normalize_model_name(model_name, brand)
    brand_key = re.sub(r"[^a-z0-9]+", "", brand.casefold())
    model_dir = ROOT / "automotive/vehicle_master/vehreg/data/2026/models"
    matches: dict[str, str] = {}
    for path in sorted(model_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        aliases = [data["brand"]["name_en"], *data["brand"].get("aliases", [])]
        keys = {re.sub(r"[^a-z0-9]+", "", value.casefold()) for value in aliases}
        if brand_key not in keys:
            continue
        brand_id = data["brand"]["id"]
        for model in data.get("models", []):
            label = model.get("name_en", "")
            normalized = xwalk.normalize_model_name(label, brand)
            is_double = "double cab" in normalized or "c cab" in normalized
            is_other_cab = normalized.endswith(" cab") and not is_double
            if double_cab and not is_double or not double_cab and not is_other_cab:
                continue
            base = normalized.replace(" double cab", "").replace(" c cab", "").replace(" x cab", "").replace(" cab", "")
            if wanted not in base and base not in wanted:
                continue
            matches[f"{brand_id}.{model['id']}"] = label
    if len(matches) != 1:
        return None
    return next(iter(matches.items()))


def _exact_catalog_identity(brand: str, model_name: str) -> tuple[str, str] | None:
    """Find one exact normalized same-brand model identity in the checked-in catalog."""
    wanted = xwalk.normalize_model_name(model_name, brand)
    brand_key = re.sub(r"[^a-z0-9]+", "", brand.casefold())
    if not wanted:
        return None
    matches: dict[str, str] = {}
    model_dir = ROOT / "automotive/vehicle_master/vehreg/data/2026/models"
    for path in sorted(model_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        actual_brand = re.sub(r"[^a-z0-9]+", "", data["brand"]["name_en"].casefold())
        aliases = [data["brand"]["name_en"], *data["brand"].get("aliases", [])]
        if brand_key not in {re.sub(r"[^a-z0-9]+", "", value.casefold()) for value in aliases} and brand_key != actual_brand:
            continue
        brand_id = data["brand"]["id"]
        for model in data.get("models", []):
            labels = [model.get("name_en", ""), *model.get("aliases", [])]
            for label in labels:
                if xwalk.normalize_model_name(label, brand) == wanted:
                    target_id = f"{brand_id}.{model['id']}"
                    matches[target_id] = model.get("name_en", label)
    if len(matches) != 1:
        return None
    target_id, target_name = next(iter(matches.items()))
    return target_id, target_name


def build_shadow_rows(owner_targets_path: Path = OWNER_TARGETS) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run the real M7.0 input through frozen owner decisions and deterministic offline rules."""
    dims, weights = package_rows()
    overlay_line_rows = source_rows_with_lines(OVERLAY)
    overlay = {row["model_group_id"]: row for _, row in overlay_line_rows}
    overlay_lines = {row["model_group_id"]: line for line, row in overlay_line_rows}
    live_rows = read_csv(LIVE_REVIEW)
    live: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in live_rows:
        group = row["ice_model_group_id"]
        live[group].append(row)
    if set(dims) != set(overlay) or set(dims) != set(live):
        raise ValueError(
            f"M7.0 group reconciliation failed: dims={len(dims)}, overlay={len(overlay)}, "
            f"live_review={len(live)}, missing_overlay={len(set(dims)-set(overlay))}, "
            f"missing_live={len(set(dims)-set(live))}"
        )
    if not owner_targets_path.exists():
        raise FileNotFoundError(f"build owner identity target package first: {owner_targets_path}")
    targets = json.loads(owner_targets_path.read_text(encoding="utf-8"))
    deterministic = targets["deterministic_identity_overrides"]
    identities = {row["model_group_id"]: row for row in targets["identities"]}
    exact = {row["model_group_id"]: row for row in targets["exact_existing_matches"]}
    recovery = {row["model_group_id"]: row for row in targets["concrete_rejected_candidate_recoveries"]}
    confirmed_auto = {row["model_group_id"]: row for row in targets["owner_confirmed_auto_matches"]}
    rejected = {row["model_group_id"]: row for row in read_csv(SOURCE / "rejected_candidates_original.csv")}
    pickup_rows = read_csv(PICKUP_SPLITS)
    pickup = {(row["ice_model_group_id"], row["registration_type"]): row for row in pickup_rows}
    ledger = {row["model_group_id"]: row for row in build_owner_ledger()}
    overlay_hash = sha256(OVERLAY)
    package_hash = sha256(PACKAGE)
    rows: list[dict[str, Any]] = []
    for (group_id, reg_type), units in sorted(weights.items()):
        owner = overlay[group_id]
        prior_rows = live[group_id]
        canonical_ids = sorted({row["canonical_model_id"] for row in prior_rows if row["canonical_model_id"]})
        prior = next((row for row in prior_rows if row.get("match_method") != "ADMIN"), prior_rows[0])
        prior_status = "CROSSWALK_COLLISION" if len(canonical_ids) > 1 else prior["status"]
        decision = ledger.get(group_id)
        target_id = ""
        target_name = ""
        disposition = ""
        eligible = False
        reason = ""
        decision_ref = ""
        action = owner["effective_action"]
        if action == "OWNER_SPLIT_BY_REG_TYPE":
            decision_ref = f"owner-overlay-line:{overlay_lines[group_id]}"
        exact_prior = [
            candidate for candidate in prior_rows
            if candidate.get("match_method") != "ADMIN"
            and candidate.get("canonical_model_id")
            and xwalk.normalize_model_name(candidate.get("canonical_model_name", ""), dims[group_id]["brand"])
                == xwalk.normalize_model_name(dims[group_id]["model_name"], dims[group_id]["brand"])
        ]
        if decision:
            decision_ref = decision["decision_id"]
            scope = normalize_reg_type_scope(decision.get("reg_type_scope", ""))
            if scope and scope != reg_type:
                pickup_row = pickup.get((group_id, reg_type))
                if pickup_row:
                    target_id, target_name, reason = _target_from_pickup(pickup_row, reg_type)
                    if reason == "RY3 exact parent identity lookup required":
                        exact_parent = _exact_catalog_identity(dims[group_id]["brand"], dims[group_id]["model_name"])
                        if exact_parent:
                            target_id, target_name = exact_parent
                            reason = "RY3 other-cab mapping uses a unique exact same-brand catalog parent; shadow only."
                    if target_id:
                        disposition = "PICKUP_RY_SPLIT_SHADOW"
                        eligible = True
                    elif reason.startswith("OWNER_REDIRECT_TO_RY3_ONLY"):
                        disposition = "OWNER_REDIRECT_CLASS_UNMAPPED"
                    else:
                        disposition = "PICKUP_SPLIT_UNAPPROVED_OR_AMBIGUOUS"
                else:
                    disposition = "OWNER_DECISION_OUT_OF_SCOPE"
                    reason = f"Owner decision is scoped to {scope}; this row is {reg_type}."
            elif action == "OWNER_EXCLUDE_FROM_COUNT":
                disposition = "OWNER_EXCLUDED"
                reason = "Frozen owner exclusion; retained outside the coverage numerator."
            elif action in {"OWNER_LINK_EXISTING", "KEEP_EXISTING_AUTO"}:
                target_id = decision["canonical_target_id"]
                target_name = decision["canonical_target_name"]
                disposition = "OWNER_APPROVED_LINK" if action == "OWNER_LINK_EXISTING" else "OWNER_APPROVED_AUTO"
                eligible = True
                reason = "Frozen owner decision takes precedence over scorer status and series evidence."
            elif action == "OWNER_CREATE_IDENTITY":
                target_id = deterministic.get(group_id, decision["canonical_target_id"])
                target_name = decision["canonical_target_name"]
                disposition = "OWNER_APPROVED_SHADOW_IDENTITY"
                eligible = True
                reason = "Explicit owner identity target materialized in the offline shadow catalog only."
        elif action == "OWNER_EXCLUDE_FROM_COUNT":
            disposition = "OWNER_EXCLUDED"
            reason = "Owner-supplied exclusion preserved from the complete overlay; excluded from the adjusted denominator."
            decision_ref = f"owner-overlay-line:{overlay_lines[group_id]}"
        elif action == "OWNER_LINK_EXISTING":
            target_id = (owner.get("owner_target_canonical_id") or owner.get("owner_existing_canonical_id")
                         or owner.get("target_canonical_id", ""))
            if not target_id:
                raise ValueError(f"owner link has no target in the frozen overlay: {group_id}")
            target_name = owner.get("scorer_candidate_name", "")
            disposition = "OWNER_APPROVED_LINK"
            eligible = True
            if len(canonical_ids) > 1 and any(candidate["canonical_model_id"] == target_id for candidate in exact_prior):
                reason = (
                    "Explicit owner link selects the exact same-brand nameplate; conflicting ADMIN row is an "
                    "unapproved structure proposal and is preserved as rejected evidence."
                )
            else:
                reason = owner.get("recovery_basis") or "Explicit owner link in the frozen 1200-row overlay."
            decision_ref = f"owner-overlay-line:{overlay_lines[group_id]}"
        elif action == "OWNER_CREATE_IDENTITY":
            target_id = deterministic.get(group_id, "")
            target_name = owner.get("owner_new_canonical_name", "")
            if not target_id or not target_name:
                raise ValueError(f"owner creation target is missing from the frozen package: {group_id}")
            disposition = "OWNER_APPROVED_SHADOW_IDENTITY"
            eligible = True
            reason = owner.get("recovery_basis") or "Owner-approved identity target exists in shadow only."
            decision_ref = f"owner-overlay-line:{overlay_lines[group_id]}"
        elif action == "KEEP_EXISTING_AUTO":
            auto = confirmed_auto.get(group_id)
            if not auto or not auto.get("canonical_model_id"):
                raise ValueError(f"owner-confirmed AUTO mapping missing from original target package: {group_id}")
            target_id = auto["canonical_model_id"]
            target_name = auto.get("canonical_name_en", "")
            disposition = "OWNER_APPROVED_AUTO"
            eligible = True
            reason = "Explicitly retained AUTO row in the frozen owner-approved keep-candidate audit."
            decision_ref = f"owner-overlay-line:{overlay_lines[group_id]}"
        elif action == "OWNER_REJECT_CANDIDATE" and group_id in recovery:
            target_id = recovery[group_id]["canonical_model_id"]
            disposition = "DETERMINISTIC_REJECTED_CANDIDATE_RECOVERY"
            eligible = True
            reason = "Rejected candidate removed; frozen recovery file supplies a distinct exact target."
            decision_ref = f"owner-overlay-line:{overlay_lines[group_id]}"
        elif action == "OWNER_REJECT_CANDIDATE":
            disposition = "OWNER_REJECTED_CANDIDATE"
            reason = "The prior candidate was explicitly rejected; no replacement target is inferred."
            decision_ref = f"owner-overlay-line:{overlay_lines[group_id]}"
        elif (group_id, reg_type) in pickup:
            target_id, target_name, reason = _target_from_pickup(pickup[(group_id, reg_type)], reg_type)
            if target_id:
                disposition = "PICKUP_RY_SPLIT_SHADOW"
                eligible = True
            elif reason == "RY3 exact parent identity lookup required":
                exact_parent = _exact_catalog_identity(dims[group_id]["brand"], dims[group_id]["model_name"])
                if exact_parent:
                    target_id, target_name = exact_parent
                    disposition = "PICKUP_RY_SPLIT_SHADOW"
                    eligible = True
                    reason = "RY3 other-cab mapping uses a unique exact same-brand catalog parent; shadow only."
                else:
                    disposition = "PICKUP_SPLIT_UNAPPROVED_OR_AMBIGUOUS"
                    reason = "RY3 is other cabs; exact same-brand parent identity was not unique in the checked-in catalog."
            elif reason.startswith("OWNER_REDIRECT_TO_RY3_ONLY"):
                disposition = "OWNER_REDIRECT_CLASS_UNMAPPED"
            else:
                disposition = "PICKUP_SPLIT_UNAPPROVED_OR_AMBIGUOUS"
        elif len(canonical_ids) > 1 and group_id == "mazda-mazda-cx-30" and len(exact_prior) == 1:
            target_id = exact_prior[0]["canonical_model_id"]
            target_name = exact_prior[0]["canonical_model_name"]
            disposition = "DETERMINISTIC_IDENTITY_LOCK_LINK"
            eligible = True
            reason = (
                "Exact same-brand CX-30 name match wins; the competing CX-3 row is an unapproved ADMIN structure proposal. "
                "The owner Mazda numeric identity lock keeps CX-30 distinct from CX-3."
            )
        elif len(canonical_ids) > 1:
            disposition = "PRIOR_CROSSWALK_COLLISION"
            reason = "Multiple canonical targets appear in the preserved live review; retain as a visible conflict rather than choose one."
        elif prior["status"] in {"AUTO", "PROPOSED"} and prior["canonical_model_id"]:
            target_id = prior["canonical_model_id"]
            target_name = prior["canonical_model_name"]
            disposition = "EXISTING_CROSSWALK_AUTO" if prior["status"] == "AUTO" else "EXISTING_CROSSWALK_PROPOSED"
            eligible = True
            reason = "Preserved prior M7.0 live-review crosswalk row; no identity change inferred."
        elif group_id in identities:
            target_id = identities[group_id]["canonical_model_id"]
            target_name = identities[group_id]["canonical_name_en"]
            disposition = "SHADOW_IDENTITY_MATERIALIZED"
            eligible = True
            reason = "Prior owner-approved identity target; no production catalog write."
        elif group_id in exact:
            target_id = exact[group_id]["canonical_model_id"]
            target_name = exact[group_id]["canonical_name_en"]
            disposition = "DETERMINISTIC_EXACT_EXISTING_LINK"
            eligible = True
            reason = exact[group_id]["rule"]
        elif group_id in recovery:
            target_id = recovery[group_id]["canonical_model_id"]
            disposition = "DETERMINISTIC_REJECTED_CANDIDATE_RECOVERY"
            eligible = True
            reason = recovery[group_id]["rule"]
        elif group_id in deterministic:
            target_id = deterministic[group_id]
            disposition = "DETERMINISTIC_PACKAGE_OVERRIDE"
            eligible = True
            reason = "Frozen deterministic override package; target preserved exactly."
        elif group_id in rejected:
            disposition = "INVALID_OR_OWNER_REJECTED"
            reason = "Previous candidate was explicitly rejected; no replacement inferred."
        else:
            model = dims[group_id]
            if units < 5:
                disposition = "LOW_VOLUME"
                reason = "Below 5 lifetime registrations; priority label only, not an identity inference."
            elif model["model_name"].strip() in {"", "ไม่ระบุ", "ไม่ระบุรุ่น"}:
                disposition = "INVALID_OR_UNSPECIFIED"
                reason = "Source model name is blank or explicitly unspecified."
            elif owner["effective_action"] == "OWNER_SPLIT_BY_REG_TYPE":
                disposition = "PICKUP_SPLIT_UNAPPROVED_OR_AMBIGUOUS"
                reason = "Pickup split directive exists; this class lacks an approved exact identity target."
            else:
                disposition = "GENUINELY_AMBIGUOUS"
                reason = "No frozen owner decision, exact catalog identity, or deterministic rule resolves this group."
        rows.append({
            "model_group_id": group_id,
            "source_package_model_group_id": group_id,
            "reg_type": reg_type,
            "brand": dims[group_id]["brand"],
            "source_model_name": dims[group_id]["model_name"],
            "reg_count": units,
            "prior_status": prior_status,
            "prior_canonical_id": canonical_ids[0] if len(canonical_ids) == 1 else ("MULTIPLE:" + "|".join(canonical_ids) if canonical_ids else ""),
            "prior_canonical_name": prior["canonical_model_name"],
            "decision_ref": decision_ref,
            "target_canonical_id": target_id,
            "target_name": target_name,
            "disposition": disposition,
            "classification_category": "",
            "coverage_eligible": eligible,
            "reason": reason,
            "owner_overlay_sha256": overlay_hash,
            "source_package_sha256": package_hash,
        })
    return rows, targets


def build_unmatched_classification(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    group_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        group_rows[row["model_group_id"]].append(row)
    residual = []
    unresolved_categories = {
        "INVALID_OR_UNSPECIFIED", "GENUINELY_AMBIGUOUS", "LOW_VOLUME",
        "PICKUP_SPLIT_UNAPPROVED_OR_AMBIGUOUS", "OWNER_REDIRECT_CLASS_UNMAPPED",
        "PRIOR_CROSSWALK_COLLISION",
    }
    source_unmatched = {
        row["model_group_id"] for row in read_csv(OVERLAY)
        if row["effective_action"] == "UNMATCHED_NO_CANDIDATE"
    }
    for group_id, group in group_rows.items():
        if group_id not in source_unmatched:
            continue
        resolved = [row for row in group if row["coverage_eligible"]]
        if resolved:
            if any(row["disposition"] in {"SHADOW_IDENTITY_MATERIALIZED", "OWNER_APPROVED_SHADOW_IDENTITY"} for row in resolved):
                category = "CREATE_PROPOSAL"
            else:
                category = "EXISTING/LINK"
            primary = sorted({row["disposition"] for row in resolved})[0]
        else:
            candidates = [row for row in group if row["disposition"] in unresolved_categories]
            primary = Counter(row["disposition"] for row in candidates or group).most_common(1)[0][0]
            category = primary
        residual.append({**group[0], "disposition": primary,
                         "classification_category": category,
                         "reg_count": sum(row["reg_count"] for row in group),
                         "reg_type": "ALL",
                         "coverage_eligible": bool(resolved),
                         "target_canonical_id": "|".join(sorted({row["target_canonical_id"] for row in resolved if row["target_canonical_id"]})),
                         "reason": "; ".join(sorted({row["reason"] for row in group if row["reason"]}))})
    return sorted(residual, key=lambda row: (-int(row["reg_count"]), row["model_group_id"]))


def build_qa(rows: list[dict[str, Any]], targets: dict[str, Any], unmatched: list[dict[str, Any]]) -> dict[str, Any]:
    dims, _ = package_rows()
    ledger = build_owner_ledger()
    overlay = read_csv(OVERLAY)
    overlay_action_counts = dict(Counter(row["effective_action"] for row in overlay))
    exclusions = {row["model_group_id"] for row in overlay if row["effective_action"] == "OWNER_EXCLUDE_FROM_COUNT"}
    fixed_denominator = sum(int(row["reg_total_all"] or 0) for row in dims.values())
    excluded_units = sum(int(dims[group]["reg_total_all"] or 0) for group in exclusions)
    mapped_by_group: dict[str, int] = defaultdict(int)
    for row in rows:
        if row["coverage_eligible"] and row["model_group_id"] not in exclusions:
            mapped_by_group[row["model_group_id"]] += int(row["reg_count"])
    covered = sum(mapped_by_group.values())
    adjusted_denominator = fixed_denominator - excluded_units
    category_counts = Counter(row["classification_category"] for row in unmatched)
    category_units: dict[str, int] = defaultdict(int)
    for row in unmatched:
        category_units[row["classification_category"]] += int(row["reg_count"])
    for category in (
        "EXISTING/LINK", "CREATE_PROPOSAL", "INVALID_OR_UNSPECIFIED",
        "GENUINELY_AMBIGUOUS", "LOW_VOLUME", "PICKUP_SPLIT_UNAPPROVED_OR_AMBIGUOUS",
    ):
        category_counts.setdefault(category, 0)
        category_units.setdefault(category, 0)
    expected = {
        "OWNER_LINK_EXISTING": 92, "KEEP_EXISTING_AUTO": 63,
        "OWNER_EXCLUDE_FROM_COUNT": 51, "OWNER_CREATE_IDENTITY": 38,
    }
    action_counts = dict(Counter(row["owner_action"] for row in ledger))
    if len(ledger) != 244 or action_counts != expected:
        raise ValueError(f"244 owner decision preservation check failed: {action_counts}")
    owner_decision_targets = targets["deterministic_identity_overrides"]
    owner_target_mismatches = []
    for decision in ledger:
        matching_rows = [
            row for row in rows
            if row["model_group_id"] == decision["model_group_id"]
            and (not decision["reg_type_scope"] or decision["reg_type_scope"] == row["reg_type"])
        ]
        for row in matching_rows:
            if decision["owner_action"] == "OWNER_EXCLUDE_FROM_COUNT":
                valid = row["disposition"] == "OWNER_EXCLUDED"
            else:
                valid = (
                    row["target_canonical_id"] == decision["canonical_target_id"]
                    and row["coverage_eligible"]
                    and row["disposition"] in {
                        "OWNER_APPROVED_LINK", "OWNER_APPROVED_AUTO", "OWNER_APPROVED_SHADOW_IDENTITY",
                    }
                )
            if not valid:
                owner_target_mismatches.append({
                    "model_group_id": decision["model_group_id"],
                    "reg_type": row["reg_type"],
                    "expected_action": decision["owner_action"],
                    "expected_target": decision["canonical_target_id"],
                    "actual_disposition": row["disposition"],
                    "actual_target": row["target_canonical_id"],
                })
    if owner_target_mismatches:
        raise ValueError(f"frozen owner decisions changed in shadow output: {owner_target_mismatches[:3]}")
    full_overlay_mismatches = []
    targets_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        targets_by_group[row["model_group_id"]].append(row)
    auto_targets = {row["model_group_id"]: row["canonical_model_id"] for row in targets["owner_confirmed_auto_matches"]}
    for source in overlay:
        action = source["effective_action"]
        group = source["model_group_id"]
        candidates = targets_by_group.get(group, [])
        scope = normalize_reg_type_scope(source.get("owner_registration_type", ""))
        scoped = [row for row in candidates if not scope or row["reg_type"] == scope]
        expected_target = ""
        expected_disposition = ""
        if action == "OWNER_LINK_EXISTING":
            expected_target = (source.get("owner_target_canonical_id") or source.get("owner_existing_canonical_id")
                               or source.get("target_canonical_id", ""))
            expected_disposition = "OWNER_APPROVED_LINK"
        elif action == "OWNER_CREATE_IDENTITY":
            expected_target = targets["deterministic_identity_overrides"].get(group, "")
            expected_disposition = "OWNER_APPROVED_SHADOW_IDENTITY"
        elif action == "KEEP_EXISTING_AUTO":
            expected_target = auto_targets.get(group, "")
            expected_disposition = "OWNER_APPROVED_AUTO"
        elif action == "OWNER_EXCLUDE_FROM_COUNT":
            expected_disposition = "OWNER_EXCLUDED"
        if expected_disposition and (
            not scoped or any(row["disposition"] != expected_disposition
                              or (expected_target and row["target_canonical_id"] != expected_target)
                              for row in scoped)
        ):
            full_overlay_mismatches.append({"model_group_id": group, "action": action})
    if full_overlay_mismatches:
        raise ValueError(f"complete overlay owner decisions changed in shadow output: {full_overlay_mismatches[:3]}")
    target_ids = [row["canonical_model_id"] for row in targets["identities"]]
    if len(target_ids) != len(set(target_ids)):
        raise ValueError("shadow identity targets contain duplicate canonical IDs")
    overlay_exclusions = {row["model_group_id"] for row in overlay if row["effective_action"] == "OWNER_EXCLUDE_FROM_COUNT"}
    ledger_exclusions = {row["model_group_id"] for row in ledger if row["excluded_from_coverage"]}
    return {
        "schema": "tdr.ice-crosswalk-r6-m7-shadow-qa.v1",
        "source_package_sha256": sha256(PACKAGE),
        "owner_overlay_sha256": sha256(OVERLAY),
        "source_master_version": "7.0",
        "source_period": "2569-09",
        "source_group_count": len(dims),
        "shadow_row_count": len(rows),
        "owner_decision_rows_loaded_and_respected": len(ledger),
        "owner_decision_action_counts": action_counts,
        "owner_overlay_group_count": len(overlay),
        "owner_overlay_action_counts": overlay_action_counts,
        "owner_overlay_owner_decision_mismatches": len(full_overlay_mismatches),
        "owner_decision_output_mismatches": len(owner_target_mismatches),
        "owner_target_conflicts": owner_target_mismatches,
        "owner_re_review_required": 0,
        "fixed_denominator_units": fixed_denominator,
        "owner_exclusion_units": excluded_units,
        "owner_exclusion_group_count": len(exclusions),
        "owner_exclusions_outside_244_ledger": len(overlay_exclusions - ledger_exclusions),
        "owner_exclusion_adjusted_denominator_units": adjusted_denominator,
        "shadow_covered_units": covered,
        "coverage_definition": (
            "Registration-weighted target availability in the offline shadow: frozen owner links/creates, "
            "preserved prior AUTO/PROPOSED crosswalk targets, deterministic exact links, and resolved pickup "
            "class targets. PROPOSED rows count as candidate coverage only; they are not represented as "
            "production-approved. Owner exclusions remain in the fixed denominator and are separately "
            "removed only for the adjusted denominator."
        ),
        "fixed_denominator_coverage_pct": round(covered * 100 / fixed_denominator, 4),
        "owner_exclusion_adjusted_coverage_pct": round(covered * 100 / adjusted_denominator, 4),
        "target_fixed_denominator_pct": 99.1,
        "target_fixed_denominator_units": (fixed_denominator * 991 + 999) // 1000,
        "target_met_fixed_denominator": covered * 1000 >= fixed_denominator * 991,
        "unmatched_group_count": len(unmatched),
        "unmatched_groups_deterministically_resolved": sum(row["coverage_eligible"] for row in unmatched),
        "unmatched_groups_still_unresolved": sum(not row["coverage_eligible"] for row in unmatched),
        "unmatched_categories": dict(category_counts),
        "unmatched_category_registration_units": dict(category_units),
        "shadow_identity_count": len(targets["identities"]),
        "owner_approved_identity_override_count": len(targets.get("owner_approved_identity_overrides", {})),
        "explicit_244_owner_created_identity_count": action_counts.get("OWNER_CREATE_IDENTITY", 0),
        "resolved_crosswalk_collision_group_count": len({
            row["model_group_id"] for row in rows
            if row["prior_status"] == "CROSSWALK_COLLISION" and row["coverage_eligible"]
        }),
        "shadow_identity_target_collisions": [],
        "all_shadow_only_no_production_writes": True,
        "live_current_snapshot_status": "NOT_CAPTURED_SECRET_NOT_IN_PROCESS",
        "live_review_basis": "Preserved M7.0 production live-review export; not a new live query in this process.",
        "m7_input_basis": "Exact real 2569-09 v3_M7.0 Full Package ZIP; DIMS and reg_trend totals cross-checked.",
        "scope_limitations": [
            "Shadow targets are not production vehicle_models materializations or crosswalk writes.",
            "Pickup RY splits with unapproved/missing targets are classified but not counted as covered.",
            "No live current-state query ran because SUPABASE_SECRET_KEY is unavailable to this process.",
        ],
    }


def write_recovery_outputs(output_dir: Path) -> dict[str, Any]:
    ledger = build_owner_ledger()
    exceptions = build_exception_review(ledger)
    rows, targets = build_shadow_rows()
    unmatched = build_unmatched_classification(rows)
    qa = build_qa(rows, targets, unmatched)
    replay_rows, replay_targets = build_shadow_rows()
    reproducibility = hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    replay_hash = hashlib.sha256(
        json.dumps(replay_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if reproducibility != replay_hash or targets != replay_targets:
        raise ValueError("deterministic shadow replay produced different output")
    qa["shadow_replay_reproducible"] = True
    qa["shadow_rows_sha256"] = reproducibility
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "owner_decision_ledger_244.csv", ledger, LEDGER_COLUMNS)
    write_csv(output_dir / "exception_only_review.csv", exceptions, [
        "model_group_id", "source_model_name", "prior_candidate_id", "owner_action",
        "owner_target_id", "technical_contradiction", "rule_flags", "re_review_required",
    ])
    write_csv(output_dir / "shadow_crosswalk_rows.csv", rows, CLASSIFICATION_COLUMNS)
    write_csv(output_dir / "unmatched_classification_sorted.csv", unmatched, CLASSIFICATION_COLUMNS)
    identity_cols = ["model_group_id", "brand", "canonical_model_id", "canonical_name_en",
                     "registration_units_m7_0", "owner_verdict", "registration_type",
                     "lifecycle_status", "distinct_from", "materialization_required"]
    write_csv(output_dir / "shadow_identity_materialization.csv", targets["identities"], identity_cols)
    (output_dir / "qa_summary.json").write_text(
        json.dumps(qa, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return qa


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-live", action="store_true", help="SELECT-only capture of M7.0 matcher dependencies")
    parser.add_argument("--snapshot", type=Path, default=OUT / "live_snapshot_7.0.json")
    parser.add_argument("--output-dir", type=Path, default=OUT)
    args = parser.parse_args(argv)
    if args.capture_live:
        result = build_live_snapshot(args.snapshot)
        print(json.dumps({
            "snapshot": str(args.snapshot),
            "groups": result["live_group_count"],
            "crosswalk_rows": len(result["crosswalk_rows"]),
            "vehicle_models": len(result["vehicle_models"]),
            "read_only": result["side_effects"],
        }, ensure_ascii=False, indent=2))
        return 0
    qa = write_recovery_outputs(args.output_dir)
    print(json.dumps(qa, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
