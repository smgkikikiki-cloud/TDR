"""The one place that decides which MarketTrim the price system may touch.

Canonical identity (``Catalog``) and "is this SKU safe for an automated
price write" are different questions. A MarketTrim can be real -- proven by
ECO/homologation evidence -- while belonging to a generation that is no
longer sold, or to a model currently flagged for manual maintenance, or
while a human reviewer has explicitly retired it. None of that changes what
the trim *is*; it changes whether price matching, the coverage backfill,
the scheduled price feed and the retail price-band projection are allowed
to use it.

This module answers that question once, from the live ``Catalog`` plus the
two existing HUMAN-only sidecar stores
(:mod:`vehreg.retail_lifecycle_review`, :mod:`vehreg.model_operational_state`),
and every price-touching caller reuses the same answer -- that is what
keeps the one-time backfill and the ongoing scheduled feed on the same
safety contract instead of drifting apart.

Nothing here writes anything. It is pure and catalog-native: no serialized
release dict, no new storage, no new review workflow.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .catalog import Catalog, DATA_DIR, DEFAULT_YEAR, Generation
from .model_operational_state import under_maintenance_model_ids
from .retail_lifecycle_review import load_trim_lifecycle_decisions
from .taxonomy import RetailStatus

#: Why a model's current lineup cannot be trusted for an automated write.
#: "" means the model is in scope.
UNDER_MAINTENANCE = "UNDER_MAINTENANCE"
MODEL_HISTORICAL = "MODEL_HISTORICAL"
GENERATION_UNRESOLVED = "GENERATION_UNRESOLVED"
UNKNOWN_MODEL = "UNKNOWN_MODEL"
TRIM_RETIRED = "TRIM_RETIRED"


def current_generation_of(catalog: Catalog, model_id: str) -> Optional[Generation]:
    """The model's one current generation, or ``None`` if that cannot be
    established with confidence.

    Confidence means exactly one of the model's generations has no
    ``ended`` date. Zero (every generation has ended -- the model is fully
    discontinued) and two-or-more (an overlapping changeover, a data
    problem) both fail closed rather than guess which generation is
    "really" current.
    """
    candidates = [g for g in catalog.generations.values()
                  if g.model_id == model_id and not g.ended]
    return candidates[0] if len(candidates) == 1 else None


@dataclass(frozen=True, slots=True)
class ModelScope:
    model_id: str
    current_generation: Optional[Generation]
    blocked_reason: str = ""

    @property
    def in_scope(self) -> bool:
        return not self.blocked_reason and self.current_generation is not None


def model_scope(catalog: Catalog, model_id: str, *,
                maintenance_ids: frozenset[str]) -> ModelScope:
    model = catalog.models.get(model_id)
    if model is None:
        return ModelScope(model_id, None, UNKNOWN_MODEL)
    if model_id in maintenance_ids:
        return ModelScope(model_id, None, UNDER_MAINTENANCE)
    if model.retail_status is RetailStatus.HISTORICAL:
        return ModelScope(model_id, None, MODEL_HISTORICAL)
    generation = current_generation_of(catalog, model_id)
    if generation is None:
        return ModelScope(model_id, None, GENERATION_UNRESOLVED)
    return ModelScope(model_id, generation, "")


def retail_scope_index(catalog: Catalog, *, data_dir=DATA_DIR,
                       year: int = DEFAULT_YEAR) -> dict[str, ModelScope]:
    """Every model's scope, computed once per run."""
    maintenance_ids = under_maintenance_model_ids(data_dir=data_dir, year=year)
    return {
        model_id: model_scope(catalog, model_id, maintenance_ids=maintenance_ids)
        for model_id in catalog.models
    }


def trim_review_index(*, data_dir=DATA_DIR, year: int = DEFAULT_YEAR) -> dict[str, dict]:
    """trim_id -> its HUMAN retail-lifecycle-review row, if any."""
    return {row["trim_id"]: row for row in
            load_trim_lifecycle_decisions(data_dir=data_dir, year=year)}


def trim_price_eligibility(catalog: Catalog, trim_id: str, *,
                           scope_index: dict[str, ModelScope],
                           trim_reviews: dict[str, dict]) -> tuple[bool, str]:
    """Whether ``trim_id`` is safe for an automated price write right now.

    Returns ``(eligible, reason)``; ``reason`` is empty when eligible, and
    is one of this module's blocked-reason constants (or ``TRIM_RETIRED``)
    otherwise. This is the single-trim version of
    :func:`scoped_siblings_by_model`, meant for the apply-time revalidation
    that has to check one row without recomputing the whole catalog scope.
    """
    trim = catalog.trims.get(trim_id)
    if trim is None:
        return False, UNKNOWN_MODEL
    generation = catalog.generations.get(trim.generation_id)
    if generation is None:
        return False, GENERATION_UNRESOLVED
    scope = scope_index.get(generation.model_id)
    if scope is None or not scope.in_scope:
        return False, (scope.blocked_reason if scope else UNKNOWN_MODEL) or GENERATION_UNRESOLVED
    if trim.generation_id != scope.current_generation.id:
        return False, GENERATION_UNRESOLVED
    review = trim_reviews.get(trim_id)
    if review is not None and review.get("status") == "HISTORICAL":
        return False, TRIM_RETIRED
    return True, ""


def siblings_from_scope(catalog: Catalog, scope_index: dict[str, ModelScope],
                        trim_reviews: dict[str, dict]) -> dict[str, list]:
    """Build the scoped siblings map from already-computed scope/review data.

    Split out from :func:`scoped_siblings_by_model` so a caller that also
    needs the per-model ``ModelScope`` (to explain a skip, or to
    revalidate a single row later) can compute ``scope_index``/
    ``trim_reviews`` once and reuse them for both purposes instead of
    paying for the sidecar reads twice.
    """
    index: dict[str, list] = {}
    for model_id, scope in scope_index.items():
        if not scope.in_scope:
            continue
        trims = catalog.trims_of_generation(scope.current_generation.id)
        eligible = [t for t in trims if trim_reviews.get(t.id, {}).get("status") != "HISTORICAL"]
        if eligible:
            index[model_id] = eligible
    return index


def scoped_siblings_by_model(catalog: Catalog, *, data_dir=DATA_DIR,
                             year: int = DEFAULT_YEAR) -> dict[str, list]:
    """Drop-in replacement for :func:`vehreg.pricefeed.trims_by_model`.

    Same shape (``model_id -> list[MarketTrim]``), but scoped to trims that
    are safe for an automated price write: belong to the model's
    confidently-resolved current generation, the model is not under
    maintenance or canonically HISTORICAL, and no HUMAN reviewer has
    retired the trim. ``match_trim``/``match_trim_diagnostic`` already
    treat an absent/empty entry as "no market trims" and fail closed to
    UNMAPPED, so passing this in place of the unscoped map is the entire
    fix at every matching call site -- no change to the matchers
    themselves.
    """
    scope_index = retail_scope_index(catalog, data_dir=data_dir, year=year)
    trim_reviews = trim_review_index(data_dir=data_dir, year=year)
    return siblings_from_scope(catalog, scope_index, trim_reviews)


__all__ = [
    "GENERATION_UNRESOLVED", "MODEL_HISTORICAL", "ModelScope", "TRIM_RETIRED",
    "UNDER_MAINTENANCE", "UNKNOWN_MODEL", "current_generation_of", "model_scope",
    "retail_scope_index", "scoped_siblings_by_model", "siblings_from_scope",
    "trim_price_eligibility", "trim_review_index",
]
