"""DLT v2 dual-run parity: v1 production registration data vs v2 shadow output.

Pure computation only - every function here takes already-fetched rows (the
live CLI, ``tools/registration_v2_parity.py``, does the actual Supabase
reads) and returns plain data. No I/O, fully exercisable with synthetic
fixtures.

The central distinction this module is built around, per the packet's own
brief: **a mapping disagreement is not automatically a unit mismatch.** The
one hard invariant is source-volume reconciliation (Invariant 2/8) - a pair
of rows whose canonical identity opinions differ is still perfectly fine as
long as neither side silently dropped or fabricated units. So this module
keeps four questions strictly separate and never lets one stand in for
another:

* **volume parity** - do v1 and v2 agree on total units, by period and by
  registration type? (``volume_parity``)
* **identity parity** - for rows both sides could compare, do they agree on
  *which canonical model* the units belong to? (``classify_pairs``)
* **resolution-coverage difference** - did one side resolve a row the other
  side could not, at all? (a ``resolution_coverage_v1_only`` /
  ``resolution_coverage_v2_only`` classification, not folded into
  "disagreement")
* **grain difference** - did v2 stop at a shallower grain than v1's
  model-level mapping implies, on a row where the two sides otherwise agree
  about which car it is? (``grain_difference_v2_coarser``)

v1 rows are the legacy Supabase ``public.registrations`` table, addressed by
a legacy ``models.id`` uuid via ``model_id``, crosswalked to a canonical text
id only through ``current_vehicle_models.tdr_model_id`` (Mechanism A's own
release-build crosswalk) - a row whose ``model_id`` is not present in that
crosswalk is reported as ``v1_uncrosswalked``, a distinct bucket from either
side being outright unresolved, because it names a different gap (a
Mechanism-A crosswalk gap, not a DLT resolution gap).

v1<->v2 pairing uses the exact backfill identity, not a fuzzy label match:
``vehreg.registration_observation.from_legacy_registration_row`` sets a v2
observation's ``source_ref`` to the legacy row's own ``id`` uuid, so a v2
observation of ``source_kind == "legacy_registrations_backfill"`` names
exactly the v1 row it was built from. A v1 row with no matching v2
observation has simply not been backfilled yet - not a disagreement, a
coverage gap the report names honestly (``legacy_rows_missing_v2_backfill``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

#: Deterministic; matches vehreg.registration_observation.LEGACY_REGISTRATIONS_BACKFILL.
LEGACY_REGISTRATIONS_BACKFILL = "legacy_registrations_backfill"


@dataclass(frozen=True, slots=True)
class LegacyRegistrationRow:
    """One row of the live ``public.registrations`` table, as read."""

    id: str
    period: str            # 'YYYY-MM'
    registration_type: str
    brand_name_raw: str
    model_name_raw: str
    model_id: Optional[str]     # legacy public.models.id uuid, or None
    units: float


@dataclass(frozen=True, slots=True)
class V2ObservationRow:
    observation_id: str
    source_kind: str
    source_ref: str
    period: str
    registration_type: str
    units: float


@dataclass(frozen=True, slots=True)
class V2FactRow:
    observation_id: str
    canonical_id: str
    grain: str              # 'BRAND' | 'MODEL' | 'VARIANT'
    units: float


def model_component(canonical_id: str) -> str:
    """The model-level prefix of any canonical id: a MODEL id is already
    ``brand.model``; a VARIANT id (``brand.model.generation.variant``) is
    truncated to the same two segments. A BRAND id (one segment) is
    returned unchanged - it is never comparable to a model."""
    parts = canonical_id.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else canonical_id


# --------------------------------------------------------------------------
# Volume parity
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class VolumeParity:
    key: str
    v1_units: float
    v2_units: float

    @property
    def difference(self) -> float:
        return self.v2_units - self.v1_units

    @property
    def matches(self) -> bool:
        return abs(self.difference) <= 0.001


def _sum_by(rows: Iterable[Any], attr: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        key = getattr(row, attr)
        out[key] = out.get(key, 0.0) + row.units
    return out


def volume_parity(legacy_rows: Iterable[LegacyRegistrationRow],
                  v2_observations: Iterable[V2ObservationRow], *,
                  by: str) -> list[VolumeParity]:
    """``by`` is ``"period"`` or ``"registration_type"``. Every v2
    observation counts here regardless of source_kind - a DLT-ingested
    future month and a backfilled historical one are both real v2 volume."""
    if by not in ("period", "registration_type"):
        raise ValueError("by must be 'period' or 'registration_type'")
    v1_totals = _sum_by(legacy_rows, by)
    v2_totals = _sum_by(v2_observations, by)
    keys = sorted(set(v1_totals) | set(v2_totals))
    return [VolumeParity(key=k, v1_units=v1_totals.get(k, 0.0),
                         v2_units=v2_totals.get(k, 0.0)) for k in keys]


# --------------------------------------------------------------------------
# Coverage (resolved vs unresolved) parity
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CoverageParity:
    v1_total_units: float
    v1_mapped_units: float
    v2_total_units: float
    v2_resolved_units: float

    @property
    def v1_mapped_pct(self) -> float:
        return (100.0 * self.v1_mapped_units / self.v1_total_units
               if self.v1_total_units else 0.0)

    @property
    def v2_resolved_pct(self) -> float:
        return (100.0 * self.v2_resolved_units / self.v2_total_units
               if self.v2_total_units else 0.0)


def coverage_parity(legacy_rows: Iterable[LegacyRegistrationRow],
                    v2_observations: Iterable[V2ObservationRow],
                    v2_facts: Iterable[V2FactRow]) -> CoverageParity:
    legacy_rows = list(legacy_rows)
    v2_observations = list(v2_observations)
    v1_total = sum(r.units for r in legacy_rows)
    v1_mapped = sum(r.units for r in legacy_rows if r.model_id)
    v2_total = sum(o.units for o in v2_observations)
    v2_resolved = sum(f.units for f in v2_facts)
    return CoverageParity(v1_total_units=v1_total, v1_mapped_units=v1_mapped,
                          v2_total_units=v2_total, v2_resolved_units=v2_resolved)


def grain_distribution(v2_facts: Iterable[V2FactRow]) -> dict[str, float]:
    out: dict[str, float] = {}
    for fact in v2_facts:
        out[fact.grain] = out.get(fact.grain, 0.0) + fact.units
    return out


# --------------------------------------------------------------------------
# Identity parity: exact v1<->v2 pairing by backfill provenance
# --------------------------------------------------------------------------
PairClassification = str
#: agree | identity_disagreement | grain_difference_v2_coarser
#: | resolution_coverage_v1_only | resolution_coverage_v2_only
#: | v1_uncrosswalked | both_unresolved


@dataclass(frozen=True, slots=True)
class PairResult:
    legacy_id: str
    classification: PairClassification
    units: float
    v1_canonical_model: Optional[str]
    v2_canonical_id: Optional[str]
    v2_grain: Optional[str]


def _classify_pair(legacy_row: LegacyRegistrationRow,
                   crosswalk: Mapping[str, str],
                   v2_fact: Optional[V2FactRow]) -> PairResult:
    v1_canonical_model: Optional[str] = None
    v1_uncrosswalked = False
    if legacy_row.model_id:
        v1_canonical_model = crosswalk.get(legacy_row.model_id)
        if v1_canonical_model is None:
            v1_uncrosswalked = True

    v2_canonical_id = v2_fact.canonical_id if v2_fact else None
    v2_grain = v2_fact.grain if v2_fact else None

    if v1_uncrosswalked:
        classification = "v1_uncrosswalked"
    elif v1_canonical_model is not None and v2_fact is not None:
        if v2_grain == "BRAND":
            v1_brand = v1_canonical_model.split(".")[0]
            classification = ("grain_difference_v2_coarser"
                             if v2_canonical_id == v1_brand
                             else "identity_disagreement")
        else:
            classification = ("agree" if model_component(v2_canonical_id)
                             == v1_canonical_model else "identity_disagreement")
    elif v1_canonical_model is not None and v2_fact is None:
        classification = "resolution_coverage_v1_only"
    elif v1_canonical_model is None and v2_fact is not None:
        classification = "resolution_coverage_v2_only"
    else:
        classification = "both_unresolved"

    return PairResult(legacy_id=legacy_row.id, classification=classification,
                      units=legacy_row.units, v1_canonical_model=v1_canonical_model,
                      v2_canonical_id=v2_canonical_id, v2_grain=v2_grain)


@dataclass(frozen=True, slots=True)
class PairingResult:
    classifications: list[PairResult]
    legacy_rows_missing_v2_backfill: list[str]      # legacy ids
    v2_orphaned_backfill_observations: list[str]    # observation ids


def classify_pairs(legacy_rows: Iterable[LegacyRegistrationRow],
                   v2_observations: Iterable[V2ObservationRow],
                   v2_facts_by_observation_id: Mapping[str, V2FactRow],
                   crosswalk: Mapping[str, str]) -> PairingResult:
    """Pair every v1 row with the v2 observation ``from_legacy_registration_row``
    built from it (same legacy row id as ``source_ref``), then classify.

    A v1 row with no such v2 observation has not been backfilled yet - listed
    separately, never silently folded into ``both_unresolved`` (which means
    something both sides *tried and failed*, not "v2 hasn't looked yet").
    """
    backfill_by_legacy_id = {
        o.source_ref: o for o in v2_observations
        if o.source_kind == LEGACY_REGISTRATIONS_BACKFILL
    }
    legacy_ids = {r.id for r in legacy_rows}

    classifications: list[PairResult] = []
    missing: list[str] = []
    for row in legacy_rows:
        v2_obs = backfill_by_legacy_id.get(row.id)
        if v2_obs is None:
            missing.append(row.id)
            continue
        fact = v2_facts_by_observation_id.get(v2_obs.observation_id)
        classifications.append(_classify_pair(row, crosswalk, fact))

    orphaned = sorted(
        o.observation_id for ref, o in backfill_by_legacy_id.items()
        if ref not in legacy_ids
    )
    classifications.sort(key=lambda c: c.legacy_id)
    return PairingResult(classifications=classifications,
                         legacy_rows_missing_v2_backfill=sorted(missing),
                         v2_orphaned_backfill_observations=orphaned)


# --------------------------------------------------------------------------
# Duplicate / double-counting and reconciliation-failure detectors
# --------------------------------------------------------------------------
def find_duplicate_source_refs(
    v2_observations: Iterable[V2ObservationRow],
) -> list[tuple[str, str]]:
    """(source_kind, source_ref) pairs claimed by more than one observation
    id. Should structurally never happen -
    ``registration_observation.observation_id`` is a pure function of
    exactly this pair - so a non-empty result names a real bug (a hash
    collision, or a caller that bypassed the adapter), not a business-logic
    disagreement."""
    seen: dict[tuple[str, str], set[str]] = {}
    for o in v2_observations:
        seen.setdefault((o.source_kind, o.source_ref), set()).add(o.observation_id)
    return sorted(key for key, ids in seen.items() if len(ids) > 1)


def find_reconciliation_failures(
    legacy_rows: Iterable[LegacyRegistrationRow],
    v2_observations: Iterable[V2ObservationRow], *, tolerance: float = 0.001,
) -> list[dict[str, Any]]:
    """Paired v1/v2 rows whose units disagree. The backfill adapter copies
    units verbatim (Invariant 1: no reinterpretation), so any disagreement
    here means the v1 data changed since the backfill last ran against it -
    a real drift to re-run backfill against, not a resolution question."""
    v2_by_legacy_id = {
        o.source_ref: o for o in v2_observations
        if o.source_kind == LEGACY_REGISTRATIONS_BACKFILL
    }
    failures: list[dict[str, Any]] = []
    for row in legacy_rows:
        v2_obs = v2_by_legacy_id.get(row.id)
        if v2_obs is not None and abs(v2_obs.units - row.units) > tolerance:
            failures.append({
                "legacy_id": row.id, "v1_units": row.units,
                "v2_units": v2_obs.units,
            })
    return sorted(failures, key=lambda f: f["legacy_id"])


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ParityReport:
    volume_by_period: list[VolumeParity]
    volume_by_registration_type: list[VolumeParity]
    coverage: CoverageParity
    grain_distribution: dict[str, float]
    pairing: PairingResult
    duplicate_source_refs: list[tuple[str, str]]
    reconciliation_failures: list[dict[str, Any]]

    def summary(self) -> dict[str, Any]:
        by_classification: dict[str, int] = {}
        units_by_classification: dict[str, float] = {}
        for c in self.pairing.classifications:
            by_classification[c.classification] = (
                by_classification.get(c.classification, 0) + 1)
            units_by_classification[c.classification] = (
                units_by_classification.get(c.classification, 0.0) + c.units)
        volume_mismatches_by_period = [
            v.key for v in self.volume_by_period if not v.matches]
        volume_mismatches_by_registration_type = [
            v.key for v in self.volume_by_registration_type if not v.matches]
        return {
            "coverage": {
                "v1_total_units": self.coverage.v1_total_units,
                "v1_mapped_units": self.coverage.v1_mapped_units,
                "v1_mapped_pct": round(self.coverage.v1_mapped_pct, 2),
                "v2_total_units": self.coverage.v2_total_units,
                "v2_resolved_units": self.coverage.v2_resolved_units,
                "v2_resolved_pct": round(self.coverage.v2_resolved_pct, 2),
            },
            "grain_distribution": dict(sorted(self.grain_distribution.items())),
            "pairs_total": len(self.pairing.classifications),
            "pairs_by_classification": dict(sorted(by_classification.items())),
            "units_by_classification": dict(sorted(units_by_classification.items())),
            "legacy_rows_missing_v2_backfill": len(
                self.pairing.legacy_rows_missing_v2_backfill),
            "v2_orphaned_backfill_observations": len(
                self.pairing.v2_orphaned_backfill_observations),
            "duplicate_source_refs": len(self.duplicate_source_refs),
            "reconciliation_failures": len(self.reconciliation_failures),
            "volume_mismatches_by_period": volume_mismatches_by_period,
            "volume_mismatches_by_registration_type":
                volume_mismatches_by_registration_type,
            "is_clean": (
                not self.duplicate_source_refs
                and not self.reconciliation_failures
                and not volume_mismatches_by_period
                and not volume_mismatches_by_registration_type
            ),
        }


def build_parity_report(
    legacy_rows: Iterable[LegacyRegistrationRow],
    v2_observations: Iterable[V2ObservationRow],
    v2_facts: Iterable[V2FactRow],
    crosswalk: Mapping[str, str],
) -> ParityReport:
    legacy_rows = list(legacy_rows)
    v2_observations = list(v2_observations)
    v2_facts = list(v2_facts)
    facts_by_observation_id = {f.observation_id: f for f in v2_facts}

    return ParityReport(
        volume_by_period=volume_parity(legacy_rows, v2_observations, by="period"),
        volume_by_registration_type=volume_parity(
            legacy_rows, v2_observations, by="registration_type"),
        coverage=coverage_parity(legacy_rows, v2_observations, v2_facts),
        grain_distribution=grain_distribution(v2_facts),
        pairing=classify_pairs(legacy_rows, v2_observations,
                               facts_by_observation_id, crosswalk),
        duplicate_source_refs=find_duplicate_source_refs(v2_observations),
        reconciliation_failures=find_reconciliation_failures(
            legacy_rows, v2_observations),
    )
