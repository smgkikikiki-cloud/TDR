"""DLT v2 canonical resolution: observation -> the deepest grain evidence proves.

This module does not reimplement matching. ``vehreg.ingest.Resolver`` already
has the correct, tested behavior - brand-first, then model within that brand,
then variant within that model, RY-class tie-breaking, trim-detail brands
capped at MODEL, never guessing across an ambiguity - and this module is a
thin, observation-shaped facade over it, not a rewrite. See
``docs/vehicle-platform/DLT_V2_ARCHITECTURE.md`` for why reuse rather than
rewrite was the deliberate choice.

What this module adds is purely representational: a stable ``ResolutionResult``
record (canonical id, grain, match method, score, reason, candidates) that a
shadow-schema writer can serialize directly, decoupled from the tuple shape
``Resolver.resolve`` happens to return today.

Two things this module is careful never to do:

* Resolve against, or accept as an input, a legacy ``public.models`` UUID.
  ``Resolver`` resolves only against ``vehreg.catalog.Catalog`` unit ids -
  the same text canonical ids (``brand.model``, ``brand.model.generation.
  variant``) a Vehicle Master release publishes into
  ``canonical_model_projection.canonical_id``. A legacy UUID never enters
  this module at all; where one exists (the historical Supabase
  ``registrations.model_id``), it is carried on the observation's
  ``source_metadata`` as parity evidence only - see
  ``registration_observation.from_legacy_registration_row`` - and is read
  by the dual-run parity tool, never by this resolver.
* Chase full coverage by loosening the match floor. ``Resolver`` already
  refuses a fuzzy match below ``normalize.MATCH_FLOOR`` and reports an
  ambiguity rather than guessing; this module does not add a second,
  looser attempt on top.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .catalog import Catalog
from .ingest import Resolver
from .registration_observation import RegistrationObservation
from .taxonomy import Grain
from .trimledger import parse_trim, residual_trim


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    """The outcome of resolving one observation against the canonical catalog.

    ``canonical_id`` is ``None`` only when even the brand could not be
    placed (Invariant 6: preserve the observation, do not fabricate a fact
    target) - in every other case it is the catalog unit id at the deepest
    grain the source actually proved, and ``grain`` says which grain that
    is. ``reason`` is non-empty whenever resolution stopped short of the
    deepest grain the row's own text plausibly claimed (a model ambiguity, a
    variant the catalog does not have, a brand that could not be found at
    all) - a non-empty reason does not mean ``canonical_id`` is ``None``; it
    means "this is honestly as deep as the evidence goes," which may still
    be BRAND or MODEL grain with a real canonical id attached.
    """

    canonical_id: Optional[str]
    grain: Optional[Grain]
    match_how: str
    match_score: float
    reason: str
    candidates: tuple[str, ...] = ()

    @property
    def is_resolved(self) -> bool:
        """False only for the "not even brand" case - Invariant 6."""
        return self.canonical_id is not None

    @property
    def stopped_short(self) -> bool:
        """True whenever the reason a fact-writer should log a review row:
        either resolution failed outright, or it succeeded at a grain
        shallower than the row's own text plausibly supported."""
        return bool(self.reason)


def resolve_observation(resolver: Resolver,
                        observation: RegistrationObservation) -> ResolutionResult:
    """Resolve one observation. Pure with respect to this module: all the
    actual matching state (alias overrides, fuzzy indexes) lives on
    ``resolver``, built once per run and reused across every observation -
    see ``registration_v2_writer.py`` for how a run assembles it."""
    unit_id, grain, how, score, reason = resolver.resolve(
        observation.raw_brand, observation.raw_model, observation.raw_variant,
        observation.registration_type)
    candidates: tuple[str, ...] = ()
    if reason.startswith("model-ambiguous"):
        candidates = tuple(resolver.last_candidates)
    return ResolutionResult(
        canonical_id=unit_id,
        grain=(grain if unit_id is not None else None),
        match_how=how, match_score=score, reason=reason, candidates=candidates,
    )


#: Trim/battery/range detail derived from an observation's raw label, kept
#: separately from the fact's own grain - it is analysis detail about a
#: MODEL-grain fact, never a finer identity the fact itself claims. See
#: Invariant 7 and ``vehreg/trimledger.py``'s own module docstring: the
#: master (and this v2 fact) stays folded to the model for every brand;
#: this is the second set of books, derived on demand, never a MarketTrim.
def derive_trim_detail(catalog: Catalog, result: ResolutionResult,
                       raw_label: str) -> Optional[dict]:
    """``None`` unless the fact resolved to MODEL grain on a trim-detail
    brand and the raw label actually carries residual text beyond the brand
    and model names - the same "only when the source said something more"
    rule ``Resolver.resolve`` itself applies before it will even look for a
    variant match."""
    if result.grain is not Grain.MODEL or result.canonical_id is None:
        return None
    model = catalog.models.get(result.canonical_id)
    if model is None or model.brand_id not in set(catalog.trim_detail_brands()):
        return None
    residual = residual_trim(catalog, result.canonical_id, raw_label)
    if not residual:
        return None
    spec = parse_trim(residual)
    return {
        "trim_label": spec.trim_label,
        "grade": spec.grade,
        "drive": spec.drive,
        "range_km": spec.range_km,
        "battery_kwh": spec.battery_kwh,
        "powertrain_hint": spec.powertrain_hint,
    }
