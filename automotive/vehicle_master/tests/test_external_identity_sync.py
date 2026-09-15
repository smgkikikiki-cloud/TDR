from tdr_bridge.external_identity_registry import ExternalIdentityBinding, RegistryDocument
from tdr_bridge.external_identity_sync import (
    OperationalRow,
    PHASE_E_MATCH_BASIS_VALUE,
    PHASE_E_VERIFIED_BY,
    SYNC_MATCH_BASIS_VALUE,
    binding_key,
    classify_binding,
    classify_operational_only,
    mutations_to_apply,
    propose_mutation,
    reconcile,
)


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


def _operational_row(**overrides) -> OperationalRow:
    fields = dict(
        source_table="models",
        source_id="e1a0b9fd-2d57-477d-b13f-1647d36d0298",
        canonical_entity_type="model",
        canonical_id="jaecoo.jaecoo_5_ev",
        status="verified",
        verified_by="OpenAI GPT-5.6 Sol",
        verified_at="2026-09-09T06:06:07.164815+00:00",
    )
    fields.update(overrides)
    return OperationalRow(**fields)


# ---------------------------------------------------------------------------
# Binding classification
# ---------------------------------------------------------------------------

def test_in_sync_binding():
    binding = _binding()
    row = _operational_row()
    result = classify_binding(binding, row, source_row_exists=True)
    assert result.classification == "in_sync"
    assert propose_mutation(result) is None


def test_missing_operational_binding():
    binding = _binding()
    result = classify_binding(binding, None, source_row_exists=True)
    assert result.classification == "missing_operational_row"


def test_canonical_target_conflict():
    binding = _binding(canonical_id="jaecoo.jaecoo_5_ev")
    row = _operational_row(canonical_id="jaecoo.jaecoo_7")
    result = classify_binding(binding, row, source_row_exists=True)
    assert result.classification == "canonical_target_conflict"
    assert propose_mutation(result) is None


def test_operational_status_conflict():
    binding = _binding(state="active")  # desired status: verified
    row = _operational_row(status="retired")
    result = classify_binding(binding, row, source_row_exists=True)
    assert result.classification == "operational_status_conflict"
    assert propose_mutation(result) is None


def test_missing_legacy_source_row():
    binding = _binding()
    result = classify_binding(binding, None, source_row_exists=False)
    assert result.classification == "missing_external_source_row"
    assert propose_mutation(result) is None


def test_same_source_id_at_different_canonical_target_type_works():
    binding_model = _binding(canonical_entity_type="model", canonical_id="jaecoo.jaecoo_5_ev")
    binding_generation = _binding(canonical_entity_type="generation", canonical_id="jaecoo.jaecoo_5_ev.gen1")
    result_model = classify_binding(binding_model, None, source_row_exists=True)
    result_generation = classify_binding(binding_generation, None, source_row_exists=True)
    assert result_model.key != result_generation.key
    assert result_model.classification == "missing_operational_row"
    assert result_generation.classification == "missing_operational_row"


def test_multiple_external_ids_to_same_canonical_entity_works():
    binding_one = _binding(external_id="11111111-1111-4111-8111-111111111111")
    binding_two = _binding(external_id="22222222-2222-4222-8222-222222222222")
    result_one = classify_binding(binding_one, None, source_row_exists=True)
    result_two = classify_binding(binding_two, None, source_row_exists=True)
    assert result_one.key != result_two.key
    assert result_one.classification == "missing_operational_row"
    assert result_two.classification == "missing_operational_row"
    # No global canonical-target-uniqueness check at this layer either.
    assert result_one.binding.canonical_id == result_two.binding.canonical_id


# ---------------------------------------------------------------------------
# Active vs. retired sync payloads and provenance separation
# ---------------------------------------------------------------------------

def test_active_sync_proposes_verified_row_with_preserved_provenance():
    binding = _binding(state="active")
    result = classify_binding(binding, None, source_row_exists=True)
    mutation = propose_mutation(result, now="2026-09-20T00:00:00Z")
    assert mutation is not None
    assert mutation.payload["status"] == "verified"
    assert mutation.payload["canonical_id"] == "jaecoo.jaecoo_5_ev"
    # Original review provenance preserved verbatim, not rewritten as if the
    # sync tool performed the review.
    assert mutation.payload["verified_by"] == "OpenAI GPT-5.6 Sol"
    assert mutation.payload["verified_at"] == "2026-09-09T06:06:07.164815+00:00"
    # Synchronization provenance is kept distinct, in its own object.
    assert mutation.payload["match_basis"]["basis"] == SYNC_MATCH_BASIS_VALUE
    assert mutation.payload["match_basis"]["synced_at"] == "2026-09-20T00:00:00Z"
    assert mutation.payload["match_basis"]["registry_state"] == "active"


def test_retired_sync_proposes_retired_row_retaining_canonical_id():
    binding = _binding(state="retired", canonical_id="byd.byd_seal", verified_by=None, verified_at=None)
    result = classify_binding(binding, None, source_row_exists=True)
    mutation = propose_mutation(result, now="2026-09-20T00:00:00Z")
    assert mutation is not None
    assert mutation.payload["status"] == "retired"
    assert mutation.payload["canonical_id"] == "byd.byd_seal"
    assert mutation.payload["match_basis"]["registry_state"] == "retired"


# ---------------------------------------------------------------------------
# Dry-run purity / idempotency / convergence
# ---------------------------------------------------------------------------

def test_dry_run_performs_zero_writes():
    # reconcile() is pure Python over already-fetched data — there is no I/O
    # to perform, and it must not mutate its inputs.
    doc = _doc(_binding())
    operational_rows = [_operational_row()]
    operational_rows_copy = list(operational_rows)
    report = reconcile(doc, operational_rows, source_row_exists={("models", _binding().external_id): True})
    assert operational_rows == operational_rows_copy
    assert report.is_fully_reconciled


def test_apply_idempotency_and_convergence():
    binding = _binding()
    doc = _doc(binding)
    exists = {("models", binding.external_id): True}

    # First dry-run: operational row absent.
    first = reconcile(doc, [], exists)
    assert first.binding_results[0].classification == "missing_operational_row"
    assert len(first.proposed_mutations) == 1

    # Simulate applying the one proposed mutation.
    mutation = first.proposed_mutations[0]
    applied_row = OperationalRow(
        source_table=mutation.payload["source_table"],
        source_id=mutation.payload["source_id"],
        canonical_entity_type=mutation.payload["canonical_entity_type"],
        canonical_id=mutation.payload["canonical_id"],
        status=mutation.payload["status"],
        verified_by=mutation.payload["verified_by"],
        verified_at=mutation.payload["verified_at"],
        match_basis=mutation.payload["match_basis"],
        notes=mutation.payload["notes"],
    )

    # Rerun: now in sync, zero further mutations proposed.
    second = reconcile(doc, [applied_row], exists)
    assert second.binding_results[0].classification == "in_sync"
    assert second.proposed_mutations == []
    assert second.is_fully_reconciled

    # A third rerun (simulating "rerun after successful apply") converges
    # identically — the tool is safe to rerun indefinitely.
    third = reconcile(doc, [applied_row], exists)
    assert third.summary() == second.summary()


def test_dry_run_still_lists_the_individually_safe_mutation_when_a_conflict_exists_elsewhere():
    # reconcile()/proposed_mutations is a dry-run *report* — per binding, on
    # its own merits. A conflict on one binding does not stop an unrelated,
    # individually-safe binding from being listed as a candidate mutation
    # here; it is --apply (mutations_to_apply(), tested below) that gates on
    # blockers existing anywhere in the run, not this reporting layer.
    # Distinct canonical targets, so this exercises conflict-vs-missing
    # isolation only -- not the operational-target-uniqueness blocker
    # (covered separately below).
    conflicting = _binding(external_id="11111111-1111-4111-8111-111111111111")
    missing = _binding(external_id="22222222-2222-4222-8222-222222222222", canonical_id="byd.byd_seal")
    doc = _doc(conflicting, missing)
    conflicting_row = _operational_row(
        source_id=conflicting.external_id, canonical_id="some.other.model",
    )
    exists = {("models", conflicting.external_id): True, ("models", missing.external_id): True}

    report = reconcile(doc, [conflicting_row], exists)
    assert report.has_blockers
    assert not report.is_fully_reconciled
    # Only the missing binding gets a proposed (dry-run) mutation; the
    # conflict never does.
    assert len(report.proposed_mutations) == 1
    assert report.proposed_mutations[0].key == binding_key(missing)
    # But nothing is actually safe to *apply* this run -- see
    # test_apply_gate_blocks_every_mutation_when_any_blocker_exists_anywhere.


def test_apply_gate_blocks_every_mutation_when_any_blocker_exists_anywhere():
    # This is the critical --apply safety property: one blocker anywhere in
    # the run means zero mutations are applied, even for a completely
    # unrelated binding whose own classification is individually safe
    # (missing_operational_row). A partial apply here would insert the
    # "missing" binding's row while leaving the conflict unresolved -- never
    # acceptable for --apply, even though it's fine to *report* in dry-run.
    conflicting = _binding(external_id="11111111-1111-4111-8111-111111111111")
    missing = _binding(external_id="22222222-2222-4222-8222-222222222222", canonical_id="byd.byd_seal")
    doc = _doc(conflicting, missing)
    conflicting_row = _operational_row(
        source_id=conflicting.external_id, canonical_id="some.other.model",
    )
    exists = {("models", conflicting.external_id): True, ("models", missing.external_id): True}

    report = reconcile(doc, [conflicting_row], exists)
    assert report.has_blockers
    # The dry-run report still lists the individually-safe mutation...
    assert len(report.proposed_mutations) == 1
    # ...but the apply gate applies none of them.
    assert mutations_to_apply(report) == []


def test_apply_gate_applies_everything_when_no_blockers_exist():
    binding = _binding()
    doc = _doc(binding)
    exists = {("models", binding.external_id): True}
    report = reconcile(doc, [], exists)
    assert not report.has_blockers
    assert mutations_to_apply(report) == report.proposed_mutations
    assert len(mutations_to_apply(report)) == 1


# ---------------------------------------------------------------------------
# Operational representability -- canonical_object_map_verified_target_uq
# ---------------------------------------------------------------------------

def test_two_active_bindings_targeting_the_same_canonical_target_are_blocked():
    # Neither binding has an operational row yet. Git allows both bindings
    # to exist (a broader identity graph than the operational layer), but
    # applying both would create two verified canonical_object_map rows for
    # one (canonical_entity_type, canonical_id) -- forbidden by
    # canonical_object_map_verified_target_uq. Both must be blocked, and
    # neither may produce a proposed mutation.
    binding_one = _binding(external_id="11111111-1111-4111-8111-111111111111")
    binding_two = _binding(external_id="22222222-2222-4222-8222-222222222222")
    doc = _doc(binding_one, binding_two)
    exists = {
        ("models", binding_one.external_id): True,
        ("models", binding_two.external_id): True,
    }

    report = reconcile(doc, [], exists)
    assert report.has_blockers
    classifications = {r.key: r.classification for r in report.binding_results}
    assert classifications[binding_key(binding_one)] == "operational_target_uniqueness_blocker"
    assert classifications[binding_key(binding_two)] == "operational_target_uniqueness_blocker"
    assert report.proposed_mutations == []
    assert mutations_to_apply(report) == []


def test_missing_binding_whose_target_is_already_verified_under_another_key_is_blocked():
    # binding's own operational row is absent (would otherwise be
    # missing_operational_row), but a *different* source key already has a
    # verified row at the same canonical target -- inserting this binding's
    # row would violate canonical_object_map_verified_target_uq just the
    # same as if both were in the registry.
    already_verified = _binding(external_id="11111111-1111-4111-8111-111111111111")
    still_missing = _binding(external_id="22222222-2222-4222-8222-222222222222")
    doc = _doc(already_verified, still_missing)
    existing_row = _operational_row(source_id=already_verified.external_id)  # in_sync for already_verified
    exists = {
        ("models", already_verified.external_id): True,
        ("models", still_missing.external_id): True,
    }

    report = reconcile(doc, [existing_row], exists)
    assert report.has_blockers
    classifications = {r.key: r.classification for r in report.binding_results}
    assert classifications[binding_key(already_verified)] == "in_sync"
    assert classifications[binding_key(still_missing)] == "operational_target_uniqueness_blocker"
    assert report.proposed_mutations == []
    assert mutations_to_apply(report) == []


def test_retired_bindings_are_never_subject_to_the_uniqueness_blocker():
    # DESIRED_STATUS_BY_BINDING_STATE maps "retired" -> "retired", not
    # "verified" -- canonical_object_map_verified_target_uq only constrains
    # status='verified' rows, so two retired bindings sharing a canonical
    # target is not a representability problem.
    binding_one = _binding(external_id="11111111-1111-4111-8111-111111111111", state="retired")
    binding_two = _binding(external_id="22222222-2222-4222-8222-222222222222", state="retired")
    doc = _doc(binding_one, binding_two)
    exists = {
        ("models", binding_one.external_id): True,
        ("models", binding_two.external_id): True,
    }

    report = reconcile(doc, [], exists)
    assert not report.has_blockers
    classifications = {r.key: r.classification for r in report.binding_results}
    assert classifications[binding_key(binding_one)] == "missing_operational_row"
    assert classifications[binding_key(binding_two)] == "missing_operational_row"
    assert len(report.proposed_mutations) == 2


# ---------------------------------------------------------------------------
# Operational-only rows — classified, never mutated
# ---------------------------------------------------------------------------

def test_operational_review_rows_survive_untouched():
    row = _operational_row(source_id="other-1", canonical_id=None, status="unmatched", verified_by=None, verified_at=None)
    results = classify_operational_only([row], registry_keys=set())
    assert len(results) == 1
    assert results[0].classification == "review_state_unmatched"

    ambiguous_row = _operational_row(source_id="other-2", canonical_id=None, status="ambiguous", verified_by=None, verified_at=None)
    results2 = classify_operational_only([ambiguous_row], registry_keys=set())
    assert results2[0].classification == "review_state_ambiguous"


def test_phase_e_projection_rows_survive_untouched():
    row = _operational_row(
        source_table="model_powertrains", source_id="pt-1", canonical_entity_type="variant",
        canonical_id="jaecoo.jaecoo_5_ev.gen1.some_variant",
        verified_by=PHASE_E_VERIFIED_BY,
        match_basis={"basis": PHASE_E_MATCH_BASIS_VALUE, "model": "jaecoo.jaecoo_5_ev"},
    )
    results = classify_operational_only([row], registry_keys=set())
    assert results[0].classification == "phase_e_projection_owned"


def test_phase_e_ownership_requires_both_verified_by_and_match_basis():
    # is_phase_e_owned is AND, not OR: only a row carrying BOTH halves of the
    # known Phase-E provenance pattern is confidently Phase-E-owned. A row
    # with just one half is real but unconfirmed provenance and must not be
    # silently hidden behind a Phase-E label it may not deserve.
    both = _operational_row(
        source_id="pe-both", verified_by=PHASE_E_VERIFIED_BY,
        match_basis={"basis": PHASE_E_MATCH_BASIS_VALUE},
    )
    assert classify_operational_only([both], registry_keys=set())[0].classification == "phase_e_projection_owned"

    actor_only = _operational_row(
        source_id="pe-actor-only", verified_by=PHASE_E_VERIFIED_BY,
        match_basis={"basis": "something-else"},
    )
    assert classify_operational_only([actor_only], registry_keys=set())[0].classification == "verified_ownership_unknown"

    basis_only = _operational_row(
        source_id="pe-basis-only", verified_by="someone-else@example.com",
        match_basis={"basis": PHASE_E_MATCH_BASIS_VALUE},
    )
    assert classify_operational_only([basis_only], registry_keys=set())[0].classification == "verified_ownership_unknown"


def test_unknown_verified_operational_rows_survive_untouched():
    row = _operational_row(source_id="other-3", verified_by="some-human@example.com", match_basis={})
    results = classify_operational_only([row], registry_keys=set())
    assert results[0].classification == "verified_ownership_unknown"


def test_retired_operational_only_row_classified():
    row = _operational_row(source_id="other-4", status="retired", verified_by=None, verified_at=None)
    results = classify_operational_only([row], registry_keys=set())
    assert results[0].classification == "retired_operational_only"


def test_operational_only_rows_never_produce_proposed_mutations():
    # proposed_mutations is derived exclusively from binding_results — an
    # operational-only row, whatever its classification, structurally
    # cannot generate a mutation.
    binding = _binding()
    doc = _doc(binding)
    unrelated_verified = _operational_row(source_id="unrelated", verified_by="someone")
    unrelated_unmatched = _operational_row(source_id="unrelated-2", status="unmatched", canonical_id=None, verified_by=None, verified_at=None)
    phase_e_row = _operational_row(
        source_table="trims", source_id="trim-1", canonical_entity_type="market_trim",
        canonical_id="jaecoo.jaecoo_5_ev.gen1.trim.x", verified_by=PHASE_E_VERIFIED_BY,
        match_basis={"basis": PHASE_E_MATCH_BASIS_VALUE},
    )
    report = reconcile(
        doc,
        [_operational_row(), unrelated_verified, unrelated_unmatched, phase_e_row],
        {("models", binding.external_id): True},
    )
    assert report.binding_results[0].classification == "in_sync"
    assert report.proposed_mutations == []
    assert len(report.operational_only) == 3
    classifications = {r.classification for r in report.operational_only}
    assert classifications == {"verified_ownership_unknown", "review_state_unmatched", "phase_e_projection_owned"}


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_deterministic_output_regardless_of_input_order():
    binding_a = _binding(external_id="22222222-2222-4222-8222-222222222222")
    binding_b = _binding(external_id="11111111-1111-4111-8111-111111111111")
    doc_forward = _doc(binding_a, binding_b)
    doc_reversed = _doc(binding_b, binding_a)
    exists = {
        ("models", binding_a.external_id): True,
        ("models", binding_b.external_id): True,
    }
    row_a = _operational_row(source_id=binding_a.external_id)
    row_b = _operational_row(source_id=binding_b.external_id)

    forward = reconcile(doc_forward, [row_a, row_b], exists)
    reversed_ = reconcile(doc_reversed, [row_b, row_a], exists)

    assert [r.key for r in forward.binding_results] == [r.key for r in reversed_.binding_results]
    assert forward.summary() == reversed_.summary()
