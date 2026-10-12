"""Strict, read-only adapter for locally supplied Vehicle Master exports.

This module has no database, HTTP, credential, or writer dependency.  It only
accepts a versioned JSON envelope supplied by the caller and never performs
identity resolution: canonical IDs and declared parent IDs are preserved.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .gap_inventory import gaps_for_model
from .planner import plan
from .registry_adapter import load_registry, resolve_key
from .retail_reconcile import validate_source_completeness
from .replay import _valid_document, validate_cached_source_document, ReplayContractError
from .validation import validate_fixture, validate_plan, validate_policy

CONTRACT_VERSION = "vehicle-master-shadow/1.0"
SOURCE_CONTRACT = "docs/vehicle-db/MASTER_TABLES.md + supabase/migration_v57_vehicle_master_tables.sql"
TABLE_KEYS = {
    "vehicle_models": "canonical_id", "vehicle_generations": "canonical_id",
    "vehicle_trims": "canonical_id", "vehicle_variants": "canonical_id",
    "vehicle_facts": "fact_id", "vehicle_price_ledger": "record_id",
    "vehicle_current_retail_sets": "model_id",
    "vehicle_trim_lifecycle_decisions": "trim_id",
    "vehicle_model_operational_states": "model_id",
}
TABLE_COLUMNS = {
    "vehicle_models": {"canonical_id", "brand_id", "tdr_model_id", "slug", "name_en", "name_th", "generation_id", "status", "segment", "body_type", "retail_price_min", "retail_price_max", "payload", "served_as_of", "revision", "seed_release_id", "created_at", "updated_at", "deleted_at"},
    "vehicle_generations": {"canonical_id", "model_id", "code", "segment", "launched", "ended", "payload", "revision", "seed_release_id", "created_at", "updated_at", "deleted_at"},
    "vehicle_trims": {"canonical_id", "model_id", "generation_id", "variant_id", "name", "powertrain", "status", "payload", "current_list_price", "campaign_quote", "price_history", "source_refs", "served_as_of", "catalog_payload", "origin", "revision", "seed_release_id", "created_at", "updated_at", "deleted_at"},
    "vehicle_variants": {"canonical_id", "generation_id", "model_id", "name", "powertrain", "import_type", "origin_country", "payload", "revision", "seed_release_id", "created_at", "updated_at", "deleted_at"},
    "vehicle_facts": {"fact_id", "trim_id", "field_key", "value_state", "value", "unit", "qualifiers", "effective_from", "effective_to", "observed_at", "claim_ids", "verification_status", "source", "source_ref", "source_locator", "authority", "locked", "served_in_release", "payload", "revision", "seed_release_id", "created_at", "updated_at"},
    "vehicle_price_ledger": {"record_id", "trim_id", "amount_thb", "price_type", "effective_from", "effective_to", "observed_at", "campaign_id", "option_id", "source", "source_ref", "source_document_id", "notes", "reference_price_thb", "retracted_at", "retraction_reason", "reviewed_by", "vat_included", "authority", "in_release", "payload", "seed_release_id", "created_at"},
    "vehicle_current_retail_sets": {"model_id", "trim_ids", "reviewer", "reviewed_at", "source_ref", "notes", "payload", "seed_release_id", "created_at"},
    "vehicle_trim_lifecycle_decisions": {"trim_id", "status", "reviewer", "reviewed_at", "source_ref", "notes", "payload", "seed_release_id", "created_at"},
    "vehicle_model_operational_states": {"model_id", "status", "reviewer", "reviewed_at", "source_ref", "notes", "payload", "seed_release_id", "created_at"},
}
OPTIONAL_TABLES = {"vehicle_variants", "vehicle_price_ledger", "vehicle_current_retail_sets",
                   "vehicle_trim_lifecycle_decisions", "vehicle_model_operational_states"}
REQUIRED_ENVELOPE = {"contract_version", "provenance", "vehicle_master_state", "tables", "field_priority_overlay", "evidence_cache"}
PROVENANCE_KEYS = {"kind", "snapshot_id", "exported_at", "anonymized", "source_contract", "source_schema_version"}
STATUSES = {"CURRENT", "HISTORICAL", "UNVERIFIED"}
HEX64 = re.compile(r"^[a-f0-9]{64}$")


class ShadowSnapshotError(ValueError):
    """Input is not a valid, traceable Vehicle Master shadow snapshot."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_shadow_export(export: dict) -> dict:
    """Validate the strict normalized export envelope and exact table contract."""
    if not isinstance(export, dict) or set(export) != REQUIRED_ENVELOPE:
        raise ShadowSnapshotError("export envelope must contain exactly contract_version, provenance, vehicle_master_state, tables, field_priority_overlay, evidence_cache")
    if export["contract_version"] != CONTRACT_VERSION:
        raise ShadowSnapshotError("unsupported shadow export contract_version")
    provenance = export["provenance"]
    if not isinstance(provenance, dict) or set(provenance) != PROVENANCE_KEYS:
        raise ShadowSnapshotError("provenance must match the versioned provenance contract exactly")
    if provenance["kind"] not in {"SYNTHETIC_FIXTURE", "AUTHORIZED_LOCAL_EXPORT", "ANONYMIZED_LOCAL_EXPORT"}:
        raise ShadowSnapshotError("snapshot provenance kind is not permitted")
    if not isinstance(provenance["snapshot_id"], str) or not provenance["snapshot_id"].strip():
        raise ShadowSnapshotError("provenance.snapshot_id is required")
    try:
        date.fromisoformat(provenance["exported_at"][:10])
    except (TypeError, ValueError, AttributeError):
        raise ShadowSnapshotError("provenance.exported_at must be an ISO date or timestamp") from None
    if type(provenance["anonymized"]) is not bool:
        raise ShadowSnapshotError("provenance.anonymized must be boolean")
    if provenance["kind"] != "SYNTHETIC_FIXTURE" and provenance["anonymized"] is not True:
        raise ShadowSnapshotError("non-synthetic local exports must attest to anonymization")
    if provenance["source_contract"] != SOURCE_CONTRACT or provenance["source_schema_version"] != "v57-v61" and provenance["kind"] != "SYNTHETIC_FIXTURE":
        raise ShadowSnapshotError("source contract/schema is not the documented Vehicle Master contract")
    tables = export["tables"]
    if not isinstance(tables, dict) or set(tables) - set(TABLE_KEYS) or set(TABLE_KEYS) - OPTIONAL_TABLES - set(tables):
        raise ShadowSnapshotError("tables must contain all required Vehicle Master sections and no unknown sections")
    for table, rows in tables.items():
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ShadowSnapshotError(f"{table} must be an array of objects")
        key = TABLE_KEYS[table]
        ids = [row.get(key) for row in rows]
        if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
            raise ShadowSnapshotError(f"{table}.{key} values must be non-empty and unique")
    state = export["vehicle_master_state"]
    if not isinstance(state, dict) or set(state) != {"scope", "seed_release_id", "seed_as_of", "seed_source_hash", "seed_canonical_revision"}:
        raise ShadowSnapshotError("vehicle_master_state must match the local export pin contract")
    if state["scope"] != "vehicle_master":
        raise ShadowSnapshotError("vehicle_master_state.scope must be vehicle_master")
    if provenance["kind"] != "SYNTHETIC_FIXTURE" and not all(state.get(k) for k in ("seed_release_id", "seed_source_hash", "seed_canonical_revision")):
        raise ShadowSnapshotError("local export requires release, source hash, and canonical revision provenance")
    date.fromisoformat(state["seed_as_of"])
    overlay = export["field_priority_overlay"]
    if not isinstance(overlay, dict) or any(not isinstance(k, str) or v not in {"P1", "P2", "P3"} for k, v in overlay.items()):
        raise ShadowSnapshotError("field_priority_overlay must map canonical keys to P1/P2/P3")
    if not isinstance(export["evidence_cache"], list) or any(not isinstance(doc, dict) for doc in export["evidence_cache"]):
        raise ShadowSnapshotError("evidence_cache must be an array of normalized SourceDocument objects")
    required_columns = {
        "vehicle_models": {"canonical_id", "generation_id", "status", "payload"},
        "vehicle_generations": {"canonical_id", "model_id", "payload"},
        "vehicle_trims": {"canonical_id", "model_id", "generation_id", "name", "powertrain", "status", "payload"},
        "vehicle_variants": {"canonical_id", "generation_id", "model_id", "name", "powertrain", "payload"},
        "vehicle_facts": {"fact_id", "trim_id", "field_key", "value_state", "value", "unit", "qualifiers", "verification_status", "source", "source_ref", "source_locator", "authority", "locked"},
        "vehicle_price_ledger": {"record_id", "trim_id", "amount_thb", "price_type", "in_release"},
        "vehicle_current_retail_sets": {"model_id", "trim_ids", "reviewer", "reviewed_at"},
        "vehicle_trim_lifecycle_decisions": {"trim_id", "status", "reviewer", "reviewed_at"},
        "vehicle_model_operational_states": {"model_id", "status", "reviewer", "reviewed_at"},
    }
    for table, rows in tables.items():
        for row in rows:
            unknown = set(row) - TABLE_COLUMNS[table]
            if unknown:
                raise ShadowSnapshotError(f"{table} row contains columns outside the v57 contract: {sorted(unknown)}")
            missing_columns = required_columns[table] - set(row)
            if missing_columns:
                raise ShadowSnapshotError(f"{table} row is missing v57 contract columns: {sorted(missing_columns)}")
    return export


def normalize_shadow_export(export: dict, *, repository_root: Path | None = None) -> tuple[dict, dict]:
    """Map authoritative table rows to the accepted Chunk 0–5 offline snapshot."""
    validate_shadow_export(export)
    tables = export["tables"]
    models_raw = tables["vehicle_models"]
    generations_raw = tables["vehicle_generations"]
    trims_raw = tables["vehicle_trims"]
    variants_raw = tables.get("vehicle_variants", [])
    facts_raw = tables["vehicle_facts"]
    model_ids = {r["canonical_id"] for r in models_raw}
    generations = {r["canonical_id"]: r for r in generations_raw}
    trim_ids = {r["canonical_id"] for r in trims_raw}
    variant_ids = {r["canonical_id"] for r in variants_raw}
    owner_set_models = {r["model_id"] for r in tables.get("vehicle_current_retail_sets", [])}
    trace: dict[str, dict] = {}
    stable_input = json.loads(canonical_json(export))
    for table, rows in stable_input["tables"].items():
        rows.sort(key=lambda row: row[TABLE_KEYS[table]])
    input_hash = _sha(stable_input)

    def traced(table: str, row: dict, pk: str) -> str:
        ref = f"{table}:{row[pk]}"
        trace[ref] = {"table": table, "primary_key": row[pk], "input_sha256": input_hash,
                      "row_sha256": _sha(row), "fields": sorted(row)}
        return ref

    # Parent links are authoritative canonical IDs; never repair or match them.
    identity_issues = []
    for generation in generations_raw:
        if generation.get("model_id") not in model_ids:
            identity_issues.append({"record_ref": traced("vehicle_generations", generation, "canonical_id"),
                                    "reason": "UNKNOWN_MODEL_PARENT"})
    for trim in trims_raw:
        gen = generations.get(trim.get("generation_id"))
        if trim.get("model_id") not in model_ids or gen is None or gen.get("model_id") != trim.get("model_id"):
            identity_issues.append({"record_ref": traced("vehicle_trims", trim, "canonical_id"),
                                    "reason": "MODEL_GENERATION_PARENT_MISMATCH"})
        if trim.get("variant_id") and trim["variant_id"] not in variant_ids:
            identity_issues.append({"record_ref": traced("vehicle_trims", trim, "canonical_id"),
                                    "reason": "UNRESOLVED_VARIANT_ID"})
    for variant in variants_raw:
        if variant.get("model_id") not in model_ids or generations.get(variant.get("generation_id"), {}).get("model_id") != variant.get("model_id"):
            identity_issues.append({"record_ref": traced("vehicle_variants", variant, "canonical_id"),
                                    "reason": "MODEL_GENERATION_PARENT_MISMATCH"})
    bad_generation_ids = {issue["record_ref"].split(":", 1)[1] for issue in identity_issues
                          if issue["record_ref"].startswith("vehicle_generations:")}
    for trim in trims_raw:
        if trim.get("generation_id") in bad_generation_ids:
            identity_issues.append({"record_ref": traced("vehicle_trims", trim, "canonical_id"),
                                    "reason": "GENERATION_PARENT_UNRESOLVED"})
    variant_by_id = {v["canonical_id"]: v for v in variants_raw}
    for trim in trims_raw:
        variant = variant_by_id.get(trim.get("variant_id"))
        if variant and (variant.get("model_id") != trim.get("model_id") or variant.get("generation_id") != trim.get("generation_id")):
            identity_issues.append({"record_ref": traced("vehicle_trims", trim, "canonical_id"),
                                    "reason": "TRIM_VARIANT_PARENT_MISMATCH"})
    bad_trim_ids = {issue["record_ref"].split(":", 1)[1] for issue in identity_issues if issue["record_ref"].startswith("vehicle_trims:")}
    bad_model_ids = {issue["record_ref"].split(":", 1)[1] for issue in identity_issues if issue["record_ref"].startswith("vehicle_models:")}
    registry = load_registry(root=repository_root)
    priority_overlay = export.get("field_priority_overlay") or {}
    unknown_priority_keys = set(priority_overlay) - set(registry["fields"])
    if unknown_priority_keys:
        raise ShadowSnapshotError(f"field priority overlay uses noncanonical/unknown registry keys: {sorted(unknown_priority_keys)}")
    maintenance_models = {r["model_id"] for r in tables.get("vehicle_model_operational_states", [])
                          if r.get("status") == "UNDER_MAINTENANCE"}
    # A cached document is evidence only after the accepted Chunk 3 validator
    # rechecks raw/content hashes, completeness, pagination and capture binding.
    # One generation document cannot establish a multi-generation model lineup.
    complete_docs_by_model: dict[str, list[dict]] = {}
    validated_documents = []
    evidence_issues = []
    for doc in sorted(export["evidence_cache"], key=lambda r: str(r.get("document_id", ""))):
        ref = f"evidence_cache:{doc.get('document_id', 'MISSING_ID')}"
        trace[ref] = {"table": "local_evidence_cache", "primary_key": doc.get("document_id"),
                      "input_sha256": input_hash, "row_sha256": _sha(doc), "fields": sorted(doc)}
        try:
            _valid_document(doc)
            verdict = validate_source_completeness(doc)
        except (ReplayContractError, KeyError, TypeError, ValueError) as exc:
            evidence_issues.append({"record_ref": ref, "reason": "SOURCE_DOCUMENT_INVALID", "detail": str(exc)})
            continue
        validated_documents.append(doc)
        if doc.get("source_kind") != "RETAIL_LINEUP":
            continue
        verdict = validate_source_completeness(doc)
        doc_gen = generations.get(doc.get("generation_id"))
        doc_trim_rows = [next((t for t in trims_raw if t["canonical_id"] == tid), None) for tid in doc.get("trim_ids", [])]
        exact_identity_scope = (doc_gen is not None and doc_gen.get("model_id") == doc.get("model_id")
            and all(t is not None and t.get("model_id") == doc.get("model_id")
                    and t.get("generation_id") == doc.get("generation_id") and t.get("status") == "CURRENT"
                    and not t.get("deleted_at") for t in doc_trim_rows))
        if (verdict["complete"] and doc.get("market") == "TH" and doc.get("source_authority") == "OFFICIAL"
                and doc.get("model_id") in model_ids and doc.get("generation_id") in generations and exact_identity_scope):
            complete_docs_by_model.setdefault(doc["model_id"], []).append(doc)
        else:
            evidence_issues.append({"record_ref": ref, "reason": "SOURCE_DOCUMENT_INCOMPLETE_OR_SCOPE_UNRESOLVED"})
    model_rows = []
    for row in sorted(models_raw, key=lambda r: r["canonical_id"]):
        payload = row.get("payload") or {}
        status = row.get("status")
        if status not in STATUSES or not isinstance(payload, dict):
            raise ShadowSnapshotError(f"unsupported canonical model status for {row['canonical_id']}")
        if row.get("generation_id") is not None and (row["generation_id"] not in generations or generations[row["generation_id"]].get("model_id") != row["canonical_id"]):
            bad_model_ids.add(row["canonical_id"])
            identity_issues.append({"record_ref": traced("vehicle_models", row, "canonical_id"), "reason": "CURRENT_GENERATION_PARENT_MISMATCH"})
        elif row.get("status") == "CURRENT" and not row.get("generation_id"):
            bad_model_ids.add(row["canonical_id"])
            identity_issues.append({"record_ref": traced("vehicle_models", row, "canonical_id"), "reason": "CURRENT_GENERATION_UNRESOLVED"})
        blocked_status = row["canonical_id"] in bad_model_ids or row["canonical_id"] in maintenance_models
        model_row = {"id": row["canonical_id"], "status": "UNVERIFIED" if blocked_status else status,
                           "deleted_at": row.get("deleted_at"), "upcoming": payload.get("upcoming") is True,
                           "admin_retired": payload.get("admin_retired") is True,
                           "specs": _canonical_payload(payload, registry),
                           "_record_ref": traced("vehicle_models", row, "canonical_id")}
        docs = complete_docs_by_model.get(row["canonical_id"], [])
        model_gens = sorted(g["canonical_id"] for g in generations_raw if g.get("model_id") == row["canonical_id"] and not g.get("deleted_at"))
        if (not blocked_status and status == "CURRENT" and row["canonical_id"] not in owner_set_models
                and len(model_gens) == 1 and len(docs) == 1 and docs[0].get("generation_id") == model_gens[0]
                and docs[0].get("generation_id") == row.get("generation_id")):
            doc = docs[0]
            model_row["lineup_evidence"] = {"market": "TH", "source_authority": "OFFICIAL",
                "completeness": "COMPLETE_LINEUP", "document_id": doc["document_id"],
                "document_sha256": doc["content_sha256"], "captured_at": doc["captured_at"],
                "model_id": row["canonical_id"], "generation_id": doc["generation_id"],
                "trim_ids": doc["trim_ids"], "source_document": doc,
                "_record_ref": f"evidence_cache:{doc['document_id']}"}
        model_rows.append(model_row)
    generation_rows = [{"id": row["canonical_id"], "model_id": row.get("model_id"),
                        "specs": _canonical_payload(row.get("payload") or {}, registry),
                        "_record_ref": traced("vehicle_generations", row, "canonical_id")}
                       for row in sorted(generations_raw, key=lambda r: r["canonical_id"])
                       if row["canonical_id"] not in bad_generation_ids]
    variant_rows = [{"id": row["canonical_id"], "model_id": row.get("model_id"),
                     "generation_id": row.get("generation_id"), "powertrain": row.get("powertrain"),
                     "specs": _canonical_payload(row.get("payload") or {}, registry),
                     "_record_ref": traced("vehicle_variants", row, "canonical_id")}
                    for row in sorted(variants_raw, key=lambda r: r["canonical_id"])]
    lifecycle = {r["trim_id"]: r for r in tables.get("vehicle_trim_lifecycle_decisions", [])}
    for decision in lifecycle.values():
        if decision["trim_id"] not in trim_ids or decision.get("status") not in {"CURRENT", "HISTORICAL"}:
            raise ShadowSnapshotError("trim lifecycle decision does not bind a supported canonical trim status")
    operational_refs = {r["model_id"]: traced("vehicle_model_operational_states", r, "model_id")
                        for r in tables.get("vehicle_model_operational_states", [])}
    trim_rows = []
    for row in sorted(trims_raw, key=lambda r: r["canonical_id"]):
        decision = lifecycle.get(row["canonical_id"])
        if decision and decision.get("status") not in {"CURRENT", "HISTORICAL"}:
            raise ShadowSnapshotError(f"invalid human lifecycle decision for {row['canonical_id']}")
        effective_status = decision["status"] if decision else row.get("status")
        if effective_status not in STATUSES or not isinstance(row.get("powertrain"), str) or not row["powertrain"]:
            raise ShadowSnapshotError(f"invalid trim status for {row['canonical_id']}")
        payload = row.get("payload") or {}
        catalog_payload = row.get("catalog_payload") or {}
        if not isinstance(payload, dict) or not isinstance(catalog_payload, dict):
            raise ShadowSnapshotError(f"trim payload must be an object for {row['canonical_id']}")
        trim_rows.append({"id": row["canonical_id"], "model_id": row.get("model_id"),
                          "generation_id": row.get("generation_id"), "variant_id": row.get("variant_id"),
                          "status": effective_status, "powertrain": row.get("powertrain"),
                          "deleted_at": row.get("deleted_at"), "admin_retired": payload.get("admin_retired") is True,
                          "owner_retired": bool(decision and decision.get("status") == "HISTORICAL"),
                          "specs": _canonical_payload({**catalog_payload, **payload}, registry),
                          "_record_ref": traced("vehicle_trims", row, "canonical_id"),
                          "_lifecycle_ref": traced("vehicle_trim_lifecycle_decisions", decision, "trim_id") if decision else None})
    facts = []
    fact_duplicates = []
    seen_fact: dict[tuple, dict] = {}
    for row in sorted(facts_raw, key=lambda r: r["fact_id"]):
        ref = traced("vehicle_facts", row, "fact_id")
        if row.get("trim_id") not in trim_ids:
            identity_issues.append({"record_ref": ref, "reason": "UNKNOWN_TRIM_PARENT"})
            continue
        if row.get("value_state") not in {"KNOWN", "UNKNOWN", "NOT_AVAILABLE", "NOT_APPLICABLE", "ABSENT"}:
            raise ShadowSnapshotError(f"invalid value_state in vehicle_facts:{row['fact_id']}")
        if row.get("verification_status") not in {"VERIFIED", "PROVISIONAL"}:
            raise ShadowSnapshotError(f"invalid verification_status in vehicle_facts:{row['fact_id']}")
        if not isinstance(row.get("qualifiers"), dict) or not isinstance(row.get("unit"), str):
            raise ShadowSnapshotError(f"invalid qualifiers/unit in vehicle_facts:{row['fact_id']}")
        if row.get("value_state") == "KNOWN" and row.get("value") is None:
            raise ShadowSnapshotError(f"KNOWN fact requires value: {row['fact_id']}")
        canonical_fact_key = resolve_key(row["field_key"], registry) or row["field_key"]
        key = (row["trim_id"], canonical_fact_key, row.get("effective_from"), row.get("effective_to"), canonical_json(row.get("qualifiers") or {}))
        prior = seen_fact.get(key)
        if prior and all(prior.get(k) == row.get(k) for k in ("value_state", "value", "unit", "verification_status", "source", "source_ref", "source_locator", "locked")):
            fact_duplicates.append({"record_ref": ref, "duplicate_of": f"vehicle_facts:{prior['fact_id']}"})
            continue
        seen_fact.setdefault(key, row)
        facts.append({"trim_id": row["trim_id"], "field_key": canonical_fact_key,
                      "value": row.get("value"), "unit": row.get("unit", ""),
                      "value_state": row["value_state"], "verification_status": row["verification_status"],
                      "source_ref": (row.get("source_ref") if row.get("source") and row.get("source_ref") and row.get("source_locator") else None),
                      "source": row.get("source") or None,
                      "source_locator": row.get("source_locator") or None,
                      "locked": bool(row.get("locked")), "authority": row.get("authority"),
                      "qualifiers": row.get("qualifiers") or {}, "effective_from": row.get("effective_from"),
                      "effective_to": row.get("effective_to"), "observed_at": row.get("observed_at"),
                      "_record_ref": ref})
    # Registry is loaded from canonical pinned JSON; P1/P2 is an explicit policy overlay.
    # Only known canonical registry fields with a declared overlay become tasks.
    field_registry = []
    for key, definition in sorted(registry["fields"].items()):
        tier = priority_overlay.get(key)
        if tier not in {"P1", "P2", "P3"}:
            continue
        field_registry.append({"key": key, "group": definition["group"], "tier": tier,
                               "applicable_powertrains": definition.get("applicable_powertrains", []),
                               "comparison_qualifiers": definition.get("comparison_qualifiers", []),
                               "canonical_unit": definition.get("canonical_unit")})
    if not field_registry:
        raise ShadowSnapshotError("field_priority_overlay must explicitly map at least one canonical field")
    retail_sets = []
    for row in tables.get("vehicle_current_retail_sets", []):
        if not row.get("reviewer") or not row.get("reviewed_at"):
            raise ShadowSnapshotError("owner-approved retail membership requires reviewer and reviewed_at")
        date.fromisoformat(row["reviewed_at"])
        if not isinstance(row.get("trim_ids"), list) or not row["trim_ids"]:
            raise ShadowSnapshotError("vehicle_current_retail_sets.trim_ids must be nonempty")
        if row["model_id"] not in model_ids or any(tid not in trim_ids for tid in row["trim_ids"]):
            raise ShadowSnapshotError("owner retail set references unknown canonical model or trim ID")
        retail_sets.append({"model_id": row["model_id"], "trim_ids": row["trim_ids"],
                            "reviewer": row["reviewer"], "reviewed_at": row["reviewed_at"],
                            "revision": row.get("revision"), "_record_ref": traced("vehicle_current_retail_sets", row, "model_id")})
    # Price Ledger is trace-only and cannot enter the spec fact universe.
    prices = [{"record_ref": traced("vehicle_price_ledger", row, "record_id"), "trim_id": row.get("trim_id"),
               "price_type": row.get("price_type"), "amount_thb": row.get("amount_thb"),
               "in_release": row.get("in_release")} for row in tables.get("vehicle_price_ledger", [])]
    for fact in facts:
        source_ref = fact.get("source_ref")
        if source_ref and not source_ref.startswith(("fixture://", "cas://", "evidence://", "sha256:")):
            # URLs can be provenance in a legitimate export but must never be fetched here.
            fact["source_ref_kind"] = "UNFETCHED_REFERENCE"
    snapshot = {"schema_version": "0.1", "as_of": export["vehicle_master_state"]["seed_as_of"],
                "models": model_rows, "generations": generation_rows, "trims": trim_rows,
                "variants": variant_rows, "facts": facts, "field_registry": field_registry,
                "current_retail_sets": retail_sets, "registration_signals": []}
    # Parent inconsistency is surfaced separately, rather than guessed away.
    # To keep existing gap/planner contracts safe, invalid trims are excluded from gap scope.
    safe_snapshot = json.loads(canonical_json(snapshot))
    safe_snapshot["trims"] = [t for t in safe_snapshot["trims"] if t["id"] not in bad_trim_ids]
    safe_trim_ids = {t["id"] for t in safe_snapshot["trims"]}
    safe_snapshot["facts"] = [f for f in safe_snapshot["facts"] if f["trim_id"] in safe_trim_ids]
    invalid_owner_models = {s["model_id"] for s in safe_snapshot["current_retail_sets"]
                            if not set(s["trim_ids"]) <= safe_trim_ids}
    for model in safe_snapshot["models"]:
        if model["id"] in invalid_owner_models:
            model["status"] = "UNVERIFIED"
            identity_issues.append({"record_ref": "vehicle_current_retail_sets:" + model["id"],
                                    "reason": "OWNER_SET_REFERENCES_AMBIGUOUS_TRIM"})
    safe_snapshot["current_retail_sets"] = [s for s in safe_snapshot["current_retail_sets"] if s["model_id"] not in invalid_owner_models]
    validate_fixture(safe_snapshot)
    meta = {"input_sha256": input_hash, "row_trace": trace, "identity_issues": identity_issues,
            "exact_duplicate_facts": fact_duplicates, "price_ledger_rows": prices,
            "evidence_issues": evidence_issues,
            "validated_documents": validated_documents,
            "operational_refs": operational_refs,
            "field_priority_overlay": priority_overlay,
            "provenance": json.loads(canonical_json(export["provenance"])),
            "production_coverage": "UNKNOWN" if export["provenance"]["kind"] == "SYNTHETIC_FIXTURE" else "LOCAL_EXPORT_ONLY"}
    return safe_snapshot, meta


def _canonical_payload(payload: dict, registry: dict) -> dict:
    result = {}
    for key, value in payload.items():
        field_name = key
        if isinstance(value, dict) and "value" in value:
            field_name = value.get("field_key", key)
            value = value["value"]
        target = resolve_key(field_name, registry)
        if target:
            if target in result and result[target] != value:
                raise ShadowSnapshotError(f"conflicting payload aliases for {target}")
            result[target] = value
    return result


def build_shadow_report(export: dict, policy: dict, *, repository_root: Path | None = None) -> dict:
    """Create deterministic coverage, gap, queue, budget and lineage report."""
    validate_policy(policy)
    snapshot, meta = normalize_shadow_export(export, repository_root=repository_root)
    plan_result = plan(snapshot, policy)
    validate_plan(plan_result)
    cached_evidence = []
    replay_issues = list(meta["evidence_issues"])
    for doc in sorted(meta["validated_documents"], key=lambda r: r["document_id"]):
        ref = f"evidence_cache:{doc['document_id']}"
        try:
            replayed = validate_cached_source_document(snapshot, doc)
            cached_evidence.append({"record_ref": ref, "document_id": doc["document_id"],
                                    "accepted_claims": replayed["accepted_claims"],
                                    "retail_lineup_validated": replayed["retail_lineup_validated"]})
        except (ReplayContractError, KeyError, TypeError, ValueError) as exc:
            replay_issues.append({"record_ref": ref, "reason": "EVIDENCE_REPLAY_HELD", "detail": str(exc)})
    owner_sets = {r["model_id"]: r for r in snapshot["current_retail_sets"]}
    operational = {r["model_id"]: r for r in export["tables"].get("vehicle_model_operational_states", [])}
    model_status_counts = Counter()
    trim_class_counts = Counter()
    all_gaps, samples, false_gaps, duplicate_rows, classification_trace = [], [], [], [], []
    model_trace = {r["id"]: r.get("_record_ref") for r in snapshot["models"]}
    trim_trace = {r["id"]: r.get("_record_ref") for r in snapshot["trims"]}
    planner_decisions = {row["model_id"]: row for row in plan_result["decisions"]}
    for model in sorted(snapshot["models"], key=lambda r: r["id"]):
        status = model.get("status")
        if model.get("deleted_at"):
            bucket = "DELETED"
        elif model.get("upcoming"):
            bucket = "UPCOMING"
        elif status == "HISTORICAL":
            bucket = "HISTORICAL"
        elif status == "UNVERIFIED":
            bucket = "UNVERIFIED"
        elif model["id"] in operational:
            bucket = "UNDER_MAINTENANCE"
        elif planner_decisions[model["id"]]["eligibility"] == "ELIGIBLE_ENRICH":
            bucket = "ELIGIBLE_CURRENT"
        elif planner_decisions[model["id"]]["eligibility"] == "RETAIL_AUDIT_ONLY":
            bucket = "RETAIL_AUDIT_ONLY"
        else:
            bucket = "IDENTITY_OR_POLICY_UNRESOLVED"
        model_status_counts[bucket] += 1
        owner_set_ref = owner_sets.get(model["id"], {}).get("_record_ref")
        classification_trace.append({"entity_type": "MODEL", "canonical_id": model["id"], "classification": bucket,
                                      "input_record_refs": sorted(r for r in (model_trace[model["id"]], owner_set_ref,
                                          meta["operational_refs"].get(model["id"]),
                                          (model.get("lineup_evidence") or {}).get("_record_ref")) if r)})
        for trim in sorted((t for t in snapshot["trims"] if t["model_id"] == model["id"]), key=lambda r: r["id"]):
            trim_decision = next((d["decision"] for d in planner_decisions[model["id"]]["trim_decisions"]
                                  if d["trim_id"] == trim["id"]), "HOLD_IDENTITY")
            if trim.get("deleted_at"):
                trim_bucket = "DELETED"
            elif trim.get("admin_retired") or trim.get("owner_retired") or trim.get("status") == "HISTORICAL":
                trim_bucket = "RETIRED_OR_HISTORICAL"
            elif bucket in {"DELETED", "UPCOMING", "HISTORICAL"}:
                trim_bucket = bucket
            elif bucket == "UNVERIFIED":
                trim_bucket = "EXCLUDED_UNVERIFIED"
            elif bucket == "UNDER_MAINTENANCE":
                trim_bucket = "EXCLUDED_UNDER_MAINTENANCE"
            elif trim.get("status") == "UNVERIFIED":
                trim_bucket = "RETAIL_AUDIT_ONLY"
            elif trim_decision == "ELIGIBLE_ENRICH":
                trim_bucket = "ELIGIBLE_CURRENT"
            elif trim_decision == "RETAIL_AUDIT_ONLY":
                trim_bucket = "RETAIL_AUDIT_ONLY"
            elif trim_decision == "EXCLUDED_NON_MEMBER":
                trim_bucket = "EXCLUDED_NON_MEMBER"
            else:
                trim_bucket = "IDENTITY_OR_POLICY_UNRESOLVED"
            trim_class_counts[trim_bucket] += 1
            classification_trace.append({"entity_type": "TRIM", "canonical_id": trim["id"], "classification": trim_bucket,
                                          "input_record_refs": sorted(r for r in (trim_trace.get(trim["id"]), trim.get("_lifecycle_ref")) if r)})
        if bucket != "ELIGIBLE_CURRENT":
            continue
        plan_decision = planner_decisions[model["id"]]
        enrichable_ids = tuple(sorted(d["trim_id"] for d in plan_decision["trim_decisions"]
                                      if d["decision"] == "ELIGIBLE_ENRICH"))
        if not enrichable_ids:
            continue
        result = gaps_for_model(snapshot, enrichable_ids)
        for disp in result["dispositions"]:
            fact_refs = sorted(f["_record_ref"] for f in snapshot["facts"]
                               if f["trim_id"] == disp["trim_id"] and f["field_key"] == disp["field_key"])
            row = {**disp, "model_id": model["id"], "model_record_ref": model_trace[model["id"]],
                   "trim_record_ref": trim_trace.get(disp["trim_id"]), "fact_record_refs": fact_refs}
            state = disp["state"]
            if state in {"MISSING", "UNKNOWN", "NOT_AVAILABLE", "NEEDS_SOURCE_TRACE", "NEEDS_QUALIFIER_REVIEW"}:
                all_gaps.append(row)
            else:
                false_gaps.append({**row, "false_gap_reason": state})
            samples.append(row)
    for duplicate in meta["exact_duplicate_facts"]:
        duplicate_rows.append({**duplicate, "classification": "DUPLICATE_FACT_ROW"})
    audit_queue = plan_result["queues"]["RETAIL_AUDIT"]
    spec_queue = plan_result["queues"]["SPEC_ENRICH"]
    p1 = sum(1 for gap in all_gaps if _tier(snapshot, gap["field_key"]) == "P1")
    p2 = sum(1 for gap in all_gaps if _tier(snapshot, gap["field_key"]) == "P2")
    report = {
        "report_schema_version": "vehicle-master-shadow-report/1.0",
        "snapshot": {"snapshot_id": export["provenance"]["snapshot_id"],
                     "provenance_kind": export["provenance"]["kind"],
                     "production_coverage": meta["production_coverage"], "as_of": snapshot["as_of"],
                     "input_sha256": meta["input_sha256"]},
        "authority_mapping": {"schema_reference": SOURCE_CONTRACT,
                              "registry_reference": "vehreg/data/2026/product/comparable_specs/registry.json",
                              "registry_sha256": load_registry(root=repository_root)["registry_sha256"],
                              "canonical_ids_preserved": True, "legacy_catalog_authority": False,
                              "serving_views_authority": False},
        "coverage": {"models_by_class": dict(sorted(model_status_counts.items())),
                     "trims_by_class": dict(sorted(trim_class_counts.items())),
                     "eligible_current_models": model_status_counts["ELIGIBLE_CURRENT"],
                     "retail_audit_only_models": model_status_counts["RETAIL_AUDIT_ONLY"],
                     "excluded_or_unverified_models": sum(n for k, n in model_status_counts.items() if k not in {"ELIGIBLE_CURRENT", "RETAIL_AUDIT_ONLY"}),
                     "identity_ambiguities": len(meta["identity_issues"])},
        "gaps": {"real_or_researchable": len(all_gaps), "p1": p1, "p2": p2,
                 "false_or_non_gap_dispositions": len(false_gaps), "duplicate_fact_rows": len(duplicate_rows),
                 "conflicts_and_identity_holds": len(meta["identity_issues"]) + sum(1 for s in samples if s["state"] == "CONFLICT"),
                 "items": sorted(all_gaps, key=lambda r: (r["model_id"], r["trim_id"], r["field_key"])),
                 "false_gap_checks": sorted(false_gaps, key=lambda r: (r["model_id"], r["trim_id"], r["field_key"], r["state"]))},
        "research": {"retail_audit_jobs": len(audit_queue), "spec_enrich_jobs": len(spec_queue),
                     "retail_audit_job_keys": [r["job_key"] for r in audit_queue],
                     "spec_enrich_job_keys": [r["job_key"] for r in spec_queue],
                     "estimated_source_work_units": len(audit_queue) + len(spec_queue),
                     "estimated_retrieval_requests_if_authorized": len(audit_queue) + len(spec_queue),
                     "authorized_retrieval_requests": 0, "estimated_paid_tokens": None,
                     "estimated_spend_thb": None, "authorized_paid_tokens": 0, "authorized_spend_thb": 0,
                     "estimate_method": "one-document-per-planned-job lower bound; provider cost is not modeled",
                     "budget_exposure": "OFFLINE_MOCK_ZERO_EXTERNAL_COST"},
        "price_ledger": {"rows_trace_only": len(meta["price_ledger_rows"]), "spec_gap_inputs": 0,
                         "trace": meta["price_ledger_rows"]},
        "identity_issues": sorted(meta["identity_issues"], key=lambda r: (r["record_ref"], r["reason"])),
        "evidence_issues": sorted(replay_issues, key=lambda r: (r["record_ref"], r["reason"])),
        "cached_evidence": cached_evidence,
        "duplicate_fact_rows": sorted(duplicate_rows, key=lambda r: r["record_ref"]),
        "row_trace": dict(sorted(meta["row_trace"].items())),
        "sample_trace": sorted(samples, key=lambda r: (r["model_id"], r["trim_id"], r["field_key"], r["state"])),
        "classification_trace": sorted(classification_trace, key=lambda r: (r["entity_type"], r["canonical_id"])),
        "activity": {"external_http_calls": 0, "paid_ai_calls": 0, "paid_search_calls": 0,
                     "paid_tokens": 0, "paid_spend_thb": 0, "production_database_accesses": 0,
                     "canonical_writes": 0, "background_workers": 0},
        "structural_evidence_policy": policy["structural_evidence"]["approval_status"],
    }
    validate_shadow_report(report)
    return report


def validate_shadow_report(report: dict) -> None:
    required = {"report_schema_version", "snapshot", "authority_mapping", "coverage", "gaps", "research",
                "price_ledger", "identity_issues", "evidence_issues", "cached_evidence", "duplicate_fact_rows", "sample_trace", "classification_trace", "row_trace",
                "activity", "structural_evidence_policy"}
    if not isinstance(report, dict) or set(report) != required or report.get("report_schema_version") != "vehicle-master-shadow-report/1.0":
        raise ShadowSnapshotError("shadow report does not match output contract version")
    if report["structural_evidence_policy"] != "PENDING_OWNER_APPROVAL":
        raise ShadowSnapshotError("shadow output must preserve the pending structural-evidence policy")
    if any(value != 0 for value in report["activity"].values()):
        raise ShadowSnapshotError("shadow output reports prohibited external, paid, Production, write or worker activity")
    if report["snapshot"]["production_coverage"] not in {"UNKNOWN", "LOCAL_EXPORT_ONLY"}:
        raise ShadowSnapshotError("shadow report cannot claim Production coverage")
    trace = report["row_trace"]
    if set(report["activity"]) != {"external_http_calls", "paid_ai_calls", "paid_search_calls", "paid_tokens",
                                    "paid_spend_thb", "production_database_accesses", "canonical_writes", "background_workers"}:
        raise ShadowSnapshotError("shadow report activity fields do not match the zero-activity contract")
    if report["research"]["authorized_retrieval_requests"] != 0 or report["research"]["authorized_paid_tokens"] != 0 or report["research"]["authorized_spend_thb"] != 0:
        raise ShadowSnapshotError("shadow report exceeds the authorized zero-work budget")
    if (report["research"]["estimated_source_work_units"] != report["research"]["retail_audit_jobs"] + report["research"]["spec_enrich_jobs"]
            or report["research"]["estimated_retrieval_requests_if_authorized"] != report["research"]["estimated_source_work_units"]):
        raise ShadowSnapshotError("source-work estimate does not reconcile with the independent queues")
    if report["gaps"]["real_or_researchable"] != len(report["gaps"]["items"]):
        raise ShadowSnapshotError("gap count does not match item sample contract")
    if report["gaps"]["false_or_non_gap_dispositions"] != len(report["gaps"]["false_gap_checks"]):
        raise ShadowSnapshotError("non-gap disposition count does not match item sample contract")
    for row in trace.values():
        if set(row) != {"table", "primary_key", "input_sha256", "row_sha256", "fields"} or not HEX64.fullmatch(row["input_sha256"]) or not HEX64.fullmatch(row["row_sha256"]):
            raise ShadowSnapshotError("row trace entry is incomplete or has an invalid content hash")
    references = [row.get("model_record_ref") for row in report["sample_trace"]]
    references.extend(row.get("trim_record_ref") for row in report["sample_trace"])
    references.extend(ref for row in report["sample_trace"] for ref in row.get("fact_record_refs", []))
    references.extend(row.get("record_ref") for row in report["identity_issues"])
    references.extend(row.get("record_ref") for row in report["evidence_issues"])
    references.extend(row.get("record_ref") for row in report["cached_evidence"])
    references.extend(row.get("record_ref") for row in report["price_ledger"]["trace"])
    references.extend(ref for row in report["classification_trace"] for ref in row.get("input_record_refs", []))
    if any(ref is not None and ref not in trace for ref in references):
        raise ShadowSnapshotError("shadow report contains unresolved row-level trace references")


def _tier(snapshot: dict, key: str) -> str | None:
    return next((row["tier"] for row in snapshot["field_registry"] if row["key"] == key), None)


def write_shadow_report(input_path: Path, policy_path: Path, output_path: Path, *, repository_root: Path | None = None) -> dict:
    export = json.loads(input_path.read_text(encoding="utf-8"))
    policy = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.suffix == ".json" else _load_yaml(policy_path)
    report = build_shadow_report(export, policy, repository_root=repository_root)
    output_path.write_text(canonical_json(report) + "\n", encoding="utf-8")
    return report


def _load_yaml(path: Path) -> dict:
    # Existing policy.yaml contains JSON-compatible YAML; parse without a new runtime dependency.
    return json.loads(path.read_text(encoding="utf-8"))
