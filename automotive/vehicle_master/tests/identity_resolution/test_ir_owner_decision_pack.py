"""The Owner Decision & Calibration Preparation Pack (`calibration/owner_decision_pack/`) is consistent, resolvable, reproducible and decides nothing.

What is pinned:

  * the committed pack is exactly what `owner_decision_pack build` produces from committed files (no package needed), and its manifest pins every file;
  * the vendored PR #201 files are byte copies (git blob ids and sha256 recorded); no PR #201 code is imported;
  * every owner field in every file is blank, every machine suggestion is in a `*_NON_AUTHORITATIVE` column, `adoption.binding` is false;
  * every evidence reference in every row resolves to a real record;
  * the nine catalog-alias collisions, the eleven brand cases, the 82 CREATE candidates and the 560 R6 rows are all present exactly once, and the R6 sheet / CREATE set reconcile;
  * the two verdict vocabularies stay apart: `check_label_consistency` flags only labels that cannot both be true;
  * brand folds never split a brand family, the negative sample is a weighted deterministic stratified sample, and the first wave is small.

Everything not marked `needs_package` runs from committed files only. Nothing here changes a rule, a policy value, the export or any sheet.
"""
from __future__ import annotations

import ast
import collections
import csv
import functools
import hashlib
import io
import json
import re
import subprocess
from pathlib import Path

import pytest

import ir_support as S  # noqa: F401  (puts the package on sys.path like the sibling tests)
from identity_resolution.calibration import adapters as A
from identity_resolution.calibration import owner_decision_pack as O
from identity_resolution.calibration import ref_eval_core as P
from identity_resolution.calibration import relation_export as E

OUT = O.OUT
PACKAGE = A.REPO_ROOT / A.PACKAGE_RELATIVE
needs_package = pytest.mark.skipif(not PACKAGE.exists(), reason="the archived M7.0 package is not in this checkout")


@functools.lru_cache(maxsize=None)
def inp() -> O.Inputs:
    return O.Inputs()


@functools.lru_cache(maxsize=None)
def tables() -> dict:
    return O.build_tables(inp())


@functools.lru_cache(maxsize=None)
def pack_csv(name: str) -> tuple:
    text = (OUT / name).read_text(encoding="utf-8")
    return tuple(csv.DictReader(io.StringIO(text, newline="")))


def manifest() -> dict:
    return json.loads((OUT / "MANIFEST.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------------------------------------------------- reproducibility and provenance
def test_committed_pack_is_what_build_produces():
    assert O.verify() == []


def test_manifest_pins_every_file_and_every_input():
    m = manifest()
    for name, info in m["files"].items():
        data = (OUT / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == info["sha256"] and len(data) == info["bytes"], name
    on_disk = {p.name for p in OUT.iterdir() if p.is_file()} - {"MANIFEST.json"}
    assert on_disk == set(m["files"]), "every file of the pack is in the manifest and nothing else is"
    assert m["export_manifest_sha256"] == O.sha256_file(E.OUT / "MANIFEST.json"), "built from the accepted export"
    assert m["r6_owner_review_sha256"] == O.sha256_file(A.CALIBRATION_DIR / "r6_owner_review.csv"), "built from the unchanged R6 sheet"
    assert m["series_evidence_sha256"] == O.sha256_file(O.SERIES_JSON)
    assert m["binding"] is False and inp().adoption["binding"] is False


def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def test_vendored_pr201_files_are_byte_pins():
    prov = json.loads((O.IN201 / "PROVENANCE.json").read_text(encoding="utf-8"))
    assert prov["commit"] == O.PR201_COMMIT == "30d2618a48b830b4afdbcf1299475f368bd9d214" and prov["pr"] == 201
    assert set(prov["files"]) == set(O.PR201_FILES) and json.loads(O.PR201_SOURCES.read_text(encoding="utf-8"))["commit"] == O.PR201_COMMIT
    for name, info in prov["files"].items():
        data = (O.IN201 / name).read_bytes()
        assert O.sha256_bytes(data) == info["sha256"] and len(data) == info["bytes"], name
        assert git_blob_id(data) == info["git_blob"], f"{name} is not the git blob PR #201 accepted"
    assert {p.name for p in O.IN201.iterdir()} == set(O.PR201_FILES) | {"PROVENANCE.json"}


def test_pack_imports_no_pr201_code_and_no_second_matcher():
    tree = ast.parse(Path(O.__file__).read_text(encoding="utf-8"))
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not [m for m in mods if "identity_bootstrap" in m or "shadow" in m], mods
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "name_relation" not in names and "series_evidence" in names, "the pack quotes the evaluator's series evidence and implements no name matcher"


@needs_package
def test_series_evidence_regenerates_from_the_archived_package():
    assert O.canonical_json(O.collect_series_evidence()) == O.SERIES_JSON.read_bytes()


# ---------------------------------------------------------------------------------------------------------------------------------------- nothing decided
def test_every_owner_field_is_blank_and_declared():
    for name, owner_cols in O.OWNER_FIELDS.items():
        rows = pack_csv(name)
        assert rows, name
        for r in rows:
            assert [c for c in r if c.startswith("owner_")] == owner_cols, name
            assert all(r[c] == "" for c in owner_cols), f"{name}: {r.get('decision_id') or r.get('item_id') or r.get('sample_id')}"
    for name, (cols, _) in O.FILES.items():
        if name not in O.OWNER_FIELDS:
            assert not [c for c in cols if c.startswith("owner_")], f"{name} must not carry an owner field"


def test_r6_owner_sheet_is_untouched_and_blank():
    rows = inp().r6
    assert len(rows) == 560
    assert all(r["owner_verdict"] == "" and r["owner_link_type"] == "" and r["owner_canonical_model_id"] == "" and r["owner_notes"] == "" for r in rows)
    assert all(r["owner_verdict"] == "" and r["owner_canonical_model_id"] == "" and r["owner_discovery_class"] == "" for r in inp().adj)


def test_machine_suggestions_are_marked_non_authoritative():
    for name, (cols, _) in O.FILES.items():
        for c in cols:
            if re.search(r"(machine|suggest|recommend|options)", c, re.I):
                assert c.endswith("_NON_AUTHORITATIVE") or c in ("machine_expectation_NON_AUTHORITATIVE",), f"{name}: {c}"
    text = (OUT / "OWNER_DECISION_PACK.md").read_text(encoding="utf-8")
    assert "Nothing here is decided, calibrated, approved or bound" in text and "binding = false" in text


# ---------------------------------------------------------------------------------------------------------------------------------------- every reference resolves
@functools.lru_cache(maxsize=None)
def indexes() -> dict:
    i = inp()
    series = i.series
    return {
        "relation_export/pairs_ice_tdr.jsonl": {f"{a} -> {b}" for (a, b) in i.pairs_tdr},
        "relation_export/ice_subjects.jsonl": set(i.subjects),
        "create_adjudication.csv(PR201)": set(i.create_ids),
        "inputs/tdr_models.json": set(i.models),
        "r6_owner_review.csv": {r["review_rank"] for r in i.r6},
        "r6_calibration_groups.csv": set(i.groups),
        "owner_decision_pack/inputs/series_evidence.json": set(series["pairs"]) | set(series["subjects"]),
        "owner_decision_pack/inputs/pr201_30d2618a4/parity_unresolved.csv": {r["external_id"] for r in i.unresolved},
        "owner_decision_pack/inputs/pr201_30d2618a4/cross_brand_review.csv": {r["external_id"] for r in i.cross_brand},
        "owner_decision_pack/inputs/pr201_30d2618a4/decisions.csv": set(i.bootstrap),
    }


def resolve_ref(r: str) -> bool:
    file, key = r.split("#", 1)
    if file == "contract/v1/policy.yaml":
        node = inp().policy
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        return True
    if file.startswith("vehreg/data/2026/models/"):
        brand = Path(file).stem
        m = re.fullmatch(r"models\[id=(.+)\]", key)
        return brand in inp().brand_files and any(x.get("id") == m.group(1) for x in inp().brand_files[brand]["models"])
    idx = indexes()[file]
    if file == "owner_decision_pack/inputs/series_evidence.json":
        m = re.fullmatch(r"(pairs|subjects)\[(.+)\]", key)
        return m.group(2) in idx
    k = key.split("=", 1)[1]
    return k in idx


def test_every_evidence_reference_resolves():
    n = 0
    for name in ("catalog_alias_collisions.csv", "brand_resolution_cases.csv", "create_candidates.csv", "r6_priority_view.csv", "negative_sample.csv"):
        for r in pack_csv(name):
            for ref in r["evidence_refs"].split(O.REF_SEP):
                n += 1
                assert resolve_ref(ref), f"{name}: {ref}"
    assert n > 1500


def test_decision_ids_are_unique_and_queue_covers_each_item_once():
    t = tables()
    ids = [r["decision_id"] for r in t["alias"]] + [r["decision_id"] for r in t["brand"]] + [r["decision_id"] for r in t["create"]]
    assert len(ids) == len(set(ids)) == 9 + 11 + 82
    q = collections.Counter((r["item_kind"], r["item_id"]) for r in t["queue"])
    assert max(q.values()) == 1
    expected = {("ALIAS_ROW", r["decision_id"]) for r in t["alias"]} | {("BRAND_CASE", r["decision_id"]) for r in t["brand"]} | {("CREATE_ROW", r["decision_id"]) for r in t["create"]} \
        | {("R6_ROW", f"R6-{r['review_rank']}") for r in t["view"]} | {("NEGATIVE_SAMPLE", r["sample_id"]) for r in t["neg"]} | {(i["kind"], i["item_id"]) for i in t["init"]}
    assert set(q) == expected
    assert [r["queue_position"] for r in t["queue"]] == list(range(1, len(t["queue"]) + 1)) and [r["wave"] for r in t["queue"]] == sorted(r["wave"] for r in t["queue"])


# ---------------------------------------------------------------------------------------------------------------------------------------- reconciliation of the R6 sheet and the 82
def test_the_82_candidates_are_pr201s_and_reconcile_with_the_sheet():
    t = tables()
    assert [r["provider_group_id"] for r in t["create"]].__len__() == 82
    assert {r["provider_group_id"] for r in t["create"]} == set(inp().create_ids)
    sheet_groups = {r["model_group_id"] for r in inp().r6}
    in_sheet = {r["provider_group_id"] for r in t["recon"] if r["in_r6_sheet"] == "yes"}
    assert in_sheet == set(inp().create_ids) & sheet_groups and len(in_sheet) == 47
    rows_for = collections.Counter(r["provider_group_id"] for r in t["recon"])
    for g in inp().create_ids:
        assert rows_for[g] == max(1, len(inp().r6_by_group.get(g, []))), g
    assert {r["r6_review_rank"] for r in t["recon"] if r["in_r6_sheet"] == "yes"} == {r["review_rank"] for r in inp().r6 if r["model_group_id"] in set(inp().create_ids)}
    # the four candidates inside the first 176 rows
    assert {r["model_group_id"] for r in inp().r6[:176]} & set(inp().create_ids) == {"audi-audi-a8l", "jaecoo-jaecoo-j7", "wuling-binguo", "zeekr-zeekr-7x"}


def test_every_create_candidate_still_has_no_candidate_in_the_export():
    for g in inp().create_ids:
        assert inp().subjects[g]["outcome"]["outcome"] == "NO_CANDIDATE", g
        assert inp().adj_by_id[g]["ir_dry_run_outcome"].startswith("NO_CANDIDATE")


def test_create_risk_tiers_follow_the_stated_rules():
    for r in tables()["create"]:
        cats = set(r["risk_categories"])
        p1 = bool(cats & {"CATALOG_ALIAS_COLLISION", "CROSS_BRAND_COLLISION", "SERIES_COINCIDES_WITH_POOL_MODEL", "LEGACY_R6_STRONG_PROPOSAL"})
        p2 = bool(cats & {"CURRENT_MARKET", "HIGH_VOLUME", "CODE_LIKE_NAME"})
        assert r["risk_tier"] == ("P1_CONTRADICTING_EVIDENCE" if p1 else "P2_HIGH_IMPACT_OR_AMBIGUOUS" if p2 else "P3_HISTORICAL_BULK"), r["provider_group_id"]
    t = collections.Counter(r["risk_tier"] for r in tables()["create"])
    assert sum(t.values()) == 82
    spot = [r for r in tables()["create"] if r["p3_spot_check_sample"] == "yes"]
    assert len(spot) == O.SPOT_CHECK_N and all(r["risk_tier"].startswith("P3") for r in spot)


# ---------------------------------------------------------------------------------------------------------------------------------------- section A
def test_alias_rows_carry_the_exact_catalog_records():
    rows = tables()["alias"]
    assert len(rows) == 9 and [r["decision_id"] for r in rows] == [f"OD-A{i:02d}" for i in range(1, 10)]
    flagged = {r["external_id"] for r in inp().adj if "POSSIBLE_EXISTING_IDENTITY_CATALOG_ALIAS" in r["review_routing_flags"].split("|")}
    assert {r["provider_group_id"] for r in rows} == flagged
    assert [int(r["provider_units_lifetime"]) for r in rows] == sorted((int(r["provider_units_lifetime"]) for r in rows), reverse=True)
    for r in rows:
        tid = r["existing_identity_id"]
        m = inp().models[tid]
        cat = next(x for x in inp().brand_files[m["brand_id"]]["models"] if x["id"] == tid.split(".", 1)[1])
        assert cat["name_en"] == r["existing_identity_name_en"] and list(cat.get("aliases", [])) == list(r["existing_identity_all_aliases"]) == list(m["aliases"])
        for a in r["matching_alias_strings"]:
            assert any(P.compact(a) == P.compact(x) for x in m["aliases"]), (tid, a)
            assert P.compact(a) in P.compact(r["provider_name"]) or P.compact(r["provider_name"]) in P.compact(a)
        assert r["export_name_relation"] == inp().pairs_tdr[(r["provider_group_id"], tid)]["r"]
        assert r["machine_suggested_alias_class_NON_AUTHORITATIVE"] in O.ALIAS_CLASSES
        assert r["machine_suggested_alias_class_NON_AUTHORITATIVE"] != "SEARCH_DISPLAY_SYNONYM", "the data cannot tell a lookup convenience from an identity claim"


def test_alias_classes_are_not_all_equal():
    classes = collections.Counter(r["machine_suggested_alias_class_NON_AUTHORITATIVE"] for r in tables()["alias"])
    assert len(classes) >= 3 and classes["IDENTITY_EQUIVALENT"] < 9


def test_series_coincident_candidates_without_an_alias_hit_are_listed():
    t = tables()
    extra = sorted(r["provider_group_id"] for r in t["create"] if r["series_coincident_targets"] and not r["alias_decision_id"])
    assert extra == ["jaecoo-jaecoo-j6", "volt-volt-volt"]
    assert all(r["also_series_coincident_without_alias_hit"] == extra for r in t["alias"])
    for r in t["create"]:
        for tgt in r["series_coincident_targets"]:
            s = O.series_for(inp(), r["provider_group_id"], tgt)
            assert s["state"] == "STRONG" and s["common_months"] >= O.TRIAGE["series_coincide_min_common_months"]


def test_parse_routing_evidence_reads_every_row_completely():
    n = 0
    for r in inp().adj:
        text = r["review_routing_evidence"]
        items = O.parse_routing_evidence(text)
        assert len(items) == text.count("(") == text.count(")"), r["external_id"]
        n += len(O.alias_hits(r))
    assert n == 10, "nine groups; one of them (the J5) matches two aliases"


# ---------------------------------------------------------------------------------------------------------------------------------------- section B
def test_brand_cases_cover_unresolved_rows_and_the_maxus_collision():
    rows = tables()["brand"]
    assert len(rows) == 11
    assert [r["provider_group_id"] for r in rows if r["case_kind"] == "UNRESOLVED_PARITY"] == sorted(r["external_id"] for r in inp().unresolved) and sum(r["case_kind"] == "UNRESOLVED_PARITY" for r in rows) == 8
    assert "maxus-maxus-v80" in {r["provider_group_id"] for r in rows}
    for r in rows:
        assert r["recommended_resolution_NON_AUTHORITATIVE"] and r["contract_level_options_NON_AUTHORITATIVE"]
        text = (r["recommended_resolution_NON_AUTHORITATIVE"] + r["contract_level_options_NON_AUTHORITATIVE"]).lower()
        assert not re.search(r"\b(jetour|chery|mercedes|range rover|maybach)\b", text), "recommendations are contract-level: no brand is named in a rule"


def test_brand_case_directions_agree_with_pr201s_reasons():
    for r in tables()["brand"]:
        reason = r["pr201_parity_reason"]
        if not reason:
            continue
        shadow_resolves = "the shadow resolves the brand to a TDR brand but" in reason
        assert shadow_resolves == (r["consumer_catalog_label_resolution"] != "none"), r["provider_group_id"]
        export_has_pool = "the export has a pool but" in reason
        assert export_has_pool == (r["producer_pool_size"] > 0), r["provider_group_id"]
        assert export_has_pool == bool(r["producer_brand_relations"]), r["provider_group_id"]


def test_producer_relations_are_the_evaluators_and_related_is_never_auto_eligible():
    pol = inp().policy["candidates"]
    assert "ALIAS_RELATED" in pol["brand_relations_allowed"] and "ALIAS_RELATED" not in pol["brand_relations_auto_eligible"]
    for r in tables()["brand"]:
        for rel in r["producer_brand_relations"]:
            brand, relation = rel.split(":")[:2]
            assert relation in ("EXACT", "ALIAS_SAME", "ALIAS_RELABEL", "ALIAS_RELATED")
            s = inp().subjects[r["provider_group_id"]]
            assert P.brand_relation(s["brand"], inp().brands[brand]["name_en"], tuple(s["brands_observed"]))[0] == relation


# ---------------------------------------------------------------------------------------------------------------------------------------- section C: R6 view, folds, starter batch
def test_r6_view_has_every_sheet_row_in_sheet_order():
    view = tables()["view"]
    assert [r["review_rank"] for r in view] == [r["review_rank"] for r in inp().r6] and len(view) == 560
    assert sum(r["in_first_176"] == "yes" for r in view) == 176 and all(r["in_first_176"] == ("yes" if int(r["review_rank"]) <= 176 else "no") for r in view)
    first = [r for r in inp().r6[:176]]
    assert collections.Counter(r["review_tier"] for r in first) == {"1": 82, "2": 94}


def test_brand_folds_never_split_a_brand_family():
    t = tables()
    by_family = collections.defaultdict(set)
    for r in t["view"]:
        by_family[r["brand_family"]].add(r["fold"])
    assert all(len(f) == 1 for f in by_family.values())
    # brands tied by a policy brand alias class share a family and therefore a fold
    for a in inp().policy["aliases"]["brand"]:
        present = [r for r in t["view"] if any(P.compact(m) == P.compact(r["ice_brand"]) for m in a["members"])]
        assert len({r["brand_family"] for r in present}) <= 1 and len({r["fold"] for r in present}) <= 1, a["id"]
    assert set(range(O.TRIAGE["folds"])) == {r["fold"] for r in t["view"]}
    weights = t["meta"]["fold_weights"]
    assert max(weights) - min(weights) <= 2 and sum(weights) == 560
    folds = {r["brand_family"]: int(r["fold"]) for r in pack_csv("brand_folds.csv")}
    assert set(by_family) <= set(folds) and all(folds[f] in fs for f, fs in by_family.items())
    for r in t["create"] + t["neg"]:
        assert folds[r["brand_family"]] == int(r["fold"]) and 0 <= int(r["fold"]) < O.TRIAGE["folds"]


def test_assign_folds_is_deterministic_and_balanced():
    items = {f"f{i}": float(w) for i, w in enumerate([9, 8, 7, 3, 3, 2, 2, 1, 1, 1])}
    a, b = O.assign_folds(items, 3), O.assign_folds(dict(reversed(list(items.items()))), 3)
    assert a == b
    load = collections.Counter()
    for k, f in a.items():
        load[f] += items[k]
    assert max(load.values()) - min(load.values()) <= 3


def test_starter_batch_definition_and_size():
    t = tables()
    view, meta = t["view"], t["meta"]
    s1 = [r for r in view if "S1_AUTO_PAIRS" in r["starter_batch"]]
    auto = [r for r in view if r["v1_group_outcome"] == "AUTO" and r["candidate_is_v1_primary"] == "yes"]
    assert len(auto) == 69 == meta["auto_pairs"] and all(r["v1_group_outcome"] == "AUTO" for r in s1)
    assert sum(r["ice_lifetime_units"] for r in s1) >= O.STARTER_FRACTION * sum(r["ice_lifetime_units"] for r in auto)
    smallest = sorted(auto, key=lambda r: (-r["ice_lifetime_units"], int(r["review_rank"])))[:len(s1) - 1]
    assert sum(r["ice_lifetime_units"] for r in smallest) < O.STARTER_FRACTION * sum(r["ice_lifetime_units"] for r in auto), "S1 is the smallest prefix reaching the coverage"
    s4 = {r["review_tier"] for r in view if "S4_STRUCTURAL" in r["starter_batch"]}
    assert s4 == {"5", "6"} and sum("S4_STRUCTURAL" in r["starter_batch"] for r in view) == 9
    s3 = [r for r in view if "S3_KNOWN_FAMILY" in r["starter_batch"]]
    assert len(s3) == 7 == len(inp().summary["review_sheet"]["suspicious_case_rows"])
    distinct = {r["review_rank"] for r in view if r["starter_batch"]}
    assert len(distinct) == meta["s1"] + meta["s2"] + meta["s3"] + meta["s4"] - 1 or len(distinct) < 60
    assert len(distinct) < 560 / 5


def test_first_wave_is_small_and_names_what_it_resolves():
    t = tables()
    st = t["istats"]
    assert st["owner_actions"] < 100 and st["owner_actions"] == st["contract_questions"] + st["alias_verdicts"] + st["create_verdicts"] + st["r6_rows_alone"]
    init_ids = {i["item_id"] for i in t["init"]}
    assert {"INIT-01", "INIT-02", "INIT-03", "INIT-04"} <= init_ids
    resolved = {x for i in t["init"] for x in i["resolves"]}
    assert {r["decision_id"] for r in t["brand"]} <= resolved, "every brand case is closed by a contract-level answer"
    assert "OD-C11" in resolved and {"OD-C04", "OD-C06"} <= resolved
    assert all(i["owner_answer"] == "" for i in t["init"])


# ---------------------------------------------------------------------------------------------------------------------------------------- two verdict vocabularies
def test_vocabularies_match_their_sources():
    assert O.CREATE_VERDICTS == ["VALID_MISSING_CANONICAL", "EXISTING_IDENTITY", "VARIANT_TRIM_CODE", "AMBIGUOUS"]
    head = (O.IN201 / "create_adjudication.csv").read_text(encoding="utf-8").splitlines()[0]
    assert all(v in head for v in O.CREATE_VERDICTS) and all(v in head for v in O.DISCOVERY_CLASSES)
    sheet_doc = (A.CALIBRATION_DIR / "DATA_DICTIONARY.md").read_text(encoding="utf-8") + (A.CALIBRATION_DIR / "README.md").read_text(encoding="utf-8")
    assert all(v in sheet_doc for v in O.R6_VERDICTS)
    assert not set(O.R6_VERDICTS) & set(O.CREATE_VERDICTS)


def lab(group="g", cand="t.a", verdict="CORRECT_EQUIVALENT", link="EQUIVALENT", canon=""):
    return {group: [{"candidate": cand, "verdict": verdict, "link_type": link, "canonical": canon}]}


def kinds(res):
    return {(r["severity"], r["kind"]) for r in res}


def test_check_label_consistency_flags_only_labels_that_cannot_both_be_true():
    ids = {"t.a", "t.b"}
    c = O.check_label_consistency
    assert c(lab(), {"g": {"verdict": "EXISTING_IDENTITY", "canonical": "t.a"}}, ids) == []
    assert ("CONFLICT", "PAIR_AND_GROUP_VERDICT_CONTRADICT") in kinds(c(lab(), {"g": {"verdict": "VALID_MISSING_CANONICAL"}}, ids))
    assert ("CONFLICT", "GROUP_TARGET_DIFFERS_FROM_CORRECT_PAIR") in kinds(c(lab(), {"g": {"verdict": "EXISTING_IDENTITY", "canonical": "t.b"}}, ids))
    assert c(lab(verdict="WRONG_TARGET", link=""), {"g": {"verdict": "VALID_MISSING_CANONICAL"}}, ids) == [], "a wrong target leaves the missing-identity question open"
    assert c(lab(verdict="WRONG_TARGET", link=""), {"g": {"verdict": "EXISTING_IDENTITY", "canonical": "t.b"}}, ids) == []
    assert ("CONFLICT", "GROUP_TARGET_IS_THE_WRONG_TARGET") in kinds(c(lab(verdict="WRONG_TARGET", link=""), {"g": {"verdict": "EXISTING_IDENTITY", "canonical": "t.a"}}, ids))
    assert ("CONFLICT", "PAIR_AND_GROUP_VERDICT_CONTRADICT") in kinds(c(lab(verdict="NO_TDR_TARGET", link=""), {"g": {"verdict": "EXISTING_IDENTITY", "canonical": "t.b"}}, ids))
    assert c(lab(verdict="NO_TDR_TARGET", link=""), {"g": {"verdict": "VALID_MISSING_CANONICAL"}}, ids) == []
    assert ("REVIEW", "PAIR_AND_GROUP_VERDICT_NEED_NOTE") in kinds(c(lab(verdict="CORRECT_PART_OF", link="PART_OF"), {"g": {"verdict": "VALID_MISSING_CANONICAL"}}, ids))
    assert c(lab(verdict="INSUFFICIENT_EVIDENCE", link=""), {"g": {"verdict": "AMBIGUOUS"}}, ids) == []


def test_check_label_consistency_structural_conflicts():
    ids = {"t.a", "t.b"}
    c = O.check_label_consistency
    two = {"g": [{"candidate": "t.a", "verdict": "CORRECT_EQUIVALENT", "link_type": "EQUIVALENT"}, {"candidate": "t.b", "verdict": "CORRECT_EQUIVALENT", "link_type": "EQUIVALENT"}]}
    assert ("CONFLICT", "TWO_EQUIVALENT_TARGETS") in kinds(c(two, {}, ids))
    assert ("CONFLICT", "LINK_TYPE_CONTRADICTS_VERDICT") in kinds(c(lab(link="PART_OF"), {}, ids))
    assert ("CONFLICT", "LINK_TYPE_CONTRADICTS_VERDICT") in kinds(c(lab(verdict="CORRECT_COMPOSED_OF", link="EQUIVALENT"), {}, ids))
    assert ("CONFLICT", "EXISTING_IDENTITY_WITHOUT_MODEL") in kinds(c({}, {"g": {"verdict": "EXISTING_IDENTITY"}}, ids))
    assert ("CONFLICT", "UNKNOWN_TDR_MODEL") in kinds(c({}, {"g": {"verdict": "EXISTING_IDENTITY", "canonical": "t.zzz"}}, ids))
    assert ("CONFLICT", "UNKNOWN_GROUP_VERDICT") in kinds(c({}, {"g": {"verdict": "EQUAL"}}, ids))
    assert ("CONFLICT", "UNKNOWN_PAIR_VERDICT") in kinds(c(lab(verdict="MAYBE"), {}, ids))
    assert ("CONFLICT", "WRONG_TARGET_NAMES_ITSELF") in kinds(c(lab(verdict="WRONG_TARGET", link="", canon="t.a"), {}, ids))


def test_crosswalk_table_matches_the_function():
    rows = pack_csv("verdict_crosswalk.csv")
    assert len(rows) == len(O.R6_VERDICTS) * len(O.CREATE_VERDICTS)
    for r in rows:
        assert r["consistent"] == O._crosswalk_reading(r["r6_pair_verdict"], r["create_group_verdict"])[0]
    assert {r["consistent"] for r in rows} >= {"CONFLICT", "REVIEW", "CONSISTENT"}


# ---------------------------------------------------------------------------------------------------------------------------------------- negative sample, thresholds and the procedure
def test_negative_sample_is_a_weighted_deterministic_stratified_sample():
    t = tables()
    rows = t["neg"]
    skip = set(inp().create_ids) | {r["model_group_id"] for r in inp().r6}
    assert rows and not {r["provider_group_id"] for r in rows} & skip
    assert all(inp().subjects[r["provider_group_id"]]["outcome"]["outcome"] == "NO_CANDIDATE" for r in rows)
    by = collections.defaultdict(list)
    for r in rows:
        by[r["stratum"]].append(r)
    for s, rs in by.items():
        info = t["neg_summary"][s]
        assert len(rs) == info["sample"] == rs[0]["stratum_sample_size"] and abs(sum(r["sampling_weight"] for r in rs) - info["population"]) < 1e-3
    pop = sum(v["population"] for v in t["neg_summary"].values())
    assert pop == sum(1 for g, s in inp().subjects.items() if s["outcome"]["outcome"] == "NO_CANDIDATE" and g not in skip)
    again = O.build_negative_sample(inp(), t["meta"])[0]
    assert [r["sample_id"] for r in t["neg"]] == [r["sample_id"] for r in again] and [r["provider_group_id"] for r in t["neg"]] == [r["provider_group_id"] for r in again]


def test_entry_requirements_use_the_stated_arithmetic():
    assert O.rule_of_three(69) == round(3 / 69, 6) and O.rule_of_three(0) is None
    lo, hi = O.wilson(0, 60)
    assert lo == 0.0 and 0.05 < hi < 0.07
    lo, hi = O.wilson(50, 60)
    assert lo < 50 / 60 < hi
    er = {r["requirement_id"]: r for r in pack_csv("calibration_entry_requirements.csv")}
    assert int(er["ER-01"]["value"]) == 69 and float(er["ER-02"]["value"]) == pytest.approx(3 / 69, abs=1e-6)
    assert [int(er[k]["value"]) for k in ("ER-T10", "ER-T05", "ER-T02", "ER-T01")] == [30, 60, 150, 300]
    assert er["ER-T05"]["meaning"].startswith("reachable") and er["ER-T02"]["meaning"].startswith("NOT reachable")


def test_pending_threshold_table_lists_only_unaccepted_calibration_entries_and_the_two_spec_gates():
    rows = pack_csv("pending_threshold_sensitivity.csv")
    names = {r["adoption_entry"] for r in rows}
    accepted = {e["id"] for e in inp().adoption["entries"] if e["status"] == "owner_accepted"}
    assert not names & accepted
    calib = {e["id"] for e in inp().adoption["entries"] if e["class"] == "calibration" and e["status"] != "owner_accepted"}
    assert calib <= names and {"series_strong"} <= names
    swept = {v["id"] for v in inp().sensitivity["variants"] if not v.get("hypothetical")}
    for r in rows:
        assert set(r["variants_run"].split("|") if r["variants_run"] else []) <= swept


def test_calibration_procedure_covers_what_was_asked():
    p = json.loads((OUT / "calibration_procedure.json").read_text(encoding="utf-8"))
    assert p == O.CALIBRATION_PROCEDURE
    text = json.dumps(p).lower()
    for must in ("brand_folds.csv", "auto_precision", "auto_recall", "propose_precision", "propose_or_better_recall", "false_auto_analysis", "pending_threshold_sensitivity", "held-out", "stop_rules"):
        assert must in text, must
    assert "adoption.binding stays false" in text
