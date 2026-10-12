"""Frozen value objects for offline replay; serialized output is JSON only."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    source_id: str
    market: str
    model_id: str
    generation_id: str
    trim_ids: tuple[str, ...]
    document_sha256: str
    local_source_id: str
    captured_at: str
    published_at: str | None
    completeness: str
    source_authority: str
    extraction_method: str


@dataclass(frozen=True)
class SourceClaim:
    field_key: str
    trim_id: str
    value: Any
    unit: str | None
    qualifiers: tuple[tuple[str, str], ...]
    quote: str
    locator: str


@dataclass(frozen=True)
class FieldCandidate:
    document_id: str
    document_sha256: str
    source_id: str
    source_authority: str
    market: str
    model_id: str
    generation_id: str
    trim_id: str
    powertrain: str
    field_key: str
    value: Any
    unit: str | None
    qualifiers: tuple[tuple[str, str], ...]
    quote: str
    locator: str
    published_at: str | None
    captured_at: str
    completeness: str
    source_kind: str
    lineage_id: str
    extraction_method: str
    candidate_status: str


@dataclass(frozen=True)
class FieldDisposition:
    trim_id: str
    field_key: str
    state: str
    replay_state: str


@dataclass(frozen=True)
class ReplaySummary:
    documents_seen: int
    candidates_total: int
    accepted_candidates: int
    held_candidates: int
    rejected_candidates: int
    external_http_calls: int = 0
    paid_model_calls: int = 0
    paid_tokens: int = 0
    paid_spend_thb: int = 0
    production_writes: int = 0


@dataclass(frozen=True)
class ReplayReport:
    replay_evidence: tuple[SourceDocument, ...]
    field_candidates: tuple[FieldCandidate, ...]
    gap_diff: tuple[FieldDisposition, ...]
    summary: ReplaySummary
