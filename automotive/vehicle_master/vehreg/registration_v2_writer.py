"""Pure batch builder: observations -> the three DLT v2 shadow row sets.

No I/O anywhere in this module - it takes an already-assembled list of
``RegistrationObservation`` plus a ``Resolver``/``Catalog`` pair the caller
built once, and returns plain dict rows ready for a live writer to upsert.
This mirrors the pure/live split ``tdr_bridge/external_identity_sync.py`` and
``tools/sync_external_identity_registry.py`` already use for Phase 1: the
classification/decision logic is fully unit-testable with synthetic fixtures,
and the live Supabase adapter (``tools/backfill_registration_v2.py``,
``tools/registration_v2_dlt_ingest.py``) is a thin, separate layer that only
ever writes exactly what this module proposed.

Row shape mirrors ``supabase/migration_v29_registration_dlt_v2_shadow.sql``
exactly - a caller only ever inserts these dicts verbatim, never edits or
re-derives a column from them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .catalog import Catalog
from .ingest import Resolver
from .registration_observation import RegistrationObservation
from .resolution_v2 import derive_trim_detail, resolve_observation


def _observation_row(observation: RegistrationObservation) -> dict[str, Any]:
    return {
        "observation_id": observation.observation_id,
        "source_kind": observation.source_kind,
        "source_ref": observation.source_ref,
        "period": observation.period,
        "registration_type": observation.registration_type,
        "province": observation.province,
        "raw_brand": observation.raw_brand,
        "raw_model": observation.raw_model,
        "raw_variant": observation.raw_variant,
        "raw_label": observation.raw_label,
        "units": observation.units,
        "normalized_brand": observation.normalized_brand,
        "normalized_model": observation.normalized_model,
        "payload_hash": observation.payload_hash,
        "source_metadata": dict(observation.source_metadata),
    }


@dataclass(frozen=True, slots=True)
class ObservationResolution:
    """One observation paired with what resolving it produced - the unit a
    caller iterates when deciding what to write, log, or report."""

    observation: RegistrationObservation
    fact_row: dict[str, Any] | None
    review_row: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class WriteBatch:
    observation_rows: list[dict[str, Any]]
    fact_rows: list[dict[str, Any]]
    review_rows: list[dict[str, Any]]
    resolutions: list[ObservationResolution]

    @property
    def total_units(self) -> float:
        return sum(o.units for o in
                   (r.observation for r in self.resolutions))

    @property
    def resolved_units(self) -> float:
        return sum(r["units"] for r in self.fact_rows)

    @property
    def unresolved_units(self) -> float:
        """Invariant 6: units of every observation that produced no fact -
        preserved and visible, never silently dropped."""
        return sum(r.observation.units for r in self.resolutions
                  if r.fact_row is None)

    def reconciles(self, tolerance: float = 0.001) -> bool:
        """Invariant 8: resolved + unresolved == observed, exactly."""
        return abs((self.resolved_units + self.unresolved_units)
                  - self.total_units) <= tolerance

    def summary(self) -> dict[str, Any]:
        by_grain: dict[str, int] = {}
        for row in self.fact_rows:
            by_grain[row["grain"]] = by_grain.get(row["grain"], 0) + 1
        by_reason: dict[str, int] = {}
        for row in self.review_rows:
            bucket = row["reason"].split(":", 1)[0]
            by_reason[bucket] = by_reason.get(bucket, 0) + 1
        return {
            "observations": len(self.observation_rows),
            "facts": len(self.fact_rows),
            "review_rows": len(self.review_rows),
            "total_units": self.total_units,
            "resolved_units": self.resolved_units,
            "unresolved_units": self.unresolved_units,
            "reconciles": self.reconciles(),
            "facts_by_grain": dict(sorted(by_grain.items())),
            "review_by_reason": dict(sorted(by_reason.items())),
        }


def build_batch(observations: list[RegistrationObservation], resolver: Resolver,
                catalog: Catalog, *, now: str | None = None) -> WriteBatch:
    """Resolve every observation and shape the rows a live writer upserts.

    Deterministic given deterministic inputs: the same observation list and
    the same resolver/catalog state always produce the same rows in the same
    order - the ordering follows the input list, which callers should
    already be feeding in a stable order (see the backfill tool's period
    ordering) so a rerun's output is reproducible for diffing.

    A repeated observation (the same ``observation_id`` appearing twice in
    ``observations`` - a source returning a row twice, or a caller re-adding
    an already-processed page) is collapsed to its first occurrence before
    resolution runs, so its units are never counted twice in this batch's
    totals or written as two rows. This is enforced here, not left to the
    live writer's upsert alone, so a batch's own summary numbers are already
    correct before anything is written.
    """
    now = now or datetime.now(timezone.utc).isoformat()
    observation_rows: list[dict[str, Any]] = []
    fact_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    resolutions: list[ObservationResolution] = []
    seen_ids: set[str] = set()

    for observation in observations:
        if observation.observation_id in seen_ids:
            continue
        seen_ids.add(observation.observation_id)
        observation_rows.append(_observation_row(observation))
        result = resolve_observation(resolver, observation)

        fact_row: dict[str, Any] | None = None
        if result.is_resolved:
            trim_detail = derive_trim_detail(catalog, result, observation.raw_label)
            fact_row = {
                "observation_id": observation.observation_id,
                "period": observation.period,
                "registration_type": observation.registration_type,
                "province": observation.province,
                "canonical_id": result.canonical_id,
                "grain": result.grain.value,
                "units": observation.units,
                "match_how": result.match_how,
                "match_score": result.match_score,
                "resolution_reason": result.reason,
                "trim_detail": trim_detail,
                "resolved_at": now,
            }
            fact_rows.append(fact_row)

        review_row: dict[str, Any] | None = None
        if result.stopped_short:
            review_row = {
                "observation_id": observation.observation_id,
                "reason": result.reason,
                "candidates": list(result.candidates),
                "best_grain": (result.grain.value
                              if result.grain is not None else None),
                "best_canonical_id": result.canonical_id,
                "match_score": result.match_score,
                "reviewed_at": now,
            }
            review_rows.append(review_row)

        resolutions.append(ObservationResolution(
            observation=observation, fact_row=fact_row, review_row=review_row))

    return WriteBatch(observation_rows=observation_rows, fact_rows=fact_rows,
                      review_rows=review_rows, resolutions=resolutions)
