"""Identity Resolution contract v1: SPEC.md and the machine-readable contract must not drift apart."""
from __future__ import annotations

import re

from identity_resolution.contract import render

import ir_support as S

CODE_PREFIXES = ("SUBJ_", "BRND_", "NAME_", "SER_", "ATTR_", "GEN_", "CARD_", "LIN_", "STATE_", "AUTH_", "INPUT_", "DISCOVERY_", "PROTECTED_HOLD_",
                 "STRUCTURAL_", "AMBIGUOUS_", "NO_CANDIDATE_", "INSUFFICIENT_", "PROPOSE_", "AUTO_", "SUPPRESSED_")
#: Record fields that share a first segment with a policy section (`lineage` and `review` are both).
RECORD_FIELDS = {"lineage.source_present", "lineage.declared_identity_change", "lineage.events", "lineage.applied_event_keys",
                 "review.required", "review.queue", "review.priority", "review.question"}
POLICY_ROOTS = {"quantization", "time", "series", "lexical", "aliases", "attributes", "subject_quality", "candidates", "granularity", "lineage",
                "state", "data_sufficiency", "fingerprint", "review"}


def test_generated_appendices_are_up_to_date():
    rendered = render.render_all()
    current = render.spec_blocks(S.spec_text())
    assert set(current) == set(rendered), "SPEC.md must contain every generated block"
    for name, body in rendered.items():
        assert current[name] == body, f"SPEC.md appendix '{name}' is stale — run: python -m identity_resolution.contract.render --write"


def test_every_policy_key_is_indexed_in_the_spec():
    index = render.spec_blocks(S.spec_text())["policy-index"]
    for path, _ in render.policy_leaves(S.policy()):
        assert f"`{path}`" in index, path


def test_spec_prose_mentions_only_registered_reason_codes():
    prose = S.prose_outside_generated(S.spec_text())
    mentioned = set(re.findall(r"`([A-Z][A-Z0-9_]+)`", prose))
    for token in mentioned:
        if token.startswith(CODE_PREFIXES) and token not in set(S.OUTCOMES) | set(S.OPERATIONS):
            assert token in S.codes(), f"SPEC mentions the unregistered reason code {token}"


def test_spec_prose_mentions_only_real_policy_keys():
    policy = S.policy()
    known: set[str] = set()
    for path, _ in render.policy_leaves(policy):
        parts = path.split(".")
        known.update(".".join(parts[:i]) for i in range(1, len(parts) + 1))
    prose = S.prose_outside_generated(S.spec_text())
    for token in set(re.findall(r"`(?:policy\.)?([a-z_]+(?:\.[a-z_]+)+)`", prose)):
        if token.split(".")[0] in POLICY_ROOTS and token not in RECORD_FIELDS:
            assert token in known, f"SPEC mentions the policy key {token}, which policy.yaml does not define"


def test_spec_invariants_are_numbered_without_gaps():
    numbers = [int(n) for n in re.findall(r"\*\*I(\d+) —", S.spec_text())]
    assert numbers == list(range(1, len(numbers) + 1)) and len(numbers) >= 17
    assert "**I4a — No assumed zero.**" in S.spec_text(), "invariant I4a (owner review, rev 2) must stay"


def test_spec_names_the_companion_files_and_they_exist():
    text = S.spec_text()
    for name in ("policy.yaml", "provider_capabilities.yaml", "adoption.yaml", "reason_codes.yaml", "taxonomy.yaml", "record.schema.json", "decision.schema.json",
                 "capabilities.schema.json", "case.schema.json", "cases.jsonl", "CHANGELOG.md"):
        assert name in text, name
        assert (S.CONTRACT_DIR / name).is_file()


def test_spec_declares_itself_a_draft_not_in_force():
    head = S.spec_text()[:900]
    assert "DRAFT" in head and "NOT FROZEN" in head and "Not in force" in head
    assert "not adopted" in head, "the head must say the provisional thresholds are not adopted"


def test_spec_states_the_three_owner_review_resolutions():
    """Rev 2: missing-row semantics are capability data; identity/aggregation/granularity are link types; bundles are link sets."""
    text = S.spec_text()
    for needle in ("series.absent_row", "Q-ICE-ABSENT-ROW", "ABSENT_IS_ZERO", "`EQUIVALENT`", "`COMPOSED_OF`", "`PART_OF`", "C1", "C2", "link set", "set_id",
                   "I17", "I16", "binding", "STRUCTURAL_STORED_CLAIMS_INCONSISTENT", "10.5", "10.6"):
        assert needle in text, needle


def test_adapter_obligations_cover_the_input_contract():
    prose = S.spec_text()
    for required in ("coverage_declared", "partial_periods", "identity_status", "brands_observed", "successor_id", "declared_identity_change", "source_version"):
        assert required in prose, required
