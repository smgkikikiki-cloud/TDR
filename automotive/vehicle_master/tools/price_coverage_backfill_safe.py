#!/usr/bin/env python3
"""Safety follow-up for the one-time current-retail price coverage backfill.

This module deliberately reuses the merged #137 implementation and only tightens
three narrow behaviors needed before the first live discovery sweep:

- aggregate all usable current-retail OEM targets for a canonical Model instead
  of stopping after the first page;
- retain both independent media URLs/identities when MEDIA_TWO_AGREE proves a
  price fact;
- allow media fallback to fill only trims not already safely proven by OEM
  evidence, while still resolving title ambiguity against the full sibling set.

Canonical identity remains HUMAN-owned. Nothing here creates, renames, merges,
retires, or reparents Brand/Model/Generation/MarketTrim identity.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional

from tools import price_coverage_backfill as base
from vehreg.price_match import TrimMatchState
from vehreg.price_sources import SourceKind
from vehreg.pricefeed import PriceClaim
from vehreg.pricing import PriceType


@dataclass(frozen=True, slots=True)
class GradeEvidence(base.GradeEvidence):
    """The #137 evidence row plus complete provenance for audit/review."""

    source_refs: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()


def _ordered_unique(values) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return tuple(out)


def _refs(evidence) -> tuple[str, ...]:
    explicit = tuple(getattr(evidence, "source_refs", ()) or ())
    return _ordered_unique((*explicit, getattr(evidence, "source_ref", "")))


def _ids(evidence) -> tuple[str, ...]:
    return _ordered_unique(getattr(evidence, "source_ids", ()) or ())


_original_to_dict = base.GradeClassification.to_dict


def _grade_to_dict(self) -> dict[str, Any]:
    payload = _original_to_dict(self)
    payload["source_refs"] = list(_refs(self.evidence))
    payload["source_ids"] = list(_ids(self.evidence))
    return payload


# Manifest serialization is process-local and backwards-compatible: source_ref
# remains the deterministic primary URL used by APPEND_PRICE, while source_refs
# and source_ids preserve the complete proof set for audit/review.
base.GradeClassification.to_dict = _grade_to_dict
base.GradeEvidence = GradeEvidence


def discover_media_grades(model, siblings: list, *, transport,
                          eligible_trim_ids: Optional[set[str]] = None):
    """Require two independent outlets, preserving both proof URLs.

    ``siblings`` is always the full current sibling set used for ambiguity
    resolution. ``eligible_trim_ids`` only limits which exact trims may receive
    media fallback, so excluding an OEM-proven sibling never makes an ambiguous
    title look unique by accident.
    """
    if not siblings:
        return []
    hits_by_source = {
        source_id: base._search_media_source(
            source_id, base_url, model.brand_id, model.name_en, transport=transport)
        for source_id, base_url in base._MEDIA_SOURCES
    }
    source_ids = [source_id for source_id, _ in base._MEDIA_SOURCES]
    if len(source_ids) < 2:
        return []

    evidence: list[GradeEvidence] = []
    for trim in siblings:
        if eligible_trim_ids is not None and trim.id not in eligible_trim_ids:
            continue
        left = base._best_media_hit_for_trim(
            hits_by_source.get(source_ids[0], []), trim.id, siblings, model.name_en)
        right = base._best_media_hit_for_trim(
            hits_by_source.get(source_ids[1], []), trim.id, siblings, model.name_en)
        if left is None or right is None:
            continue
        if left.amounts[0] != right.amounts[0]:
            continue
        if not base._independent_media_hits(left, right):
            continue
        refs = _ordered_unique((left.url, right.url))
        ids = _ordered_unique((left.source_id, right.source_id))
        evidence.append(GradeEvidence(
            raw_grade=trim.name,
            amount_thb=left.amounts[0],
            extracted_price_type=PriceType.LIST_PRICE,
            evidence_tier=base.EvidenceTier.MEDIA_TWO_AGREE,
            source_ref=refs[0] if refs else "",
            source_refs=refs,
            source_ids=ids,
            observed_at=base.date.today().isoformat(),
        ))
    return evidence


def discover_oem_grades(model, registry, *, transport):
    """Aggregate every usable OEM current-retail target for this Model.

    Multiple partial pages remain PARTIAL. EXHAUSTIVE is only inherited from an
    explicit reviewed ``lineup_complete=true`` target. Exact claim deduplication
    is source-aware; cross-page conflicts are handled after canonical matching
    so two differently-named surfaces cannot silently choose a winner.
    """
    targets = sorted(
        (target for target in registry.targets.values()
         if target.model_hint == model.id and target.enabled),
        key=lambda target: target.id,
    )
    observed = base.date.today().isoformat()
    grades: list[GradeEvidence] = []
    source_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, Optional[int], str]] = set()
    explicitly_complete = False

    for target in targets:
        profile = registry.profiles.get(target.source_id)
        if profile is None or profile.kind is not SourceKind.OEM:
            continue
        if target.role not in base._CURRENT_OEM_ROLES:
            continue
        try:
            adapter = base.adapter_for(registry, target, transport=transport)
            result = adapter.fetch(target)
        except base.FetchError:
            continue
        if result.not_modified or result.document is None:
            continue
        try:
            extraction = base.extract_oem_price_claims(target, result)
        except base.ExtractionError:
            continue
        list_claims = [
            claim for claim in extraction.claims
            if claim.price_type is PriceType.LIST_PRICE
        ]
        if not list_claims:
            continue

        explicitly_complete = explicitly_complete or bool(target.lineup_complete)
        source_rows.append({
            "target_id": target.id,
            "role": target.role.value,
            "source_id": target.source_id,
            "url": target.url,
            "lineup_complete": bool(target.lineup_complete),
        })
        for claim in list_claims:
            key = (str(claim.trim_raw).strip().casefold(), claim.amount_thb, target.url)
            if key in seen:
                continue
            seen.add(key)
            grades.append(GradeEvidence(
                raw_grade=claim.trim_raw,
                amount_thb=claim.amount_thb,
                extracted_price_type=claim.price_type,
                evidence_tier=base.EvidenceTier.OEM_CURRENT_MODEL_PAGE,
                source_ref=target.url,
                source_refs=(target.url,),
                source_ids=(target.source_id,),
                observed_at=observed,
                semantics_clear=True,
            ))

    if not grades:
        return None

    urls = _ordered_unique(row["url"] for row in source_rows)
    source_ids = _ordered_unique(row["source_id"] for row in source_rows)
    roles = _ordered_unique(row["role"] for row in source_rows)
    source = {
        "role": roles[0] if len(roles) == 1 else "MULTI_CURRENT_RETAIL",
        "source_id": source_ids[0] if len(source_ids) == 1 else "+".join(source_ids),
        "url": urls[0] if urls else "",
        "urls": list(urls),
        "targets": source_rows,
        "fetched_at": observed,
        "lineup_complete": explicitly_complete,
    }
    lineup_status = (
        base.LineupStatus.EXHAUSTIVE
        if explicitly_complete else base.LineupStatus.PARTIAL
    )
    return lineup_status, source, grades


def _classify_evidence(model, catalog, ledger, siblings_by_model, evidence):
    match = None
    if evidence.evidence_tier is not base.EvidenceTier.NONE:
        evidence_source_ids = _ids(evidence)
        claim = PriceClaim(
            claim_id=f"backfill-{model.id}-{evidence.raw_grade}",
            document_id="sha256:" + "0" * 64,
            source_id=evidence_source_ids[0] if evidence_source_ids else "",
            brand_raw=model.brand_id,
            model_raw=model.name_en,
            trim_raw=evidence.raw_grade,
            amount_thb=evidence.amount_thb or 0,
            price_type=evidence.extracted_price_type or PriceType.UNKNOWN,
        )
        match = base.match_trim_diagnostic(
            catalog, claim, siblings_by_model=siblings_by_model)

    existing = None
    generation_id = None
    if match is not None and match.trim_id is not None:
        trim = catalog.trims.get(match.trim_id)
        generation_id = trim.generation_id if trim else None
        row = ledger.current_list_price(match.trim_id)
        existing = row.amount_thb if row else None
    return base.classify_grade(
        evidence, match, existing_list_price_thb=existing,
        generation_id=generation_id)


def _coalesce_exact_trim_evidence(grades):
    """One canonical trim gets one safe fact, or an explicit local conflict."""
    by_trim: dict[str, list] = {}
    passthrough: list = []
    order: list[str] = []
    for grade in grades:
        if (grade.match is None
                or grade.match.state is not TrimMatchState.EXACT
                or not grade.trim_id):
            passthrough.append(grade)
            continue
        if grade.trim_id not in by_trim:
            order.append(grade.trim_id)
            by_trim[grade.trim_id] = []
        by_trim[grade.trim_id].append(grade)

    merged: list = []
    for trim_id in order:
        group = by_trim[trim_id]
        amounts = {grade.evidence.amount_thb for grade in group}
        if len(amounts) > 1:
            detail = ", ".join(str(value) for value in sorted(amounts) if value is not None)
            for grade in group:
                merged.append(replace(
                    grade,
                    terminal_state=base.TerminalState.PRICE_CONFLICT,
                    note=("conflicting current evidence for the same canonical trim "
                          f"({trim_id}): {detail} THB; no automatic winner"),
                ))
            continue

        first = group[0]
        refs = _ordered_unique(ref for grade in group for ref in _refs(grade.evidence))
        ids = _ordered_unique(source_id for grade in group for source_id in _ids(grade.evidence))
        evidence = replace(
            first.evidence,
            source_ref=refs[0] if refs else first.evidence.source_ref,
            source_refs=refs,
            source_ids=ids,
        )
        merged.append(replace(first, evidence=evidence))
    return [*merged, *passthrough]


def discover_model(model, catalog, ledger, registry, *, scope,
                   siblings_by_model: dict[str, list], transport):
    siblings = siblings_by_model.get(model.id, [])
    oem_result = discover_oem_grades(model, registry, transport=transport)

    source: dict[str, Any]
    lineup_status: base.LineupStatus
    evidence_tier: base.EvidenceTier
    grades: list = []

    if oem_result is not None:
        lineup_status, source, oem_evidence = oem_result
        evidence_tier = base.EvidenceTier.OEM_CURRENT_MODEL_PAGE
        grades = _coalesce_exact_trim_evidence([
            _classify_evidence(model, catalog, ledger, siblings_by_model, evidence)
            for evidence in oem_evidence
        ])
        safely_proven = {
            grade.trim_id for grade in grades
            if grade.trim_id and grade.terminal_state in {
                base.TerminalState.AUTO_READY, base.TerminalState.COMPLETE,
            }
        }
        missing_ids = {trim.id for trim in siblings if trim.id not in safely_proven}
        media_evidence = discover_media_grades(
            model, siblings, transport=transport, eligible_trim_ids=missing_ids)
        if media_evidence:
            media_grades = [
                _classify_evidence(model, catalog, ledger, siblings_by_model, evidence)
                for evidence in media_evidence
            ]
            grades = _coalesce_exact_trim_evidence([*grades, *media_grades])
            source = dict(source)
            source["media_fallback"] = {
                "source_ids": list(_ordered_unique(
                    source_id for evidence in media_evidence for source_id in _ids(evidence))),
                "urls": list(_ordered_unique(
                    ref for evidence in media_evidence for ref in _refs(evidence))),
            }
    else:
        media_evidence = discover_media_grades(model, siblings, transport=transport)
        if media_evidence:
            lineup_status = base.LineupStatus.PARTIAL
            evidence_tier = base.EvidenceTier.MEDIA_TWO_AGREE
            source = {
                "role": "MEDIA_SEARCH",
                "source_id": "autolifethailand+headlightmag",
                "url": media_evidence[0].source_ref,
                "urls": list(_ordered_unique(
                    ref for evidence in media_evidence for ref in _refs(evidence))),
                "fetched_at": media_evidence[0].observed_at,
                "lineup_complete": False,
            }
            grades = _coalesce_exact_trim_evidence([
                _classify_evidence(model, catalog, ledger, siblings_by_model, evidence)
                for evidence in media_evidence
            ])
        else:
            lineup_status = base.LineupStatus.UNKNOWN
            evidence_tier = base.EvidenceTier.NONE
            source = {}
            no_source = GradeEvidence(
                raw_grade=model.name_en,
                amount_thb=None,
                extracted_price_type=None,
                evidence_tier=base.EvidenceTier.NONE,
                source_ref="",
                source_refs=(),
                source_ids=(),
                observed_at=base.date.today().isoformat(),
            )
            grades = [
                _classify_evidence(model, catalog, ledger, siblings_by_model, no_source)
            ]

    topology_required, topology_note = base._topology_review(
        lineup_status, grades, siblings)
    return base.ModelManifestEntry(
        model_id=model.id,
        lineup_status=lineup_status,
        evidence_tier=evidence_tier,
        lineup_source=source,
        grades=grades,
        topology_review_required=topology_required,
        topology_note=topology_note,
    )


# Patch only the runtime hooks the merged #137 orchestrator resolves by name.
# run_discover/run_apply/batching/writer logic remains the reviewed implementation.
base.discover_media_grades = discover_media_grades
base.discover_oem_grades = discover_oem_grades
base.discover_model = discover_model


def main(argv=None) -> int:
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
