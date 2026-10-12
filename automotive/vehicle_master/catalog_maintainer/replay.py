"""Deterministic, local-only evidence replay for a bounded source grammar."""
from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import re
from dataclasses import asdict
import tempfile

from .eligibility import evaluate_model
from .gap_inventory import gaps_for_model
from .registry_adapter import adapt_snapshot, load_registry, resolve_key
from .replay_contracts import FieldCandidate, FieldDisposition, ReplayReport, ReplaySummary, SourceClaim, SourceDocument
from .retail_reconcile import validate_source_completeness, validate_source_representation
from .validation import validate_fixture

SCHEMA_VERSION = "1.0"
LINE_RE = re.compile(r"^claim\|([^|]+)\|([^|]+)\|([^|]+)(?:\|(.*))?$")
NUMBER_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*([A-Za-z%/]+)?\s*$")
RANGE_BASES = {"NEDC", "WLTP", "CLTC"}
RANGE_SCOPES = {"FULL", "ELECTRIC_ONLY"}
SUPPORTED = {
    "engine.displacement_cc", "powertrain.max_power_kw", "battery.catalog_capacity_kwh",
    "ev.rated_range_km", "vehicle.length_mm", "vehicle.width_mm", "vehicle.height_mm",
    "vehicle.wheelbase_mm", "vehicle.seats", "safety.aeb", "safety.airbag_count",
}


class ReplayContractError(ValueError):
    pass


def _stable(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _jsonl(rows: list[dict]) -> str:
    return "".join(_stable(row) + "\n" for row in rows)


def _valid_document(doc: dict) -> SourceDocument:
    required = {"schema_version", "document_id", "source_id", "market", "model_id", "generation_id",
                "trim_ids", "source_authority", "local_source_id", "content", "content_sha256",
                "captured_at", "completeness", "extraction_method", "source_kind"}
    missing = sorted(required - doc.keys())
    if missing:
        raise ReplayContractError(f"document missing keys: {missing}")
    if doc["schema_version"] != SCHEMA_VERSION or doc["market"] not in {"TH", "OTHER"}:
        raise ReplayContractError("unsupported document schema or market")
    if not isinstance(doc["trim_ids"], list) or len(doc["trim_ids"]) != len(set(doc["trim_ids"])):
        raise ReplayContractError("trim_ids must be a unique array")
    if any(not isinstance(value, str) or not value for value in doc["trim_ids"]):
        raise ReplayContractError("trim_ids must contain nonempty strings")
    for mapping_key in ("trim_variant_ids", "powertrain_by_trim", "model_year_by_trim"):
        mapping = doc.get(mapping_key, {})
        if not isinstance(mapping, dict) or not set(mapping) <= set(doc["trim_ids"]):
            raise ReplayContractError(f"{mapping_key} must map only declared trim_ids")
        if mapping_key != "model_year_by_trim" and any(not isinstance(value, str) or not value for value in mapping.values()):
            raise ReplayContractError(f"{mapping_key} values must be nonempty strings")
        if mapping_key == "model_year_by_trim" and any(type(value) is not int for value in mapping.values()):
            raise ReplayContractError("model_year_by_trim values must be integer model years")
    if doc["source_authority"] not in {"OFFICIAL", "ADMIN", "SECONDARY"}:
        raise ReplayContractError("invalid source_authority")
    if doc["source_kind"] not in {"SPEC_SHEET", "RETAIL_LINEUP"}:
        raise ReplayContractError("invalid source_kind")
    if not doc["local_source_id"].startswith(("fixture://", "file://")):
        raise ReplayContractError("replay accepts fixture:// or file:// source identifiers only")
    if doc["completeness"] not in {"COMPLETE_LINEUP", "PARTIAL_TRIM_LIST", "INDIVIDUAL_TRIM", "SPEC_ONLY"}:
        raise ReplayContractError("invalid document completeness")
    if doc["completeness"] in {"COMPLETE_LINEUP", "PARTIAL_TRIM_LIST"} and doc["source_kind"] != "RETAIL_LINEUP":
        raise ReplayContractError("lineup completeness requires source_kind=RETAIL_LINEUP")
    if doc["extraction_method"] != "CONTROLLED_LINE_READER_V1":
        raise ReplayContractError("unsupported extraction method")
    date.fromisoformat(doc["captured_at"])
    if doc.get("published_at"):
        date.fromisoformat(doc["published_at"])
    if not isinstance(doc["content"], str) or hashlib.sha256(doc["content"].encode("utf-8")).hexdigest() != doc["content_sha256"]:
        raise ReplayContractError("content hash mismatch")
    representation=validate_source_representation(doc)
    if not representation["valid"]:
        raise ReplayContractError("source representation is not raw-bound: " + ",".join(representation["reason_codes"]))
    manifest = doc.get("capture_manifest")
    if doc["completeness"] in {"COMPLETE_LINEUP", "PARTIAL_TRIM_LIST"}:
        if not isinstance(manifest, dict) or not isinstance(manifest.get("listed_trim_ids"), list):
            raise ReplayContractError("lineup completeness requires a capture_manifest with listed_trim_ids")
        if (not isinstance(manifest.get("pagination_complete"), bool)
                or type(manifest.get("source_page_count")) is not int
                or type(manifest.get("row_count")) is not int):
            raise ReplayContractError("capture_manifest needs pagination_complete, source_page_count and row_count")
        body_ids = [line.split("|", 2)[2] for line in doc["content"].splitlines()
                    if line.startswith("lineup|trim|") and len(line.split("|", 2)) == 3]
        if body_ids != manifest["listed_trim_ids"] or len(body_ids) != manifest["row_count"]:
            raise ReplayContractError("capture_manifest does not match explicit lineup rows")
        if set(body_ids) != set(doc["trim_ids"]):
            raise ReplayContractError("document trim_ids do not match captured lineup rows")
        if manifest["source_page_count"] < 0 or manifest["row_count"] < 0:
            raise ReplayContractError("capture manifest counts must be nonnegative")
        if doc["completeness"] == "COMPLETE_LINEUP" and (
                not manifest["pagination_complete"] or manifest["source_page_count"] < 1):
            raise ReplayContractError("COMPLETE_LINEUP requires a complete paginated capture")
        if doc["completeness"] == "PARTIAL_TRIM_LIST" and manifest["pagination_complete"]:
            raise ReplayContractError("partial lineup cannot claim a complete paginated capture")
        if doc["completeness"] == "COMPLETE_LINEUP":
            completeness = validate_source_completeness(doc)
            if not completeness["complete"]:
                raise ReplayContractError("complete lineup lacks validated completeness evidence: "
                                          + ",".join(completeness["reason_codes"]))
    return SourceDocument(doc["document_id"], doc["source_id"], doc["market"], doc["model_id"],
                          doc["generation_id"], tuple(doc["trim_ids"]), doc["content_sha256"],
                          doc["local_source_id"], doc["captured_at"], doc.get("published_at"),
                          doc["completeness"], doc["source_authority"], doc["extraction_method"])


def _parse_value(raw: str, definition: dict) -> tuple[object, str | None]:
    typ, unit = definition["value_type"], definition.get("canonical_unit")
    if typ == "BOOLEAN":
        values = {"true": True, "yes": True, "included": True, "false": False, "no": False, "not included": False}
        value = values.get(raw.strip().lower())
        if value is None:
            raise ReplayContractError("INVALID_BOOLEAN")
        return value, None
    if typ == "NUMBER":
        match = NUMBER_RE.fullmatch(raw)
        if not match:
            raise ReplayContractError("INVALID_NUMBER")
        value, found_unit = float(match.group(1)), match.group(2)
        if found_unit and unit and found_unit.lower() != unit.lower():
            # Only exact canonical units are accepted in this chunk; no inferred conversions.
            raise ReplayContractError("UNIT_MISMATCH")
        # Count fields are dimensionless by definition. Other dimensional numbers
        # need an explicit unit in the quoted source text; the canonical unit is
        # not evidence that the source stated it.
        if unit and unit.lower() != "seat" and not found_unit:
            raise ReplayContractError("UNIT_EVIDENCE_MISSING")
        if value.is_integer():
            value = int(value)
        return value, found_unit or (None if unit and unit.lower() == "seat" else unit)
    return raw.strip(), unit


def _claims(doc: dict, registry: dict, eligible_trim_ids: set[str], active_rows: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    rows, held = [], []
    model = active_rows.get(doc["model_id"])
    if not model:
        return rows, [{"document_id": doc["document_id"], "status": "REJECTED", "reason_code": "MODEL_NOT_FOUND"}]
    if doc["market"] != "TH":
        return rows, [{"document_id": doc["document_id"], "status": "REJECTED", "reason_code": "WRONG_MARKET"}]
    if doc["source_authority"] != "OFFICIAL":
        return rows, [{"document_id": doc["document_id"], "status": "HELD", "reason_code": "SOURCE_AUTHORITY_NOT_OFFICIAL"}]
    if model.get("status") != "CURRENT" or model.get("upcoming") or model.get("discovered"):
        return rows, [{"document_id": doc["document_id"], "status": "REJECTED", "reason_code": "MODEL_OUT_OF_SCOPE"}]
    # The caller has validated generation/trim lineage and passes the existing ids below.
    for index, line in enumerate(doc["content"].splitlines(), 1):
        match = LINE_RE.fullmatch(line.strip())
        if not match:
            continue
        raw_key, trim_id, raw_value, qualifier_text = match.groups()
        key = resolve_key(raw_key.strip(), registry)
        if key not in SUPPORTED:
            held.append({"document_id": doc["document_id"], "locator": f"line:{index}", "status": "HELD",
                         "reason_code": "FIELD_UNSUPPORTED_OR_OUT_OF_SCOPE", "source_field": raw_key.strip()})
            continue
        trim = active_rows.get("__trims__", {}).get(trim_id)
        if trim is None or trim.get("model_id") != doc["model_id"]:
            held.append({"document_id": doc["document_id"], "trim_id": trim_id, "locator": f"line:{index}",
                         "status": "REJECTED", "reason_code": "TRIM_MISMATCH"})
            continue
        if trim.get("generation_id") != doc["generation_id"]:
            held.append({"document_id": doc["document_id"], "trim_id": trim_id, "locator": f"line:{index}",
                         "status": "REJECTED", "reason_code": "GENERATION_MISMATCH"})
            continue
        if doc.get("trim_variant_ids", {}).get(trim_id) and doc["trim_variant_ids"][trim_id] != trim.get("variant_id"):
            held.append({"document_id": doc["document_id"], "trim_id": trim_id, "locator": f"line:{index}",
                         "status": "HELD", "reason_code": "VARIANT_MISMATCH"})
            continue
        if doc.get("powertrain_by_trim", {}).get(trim_id) and doc["powertrain_by_trim"][trim_id] != trim.get("powertrain"):
            held.append({"document_id": doc["document_id"], "trim_id": trim_id, "locator": f"line:{index}",
                         "status": "HELD", "reason_code": "POWERTRAIN_MISMATCH"})
            continue
        stated_year = doc.get("model_year_by_trim", {}).get(trim_id)
        generation = active_rows.get("__generations__", {}).get(trim.get("generation_id"), {})
        actual_year = trim.get("model_year") or generation.get("model_year")
        if stated_year is not None and actual_year is None:
            held.append({"document_id": doc["document_id"], "trim_id": trim_id, "locator": f"line:{index}",
                         "status": "HELD", "reason_code": "MODEL_YEAR_UNRESOLVED"})
            continue
        if stated_year is not None and str(stated_year) != str(actual_year):
            held.append({"document_id": doc["document_id"], "trim_id": trim_id, "locator": f"line:{index}",
                         "status": "HELD", "reason_code": "MODEL_YEAR_MISMATCH"})
            continue
        if trim_id not in doc["trim_ids"] or trim_id not in eligible_trim_ids:
            held.append({"document_id": doc["document_id"], "trim_id": trim_id, "locator": f"line:{index}",
                         "status": "HELD", "reason_code": "TRIM_NOT_EXPLICITLY_ADMITTED"})
            continue
        definition = registry["fields"][key]
        if definition.get("applicable_powertrains") and trim.get("powertrain") not in definition["applicable_powertrains"]:
            held.append({"document_id": doc["document_id"], "trim_id": trim_id, "locator": f"line:{index}",
                         "status": "HELD", "reason_code": "POWERTRAIN_NOT_APPLICABLE"})
            continue
        qualifiers = {}
        if qualifier_text:
            for pair in qualifier_text.split(";"):
                if "=" not in pair:
                    held.append({"document_id": doc["document_id"], "trim_id": trim_id, "status": "HELD",
                                 "locator": f"line:{index}", "reason_code": "INVALID_QUALIFIER"})
                    break
                qkey, qvalue = pair.split("=", 1)
                qualifiers[qkey.strip()] = qvalue.strip()
            else:
                pass
            if any("=" not in pair for pair in qualifier_text.split(";")):
                continue
        required_q = set(definition.get("comparison_qualifiers", []))
        missing_q = required_q - qualifiers.keys()
        if missing_q:
            held.append({"document_id": doc["document_id"], "trim_id": trim_id, "locator": f"line:{index}",
                         "status": "HELD", "reason_code": "MISSING_MEASUREMENT_QUALIFIER", "fields": sorted(missing_q)})
            continue
        if key == "ev.rated_range_km" and (qualifiers.get("measurement_basis") not in RANGE_BASES or qualifiers.get("range_scope") not in RANGE_SCOPES):
            held.append({"document_id": doc["document_id"], "trim_id": trim_id, "locator": f"line:{index}",
                         "status": "HELD", "reason_code": "UNSUPPORTED_RANGE_BASIS_OR_SCOPE"})
            continue
        try:
            value, unit = _parse_value(raw_value.strip(), definition)
        except ReplayContractError as exc:
            held.append({"document_id": doc["document_id"], "trim_id": trim_id, "locator": f"line:{index}",
                         "source_field": raw_key.strip(), "status": "HELD", "reason_code": str(exc)})
            continue
        locator = f"line:{index}"
        claim = SourceClaim(key, trim_id, value, unit, tuple(sorted(qualifiers.items())), line, locator)
        candidate = FieldCandidate(doc["document_id"], doc["content_sha256"], doc["source_id"],
                     doc["source_authority"], doc["market"], doc["model_id"], doc["generation_id"],
                     claim.trim_id, trim.get("powertrain", ""), claim.field_key, claim.value, claim.unit, claim.qualifiers, claim.quote,
                     claim.locator, doc.get("published_at"), doc["captured_at"], doc["completeness"],
                     doc["source_kind"], doc.get("lineage_id", doc["document_id"]),
                     doc["extraction_method"], "PENDING")
        row = asdict(candidate)
        row["schema_version"] = SCHEMA_VERSION
        row["qualifiers"] = dict(candidate.qualifiers)
        generation = active_rows.get("__generations__", {}).get(trim.get("generation_id"), {})
        row["applicability"] = {"trim_id": claim.trim_id, "powertrain": trim.get("powertrain"),
                                "model_year": trim.get("model_year") or generation.get("model_year")}
        rows.append(row)
    return rows, held


def replay(snapshot_path: str | Path, document_paths: list[str | Path], output_dir: str | Path,
           *, root: Path | None = None) -> dict:
    snapshot_path = Path(snapshot_path)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    validate_fixture(snapshot)
    documents = [json.loads(Path(p).read_text(encoding="utf-8")) for p in document_paths]
    documents.sort(key=lambda d: d.get("document_id", ""))
    registry = load_registry(root=root)
    eligible = set()
    for model in snapshot.get("models", []):
        scope = evaluate_model(snapshot, model)
        eligible.update(scope.admitted_trim_ids)
    gap_before: dict[str, dict] = {}
    # Use canonical registry metadata and canonical aliases for present-value suppression.
    canonical_snapshot, tiers, out_of_scope = adapt_snapshot(snapshot, tuple(sorted(eligible)), registry)
    # From here onward, all identity and value lookups use the adapted rows.
    model_rows = {m["id"]: m for m in canonical_snapshot.get("models", [])}
    trim_rows = {t["id"]: t for t in canonical_snapshot.get("trims", [])}
    generation_rows = {g["id"]: g for g in canonical_snapshot.get("generations", [])}
    active_rows = dict(model_rows)
    active_rows["__trims__"] = trim_rows
    active_rows["__generations__"] = generation_rows
    for model_id in sorted({trim_rows[t]["model_id"] for t in eligible}):
        model_trims = tuple(sorted(t for t in eligible if trim_rows[t]["model_id"] == model_id))
        gap_before[model_id] = gaps_for_model(canonical_snapshot, model_trims)
    evidence, candidates, rejects, source_documents = [], [], [], []
    duplicate_hashes: dict[str, tuple] = {}
    duplicate_hash_suppressions = 0
    conflicting_hashes: set[str] = set()
    def hash_scope(doc: dict) -> tuple:
        return tuple((key, _stable(doc.get(key))) for key in (
            "source_id", "source_authority", "market", "model_id", "generation_id", "trim_ids",
            "trim_variant_ids", "powertrain_by_trim", "model_year_by_trim", "completeness", "capture_manifest", "source_kind"))
    for doc in documents:
        _valid_document(doc)
        signature = hash_scope(doc)
        previous = duplicate_hashes.get(doc["content_sha256"])
        if previous is not None and previous != signature:
            conflicting_hashes.add(doc["content_sha256"])
        duplicate_hashes[doc["content_sha256"]] = signature
    seen_hashes: set[str] = set()
    for doc in documents:
        validated_document = _valid_document(doc)
        if doc["content_sha256"] in conflicting_hashes:
            rejects.append({"document_id": doc["document_id"], "status": "HELD", "reason_code": "DUPLICATE_HASH_METADATA_CONFLICT"})
            continue
        if doc["content_sha256"] in seen_hashes:
            duplicate_hash_suppressions += 1
            rejects.append({"document_id": doc["document_id"], "status": "SUPPRESSED", "reason_code": "DUPLICATE_DOCUMENT_HASH"})
            continue
        seen_hashes.add(doc["content_sha256"])
        source_documents.append(validated_document)
        evidence.append({k: doc.get(k) for k in ("schema_version", "document_id", "source_id", "source_authority", "market",
                         "model_id", "generation_id", "trim_ids", "trim_variant_ids", "powertrain_by_trim", "model_year_by_trim",
                         "local_source_id", "content_sha256", "published_at",
                         "captured_at", "completeness", "capture_manifest", "source_kind", "lineage_id", "extraction_method")})
        model = model_rows.get(doc["model_id"])
        gen = generation_rows.get(doc["generation_id"])
        if not model or not gen or gen.get("model_id") != doc["model_id"]:
            rejects.append({"document_id": doc["document_id"], "status": "REJECTED", "reason_code": "MODEL_GENERATION_MISMATCH"})
            continue
        as_of = date.fromisoformat(snapshot["as_of"])
        if date.fromisoformat(doc["captured_at"]) > as_of or (doc.get("published_at") and date.fromisoformat(doc["published_at"]) > as_of):
            rejects.append({"document_id": doc["document_id"], "status": "HELD", "reason_code": "SOURCE_DATE_AFTER_SNAPSHOT"})
            continue
        if doc.get("published_at") and (as_of - date.fromisoformat(doc["published_at"])).days > 730:
            rejects.append({"document_id": doc["document_id"], "status": "HELD", "reason_code": "SOURCE_STALE"})
            continue
        parsed, held = _claims(doc, registry, eligible, active_rows)
        candidates.extend(parsed); rejects.extend(held)
    # Exact quote and line locator are checked again on candidate rows before disposition.
    contents = {d["document_id"]: d["content"] for d in documents}
    for candidate in candidates:
        lines = contents[candidate["document_id"]].splitlines()
        n = int(candidate["locator"].split(":")[1])
        if n < 1 or n > len(lines) or lines[n-1] != candidate["quote"]:
            candidate["candidate_status"] = "HELD"
            candidate["reason_code"] = "QUOTE_LOCATOR_MISMATCH"
    current_values: dict[tuple[str, str], list[dict]] = {}
    disposition_states = {}
    for model_id, gap in gap_before.items():
        for d in gap["dispositions"]:
            disposition_states[(d["trim_id"], d["field_key"])] = d["state"]
    for trim_id in eligible:
        trim = trim_rows[trim_id]
        generation = generation_rows.get(trim["generation_id"], {})
        model = model_rows.get(trim["model_id"], {})
        variant = next((v for v in canonical_snapshot.get("variants", []) if v.get("id") == trim.get("variant_id")), {})
        layers = [trim.get("specs", {}), variant.get("specs", {}), generation.get("specs", {}), model.get("specs", {})]
        for layer in layers:
            for key, value in layer.items():
                current_values.setdefault((trim_id, key), []).append({"value": value, "qualifiers": None})
        for fact in canonical_snapshot.get("facts", []):
            if fact.get("trim_id") == trim_id and fact.get("value_state") == "KNOWN" and fact.get("value") is not None:
                start, end = fact.get("effective_from"), fact.get("effective_to")
                if (not start or start <= snapshot["as_of"]) and (not end or end >= snapshot["as_of"]):
                    qualifiers = fact.get("qualifiers")
                    if not isinstance(qualifiers, dict):
                        required = set(registry["fields"].get(fact["field_key"], {}).get("comparison_qualifiers", []))
                        qualifier_keys = {"measurement_basis", "range_scope", "output_scope", "rating_basis"} | required
                        qualifiers = {key: fact[key] for key in qualifier_keys if key in fact}
                    current_values.setdefault((trim_id, fact["field_key"]), []).append({"value": fact["value"], "qualifiers": qualifiers or None})
    grouped: dict[tuple, list[dict]] = {}
    for c in candidates:
        qkey = tuple(sorted(c["qualifiers"].items()))
        grouped.setdefault((c["trim_id"], c["field_key"], qkey), []).append(c)
    for group in grouped.values():
        values = {json.dumps(c["value"], sort_keys=True) for c in group}
        if len(values) > 1:
            for c in group:
                c["candidate_status"], c["reason_code"] = "HELD", "CONFLICTING_SOURCE_VALUES"
                rejects.append({"document_id": c["document_id"], "trim_id": c["trim_id"], "field_key": c["field_key"],
                                "status": "HELD", "reason_code": "CONFLICTING_SOURCE_VALUES"})
        else:
            seen_lineage_claims = set()
            for c in sorted(group, key=lambda row: row["document_id"]):
                all_existing = current_values.get((c["trim_id"], c["field_key"]), [])
                definition = registry["fields"].get(c["field_key"], {})
                required_qualifiers = set(definition.get("comparison_qualifiers", []))
                candidate_qualifiers = c["qualifiers"]
                existing = all_existing
                qualifier_block = None
                if required_qualifiers and all_existing:
                    comparable, unresolved = [], False
                    for row in all_existing:
                        eq = row["qualifiers"]
                        if not eq or not required_qualifiers <= eq.keys():
                            unresolved = True
                        elif all(eq[key] == candidate_qualifiers.get(key) for key in required_qualifiers):
                            comparable.append(row)
                    if unresolved:
                        qualifier_block = "CURRENT_VALUE_QUALIFIERS_UNRESOLVED"
                        existing = []
                    elif comparable:
                        existing = comparable
                    else:
                        qualifier_block = "CURRENT_VALUE_QUALIFIERS_DIFFER"
                        existing = []
                distinct = {json.dumps(row["value"], sort_keys=True) for row in existing}
                state = disposition_states.get((c["trim_id"], c["field_key"]))
                if qualifier_block:
                    c["candidate_status"], c["reason_code"] = "HELD", qualifier_block
                elif state == "TOMBSTONED_LOCKED":
                    c["candidate_status"], c["reason_code"] = "HELD", "ADMIN_LOCKED_TOMBSTONE"
                elif state == "CONFLICT":
                    c["candidate_status"], c["reason_code"] = "HELD", "CURRENT_FACT_CONFLICT"
                elif state == "NOT_APPLICABLE":
                    c["candidate_status"], c["reason_code"] = "HELD", "FIELD_NOT_APPLICABLE"
                elif state == "ABSENT":
                    c["candidate_status"], c["reason_code"] = "HELD", "CURRENTLY_ABSENT"
                elif len(distinct) > 1 or (existing and any(row["value"] != c["value"] for row in existing)):
                    c["candidate_status"], c["reason_code"] = "HELD", "CONFLICT_WITH_CURRENT_VALUE"
                elif existing and disposition_states.get((c["trim_id"], c["field_key"])) == "NEEDS_SOURCE_TRACE":
                    c["candidate_status"], c["reason_code"] = "ACCEPTED_CANDIDATE", "SOURCE_TRACE_MATCHED"
                elif existing:
                    c["candidate_status"], c["reason_code"] = "HELD", "ALREADY_PRESENT"
                elif c["lineage_id"] in seen_lineage_claims:
                    c["candidate_status"], c["reason_code"] = "HELD", "DUPLICATE_LINEAGE_CLAIM"
                else:
                    c["candidate_status"], c["reason_code"] = "ACCEPTED_CANDIDATE", "EXACT_TRIM_SOURCE_MATCH"
                seen_lineage_claims.add(c["lineage_id"])
    open_states = {"MISSING", "UNKNOWN", "NEEDS_SOURCE_TRACE", "SOURCE_EXHAUSTED", "NOT_AVAILABLE"}
    before_flat = {(d["trim_id"], d["field_key"], d["state"]) for g in gap_before.values() for d in g["dispositions"]
                   if d["state"] in open_states}
    open_gap_pairs = {(d["trim_id"], d["field_key"]) for g in gap_before.values() for d in g["dispositions"]
                      if d["state"] in open_states}
    proposed = {(c["trim_id"], c["field_key"]) for c in candidates
                if c["candidate_status"] == "ACCEPTED_CANDIDATE" and (c["trim_id"], c["field_key"]) in open_gap_pairs}
    claim_rejects = [x for x in rejects if x.get("locator") and x.get("trim_id")]
    accepted_count = sum(c["candidate_status"] == "ACCEPTED_CANDIDATE" for c in candidates)
    held_count = sum(c["candidate_status"] == "HELD" for c in candidates) + sum(x.get("status") == "HELD" for x in claim_rejects)
    rejected_count = sum(x.get("status") == "REJECTED" for x in claim_rejects)
    summary = {"schema_version": SCHEMA_VERSION, "documents_seen": len(documents), "unique_documents": len(evidence),
               "duplicate_hash_suppressions": duplicate_hash_suppressions,
               "candidates_total": accepted_count + held_count + rejected_count,
               "accepted_candidates": accepted_count, "held_candidates": held_count,
               "rejected_candidates": rejected_count,
               "held_documents": sum(x.get("status") == "HELD" and not x.get("locator") for x in rejects),
               "rejected_documents": sum(x.get("status") == "REJECTED" and not x.get("locator") for x in rejects),
               "reason_counts": {}, "applicable_gaps_before": len(before_flat),
               "applicable_gaps_after_replay": max(0, len(before_flat) - len(proposed)),
               "priority_gap_items_before_replay": len(open_gap_pairs),
               "priority_gap_items_proposed": len(proposed),
               "priority_gap_items_after_replay": max(0, len(open_gap_pairs) - len(proposed)),
               "accepted_candidates_not_resolving_priority_gaps": accepted_count - sum(
                   c["candidate_status"] == "ACCEPTED_CANDIDATE" and (c["trim_id"], c["field_key"]) in open_gap_pairs for c in candidates),
               "proposed_canonical_writes": 0, "production_writes": 0, "external_http_calls": 0,
               "paid_model_calls": 0, "paid_tokens": 0, "paid_spend_thb": 0,
               "canonical_registry_year": registry["year"], "canonical_registry_sha256": registry["registry_sha256"],
               "priority_overlay_fields": len(tiers), "lineage_independent_source_count": len({c["lineage_id"] for c in candidates}),
               "lineage_note": "Documents sharing lineage_id count as one source; replay does not infer source independence."}
    for row in rejects + candidates + out_of_scope:
        code = row.get("reason_code")
        if code: summary["reason_counts"][code] = summary["reason_counts"].get(code, 0) + 1
    summary["matched_candidates"] = summary["accepted_candidates"]
    summary["mismatched_candidates"] = held_count
    summary["cache_suppressions"] = summary["duplicate_hash_suppressions"]
    summary["accepted_by_reason"] = _count_reasons([c for c in candidates if c["candidate_status"] == "ACCEPTED_CANDIDATE"])
    summary["held_by_reason"] = _count_reasons([c for c in candidates if c["candidate_status"] == "HELD"]
                                               + [r for r in claim_rejects if r.get("status") == "HELD"])
    summary["rejected_by_reason"] = _count_reasons([r for r in claim_rejects if r.get("status") == "REJECTED"])
    dispositions = []
    for model_id, gap in sorted(gap_before.items()):
        for row in gap["dispositions"]:
            disposition = dict(row)
            if (row["trim_id"], row["field_key"]) in proposed and row["state"] in open_states:
                disposition["replay_state"] = "CANDIDATE_PROPOSED"
            else:
                disposition["replay_state"] = row["state"]
            dispositions.append(disposition)
    for trim_id in sorted(eligible):
        trim = trim_rows[trim_id]
        for row in out_of_scope:
            allowed = row["applicable_powertrains"]
            if allowed and trim.get("powertrain") not in allowed:
                continue
            dispositions.append({"trim_id": trim_id, "field_key": row["field_key"], "state": "OUT_OF_SCOPE",
                                 "reason_code": row["reason_code"], "tier": row["tier"]})
    dispositions.sort(key=lambda x: (x["trim_id"], x["field_key"], x["state"]))
    candidate_contracts = tuple(FieldCandidate(
        c["document_id"], c["document_sha256"], c["source_id"], c["source_authority"], c["market"],
        c["model_id"], c["generation_id"], c["trim_id"], c["powertrain"], c["field_key"], c["value"], c["unit"],
        tuple(sorted(c["qualifiers"].items())), c["quote"], c["locator"], c["published_at"],
        c["captured_at"], c["completeness"], c["source_kind"], c["lineage_id"],
        c["extraction_method"], c["candidate_status"]) for c in candidates)
    report = ReplayReport(tuple(source_documents), candidate_contracts,
                          tuple(FieldDisposition(d["trim_id"], d["field_key"], d["state"], d.get("replay_state", d["state"]))
                                for d in dispositions),
                          ReplaySummary(len(documents), len(candidates), summary["accepted_candidates"],
                                        summary["held_candidates"], summary["rejected_candidates"]))
    _validate_report(report)
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "replay_evidence.jsonl").write_text(_jsonl(sorted(evidence, key=lambda r: r["document_id"])), encoding="utf-8")
    (out / "field_candidates.jsonl").write_text(_jsonl(sorted(candidates, key=lambda r: (r["model_id"], r["trim_id"], r["field_key"], r["document_id"]))), encoding="utf-8")
    (out / "gap_diff.json").write_text(json.dumps({"schema_version": SCHEMA_VERSION, "dispositions": dispositions,
                "held_or_rejected": sorted(rejects, key=lambda r: (r.get("document_id", ""), r.get("locator", ""), r.get("reason_code", "")))},
                ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (out / "replay_summary.json").write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return summary


def _validate_report(report: ReplayReport) -> None:
    if (report.summary.external_http_calls or report.summary.paid_model_calls or report.summary.paid_tokens
            or report.summary.paid_spend_thb or report.summary.production_writes):
        raise ReplayContractError("replay report violated zero-call/zero-write contract")
    hashes = {row.document_sha256 for row in report.replay_evidence}
    for candidate in report.field_candidates:
        if candidate.document_sha256 not in hashes or candidate.market != "TH":
            raise ReplayContractError("candidate has no admitted Thai evidence document")
        if not candidate.quote or not re.fullmatch(r"line:[1-9][0-9]*", candidate.locator):
            raise ReplayContractError("candidate quote/locator contract is invalid")
        if candidate.candidate_status not in {"ACCEPTED_CANDIDATE", "HELD"}:
            raise ReplayContractError("invalid candidate disposition")


def validate_cached_source_document(snapshot: dict, document: dict) -> dict:
    """Re-admit cached bytes through the same fixture and replay contracts.

    The returned coverage contains only exact claims the deterministic replay
    pipeline accepts against this snapshot. Metadata on its own never grants
    cache coverage.
    """
    validate_fixture(snapshot)
    _valid_document(document)
    with tempfile.TemporaryDirectory(prefix="catalog-evidence-replay-") as directory:
        root = Path(directory)
        snapshot_path = root / "snapshot.json"
        document_path = root / "document.json"
        output_path = root / "out"
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        document_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        replay(snapshot_path, [document_path], output_path)
        candidates = [json.loads(line) for line in (output_path / "field_candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    accepted = [row for row in candidates if row.get("candidate_status") == "ACCEPTED_CANDIDATE"]
    if document.get("source_kind") == "RETAIL_LINEUP":
        from .retail_reconcile import validate_source_completeness
        complete = validate_source_completeness(document)["complete"]
        if not complete or document.get("market") != "TH" or document.get("source_authority") != "OFFICIAL":
            raise ReplayContractError("cached retail evidence is not a validated complete official Thai lineup")
    return {"source_document": document,
            "accepted_claims": [{"model_id": row["model_id"], "generation_id": row["generation_id"],
                                 "trim_id": row["trim_id"], "field_key": row["field_key"],
                                 "document_sha256": row["document_sha256"]} for row in accepted],
            "retail_lineup_validated": document.get("source_kind") == "RETAIL_LINEUP"}


def _count_reasons(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        code = row.get("reason_code", "UNSPECIFIED")
        counts[code] = counts.get(code, 0) + 1
    return counts
