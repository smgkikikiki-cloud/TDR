"""The generic provider-adapter interface (SPEC §3).

An adapter turns one provider's native package into the engine's generic ``snapshot`` and nothing more: no matching
logic, no thresholds, no aliases. Two small interfaces keep the two sides of a comparison symmetric:

* ``SubjectSource`` — the provider side (Ice: model_groups, their monthly series, id_changes lineage).
* ``TargetSource``  — the TDR side (catalog targets, their registrations series, the existing mappings).

``assemble_snapshot`` joins them and validates the result against ``contract/v1/record.schema.json``, so an adapter that
produces something the engine would not accept fails here, at the boundary, with a message — not deep inside a decision.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from identity_resolution.contract import loader, schema_subset

CONTRACT_VERSION = "v1"


class SnapshotError(ValueError):
    """The assembled snapshot does not conform to record.schema.json (the message lists every violation)."""


@runtime_checkable
class SubjectSource(Protocol):
    """The provider side of a snapshot. Every method returns plain data shaped by record.schema.json."""

    provider_id: str

    def source_version(self) -> dict:
        """``{"label": str, "attributes": {...}}`` — a stable, human-traceable label (Ice: ``ice:2569-09:v3:M7.0``)."""

    def as_of_period(self) -> str:
        """Newest period the provider covers, Gregorian ISO ``YYYY-MM``."""

    def subjects(self) -> list[dict]:
        """``subject`` objects. Periods already Gregorian; sparse rows already made dense (zero-fill only inside declared coverage)."""

    def lineage(self) -> dict:
        """``lineage_input``: ``source_present``, ``declared_identity_change``, ``events`` and optionally ``applied_event_keys``."""


@runtime_checkable
class TargetSource(Protocol):
    """The TDR side of a snapshot."""

    def targets(self) -> list[dict]:
        """``target`` objects."""

    def existing_mappings(self) -> list[dict]:
        """``existing_mapping`` objects (the persisted state the engine must respect)."""


def assemble_snapshot(subjects: SubjectSource, targets: TargetSource, *, policy_version: str, version: str = CONTRACT_VERSION) -> dict:
    snapshot: dict[str, Any] = {
        "contract_version": version,
        "policy_version": policy_version,
        "provider": subjects.provider_id,
        "source_version": subjects.source_version(),
        "as_of_period": subjects.as_of_period(),
        "subjects": subjects.subjects(),
        "targets": targets.targets(),
        "existing_mappings": targets.existing_mappings(),
        "lineage": subjects.lineage(),
    }
    validate_snapshot(snapshot, version)
    return snapshot


def validate_snapshot(snapshot: dict, version: str = CONTRACT_VERSION) -> None:
    schemas = loader.load_schema_registry(version)
    root = schemas["record.schema.json"]
    errors = schema_subset.validate(snapshot, root["$defs"]["snapshot"], registry=schemas, root=root)
    if errors:
        raise SnapshotError("; ".join(errors))
