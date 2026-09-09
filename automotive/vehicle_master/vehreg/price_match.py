"""P4 diagnostics around the canonical MarketTrim matcher.

The production matcher remains :func:`vehreg.pricefeed.match_trim`.  This module
never reimplements its resolution decision; it explains that decision so fetch
and review tooling can distinguish a unique canonical match from ambiguity or
an unmapped raw grade.

PriceClaim -> existing match_trim() -> TrimMatchResult

Nothing here writes PriceLedger, changes catalog identity, or resolves DLT
Variant / DLT Trim Ledger rows.
"""

from __future__ import annotations

from dataclasses import dataclass
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

    def as_dict(self) -> dict:
        return {
            "state": self.state.value,
            "model_id": self.model_id,
            "trim_id": self.trim_id,
            "candidate_ids": list(self.candidate_ids),
            "method": self.method.value,
            "reason": self.reason,
        }


def _exact_sources(catalog: Catalog, model_id: str, trim_ids: tuple[str, ...],
                   claim: PriceClaim) -> dict[str, str]:
    """For already-selected matcher candidates, explain exact token equality."""
    model = catalog.models[model_id]
    wanted = grade_tokens(claim.trim_raw, model.name_en)
    sources: dict[str, str] = {}
    for trim_id in trim_ids:
        trim = catalog.trims[trim_id]
        if wanted and grade_tokens(trim.name, model.name_en) == wanted:
            sources[trim_id] = "name"
            continue
        if wanted and any(grade_tokens(alias, model.name_en) == wanted
                          for alias in trim.aliases):
            sources[trim_id] = "alias"
    return sources


def match_trim_diagnostic(catalog: Catalog, claim: PriceClaim, *,
                          siblings_by_model: Optional[dict[str, list]] = None,
                          model_memo: Optional[dict] = None) -> TrimMatchResult:
    """Explain the existing canonical MarketTrim matcher without changing it.

    ``EXACT`` means the claim resolves to exactly one canonical MarketTrim.  The
    ``method`` field says whether that uniqueness came from exact canonical-name
    tokens, an exact alias, or the production matcher's conservative partial
    grade rule.  Ambiguous and unmapped results are never promoted here.
    """
    key = (claim.brand_raw, claim.model_raw, claim.trim_raw)
    if model_memo is not None and key in model_memo:
        _, model_id = model_memo[key]
    else:
        _, model_id = match_model(catalog, *key)
        if model_memo is not None:
            brand_id, checked_model_id = match_model(catalog, *key)
            model_memo[key] = (brand_id, checked_model_id)
            model_id = checked_model_id

    if model_id is None:
        return TrimMatchResult(
            TrimMatchState.UNMAPPED, None, None, (), TrimMatchMethod.NO_MODEL,
            "brand/model could not be resolved to one canonical catalog model",
        )

    if siblings_by_model is None:
        siblings_by_model = trims_by_model(catalog)
    siblings = siblings_by_model.get(model_id, [])
    if not siblings:
        return TrimMatchResult(
            TrimMatchState.UNMAPPED, model_id, None, (),
            TrimMatchMethod.NO_MARKET_TRIMS,
            "canonical model has no MarketTrim children",
        )

    model = catalog.models[model_id]
    wanted = grade_tokens(claim.trim_raw, model.name_en)
    if not wanted:
        return TrimMatchResult(
            TrimMatchState.UNMAPPED, model_id, None, (),
            TrimMatchMethod.EMPTY_GRADE,
            "raw grade contains no identifying tokens after normalization",
        )

    trim_id, candidates = match_trim(
        catalog, claim,
        siblings_by_model=siblings_by_model,
        model_memo=model_memo,
    )
    exact_sources = _exact_sources(catalog, model_id, candidates, claim)

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
        )

    return TrimMatchResult(
        TrimMatchState.UNMAPPED, model_id, None, (), TrimMatchMethod.NO_GRADE_MATCH,
        "model resolved but no canonical MarketTrim safely matches the raw grade",
    )
