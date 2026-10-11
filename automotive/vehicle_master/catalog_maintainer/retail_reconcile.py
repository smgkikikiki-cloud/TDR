"""Offline Thai retail-lineup evidence validation and pure MarketTrim proposals.

This module returns reviewable outcomes only. It never creates identities or writes data.
"""
from __future__ import annotations

from datetime import date
import hashlib


OUTCOMES = {"KEEP", "ADD_PROPOSAL", "SOFT_DISCONTINUE_PROPOSAL", "HOLD", "REVIEW"}


def validate_reconciliation_output(result: dict) -> None:
    if not isinstance(result, dict) or not isinstance(result.get("outcomes"), list):
        raise ValueError("retail reconciliation output is missing outcomes")
    if result.get("canonical_writes") != 0:
        raise ValueError("retail reconciliation output cannot write canonical data")
    for row in result["outcomes"]:
        if row.get("outcome") not in OUTCOMES or not isinstance(row.get("reason_codes"), list):
            raise ValueError("invalid retail reconciliation outcome contract")
        if row.get("outcome") == "SOFT_DISCONTINUE_PROPOSAL" and row.get("soft_archive_only") is not True:
            raise ValueError("discontinuation outcome must be a soft archive proposal")


def validate_source_completeness(document: dict) -> dict:
    """Validate a normalized capture and explicit publisher completeness evidence."""
    reasons: list[str] = []
    content = document.get("content")
    if document.get("completeness") != "COMPLETE_LINEUP":
        reasons.append("SOURCE_NOT_DECLARED_COMPLETE_LINEUP")
    manifest = document.get("capture_manifest")
    proof = document.get("completeness_evidence")
    if document.get("market") != "TH" or document.get("source_authority") != "OFFICIAL":
        reasons.append("SOURCE_NOT_OFFICIAL_THAI")
    if document.get("source_kind") != "RETAIL_LINEUP":
        reasons.append("NOT_A_RETAIL_LINEUP")
    if not isinstance(content, str) or hashlib.sha256(content.encode("utf-8")).hexdigest() != document.get("content_sha256"):
        reasons.append("SOURCE_HASH_MISMATCH")
    try:
        captured = date.fromisoformat(document.get("captured_at", ""))
        published = document.get("published_at")
        if published:
            date.fromisoformat(published)
            if date.fromisoformat(published) > captured:
                reasons.append("PUBLICATION_AFTER_CAPTURE")
    except (TypeError, ValueError):
        reasons.append("SOURCE_DATE_INVALID")
    if not isinstance(manifest, dict):
        reasons.append("CAPTURE_MANIFEST_MISSING")
    else:
        ids = manifest.get("listed_trim_ids")
        if (manifest.get("pagination_complete") is not True or type(manifest.get("source_page_count")) is not int
                or type(manifest.get("row_count")) is not int or manifest.get("source_page_count", 0) < 1
                or manifest.get("row_count", 0) < 1 or not isinstance(ids, list) or not ids
                or any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids))):
            reasons.append("CAPTURE_INCOMPLETE_OR_EMPTY")
        else:
            body_ids = [line.split("|", 2)[2] for line in content.splitlines()
                        if line.startswith("lineup|trim|") and len(line.split("|", 2)) == 3]
            if body_ids != ids or len(body_ids) != manifest["row_count"] or set(body_ids) != set(document.get("trim_ids", [])):
                reasons.append("CAPTURE_ROWS_DO_NOT_MATCH_MANIFEST")
    if not isinstance(proof, dict):
        reasons.append("COMPLETENESS_EVIDENCE_MISSING")
    else:
        quote, locator = proof.get("quote"), proof.get("locator")
        lines = content.splitlines() if isinstance(content, str) else []
        try:
            line_no = int(locator.split(":", 1)[1]) if isinstance(locator, str) and locator.startswith("line:") else -1
        except ValueError:
            line_no = -1
        quote_bound = 1 <= line_no <= len(lines) and lines[line_no - 1] == quote
        if proof.get("publisher_declared_complete") is not True or not quote_bound:
            reasons.append("PUBLISHER_COMPLETENESS_NOT_EVIDENCED")
        if proof.get("capture_status") != "COMPLETE":
            reasons.append("CAPTURE_NOT_COMPLETE")
        if (type(proof.get("expected_page_count")) is not int or type(proof.get("captured_page_count")) is not int
                or proof.get("expected_page_count", 0) < 1
                or proof.get("expected_page_count") != proof.get("captured_page_count")):
            reasons.append("PAGE_COUNT_MISMATCH")
    if document.get("completeness") == "COMPLETE_LINEUP":
        rows = document.get("lineup_rows")
        manifest_ids = manifest.get("listed_trim_ids", []) if isinstance(manifest, dict) else []
        if not isinstance(rows, list):
            reasons.append("NORMALIZED_LINEUP_ROWS_MISSING")
        else:
            row_ids = [r.get("market_trim_id") for r in rows if isinstance(r, dict)]
            if (len(row_ids) != len(rows) or len(row_ids) != len(set(row_ids)) or set(row_ids) != set(manifest_ids)
                    or any(not all(k in r for k in ("market_trim_id", "model_id", "generation_id", "grade",
                                                       "powertrain", "model_year", "facelift_id"))
                           or r.get("model_id") != document.get("model_id")
                           or r.get("generation_id") != document.get("generation_id")
                           or not isinstance(r.get("powertrain"), str) or not r.get("powertrain") for r in rows)):
                reasons.append("NORMALIZED_LINEUP_ROWS_INVALID")
    return {"complete": not reasons, "reason_codes": sorted(set(reasons)),
            "trim_ids": sorted(document.get("trim_ids", [])) if not reasons else []}


def _identity(row: dict) -> tuple:
    """MarketTrim identity fields are exact and never fuzzy matched."""
    return (row.get("model_id"), row.get("generation_id"), row.get("grade"),
            row.get("powertrain"), row.get("model_year"), row.get("facelift_id"))


def reconcile_retail_lineup(snapshot: dict, document: dict, *, prior_complete_documents: list[dict] | None = None,
                            minimum_interval_days: int = 30) -> dict:
    """Return deterministic per-MarketTrim outcomes; all structural changes are proposals."""
    completeness = validate_source_completeness(document)
    model_id = document.get("model_id")
    model = next((x for x in snapshot.get("models", []) if x.get("id") == model_id), None)
    generation = next((x for x in snapshot.get("generations", []) if x.get("id") == document.get("generation_id")), None)
    if not model or not generation or generation.get("model_id") != model_id:
        result = {"model_id": model_id, "outcomes": [], "model_outcome": "REVIEW",
                  "reason_codes": ["MODEL_GENERATION_IDENTITY_UNRESOLVED"], "canonical_writes": 0}
        validate_reconciliation_output(result)
        return result
    if model.get("status") != "CURRENT" or model.get("admin_retired"):
        result = {"model_id": model_id, "outcomes": [], "model_outcome": "REVIEW",
                  "reason_codes": ["MODEL_NOT_ELIGIBLE_FOR_RETAIL_RECONCILIATION"], "canonical_writes": 0}
        validate_reconciliation_output(result)
        return result
    try:
        if date.fromisoformat(document["captured_at"]) > date.fromisoformat(snapshot["as_of"]):
            result = {"model_id": model_id, "outcomes": [{"market_trim_id": None, "outcome": "HOLD",
                      "reason_codes": ["SOURCE_CAPTURE_AFTER_SNAPSHOT"]}], "model_outcome": "HOLD",
                      "reason_codes": ["SOURCE_CAPTURE_AFTER_SNAPSHOT"], "canonical_writes": 0}
            validate_reconciliation_output(result)
            return result
    except (KeyError, TypeError, ValueError):
        result = {"model_id": model_id, "outcomes": [{"market_trim_id": None, "outcome": "HOLD",
                  "reason_codes": ["SOURCE_OR_SNAPSHOT_DATE_INVALID"]}], "model_outcome": "HOLD",
                  "reason_codes": ["SOURCE_OR_SNAPSHOT_DATE_INVALID"], "canonical_writes": 0}
        validate_reconciliation_output(result)
        return result
    trims = {t["id"]: t for t in snapshot.get("trims", []) if t.get("model_id") == model_id}
    approved = next((s for s in snapshot.get("current_retail_sets", []) if s.get("model_id") == model_id), None)
    protected = set(approved.get("trim_ids", [])) if approved else set()
    listed = set(completeness["trim_ids"])
    results: list[dict] = []
    if not completeness["complete"]:
        targets = sorted(listed | protected)
        results.extend({"market_trim_id": tid, "outcome": "HOLD", "reason_codes": completeness["reason_codes"]}
                       for tid in targets)
        if not targets:
            results.append({"market_trim_id": None, "outcome": "HOLD", "reason_codes": completeness["reason_codes"]})
        result = {"model_id": model_id, "outcomes": results, "model_outcome": "HOLD",
                  "reason_codes": completeness["reason_codes"], "canonical_writes": 0}
        validate_reconciliation_output(result)
        return result

    # An exact ID plus exact identity tuple is required; aliases are retained as source metadata only.
    rows = document.get("lineup_rows", [])
    rows_by_id = {r.get("market_trim_id"): r for r in rows if isinstance(r, dict)}
    if set(rows_by_id) != listed:
        result = {"model_id": model_id, "outcomes": [{"market_trim_id": None, "outcome": "REVIEW",
                  "reason_codes": ["NORMALIZED_LINEUP_ROWS_MISMATCH"]}], "model_outcome": "REVIEW",
                  "reason_codes": ["NORMALIZED_LINEUP_ROWS_MISMATCH"], "canonical_writes": 0}
        validate_reconciliation_output(result)
        return result
    for tid in sorted(listed):
        row = rows_by_id[tid]
        if row.get("model_id") != model_id or row.get("generation_id") != document.get("generation_id"):
            results.append({"market_trim_id": tid, "outcome": "REVIEW", "reason_codes": ["CROSS_MODEL_OR_GENERATION_IDENTITY"]})
            continue
        existing = trims.get(tid)
        if existing:
            if _identity(row) != _identity(existing):
                results.append({"market_trim_id": tid, "outcome": "REVIEW", "reason_codes": ["CANONICAL_IDENTITY_COLLISION"]})
            elif existing.get("status") != "CURRENT" or existing.get("admin_retired") or existing.get("owner_retired"):
                results.append({"market_trim_id": tid, "outcome": "REVIEW", "reason_codes": ["NON_CURRENT_OR_RETIRED_TRIM_PROTECTED"]})
            else:
                results.append({"market_trim_id": tid, "outcome": "KEEP", "reason_codes": ["EXACT_MARKET_TRIM_IDENTITY"]})
        else:
            collision = any(_identity(t) == _identity(row) for t in trims.values())
            if collision:
                results.append({"market_trim_id": tid, "outcome": "REVIEW", "reason_codes": ["MARKET_TRIM_IDENTITY_COLLISION"]})
            else:
                results.append({"market_trim_id": tid, "outcome": "ADD_PROPOSAL", "reason_codes": ["EXACT_NEW_THAI_GRADE_POWERTRAIN_IDENTITY"]})

    absent = sorted(set(trims) - listed)
    prior = prior_complete_documents or []
    for tid in absent:
        trim = trims[tid]
        if tid in protected or trim.get("admin_retired") or trim.get("owner_retired"):
            results.append({"market_trim_id": tid, "outcome": "REVIEW", "reason_codes": ["OWNER_OR_ADMIN_PROTECTED_TRIM"]})
            continue
        if trim.get("status") == "HISTORICAL":
            results.append({"market_trim_id": tid, "outcome": "REVIEW", "reason_codes": ["HISTORICAL_TRIM_NOT_AUTO_RETIRED"]})
            continue
        explicit = False
        content_lines = document.get("content", "").splitlines()
        for evidence in document.get("end_of_sale_evidence", []):
            locator = evidence.get("locator", "")
            try:
                line_no = int(locator.split(":", 1)[1]) if locator.startswith("line:") else -1
            except ValueError:
                line_no = -1
            if (evidence.get("market_trim_id") == tid and evidence.get("first_party_end_of_sale") is True
                    and document.get("source_authority") == "OFFICIAL" and document.get("market") == "TH"
                    and 1 <= line_no <= len(content_lines) and content_lines[line_no - 1] == evidence.get("quote")):
                explicit = True
                break
        independent = []
        for old in prior:
            verdict = validate_source_completeness(old)
            if (verdict["complete"] and old.get("market") == "TH" and old.get("source_authority") == "OFFICIAL"
                    and old.get("model_id") == model_id and old.get("generation_id") == document.get("generation_id")
                    and tid in set(old.get("trim_ids", [])) and old.get("source_id") != document.get("source_id")
                    and old.get("lineage_id") != document.get("lineage_id")
                    and old.get("content_sha256") != document.get("content_sha256")):
                independent.append(old)
        enough_interval = any(abs((date.fromisoformat(document["captured_at"]) - date.fromisoformat(old["captured_at"])).days)
                              >= minimum_interval_days for old in independent)
        if trim.get("status") == "CURRENT" and (explicit or enough_interval):
            reason = "FIRST_PARTY_END_OF_SALE" if explicit else "TWO_INDEPENDENT_COMPLETE_LINEUPS"
            results.append({"market_trim_id": tid, "outcome": "SOFT_DISCONTINUE_PROPOSAL", "reason_codes": [reason],
                            "soft_archive_only": True})
        else:
            results.append({"market_trim_id": tid, "outcome": "HOLD", "reason_codes": ["ABSENCE_IN_COMPLETE_LINEUP_INSUFFICIENT"]})
    outcomes = [x["outcome"] for x in results]
    model_outcome = "REVIEW" if "REVIEW" in outcomes else ("HOLD" if "HOLD" in outcomes else "KEEP")
    result = {"model_id": model_id, "outcomes": results, "model_outcome": model_outcome,
              "reason_codes": [], "canonical_writes": 0,
              "proposal_count": sum(x["outcome"].endswith("_PROPOSAL") for x in results)}
    validate_reconciliation_output(result)
    return result
