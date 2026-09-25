#!/usr/bin/env python3
"""One-time Current Retail Price Coverage Backfill.

Discovers today's Thai retail lineup per canonical Model, matches each
discovered grade to a canonical MarketTrim identity, and classifies the
result deterministically as ``AUTO_READY`` (safe to write automatically)
or one of several fail-closed exception states. ``AUTO_READY`` rows are
written through the existing ``APPEND_PRICE`` canonical command path
(:mod:`vehreg.canonical_write`, via :class:`vehreg.input_pipeline.
CanonicalInputPipeline`) -- the same path a Save in the admin, or the
scheduled price feed, already uses. Nothing here builds a second writer,
a new review platform, or continuous-monitoring machinery: this is a
one-time baseline fill, not a replacement for the scheduled price feed
(``tools/pricefeed_write.py``), which remains responsible for ongoing
price drift and campaign data.

Two modes:

* ``--discover`` (default): read-only. Walks the canonical catalog,
  attempts OEM-then-media evidence discovery per model, classifies every
  grade, and writes a manifest. Safe to re-run any number of times.
* ``--apply <manifest>``: reads a manifest produced by ``--discover``,
  builds one canonical input batch from every still-unapplied
  ``AUTO_READY`` row, and submits it through
  ``CanonicalInputPipeline.apply()``. Every other terminal state is left
  exactly as the manifest recorded it -- this tool never guesses past a
  fail-closed classification.

Decision rules implemented here (classify_grade / model lineup status)
are the exact tables from the approved architecture: AUTO_READY requires
an EXACT_NAME or EXACT_ALIAS match, a clean LIST_PRICE reading, a strong
evidence tier (usable OEM current-model evidence, or two independent
media sources agreeing on grade and amount), and no existing current
canonical LIST_PRICE for that trim. Anything else fails closed into
IDENTITY_BLOCKED / SEMANTIC_BLOCKED / CAMPAIGN_ONLY / PRICE_CONFLICT /
NO_SOURCE. No score, no fuzzy threshold, no automatic correction of an
existing differing LIST_PRICE.
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
from typing import Any, Iterable, Optional
import urllib.parse

from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR, Model
from vehreg.input_pipeline import CanonicalInputPipeline
from vehreg.price_extract import ExtractionError, extract_oem_price_claims
from vehreg.price_fetch import FetchError, Transport, UrllibTransport, adapter_for
from vehreg.price_match import TrimMatchMethod, TrimMatchResult, TrimMatchState, match_trim_diagnostic
from vehreg.price_sources import SourceKind, TargetRole, load_source_target_registry
from vehreg.pricefeed import PriceClaim, grade_tokens
from vehreg.pricefeed_writer import batch_id_for
from vehreg.pricing import PriceLedger, PriceType
from vehreg.retail_scope import (
    ModelScope, retail_scope_index, siblings_from_scope, trim_price_eligibility,
    trim_review_index,
)


# --------------------------------------------------------------------- enums

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


#: The only two match methods conservative enough for an automatic write.
#: PARTIAL_GRADE resolving to exactly one candidate is still inference, not
#: identity -- see the architecture report. Deliberately not importing this
#: from anywhere else: it is this tool's one opinion about matching.
_AUTO_READY_METHODS = frozenset({TrimMatchMethod.EXACT_NAME, TrimMatchMethod.EXACT_ALIAS})

#: Price types that read as promotional/non-list evidence rather than a
#: semantics failure -- these produce CAMPAIGN_ONLY, not SEMANTIC_BLOCKED.
_NON_LIST_PRICE_TYPES = frozenset({
    PriceType.CAMPAIGN_PRICE, PriceType.FINANCE_PRICE, PriceType.ESTIMATED_PRICE,
    PriceType.DEALER_PRICE, PriceType.ECO_STICKER_PRICE, PriceType.INTRODUCTORY_PRICE,
})


# ---------------------------------------------------------------- evidence

@dataclass(frozen=True, slots=True)
class GradeEvidence:
    """One raw grade string plus one discovered amount, before matching.

    ``semantics_clear=False`` forces SEMANTIC_BLOCKED regardless of
    ``extracted_price_type`` -- it means the discovery step itself could not
    confidently tell what kind of price this is, which is a different
    failure than "it is clearly a campaign price" (CAMPAIGN_ONLY).
    """

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
    #: The current generation this grade was resolved against at discovery
    #: time. Apply-time revalidation compares this to a freshly resolved
    #: current generation and blocks the write if they differ -- a
    #: generation changeover between --discover and --apply is exactly the
    #: kind of identity drift that must never auto-repair (see
    #: vehreg.retail_scope).
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
    """The exact terminal-state decision table from the architecture report.

    Evaluated in a fixed order; the first matching rule wins. Nothing here
    is a score or a threshold -- every branch is a boolean check against
    already-existing, already-reviewed primitives (TrimMatchState/Method,
    PriceType, PriceLedger.current_list_price). ``match`` is expected to
    have been resolved against an already lifecycle-scoped siblings map
    (see vehreg.retail_scope), so a trim outside the current generation or
    explicitly retired by a HUMAN reviewer never appears as a candidate in
    the first place -- there is no separate generation/lifecycle branch
    here because the matcher itself cannot see those trims.
    """
    if evidence.evidence_tier is EvidenceTier.NONE:
        return GradeClassification(
            evidence=evidence, match=match, terminal_state=TerminalState.NO_SOURCE,
            existing_list_price_thb=None, generation_id=generation_id,
            note="no qualifying evidence tier reached this grade")

    if not evidence.semantics_clear or evidence.extracted_price_type is None \
            or evidence.extracted_price_type is PriceType.UNKNOWN:
        return GradeClassification(
            evidence=evidence, match=match, terminal_state=TerminalState.SEMANTIC_BLOCKED,
            existing_list_price_thb=None, generation_id=generation_id,
            note="price type or lineup semantics could not be safely established")

    if evidence.extracted_price_type in _NON_LIST_PRICE_TYPES:
        return GradeClassification(
            evidence=evidence, match=match, terminal_state=TerminalState.CAMPAIGN_ONLY,
            existing_list_price_thb=None, generation_id=generation_id,
            note=(f"{evidence.extracted_price_type.value} evidence only; "
                  "no accompanying normal LIST_PRICE found for this grade"))

    # From here the reading is a clean LIST_PRICE claim.
    if match is None or match.state is not TrimMatchState.EXACT:
        state = match.state.value if match else "NONE"
        return GradeClassification(
            evidence=evidence, match=match, terminal_state=TerminalState.IDENTITY_BLOCKED,
            existing_list_price_thb=None, generation_id=generation_id,
            note=f"match state {state}; identity is not safe to auto-write")

    if match.method not in _AUTO_READY_METHODS:
        return GradeClassification(
            evidence=evidence, match=match, terminal_state=TerminalState.IDENTITY_BLOCKED,
            existing_list_price_thb=None, generation_id=generation_id,
            note=(f"match method {match.method.value} resolves to one trim but is "
                  "inference, not exact identity -- never auto-written"))

    if existing_list_price_thb is not None:
        if existing_list_price_thb == evidence.amount_thb:
            return GradeClassification(
                evidence=evidence, match=match, terminal_state=TerminalState.COMPLETE,
                existing_list_price_thb=existing_list_price_thb, generation_id=generation_id,
                note="discovered amount matches the existing current LIST_PRICE")
        return GradeClassification(
            evidence=evidence, match=match, terminal_state=TerminalState.PRICE_CONFLICT,
            existing_list_price_thb=existing_list_price_thb, generation_id=generation_id,
            note=(f"discovered {evidence.amount_thb} THB differs from existing current "
                  f"LIST_PRICE {existing_list_price_thb} THB; never auto-corrected"))

    if evidence.evidence_tier not in (EvidenceTier.OEM_CURRENT_MODEL_PAGE, EvidenceTier.MEDIA_TWO_AGREE):
        return GradeClassification(
            evidence=evidence, match=match, terminal_state=TerminalState.NO_SOURCE,
            existing_list_price_thb=None, generation_id=generation_id,
            note=f"evidence tier {evidence.evidence_tier.value} is not strong enough to auto-write")

    return GradeClassification(
        evidence=evidence, match=match, terminal_state=TerminalState.AUTO_READY,
        existing_list_price_thb=None, generation_id=generation_id, note="")


# ------------------------------------------------------------------- model

@dataclass
class ModelManifestEntry:
    model_id: str
    lineup_status: LineupStatus
    evidence_tier: EvidenceTier
    lineup_source: dict[str, Any]
    grades: list[GradeClassification] = field(default_factory=list)
    #: Set when discovery was never attempted for this model -- it was
    #: under maintenance, canonically HISTORICAL, or its current generation
    #: could not be resolved with confidence (vehreg.retail_scope). No
    #: network call is made and no grade is produced for a blocked model;
    #: the whole point is that the price system never repairs or guesses
    #: its way past an identity problem, it just leaves the model alone.
    blocked_reason: str = ""

    @property
    def current_retail_model_complete(self) -> bool:
        """Section 5 of the architecture report, verbatim.

        The 1,502-trim canonical catalog is never the denominator here --
        only the grades this model's own discovered lineup names."""
        if self.lineup_status is not LineupStatus.EXHAUSTIVE:
            return False
        if not self.grades:
            return False
        for grade in self.grades:
            if grade.match is None or grade.match.method not in _AUTO_READY_METHODS:
                return False
            has_current_price = (
                grade.terminal_state is TerminalState.COMPLETE
                or (grade.terminal_state is TerminalState.AUTO_READY and grade.applied)
            )
            if not has_current_price:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "lineup_status": self.lineup_status.value,
            "evidence_tier": self.evidence_tier.value,
            "lineup_source": self.lineup_source,
            "blocked_reason": self.blocked_reason,
            "current_retail_model_complete": self.current_retail_model_complete,
            "grades": [grade.to_dict() for grade in self.grades],
        }


# ---------------------------------------------------------------- manifest

@dataclass
class Manifest:
    generated_at: str
    models: list[ModelManifestEntry] = field(default_factory=list)
    schema_version: int = 1

    def summary(self) -> dict[str, Any]:
        counts = {state.value: 0 for state in TerminalState}
        lineup_counts = {status.value: 0 for status in LineupStatus}
        complete = 0
        for model in self.models:
            lineup_counts[model.lineup_status.value] += 1
            if model.current_retail_model_complete:
                complete += 1
            for grade in model.grades:
                counts[grade.terminal_state.value] += 1
        return {**counts, "lineup_status": lineup_counts,
                "current_retail_model_complete": complete, "total_models": len(self.models)}

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
        tmp.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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

_OFFICIAL_PRICE_TITLE = re.compile(r"ราคาอย่างเป็นทางการ|official price|เปิดราคา", re.IGNORECASE)
_BAD_TITLE = re.compile(
    r"คาดการณ์|คาดราคา|ลุ้นราคา|มือสอง|used|display|demo|ส่วนลด|ราคาพิเศษ", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_AMOUNT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[,.]\d{3}){1,2}|\d{6,8})(?!\d)")


def _clean_text(raw: str) -> str:
    return _SPACE_RE.sub(" ", _TAG_RE.sub(" ", raw or "")).strip()


def _title_amounts(title: str) -> list[int]:
    if not re.search(r"ราคา|บาท|price", title, re.IGNORECASE):
        return []
    found: set[int] = set()
    for match in _AMOUNT_RE.finditer(title):
        value = int(match.group(1).replace(",", "").replace(".", ""))
        if 250_000 <= value <= 50_000_000:
            found.add(value)
    return sorted(found)


@dataclass(frozen=True, slots=True)
class MediaHit:
    title: str
    url: str
    amounts: tuple[int, ...]
    official_title: bool
    excluded_title: bool


def _search_media_source(source_id: str, base_url: str, brand: str, model: str, *,
                         transport: Transport) -> list[MediaHit]:
    """One WordPress REST search against one media outlet.

    Independent re-implementation of the discovery idea PR #81 proved out
    (title-regex official-price detection, BAD_TITLE exclusion) -- not an
    import of it. PR #81 remains draft/unmerged and this tool must not
    depend on its files being present; every hit here is fresh evidence,
    revalidated against current `main` at classification time, not a
    replay of that PR's stored dispositions.
    """
    query = f"{brand} {model} ราคาอย่างเป็นทางการ"
    url = f"{base_url}/wp-json/wp/v2/search?search={urllib.parse.quote(query)}&per_page=10"
    try:
        response = transport.fetch(url, headers={"User-Agent": "TDR-price-backfill/1.0"}, timeout=25.0)
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
        amounts = _title_amounts(title)
        results.append(MediaHit(
            title=title, url=str(hit.get("url") or ""), amounts=tuple(amounts),
            official_title=bool(_OFFICIAL_PRICE_TITLE.search(title)),
            excluded_title=bool(_BAD_TITLE.search(title)),
        ))
    return results


def _preferred_amount_for_grade(hits: list[MediaHit], wanted: frozenset[str],
                                model_name: str) -> tuple[Optional[int], str]:
    """The one hit, if any, that both names this exact grade and reads as
    an unambiguous official single-amount price claim.

    ``wanted`` is never free-extracted text: it is always one of this
    model's own current, scoped MarketTrim names/aliases (see
    ``discover_media_grades``), the same token space
    ``match_trim_diagnostic`` resolves against, so a hit can only be
    credited to a grade the catalog already knows exists.
    """
    for hit in hits:
        if not hit.official_title or hit.excluded_title or len(hit.amounts) != 1:
            continue
        if wanted <= grade_tokens(hit.title, model_name):
            return hit.amounts[0], hit.url
    return None, ""


def discover_media_grades(model: Model, siblings: list, *,
                          transport: Transport) -> list[GradeEvidence]:
    """Tier-2 fallback, one grade at a time.

    Media evidence never invents a grade from the model name. For each of
    this model's own current, lifecycle-scoped MarketTrims, both preferred
    media sources must independently name *that exact trim* (by its
    canonical name or alias, matched the same way match_trim_diagnostic
    matches) and agree on one amount before MEDIA_TWO_AGREE evidence is
    produced for it. A single-source hit, or two sources that only agree
    on an amount without both naming the same grade, is never enough --
    see classify_grade's NO_SOURCE handling for weak-tier evidence.
    """
    if not siblings:
        return []
    hits_by_source: dict[str, list[MediaHit]] = {
        source_id: _search_media_source(source_id, base_url, model.brand_id, model.name_en,
                                        transport=transport)
        for source_id, base_url in _MEDIA_SOURCES
    }

    evidence: list[GradeEvidence] = []
    for trim in siblings:
        wanted = grade_tokens(trim.name, model.name_en)
        if not wanted:
            continue
        per_source = {
            source_id: _preferred_amount_for_grade(hits, wanted, model.name_en)
            for source_id, hits in hits_by_source.items()
        }
        amounts = [amount for amount, _ in per_source.values() if amount is not None]
        if len(amounts) < 2 or len(set(amounts)) != 1:
            continue  # disagreement, or fewer than two sources named this grade
        amount = amounts[0]
        url = next(url for amount_found, url in per_source.values() if amount_found == amount)
        evidence.append(GradeEvidence(
            raw_grade=trim.name, amount_thb=amount, extracted_price_type=PriceType.LIST_PRICE,
            evidence_tier=EvidenceTier.MEDIA_TWO_AGREE, source_ref=url,
            observed_at=date.today().isoformat(), semantics_clear=True,
        ))
    return evidence


# ----------------------------------------------------------- OEM discovery

def discover_oem_grades(model: Model, registry, *, transport: Transport) -> Optional[
        tuple[LineupStatus, dict[str, Any], list[GradeEvidence]]]:
    """Try every registered target for this model, in registry order.

    Deliberately role-agnostic: extract_oem_price_claims already refuses to
    produce claims for a role/source it does not have deterministic parsing
    for (today: only official_jaecoo_th's PRICE_LIST/BLOG/PROMOTION pages).
    Duplicating that role knowledge here would be a second, driftable copy
    of it; instead this simply tries and accepts an empty result as "no
    usable OEM evidence", which is exactly the fall-through-to-media signal
    the architecture calls for. Returns None when nothing usable was found.
    """
    targets = [target for target in registry.targets.values() if target.model_hint == model.id]
    for target in targets:
        profile = registry.profiles.get(target.source_id)
        if profile is None or profile.kind is not SourceKind.OEM:
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
        list_claims = [c for c in extraction.claims if c.price_type is PriceType.LIST_PRICE]
        if not extraction.claims:
            continue
        observed = date.today().isoformat()
        grades = [
            GradeEvidence(
                raw_grade=claim.trim_raw, amount_thb=claim.amount_thb,
                extracted_price_type=claim.price_type,
                evidence_tier=EvidenceTier.OEM_CURRENT_MODEL_PAGE,
                source_ref=target.url, observed_at=observed,
                semantics_clear=claim.price_type is not PriceType.UNKNOWN,
            )
            for claim in extraction.claims
        ]
        # EXHAUSTIVE requires a concrete source/parser signal that this
        # target represents the complete current retail lineup -- counting
        # distinct grades in one fetch is not that signal (a buyer-guide
        # article covering two of five grades would satisfy it just as
        # well as an actual full price table). The registry's own
        # TargetRole is that signal instead: PRICE_LIST is an explicit
        # operator assertion, made when the target was registered, that
        # this URL is the official price list for the model. BLOG
        # (buyer-guide) and PROMOTION (campaign detail) pages never carry
        # that assertion, however many grades they happen to mention, so
        # they can only ever produce PARTIAL lineup evidence.
        lineup_status = (LineupStatus.EXHAUSTIVE
                         if target.role is TargetRole.PRICE_LIST and list_claims
                         else LineupStatus.PARTIAL)
        source = {"role": target.role.value, "source_id": target.source_id,
                  "url": target.url, "fetched_at": observed}
        return lineup_status, source, grades
    return None


# --------------------------------------------------------- orchestration

def discover_model(model: Model, catalog: Catalog, ledger: PriceLedger, registry, *,
                   scope: ModelScope, siblings_by_model: dict[str, list],
                   transport: Transport) -> ModelManifestEntry:
    """Discover and classify one model's current lineup.

    Only called for a model ``scope.in_scope`` already cleared -- current
    generation resolved, not under maintenance, not canonically HISTORICAL.
    ``siblings_by_model`` is the lifecycle-scoped map from
    vehreg.retail_scope: every match below can only ever resolve to a trim
    of this model's current generation that no HUMAN reviewer has retired,
    so AUTO_READY is structurally impossible for anything else -- there is
    no separate generation check to remember to add here.
    """
    generation_id = scope.current_generation.id if scope.current_generation else None
    oem_result = discover_oem_grades(model, registry, transport=transport)
    if oem_result is not None:
        lineup_status, source, grade_evidence_list = oem_result
        evidence_tier = EvidenceTier.OEM_CURRENT_MODEL_PAGE
    else:
        siblings = siblings_by_model.get(model.id, [])
        media_grades = discover_media_grades(model, siblings, transport=transport)
        if media_grades:
            lineup_status = LineupStatus.PARTIAL
            evidence_tier = EvidenceTier.MEDIA_TWO_AGREE
            source = {"role": "MEDIA_SEARCH", "source_id": "autolifethailand+headlightmag",
                      "url": media_grades[0].source_ref, "fetched_at": media_grades[0].observed_at}
            grade_evidence_list = media_grades
        else:
            lineup_status = LineupStatus.UNKNOWN
            evidence_tier = EvidenceTier.NONE
            source = {}
            grade_evidence_list = [GradeEvidence(
                raw_grade=model.name_en, amount_thb=None, extracted_price_type=None,
                evidence_tier=EvidenceTier.NONE, source_ref="",
                observed_at=date.today().isoformat(), semantics_clear=True,
            )]

    grades: list[GradeClassification] = []
    for evidence in grade_evidence_list:
        match = None
        if evidence.evidence_tier is not EvidenceTier.NONE:
            claim = PriceClaim(
                claim_id=f"backfill-{model.id}-{evidence.raw_grade}",
                document_id="sha256:" + "0" * 64,
                source_id=source.get("source_id", ""),
                brand_raw=model.brand_id, model_raw=model.name_en, trim_raw=evidence.raw_grade,
                amount_thb=evidence.amount_thb or 0,
                price_type=evidence.extracted_price_type or PriceType.UNKNOWN,
            )
            match = match_trim_diagnostic(catalog, claim, siblings_by_model=siblings_by_model)
        existing = None
        if match is not None and match.trim_id is not None:
            row = ledger.current_list_price(match.trim_id)
            existing = row.amount_thb if row else None
        grades.append(classify_grade(evidence, match, existing_list_price_thb=existing,
                                     generation_id=generation_id))

    return ModelManifestEntry(
        model_id=model.id, lineup_status=lineup_status, evidence_tier=evidence_tier,
        lineup_source=source, grades=grades,
    )


def run_discover(*, data_dir: Path = DATA_DIR, year: int = DEFAULT_YEAR,
                 out_path: Path, limit: Optional[int] = None,
                 transport: Optional[Transport] = None) -> Manifest:
    catalog = Catalog.load(data_dir, year)
    ledger = PriceLedger.load(data_dir, year=year, catalog=catalog)
    registry = load_source_target_registry(data_dir, year)
    transport = transport or UrllibTransport()

    # Computed once for the whole run: which models are safe to touch at
    # all (current generation resolved, not under maintenance/HISTORICAL),
    # and the lifecycle-scoped siblings every match below resolves
    # against. A model that fails this gate is never fetched or matched --
    # the price system does not try to repair or guess past an identity
    # problem, it leaves the model alone and records why.
    scope_index = retail_scope_index(catalog, data_dir=data_dir, year=year)
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
                model_id=model_id, lineup_status=LineupStatus.UNKNOWN,
                evidence_tier=EvidenceTier.NONE, lineup_source={}, grades=[],
                blocked_reason=scope.blocked_reason,
            ))
            continue
        manifest.models.append(discover_model(
            model, catalog, ledger, registry, scope=scope,
            siblings_by_model=siblings_by_model, transport=transport))

    manifest.save(out_path)
    return manifest


# --------------------------------------------------------------- apply

def build_append_price_batch(manifest_dict: dict[str, Any], *, year: int) -> Optional[dict[str, Any]]:
    """AUTO_READY rows, still unapplied, as APPEND_PRICE commands -- the
    exact command shape vehreg.pricefeed_writer.batch_from_outcomes already
    builds for the scheduled price feed. No new writer."""
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
                "source": model.get("evidence_tier", ""),
            }
            if grade.get("source_ref"):
                payload["source_ref"] = grade["source_ref"]
            commands.append({"operation": "APPEND_PRICE", "canonical_id": trim_id, "payload": payload})
    if not commands:
        return None
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


def _revalidate_auto_ready_row(catalog: Catalog, ledger: PriceLedger, *,
                               scope_index: dict[str, ModelScope],
                               siblings_by_model: dict[str, list],
                               trim_reviews: dict[str, dict],
                               model_id: str, grade: dict[str, Any]) -> tuple[bool, str, str]:
    """Re-run the AUTO_READY gate fresh, right now, for one manifest row.

    A --discover manifest can be arbitrarily old by the time --apply runs
    against it. This does not trust any of its stored dispositions as
    still true -- it rebuilds the match and re-checks scope/price/
    semantics against the current catalog, ledger and lifecycle sidecars,
    exactly as run_discover would if it saw this evidence today. Returns
    ``(still_ok, blocked_terminal_state, note)``; the first is empty when
    ``still_ok`` is True.
    """
    scope = scope_index.get(model_id)
    if scope is None or not scope.in_scope:
        reason = scope.blocked_reason if scope else "model not found in current catalog"
        return False, TerminalState.IDENTITY_BLOCKED.value, \
            f"model no longer in scope at apply time ({reason})"

    generation_id = scope.current_generation.id if scope.current_generation else None
    if grade.get("generation_id") and grade["generation_id"] != generation_id:
        return False, TerminalState.IDENTITY_BLOCKED.value, \
            "current generation changed since --discover; re-run discovery for this model"

    trim_id = grade.get("trim_id")
    if not trim_id:
        return False, TerminalState.IDENTITY_BLOCKED.value, "no trim_id recorded at discovery time"

    eligible, reason = trim_price_eligibility(
        catalog, trim_id, scope_index=scope_index, trim_reviews=trim_reviews)
    if not eligible:
        return False, TerminalState.IDENTITY_BLOCKED.value, \
            f"trim no longer price-eligible at apply time ({reason})"

    model = catalog.models.get(model_id)
    claim = PriceClaim(
        claim_id=f"apply-revalidate-{trim_id}", document_id="sha256:" + "0" * 64,
        source_id="", brand_raw=model.brand_id if model else "",
        model_raw=model.name_en if model else "", trim_raw=str(grade.get("raw_grade") or ""),
        amount_thb=int(grade.get("amount_thb") or 0),
        price_type=PriceType.parse(grade.get("extracted_price_type") or "UNKNOWN"),
    )
    match = match_trim_diagnostic(catalog, claim, siblings_by_model=siblings_by_model)
    if (match.state is not TrimMatchState.EXACT or match.method not in _AUTO_READY_METHODS
            or match.trim_id != trim_id):
        return False, TerminalState.IDENTITY_BLOCKED.value, \
            "identity no longer resolves the same way at apply time"

    row = ledger.current_list_price(trim_id)
    existing = row.amount_thb if row else None
    amount_thb = grade.get("amount_thb")
    if existing is not None and existing == amount_thb:
        return False, TerminalState.COMPLETE.value, \
            "current LIST_PRICE already matches at apply time; nothing to write"
    if existing is not None and existing != amount_thb:
        return False, TerminalState.PRICE_CONFLICT.value, \
            (f"current LIST_PRICE changed to {existing} THB since discovery; "
             "never auto-corrected")

    price_type = PriceType.parse(grade.get("extracted_price_type") or "UNKNOWN")
    if price_type is not PriceType.LIST_PRICE:
        return False, TerminalState.SEMANTIC_BLOCKED.value, \
            "evidence price type no longer reads as a clean LIST_PRICE at apply time"

    return True, "", ""


def revalidate_manifest_for_apply(manifest_dict: dict[str, Any], *,
                                  data_dir: Path = DATA_DIR, year: int = DEFAULT_YEAR) -> int:
    """Downgrade any AUTO_READY row that no longer qualifies, in place.

    Returns how many rows were downgraded. A row that survives is left
    completely untouched; a row that is downgraded gets a new
    terminal_state and note explaining why, and is never written.
    """
    catalog = Catalog.load(data_dir, year)
    ledger = PriceLedger.load(data_dir, year=year, catalog=catalog)
    scope_index = retail_scope_index(catalog, data_dir=data_dir, year=year)
    trim_reviews = trim_review_index(data_dir=data_dir, year=year)
    siblings_by_model = siblings_from_scope(catalog, scope_index, trim_reviews)

    downgraded = 0
    for model in manifest_dict.get("models", []):
        model_id = model.get("model_id")
        for grade in model.get("grades", []):
            if grade.get("terminal_state") != TerminalState.AUTO_READY.value or grade.get("applied"):
                continue
            ok, blocked_state, note = _revalidate_auto_ready_row(
                catalog, ledger, scope_index=scope_index, siblings_by_model=siblings_by_model,
                trim_reviews=trim_reviews, model_id=model_id, grade=grade)
            if ok:
                continue
            grade["terminal_state"] = blocked_state
            grade["note"] = note
            downgraded += 1
    return downgraded


def run_apply(*, data_dir: Path = DATA_DIR, year: int = DEFAULT_YEAR,
             manifest_path: Path):
    manifest_dict = load_manifest_dict(manifest_path)
    downgraded = revalidate_manifest_for_apply(manifest_dict, data_dir=data_dir, year=year)
    batch = build_append_price_batch(manifest_dict, year=year)
    if batch is None:
        manifest_path.write_text(
            json.dumps(manifest_dict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {
            "applied": False,
            "reason": "no unapplied AUTO_READY rows survived apply-time revalidation"
                     if downgraded else "no unapplied AUTO_READY rows in manifest",
            "revalidation_blocked": downgraded,
        }
    result = CanonicalInputPipeline(data_dir).apply(batch)

    applied_ids = {command["canonical_id"] for command in batch["commands"]}
    for model in manifest_dict.get("models", []):
        for grade in model.get("grades", []):
            if grade.get("trim_id") in applied_ids and grade.get("terminal_state") == TerminalState.AUTO_READY.value:
                grade["applied"] = True
                grade["applied_command_id"] = batch["batch_id"]
    manifest_path.write_text(
        json.dumps(manifest_dict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "applied": True, "batch_id": batch["batch_id"], "commands": len(batch["commands"]),
        "idempotent_replay": result.idempotent_replay, "changed_files": list(result.changed_files),
        "revalidation_blocked": downgraded,
    }


# ----------------------------------------------------------------- CLI

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--out", type=Path,
                        default=Path("vehreg/data") / str(DEFAULT_YEAR) / "market" / "prices"
                                / "research" / f"price_coverage_backfill_{date.today().isoformat()}.json")
    parser.add_argument("--limit", type=int, help="only the first N models, sorted by id (testing)")
    parser.add_argument("--apply", type=Path, help="apply AUTO_READY rows from this manifest")
    args = parser.parse_args(argv)

    if args.apply:
        result = run_apply(data_dir=args.data_dir, year=args.year, manifest_path=args.apply)
        print(json.dumps(result, ensure_ascii=False))
        return 0

    manifest = run_discover(data_dir=args.data_dir, year=args.year, out_path=args.out, limit=args.limit)
    print(json.dumps({"out": str(args.out), "summary": manifest.summary()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
