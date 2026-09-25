"""Retail scope for automated price facts.

Canonical identity and price eligibility are separate claims.  This module
answers the narrow question the price system actually needs: which existing
MarketTrim identities may receive an automated price fact *as of a date*.

Rules:
- HUMAN ``UNDER_MAINTENANCE`` is the only model-wide operational stop.
- Canonically HISTORICAL models are out of scope.
- A generation is active when it has launched by ``as_of`` (or has no launch
  date) and has not ended yet.  Legitimate old/new-generation overlap is
  allowed; overlap is not itself an identity failure.
- HUMAN-retired trims are out of scope.
- This module never creates, renames, merges or retires identity.

Lineup completeness/topology review is deliberately *not* a price-eligibility
gate.  A partial/noisy source may fail to describe the whole lineup while an
exact current price fact for one known trim is still valid.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from .catalog import Catalog, DATA_DIR, DEFAULT_YEAR, Generation
from .model_operational_state import under_maintenance_model_ids
from .retail_lifecycle_review import load_trim_lifecycle_decisions
from .taxonomy import RetailStatus

UNDER_MAINTENANCE = "UNDER_MAINTENANCE"
MODEL_HISTORICAL = "MODEL_HISTORICAL"
GENERATION_UNRESOLVED = "GENERATION_UNRESOLVED"
UNKNOWN_MODEL = "UNKNOWN_MODEL"
TRIM_RETIRED = "TRIM_RETIRED"


def _iso_on_or_before(value: Optional[str], as_of: date) -> bool:
    if not value:
        return True
    try:
        return date.fromisoformat(value) <= as_of
    except ValueError:
        return False


def _iso_after(value: Optional[str], as_of: date) -> bool:
    if not value:
        return True
    try:
        return date.fromisoformat(value) > as_of
    except ValueError:
        return False


def active_generations_of(catalog: Catalog, model_id: str, *,
                          as_of: Optional[date] = None) -> tuple[Generation, ...]:
    """Return every generation legitimately on sale at ``as_of``.

    Overlap is allowed.  A future ``ended`` date remains active until that date
    is reached; a future ``launched`` date is not active yet.  Malformed dates
    fail closed for that generation rather than being guessed around.
    """
    as_of = as_of or date.today()
    rows = [
        generation for generation in catalog.generations.values()
        if generation.model_id == model_id
        and _iso_on_or_before(generation.launched, as_of)
        and _iso_after(generation.ended, as_of)
    ]
    return tuple(sorted(rows, key=lambda row: (row.launched or "", row.id)))


def current_generation_of(catalog: Catalog, model_id: str, *,
                          as_of: Optional[date] = None) -> Optional[Generation]:
    """Compatibility helper: return the sole active generation, if there is one.

    Price matching itself uses :func:`active_generations_of` and therefore does
    not fail merely because two generations overlap during a real changeover.
    """
    active = active_generations_of(catalog, model_id, as_of=as_of)
    return active[0] if len(active) == 1 else None


@dataclass(frozen=True, slots=True)
class ModelScope:
    model_id: str
    active_generations: tuple[Generation, ...]
    blocked_reason: str = ""

    @property
    def in_scope(self) -> bool:
        return not self.blocked_reason and bool(self.active_generations)

    @property
    def current_generation(self) -> Optional[Generation]:
        """Compatibility view for callers that only care about the 1-gen case."""
        return self.active_generations[0] if len(self.active_generations) == 1 else None

    @property
    def active_generation_ids(self) -> frozenset[str]:
        return frozenset(generation.id for generation in self.active_generations)


def model_scope(catalog: Catalog, model_id: str, *,
                maintenance_ids: frozenset[str],
                as_of: Optional[date] = None) -> ModelScope:
    model = catalog.models.get(model_id)
    if model is None:
        return ModelScope(model_id, (), UNKNOWN_MODEL)
    if model_id in maintenance_ids:
        return ModelScope(model_id, (), UNDER_MAINTENANCE)
    if model.retail_status is RetailStatus.HISTORICAL:
        return ModelScope(model_id, (), MODEL_HISTORICAL)
    active = active_generations_of(catalog, model_id, as_of=as_of)
    if not active:
        return ModelScope(model_id, (), GENERATION_UNRESOLVED)
    return ModelScope(model_id, active, "")


def retail_scope_index(catalog: Catalog, *, data_dir=DATA_DIR,
                       year: int = DEFAULT_YEAR,
                       as_of: Optional[date] = None) -> dict[str, ModelScope]:
    """Every model's price scope, computed once per run."""
    maintenance_ids = under_maintenance_model_ids(data_dir=data_dir, year=year)
    return {
        model_id: model_scope(
            catalog, model_id, maintenance_ids=maintenance_ids, as_of=as_of)
        for model_id in catalog.models
    }


def trim_review_index(*, data_dir=DATA_DIR, year: int = DEFAULT_YEAR) -> dict[str, dict]:
    """trim_id -> its HUMAN retail-lifecycle-review row, if any."""
    return {row["trim_id"]: row for row in
            load_trim_lifecycle_decisions(data_dir=data_dir, year=year)}


def trim_price_eligibility(catalog: Catalog, trim_id: str, *,
                           scope_index: dict[str, ModelScope],
                           trim_reviews: dict[str, dict]) -> tuple[bool, str]:
    """Whether one existing trim may receive an automated price fact now."""
    trim = catalog.trims.get(trim_id)
    if trim is None:
        return False, UNKNOWN_MODEL
    generation = catalog.generations.get(trim.generation_id)
    if generation is None:
        return False, GENERATION_UNRESOLVED
    scope = scope_index.get(generation.model_id)
    if scope is None or not scope.in_scope:
        return False, (scope.blocked_reason if scope else UNKNOWN_MODEL) or GENERATION_UNRESOLVED
    if trim.generation_id not in scope.active_generation_ids:
        return False, GENERATION_UNRESOLVED
    review = trim_reviews.get(trim_id)
    if review is not None and review.get("status") == "HISTORICAL":
        return False, TRIM_RETIRED
    return True, ""


def siblings_from_scope(catalog: Catalog, scope_index: dict[str, ModelScope],
                        trim_reviews: dict[str, dict]) -> dict[str, list]:
    """Build ``model_id -> price-eligible MarketTrim`` from precomputed scope."""
    index: dict[str, list] = {}
    for model_id, scope in scope_index.items():
        if not scope.in_scope:
            continue
        trims = [
            trim
            for generation in scope.active_generations
            for trim in catalog.trims_of_generation(generation.id)
        ]
        eligible = [
            trim for trim in trims
            if trim_reviews.get(trim.id, {}).get("status") != "HISTORICAL"
        ]
        if eligible:
            index[model_id] = eligible
    return index


def scoped_siblings_by_model(catalog: Catalog, *, data_dir=DATA_DIR,
                             year: int = DEFAULT_YEAR,
                             as_of: Optional[date] = None) -> dict[str, list]:
    """Drop-in siblings map restricted to active, non-retired retail identity."""
    scope_index = retail_scope_index(
        catalog, data_dir=data_dir, year=year, as_of=as_of)
    trim_reviews = trim_review_index(data_dir=data_dir, year=year)
    return siblings_from_scope(catalog, scope_index, trim_reviews)


__all__ = [
    "GENERATION_UNRESOLVED", "MODEL_HISTORICAL", "ModelScope", "TRIM_RETIRED",
    "UNDER_MAINTENANCE", "UNKNOWN_MODEL", "active_generations_of",
    "current_generation_of", "model_scope", "retail_scope_index",
    "scoped_siblings_by_model", "siblings_from_scope", "trim_price_eligibility",
    "trim_review_index",
]
