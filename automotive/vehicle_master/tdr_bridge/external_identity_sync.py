"""Registry -> `canonical_object_map` reconciliation and sync — Phase 1 completion.

This module answers, for every Git-pinned binding
(`tdr_bridge.external_identity_registry`), "does the live operational bridge
(`canonical_object_map`) already reflect this?" and, only for the one safe
case (the operational row is simply absent), can create it.

Design goal: the classification/decision logic here is pure — it takes
already-fetched data (`OperationalRow` values, source-existence booleans) and
returns classifications and a list of proposed mutations, all as plain data.
It performs no I/O itself and can be fully exercised with synthetic fixtures.
The live Supabase adapter (`SupabaseRestClient`) is a thin, separate layer
that fetches that data and, only when explicitly asked, executes the
mutations this module proposed — never anything this module didn't propose.

Reconciliation key: `(source_table, source_id, canonical_entity_type)` —
exactly `canonical_object_map`'s own key (migration_v12's
`unique (source_table, source_id, canonical_entity_type)`), and exactly what
the registry's own `(namespace, external_entity_type, external_id,
canonical_entity_type)` key reduces to once `external_entity_type` is mapped
to its Supabase table name. The same external UUID may legitimately have
bindings at more than one canonical_entity_type (a different key each time);
that is not a conflict — see `external_identity_registry.py`'s
`comparability_key`.

Safety boundary (the entire point of this module): the sync writer may only
ever create a `canonical_object_map` row for a key the Git registry actually
contains. It never touches a row whose key is not in the registry — not a
review-state row (`unmatched`/`ambiguous`), not a Phase-E projection-owned
row, not an operational-only `verified` row of unknown origin, not a
retired-operational-only row. It never *updates* an existing row, even one
that conflicts with Git — a conflict is reported, never silently resolved,
never overwritten. See `classify_binding()` and `SAFE_MUTATION_STATES` below.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from tdr_bridge.external_identity_registry import (
    ExternalIdentityBinding,
    RegistryDocument,
)

#: Registry external_entity_type -> canonical_object_map.source_table.
#: The inverse of lib/external-identity/mechanism-adapters.ts's
#: SOURCE_TABLE_TO_EXTERNAL_ENTITY_TYPE — keep both in sync.
EXTERNAL_ENTITY_TYPE_TO_SOURCE_TABLE = {
    "brand": "brands",
    "model": "models",
    "model_powertrain": "model_powertrains",
    "trim": "trims",
}

#: What a Phase-E-generated canonical_object_map row looks like — see
#: apply_vehicle_serving_projection in supabase/migration_v14_serving_projection.sql.
PHASE_E_VERIFIED_BY = "phase-e-publisher"
PHASE_E_MATCH_BASIS_VALUE = "phase-e canonical serving projection"

#: What this module's own writes look like, so a future operator can always
#: tell a row was projected from the Git registry rather than created by a
#: human directly in Supabase or by the Phase-E publisher.
SYNC_MATCH_BASIS_VALUE = "external_identity_registry_sync"
SYNC_ACTOR = "external-identity-registry-sync"

#: Desired canonical_object_map.status for each registry binding state.
DESIRED_STATUS_BY_BINDING_STATE = {"active": "verified", "retired": "retired"}


@dataclass(frozen=True, slots=True)
class OperationalRow:
    """One `canonical_object_map` row, as read live. Field names/shapes
    mirror the table exactly (supabase/migration_v12_canonical_write_pipeline.sql)."""

    source_table: str
    source_id: str
    canonical_entity_type: str
    canonical_id: str | None
    status: str
    verified_by: str | None = None
    verified_at: str | None = None
    match_basis: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.source_table, self.source_id, self.canonical_entity_type)

    @property
    def is_phase_e_owned(self) -> bool:
        return (
            self.verified_by == PHASE_E_VERIFIED_BY
            or (isinstance(self.match_basis, dict) and self.match_basis.get("basis") == PHASE_E_MATCH_BASIS_VALUE)
        )

    @property
    def is_registry_sync_owned(self) -> bool:
        return isinstance(self.match_basis, dict) and self.match_basis.get("basis") == SYNC_MATCH_BASIS_VALUE


def binding_key(binding: ExternalIdentityBinding) -> tuple[str, str, str]:
    """The registry binding's key, expressed in canonical_object_map's own
    (source_table, source_id, canonical_entity_type) shape."""
    source_table = EXTERNAL_ENTITY_TYPE_TO_SOURCE_TABLE.get(binding.external_entity_type)
    if source_table is None:
        raise ValueError(f"no source_table mapping for external_entity_type {binding.external_entity_type!r}")
    return (source_table, binding.external_id, binding.canonical_entity_type)


BindingClassification = str  # in_sync | missing_operational_row | canonical_target_conflict
                              # | operational_status_conflict | missing_external_source_row

#: Classifications the sync writer may act on — everything else is a
#: blocker, reported and never auto-resolved.
SAFE_MUTATION_CLASSIFICATIONS = frozenset({"missing_operational_row"})

BLOCKER_CLASSIFICATIONS = frozenset({
    "canonical_target_conflict", "operational_status_conflict", "missing_external_source_row",
})


@dataclass(frozen=True, slots=True)
class BindingReconciliation:
    binding: ExternalIdentityBinding
    key: tuple[str, str, str]
    classification: BindingClassification
    desired_status: str
    operational_row: OperationalRow | None
    detail: str


def classify_binding(
    binding: ExternalIdentityBinding,
    operational_row: OperationalRow | None,
    *,
    source_row_exists: bool,
) -> BindingReconciliation:
    key = binding_key(binding)
    desired_status = DESIRED_STATUS_BY_BINDING_STATE[binding.state]

    if not source_row_exists:
        return BindingReconciliation(
            binding=binding, key=key, classification="missing_external_source_row",
            desired_status=desired_status, operational_row=operational_row,
            detail=(
                f"legacy source row {binding.external_id!r} not found in "
                f"{EXTERNAL_ENTITY_TYPE_TO_SOURCE_TABLE[binding.external_entity_type]!r} — "
                f"refusing to sync a binding whose external source no longer exists"
            ),
        )

    if operational_row is None:
        return BindingReconciliation(
            binding=binding, key=key, classification="missing_operational_row",
            desired_status=desired_status, operational_row=None,
            detail=f"no canonical_object_map row exists for key {key!r}; safe to create",
        )

    if operational_row.canonical_id != binding.canonical_id:
        return BindingReconciliation(
            binding=binding, key=key, classification="canonical_target_conflict",
            desired_status=desired_status, operational_row=operational_row,
            detail=(
                f"operational canonical_id {operational_row.canonical_id!r} != "
                f"registry canonical_id {binding.canonical_id!r} — not auto-resolved"
            ),
        )

    if operational_row.status != desired_status:
        return BindingReconciliation(
            binding=binding, key=key, classification="operational_status_conflict",
            desired_status=desired_status, operational_row=operational_row,
            detail=(
                f"operational status {operational_row.status!r} != desired {desired_status!r} "
                f"for registry state {binding.state!r} — not auto-resolved"
            ),
        )

    return BindingReconciliation(
        binding=binding, key=key, classification="in_sync",
        desired_status=desired_status, operational_row=operational_row,
        detail="operational row matches the registry binding",
    )


def classify_bindings(
    doc: RegistryDocument,
    operational_by_key: dict[tuple[str, str, str], OperationalRow],
    source_row_exists: dict[tuple[str, str], bool],
) -> list[BindingReconciliation]:
    results = []
    for binding in doc.bindings:
        source_table = EXTERNAL_ENTITY_TYPE_TO_SOURCE_TABLE.get(binding.external_entity_type)
        exists = source_row_exists.get((source_table, binding.external_id), False) if source_table else False
        results.append(classify_binding(
            binding,
            operational_by_key.get(binding_key(binding)) if source_table else None,
            source_row_exists=exists,
        ))
    # Deterministic order, independent of dict/input ordering.
    results.sort(key=lambda r: r.key)
    return results


OperationalOnlyClassification = str
# review_state_unmatched | review_state_ambiguous | retired_operational_only
# | phase_e_projection_owned | registry_sync_owned | verified_ownership_unknown
# | unknown_status


@dataclass(frozen=True, slots=True)
class OperationalOnlyRow:
    row: OperationalRow
    classification: OperationalOnlyClassification


def classify_operational_only_row(row: OperationalRow) -> OperationalOnlyClassification:
    if row.status == "unmatched":
        return "review_state_unmatched"
    if row.status == "ambiguous":
        return "review_state_ambiguous"
    if row.status == "retired":
        return "retired_operational_only"
    if row.status == "verified":
        if row.is_registry_sync_owned:
            # Should not normally appear as "operational-only" (its key
            # should match a registry binding), but classify honestly rather
            # than crash if the registry and this row's key have since
            # diverged (e.g. the binding was removed from Git after sync).
            return "registry_sync_owned"
        if row.is_phase_e_owned:
            return "phase_e_projection_owned"
        return "verified_ownership_unknown"
    return "unknown_status"


def classify_operational_only(
    operational_rows: list[OperationalRow],
    registry_keys: set[tuple[str, str, str]],
) -> list[OperationalOnlyRow]:
    results = [
        OperationalOnlyRow(row=row, classification=classify_operational_only_row(row))
        for row in operational_rows
        if row.key not in registry_keys
    ]
    results.sort(key=lambda r: r.row.key)
    return results


@dataclass(frozen=True, slots=True)
class ProposedMutation:
    """One safe, additive `canonical_object_map` insert this module proposes.
    The live adapter is the only thing that may turn this into a write, and
    only ever inserts exactly this payload — never an update, never a
    payload constructed any other way."""

    key: tuple[str, str, str]
    payload: dict[str, Any]


def propose_mutation(reconciliation: BindingReconciliation, *, now: str | None = None) -> ProposedMutation | None:
    """A mutation is proposed only for `missing_operational_row` — the one
    classification where nothing existing is touched, only created. Every
    other classification (including every blocker) proposes nothing."""
    if reconciliation.classification not in SAFE_MUTATION_CLASSIFICATIONS:
        return None
    binding = reconciliation.binding
    source_table, source_id, canonical_entity_type = reconciliation.key
    now = now or datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "source_table": source_table,
        "source_id": source_id,
        "canonical_entity_type": canonical_entity_type,
        "canonical_id": binding.canonical_id,
        "status": reconciliation.desired_status,
        # Original review provenance is preserved as-is — this write is a
        # projection of an existing decision, not a new review. A binding
        # missing verified_at/verified_by for an active+explicit_review
        # state is already rejected by validate_registry(), so this is safe
        # for status='verified'; a retired binding may legitimately have
        # neither (canonical_object_map does not require them off 'verified').
        "verified_by": binding.verified_by,
        "verified_at": binding.verified_at,
        # Synchronization provenance is kept distinct from the above, in its
        # own object — never overwriting verified_by/verified_at as if this
        # tool performed the original review.
        "match_basis": {
            "basis": SYNC_MATCH_BASIS_VALUE,
            "registry_namespace": binding.namespace,
            "registry_external_entity_type": binding.external_entity_type,
            "registry_authority_basis": binding.authority_basis,
            "registry_state": binding.state,
            "synced_at": now,
            "synced_by": SYNC_ACTOR,
        },
        "notes": binding.notes or None,
    }
    return ProposedMutation(key=reconciliation.key, payload=payload)


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    binding_results: list[BindingReconciliation]
    operational_only: list[OperationalOnlyRow]
    proposed_mutations: list[ProposedMutation]

    @property
    def has_blockers(self) -> bool:
        return any(r.classification in BLOCKER_CLASSIFICATIONS for r in self.binding_results)

    @property
    def is_fully_reconciled(self) -> bool:
        """True when every registry binding is in_sync and no mutation is
        pending — the state a successful `--apply` should converge to."""
        return all(r.classification == "in_sync" for r in self.binding_results)

    def summary(self) -> dict[str, Any]:
        by_classification: dict[str, int] = {}
        for r in self.binding_results:
            by_classification[r.classification] = by_classification.get(r.classification, 0) + 1
        operational_only_by_classification: dict[str, int] = {}
        for r in self.operational_only:
            operational_only_by_classification[r.classification] = (
                operational_only_by_classification.get(r.classification, 0) + 1
            )
        return {
            "bindings_total": len(self.binding_results),
            "bindings_by_classification": dict(sorted(by_classification.items())),
            "operational_only_total": len(self.operational_only),
            "operational_only_by_classification": dict(sorted(operational_only_by_classification.items())),
            "proposed_mutations": len(self.proposed_mutations),
            "has_blockers": self.has_blockers,
            "is_fully_reconciled": self.is_fully_reconciled,
        }


def reconcile(
    doc: RegistryDocument,
    operational_rows: list[OperationalRow],
    source_row_exists: dict[tuple[str, str], bool],
) -> ReconciliationReport:
    """Pure reconciliation: takes already-fetched data, returns
    classifications and proposed mutations. No I/O. Deterministic — same
    inputs always produce the same report, regardless of input list order."""
    operational_by_key = {row.key: row for row in operational_rows}
    binding_results = classify_bindings(doc, operational_by_key, source_row_exists)
    registry_keys = {r.key for r in binding_results}
    operational_only = classify_operational_only(operational_rows, registry_keys)
    proposed_mutations = [m for m in (propose_mutation(r) for r in binding_results) if m is not None]
    return ReconciliationReport(
        binding_results=binding_results,
        operational_only=operational_only,
        proposed_mutations=proposed_mutations,
    )
