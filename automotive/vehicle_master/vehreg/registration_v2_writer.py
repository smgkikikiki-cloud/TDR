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

Observation immutability (Phase 3 preflight fix): ``registration_observations_v2``
must never be silently overwritten. This module enforces the three-way rule
at the pure-logic level, before any live write is attempted:

* same observation id, same payload hash (within one batch, or against what
  is already persisted) -> idempotent no-op, exactly one row.
* same observation id, *different* payload hash -> a ``DriftConflict``,
  never resolved by "keep the first" - see ``build_batch``'s two-pass
  grouping and ``plan_observation_writes``.
* fact/review rows are derived and may always be regenerated/upserted for an
  id that is not in conflict - only the raw observation row itself is
  write-once.

The live CLIs never ``UPDATE``/``DELETE`` a row in ``registration_observations_v2``
(the DB grants back this up - see
``supabase/migration_v30_registration_v2_immutable_observations.sql``); they
only ever plain-``INSERT`` a row this module classified as ``to_insert``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

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
class DriftConflict:
    """The same observation id claimed by two or more different payload
    hashes - either within one batch (``source == "within_batch"``), or
    between this batch and what is already persisted
    (``source == "existing"``). Never resolved automatically: the ids
    involved are excluded from every row set this module proposes, and the
    live writer must block the whole run rather than guess which payload is
    authoritative."""

    observation_id: str
    payload_hashes: tuple[str, ...]
    source: str    # "within_batch" | "existing"
    units: float   # total units across every conflicting occurrence, so a
                    # disputed observation's volume stays visible in a
                    # summary rather than silently vanishing from the count.


@dataclass(frozen=True, slots=True)
class WriteBatch:
    observation_rows: list[dict[str, Any]]
    fact_rows: list[dict[str, Any]]
    review_rows: list[dict[str, Any]]
    resolutions: list[ObservationResolution]
    drift_conflicts: list[DriftConflict] = field(default_factory=list)

    @property
    def has_drift_conflicts(self) -> bool:
        return bool(self.drift_conflicts)

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

    @property
    def drift_conflict_units(self) -> float:
        """Units belonging to disputed observation ids - excluded from
        ``total_units``/``resolved_units``/``unresolved_units`` (those ids
        were never resolved at all), but still visible here so a summary
        never silently drops them."""
        return sum(c.units for c in self.drift_conflicts)

    def reconciles(self, tolerance: float = 0.001) -> bool:
        """Invariant 8: resolved + unresolved == observed, exactly, over the
        non-disputed subset of this batch. A batch with drift conflicts can
        still reconcile over what it did resolve - the conflicting units are
        a separate, explicitly-reported blocker, not a reconciliation
        failure in disguise."""
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
            "drift_conflicts": len(self.drift_conflicts),
            "drift_conflict_units": self.drift_conflict_units,
        }


def build_batch(observations: list[RegistrationObservation], resolver: Resolver,
                catalog: Catalog, *, now: str | None = None) -> WriteBatch:
    """Resolve every observation and shape the rows a live writer upserts.

    Deterministic given deterministic inputs: the same observation list and
    the same resolver/catalog state always produce the same rows in the same
    order - the ordering follows the input list, which callers should
    already be feeding in a stable order (see the backfill tool's period
    ordering) so a rerun's output is reproducible for diffing.

    Two passes, by observation id:

    1. Group ``observations`` by ``observation_id`` and look at each group's
       distinct ``payload_hash`` values. A group with exactly one distinct
       hash is a genuine repeat (a source returning a row twice, or a caller
       re-adding an already-processed page) - it is collapsed to its first
       occurrence, resolved once, and counted once. A group with *more than
       one* distinct hash is a within-batch drift conflict: none of its
       occurrences are resolved or written - the id is excluded from every
       row set this batch proposes and recorded in ``drift_conflicts``
       instead. This is the "must fail, not keep the first silently" rule;
       see ``plan_observation_writes`` for the second half (drift against
       what is already persisted).
    2. Resolve exactly once per surviving, non-conflicting observation id.
    """
    now = now or datetime.now(timezone.utc).isoformat()
    observation_rows: list[dict[str, Any]] = []
    fact_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    resolutions: list[ObservationResolution] = []
    drift_conflicts: list[DriftConflict] = []

    groups: dict[str, list[RegistrationObservation]] = {}
    for observation in observations:
        groups.setdefault(observation.observation_id, []).append(observation)

    for observation_id, group in groups.items():
        distinct_hashes = sorted({o.payload_hash for o in group})
        if len(distinct_hashes) > 1:
            drift_conflicts.append(DriftConflict(
                observation_id=observation_id, payload_hashes=tuple(distinct_hashes),
                source="within_batch", units=sum(o.units for o in group)))
            continue

        observation = group[0]
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

    drift_conflicts.sort(key=lambda c: c.observation_id)
    return WriteBatch(observation_rows=observation_rows, fact_rows=fact_rows,
                      review_rows=review_rows, resolutions=resolutions,
                      drift_conflicts=drift_conflicts)


# --------------------------------------------------------------------------
# Immutability: plan what to actually write against what is already
# persisted, and the global fail-closed apply gate.
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ObservationWritePlan:
    """What is actually safe to write to ``registration_observations_v2``.

    ``to_insert`` are plain ``INSERT``s - ids this batch produced that do not
    exist yet. ``unchanged_ids`` already exist with the identical payload
    hash - an idempotent no-op, nothing to write. ``drift_conflicts`` (this
    batch's own within-batch conflicts, plus any id whose persisted hash
    disagrees with this batch's) are never written - see
    ``registration_v2_writer``'s module docstring for the invariant this
    enforces.
    """

    to_insert: list[dict[str, Any]]
    unchanged_ids: list[str]
    drift_conflicts: list[DriftConflict]

    @property
    def is_blocked(self) -> bool:
        return bool(self.drift_conflicts)

    def summary(self) -> dict[str, Any]:
        return {
            "to_insert": len(self.to_insert),
            "unchanged": len(self.unchanged_ids),
            "drift_conflicts": len(self.drift_conflicts),
            "drift_conflict_units": sum(c.units for c in self.drift_conflicts),
            "is_blocked": self.is_blocked,
        }


def plan_observation_writes(
    batch: WriteBatch, existing_payload_hashes: Mapping[str, str] | None = None,
) -> ObservationWritePlan:
    """Classify every surviving observation id in ``batch`` against what is
    already persisted (``existing_payload_hashes``, an ``{observation_id:
    payload_hash}`` mapping the live caller fetched for exactly these ids -
    an empty/omitted mapping is correct for a fresh id set that has never
    been written before, e.g. the first run of a brand-new period).

    ``batch.drift_conflicts`` (within-batch conflicts, already excluded from
    every other row set) are carried through unchanged into the plan's own
    ``drift_conflicts`` - a caller only ever needs to look at the plan to
    know the full picture.
    """
    existing_payload_hashes = existing_payload_hashes or {}
    to_insert: list[dict[str, Any]] = []
    unchanged: list[str] = []
    against_existing: list[DriftConflict] = []

    for row in batch.observation_rows:
        observation_id = row["observation_id"]
        payload_hash = row["payload_hash"]
        existing_hash = existing_payload_hashes.get(observation_id)
        if existing_hash is None:
            to_insert.append(row)
        elif existing_hash == payload_hash:
            unchanged.append(observation_id)
        else:
            against_existing.append(DriftConflict(
                observation_id=observation_id,
                payload_hashes=tuple(sorted({payload_hash, existing_hash})),
                source="existing", units=row["units"]))

    to_insert.sort(key=lambda r: r["observation_id"])
    against_existing.sort(key=lambda c: c.observation_id)
    return ObservationWritePlan(
        to_insert=to_insert, unchanged_ids=sorted(unchanged),
        drift_conflicts=sorted(batch.drift_conflicts + against_existing,
                               key=lambda c: c.observation_id))


@dataclass(frozen=True, slots=True)
class WritesToApply:
    """The rows actually safe to send to the live writer this run - empty
    across the board whenever the plan is blocked. A global, whole-run
    fail-closed gate, the same pattern
    ``tdr_bridge.external_identity_sync.mutations_to_apply`` already
    established for Phase 1: any drift conflict anywhere in the run means
    zero writes this run, even for observation ids that are individually
    clean - never a partial apply that leaves some of a disputed run's
    volume silently written and some not."""

    observations: list[dict[str, Any]]
    facts: list[dict[str, Any]]
    reviews: list[dict[str, Any]]


def writes_to_apply(batch: WriteBatch, plan: ObservationWritePlan) -> WritesToApply:
    if plan.is_blocked:
        return WritesToApply(observations=[], facts=[], reviews=[])
    insert_ids = {row["observation_id"] for row in plan.to_insert}
    return WritesToApply(
        observations=plan.to_insert,
        facts=[r for r in batch.fact_rows
              if r["observation_id"] in insert_ids
              or r["observation_id"] in set(plan.unchanged_ids)],
        reviews=[r for r in batch.review_rows
                if r["observation_id"] in insert_ids
                or r["observation_id"] in set(plan.unchanged_ids)],
    )
