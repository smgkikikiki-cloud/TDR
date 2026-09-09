"""P4 diagnostics around the canonical MarketTrim matcher.

The production resolver remains :func:`vehreg.pricefeed.match_trim`. This module
adds a narrow retail-grade surface normalization and explains the resolver's
decision so fetch/review tooling can distinguish a unique canonical match from
ambiguity or an unmapped raw grade.

PriceClaim -> retail surface normalization -> existing match_trim() -> diagnostic

Nothing here writes PriceLedger, changes catalog identity, or resolves DLT
Variant / DLT Trim Ledger rows.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional

from .catalog import Catalog
from .pricefeed import (
    PriceClaim,
    grade_tokens,
    match_model,
    match_trim,
    trims_by_model,
)


class TrimMatchState(str, Enum):
    """P4 disposition for a raw retail-grade claim."""

    EXACT = "EXACT"
    AMBIGUOUS = "AMBIGUOUS"
    UNMAPPED = "UNMAPPED"


class TrimMatchMethod(str, Enum):
    """Why the production matcher produced its answer."""

    EXACT_NAME = "EXACT_NAME"
    EXACT_ALIAS = "EXACT_ALIAS"
    PARTIAL_GRADE = "PARTIAL_GRADE"
    AMBIGUOUS_EXACT = "AMBIGUOUS_EXACT"
    AMBIGUOUS_PARTIAL = "AMBIGUOUS_PARTIAL"
    NO_MODEL = "NO_MODEL"
    NO_MARKET_TRIMS = "NO_MARKET_TRIMS"
    EMPTY_GRADE = "EMPTY_GRADE"
    NO_GRADE_MATCH = "NO_GRADE_MATCH"


@dataclass(frozen=True, slots=True)
class TrimMatchResult:
    state: TrimMatchState
    model_id: Optional[str]
    trim_id: Optional[str]
    candidate_ids: tuple[str, ...]
    method: TrimMatchMethod
    reason: str
    normalized_trim_raw: str

    def as_dict(self) -> dict:
        return {
            "state": self.state.value,
            "model_id": self.model_id,
            "trim_id": self.trim_id,
            "candidate_ids": list(self.candidate_ids),
            "method": self.method.value,
            "reason": self.reason,
            "normalized_trim_raw": self.normalized_trim_raw,
        }


def normalize_retail_grade(raw: str) -> str:
    """Preserve grade punctuation that generic catalog folding discards.

    ``fold`` intentionally removes punctuation across the wider DLT/catalog
    matcher. For retail grades, however, ``MAX+`` and ``MAX`` are different
    products. Expanding ``+`` to the word ``PLUS`` before the existing matcher
    keeps that distinction without changing normalization globally.
    """
    return " ".join(str(raw or "").replace("+", " PLUS ").split())


def _normalized_claim(claim: PriceClaim) -> PriceClaim:
    normalized = normalize_retail_grade(claim.trim_raw)
    return claim if normalized == claim.trim_raw else replace(claim, trim_raw=normalized)


def _exact_sources(catalog: Catalog, model_id: str, trim_ids: tuple[str, ...],
                   claim: PriceClaim) -> dict[str, str]:
    """For already-selected matcher candidates, explain exact token equality."""
    model = catalog.models[model_id]
    wanted = grade_tokens(claim.trim_raw, model.name_en)
    sources: dict[str, str] = {}
    for trim_id in trim_ids:
        trim = catalog.trims[trim_id]
        # Canonical names receive the same retail-surface normalization as raw
        # claims so punctuation like MAX+ retains its meaning in diagnostics.
        name = normalize_retail_grade(trim.name)
        if wanted and grade_tokens(name, model.name_en) == wanted:
            sources[trim_id] = "name"
            continue
        if wanted and any(
            grade_tokens(normalize_retail_grade(alias), model.name_en) == wanted
            for alias in trim.aliases
        ):
            sources[trim_id] = "alias"
    return sources


def match_trim_diagnostic(catalog: Catalog, claim: PriceClaim, *,
                          siblings_by_model: Optional[dict[str, list]] = None,
                          model_memo: Optional[dict] = None) -> TrimMatchResult:
    """Resolve and explain one raw grade without changing canonical data.

    ``EXACT`` means exactly one canonical MarketTrim was resolved. ``method``
    records whether uniqueness came from exact canonical-name tokens, an exact
    alias, or the existing matcher's conservative partial-grade rule.
    """
    matched_claim = _normalized_claim(claim)
    normalized = matched_claim.trim_raw
    key = (matched_claim.brand_raw, matched_claim.model_raw, matched_claim.trim_raw)
    if model_memo is not None and key in model_memo:
        _, model_id = model_memo[key]
    else:
        brand_id, model_id = match_model(catalog, *key)
        if model_memo is not None:
            model_memo[key] = (brand_id, model_id)

    if model_id is None:
        return TrimMatchResult(
            TrimMatchState.UNMAPPED, None, None, (), TrimMatchMethod.NO_MODEL,
            "brand/model could not be resolved to one canonical catalog model",
            normalized,
        )

    if siblings_by_model is None:
        siblings_by_model = trims_by_model(catalog)
    siblings = siblings_by_model.get(model_id, [])
    if not siblings:
        return TrimMatchResult(
            TrimMatchState.UNMAPPED, model_id, None, (),
            TrimMatchMethod.NO_MARKET_TRIMS,
            "canonical model has no MarketTrim children",
            normalized,
        )

    model = catalog.models[model_id]
    wanted = grade_tokens(matched_claim.trim_raw, model.name_en)
    if not wanted:
        return TrimMatchResult(
            TrimMatchState.UNMAPPED, model_id, None, (),
            TrimMatchMethod.EMPTY_GRADE,
            "raw grade contains no identifying tokens after normalization",
            normalized,
        )

    trim_id, candidates = match_trim(
        catalog, matched_claim,
        siblings_by_model=siblings_by_model,
        model_memo=model_memo,
    )
    exact_sources = _exact_sources(catalog, model_id, candidates, matched_claim)

    if trim_id is not None:
        source = exact_sources.get(trim_id)
        if source == "name":
            method = TrimMatchMethod.EXACT_NAME
            reason = "raw grade tokens exactly match the canonical MarketTrim name"
        elif source == "alias":
            method = TrimMatchMethod.EXACT_ALIAS
            reason = "raw grade tokens exactly match a canonical MarketTrim alias"
        else:
            method = TrimMatchMethod.PARTIAL_GRADE
            reason = "one canonical MarketTrim uniquely satisfies the conservative partial-grade rule"
        return TrimMatchResult(
            TrimMatchState.EXACT, model_id, trim_id, candidates, method, reason,
            normalized,
        )

    if candidates:
        if exact_sources and len(exact_sources) == len(candidates):
            method = TrimMatchMethod.AMBIGUOUS_EXACT
            reason = "multiple MarketTrims have an exact grade-token match; tie is not broken"
        else:
            method = TrimMatchMethod.AMBIGUOUS_PARTIAL
            reason = "multiple MarketTrims tie under the conservative partial-grade rule"
        return TrimMatchResult(
            TrimMatchState.AMBIGUOUS, model_id, None, candidates, method, reason,
            normalized,
        )

    return TrimMatchResult(
        TrimMatchState.UNMAPPED, model_id, None, (), TrimMatchMethod.NO_GRADE_MATCH,
        "model resolved but no canonical MarketTrim safely matches the raw grade",
        normalized,
    )
