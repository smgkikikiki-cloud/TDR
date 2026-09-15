"""Git-backed external-identity registry — Phase 1B.

This module owns the canonical, pinned mapping from an external legacy
identity (today: a `legacy_tdr` Supabase UUID) to a canonical Vehicle Master
entity. It is deliberately small and deliberately not the same thing as
either of the two mechanisms it sits alongside:

* Mechanism A (`tdr_bridge/release.py`'s release-build crosswalk, surfaced
  live via Supabase `current_vehicle_brands`/`current_vehicle_models`) is a
  *derived* mapping, recomputed from names/aliases/`crosswalk_overrides.json`
  on every release. It owns no canonical binding truth and nothing here
  copies its links in.
* Mechanism B (`canonical_object_map`) remains the operational bridge for
  the Phase-C write gate, review states (`unmatched`/`ambiguous`), and
  Phase-E serving-projection bookkeeping. A `canonical_object_map` row with
  `status = 'verified'` is an *operational* trust statement, not proof of a
  human identity review — see "Phase-E projection-owned rows" below. This
  module does not read from or write to Supabase at all.

This registry holds only bindings that are non-reconstructible identity
*decisions*: something a human (or an equivalent, named, one-off review
process) looked at directly and pinned, which nothing else in the system
could regenerate from names, aliases, or a serving publisher's own output.

Everything else is deliberately excluded from this registry, on purpose,
in Phase 1B:

* Mechanism A's derived crosswalk links (currently 383 Brand+Model links) —
  agreement with a canonical name/alias/reviewed override is not a pinned
  decision; see docs/vehicle-platform/EXTERNAL_IDENTITY_PERSISTENCE.md.
* `canonical_object_map` rows whose `match_basis.basis` is
  `"phase-e canonical serving projection"` and `verified_by` is
  `"phase-e-publisher"` — these are generated deterministically by
  `apply_vehicle_serving_projection` (`supabase/migration_v14_serving_projection.sql`)
  every time it projects a legacy child row from canonical state. They are
  operationally authoritative for that projection and fully reconstructible
  from canonical state + the publisher; they are projection-owned, not
  pinned, and must not be copied into this registry merely because their
  `status` says `verified`. This module does not attempt to detect or filter
  such rows automatically — it simply never seeds them, because import into
  this registry is always a deliberate, reviewed act (see
  `integration_data/external_identity_registry.json`'s own seed history).
* `canonical_object_map` rows with `status` in (`unmatched`, `ambiguous`) —
  those are review/workflow states, not canonical binding truth. This
  registry's `state` vocabulary is intentionally narrower (`active` /
  `retired` only) so an unresolved or contested mapping structurally cannot
  be stored here as if it were settled.
* `integration_data/crosswalk_overrides.json` entries — these remain
  Mechanism A matching inputs. A reviewed override is still a name/alias
  disambiguation hint fed to a derived, recomputed-every-release mapping; it
  is not, by itself, a pinned canonical identity decision. A later packet
  may individually review and promote specific overrides if appropriate —
  none are auto-promoted here.

No production consumer reads this registry yet. See
docs/vehicle-platform/EXTERNAL_IDENTITY_PERSISTENCE.md for the full
ownership model and docs/vehicle-platform/status/CURRENT.md for current
migration status.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json
import uuid

from vehreg.catalog import Catalog

SCHEMA_VERSION = 1

DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1] / "integration_data" / "external_identity_registry.json"
)

#: Mirrors lib/external-identity/types.ts's ExternalNamespace. Only one
#: namespace exists today; this registry does not speculatively support any
#: other one.
VALID_NAMESPACES = frozenset({"legacy_tdr"})

#: Mirrors lib/external-identity/types.ts's ExternalEntityType exactly —
#: keep these two vocabularies in sync if either changes.
VALID_EXTERNAL_ENTITY_TYPES = frozenset({"brand", "model", "model_powertrain", "trim"})

#: Mirrors lib/external-identity/types.ts's CanonicalEntityType exactly, and
#: canonical_object_map's own check constraint
#: (supabase/migration_v12_canonical_write_pipeline.sql). "variant" is
#: deliberately not renamed to "Configuration" — see MASTER_ARCHITECTURE.md.
VALID_CANONICAL_ENTITY_TYPES = frozenset({"brand", "model", "generation", "variant", "market_trim"})

#: Binding states. Deliberately narrower than Mechanism B's `status` column:
#: `unmatched` and `ambiguous` are review/workflow states, not canonical
#: binding truth, and must never be representable here.
VALID_STATES = frozenset({"active", "retired"})

#: What justifies a binding's presence in this registry. Phase 1B seeds and
#: accepts exactly one basis: a deliberate, non-reconstructible human/named
#: review. "derived" (Mechanism A) and "projection_owned" (Phase-E) are
#: real, documented concepts (see EXTERNAL_IDENTITY_PERSISTENCE.md) but are
#: intentionally NOT valid values here — a record asserting either would be
#: a category error, not a registry entry, so the validator rejects it
#: rather than accepting and merely labeling it.
VALID_AUTHORITY_BASES = frozenset({"explicit_review"})

#: Which Catalog dict a canonical_entity_type resolves against.
_CATALOG_ATTR_BY_ENTITY_TYPE = {
    "brand": "brands",
    "model": "models",
    "generation": "generations",
    "variant": "variants",
    "market_trim": "trims",
}


class RegistryError(ValueError):
    """A structurally malformed registry file (bad JSON, missing/wrong-typed
    required fields). Distinct from a semantic validation failure (see
    `validate_registry`, which returns a list of problems instead of raising,
    so every problem in a file can be reported at once rather than stopping
    at the first one)."""


@dataclass(frozen=True, slots=True)
class ExternalIdentityBinding:
    """One pinned external-identity decision. See module docstring for what
    belongs here versus what deliberately does not."""

    namespace: str
    external_entity_type: str
    external_id: str
    canonical_entity_type: str
    canonical_id: str
    state: str
    authority_basis: str
    verified_at: str | None = None
    verified_by: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    imported_at: str | None = None
    imported_by: str | None = None

    @property
    def comparability_key(self) -> tuple[str, str, str, str]:
        """The registry's binding key (task requirement §6):
        (namespace, external_entity_type, external_id, canonical_entity_type).
        At most one *current* binding may exist per key — see
        `validate_registry`'s duplicate-key check. This is deliberately NOT
        globally unique on canonical_entity_type + canonical_id: multiple
        external identities (and, in the future, namespaces) may legitimately
        point at the same canonical entity, and one external ID may
        legitimately have bindings at more than one canonical entity type
        (e.g. a legacy model row pinned as evidence for both a canonical
        model and a canonical generation) — those are different keys, not
        conflicts. Do not copy canonical_object_map's global
        verified-target uniqueness index into this registry."""
        return (self.namespace, self.external_entity_type, self.external_id, self.canonical_entity_type)


@dataclass(frozen=True, slots=True)
class RegistryDocument:
    schema_version: int
    bindings: tuple[ExternalIdentityBinding, ...]


def _require_str(obj: dict, key: str, *, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value:
        raise RegistryError(f"{where}: {key!r} must be a non-empty string, got {value!r}")
    return value


def _optional_str(obj: dict, key: str) -> str | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RegistryError(f"binding {obj.get('external_id')!r}: {key!r} must be a string or null, got {value!r}")
    return value


def parse_registry(text: str, *, source: str = "<memory>") -> RegistryDocument:
    """Parse and structurally validate registry JSON. Raises `RegistryError`
    for a malformed file (bad JSON, missing/wrong-typed required fields).
    Does not check semantic invariants (uniqueness, canonical targets,
    allowed vocabulary values) — see `validate_registry` for that; keeping
    them separate lets a caller report every semantic problem in one pass
    instead of stopping at the first structural one.
    """
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RegistryError(f"{source}: invalid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise RegistryError(f"{source}: top level must be a JSON object")

    schema_version = raw.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise RegistryError(
            f"{source}: schema_version must be {SCHEMA_VERSION}, got {schema_version!r}"
        )

    raw_bindings = raw.get("bindings")
    if not isinstance(raw_bindings, list):
        raise RegistryError(f"{source}: 'bindings' must be a list")

    bindings: list[ExternalIdentityBinding] = []
    for index, raw_binding in enumerate(raw_bindings):
        where = f"{source}: bindings[{index}]"
        if not isinstance(raw_binding, dict):
            raise RegistryError(f"{where}: each binding must be an object")
        evidence = raw_binding.get("evidence", {})
        if evidence is None:
            evidence = {}
        if not isinstance(evidence, dict):
            raise RegistryError(f"{where}: 'evidence' must be an object")
        notes = raw_binding.get("notes", "")
        if not isinstance(notes, str):
            raise RegistryError(f"{where}: 'notes' must be a string")

        bindings.append(ExternalIdentityBinding(
            namespace=_require_str(raw_binding, "namespace", where=where),
            external_entity_type=_require_str(raw_binding, "external_entity_type", where=where),
            external_id=_require_str(raw_binding, "external_id", where=where),
            canonical_entity_type=_require_str(raw_binding, "canonical_entity_type", where=where),
            canonical_id=_require_str(raw_binding, "canonical_id", where=where),
            state=_require_str(raw_binding, "state", where=where),
            authority_basis=_require_str(raw_binding, "authority_basis", where=where),
            verified_at=_optional_str(raw_binding, "verified_at"),
            verified_by=_optional_str(raw_binding, "verified_by"),
            evidence=evidence,
            notes=notes,
            imported_at=_optional_str(raw_binding, "imported_at"),
            imported_by=_optional_str(raw_binding, "imported_by"),
        ))

    # Deterministic order regardless of on-disk array order — this registry
    # is Git-reviewed, and diffs/printed summaries should not depend on
    # wherever in the file a binding happened to be appended.
    bindings.sort(key=lambda b: b.comparability_key)
    return RegistryDocument(schema_version=schema_version, bindings=tuple(bindings))


def load_registry(path: Path | str = DEFAULT_REGISTRY_PATH) -> RegistryDocument:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryError(f"{path}: cannot read registry file: {exc}") from exc
    return parse_registry(text, source=str(path))


def _is_valid_legacy_tdr_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _find_canonical_entity_type(catalog: Catalog, canonical_id: str) -> str | None:
    """Which canonical entity type, if any, this id actually belongs to —
    used only to produce a precise "wrong type" error message distinct from
    "does not exist at all"."""
    for entity_type, attr in _CATALOG_ATTR_BY_ENTITY_TYPE.items():
        if canonical_id in getattr(catalog, attr):
            return entity_type
    return None


def validate_registry(doc: RegistryDocument, catalog: Catalog) -> list[str]:
    """Semantic/invariant validation. Returns a list of human-readable
    problems; empty means the registry is valid. Never raises for a
    well-formed-but-semantically-wrong document (that is exactly what this
    function exists to report) — only `parse_registry`/`load_registry` raise,
    for structurally malformed input.

    Deliberately does NOT require the corresponding legacy Supabase row to
    exist — offline Git validation must not depend on live Supabase (task
    requirement §7). Live existence/parity is a later reconciliation layer's
    job, not this one's.
    """
    problems: list[str] = []
    seen_keys: dict[tuple[str, str, str, str], int] = {}

    for index, binding in enumerate(doc.bindings):
        where = f"bindings[{index}] ({binding.external_id})"

        if binding.namespace not in VALID_NAMESPACES:
            problems.append(f"{where}: unknown namespace {binding.namespace!r}")
        if binding.external_entity_type not in VALID_EXTERNAL_ENTITY_TYPES:
            problems.append(f"{where}: unknown external_entity_type {binding.external_entity_type!r}")
        if binding.canonical_entity_type not in VALID_CANONICAL_ENTITY_TYPES:
            problems.append(f"{where}: unknown canonical_entity_type {binding.canonical_entity_type!r}")
        if binding.state not in VALID_STATES:
            problems.append(
                f"{where}: state {binding.state!r} is not a valid registry state "
                f"({sorted(VALID_STATES)}) — unmatched/ambiguous are review states, "
                f"not canonical registry truth, and must never be stored here"
            )
        if binding.authority_basis not in VALID_AUTHORITY_BASES:
            problems.append(
                f"{where}: authority_basis {binding.authority_basis!r} is not supported "
                f"({sorted(VALID_AUTHORITY_BASES)}) — 'derived' and 'projection_owned' "
                f"mappings must never be seeded into this registry"
            )

        # An active, explicitly-reviewed binding without knowing who/when
        # reviewed it is a data-quality gap in its own right, and the
        # synchronization tool (tdr_bridge/external_identity_sync.py) must be
        # able to trust these are present before writing an operational
        # 'verified' row (canonical_object_map's own check constraint
        # requires verified_at whenever status='verified'). Enforcing this
        # here, at offline validation time, means sync never has to invent a
        # timestamp/actor or special-case a partially-provenanced binding.
        if (
            binding.state == "active"
            and binding.authority_basis == "explicit_review"
            and (not binding.verified_at or not binding.verified_by)
        ):
            problems.append(
                f"{where}: state='active' with authority_basis='explicit_review' requires "
                f"both verified_at and verified_by to be recorded"
            )

        if binding.namespace == "legacy_tdr" and not _is_valid_legacy_tdr_uuid(binding.external_id):
            problems.append(
                f"{where}: external_id {binding.external_id!r} is not a valid UUID, "
                f"required for namespace 'legacy_tdr'"
            )

        # Canonical target validation — both active and retired bindings must
        # resolve to a real entity of the declared type (task requirement §7).
        if binding.canonical_entity_type in _CATALOG_ATTR_BY_ENTITY_TYPE:
            attr = _CATALOG_ATTR_BY_ENTITY_TYPE[binding.canonical_entity_type]
            if binding.canonical_id not in getattr(catalog, attr):
                actual_type = _find_canonical_entity_type(catalog, binding.canonical_id)
                if actual_type is not None:
                    problems.append(
                        f"{where}: canonical_id {binding.canonical_id!r} exists as a "
                        f"{actual_type!r}, not a {binding.canonical_entity_type!r} — "
                        f"canonical_entity_type mismatch"
                    )
                else:
                    problems.append(
                        f"{where}: canonical_id {binding.canonical_id!r} does not exist "
                        f"in the catalog as a {binding.canonical_entity_type!r}"
                    )

        key = binding.comparability_key
        if key in seen_keys:
            problems.append(
                f"{where}: duplicate binding key {key!r} (also at bindings[{seen_keys[key]}]) — "
                f"at most one current binding may exist per "
                f"(namespace, external_entity_type, external_id, canonical_entity_type)"
            )
        else:
            seen_keys[key] = index

    return problems


def summarize(doc: RegistryDocument) -> dict[str, Any]:
    """Deterministic counts for the offline validation CLI. Computed fresh
    from whatever `doc` actually contains — never hard-coded."""
    by_state: dict[str, int] = {}
    by_namespace: dict[str, int] = {}
    by_authority_basis: dict[str, int] = {}
    for binding in doc.bindings:
        by_state[binding.state] = by_state.get(binding.state, 0) + 1
        by_namespace[binding.namespace] = by_namespace.get(binding.namespace, 0) + 1
        by_authority_basis[binding.authority_basis] = by_authority_basis.get(binding.authority_basis, 0) + 1
    return {
        "schema_version": doc.schema_version,
        "bindings": len(doc.bindings),
        "active": by_state.get("active", 0),
        "retired": by_state.get("retired", 0),
        "namespaces": dict(sorted(by_namespace.items())),
        "authority_basis": dict(sorted(by_authority_basis.items())),
    }
