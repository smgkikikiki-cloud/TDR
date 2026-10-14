"""Invariant I19 and the lexical-relation correction pass (owner decision 2026-10-11, `od_lexical_relation_correction`).

The pass tightened three things in the name-relation ladder (SPEC §5.3, §5.4): FUZZY refuses tokens that contain a digit, SIBLING needs a distinctive shared token (a
generic, policy-driven rule), and two Honda model synonyms exist. The risk the owner named is that making a relation stricter silently moves an uncertain case towards AUTO.
These tests pin that it cannot, on four levels:

  1. the policy data is well formed and the evaluator names no model;
  2. over every name pair the corpus mentions, the tightened relation is never more permissive than the rev 3 one, and new `EQUAL*` pairs are exactly the synonyms;
  3. over every `resolve` case, AUTO(after) is AUTO(before) plus the explicitly listed synonym cases;
  4. over the real M7.0 snapshot (when the archived package is present), the committed before/after measurements are what the code produces, AUTO is the same set,
     and the report is what the measurements render to.

"Before" is not a stored opinion: `lexical_pass.rev3_rules()` switches the three rules back in the evaluator's policy object, so the rev 3 behaviour is re-derived live.
"""
from __future__ import annotations

import ast
import collections
import itertools
import json
import re
from pathlib import Path

import pytest

import ir_support as S
from identity_resolution.calibration import adapters as A
from identity_resolution.calibration import lexical_pass as L
from identity_resolution.calibration import ref_eval_core as P
from identity_resolution.calibration import ref_eval_resolve as P2

PACKAGE = A.REPO_ROOT / A.PACKAGE_RELATIVE
needs_package = pytest.mark.skipif(not PACKAGE.exists(), reason="the archived M7.0 package is not in this checkout")

#: Demotions the rules allow, as (rev 3 relation, relation now). Anything else that changes is a loosening.
DEMOTIONS = {("FUZZY", "CONTRADICTION"), ("FUZZY", "SIBLING"), ("SIBLING", "CONTRADICTION")}
#: The resolve cases whose AUTO is new in rev 4. Adding a synonym means adding it here, deliberately.
SYNONYM_AUTO_CASES = {"resolve.lex-honda-jazz-is-fit", "resolve.lex-honda-step-wgn-is-stepwagon"}
RANK = {"EQUAL": 0, "EQUAL_VIA_MODEL_ALIAS": 0, "EQUAL_VIA_TOKEN_EQUIV": 0, "FUZZY": 1, "SUBJECT_COARSER": 2, "SUBJECT_FINER": 2, "SIBLING": 3, "CONTRADICTION": 4, "UNAVAILABLE": 5}


def check_not_looser(before: str, after: str, auto: set[str], is_scoped_synonym: bool) -> str | None:
    """None if the move from the rev 3 relation to the current one respects I19, else a message. Used on every pair, and tested against known loosenings below."""
    if before == after:
        return None
    if (before, after) in DEMOTIONS:
        return None
    if after in auto and before not in auto:
        return None if (after == "EQUAL_VIA_MODEL_ALIAS" and is_scoped_synonym) else f"{before} -> {after} adds AUTO eligibility without a scoped synonym"
    return f"{before} -> {after} is not a listed demotion"


# ---------------------------------------------------------------------------------------------------------------------------------------------- 1. the data
def test_the_distinctive_token_policy_is_well_formed():
    rule = S.policy()["lexical"]["distinctive_token"]
    assert set(rule) == {"required_for_relations", "min_length", "exclude_numeric", "non_distinctive", "non_distinctive_patterns"}
    assert set(rule["required_for_relations"]) <= {"SIBLING", "SUBJECT_COARSER", "SUBJECT_FINER"}, "only relations that rest on shared tokens can need a distinctive one"
    assert rule["required_for_relations"] == ["SIBLING"], "v1 asks it of SIBLING only (the owner's scope); containment is a reported observation"
    assert isinstance(rule["min_length"], int) and rule["min_length"] >= 1 and isinstance(rule["exclude_numeric"], bool)
    assert set(rule["non_distinctive"]) == {"body", "powertrain", "trim", "generation", "market"}
    seen: dict[str, str] = {}
    for cls, words in rule["non_distinctive"].items():
        for word in words:
            assert word == word.casefold() and P._tokens_raw(word) == [word], f"{cls}: {word!r} must be one normalized token or it can never match"
            assert word not in seen, f"{word!r} is listed under both {seen[word]} and {cls}"
            seen[word] = cls
    for pattern in rule["non_distinctive_patterns"]:
        re.compile(pattern)
        assert pattern.startswith("^") and pattern.endswith("$"), f"{pattern}: a descriptor shape matches a whole token"
    fuzzy = S.policy()["lexical"]["fuzzy_token"]
    assert fuzzy["allow_tokens_with_digits"] is False


def test_model_aliases_are_scoped_and_the_honda_synonyms_are_the_owners_pairs():
    entries = {m["id"]: m for m in S.policy()["aliases"]["model"]}
    for entry in entries.values():
        assert entry["brand_alias_ids"] or entry.get("brands"), f"{entry['id']} applies to every brand: an alias must be scoped"
        assert all(isinstance(b, str) and b.strip() for b in entry.get("brands", []))
    honda = entries["honda_model_synonyms"]
    assert honda["brands"] == ["Honda"] and honda["brand_alias_ids"] == []
    assert honda["pairs"] == [["Jazz", "Fit"], ["Stepwagon", "Step WGN"]]
    assert S.policy()["alias_provenance"]["honda_model_synonyms"] == "owner_seed"


def test_the_evaluator_names_no_model_and_the_policy_carries_the_vocabulary():
    """Owner: 'do not hardcode V/CX/GR/RS/AMG as model-specific exceptions'. No string literal of the evaluator may be one of them (or a Honda synonym)."""
    source = Path(P.__file__).read_text(encoding="utf-8")
    literals = {n.value.casefold() for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    forbidden = {"v", "cx", "mx", "gr", "rs", "hr", "wr", "amg", "jazz", "fit", "stepwagon", "step wgn", "honda", "sport", "hybrid", "hatchback", "sedan"}
    assert not literals & forbidden, f"the evaluator hardcodes {sorted(literals & forbidden)}; it belongs in policy.yaml"
    vocab = {w for words in S.policy()["lexical"]["distinctive_token"]["non_distinctive"].values() for w in words}
    assert "amg" in vocab, "'amg' is a three-letter trim label: the policy vocabulary, not code, is what keeps it from being distinctive"
    for short in ("v", "cx", "gr", "rs", "hr"):
        assert short not in vocab, f"{short!r} must be excluded by the length floor alone, not listed"
        assert not P.is_distinctive(short)


def test_the_distinctive_rule_follows_the_policy_not_a_constant():
    """The same evaluator, a different floor: the rule is data."""
    rule = P.POL["lexical"]["distinctive_token"]
    saved = rule["min_length"]
    try:
        assert not P.is_distinctive("gr") and P.is_distinctive("nsx") and not P.is_distinctive("4x2") and not P.is_distinctive("hybrid") and not P.is_distinctive("300")
        rule["min_length"] = 2
        assert P.is_distinctive("gr") and not P.is_distinctive("v")
        rule["min_length"] = 4
        assert not P.is_distinctive("nsx") and P.is_distinctive("revo")
    finally:
        rule["min_length"] = saved
    assert P.is_distinctive("nsx")


# ---------------------------------------------------------------------------------------------------------------------------------------------- 2. every name pair
def _name_pool() -> list[tuple[str, str]]:
    """Every (name, brand) the corpus mentions."""
    pool: set[tuple[str, str]] = set()
    for item in S.cases():
        i, k = item["input"], item["kind"]
        if k == "name_relation":
            pool |= {(i["subject_name"], i["subject_brand"]), (i["target_name"], i["target_brand"])}
        elif k == "resolve" and "subjects" in i:
            pool |= {(s["display_name"], s["brand"]) for s in i["subjects"]} | {(t["display_name"], t["brand"]) for t in i["targets"]}
    return sorted(pool)


def _relations(pool) -> dict[tuple, str]:
    out = {}
    for (n1, b1), (n2, b2) in itertools.permutations(pool, 2):
        if P.compact(b1) == P.compact(b2) or P.brand_relation(b1, b2)[0] in ("ALIAS_SAME", "ALIAS_RELABEL"):
            out[(n1, b1, n2, b2)] = P.name_relation(n1, b1, n2, b2)[0]
    return out


def _is_scoped_synonym(n1, b1, n2, b2) -> bool:
    """Independent of the evaluator: do the two compact names form a pair of an entry scoped by `brands`, for this brand?"""
    for entry in S.policy()["aliases"]["model"]:
        if entry.get("brands") and P.compact(b1) in {P.compact(b) for b in entry["brands"]} and P.compact(b2) in {P.compact(b) for b in entry["brands"]}:
            for a, b in entry["pairs"]:
                if {P.compact(n1), P.compact(n2)} == {P.compact(a), P.compact(b)}:
                    return True
    return False


def test_no_name_pair_became_more_permissive_and_new_equal_pairs_are_the_synonyms():
    pool = _name_pool()
    assert len(pool) > 150
    after = _relations(pool)
    with L.rev3_rules():
        before = _relations(pool)
    auto = set(S.policy()["lexical"]["name"]["auto_relations"])
    candidate = set(S.policy()["lexical"]["name"]["candidate_relations"])
    moved = collections.Counter()
    for key, now in after.items():
        was = before[key]
        problem = check_not_looser(was, now, auto, _is_scoped_synonym(*key))
        assert problem is None, f"{key}: {problem}"
        if was != now:
            moved[(was, now)] += 1
        if was in auto:
            assert now == was, f"{key}: an AUTO-eligible relation changed ({was} -> {now})"
        if now in candidate and was not in candidate:
            assert now == "EQUAL_VIA_MODEL_ALIAS", f"{key}: became a candidate relation without being a synonym ({was} -> {now})"
    assert moved[("FUZZY", "CONTRADICTION")] and moved[("SIBLING", "CONTRADICTION")] and moved[("CONTRADICTION", "EQUAL_VIA_MODEL_ALIAS")], dict(moved)
    assert set(moved) <= DEMOTIONS | {("CONTRADICTION", "EQUAL_VIA_MODEL_ALIAS"), ("SIBLING", "EQUAL_VIA_MODEL_ALIAS")}, dict(moved)


def test_the_invariant_checker_rejects_a_loosening():
    """The check above would fail if a rule were loosened: it is not vacuous."""
    auto = {"EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV"}
    for before, after in (("CONTRADICTION", "FUZZY"), ("SIBLING", "FUZZY"), ("CONTRADICTION", "SIBLING"), ("SIBLING", "EQUAL"), ("FUZZY", "EQUAL"),
                          ("SUBJECT_COARSER", "FUZZY"), ("CONTRADICTION", "EQUAL_VIA_TOKEN_EQUIV")):
        assert check_not_looser(before, after, auto, False), (before, after)
    assert check_not_looser("CONTRADICTION", "EQUAL_VIA_MODEL_ALIAS", auto, False), "a model alias that is not a scoped synonym is a loosening"
    assert check_not_looser("CONTRADICTION", "EQUAL_VIA_MODEL_ALIAS", auto, True) is None
    assert check_not_looser("SIBLING", "CONTRADICTION", auto, False) is None and check_not_looser("FUZZY", "SIBLING", auto, False) is None


def test_a_demotion_and_its_survivor_are_both_in_the_corpus():
    """SPEC I19: a change to the ladder ships rows for each demoted pair AND for the case that survives it."""
    by_tax = collections.defaultdict(list)
    for item in S.cases():
        for tax in item["taxonomy"]:
            by_tax[tax].append(item["id"])
    for tax in ("NAME-14", "NAME-15", "NAME-16"):
        assert any(i.startswith("name_relation.") for i in by_tax[tax]) and any(i.startswith("resolve.") for i in by_tax[tax]), tax
    assert sum(i.startswith("resolve.") for i in by_tax["NAME-17"]) >= 7, "NAME-17 (a tightening never promotes) is a decision-level class"
    demoted = {c["id"] for c in S.cases() if c["kind"] == "name_relation" and c["expect"]["relation"] == "CONTRADICTION" and "NAME-15" in c["taxonomy"]}
    kept = {c["id"] for c in S.cases() if c["kind"] == "name_relation" and c["expect"]["relation"] == "SIBLING" and "NAME-15" in c["taxonomy"]}
    assert len(demoted) >= 15 and len(kept) >= 6


# ---------------------------------------------------------------------------------------------------------------------------------------------- 3. every resolve case
def _outcomes(case) -> dict[str, tuple]:
    res = P2.resolve(case["input"])
    if "refusal" in res:
        return {}
    return {sid: (d["outcome"], tuple(d.get("target_ids", [])), "NAME_EQUAL_VIA_MODEL_ALIAS" in {c for c, _ in d["codes"]}) for sid, d in res["decisions"].items()}


def test_no_resolve_case_gains_an_auto_except_the_listed_synonym_cases():
    cases = [c for c in S.cases() if c["kind"] == "resolve" and "refusal" not in c["expect"]]
    assert len(cases) > 100
    after = {c["id"]: _outcomes(c) for c in cases}
    with L.rev3_rules():
        before = {c["id"]: _outcomes(c) for c in cases}
    newly_auto = set()
    for cid, subjects in after.items():
        for sid, (outcome, targets, via_alias) in subjects.items():
            was = before[cid].get(sid)
            if outcome == "AUTO" and (was is None or was[0] != "AUTO"):
                newly_auto.add(cid)
                assert via_alias, f"{cid}/{sid}: became AUTO without a model synonym ({was} -> {outcome})"
            if was and was[0] == "AUTO":
                assert outcome == "AUTO" or outcome in ("PROPOSE", "AMBIGUOUS", "NO_CANDIDATE", "STRUCTURAL_REVIEW", "INSUFFICIENT_DATA", "PROTECTED_HOLD", "SUPPRESSED"), (cid, sid)
    assert newly_auto == SYNONYM_AUTO_CASES, f"new AUTO outcomes must be listed deliberately: {sorted(newly_auto ^ SYNONYM_AUTO_CASES)}"


def test_the_uncertain_cases_the_pass_was_about_are_never_auto_and_a_survivor_is_never_promoted():
    for cid in ("resolve.lex-mazda6e-is-not-mazda6", "resolve.lex-mazda2-is-not-mazda3", "resolve.lex-hino-chassis-code-is-not-a-typo", "resolve.lex-hr-v-is-not-wr-v",
                "resolve.lex-ioniq-5-is-a-sibling-of-ioniq-6", "resolve.lex-version-typo-does-not-outrank-the-right-name", "resolve.lex-jazz-fit-outside-honda-is-no-candidate"):
        case = next(c for c in S.cases() if c["id"] == cid)
        for sid, (outcome, _targets, _alias) in _outcomes(case).items():
            assert outcome != "AUTO", f"{cid}/{sid}"
    # the survivor: with the wrong strong-series neighbour gone, the right same-name target is PROPOSED on its name and its own (weak) series keeps it from AUTO
    survivor = next(c for c in S.cases() if c["id"] == "resolve.lex-version-typo-does-not-outrank-the-right-name")
    ((outcome, targets, _a),) = _outcomes(survivor).values()
    assert outcome == "PROPOSE" and targets == ("mazda_mazda2",)
    with L.rev3_rules():
        ((was, was_targets, _a),) = _outcomes(survivor).values()
    assert (was, was_targets) == ("PROPOSE", ("mazda_mazda3",)), "rev 3 proposed the wrong, digit-differing target on its strong series"


# ---------------------------------------------------------------------------------------------------------------------------------------------- 4. the committed measurements
def _committed():
    return json.loads((L.DIR / "before_rev3.json").read_text(encoding="utf-8")), json.loads((L.DIR / "after_rev4.json").read_text(encoding="utf-8"))


def test_the_committed_report_is_what_the_measurements_render_to():
    before, after = _committed()
    assert (L.DIR / "LEXICAL_PASS_REPORT.md").read_text(encoding="utf-8") == L.render_report(before, after), "run: python -m identity_resolution.calibration.lexical_pass report"
    assert json.loads((L.DIR / "comparison.json").read_text(encoding="utf-8")) == L.compare(before, after)


def test_the_committed_measurements_respect_the_invariant():
    before, after = _committed()
    c = L.compare(before, after)
    # relations that must not move at all
    for pop in ("ice_ice", "ice_tdr"):
        for relation in ("EQUAL", "EQUAL_VIA_TOKEN_EQUIV", "SUBJECT_COARSER", "SUBJECT_FINER", "UNAVAILABLE"):
            assert before[pop]["relations"][relation] == after[pop]["relations"][relation], (pop, relation)
        assert after[pop]["fuzzy"]["differing_token_has_digit"] == 0 and after[pop]["sibling"]["only_non_distinctive_shared_tokens"] == 0
        # the independent oracle predicts the engine's counts: FUZZY loses exactly its digit pairs, SIBLING loses exactly its descriptor-only pairs and gains the refused typos that share a stem
        moved_to_sibling = c["transitions"][pop].get("FUZZY -> SIBLING", 0)
        assert after[pop]["fuzzy"]["total"] == before[pop]["fuzzy"]["total"] - before[pop]["fuzzy"]["differing_token_has_digit"], pop
        assert after[pop]["sibling"]["total"] == before[pop]["sibling"]["total"] - before[pop]["sibling"]["only_non_distinctive_shared_tokens"] + moved_to_sibling, pop
        for move in c["transitions"][pop]:
            old, _, new = move.partition(" -> ")
            assert (old, new) in DEMOTIONS | {("(other)", "EQUAL_VIA_MODEL_ALIAS")} or (old, new) in {("FUZZY", "(other)"), ("SIBLING", "(other)")}, move
    # decisions: AUTO is the same set; a changed decision is never a new AUTO
    assert c["auto"]["same_set"] and not c["auto"]["newly_auto"] and not c["auto"]["no_longer_auto"]
    synonym_subjects = {k.rsplit("|", 1)[0] for k in c["synonym_pairs"]["ice_tdr"]}
    for change in c["changed_decisions"]:
        assert change["after"][0] != "AUTO" or change["group"] in synonym_subjects, change
    assert {d["group"] for d in c["changed_decisions"]} == {"mazda-mazda6e", "honda-honda-stepwagon"}


@needs_package
def test_the_committed_before_and_after_are_what_the_code_produces_today():
    before, after = _committed()
    live_after = L.measure("rev4")
    with L.rev3_rules():
        live_before = L.measure("rev3")
    for key in before:
        if key not in ("label", "policy"):
            assert live_before[key] == before[key], f"before_rev3.json is stale or edited ({key})"
    for key in after:
        if key not in ("label", "policy"):
            assert live_after[key] == after[key], f"after_rev4.json is stale ({key}); run: python -m identity_resolution.calibration.lexical_pass measure --label rev4 --out ..."
    assert live_after["policy"]["fuzzy_token"]["allow_tokens_with_digits"] is False and "honda_model_synonyms" in live_after["policy"]["model_aliases"]
    assert "honda_model_synonyms" not in before["policy"]["model_aliases"] and before["policy"]["fuzzy_token"]["allow_tokens_with_digits"] is True
    assert before["policy"]["distinctive_token_required_for"] == [] and after["policy"]["distinctive_token_required_for"] == ["SIBLING"]


@needs_package
def test_on_the_real_snapshot_no_group_gains_an_auto_and_the_auto_groups_are_unchanged():
    before, after = _committed()
    assert after["decision_summary"]["auto_groups"] == before["decision_summary"]["auto_groups"] and len(before["decision_summary"]["auto_groups"]) == 69
    synonym_groups = {key.rsplit("|", 1)[0] for key, rel in after["ice_tdr_relation_pairs"].items() if rel == "EQUAL_VIA_MODEL_ALIAS"}
    for gid, now in after["decisions"].items():
        was = before["decisions"][gid]
        if now[0] == "AUTO" and was[0] != "AUTO":
            assert gid in synonym_groups, f"{gid}: {was[:2]} -> {now[:2]} without a synonym"
        if now != was:
            assert now[0] != "AUTO" or gid in synonym_groups
