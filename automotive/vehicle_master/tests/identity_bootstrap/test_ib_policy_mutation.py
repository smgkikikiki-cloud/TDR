"""No number, word or mapping may hide in Python: flipping behaviour-bearing policy keys must break the corpus, and every key must be read."""
from __future__ import annotations

import copy

import pytest

import ib_reference as R
import ib_support as S

DECIDE = [c for c in S.kind("decide")]
BASE = S.policy()


def corpus_breaks(policy: dict) -> bool:
    for c in DECIDE:
        try:
            exp = c["expect"]
            if "refusal" in exp:
                try:
                    S.run_decide(c["input"], policy)
                except R.Refusal as r:
                    if r.code == exp["refusal"]:
                        continue
                return True
            out = S.by_subject(S.run_decide(c["input"], policy))
            if set(out) != set(exp["decisions"]):
                return True
            for sid, want in exp["decisions"].items():
                got = S.project(out[sid])
                if any(got[k] != v for k, v in want.items()):
                    return True
        except (R.Refusal, KeyError, AssertionError, TypeError, ValueError):
            return True
    return False


def mutate(path: str, value):
    pol = copy.deepcopy(BASE)
    node = pol
    parts = path.split(".")
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value
    return pol


def without(path: str, item):
    pol = copy.deepcopy(BASE)
    node = pol
    for part in path.split("."):
        node = node[part]
    node.remove(item)
    return pol


MUTATIONS = {
    "activation.required_ir_outcome": "AUTO",
    "activation.structural_review_outcome": "AMBIGUOUS",
    "subject.creatable_identity_statuses": ["settled", "provisional"],
    "subject.status_codes": {"provisional": "PROVIDER_RAW_NAME", "unmapped_name": "PROVIDER_RAW_NAME"},
    "subject.unavailable_name_values": [],
    "subject.raw_name.separator_characters": [],
    "subject.raw_name.registration_code_token_pattern": "^$",
    "brand.creatable_relations": ["EXACT", "ALIAS_SAME", "ALIAS_RELABEL", "ALIAS_RELATED"],
    "brand.relation_codes": {"UNKNOWN": "BRAND_UNKNOWN", "NOT_IN_TDR": "BRAND_UNKNOWN", "ALIAS_RELATED": "STRUCTURAL_CONFLICT"},
    "lexical.token_boundary_characters": [],
    "lexical.generic_tokens": [],
    "shape.model_code.token_patterns": [],
    "shape.trim.tokens": [],
    "shape.powertrain.tokens": [],
    "shape.powertrain.name_patterns": [],
    "shape.body.tokens": [],
    "shape.generation.tokens": [],
    "shape.generation.token_patterns": [],
    "shape.codes": {"model_code": "POSSIBLE_TRIM_NOT_MODEL", "trim": "POSSIBLE_TRIM_NOT_MODEL", "powertrain": "POSSIBLE_POWERTRAIN_DERIVATIVE", "body": "POSSIBLE_BODY_VARIANT", "generation": "POSSIBLE_GENERATION_VARIANT"},
    "relations.name_classes": {"duplicate": ["EQUAL"], "finer": ["SUBJECT_FINER"], "coarser": ["SUBJECT_COARSER"], "sibling": ["SIBLING"], "ignored": ["CONTRADICTION", "UNAVAILABLE", "FUZZY", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV"]},
    "relations.peer_state_classes": {"DISCOVERED": "canonical", "ENRICHING": "canonical", "VERIFIED": "canonical", "PUBLISHED": "canonical", "WITHDRAWN": "withdrawn", "legacy": "canonical"},
    "relations.canonical_codes": {"duplicate": "DUPLICATE_CANONICAL_SUSPECTED", "finer": "EXISTING_IDENTITY_SUSPECTED", "coarser": "PROVIDER_COARSER_THAN_TDR", "sibling": "EXISTING_IDENTITY_SUSPECTED"},
    "relations.pending_codes": {"duplicate": "EXISTING_IDENTITY_SUSPECTED", "finer": "EXISTING_IDENTITY_SUSPECTED", "coarser": "EXISTING_IDENTITY_SUSPECTED", "sibling": "EXISTING_IDENTITY_SUSPECTED"},
    "relations.withdrawn_codes": {},
    "batch.ignore_peers_holding": [],
    "batch.same_provider": {"duplicate": ["STRUCTURAL_CONFLICT"], "finer": ["STRUCTURAL_CONFLICT"], "sibling": ["STRUCTURAL_CONFLICT"]},
    "batch.cross_provider": {"duplicate": "COALESCE", "finer": [], "sibling": ["STRUCTURAL_CONFLICT"]},
    "batch.provider_priority": ["dlt", "ice"],
    "lineage.actions.rename_old_bound": "PROCEED_WITH_RETIRED_ALIAS",
    "lineage.actions.rename_old_unbound": "HOLD_CONTINUITY",
    "lineage.actions.merge_old_bound_to_one": "REVIEW_AMBIGUOUS",
    "lineage.actions.merge_old_bound_to_many": "HOLD_CONTINUITY",
    "lineage.actions.merge_none_bound": "REVIEW_AMBIGUOUS",
    "lineage.actions.split_any_role": "PROCEED_WITH_RETIRED_ALIAS",
    "lineage.actions.cycle": "REVIEW_AMBIGUOUS",
    "evidence.kind_tiers": {"PROVIDER_IDENTITY": 0, "SECOND_PROVIDER_IDENTITY": 1, "REGULATORY_RECORD": 2, "HOMOLOGATION": 2, "ECO_STICKER": 1, "OFFICIAL_PRICE_LIST": 3, "OFFICIAL_DISTRIBUTOR": 3, "OFFICIAL_LAUNCH_MATERIAL": 3, "OFFICIAL_MANUFACTURER": 3},
    "evidence.providers": {"dlt": {"may_create": True, "base_kind": "SECOND_PROVIDER_IDENTITY"}},
    "evidence.required_tier.create_clean": 1,
    "evidence.soft_clear.min_tier": 3,
    "evidence.soft_clear.required_attestation": "something_else",
    "evidence.corroboration_kind": "REGULATORY_RECORD",
    "allocation.id_format": "{brand_id}:{local}",
    "allocation.forbidden_local_segments": [],
    "allocation.canonical_name.strip_brand_prefix": False,
    "allocation.local_segment_function": "vehreg.normalize.fold",
    "writes.initial_state": {"identity_state": "ENRICHING", "enrichment_state": "IN_PROGRESS"},
    "writes.apply_mode": "DIRECT",
    "writes.shell_columns": ["canonical_id", "brand_id", "slug", "name_en"],
    "writes.lock_key": "other:{brand_id}",
    "event.name": "VEHICLE_IDENTITY_REGISTERED",
    "event.include_provider_hints": False,
    "event.outbox": "other_outbox",
    "priority.bands": [{"min_units": 0, "band": "LOW"}],
    "priority.unknown_units_band": "LOW",
    "priority.queues": {"IDENTITY_REVIEW": "q1", "HOLD": "q2"},
    "priority.silent_hold_codes": [],
    "priority.alert_bands": [],
    "version": 3,
    "subject.raw_name.code_segment_pattern": "^$",
    "brand.sub_brands": {},
    "brand.family.duplicate_relations": [],
    "brand.family.suspect_relations": [],
    "brand.family.suspect_code": "STRUCTURAL_CONFLICT",
    "shape.truncation.code": "POSSIBLE_TRIM_NOT_MODEL",
    "shape.truncation.min_compact_chars": 1,
    "shape.truncation.exempt_digit_only": False,
    "shape.truncation.dangling_tokens": [],
    "shape.generation.contextual_token_patterns": [],
    "shape.generation.contextual_min_tokens": 1,
    "shape.powertrain.token_patterns": [],
    "shape.model_code.token_patterns": ["^[a-z]{1,3}[0-9]{3}[a-z]{0,3}$"],
}


@pytest.mark.parametrize("path", sorted(MUTATIONS))
def test_flipping_a_behaviour_bearing_key_breaks_the_corpus(path):
    assert corpus_breaks(mutate(path, MUTATIONS[path])), f"{path} can change without any corpus case noticing"


def test_dropping_any_single_lexicon_word_is_noticed():
    for section in ("trim", "powertrain", "body", "generation"):
        for word in BASE["shape"][section]["tokens"]:
            assert corpus_breaks(without(f"shape.{section}.tokens", word)), f"{section}.{word}"


class Tracked(dict):
    """Records every policy path the oracle reads (a dict read, an iteration, a membership test)."""

    def __init__(self, data, path, seen):
        super().__init__({k: Tracked(v, f"{path}.{k}" if path else k, seen) if isinstance(v, dict) else v for k, v in data.items()})
        self._path, self._seen = path, seen

    def _mark(self, key=None):
        self._seen.add(f"{self._path}.{key}" if key is not None and self._path else (key or self._path))

    def __getitem__(self, key):
        self._mark(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._mark(key)
        return super().get(key, default)

    def __contains__(self, key):
        self._mark(key)
        return super().__contains__(key)

    def __iter__(self):
        for k in super().keys():
            self._mark(k)
        return super().__iter__()

    def items(self):
        for k in super().keys():
            self._mark(k)
        return super().items()

    def values(self):
        for k in super().keys():
            self._mark(k)
        return super().values()

    def keys(self):
        for k in super().keys():
            self._mark(k)
        return super().keys()


def leaves(node, path=""):
    if isinstance(node, dict) and node and path.count(".") < 1 + (0 if not path else 0):
        for k, v in node.items():
            yield from leaves(v, f"{path}.{k}" if path else k)
    else:
        yield path


#: Keys that are documentation of a contract rule enforced elsewhere (schemas, the writer, the event consumer), not read by the decision procedure.
DECLARATIVE = {
    "writes.conflict_policy", "writes.forbidden_attribute_fields", "writes.actor_kind", "writes.required_permission",
    "event.delivery", "event.version", "fingerprint.algorithm", "fingerprint.decision_includes_policy_digest", "fingerprint.never_in_fingerprints",
    "admin.directive_actions", "admin.creator_type_machine", "admin.creator_type_admin", "allocation.tombstones_reserve_ids", "allocation.collision_resolution",
}


def test_every_policy_key_is_read_by_the_oracle_or_declared_declarative():
    seen: set[str] = set()
    tracked = Tracked(BASE, "", seen)
    for c in DECIDE + S.kind("allocate"):
        if c["kind"] == "decide":
            try:
                R.decide(copy.deepcopy(c["input"]), tracked, S.registry())
            except R.Refusal:
                pass
        else:
            R.allocate(c["input"]["brand_id"], c["input"]["display_name"], c["input"]["identities"], tracked)
    unread = []
    for section, body in BASE.items():
        if section in ("provenance", "version"):
            continue
        for key in body:
            path = f"{section}.{key}"
            if not any(s == path or s.startswith(path + ".") for s in seen) and path not in DECLARATIVE:
                unread.append(path)
    assert not unread, f"policy keys no code path reads (dead configuration): {unread}"
    assert DECLARATIVE <= {f"{s}.{k}" for s, b in BASE.items() if isinstance(b, dict) for k in b}, "DECLARATIVE names a key that does not exist"
