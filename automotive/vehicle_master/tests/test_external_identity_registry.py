import json

import pytest

from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from tdr_bridge.external_identity_registry import (
    DEFAULT_REGISTRY_PATH,
    ExternalIdentityBinding,
    RegistryDocument,
    RegistryError,
    load_registry,
    parse_registry,
    summarize,
    validate_registry,
)


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.load(DATA_DIR, DEFAULT_YEAR)


@pytest.fixture(scope="module")
def jaecoo_generation_id(catalog: Catalog) -> str:
    gen_id = next(
        (gid for gid, gen in catalog.generations.items() if gen.model_id == "jaecoo.jaecoo_5_ev"),
        None,
    )
    assert gen_id is not None, "fixture assumption: jaecoo.jaecoo_5_ev must have at least one generation"
    return gen_id


def _binding(**overrides) -> ExternalIdentityBinding:
    fields = dict(
        namespace="legacy_tdr",
        external_entity_type="model",
        external_id="e1a0b9fd-2d57-477d-b13f-1647d36d0298",
        canonical_entity_type="model",
        canonical_id="jaecoo.jaecoo_5_ev",
        state="active",
        authority_basis="explicit_review",
        verified_at="2026-09-09T06:06:07.164815+00:00",
        verified_by="OpenAI GPT-5.6 Sol",
    )
    fields.update(overrides)
    return ExternalIdentityBinding(**fields)


def _doc(*bindings: ExternalIdentityBinding) -> RegistryDocument:
    return RegistryDocument(schema_version=1, bindings=tuple(bindings))


# ---------------------------------------------------------------------------
# Real seed file
# ---------------------------------------------------------------------------

def test_valid_jaecoo_seed_loads_successfully(catalog: Catalog):
    doc = load_registry(DEFAULT_REGISTRY_PATH)
    assert len(doc.bindings) == 1
    binding = doc.bindings[0]
    assert binding.namespace == "legacy_tdr"
    assert binding.external_entity_type == "model"
    assert binding.external_id == "e1a0b9fd-2d57-477d-b13f-1647d36d0298"
    assert binding.canonical_entity_type == "model"
    assert binding.canonical_id == "jaecoo.jaecoo_5_ev"
    assert binding.state == "active"
    assert binding.authority_basis == "explicit_review"
    # Original Mechanism-B provenance is preserved verbatim, not rewritten.
    assert binding.verified_by == "OpenAI GPT-5.6 Sol"
    assert binding.verified_at == "2026-09-09T06:06:07.164815+00:00"
    # Distinct from the registry's own import metadata.
    assert binding.imported_at == "2026-09-15"
    assert binding.imported_by == "phase-1b-registry-seed"

    problems = validate_registry(doc, catalog)
    assert problems == []

    summary = summarize(doc)
    assert summary == {
        "schema_version": 1,
        "bindings": 1,
        "active": 1,
        "retired": 0,
        "namespaces": {"legacy_tdr": 1},
        "authority_basis": {"explicit_review": 1},
    }


def test_seed_file_contains_exactly_the_one_pinned_jaecoo_binding_not_bulk_data():
    raw = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert len(raw["bindings"]) == 1, (
        "Phase 1B must seed exactly the one explicitly-reviewed Jaecoo binding — "
        "not the 383 Mechanism-A links, not the 326 unmatched Mechanism-B rows, "
        "not the 8 Phase-E projection-owned verified rows, not crosswalk_overrides.json"
    )


# ---------------------------------------------------------------------------
# Canonical target validation
# ---------------------------------------------------------------------------

def test_nonexistent_canonical_target_rejected(catalog: Catalog):
    doc = _doc(_binding(canonical_id="does.not.exist.anywhere"))
    problems = validate_registry(doc, catalog)
    assert len(problems) == 1
    assert "does not exist" in problems[0]


def test_canonical_entity_type_mismatch_rejected(catalog: Catalog, jaecoo_generation_id: str):
    # A real Generation id, declared as canonical_entity_type "model".
    doc = _doc(_binding(canonical_entity_type="model", canonical_id=jaecoo_generation_id))
    problems = validate_registry(doc, catalog)
    assert len(problems) == 1
    assert "mismatch" in problems[0]
    assert "generation" in problems[0]


# ---------------------------------------------------------------------------
# Key / cardinality rules
# ---------------------------------------------------------------------------

def test_duplicate_binding_key_rejected(catalog: Catalog):
    doc = _doc(_binding(), _binding())
    problems = validate_registry(doc, catalog)
    assert len(problems) == 1
    assert "duplicate binding key" in problems[0]


def test_same_external_id_at_different_canonical_entity_types_allowed(catalog: Catalog, jaecoo_generation_id: str):
    doc = _doc(
        _binding(canonical_entity_type="model", canonical_id="jaecoo.jaecoo_5_ev"),
        _binding(canonical_entity_type="generation", canonical_id=jaecoo_generation_id),
    )
    problems = validate_registry(doc, catalog)
    assert problems == []


def test_two_different_external_ids_pointing_to_same_canonical_entity_allowed(catalog: Catalog):
    doc = _doc(
        _binding(external_id="11111111-1111-4111-8111-111111111111"),
        _binding(external_id="22222222-2222-4222-8222-222222222222"),
    )
    problems = validate_registry(doc, catalog)
    assert problems == [], (
        "global canonical-target uniqueness is NOT a generic registry invariant — "
        "only external-key uniqueness is checked"
    )


# ---------------------------------------------------------------------------
# Namespace / vocabulary invariants
# ---------------------------------------------------------------------------

def test_malformed_legacy_tdr_uuid_rejected(catalog: Catalog):
    doc = _doc(_binding(external_id="not-a-uuid"))
    problems = validate_registry(doc, catalog)
    assert len(problems) == 1
    assert "UUID" in problems[0]


@pytest.mark.parametrize("state", ["unmatched", "ambiguous"])
def test_unmatched_and_ambiguous_registry_state_rejected(catalog: Catalog, state: str):
    doc = _doc(_binding(state=state))
    problems = validate_registry(doc, catalog)
    assert len(problems) == 1
    assert "state" in problems[0]


@pytest.mark.parametrize("basis", ["derived", "projection_owned", "made_up_basis"])
def test_unsupported_authority_basis_rejected(catalog: Catalog, basis: str):
    doc = _doc(_binding(authority_basis=basis))
    problems = validate_registry(doc, catalog)
    assert len(problems) == 1
    assert "authority_basis" in problems[0]


def test_retired_binding_may_retain_canonical_id(catalog: Catalog):
    doc = _doc(_binding(state="retired", canonical_id="jaecoo.jaecoo_5_ev"))
    problems = validate_registry(doc, catalog)
    assert problems == []
    assert doc.bindings[0].canonical_id == "jaecoo.jaecoo_5_ev"
    assert doc.bindings[0].state == "retired"


def test_retired_binding_target_still_validated(catalog: Catalog):
    # Retired does not mean exempt from canonical-target validation (task §7:
    # "every active or retired registry target must resolve to a real
    # canonical Vehicle Master entity of the declared type").
    doc = _doc(_binding(state="retired", canonical_id="does.not.exist"))
    problems = validate_registry(doc, catalog)
    assert len(problems) == 1


# ---------------------------------------------------------------------------
# Structural (parse-time) validation
# ---------------------------------------------------------------------------

def test_malformed_json_raises_registry_error():
    with pytest.raises(RegistryError):
        parse_registry("{not valid json")


def test_wrong_schema_version_raises_registry_error():
    with pytest.raises(RegistryError):
        parse_registry(json.dumps({"schema_version": 2, "bindings": []}))


def test_missing_required_field_raises_registry_error():
    payload = {
        "schema_version": 1,
        "bindings": [{"namespace": "legacy_tdr"}],  # missing everything else
    }
    with pytest.raises(RegistryError):
        parse_registry(json.dumps(payload))


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_deterministic_load_sort_behavior_regardless_of_file_order():
    binding_a = {
        "namespace": "legacy_tdr", "external_entity_type": "model",
        "external_id": "22222222-2222-4222-8222-222222222222",
        "canonical_entity_type": "model", "canonical_id": "some.model.a",
        "state": "active", "authority_basis": "explicit_review",
    }
    binding_b = {
        "namespace": "legacy_tdr", "external_entity_type": "model",
        "external_id": "11111111-1111-4111-8111-111111111111",
        "canonical_entity_type": "model", "canonical_id": "some.model.b",
        "state": "active", "authority_basis": "explicit_review",
    }

    forward = parse_registry(json.dumps({"schema_version": 1, "bindings": [binding_a, binding_b]}))
    reversed_ = parse_registry(json.dumps({"schema_version": 1, "bindings": [binding_b, binding_a]}))

    assert [b.external_id for b in forward.bindings] == [b.external_id for b in reversed_.bindings]
    # Sorted by comparability key — binding_b's external_id sorts first.
    assert [b.external_id for b in forward.bindings] == [binding_b["external_id"], binding_a["external_id"]]


def test_summarize_is_deterministic_and_computed_not_hardcoded(catalog: Catalog):
    doc = _doc(
        _binding(external_id="11111111-1111-4111-8111-111111111111", state="active"),
        _binding(external_id="22222222-2222-4222-8222-222222222222", state="retired"),
    )
    summary_first = summarize(doc)
    summary_second = summarize(doc)
    assert summary_first == summary_second
    assert summary_first["bindings"] == 2
    assert summary_first["active"] == 1
    assert summary_first["retired"] == 1
