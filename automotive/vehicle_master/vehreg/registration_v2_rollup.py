"""v2 serving rollup: MODEL/VARIANT/BRAND-safe aggregation of resolved facts.

Pure computation only, no I/O - this is the reference implementation the SQL
serving view (`registration_facts_v2_serving`,
`supabase/migration_v31_registration_v2_serving_and_cutover.sql`) mirrors, so
the rollup rule is testable offline without a live Postgres. See
`docs/vehicle-platform/PHASE3_CUTOVER.md` "Serving projection" for the full
rationale; the three rules this module enforces, restated:

* a MODEL-grain fact counts directly, at its own canonical id.
* a VARIANT-grain fact rolls up to its canonical model (the first two
  dot-segments of its id - ``vehreg.registration_v2_parity.model_component``,
  reused here rather than redefined).
* a BRAND-grain fact is **never** distributed across the brand's models -
  it stays a brand-only bucket, visible as "unknown/coarse" volume a
  model-level report cannot place at any model, never silently dropped from
  the report just because the report asked for a finer grain than the
  source proved (Invariant 15).

Every descendant grain (BRAND/MODEL/VARIANT alike) rolls up safely to brand,
so a brand-level report is always a plain, single ``sum(units) group by
canonical_brand_id`` over the same fact set - no separate "unknown" bucket
is needed at brand grain, because brand is always known whenever anything
deeper is.

Because each fact row corresponds to exactly one observation (Phase 2's own
1:1 invariant - see ``registration_v2_writer.build_batch``), no fact is ever
counted under two different rollup buckets here: ``model_level_rollup`` and
``unknown_coarse_volume_by_brand`` partition the fact set by grain (MODEL/
VARIANT vs. BRAND) with no overlap, and together they sum to exactly
``brand_level_rollup``'s total - proven directly by
``test_registration_v2_rollup.py::test_no_parent_child_double_count``.

``RollupFact``/``model_level_rollup``/``brand_level_rollup``/
``unknown_coarse_volume_by_brand``/``rollup_reconciles`` above describe only
already-*resolved* facts - the shape the earlier `registration_facts_v2_
serving` (fact-driven, ``registration_facts_v2 JOIN registration_observations_v2``)
used to emit. That view now starts from the authoritative OBSERVATION set
instead (``registration_observations_v2 LEFT JOIN registration_facts_v2``),
so a completely unresolved observation still contributes a row. ``ServingRow``/
``serving_reconciles`` below describe that broader, observation-driven shape;
the resolved-facts-only functions above remain correct and reused unchanged
for the portion of serving that did resolve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .registration_v2_parity import model_component


def brand_component(canonical_id: str) -> str:
    """The brand-level prefix of any canonical id - the first dot segment,
    which is also the id itself for a BRAND-grain fact."""
    return canonical_id.split(".", 1)[0]


@dataclass(frozen=True, slots=True)
class RollupFact:
    """The minimal shape this module needs from a resolved
    ``registration_facts_v2`` row."""

    canonical_id: str
    grain: str    # 'BRAND' | 'MODEL' | 'VARIANT'
    units: float


def model_level_rollup(facts: Iterable[RollupFact]) -> dict[str, float]:
    """canonical_model_id -> units, MODEL/VARIANT grain only. BRAND-grain
    facts are excluded entirely - never distributed across models - and are
    reported separately by ``unknown_coarse_volume_by_brand``."""
    out: dict[str, float] = {}
    for f in facts:
        if f.grain == "BRAND":
            continue
        key = model_component(f.canonical_id)
        out[key] = out.get(key, 0.0) + f.units
    return out


def brand_level_rollup(facts: Iterable[RollupFact]) -> dict[str, float]:
    """canonical_brand_id -> units, every grain included - safe because a
    canonical id's brand is always derivable regardless of how deep
    resolution reached."""
    out: dict[str, float] = {}
    for f in facts:
        key = brand_component(f.canonical_id)
        out[key] = out.get(key, 0.0) + f.units
    return out


def unknown_coarse_volume_by_brand(facts: Iterable[RollupFact]) -> dict[str, float]:
    """canonical_brand_id -> units, BRAND-grain facts only - the portion of
    ``brand_level_rollup`` a model-level report cannot place at any model.
    Must stay measurable on its own, not vanish because a caller asked for
    MODEL grain (Invariant 15)."""
    out: dict[str, float] = {}
    for f in facts:
        if f.grain == "BRAND":
            out[f.canonical_id] = out.get(f.canonical_id, 0.0) + f.units
    return out


def rollup_reconciles(facts: Iterable[RollupFact],
                      tolerance: float = 0.001) -> bool:
    """model_level_rollup + unknown_coarse_volume_by_brand ==
    brand_level_rollup == the plain sum of every fact's units - proof that
    no fact is ever counted twice and none silently disappears when rolled
    up to a coarser grain."""
    facts = list(facts)
    total = sum(f.units for f in facts)
    model_total = sum(model_level_rollup(facts).values())
    coarse_total = sum(unknown_coarse_volume_by_brand(facts).values())
    brand_total = sum(brand_level_rollup(facts).values())
    return (abs((model_total + coarse_total) - total) <= tolerance
           and abs(brand_total - total) <= tolerance)


# --------------------------------------------------------------------------
# Serving semantics: the authoritative OBSERVATION set is the volume source
# of truth; fact resolution is optional. Mirrors `registration_facts_v2_
# serving`'s own `registration_observations_v2 LEFT JOIN registration_facts_v2`
# (supabase/migration_v31_registration_v2_serving_and_cutover.sql) - every
# authoritative observation contributes a ``ServingRow`` whether or not it
# ever produced a fact, so this module's totals only ever agree with the SQL
# view's if a completely unresolved observation's units are still counted
# somewhere (``unresolved_units``), never dropped.
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ServingRow:
    """One row of ``registration_facts_v2_serving``: an authoritative
    observation, optionally joined to its resolved fact. ``canonical_id``/
    ``grain`` are both ``None`` for a completely unresolved observation
    (Invariant 6: the observation's units remain visible in serving even
    when resolution produced nothing at all) - never partially populated,
    since a fact either fully exists (canonical_id and grain both set) or
    does not exist at all."""

    canonical_id: str | None
    grain: str | None    # 'BRAND' | 'MODEL' | 'VARIANT' | None (unresolved)
    units: float

    @property
    def is_resolved(self) -> bool:
        return self.grain is not None


def resolved_rollup_facts(rows: Iterable[ServingRow]) -> list[RollupFact]:
    """The subset of serving rows that did resolve to something, as the
    plain ``RollupFact`` values ``model_level_rollup``/``brand_level_rollup``/
    ``unknown_coarse_volume_by_brand`` already operate on unchanged."""
    return [RollupFact(canonical_id=r.canonical_id, grain=r.grain, units=r.units)
           for r in rows if r.is_resolved]


def unresolved_units(rows: Iterable[ServingRow]) -> float:
    """Units of completely unresolved observations - no fact at all, so
    ``canonical_id``/``grain`` are both null. Visible on its own, exactly
    mirroring the SQL view's LEFT JOIN miss, per Invariant 6."""
    return sum(r.units for r in rows if not r.is_resolved)


def serving_reconciles(rows: Iterable[ServingRow], tolerance: float = 0.001) -> bool:
    """model_level_rollup + unknown_coarse_volume_by_brand (the BRAND-grain
    bucket) + unresolved_units == the plain sum of every serving row's units
    - the authoritative-observation volume ``registration_facts_v2_serving``
    must never drop or double-count, regardless of resolution coverage.
    Equivalent to, and a superset of, ``rollup_reconciles`` (which only ever
    saw resolved facts and had no unresolved-observation concept to prove)."""
    rows = list(rows)
    total = sum(r.units for r in rows)
    facts = resolved_rollup_facts(rows)
    model_total = sum(model_level_rollup(facts).values())
    coarse_total = sum(unknown_coarse_volume_by_brand(facts).values())
    return abs((model_total + coarse_total + unresolved_units(rows)) - total) <= tolerance
