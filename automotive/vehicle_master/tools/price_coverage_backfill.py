#!/usr/bin/env python3
"""One-time Current Retail Price Coverage Backfill.

The tool fills missing LIST_PRICE facts for existing canonical MarketTrim
identities.  It is intentionally conservative about *identity* while remaining
practical about *price*:

- one bad/partial source does not freeze a whole model;
- an exact, current price fact for one known trim may still be written even when
  the full lineup is not proven complete;
- only a HUMAN ``UNDER_MAINTENANCE`` state stops automated writes for the whole
  model;
- the price system never creates/renames/merges/retires MarketTrim identity;
- lineup completeness is a separate claim used for coverage/topology review,
  never inferred merely from a page being called PRICE_LIST;
- ``--apply`` revalidates current evidence before writing and writes in bounded,
  deterministic batches.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import re
from typing import Any, Optional
import urllib.parse

from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR, Model
from vehreg.input_pipeline import CanonicalInputPipeline
from vehreg.price_extract import ExtractionError, extract_oem_price_claims
from vehreg.price_fetch import FetchError, Transport, UrllibTransport, adapter_for
from vehreg.price_match import TrimMatchMethod, TrimMatchResult, TrimMatchState, match_trim_diagnostic
from vehreg.price_sources import SourceKind, TargetRole, load_source_target_registry
from vehreg.pricefeed import (
    PriceClaim, SourceDocument, body_sketch, content_id, grade_tokens, looks_reprinted,
)
from vehreg.pricefeed_writer import batch_id_for
from vehreg.pricing import PriceLedger, PriceType
from vehreg.retail_scope import (
    ModelScope, retail_scope_index, siblings_from_scope, trim_price_eligibility,
    trim_review_index,
)


class TerminalState(str, Enum):
    AUTO_READY = "AUTO_READY"
    COMPLETE = "COMPLETE"
    IDENTITY_BLOCKED = "IDENTITY_BLOCKED"
    SEMANTIC_BLOCKED = "SEMANTIC_BLOCKED"
    CAMPAIGN_ONLY = "CAMPAIGN_ONLY"
    PRICE_CONFLICT = "PRICE_CONFLICT"
    NO_SOURCE = "NO_SOURCE"


class LineupStatus(str, Enum):
    EXHAUSTIVE = "EXHAUSTIVE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class EvidenceTier(str, Enum):
    OEM_CURRENT_MODEL_PAGE = "OEM_CURRENT_MODEL_PAGE"
    MEDIA_TWO_AGREE = "MEDIA_TWO_AGREE"
    NONE = "NONE"


_AUTO_READY_METHODS = frozenset({TrimMatchMethod.EXACT_NAME, TrimMatchMethod.EXACT_ALIAS})
_NON_LIST_PRICE_TYPES = frozenset({
    PriceType.CAMPAIGN_PRICE, PriceType.FINANCE_PRICE, PriceType.ESTIMATED_PRICE,
    PriceType.DEALER_PRICE, PriceType.ECO_STICKER_PRICE, PriceType.INTRODUCTORY_PRICE,
})
_APPLY_CHUNK_SIZE = 400
_CURRENT_OEM_ROLES = frozenset({TargetRole.CURRENT_MODEL_PAGE, TargetRole.PRICE_LIST})


@dataclass(frozen=True, slots=True)
class GradeEvidence:
    raw_grade: str
    amount_thb: Optional[int]
    extracted_price_type: Optional[PriceType]
    evidence_tier: EvidenceTier
    source_ref: str
    observed_at: str
    semantics_clear: bool = True


@dataclass(frozen=True, slots=True)
class GradeClassification:
    evidence: GradeEvidence
    match: Optional[TrimMatchResult]
    terminal_state: TerminalState
    existing_list_price_thb: Optional[int]
    note: str = ""
    applied: bool = False
    applied_command_id: Optional[str] = None
    generation_id: Optional[str] = None

    @property
    def trim_id(self) -> Optional[str]:
        return self.match.trim_id if self.match else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_grade": self.evidence.raw_grade,
            "trim_id": self.trim_id,
            "generation_id": self.generation_id,
            "amount_thb": self.evidence.amount_thb,
            "extracted_price_type": self.evidence.extracted_price_type.value
                if self.evidence.extracted_price_type else None,
            "match_state": self.match.state.value if self.match else None,
            "match_method": self.match.method.value if self.match else None,
            "match_candidates": list(self.match.candidate_ids) if self.match else [],
            "evidence_tier": self.evidence.evidence_tier.value,
            "existing_list_price_thb": self.existing_list_price_thb,
            "terminal_state": self.terminal_state.value,
            "note": self.note,
            "source_ref": self.evidence.source_ref,
            "observed_at": self.evidence.observed_at,
            "applied": self.applied,
            "applied_command_id": self.applied_command_id,
        }


def classify_grade(evidence: GradeEvidence, match: Optional[TrimMatchResult], *,
                   existing_list_price_thb: Optional[int],
                   generation_id: Optional[str] = None) -> GradeClassification:
    """Classify one price fact.  Lineup completeness is intentionally absent.

    A page can be partial yet still prove one exact current LIST_PRICE.  This
    function therefore asks only whether *this claim* is safe to write.
    """
    if evidence.evidence_tier is EvidenceTier.NONE:
        return GradeClassification(
            evidence=evidence, match=match, terminal_state=TerminalState.NO_SOURCE,
            existing_list_price_thb=None, generation_id=generation_id,
            note="no qualifying current price evidence reached this grade")
    if not evidence.semantics_clear or evidence.extracted_price_type in (None, PriceType.UNKNOWN):
        return GradeClassification(
            evidence=evidence, match=match, terminal_state=TerminalState.SEMANTIC_BLOCKED,
            existing_list_price_thb=None, generation_id=generation_id,
            note="price semantics could not be safely established")
    if evidence.extracted_price_type in _NON_LIST_PRICE_TYPES:
        return GradeClassification(
            evidence=evidence, match=match, terminal_state=TerminalState.CAMPAIGN_ONLY,
            existing_list_price_thb=None, generation_id=generation_id,
            note=f"{evidence.extracted_price_type.value} evidence is not a normal LIST_PRICE")
    if match is None or match.state is not TrimMatchState.EXACT:
        return GradeClassification(
            evidence=evidence, match=match, terminal_state=TerminalState.IDENTITY_BLOCKED,
            existing_list_price_thb=None, generation_id=generation_id,
            note="claim does not resolve to exactly one canonical current trim")
    if match.method not in _AUTO_READY_METHODS:
        return GradeClassification(
            evidence=evidence, match=match, terminal_state=TerminalState.IDENTITY_BLOCKED,
            existing_list_price_thb=None, generation_id=generation_id,
            note=f"{match.method.value} is inference, not exact trim identity")
    if existing_list_price_thb is not None:
        if existing_list_price_thb == evidence.amount_thb:
            return GradeClassification(
                evidence=evidence, match=match, terminal_state=TerminalState.COMPLETE,
                existing_list_price_thb=existing_list_price_thb, generation_id=generation_id,
                note="current LIST_PRICE already matches")
        return GradeClassification(
            evidence=evidence, match=match, terminal_state=TerminalState.PRICE_CONFLICT,
            existing_list_price_thb=existing_list_price_thb, generation_id=generation_id,
            note=(f"discovered {evidence.amount_thb} THB differs from existing current "
                  f"LIST_PRICE {existing_list_price_thb} THB; never auto-corrected"))
    if evidence.evidence_tier not in {
            EvidenceTier.OEM_CURRENT_MODEL_PAGE, EvidenceTier.MEDIA_TWO_AGREE}:
        return GradeClassification(
            evidence=evidence, match=match, terminal_state=TerminalState.NO_SOURCE,
            existing_list_price_thb=None, generation_id=generation_id,
            note="evidence is not strong/current enough for an automatic write")
    return GradeClassification(
        evidence=evidence, match=match, terminal_state=TerminalState.AUTO_READY,
        existing_list_price_thb=None, generation_id=generation_id)


@dataclass
class ModelManifestEntry:
    model_id: str
    lineup_status: LineupStatus
    evidence_tier: EvidenceTier
    lineup_source: dict[str, Any]
    grades: list[GradeClassification] = field(default_factory=list)
    blocked_reason: str = ""
    topology_review_required: bool = False
    topology_note: str = ""

    @property
    def current_retail_model_complete(self) -> bool:
        if self.blocked_reason or self.topology_review_required:
            return False
        if self.lineup_status is not LineupStatus.EXHAUSTIVE or not self.grades:
            return False
        for grade in self.grades:
            if grade.match is None or grade.match.method not in _AUTO_READY_METHODS:
                return False
            if not (
                grade.terminal_state is TerminalState.COMPLETE
                or (grade.terminal_state is TerminalState.AUTO_READY and grade.applied)
            ):
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "lineup_status": self.lineup_status.value,
            "evidence_tier": self.evidence_tier.value,
            "lineup_source": self.lineup_source,
            "blocked_reason": self.blocked_reason,
            "topology_review_required": self.topology_review_required,
            "topology_note": self.topology_note,
            "current_retail_model_complete": self.current_retail_model_complete,
            "grades": [grade.to_dict() for grade in self.grades],
        }


@dataclass
class Manifest:
    generated_at: str
    models: list[ModelManifestEntry] = field(default_factory=list)
    schema_version: int = 1

    def summary(self) -> dict[str, Any]:
        counts = {state.value: 0 for state in TerminalState}
        lineup_counts = {status.value: 0 for status in LineupStatus}
        complete = 0
        topology_review = 0
        for model in self.models:
            lineup_counts[model.lineup_status.value] += 1
            complete += int(model.current_retail_model_complete)
            topology_review += int(model.topology_review_required)
            for grade in model.grades:
                counts[grade.terminal_state.value] += 1
        return {
            **counts,
            "lineup_status": lineup_counts,
            "current_retail_model_complete": complete,
            "topology_review_required": topology_review,
            "total_models": len(self.models),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "models": [model.to_dict() for model in self.models],
            "summary": self.summary(),
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        os.replace(tmp, path)


def load_manifest_dict(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError(f"{path}: unsupported manifest schema_version")
    return payload


# --------------------------------------------------------- media discovery

_MEDIA_SOURCES: tuple[tuple[str, str], ...] = (
    ("autolifethailand", "https://autolifethailand.tv"),
    ("headlightmag", "https://www.headlightmag.com"),
)
_OFFICIAL_PRICE_TITLE = re.compile(r"ราคาอย่างเป็นทางการ|official price|เปิดราคา", re.I)
_BAD_TITLE = re.compile(r"คาดการณ์|คาดราคา|ลุ้นราคา|มือสอง|used|display|demo|ส่วนลด|ราคาพิเศษ", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_AMOUNT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[,.]\d{3}){1,2}|\d{6,8})(?!\d)")


def _clean_text(raw: str) -> str:
    return _SPACE_RE.sub(" ", _TAG_RE.sub(" ", raw or "")).strip()


def _title_amounts(title: str) -> list[int]:
    if not re.search(r"ราคา|บาท|price", title, re.I):
        return []
    found: set[int] = set()
    for match in _AMOUNT_RE.finditer(title):
        value = int(match.group(1).replace(",", "").replace(".", ""))
        if 250_000 <= value <= 50_000_000:
            found.add(value)
    return sorted(found)


@dataclass(frozen=True, slots=True)
class MediaHit:
    source_id: str
    title: str
    url: str
    amounts: tuple[int, ...]
    official_title: bool
    excluded_title: bool
    sketch: tuple[str, ...] = ()


def _article_sketch(url: str, *, transport: Transport) -> tuple[str, ...]:
    if not url.startswith("http"):
        return ()
    try:
        response = transport.fetch(
            url, headers={"User-Agent": "TDR-price-backfill/1.0"}, timeout=25.0)
    except FetchError:
        return ()
    if response.status != 200:
        return ()
    try:
        text = response.body.decode("utf-8", errors="ignore")
    except AttributeError:
        return ()
    return body_sketch(_clean_text(text))


def _search_media_source(source_id: str, base_url: str, brand: str, model: str, *,
                         transport: Transport) -> list[MediaHit]:
    query = f"{brand} {model} ราคาอย่างเป็นทางการ"
    url = f"{base_url}/wp-json/wp/v2/search?search={urllib.parse.quote(query)}&per_page=10"
    try:
        response = transport.fetch(
            url, headers={"User-Agent": "TDR-price-backfill/1.0"}, timeout=25.0)
    except FetchError:
        return []
    if response.status != 200:
        return []
    try:
        hits = json.loads(response.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    results: list[MediaHit] = []
    model_folded = re.sub(r"[^a-z0-9ก-๙]+", "", model.casefold())
    for hit in hits if isinstance(hits, list) else []:
        title = _clean_text(str(hit.get("title") or ""))
        title_folded = re.sub(r"[^a-z0-9ก-๙]+", "", title.casefold())
        if model_folded and model_folded not in title_folded:
            continue
        hit_url = str(hit.get("url") or "")
        results.append(MediaHit(
            source_id=source_id,
            title=title,
            url=hit_url,
            amounts=tuple(_title_amounts(title)),
            official_title=bool(_OFFICIAL_PRICE_TITLE.search(title)),
            excluded_title=bool(_BAD_TITLE.search(title)),
            sketch=_article_sketch(hit_url, transport=transport),
        ))
    return results


def _resolved_media_trim_id(hit: MediaHit, siblings: list, model_name: str) -> Optional[str]:
    """Resolve a title to one and only one known trim.

    The deliberate ambiguity check prevents ``Premium`` from binding to a title
    that really names ``Premium Luxury``: both would be candidates, therefore
    neither is accepted automatically.
    """
    title_tokens = grade_tokens(hit.title, model_name)
    candidates: set[str] = set()
    for trim in siblings:
        for surface in (trim.name, *trim.aliases):
            tokens = grade_tokens(surface, model_name)
            if tokens and tokens <= title_tokens:
                candidates.add(trim.id)
                break
    return next(iter(candidates)) if len(candidates) == 1 else None


def _best_media_hit_for_trim(hits: list[MediaHit], trim_id: str, siblings: list,
                             model_name: str) -> Optional[MediaHit]:
    candidates = [
        hit for hit in hits
        if hit.official_title and not hit.excluded_title and len(hit.amounts) == 1
        and _resolved_media_trim_id(hit, siblings, model_name) == trim_id
    ]
    return candidates[0] if len(candidates) == 1 else None


def _independent_media_hits(left: MediaHit, right: MediaHit) -> bool:
    left_doc = SourceDocument(
        document_id=content_id(f"{left.source_id}|{left.url}|{left.title}"),
        source_id=left.source_id, url=left.url or "https://invalid.local/left",
        content_hash=content_id(left.title), body_sketch=left.sketch,
    )
    right_doc = SourceDocument(
        document_id=content_id(f"{right.source_id}|{right.url}|{right.title}"),
        source_id=right.source_id, url=right.url or "https://invalid.local/right",
        content_hash=content_id(right.title), body_sketch=right.sketch,
    )
    return not looks_reprinted(left_doc, right_doc)


def discover_media_grades(model: Model, siblings: list, *,
                          transport: Transport) -> list[GradeEvidence]:
    """Require two independent outlets to agree on one uniquely resolved trim."""
    if not siblings:
        return []
    hits_by_source = {
        source_id: _search_media_source(
            source_id, base_url, model.brand_id, model.name_en, transport=transport)
        for source_id, base_url in _MEDIA_SOURCES
    }
    evidence: list[GradeEvidence] = []
    source_ids = [source_id for source_id, _ in _MEDIA_SOURCES]
    if len(source_ids) < 2:
        return []
    for trim in siblings:
        left = _best_media_hit_for_trim(
            hits_by_source.get(source_ids[0], []), trim.id, siblings, model.name_en)
        right = _best_media_hit_for_trim(
            hits_by_source.get(source_ids[1], []), trim.id, siblings, model.name_en)
        if left is None or right is None:
            continue
        if left.amounts[0] != right.amounts[0]:
            continue
        if not _independent_media_hits(left, right):
            continue
        evidence.append(GradeEvidence(
            raw_grade=trim.name,
            amount_thb=left.amounts[0],
            extracted_price_type=PriceType.LIST_PRICE,
            evidence_tier=EvidenceTier.MEDIA_TWO_AGREE,
            source_ref=left.url,
            observed_at=date.today().isoformat(),
        ))
    return evidence


# ----------------------------------------------------------- OEM discovery


def discover_oem_grades(model: Model, registry, *, transport: Transport) -> Optional[
        tuple[LineupStatus, dict[str, Any], list[GradeEvidence]]]:
    """Use only OEM targets that explicitly represent current retail state.

    BLOG/PROMOTION/PRESS_RELEASE/LAUNCH_PAGE remain useful evidence elsewhere,
    but this one-time current-price backfill does not promote them to a current
    LIST_PRICE source merely because they are first-party.
    """
    targets = sorted(
        (target for target in registry.targets.values()
         if target.model_hint == model.id and target.enabled),
        key=lambda target: target.id,
    )
    for target in targets:
        profile = registry.profiles.get(target.source_id)
        if profile is None or profile.kind is not SourceKind.OEM:
            continue
        if target.role not in _CURRENT_OEM_ROLES:
            continue
        try:
            adapter = adapter_for(registry, target, transport=transport)
            result = adapter.fetch(target)
        except FetchError:
            continue
        if result.not_modified or result.document is None:
            continue
        try:
            extraction = extract_oem_price_claims(target, result)
        except ExtractionError:
            continue
        list_claims = [claim for claim in extraction.claims
                       if claim.price_type is PriceType.LIST_PRICE]
        if not list_claims:
            continue
        observed = date.today().isoformat()
        grades = [GradeEvidence(
            raw_grade=claim.trim_raw,
            amount_thb=claim.amount_thb,
            extracted_price_type=claim.price_type,
            evidence_tier=EvidenceTier.OEM_CURRENT_MODEL_PAGE,
            source_ref=target.url,
            observed_at=observed,
            semantics_clear=True,
        ) for claim in list_claims]
        lineup_status = (
            LineupStatus.EXHAUSTIVE if target.lineup_complete else LineupStatus.PARTIAL)
        source = {
            "role": target.role.value,
            "source_id": target.source_id,
            "url": target.url,
            "fetched_at": observed,
            "lineup_complete": bool(target.lineup_complete),
        }
        return lineup_status, source, grades
    return None


# --------------------------------------------------------- orchestration


def _topology_review(lineup_status: LineupStatus, grades: list[GradeClassification],
                     expected_siblings: list) -> tuple[bool, str]:
    """Detect topology drift only when the source explicitly proves completeness.

    This is a review signal, not a model-wide price-write stop. Exact price facts
    remain useful while humans reconcile a changed lineup.
    """
    if lineup_status is not LineupStatus.EXHAUSTIVE:
        return False, ""
    expected = {trim.id for trim in expected_siblings}
    matched = {
        grade.trim_id for grade in grades
        if grade.trim_id and grade.match and grade.match.state is TrimMatchState.EXACT
    }
    identity_problem = any(
        grade.terminal_state is TerminalState.IDENTITY_BLOCKED for grade in grades)
    if identity_problem or matched != expected:
        missing = sorted(expected - matched)
        extra = sorted(matched - expected)
        return True, (
            "complete current lineup does not match canonical topology; "
            f"missing={missing}, unexpected={extra}. Price facts for exact known trims may "
            "continue, but lineup-level completeness requires human review."
        )
    return False, ""


def discover_model(model: Model, catalog: Catalog, ledger: PriceLedger, registry, *,
                   scope: ModelScope, siblings_by_model: dict[str, list],
                   transport: Transport) -> ModelManifestEntry:
    siblings = siblings_by_model.get(model.id, [])
    oem_result = discover_oem_grades(model, registry, transport=transport)
    if oem_result is not None:
        lineup_status, source, grade_evidence_list = oem_result
        evidence_tier = EvidenceTier.OEM_CURRENT_MODEL_PAGE
    else:
        media_grades = discover_media_grades(model, siblings, transport=transport)
        if media_grades:
            lineup_status = LineupStatus.PARTIAL
            evidence_tier = EvidenceTier.MEDIA_TWO_AGREE
            source = {
                "role": "MEDIA_SEARCH",
                "source_id": "autolifethailand+headlightmag",
                "url": media_grades[0].source_ref,
                "fetched_at": media_grades[0].observed_at,
                "lineup_complete": False,
            }
            grade_evidence_list = media_grades
        else:
            lineup_status = LineupStatus.UNKNOWN
            evidence_tier = EvidenceTier.NONE
            source = {}
            grade_evidence_list = [GradeEvidence(
                raw_grade=model.name_en,
                amount_thb=None,
                extracted_price_type=None,
                evidence_tier=EvidenceTier.NONE,
                source_ref="",
                observed_at=date.today().isoformat(),
            )]

    grades: list[GradeClassification] = []
    for evidence in grade_evidence_list:
        match = None
        if evidence.evidence_tier is not EvidenceTier.NONE:
            claim = PriceClaim(
                claim_id=f"backfill-{model.id}-{evidence.raw_grade}",
                document_id="sha256:" + "0" * 64,
                source_id=source.get("source_id", ""),
                brand_raw=model.brand_id,
                model_raw=model.name_en,
                trim_raw=evidence.raw_grade,
                amount_thb=evidence.amount_thb or 0,
                price_type=evidence.extracted_price_type or PriceType.UNKNOWN,
            )
            match = match_trim_diagnostic(
                catalog, claim, siblings_by_model=siblings_by_model)
        existing = None
        generation_id = None
        if match is not None and match.trim_id is not None:
            trim = catalog.trims.get(match.trim_id)
            generation_id = trim.generation_id if trim else None
            row = ledger.current_list_price(match.trim_id)
            existing = row.amount_thb if row else None
        grades.append(classify_grade(
            evidence, match, existing_list_price_thb=existing,
            generation_id=generation_id))

    topology_required, topology_note = _topology_review(
        lineup_status, grades, siblings)
    return ModelManifestEntry(
        model_id=model.id,
        lineup_status=lineup_status,
        evidence_tier=evidence_tier,
        lineup_source=source,
        grades=grades,
        topology_review_required=topology_required,
        topology_note=topology_note,
    )


def run_discover(*, data_dir: Path = DATA_DIR, year: int = DEFAULT_YEAR,
                 out_path: Path, limit: Optional[int] = None,
                 transport: Optional[Transport] = None) -> Manifest:
    catalog = Catalog.load(data_dir, year)
    ledger = PriceLedger.load(data_dir, year=year, catalog=catalog)
    registry = load_source_target_registry(data_dir, year)
    transport = transport or UrllibTransport()
    as_of = date.today()
    scope_index = retail_scope_index(
        catalog, data_dir=data_dir, year=year, as_of=as_of)
    trim_reviews = trim_review_index(data_dir=data_dir, year=year)
    siblings_by_model = siblings_from_scope(catalog, scope_index, trim_reviews)

    model_ids = sorted(catalog.models)
    if limit:
        model_ids = model_ids[:limit]
    manifest = Manifest(generated_at=datetime.now(timezone.utc).date().isoformat())
    for model_id in model_ids:
        model = catalog.models[model_id]
        scope = scope_index[model_id]
        if not scope.in_scope:
            manifest.models.append(ModelManifestEntry(
                model_id=model_id,
                lineup_status=LineupStatus.UNKNOWN,
                evidence_tier=EvidenceTier.NONE,
                lineup_source={},
                grades=[],
                blocked_reason=scope.blocked_reason,
            ))
            continue
        manifest.models.append(discover_model(
            model, catalog, ledger, registry, scope=scope,
            siblings_by_model=siblings_by_model, transport=transport))
    manifest.save(out_path)
    return manifest


# --------------------------------------------------------------- apply


def _append_price_commands(manifest_dict: dict[str, Any]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    for model in manifest_dict.get("models", []):
        for grade in model.get("grades", []):
            if grade.get("terminal_state") != TerminalState.AUTO_READY.value or grade.get("applied"):
                continue
            trim_id = grade.get("trim_id")
            if not trim_id:
                continue
            payload = {
                "trim_id": trim_id,
                "amount_thb": grade["amount_thb"],
                "price_type": PriceType.LIST_PRICE.value,
                "observed_at": grade.get("observed_at") or date.today().isoformat(),
                "source": grade.get("evidence_tier") or model.get("evidence_tier", ""),
            }
            if grade.get("source_ref"):
                payload["source_ref"] = grade["source_ref"]
            commands.append({
                "operation": "APPEND_PRICE",
                "canonical_id": trim_id,
                "payload": payload,
            })
    return commands


def _batch(commands: list[dict[str, Any]], *, year: int) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "batch_id": batch_id_for(commands, prefix="price-coverage-backfill"),
        "year": year,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "source": {"kind": "PRICE_HARVEST", "ref": "tools/price_coverage_backfill.py"},
        "actor": "price-coverage-backfill",
        "reason": "current retail price coverage backfill",
        "commands": commands,
    }


def build_append_price_batch(manifest_dict: dict[str, Any], *, year: int) -> Optional[dict[str, Any]]:
    """Compatibility helper returning one batch; run_apply uses bounded chunks."""
    commands = _append_price_commands(manifest_dict)
    return _batch(commands, year=year) if commands else None


def build_append_price_batches(manifest_dict: dict[str, Any], *, year: int,
                               chunk_size: int = _APPLY_CHUNK_SIZE) -> list[dict[str, Any]]:
    if chunk_size <= 0 or chunk_size > 500:
        raise ValueError("chunk_size must be between 1 and 500")
    commands = _append_price_commands(manifest_dict)
    return [
        _batch(commands[index:index + chunk_size], year=year)
        for index in range(0, len(commands), chunk_size)
    ]


def _local_revalidate_auto_ready_row(catalog: Catalog, ledger: PriceLedger, *,
                                     scope_index: dict[str, ModelScope],
                                     siblings_by_model: dict[str, list],
                                     trim_reviews: dict[str, dict],
                                     model_id: str,
                                     grade: dict[str, Any]) -> tuple[bool, str, str]:
    scope = scope_index.get(model_id)
    if scope is None or not scope.in_scope:
        reason = scope.blocked_reason if scope else "model not found in current catalog"
        return False, TerminalState.IDENTITY_BLOCKED.value, \
            f"model no longer in price scope ({reason})"
    trim_id = str(grade.get("trim_id") or "")
    if not trim_id:
        return False, TerminalState.IDENTITY_BLOCKED.value, "no trim_id recorded at discovery time"
    eligible, reason = trim_price_eligibility(
        catalog, trim_id, scope_index=scope_index, trim_reviews=trim_reviews)
    if not eligible:
        return False, TerminalState.IDENTITY_BLOCKED.value, \
            f"trim no longer price-eligible ({reason})"
    trim = catalog.trims.get(trim_id)
    if grade.get("generation_id") and trim and grade["generation_id"] != trim.generation_id:
        return False, TerminalState.IDENTITY_BLOCKED.value, \
            "canonical trim generation changed since discovery"
    model = catalog.models.get(model_id)
    claim = PriceClaim(
        claim_id=f"apply-revalidate-{trim_id}",
        document_id="sha256:" + "0" * 64,
        source_id="",
        brand_raw=model.brand_id if model else "",
        model_raw=model.name_en if model else "",
        trim_raw=str(grade.get("raw_grade") or ""),
        amount_thb=int(grade.get("amount_thb") or 0),
        price_type=PriceType.parse(grade.get("extracted_price_type") or "UNKNOWN"),
    )
    match = match_trim_diagnostic(catalog, claim, siblings_by_model=siblings_by_model)
    if (match.state is not TrimMatchState.EXACT
            or match.method not in _AUTO_READY_METHODS
            or match.trim_id != trim_id):
        return False, TerminalState.IDENTITY_BLOCKED.value, \
            "identity no longer resolves the same way"
    row = ledger.current_list_price(trim_id)
    existing = row.amount_thb if row else None
    amount = grade.get("amount_thb")
    if existing is not None and existing == amount:
        return False, TerminalState.COMPLETE.value, \
            "current LIST_PRICE already matches; nothing to write"
    if existing is not None:
        return False, TerminalState.PRICE_CONFLICT.value, \
            f"current LIST_PRICE is now {existing} THB; never auto-corrected"
    if PriceType.parse(grade.get("extracted_price_type") or "UNKNOWN") is not PriceType.LIST_PRICE:
        return False, TerminalState.SEMANTIC_BLOCKED.value, \
            "manifest row is no longer a clean LIST_PRICE claim"
    return True, "", ""


def _fresh_model_evidence(model_id: str, *, catalog: Catalog, ledger: PriceLedger,
                          registry, scope_index: dict[str, ModelScope],
                          siblings_by_model: dict[str, list], transport: Transport
                          ) -> Optional[ModelManifestEntry]:
    model = catalog.models.get(model_id)
    scope = scope_index.get(model_id)
    if model is None or scope is None or not scope.in_scope:
        return None
    return discover_model(
        model, catalog, ledger, registry, scope=scope,
        siblings_by_model=siblings_by_model, transport=transport)


def revalidate_manifest_for_apply(manifest_dict: dict[str, Any], *,
                                  data_dir: Path = DATA_DIR, year: int = DEFAULT_YEAR,
                                  transport: Optional[Transport] = None,
                                  require_fresh_evidence: bool = False) -> int:
    """Revalidate identity/ledger, and optionally current external evidence.

    ``run_apply`` always sets ``require_fresh_evidence=True``.  The optional
    local-only mode exists for unit-level validation helpers and never powers the
    production CLI.
    """
    catalog = Catalog.load(data_dir, year)
    ledger = PriceLedger.load(data_dir, year=year, catalog=catalog)
    as_of = date.today()
    scope_index = retail_scope_index(
        catalog, data_dir=data_dir, year=year, as_of=as_of)
    trim_reviews = trim_review_index(data_dir=data_dir, year=year)
    siblings_by_model = siblings_from_scope(catalog, scope_index, trim_reviews)
    registry = load_source_target_registry(data_dir, year) if require_fresh_evidence else None
    if require_fresh_evidence:
        transport = transport or UrllibTransport()

    downgraded = 0
    fresh_cache: dict[str, Optional[ModelManifestEntry]] = {}
    for model_payload in manifest_dict.get("models", []):
        model_id = str(model_payload.get("model_id") or "")
        candidates = [
            grade for grade in model_payload.get("grades", [])
            if grade.get("terminal_state") == TerminalState.AUTO_READY.value
            and not grade.get("applied")
        ]
        if not candidates:
            continue
        if require_fresh_evidence:
            fresh_cache[model_id] = _fresh_model_evidence(
                model_id, catalog=catalog, ledger=ledger, registry=registry,
                scope_index=scope_index, siblings_by_model=siblings_by_model,
                transport=transport)
        fresh = fresh_cache.get(model_id)
        fresh_by_trim: dict[str, GradeClassification] = {}
        if fresh is not None:
            fresh_by_trim = {
                grade.trim_id: grade for grade in fresh.grades if grade.trim_id
            }

        for grade in candidates:
            ok, blocked_state, note = _local_revalidate_auto_ready_row(
                catalog, ledger, scope_index=scope_index,
                siblings_by_model=siblings_by_model, trim_reviews=trim_reviews,
                model_id=model_id, grade=grade)
            if not ok:
                grade["terminal_state"] = blocked_state
                grade["note"] = note
                downgraded += 1
                continue
            if not require_fresh_evidence:
                continue
            current = fresh_by_trim.get(str(grade.get("trim_id") or ""))
            if current is None:
                grade["terminal_state"] = TerminalState.NO_SOURCE.value
                grade["note"] = "current evidence no longer proves this price fact; re-run discovery"
                downgraded += 1
                continue
            if current.terminal_state is TerminalState.COMPLETE:
                grade["terminal_state"] = TerminalState.COMPLETE.value
                grade["note"] = "fresh evidence still agrees and price is already present"
                downgraded += 1
                continue
            if current.terminal_state is not TerminalState.AUTO_READY:
                grade["terminal_state"] = current.terminal_state.value
                grade["note"] = "fresh evidence no longer qualifies for automatic write"
                downgraded += 1
                continue
            if current.evidence.amount_thb != grade.get("amount_thb"):
                grade["terminal_state"] = TerminalState.PRICE_CONFLICT.value
                grade["note"] = (
                    f"source changed before apply: manifest={grade.get('amount_thb')} THB, "
                    f"fresh={current.evidence.amount_thb} THB; re-run discovery")
                downgraded += 1
                continue
            if current.evidence.extracted_price_type is not PriceType.LIST_PRICE:
                grade["terminal_state"] = TerminalState.SEMANTIC_BLOCKED.value
                grade["note"] = "fresh evidence is no longer a normal LIST_PRICE"
                downgraded += 1
    return downgraded


def _mark_applied(manifest_dict: dict[str, Any], batch: dict[str, Any]) -> None:
    ids = {command["canonical_id"] for command in batch["commands"]}
    for model in manifest_dict.get("models", []):
        for grade in model.get("grades", []):
            if (grade.get("trim_id") in ids
                    and grade.get("terminal_state") == TerminalState.AUTO_READY.value
                    and not grade.get("applied")):
                grade["applied"] = True
                grade["applied_command_id"] = batch["batch_id"]


def _write_manifest_dict(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def run_apply(*, data_dir: Path = DATA_DIR, year: int = DEFAULT_YEAR,
             manifest_path: Path, transport: Optional[Transport] = None):
    manifest_dict = load_manifest_dict(manifest_path)
    downgraded = revalidate_manifest_for_apply(
        manifest_dict, data_dir=data_dir, year=year,
        transport=transport, require_fresh_evidence=True)
    batches = build_append_price_batches(manifest_dict, year=year)
    if not batches:
        _write_manifest_dict(manifest_path, manifest_dict)
        return {
            "applied": False,
            "reason": "no unapplied AUTO_READY rows survived fresh apply-time revalidation"
                     if downgraded else "no unapplied AUTO_READY rows in manifest",
            "revalidation_blocked": downgraded,
            "commands": 0,
            "batch_ids": [],
        }

    pipeline = CanonicalInputPipeline(data_dir)
    changed_files: list[str] = []
    batch_ids: list[str] = []
    idempotent = True
    command_count = 0
    for batch in batches:
        result = pipeline.apply(batch)
        batch_ids.append(batch["batch_id"])
        command_count += len(batch["commands"])
        idempotent = idempotent and result.idempotent_replay
        changed_files.extend(result.changed_files)
        _mark_applied(manifest_dict, batch)
        # Checkpoint after every independently valid bounded batch so a later
        # failure can resume without replaying already-applied rows.
        _write_manifest_dict(manifest_path, manifest_dict)

    return {
        "applied": True,
        "batch_id": batch_ids[0] if len(batch_ids) == 1 else None,
        "batch_ids": batch_ids,
        "commands": command_count,
        "idempotent_replay": idempotent,
        "changed_files": sorted(set(changed_files)),
        "revalidation_blocked": downgraded,
    }


# ----------------------------------------------------------------- CLI


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument(
        "--out", type=Path,
        default=Path("vehreg/data") / str(DEFAULT_YEAR) / "market" / "prices"
        / "research" / f"price_coverage_backfill_{date.today().isoformat()}.json")
    parser.add_argument("--limit", type=int, help="only the first N models, sorted by id")
    parser.add_argument("--apply", type=Path, help="apply AUTO_READY rows from this manifest")
    args = parser.parse_args(argv)

    if args.apply:
        result = run_apply(
            data_dir=args.data_dir, year=args.year, manifest_path=args.apply)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    manifest = run_discover(
        data_dir=args.data_dir, year=args.year, out_path=args.out, limit=args.limit)
    print(json.dumps({"out": str(args.out), "summary": manifest.summary()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
