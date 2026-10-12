"""Capped, fixture-only structured extraction; there is no live model client."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import tempfile

from .replay import SUPPORTED, replay
from .registry_adapter import load_registry

MODEL_ID = "claude-haiku-4-5-20251001"
PROMPT_VERSION = "catalog-extract-v1"
EXTRACTION_METHOD = "AI_STRUCTURED_MOCK_V1"
MAX_SNIPPET_CHARS = 2400
MAX_TARGETS = 24
MAX_CLAIMS = 24
MAX_MOCK_REQUESTS = 3
OPEN_STATES = {"MISSING", "UNKNOWN", "NEEDS_SOURCE_TRACE", "SOURCE_EXHAUSTED", "NOT_AVAILABLE"}


class ExtractionError(ValueError):
    """Fail-closed error for malformed mock requests, responses or cache rows."""


@dataclass(frozen=True)
class ExtractionRequest:
    request_key: str
    model_id: str
    document_id: str
    document_sha256: str
    market: str
    snippet: str
    target_pairs: tuple[tuple[str, str], ...]
    prompt_version: str = PROMPT_VERSION


class ExtractionProvider:
    """Narrow local contract for model-shaped responses."""

    mode: str
    model_id: str

    def extract(self, request: ExtractionRequest) -> dict:
        raise NotImplementedError


class RecordedMockProvider(ExtractionProvider):
    """Read one pre-recorded response tape; performs no HTTP or SDK operation."""

    mode = "MOCK"

    def __init__(self, tape: dict):
        if not isinstance(tape, dict) or set(tape) != {"schema_version", "mode", "model_id", "responses"}:
            raise ExtractionError("MOCK_TAPE_SCHEMA_INVALID")
        if tape["schema_version"] != "1.0" or tape["mode"] != "MOCK" or tape["model_id"] != MODEL_ID:
            raise ExtractionError("MOCK_TAPE_MODE_OR_MODEL_INVALID")
        if not isinstance(tape["responses"], dict):
            raise ExtractionError("MOCK_TAPE_RESPONSES_INVALID")
        self.model_id = tape["model_id"]
        self.responses = tape["responses"]
        self.fixture_reads = 0

    def extract(self, request: ExtractionRequest) -> dict:
        self.fixture_reads += 1
        response = self.responses.get(request.request_key)
        if response is None:
            raise ExtractionError("MOCK_RESPONSE_NOT_RECORDED")
        return response


def _stable(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _request_key(doc: dict, pairs: list[tuple[str, str]]) -> str:
    payload = {"model_id": MODEL_ID, "prompt_version": PROMPT_VERSION,
               "document_sha256": doc["content_sha256"], "market": doc["market"],
               "snippet_sha256": hashlib.sha256(doc["content"].encode("utf-8")).hexdigest(),
               "targets": [list(pair) for pair in pairs]}
    return hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()


def _request(doc: dict, pairs: list[tuple[str, str]]) -> ExtractionRequest:
    return ExtractionRequest(_request_key(doc, pairs), MODEL_ID, doc["document_id"],
                             doc["content_sha256"], doc["market"], doc["content"], tuple(pairs))


def _response_claims(response: dict, request: ExtractionRequest, doc: dict,
                     registry: dict) -> tuple[list[dict], list[dict]]:
    if (not isinstance(response, dict) or set(response) != {"schema_version", "mode", "model_id", "request_key", "claims"}
            or response.get("schema_version") != "1.0" or response.get("mode") != "MOCK"
            or response.get("model_id") != request.model_id or response.get("request_key") != request.request_key
            or not isinstance(response.get("claims"), list) or len(response["claims"]) > MAX_CLAIMS):
        raise ExtractionError("MOCK_RESPONSE_SCHEMA_OR_BINDING_INVALID")
    lines = doc["content"].splitlines()
    requested = set(request.target_pairs)
    accepted, held = [], []
    seen = set()
    for index, row in enumerate(response["claims"]):
        if not isinstance(row, dict) or set(row) != {"field_key", "trim_id", "value_text", "qualifiers", "quote", "locator"}:
            raise ExtractionError("MOCK_CLAIM_SCHEMA_INVALID")
        if (not isinstance(row["field_key"], str) or not isinstance(row["trim_id"], str)
                or not isinstance(row["value_text"], str) or not isinstance(row["qualifiers"], dict)
                or not isinstance(row["quote"], str) or not isinstance(row["locator"], str)):
            raise ExtractionError("MOCK_CLAIM_TYPES_INVALID")
        pair = (row["trim_id"], row["field_key"])
        locator, quote = row["locator"], row["quote"]
        reason = None
        if pair not in requested:
            reason = "CLAIM_OUTSIDE_REQUESTED_GAPS"
        elif row["field_key"] not in SUPPORTED:
            reason = "FIELD_UNSUPPORTED_OR_OUT_OF_SCOPE"
        elif pair in seen:
            reason = "DUPLICATE_MODEL_CLAIM"
        elif not isinstance(locator, str) or not re.fullmatch(r"line:[1-9][0-9]*", locator):
            reason = "QUOTE_LOCATOR_INVALID"
        elif not isinstance(quote, str) or not quote:
            reason = "QUOTE_MISSING"
        else:
            line_number = int(locator.split(":", 1)[1])
            if line_number > len(lines) or quote != lines[line_number - 1]:
                reason = "QUOTE_LOCATOR_MISMATCH"
        value_text = row["value_text"]
        if reason is None and (not isinstance(value_text, str) or not value_text.strip() or value_text not in quote):
            reason = "VALUE_NOT_QUOTED"
        qualifiers = row["qualifiers"]
        allowed_qualifiers = set(registry["fields"].get(row["field_key"], {}).get("comparison_qualifiers", []))
        if reason is None and (not set(qualifiers) <= allowed_qualifiers
                               or any(not isinstance(value, str) or not value
                                      or value not in quote for key, value in qualifiers.items())):
            reason = "QUALIFIERS_NOT_QUOTED"
        if reason:
            held.append({"claim_index": index, "trim_id": row.get("trim_id"),
                         "field_key": row.get("field_key"), "status": "HELD", "reason_code": reason})
        else:
            accepted.append({"field_key": row["field_key"], "trim_id": row["trim_id"],
                             "value_text": value_text, "qualifiers": qualifiers,
                             "quote": quote, "locator": locator})
            seen.add(pair)
    return accepted, held


def run_mock_extraction(snapshot_path: str | Path, document_paths: list[str | Path],
                        response_tape_path: str | Path, cache_dir: str | Path,
                        output_dir: str | Path, *, confirm_mock_only: bool,
                        root: Path | None = None) -> dict:
    """Replay cassette output through the canonical evidence/gap validator."""
    if confirm_mock_only is not True:
        raise ExtractionError("MOCK_ONLY_ACKNOWLEDGEMENT_REQUIRED")
    from .replay import _valid_document

    docs = [json.loads(Path(path).read_text(encoding="utf-8")) for path in document_paths]
    docs.sort(key=lambda row: row.get("document_id", ""))
    for doc in docs:
        _valid_document(doc)
    tape = json.loads(Path(response_tape_path).read_text(encoding="utf-8"))
    provider = RecordedMockProvider(tape)
    if provider.mode != "MOCK" or provider.model_id != MODEL_ID:
        raise ExtractionError("LIVE_PROVIDER_DISABLED")
    registry = load_registry(root=root)

    with tempfile.TemporaryDirectory(prefix="catalog-ai-baseline-") as temp:
        replay(snapshot_path, document_paths, temp, root=root)
        before = json.loads((Path(temp) / "gap_diff.json").read_text(encoding="utf-8"))
        baseline_candidates = [json.loads(line) for line in (Path(temp) / "field_candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    existing = {(row["trim_id"], row["field_key"]) for row in baseline_candidates}
    extracted: dict[str, list[dict]] = {}
    held_rows: list[dict] = []
    cache_root = Path(cache_dir)
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_hits = cache_misses = skipped_no_gap = 0
    for doc in docs:
        pairs = sorted({(row["trim_id"], row["field_key"]) for row in before["dispositions"]
                        if row["trim_id"] in doc["trim_ids"] and row["state"] in OPEN_STATES
                        and row["field_key"] in SUPPORTED and (row["trim_id"], row["field_key"]) not in existing})
        if not pairs:
            skipped_no_gap += 1
            continue
        if len(doc["content"]) > MAX_SNIPPET_CHARS or len(pairs) > MAX_TARGETS:
            held_rows.append({"document_id": doc["document_id"], "status": "HELD",
                              "reason_code": "SNIPPET_LIMIT_EXCEEDED" if len(doc["content"]) > MAX_SNIPPET_CHARS else "TARGET_LIMIT_EXCEEDED"})
            continue
        request = _request(doc, pairs)
        cache_path = cache_root / f"{request.request_key}.json"
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (not isinstance(cached, dict) or set(cached) != {"request_key", "response", "response_sha256"}
                    or cached["request_key"] != request.request_key
                    or hashlib.sha256(_stable(cached["response"]).encode("utf-8")).hexdigest() != cached["response_sha256"]):
                raise ExtractionError("CACHE_INTEGRITY_FAILURE_STOP")
            response = cached["response"]
            cache_hits += 1
        else:
            if provider.fixture_reads >= MAX_MOCK_REQUESTS:
                held_rows.append({"document_id": doc["document_id"], "status": "HELD",
                                  "reason_code": "MOCK_REQUEST_CAP_REACHED_STOP"})
                continue
            response = provider.extract(request)
            cache_misses += 1
        valid, held = _response_claims(response, request, doc, registry)
        held_rows.extend({"document_id": doc["document_id"], **row} for row in held)
        if valid:
            extracted[doc["document_id"]] = valid
        if not cache_path.exists():
            cache_row = {"request_key": request.request_key, "response": response,
                         "response_sha256": hashlib.sha256(_stable(response).encode("utf-8")).hexdigest()}
            temporary = cache_path.with_suffix(".tmp")
            temporary.write_text(_stable(cache_row) + "\n", encoding="utf-8")
            temporary.replace(cache_path)

    with tempfile.TemporaryDirectory(prefix="catalog-ai-validated-") as temp:
        summary = replay(snapshot_path, document_paths, temp, root=root,
                         extracted_claims=extracted, extraction_method=EXTRACTION_METHOD)
        evidence_text = (Path(temp) / "replay_evidence.jsonl").read_text(encoding="utf-8")
        candidates = [json.loads(line) for line in (Path(temp) / "field_candidates.jsonl").read_text(encoding="utf-8").splitlines()]
        gap_diff = json.loads((Path(temp) / "gap_diff.json").read_text(encoding="utf-8"))
    ai_keys = {(doc_id, row["trim_id"], row["field_key"]) for doc_id, rows in extracted.items() for row in rows}
    for row in candidates:
        if (row["document_id"], row["trim_id"], row["field_key"]) in ai_keys:
            row["extraction_origin"] = "RECORDED_MOCK_RESPONSE"
    summary.update({"mode": "MOCK", "provider_model_id": MODEL_ID,
                    "recorded_response_reads": provider.fixture_reads,
                    "cache_hits": cache_hits, "cache_misses": cache_misses,
                    "mock_request_cap": MAX_MOCK_REQUESTS,
                    "mock_request_cap_reached": any(row["reason_code"] == "MOCK_REQUEST_CAP_REACHED_STOP" for row in held_rows),
                    "skipped_no_open_gap": skipped_no_gap, "adapter_held_count": len(held_rows),
                    "adapter_held": held_rows, "external_http_calls": 0,
                    "paid_model_calls": 0, "paid_tokens": 0, "paid_spend_thb": 0,
                    "production_writes": 0, "live_provider_enabled": False})
    summary["accepted_ai_mock_candidates"] = sum(
        row.get("extraction_origin") == "RECORDED_MOCK_RESPONSE" and row["candidate_status"] == "ACCEPTED_CANDIDATE"
        for row in candidates)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "replay_evidence.jsonl").write_text(evidence_text, encoding="utf-8")
    (out / "field_candidates.jsonl").write_text("".join(_stable(row) + "\n" for row in sorted(
        candidates, key=lambda row: (row["model_id"], row["trim_id"], row["field_key"], row["document_id"]))), encoding="utf-8")
    gap_diff["ai_adapter_held"] = sorted(held_rows, key=lambda row: (row.get("document_id", ""), row.get("claim_index", -1), row["reason_code"]))
    (out / "gap_diff.json").write_text(json.dumps(gap_diff, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (out / "replay_summary.json").write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return summary
