"""Identity Bootstrap contract v1: the YAML files are well-formed and mutually consistent, and SPEC.md cannot drift from them."""
from __future__ import annotations

import re

import pytest

from identity_bootstrap.contract import loader, render

import ib_support as S

POLICY, REG, TAX, LC = S.policy(), S.registry(), S.taxonomy(), S.lifecycle()
CODES = REG["codes"]
PROVENANCE_TAGS = {"inherited", "observed", "proposal", "assumption"}


def walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for v in node:
            yield from walk(v, path)
    else:
        yield path, node


def test_loader_rejects_duplicate_yaml_keys(tmp_path):
    bad = tmp_path / "x.yaml"
    bad.write_text("a: 1\na: 2\n", encoding="utf-8")
    import yaml
    with pytest.raises(loader.DuplicateKeyError):
        yaml.load(bad.read_text(), Loader=loader._StrictLoader)


def test_every_policy_section_has_a_provenance_tag():
    sections = {k for k in POLICY if k not in ("version", "provenance")}
    assert sections == set(POLICY["provenance"]), sections ^ set(POLICY["provenance"])
    assert set(POLICY["provenance"].values()) <= PROVENANCE_TAGS


def test_reason_code_registry_is_well_formed():
    assert set(REG["outcomes"]) == set(S.OUTCOMES)
    ranks = [e["primary_rank"] for e in CODES.values()]
    assert len(ranks) == len(set(ranks)), "primary_rank must be unique so ordering is total"
    for code, e in CODES.items():
        assert re.fullmatch(r"[A-Z][A-Z0-9_]+", code)
        assert e["route"] in REG["routes"] and e["clearable"] in REG["clearable_values"], code
        assert e["summary"].strip(), code
        if e["route"] in ("NONE", "REFUSE"):
            assert e["clearable"] == "never", code
        if e["route"] == "CREATE":
            assert code == "NEW_IDENTITY_CONFIRMED"
    assert {c for c, e in CODES.items() if e["route"] == "CREATE"} == {"NEW_IDENTITY_CONFIRMED"}


def test_the_required_reason_codes_exist():
    required = """NEW_IDENTITY_CONFIRMED EXISTING_IDENTITY_SUSPECTED DUPLICATE_CANONICAL_SUSPECTED PROVIDER_IDENTITY_PROVISIONAL PROVIDER_RAW_NAME
    PROVIDER_LINEAGE_AMBIGUOUS PROVIDER_FINER_THAN_TDR POSSIBLE_TRIM_NOT_MODEL POSSIBLE_GENERATION_VARIANT POSSIBLE_BODY_VARIANT POSSIBLE_MODEL_CODE
    BRAND_UNKNOWN CANONICAL_ID_COLLISION STRUCTURAL_CONFLICT IDENTITY_ALREADY_DISCOVERED INSUFFICIENT_IDENTITY_EVIDENCE""".split()
    assert set(required) <= set(CODES)


def test_clearability_follows_the_two_authorities():
    """Lexical suspicions are clearable by evidence; structural questions about TDR's own catalog only by an admin; duplicates and hard gates never."""
    lexical = {"POSSIBLE_MODEL_CODE", "POSSIBLE_TRIM_NOT_MODEL", "POSSIBLE_POWERTRAIN_DERIVATIVE", "POSSIBLE_BODY_VARIANT", "POSSIBLE_GENERATION_VARIANT"}
    assert {c for c, e in CODES.items() if e["clearable"] in ("evidence", "evidence_or_admin")} == lexical
    for code in ("DUPLICATE_CANONICAL_SUSPECTED", "IDENTITY_ALREADY_DISCOVERED", "CANONICAL_ID_COLLISION", "BRAND_NOT_IN_TDR", "PROVIDER_IDENTITY_PROVISIONAL",
                 "PROVIDER_RAW_NAME", "NAME_UNSPECIFIED", "BRAND_UNKNOWN", "NOT_ACTIVATED", "LINEAGE_UNRESOLVED", "INSUFFICIENT_IDENTITY_EVIDENCE"):
        assert CODES[code]["clearable"] == "never", code
    for code, e in CODES.items():
        if e["route"] == "HOLD":
            assert e["clearable"] == "never", f"{code}: a HOLD asks nobody to decide, so nothing may clear it"


def test_every_code_named_by_the_policy_exists_and_has_the_right_route():
    for section in ("status_codes", "relation_codes", "canonical_codes", "pending_codes", "withdrawn_codes", "codes"):
        for _, value in walk({k: v for k, v in _find(POLICY, section).items()}):
            assert value in CODES, f"{section}: {value}"
    for code in POLICY["batch"]["ignore_peers_holding"] + POLICY["priority"]["silent_hold_codes"]:
        assert code in CODES, code
    for code in POLICY["batch"]["same_provider"]["duplicate"] + POLICY["batch"]["same_provider"]["finer"] + POLICY["batch"]["same_provider"]["sibling"]:
        assert CODES[code]["route"] == "REVIEW", code
    for code in POLICY["priority"]["silent_hold_codes"] + POLICY["batch"]["ignore_peers_holding"]:
        assert CODES[code]["route"] == "HOLD", code
    for code in POLICY["subject"]["status_codes"].values():
        assert CODES[code]["route"] == "HOLD", code


def _find(node, key):
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for v in node.values():
            found = _find(v, key)
            if found is not None:
                return found
    return None


def test_policy_has_no_volume_threshold_that_decides_creation():
    """Remove any design assumption equivalent to '>= 500 registrations means create a model'."""
    text = repr(POLICY).lower()
    for forbidden in ("min_units_to_create", "catalog_gap_min_units", "create_min", "min_registrations"):
        assert forbidden not in text
    for path, _ in walk(POLICY):
        if "units" in path:
            assert path.startswith("priority."), f"volume appears outside the priority section: {path}"


def test_policy_regexes_compile_and_lists_are_unique():
    for path, value in walk(POLICY):
        if path.endswith("token_patterns") or path.endswith("name_patterns") or path.endswith("registration_code_token_pattern"):
            re.compile(value)
    for section in ("trim", "powertrain", "body", "generation"):
        tokens = POLICY["shape"][section]["tokens"]
        assert len(tokens) == len(set(tokens)), section
    classes = POLICY["relations"]["name_classes"]
    flat = [r for members in classes.values() for r in members]
    assert len(flat) == len(set(flat)) == 9, "every IR name relation belongs to exactly one class"


def test_apply_mode_is_propose_until_the_owner_amends_the_permission_table():
    assert POLICY["writes"]["apply_mode"] == "PROPOSE", "DIRECT needs an explicit owner amendment of VEHICLE_DB_V3 section 4"
    assert POLICY["writes"]["initial_state"] == LC["initial_state"]
    assert set(POLICY["writes"]["shell_columns"]).isdisjoint(POLICY["writes"]["forbidden_attribute_fields"])


def test_taxonomy_is_consistent():
    ids = [e["id"] for e in TAX["entries"]]
    assert len(ids) == len(set(ids))
    for e in TAX["entries"]:
        assert e["area"] in TAX["areas"] and e["id"].startswith(e["area"] + "-"), e["id"]
        assert e["outcome"] in S.OUTCOMES
        assert set(e["codes"]) <= set(CODES), e["id"]
    seen = {c for e in TAX["entries"] for c in e["codes"]}
    missing = {c for c, e in CODES.items() if e["route"] != "REFUSE"} - seen
    assert not missing, f"reason codes no taxonomy entry mentions: {sorted(missing)}"


def test_spec_appendices_are_current():
    assert render.main(["--check"]) == 0


def test_spec_prose_names_only_real_codes_and_mentions_every_decision_code():
    text = S.spec_text()
    prose = render._BLOCK.sub("", text)
    known = set(CODES) | set(REG["outcomes"]) | {
        "NO_CANDIDATE", "STRUCTURAL_REVIEW", "AUTO", "PROPOSED", "DISCOVERED", "ENRICHING", "VERIFIED", "PUBLISHED", "WITHDRAWN", "PENDING", "IN_PROGRESS", "COMPLETE",
        "BLOCKED", "NOT_NULL", "PROPOSE", "DIRECT", "HOLD_CONTINUITY", "REVIEW_AMBIGUOUS", "PROCEED_WITH_RETIRED_ALIAS", "HOLD_UNRESOLVED", "ALREADY_APPLIED", "STALE",
        "RESERVE_CANONICAL_ID", "INSERT_IDENTITY_SHELL", "INSERT_EXTERNAL_ALIAS", "INSERT_PROVENANCE", "ENQUEUE_EVENT", "PROPOSE_ORIGIN_MAPPING", "VEHICLE_IDENTITY_CREATED",
        "RETIRED_PREDECESSOR", "ADDITIONAL", "ORIGIN", "CREATE", "CLAIM", "VERIFY", "PUBLISH", "RELEASE", "SUBJECT_FINER", "SUBJECT_COARSER", "CONTRADICTION", "UNAVAILABLE",
        "SIBLING", "NEVER", "ENRICH_IDENTITY", "HIGH_VOLUME_UNRESOLVED", "CREATE_IDENTITY", "DO_NOT_CREATE", "TARGET", "SUBJECT", "SPLIT", "MERGE", "RENAME",
        "REVIEW", "REFUSE", "NULL", "CURRENT", "HISTORICAL", "UNVERIFIED", "BOOTSTRAP", "ADMIN", "ENRICHMENT",
    }
    for token in set(re.findall(r"`([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|[A-Z]{4,})`", prose)):
        assert token in known or token.startswith("STALE:"), f"SPEC prose mentions unknown `{token}`"
    for code, e in CODES.items():
        if e["kind"] in ("decision", "gate", "flag"):
            assert f"`{code}`" in prose, f"SPEC prose never mentions {code}"


def test_spec_prose_policy_keys_exist():
    prose = render._BLOCK.sub("", S.spec_text())
    for key in set(re.findall(r"`((?:activation|subject|brand|lexical|shape|relations|batch|lineage|evidence|allocation|admin|writes|event|priority|fingerprint)\.[a-z_.]+)`", prose)):
        if key.endswith((".json", ".md", ".yaml")):
            continue
        node = POLICY
        for part in key.split("."):
            assert isinstance(node, dict) and part in node, f"SPEC mentions policy key {key} that does not exist"
            node = node[part]
