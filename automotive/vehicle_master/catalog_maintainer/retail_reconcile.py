"""Offline Thai retail-lineup evidence validation and pure MarketTrim proposals.

This module returns reviewable outcomes only. It never creates identities or writes data.
"""
from __future__ import annotations

from datetime import date
import hashlib
from html.parser import HTMLParser
import re


OUTCOMES = {"KEEP", "ADD_PROPOSAL", "SOFT_DISCONTINUE_PROPOSAL", "HOLD", "REVIEW"}
ATTESTATION_RE = re.compile(
    r"^lineup_attestation\|COMPLETE_CURRENT_THAI_RETAIL_LINEUP\|model=([^|]+)\|generation=([^|]+)\|model_year=([^|]+)\|facelift=([^|]+)$")
RETAIL_END_RE = re.compile(
    r"^retail_end_of_sale\|market=TH\|model=([^|]+)\|generation=([^|]+)\|trim=([^|]+)\|model_year=([^|]+)\|facelift=([^|]+)\|effective_date=(\d{4}-\d{2}-\d{2})$")
CAPTURE_RE = re.compile(
    r"^capture\|edition=([^|]+)\|capture_id=([^|]+)\|captured_at=(\d{4}-\d{2}-\d{2})\|method=LOCAL_FIXTURE_CAPTURE$")


def _scope_value(value: object) -> str:
    return "NONE" if value is None else str(value)


def _parse_scope_value(value: str) -> object:
    if value == "NONE":
        return None
    if re.fullmatch(r"20[0-9]{2}", value):
        return int(value)
    return value


def _document_attestation(document: dict, lines: list[str]) -> dict | None:
    proof = document.get("completeness_evidence") or {}
    if proof.get("assertion_type") == "structured_attribute_assertion":
        if not validate_source_representation(document)["valid"]:
            return None
        record=proof.get("normalized_scope_record")
        if not isinstance(record,str) or record not in lines or proof.get("raw_source_sha256") != (document.get("source_representation") or {}).get("raw_source_sha256"):
            return None
        match=ATTESTATION_RE.fullmatch(record)
        if not match:return None
        model_id,generation_id,model_year,facelift_id=match.groups()
        return {"model_id":model_id,"generation_id":generation_id,
                "model_year":_parse_scope_value(model_year),"facelift_id":_parse_scope_value(facelift_id)}
    locator, quote = proof.get("locator"), proof.get("quote")
    try:
        line_no = int(locator.split(":", 1)[1]) if isinstance(locator, str) and locator.startswith("line:") else -1
    except ValueError:
        line_no = -1
    if not (1 <= line_no <= len(lines) and lines[line_no - 1] == quote):
        return None
    match = ATTESTATION_RE.fullmatch(quote)
    if not match:
        return None
    model_id, generation_id, model_year, facelift_id = match.groups()
    return {"model_id": model_id, "generation_id": generation_id,
            "model_year": _parse_scope_value(model_year), "facelift_id": _parse_scope_value(facelift_id)}


class _RawHTMLIndex(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements=[]
        self.occurrences={}
    def handle_starttag(self,tag,attrs):
        if tag not in {"source-document","claim","trim","complete-lineup","capture"}:return
        line,column=self.getpos(); ordinal=self.occurrences.get(tag,0)+1; self.occurrences[tag]=ordinal
        self.elements.append({"tag":tag,"line":line,"column":column,"ordinal":ordinal,
            "raw_start_tag":self.get_starttag_text(),"attributes":{k:v for k,v in attrs}})


def validate_source_representation(document: dict) -> dict:
    """Validate structured HTML assertions against immutable raw bytes and exact element locators."""
    rep=document.get("source_representation")
    if rep is None:return {"valid":True,"reason_codes":[]}
    reasons=[]
    if not isinstance(rep,dict) or rep.get("kind")!="STRUCTURED_HTML_ATTRIBUTES":
        return {"valid":False,"reason_codes":["SOURCE_REPRESENTATION_UNSUPPORTED"]}
    raw=rep.get("raw_source_utf8")
    proof=document.get("completeness_evidence") or {}
    if (not isinstance(raw,str) or hashlib.sha256(raw.encode("utf-8")).hexdigest()!=rep.get("raw_source_sha256")
            or (proof.get("assertion_type")=="structured_attribute_assertion"
                and rep.get("raw_source_sha256")!=proof.get("raw_source_sha256"))
            or rep.get("raw_source_ref")!=document.get("local_source_id")):
        reasons.append("RAW_SOURCE_HASH_OR_REFERENCE_INVALID")
    parser=_RawHTMLIndex()
    try:parser.feed(raw if isinstance(raw,str) else "")
    except Exception:reasons.append("RAW_HTML_PARSE_INVALID")
    assertions=rep.get("assertions")
    if not isinstance(assertions,list) or len(assertions)!=len(parser.elements):
        reasons.append("RAW_SOURCE_ASSERTION_INDEX_MISMATCH")
        assertions=[]
    normalized=[]
    for actual,assertion in zip(parser.elements,assertions):
        if not isinstance(assertion,dict):
            reasons.append("RAW_SOURCE_ASSERTION_INVALID"); continue
        locator=f"html:{actual['line']}:{actual['column']}:{actual['tag']}#{actual['ordinal']}"
        if (any(assertion.get(k)!=actual.get(k) for k in ("tag","line","column","ordinal","raw_start_tag","attributes"))
                or assertion.get("normalized_lines") is None):
            reasons.append("RAW_SOURCE_LOCATOR_OR_ATTRIBUTES_MISMATCH")
        if actual["tag"]=="source-document":
            a={k.removeprefix("data-"):v for k,v in actual["attributes"].items()}
            checks={"document_id":"document-id","model_id":"model-id","generation_id":"generation-id",
                    "captured_at":"captured-at","published_at":"published-at","source_kind":"source-kind",
                    "lineage_id":"lineage-id","edition_id":"edition-id"}
            if any(document.get(target)!=(a.get(attr) or (document.get(target) if target in {"lineage_id","edition_id"} else None))
                   for target,attr in checks.items()):
                reasons.append("RAW_SOURCE_DOCUMENT_METADATA_MISMATCH")
            continue
        a={k.removeprefix("data-"):v for k,v in actual["attributes"].items()}
        expected=None
        if actual["tag"]=="claim" and all(a.get(k) for k in ("field","trim","value")):
            value=a["value"]
            if a.get("unit") and not re.search(r"\s"+re.escape(a["unit"])+r"$",value):value+=f" {a['unit']}"
            expected=f"claim|{a['field']}|{a['trim']}|{value}"+("|"+a["qualifiers"] if a.get("qualifiers") else "")
        elif actual["tag"]=="trim" and a.get("id"):
            expected=f"lineup|trim|{a['id']}"
        elif actual["tag"]=="complete-lineup":
            expected=(f"lineup_attestation|COMPLETE_CURRENT_THAI_RETAIL_LINEUP|model={document.get('model_id')}|"
                      f"generation={document.get('generation_id')}|model_year={a.get('model-year','NONE')}|facelift={a.get('facelift-id','NONE')}")
        elif actual["tag"]=="capture":
            expected=(f"capture|edition={document.get('edition_id')}|capture_id={a.get('id','')}|"
                      f"captured_at={a.get('captured-at',document.get('captured_at',''))}|method=LOCAL_FIXTURE_CAPTURE")
        declared=assertion.get("normalized_lines")
        if expected is None or declared!=[expected]:
            reasons.append("NORMALIZED_ASSERTION_NOT_SUPPORTED_BY_RAW_SOURCE")
        else:normalized.append(expected)
    content_lines=document.get("content","").splitlines()
    if sorted(normalized)!=sorted(content_lines):
        reasons.append("NORMALIZED_CONTENT_NOT_BOUND_TO_RAW_ASSERTIONS")
    return {"valid":not reasons,"reason_codes":sorted(set(reasons))}


def validate_model_lineup_binding(snapshot: dict, model: dict) -> tuple[bool, str]:
    """Validate the same document-bound source contract used by retail reconciliation."""
    evidence = model.get("lineup_evidence") or {}
    document = evidence.get("source_document")
    if not isinstance(document, dict):
        return False, "LINEUP_SOURCE_DOCUMENT_MISSING"
    verdict = validate_source_completeness(document)
    if not verdict["complete"]:
        return False, "LINEUP_SOURCE_DOCUMENT_INVALID"
    if (evidence.get("document_id") != document.get("document_id")
            or evidence.get("document_sha256") != document.get("content_sha256")
            or evidence.get("market") != document.get("market")
            or evidence.get("source_authority") != document.get("source_authority")
            or evidence.get("completeness") != document.get("completeness")
            or evidence.get("model_id") != model.get("id")
            or evidence.get("generation_id") != document.get("generation_id")
            or evidence.get("trim_ids") != document.get("trim_ids")
            or evidence.get("captured_at") != document.get("captured_at")):
        return False, "LINEUP_SOURCE_REFERENCE_MISMATCH"
    generations = {g["id"]: g for g in snapshot.get("generations", [])}
    trims = {t["id"]: t for t in snapshot.get("trims", [])}
    gen = generations.get(document.get("generation_id"))
    if not gen or gen.get("model_id") != model.get("id"):
        return False, "LINEUP_GENERATION_SCOPE_MISMATCH"
    for row in document.get("lineup_rows", []):
        trim = trims.get(row["market_trim_id"])
        if not trim or trim.get("model_id") != model.get("id") or trim.get("generation_id") != gen["id"]:
            return False, "LINEUP_TRIM_IDENTITY_UNRESOLVED"
        model_year = trim.get("model_year", gen.get("model_year"))
        facelift = trim.get("facelift_id", gen.get("facelift_id"))
        if (row.get("powertrain") != trim.get("powertrain") or row.get("grade") != trim.get("grade")
                or row.get("model_year") != model_year or row.get("facelift_id") != facelift):
            return False, "LINEUP_TRIM_SCOPE_MISMATCH"
    return True, "DOCUMENT_BOUND_COMPLETE_LINEUP"


def validate_reconciliation_output(result: dict) -> None:
    if not isinstance(result, dict) or not isinstance(result.get("outcomes"), list):
        raise ValueError("retail reconciliation output is missing outcomes")
    if result.get("canonical_writes") != 0:
        raise ValueError("retail reconciliation output cannot write canonical data")
    policy = result.get("evidence_policy")
    if (not isinstance(policy, dict) or policy.get("approval_status") != "PENDING_OWNER_APPROVAL"
            or type(policy.get("minimum_independent_negative_interval_days")) is not int
            or policy["minimum_independent_negative_interval_days"] < 1):
        raise ValueError("reconciliation output must expose the pending structural evidence policy")
    for row in result["outcomes"]:
        if row.get("outcome") not in OUTCOMES or not isinstance(row.get("reason_codes"), list):
            raise ValueError("invalid retail reconciliation outcome contract")
        if row.get("outcome") == "SOFT_DISCONTINUE_PROPOSAL" and row.get("soft_archive_only") is not True:
            raise ValueError("discontinuation outcome must be a soft archive proposal")


def validate_source_completeness(document: dict) -> dict:
    """Validate a normalized capture and explicit publisher completeness evidence."""
    reasons: list[str] = []
    representation=validate_source_representation(document)
    if not representation["valid"]:reasons.extend(representation["reason_codes"])
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
    provenance = document.get("capture_provenance")
    if (not isinstance(document.get("edition_id"), str) or not document.get("edition_id")
            or not isinstance(document.get("capture_provenance"), dict)
            or not isinstance(provenance.get("capture_id"), str) or not provenance.get("capture_id")
            or provenance.get("capture_method") != "LOCAL_FIXTURE_CAPTURE"
            or provenance.get("captured_at") != document.get("captured_at")):
        reasons.append("CAPTURE_PROVENANCE_MISSING_OR_INVALID")
    provenance_data = provenance if isinstance(provenance, dict) else {}
    capture_line = (f"capture|edition={document.get('edition_id')}|"
                    f"capture_id={provenance_data.get('capture_id')}|"
                    f"captured_at={provenance_data.get('captured_at')}|method=LOCAL_FIXTURE_CAPTURE")
    if not isinstance(content, str) or capture_line not in content.splitlines():
        reasons.append("CAPTURE_PROVENANCE_NOT_BOUND_TO_CONTENT")
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
        lines = content.splitlines() if isinstance(content, str) else []
        if proof.get("assertion_type")=="structured_attribute_assertion":
            locator=proof.get("raw_source_locator")
            assertions=(document.get("source_representation") or {}).get("assertions",[])
            bound=any(isinstance(a,dict) and a.get("tag")=="complete-lineup"
                      and locator==f"html:{a.get('line')}:{a.get('column')}:complete-lineup#{a.get('ordinal')}"
                      for a in assertions)
            if (proof.get("publisher_declared_complete") is not True or not bound
                    or not isinstance(proof.get("normalized_scope_record"),str)
                    or proof.get("normalized_scope_record") not in lines):
                reasons.append("PUBLISHER_COMPLETENESS_NOT_EVIDENCED")
            assertion=next((a for a in assertions if isinstance(a,dict) and a.get("tag")=="complete-lineup"
                            and f"html:{a.get('line')}:{a.get('column')}:complete-lineup#{a.get('ordinal')}"==locator),None)
            attrs={k.removeprefix("data-"):v for k,v in (assertion or {}).get("attributes",{}).items()}
            if (attrs.get("publisher-declared-complete")!="true" or attrs.get("pagination-complete")!="true"
                    or attrs.get("expected-pages")!=attrs.get("captured-pages")
                    or not attrs.get("expected-pages","").isdigit()
                    or attrs.get("model-id")!=document.get("model_id")
                    or attrs.get("generation-id")!=document.get("generation_id")):
                reasons.append("RAW_COMPLETENESS_ATTRIBUTES_INSUFFICIENT")
        else:
            quote, locator = proof.get("quote"), proof.get("locator")
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
                or proof.get("expected_page_count") != proof.get("captured_page_count")
                or (isinstance(manifest, dict)
                    and (proof.get("expected_page_count") != manifest.get("source_page_count")
                         or proof.get("captured_page_count") != manifest.get("source_page_count"))
                    or (isinstance(provenance, dict)
                        and provenance.get("captured_page_count") != proof.get("captured_page_count")))):
            reasons.append("PAGE_COUNT_MISMATCH")
    lines = content.splitlines() if isinstance(content, str) else []
    attested_scope = _document_attestation(document, lines)
    if (not attested_scope or attested_scope.get("model_id") != document.get("model_id")
            or attested_scope.get("generation_id") != document.get("generation_id")):
        reasons.append("PUBLISHER_ATTESTATION_SEMANTICS_OR_SCOPE_INVALID")
    captured_lines = [CAPTURE_RE.fullmatch(line) for line in lines if CAPTURE_RE.fullmatch(line)]
    captured_line = captured_lines[0] if len(captured_lines) == 1 else None
    if (not captured_line or captured_line.group(1) != document.get("edition_id")
            or captured_line.group(2) != provenance_data.get("capture_id")
            or captured_line.group(3) != document.get("captured_at")):
        reasons.append("CAPTURE_PROVENANCE_NOT_BOUND_TO_CONTENT")
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
                           or not attested_scope
                           or r.get("model_year") != attested_scope.get("model_year")
                           or r.get("facelift_id") != attested_scope.get("facelift_id")
                           or not isinstance(r.get("powertrain"), str) or not r.get("powertrain") for r in rows)):
                reasons.append("NORMALIZED_LINEUP_ROWS_INVALID")
    return {"complete": not reasons, "reason_codes": sorted(set(reasons)),
            "trim_ids": sorted(document.get("trim_ids", [])) if not reasons else []}


def _identity(row: dict) -> tuple:
    """MarketTrim identity fields are exact and never fuzzy matched."""
    return (row.get("model_id"), row.get("generation_id"), row.get("grade"),
            row.get("powertrain"), row.get("model_year"), row.get("facelift_id"))


def _scope(document: dict) -> dict | None:
    content = document.get("content", "")
    return _document_attestation(document, content.splitlines())


def _trim_in_scope(trim: dict, generation: dict, scope: dict) -> bool:
    year = trim.get("model_year", generation.get("model_year"))
    facelift = trim.get("facelift_id", generation.get("facelift_id"))
    return (trim.get("generation_id") == scope["generation_id"]
            and year == scope["model_year"] and facelift == scope["facelift_id"])


def _independent_negative(old: dict, current: dict, trim_id: str, scope: dict,
                          minimum_interval_days: int) -> bool:
    old_check = validate_source_completeness(old)
    old_scope = _scope(old)
    if not old_check["complete"] or not old_scope or old_scope != scope:
        return False
    if (old.get("market") != "TH" or old.get("source_authority") != "OFFICIAL"
            or old.get("model_id") != current.get("model_id")
            or old.get("generation_id") != current.get("generation_id")
            or trim_id in set(old.get("trim_ids", []))):
        return False
    provenance_old = old.get("capture_provenance") or {}
    provenance_current = current.get("capture_provenance") or {}
    if (old.get("content_sha256") == current.get("content_sha256")
            or old.get("edition_id") == current.get("edition_id")
            or provenance_old.get("capture_id") == provenance_current.get("capture_id")):
        return False
    try:
        old_date = date.fromisoformat(old["captured_at"])
        current_date = date.fromisoformat(current["captured_at"])
    except (KeyError, TypeError, ValueError):
        return False
    return old_date < current_date and (current_date - old_date).days >= minimum_interval_days


def _validated_retail_end_of_sale(document: dict, trim_id: str, trim: dict,
                                  generation: dict, scope: dict, as_of: str) -> bool:
    lines = document.get("content", "").splitlines()
    try:
        captured = date.fromisoformat(document["captured_at"])
        snapshot_date = date.fromisoformat(as_of)
    except (KeyError, TypeError, ValueError):
        return False
    if captured > snapshot_date:
        return False
    for evidence in document.get("end_of_sale_evidence", []):
        if not isinstance(evidence, dict) or evidence.get("event_type") != "RETAIL_SALE_ENDED":
            continue
        quote, locator = evidence.get("quote"), evidence.get("locator", "")
        try:
            line_no = int(locator.split(":", 1)[1]) if locator.startswith("line:") else -1
        except ValueError:
            line_no = -1
        match = RETAIL_END_RE.fullmatch(quote or "")
        if not match or not (1 <= line_no <= len(lines) and lines[line_no - 1] == quote):
            continue
        model_id, generation_id, stated_trim, year_text, facelift_text, effective_text = match.groups()
        try:
            effective = date.fromisoformat(effective_text)
        except ValueError:
            continue
        trim_year = trim.get("model_year", generation.get("model_year"))
        trim_facelift = trim.get("facelift_id", generation.get("facelift_id"))
        if (stated_trim == trim_id and model_id == document.get("model_id")
                and generation_id == scope["generation_id"]
                and _parse_scope_value(year_text) == trim_year == scope["model_year"]
                and _parse_scope_value(facelift_text) == trim_facelift == scope["facelift_id"]
                and evidence.get("market_trim_id") == trim_id
                and evidence.get("model_id") == model_id and evidence.get("generation_id") == generation_id
                and evidence.get("effective_date") == effective_text
                and effective <= captured and effective <= snapshot_date):
            return True
    return False


def reconcile_retail_lineup(snapshot: dict, document: dict, *, policy: dict,
                            prior_complete_documents: list[dict] | None = None) -> dict:
    """Return deterministic per-MarketTrim outcomes; all structural changes are proposals."""
    from .validation import validate_policy
    validate_policy(policy)
    structural_policy = policy["structural_evidence"]
    minimum_interval_days = structural_policy["minimum_independent_negative_interval_days"]
    evidence_policy = {"approval_status": structural_policy["approval_status"],
                       "minimum_independent_negative_interval_days": minimum_interval_days}

    def finish(result: dict) -> dict:
        result["evidence_policy"] = evidence_policy
        validate_reconciliation_output(result)
        return result

    completeness = validate_source_completeness(document)
    model_id = document.get("model_id")
    model = next((x for x in snapshot.get("models", []) if x.get("id") == model_id), None)
    generation = next((x for x in snapshot.get("generations", []) if x.get("id") == document.get("generation_id")), None)
    if not model or not generation or generation.get("model_id") != model_id:
        result = {"model_id": model_id, "outcomes": [], "model_outcome": "REVIEW",
                  "reason_codes": ["MODEL_GENERATION_IDENTITY_UNRESOLVED"], "canonical_writes": 0}
        return finish(result)
    if model.get("status") != "CURRENT" or model.get("admin_retired"):
        result = {"model_id": model_id, "outcomes": [], "model_outcome": "REVIEW",
                  "reason_codes": ["MODEL_NOT_ELIGIBLE_FOR_RETAIL_RECONCILIATION"], "canonical_writes": 0}
        return finish(result)
    try:
        if date.fromisoformat(document["captured_at"]) > date.fromisoformat(snapshot["as_of"]):
            result = {"model_id": model_id, "outcomes": [{"market_trim_id": None, "outcome": "HOLD",
                      "reason_codes": ["SOURCE_CAPTURE_AFTER_SNAPSHOT"]}], "model_outcome": "HOLD",
                      "reason_codes": ["SOURCE_CAPTURE_AFTER_SNAPSHOT"], "canonical_writes": 0}
            return finish(result)
    except (KeyError, TypeError, ValueError):
        result = {"model_id": model_id, "outcomes": [{"market_trim_id": None, "outcome": "HOLD",
                  "reason_codes": ["SOURCE_OR_SNAPSHOT_DATE_INVALID"]}], "model_outcome": "HOLD",
                  "reason_codes": ["SOURCE_OR_SNAPSHOT_DATE_INVALID"], "canonical_writes": 0}
        return finish(result)
    all_model_trims = {t["id"]: t for t in snapshot.get("trims", []) if t.get("model_id") == model_id}
    scope = _scope(document) if completeness["complete"] else None
    generation_rows = {g["id"]: g for g in snapshot.get("generations", [])}
    trims = {tid: trim for tid, trim in all_model_trims.items()
             if scope and _trim_in_scope(trim, generation_rows.get(trim.get("generation_id"), {}), scope)}
    approved = next((s for s in snapshot.get("current_retail_sets", []) if s.get("model_id") == model_id), None)
    protected = set(approved.get("trim_ids", [])) if approved else set()
    listed = set(completeness["trim_ids"])
    results: list[dict] = []
    if not completeness["complete"]:
        results.extend({"market_trim_id": tid, "outcome": "HOLD",
                        "reason_codes": ["OUT_OF_SCOPE_GENERATION"] if trim.get("generation_id") != document.get("generation_id")
                                        else completeness["reason_codes"]}
                       for tid, trim in sorted(all_model_trims.items()))
        if not results:
            results.append({"market_trim_id": None, "outcome": "HOLD", "reason_codes": completeness["reason_codes"]})
        result = {"model_id": model_id, "outcomes": results, "model_outcome": "HOLD",
                  "reason_codes": completeness["reason_codes"], "canonical_writes": 0}
        return finish(result)

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
        if (row.get("model_id") != model_id or row.get("generation_id") != document.get("generation_id")
                or row.get("model_year") != scope["model_year"] or row.get("facelift_id") != scope["facelift_id"]):
            results.append({"market_trim_id": tid, "outcome": "REVIEW", "reason_codes": ["CROSS_MODEL_OR_GENERATION_IDENTITY"]})
            continue
        existing = all_model_trims.get(tid)
        if existing:
            if existing.get("generation_id") != scope["generation_id"]:
                results.append({"market_trim_id": tid, "outcome": "REVIEW", "reason_codes": ["CANONICAL_ID_OTHER_GENERATION"]})
            elif not _trim_in_scope(existing, generation_rows.get(existing.get("generation_id"), {}), scope) or _identity(row) != _identity(existing):
                results.append({"market_trim_id": tid, "outcome": "REVIEW", "reason_codes": ["CANONICAL_IDENTITY_COLLISION"]})
            elif existing.get("status") != "CURRENT" or existing.get("admin_retired") or existing.get("owner_retired"):
                results.append({"market_trim_id": tid, "outcome": "REVIEW", "reason_codes": ["NON_CURRENT_OR_RETIRED_TRIM_PROTECTED"]})
            else:
                results.append({"market_trim_id": tid, "outcome": "KEEP", "reason_codes": ["EXACT_MARKET_TRIM_IDENTITY"]})
        else:
            collision = any(_identity(t) == _identity(row) for t in all_model_trims.values())
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
        generation = generation_rows[trim["generation_id"]]
        explicit = _validated_retail_end_of_sale(document, tid, trim, generation, scope, snapshot["as_of"])
        enough_interval = any(_independent_negative(old, document, tid, scope, minimum_interval_days)
                              for old in prior)
        if trim.get("status") == "CURRENT" and (explicit or enough_interval):
            reason = "FIRST_PARTY_END_OF_SALE" if explicit else "TWO_INDEPENDENT_COMPLETE_LINEUPS"
            results.append({"market_trim_id": tid, "outcome": "SOFT_DISCONTINUE_PROPOSAL", "reason_codes": [reason],
                            "soft_archive_only": True})
        else:
            results.append({"market_trim_id": tid, "outcome": "HOLD", "reason_codes": ["ABSENCE_IN_COMPLETE_LINEUP_INSUFFICIENT"]})
    # Captures apply only to the attested generation/model-year/facelift slice.
    # Other slices are surfaced as HOLD without interpreting absence.
    for tid, trim in sorted(all_model_trims.items()):
        if tid in trims:
            continue
        code = ("OUT_OF_SCOPE_GENERATION" if trim.get("generation_id") != scope["generation_id"]
                else "OUT_OF_SCOPE_MODEL_YEAR_OR_FACELIFT")
        results.append({"market_trim_id": tid, "outcome": "HOLD", "reason_codes": [code]})
    outcomes = [x["outcome"] for x in results]
    model_outcome = "REVIEW" if "REVIEW" in outcomes else ("HOLD" if "HOLD" in outcomes else "KEEP")
    result = {"model_id": model_id, "outcomes": results, "model_outcome": model_outcome,
              "reason_codes": [], "canonical_writes": 0,
              "proposal_count": sum(x["outcome"].endswith("_PROPOSAL") for x in results)}
    return finish(result)
