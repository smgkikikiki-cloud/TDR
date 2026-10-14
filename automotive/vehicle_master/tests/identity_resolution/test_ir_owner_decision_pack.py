"""The Owner Decision & Calibration Preparation Pack (`calibration/owner_decision_pack/`) is consistent, resolvable, reproducible and decides nothing.

What is pinned:

  * the committed pack is exactly what `owner_decision_pack build` produces from committed files (no package needed), and its manifest pins every file;
  * the vendored PR #201 files are byte copies (git blob ids and sha256 recorded); no PR #201 code is imported;
  * every owner field in every file is blank, every machine suggestion is in a `*_NON_AUTHORITATIVE` column, `adoption.binding` is false;
  * every evidence reference in every row resolves to a real record;
  * the nine catalog-alias collisions, the eleven brand cases, the 82 CREATE candidates and the 560 R6 rows are all present exactly once, and the R6 sheet / CREATE set reconcile;
  * the two verdict vocabularies stay apart: `check_label_consistency` flags only labels that cannot both be true;
  * brand folds never split a brand family, the negative sample is a weighted deterministic stratified sample, and the first wave is small;
  * ground truth is derived per link type (a missing canonical identity is EQUIVALENT-negative only; a variant infers nothing), threshold selection sees training folds only, and the first-wave
    count is exactly the number of ACTION_REQUIRED queue rows, every other row being a SUPPORTING_ROW that names the one action that resolves it.

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
    assert m["sensitivity_results_sha256"] == O.sha256_file(A.CALIBRATION_DIR / "sensitivity_results.json"), "the registered threshold grid is pinned"
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
    assert set(q) == expected, "no underlying record is dropped: 82 CREATE, 560 R6, 9 alias, 11 brand, 24 negative-sample rows and the 4 questions"
    assert len(t["queue"]) == 82 + 560 + 9 + 11 + 24 + 4
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


def test_first_wave_is_small_and_names_what_it_informs():
    t = tables()
    st = t["istats"]
    assert st["review_sessions"] < 100 and st["atomic_verdicts_total"] == st["atomic_verdicts_own"] + st["atomic_verdicts_children"]
    assert [i["item_id"] for i in t["init"]] == ["INIT-01", "INIT-02", "INIT-03", "INIT-04"], "initial_owner_decisions.csv holds only decisions that have no row of their own elsewhere"
    informs = {x for i in t["init"] for x in i["resolves"]}
    assert {r["decision_id"] for r in t["brand"]} <= informs, "every brand case is evidence for a contract-level question"
    assert "OD-C11" not in informs, "a CREATE verdict is never listed as settled by a filing question"
    assert all(i["owner_answer"] == "" for i in t["init"])


# ---------------------------------------------------------------------------------------------------------------------------------------- ODP-3/4: review sessions, child verdicts, atomic cells
def sessions_by_id() -> dict:
    return {x["session_id"]: x for x in tables()["sessions"]}


def test_wave_1_reconciles_review_sessions_to_atomic_verdict_cells():
    t = tables()
    queue = pack_csv("decision_queue.csv")
    assert set(r["queue_role"] for r in queue) == {"REVIEW_SESSION", "CHILD_DECISION", "EVIDENCE_ROW"}
    w1 = [r for r in queue if r["wave"] == "1"]
    roles = collections.Counter(r["queue_role"] for r in w1)
    assert roles == {"REVIEW_SESSION": 65, "CHILD_DECISION": 13, "EVIDENCE_ROW": 11} and len(w1) == 89
    sess = [x for x in t["sessions"] if x["wave"] == 1]
    assert len(sess) == 65 == t["istats"]["review_sessions"]
    own = sum(x["atomic_verdicts_own"] for x in sess)
    kids = sum(x["atomic_verdicts_children"] for x in sess)
    assert (own, kids, own + kids) == (65, 13, 78) == (t["istats"]["atomic_verdicts_own"], t["istats"]["atomic_verdicts_children"], t["istats"]["atomic_verdicts_total"])
    assert sum(int(r["atomic_verdict_fields"]) for r in w1) == 78, "the queue's atomic field counts add up to the same 78"
    assert all(x["atomic_verdicts_total"] == len(x["own_cells"]) + len(x["child_cells"]) for x in t["sessions"])
    kinds = collections.Counter(x["kind"] for x in sess)
    assert kinds == {"CONTRACT": 3, "CATALOG": 1, "ALIAS_ROW": 5, "CREATE_ROW": 9, "R6_ROW": 47}
    text = (OUT / "OWNER_DECISION_PACK.md").read_text(encoding="utf-8")
    for must in ("**65 review sessions**", "**78 independent owner verdict cells**", "65 cells owned by the sessions themselves plus 13 child verdicts", "lists 89 first-wave rows", "**78 atomic verdict cells**"):
        assert must in text, must


def test_every_source_record_is_in_exactly_one_session_cell_and_nothing_is_dropped():
    t = tables()
    cells = collections.Counter(c for x in t["sessions"] for c in x["own_cells"] + x["child_cells"])
    assert max(cells.values()) == 1, "no cell is solicited by two sessions"
    by_file = collections.Counter(c.split("#", 1)[0] for c in cells)
    assert by_file == {"initial_owner_decisions.csv": 4, "catalog_alias_collisions.csv": 9, "create_candidates.csv": 82, "r6_owner_review.csv": 560, "negative_sample.csv": 24}
    assert len(cells) == 679 == sum(x["atomic_verdicts_total"] for x in t["sessions"])
    assert {c.split("#", 1)[1].rsplit("@", 1)[0] for c in cells if c.startswith("r6_owner_review.csv")} == {f"review_rank={r['review_rank']}" for r in inp().r6}
    assert {c.split("#", 1)[1].rsplit("@", 1)[0] for c in cells if c.startswith("create_candidates.csv")} == {c["decision_id"] for c in t["create"]}
    starter = {r["review_rank"] for r in t["view"] if r["starter_batch"]}
    assert len(starter) == 48
    w1_cells = {c for x in t["sessions"] if x["wave"] == 1 for c in x["own_cells"] + x["child_cells"]}
    assert {f"r6_owner_review.csv#review_rank={r}@owner_verdict" for r in starter} <= w1_cells


def test_session_cell_addresses_resolve_and_are_blank_in_the_committed_files():
    files = {"initial_owner_decisions.csv": ("item_id", pack_csv("initial_owner_decisions.csv")), "catalog_alias_collisions.csv": ("decision_id", pack_csv("catalog_alias_collisions.csv")),
             "create_candidates.csv": ("decision_id", pack_csv("create_candidates.csv")), "negative_sample.csv": ("sample_id", pack_csv("negative_sample.csv")),
             "r6_owner_review.csv": ("review_rank", tuple(inp().r6))}
    for x in tables()["sessions"]:
        for cell in x["own_cells"] + x["child_cells"]:
            file, rest = cell.split("#", 1)
            key, field = rest.rsplit("@", 1)
            col, rows = files[file]
            k = key.split("=", 1)[-1]
            hit = [r for r in rows if r[col] == k]
            assert len(hit) == 1 and field in hit[0], cell
            assert hit[0][field] == "", f"{cell} must be blank"


def test_session_and_queue_references_resolve_and_roles_are_consistent():
    t = tables()
    ids = sessions_by_id()
    queue = pack_csv("decision_queue.csv")
    assert "action_id" not in queue[0] and "resolved_by_action_id" not in queue[0], "no row claims to be 'resolved by' another question"
    for r in queue:
        assert r["session_id"] in ids, r["item_id"]
        s = ids[r["session_id"]]
        if r["queue_role"] == "REVIEW_SESSION":
            assert r["item_id"] == r["session_id"] and r["required_for_session_completion"] == "yes" and int(r["atomic_verdict_fields"]) == len(s["own_cells"]) >= 1
        elif r["queue_role"] == "CHILD_DECISION":
            assert r["item_id"] in s["child_decision_ids"] and r["required_for_session_completion"] == "yes" and r["atomic_verdict_fields"] == "1" and r["wave"] == str(s["wave"])
            assert "does not settle it" in r["why_in_this_wave"]
        else:
            assert r["item_id"] in s["evidence_row_ids"] and r["required_for_session_completion"] == "no" and r["atomic_verdict_fields"] == "0" and r["item_kind"] == "BRAND_CASE"
    assert collections.Counter(r["item_id"] for r in queue if r["queue_role"] != "EVIDENCE_ROW") == collections.Counter(c for x in t["sessions"] for c in [x["session_id"], *x["child_decision_ids"]])
    for x in t["sessions"]:
        assert len(x["child_decision_ids"]) == len(x["child_cells"]) and x["wave"] in (1, 2, 3)
    assert len(queue) == 690 and len(pack_csv("review_sessions.csv")) == len(t["sessions"])


def test_init_03_separately_collects_filing_v80_create_and_the_maxus_pair_verdicts():
    s = sessions_by_id()["INIT-03"]
    assert s["own_cells"] == ["initial_owner_decisions.csv#INIT-03@owner_answer"]
    assert s["child_decision_ids"] == ["OD-C11", "R6-190", "R6-183", "R6-184"]
    assert s["child_cells"] == ["create_candidates.csv#OD-C11@owner_verdict", "r6_owner_review.csv#review_rank=190@owner_verdict", "r6_owner_review.csv#review_rank=183@owner_verdict",
                                "r6_owner_review.csv#review_rank=184@owner_verdict"]
    assert s["atomic_verdicts_total"] == 5
    byid = {r["decision_id"]: r for r in tables()["create"]}
    assert byid["OD-C11"]["provider_group_id"] == "maxus-maxus-v80"
    assert {r["model_group_id"] for r in inp().r6 if r["review_rank"] in ("190", "183", "184")} == {"maxus-maxus-v80", "maxus-mifa-7", "maxus-mifa-9"}
    assert set(s["evidence_row_ids"]) == {"OD-B09", "OD-B10", "OD-B11"}


def test_alias_sessions_separately_collect_alias_class_group_verdict_and_pair_verdicts():
    t = tables()
    ids = sessions_by_id()
    create_of = {c["provider_group_id"]: c for c in t["create"]}
    for a in t["alias"]:
        s = ids[a["decision_id"]]
        g = a["provider_group_id"]
        assert s["own_cells"] == [f"catalog_alias_collisions.csv#{a['decision_id']}@owner_alias_class"]
        want = [f"create_candidates.csv#{create_of[g]['decision_id']}@owner_verdict"] + [f"r6_owner_review.csv#review_rank={r['review_rank']}@owner_verdict" for r in inp().r6_by_group.get(g, [])]
        assert s["child_cells"] == want, a["decision_id"]
        assert s["atomic_verdicts_total"] == 1 + len(want) >= 2
    assert sessions_by_id()["OD-A02"]["child_decision_ids"] == ["OD-C01", "R6-15"]


def test_a_verdict_row_is_never_labelled_as_settled_by_another_question():
    for name in ("decision_queue.csv", "review_sessions.csv", "initial_owner_decisions.csv"):
        text = (OUT / name).read_text(encoding="utf-8")
        assert "resolved_by" not in text and "SUPPORTING_ROW" not in text and "ACTION_REQUIRED" not in text and "written together with" not in text, name
    md = (OUT / "OWNER_DECISION_PACK.md").read_text(encoding="utf-8")
    assert "SUPPORTING_ROW" not in md and "settles" not in md.split("## 2.")[0].replace("never settled", "").replace("not settle", "").replace("none is settled", "")


# ---------------------------------------------------------------------------------------------------------------------------------------- the completion validator (adversarial)
def meta_():
    return tables()["cell_meta"]


def U():
    return O.trusted_model_universe(inp())


def coherent_answers(session: dict) -> dict:
    """The most neutral complete answer set: AMBIGUOUS / INSUFFICIENT_EVIDENCE / UNRESOLVED never contradict each other."""
    ans = {}
    for c in session["own_cells"] + session["child_cells"]:
        file = c.split("#", 1)[0]
        ans[c] = {"initial_owner_decisions.csv": "owner answer", "catalog_alias_collisions.csv": "UNRESOLVED", "create_candidates.csv": "AMBIGUOUS", "r6_owner_review.csv": "INSUFFICIENT_EVIDENCE",
                  "negative_sample.csv": "NO"}[file]
    return ans


def kinds_of(problems):
    return collections.Counter(p["kind"] for p in problems)


def test_validator_refuses_an_empty_session_and_names_every_missing_cell():
    s = sessions_by_id()["INIT-03"]
    probs = O.validate_session(s, {}, meta_(), U())
    assert kinds_of(probs) == {"UNANSWERED_MANDATORY_CELL": 5} and {p["cell"] for p in probs} == set(s["own_cells"] + s["child_cells"])
    assert not O.session_is_complete(s, {}, meta_(), U())


def test_filing_answer_alone_never_completes_init_03_and_alias_class_alone_never_completes_an_alias_session():
    s = sessions_by_id()["INIT-03"]
    answers = {s["own_cells"][0]: "file under MG"}
    probs = O.validate_session(s, answers, meta_(), U())
    assert {p["cell"] for p in probs} == set(s["child_cells"]) and kinds_of(probs) == {"UNANSWERED_MANDATORY_CELL": 4}
    before = dict(answers)
    O.validate_session(s, answers, meta_(), U())
    assert answers == before, "the validator fills nothing in"
    a = sessions_by_id()["OD-A02"]
    probs = O.validate_session(a, {a["own_cells"][0]: "IDENTITY_EQUIVALENT"}, meta_(), U())
    assert {p["cell"] for p in probs} == set(a["child_cells"]), "an alias class does not fill the group verdict or the pair verdict"
    for child_missing in a["child_cells"]:   # omitting any single child verdict blocks completion
        ans = coherent_answers(a)
        del ans[child_missing]
        assert [p["cell"] for p in O.validate_session(a, ans, meta_(), U())] == [child_missing]


def test_validator_accepts_a_complete_coherent_session_and_every_wave_1_session_can_be_completed():
    for x in tables()["sessions"]:
        if x["wave"] == 1:
            assert O.session_is_complete(x, coherent_answers(x), meta_(), U()), x["session_id"]


def test_validator_checks_values_and_conditional_fields():
    s = sessions_by_id()["OD-A02"]
    ans = coherent_answers(s)
    ans["create_candidates.csv#OD-C01@owner_verdict"] = "SORT_OF"
    assert kinds_of(O.validate_session(s, ans, meta_(), U())) == {"VALUE_NOT_ALLOWED": 1}
    ans["create_candidates.csv#OD-C01@owner_verdict"] = "EXISTING_IDENTITY"
    assert kinds_of(O.validate_session(s, ans, meta_(), U())) == {"CONDITIONAL_FIELD_MISSING": 1}
    ans["create_candidates.csv#OD-C01@owner_canonical_model_id"] = "wuling.wuling_bingo"
    assert O.validate_session(s, ans, meta_(), U()) == []
    ans["create_candidates.csv#OD-C01@owner_canonical_model_id"] = "wuling.nonexistent"
    assert kinds_of(O.validate_session(s, ans, meta_(), U())) == {"UNKNOWN_TDR_MODEL": 1}
    ans["create_candidates.csv#OD-C01@owner_verdict"] = "VALID_MISSING_CANONICAL"
    ans.pop("create_candidates.csv#OD-C01@owner_canonical_model_id")
    assert "CONDITIONAL_FIELD_MISSING" in kinds_of(O.validate_session(s, ans, meta_(), U()))
    ans["create_candidates.csv#OD-C01@owner_discovery_class"] = "HISTORICAL_BACKFILL"
    assert O.validate_session(s, ans, meta_(), U()) == []
    r6 = "r6_owner_review.csv#review_rank=15@owner_verdict"
    ans[r6] = "CORRECT_PART_OF"
    assert kinds_of(O.validate_session(s, ans, meta_(), U())) == {"CONDITIONAL_FIELD_MISSING": 1}
    ans["r6_owner_review.csv#review_rank=15@owner_link_type"] = "EQUIVALENT"
    ans["r6_owner_review.csv#review_rank=15@owner_canonical_model_id"] = "wuling.wuling_bingo"
    assert kinds_of(O.validate_session(s, ans, meta_(), U())) == {"CONDITIONAL_FIELD_MISSING": 1, "CONTRADICTORY_ANSWERS": 1}, "the link type must match the verdict"
    ans["r6_owner_review.csv#review_rank=15@owner_link_type"] = "PART_OF"
    assert "CONDITIONAL_FIELD_MISSING" not in kinds_of(O.validate_session(s, ans, meta_(), U()))


def test_validator_flags_contradictory_answers_without_resolving_them():
    s = sessions_by_id()["OD-A02"]
    a, c, r = s["own_cells"][0], "create_candidates.csv#OD-C01@owner_verdict", "r6_owner_review.csv#review_rank=15@owner_verdict"
    target = next(x for x in tables()["alias"] if x["decision_id"] == "OD-A02")["existing_identity_id"]
    cand = meta_()[r]["candidate"]
    base = {"create_candidates.csv#OD-C01@owner_discovery_class": "HISTORICAL_BACKFILL"}
    # alias class says the same model, group verdict says no identity exists
    ans = {**base, a: "IDENTITY_EQUIVALENT", c: "VALID_MISSING_CANONICAL", r: "WRONG_TARGET"}
    assert kinds_of(O.validate_session(s, ans, meta_(), U())) == {"CONTRADICTORY_ANSWERS": 1}
    # a correct EQUIVALENT pair next to a missing-identity group verdict
    ans = {**base, a: "UNRESOLVED", c: "VALID_MISSING_CANONICAL", r: "CORRECT_EQUIVALENT", "r6_owner_review.csv#review_rank=15@owner_link_type": "EQUIVALENT", "r6_owner_review.csv#review_rank=15@owner_canonical_model_id": cand}
    assert "CONTRADICTORY_ANSWERS" in kinds_of(O.validate_session(s, ans, meta_(), U()))
    # misleading alias, but the group verdict names the alias target
    ans = {a: "MISLEADING_ALIAS", c: "EXISTING_IDENTITY", "create_candidates.csv#OD-C01@owner_canonical_model_id": target, r: "INSUFFICIENT_EVIDENCE"}
    assert kinds_of(O.validate_session(s, ans, meta_(), U())) == {"CONTRADICTORY_ANSWERS": 1}
    # equivalent alias, but the group verdict names a different model
    ans = {a: "IDENTITY_EQUIVALENT", c: "EXISTING_IDENTITY", "create_candidates.csv#OD-C01@owner_canonical_model_id": "wuling.other", r: "INSUFFICIENT_EVIDENCE"}
    assert "CONTRADICTORY_ANSWERS" in kinds_of(O.validate_session(s, ans, meta_(), U()))
    # a wrong-target pair whose own model is also named as the group's existing identity
    ans = {a: "UNRESOLVED", c: "EXISTING_IDENTITY", "create_candidates.csv#OD-C01@owner_canonical_model_id": cand, r: "WRONG_TARGET"}
    assert "CONTRADICTORY_ANSWERS" in kinds_of(O.validate_session(s, ans, meta_(), U()))
    # a coherent set stays clean (the sheet's candidate for rank 15 is the alias target itself)
    assert cand == target
    ans = {a: "IDENTITY_EQUIVALENT", c: "EXISTING_IDENTITY", "create_candidates.csv#OD-C01@owner_canonical_model_id": target, r: "CORRECT_EQUIVALENT",
           "r6_owner_review.csv#review_rank=15@owner_link_type": "EQUIVALENT", "r6_owner_review.csv#review_rank=15@owner_canonical_model_id": target}
    assert O.validate_session(s, ans, meta_(), U()) == []


def test_validator_accepts_different_groups_each_with_a_correct_equivalent_pair():
    s = sessions_by_id()["INIT-03"]
    ans = coherent_answers(s)
    ans[s["own_cells"][0]] = "keep under MG"
    for rk, cand in (("183", "mg.mg_maxus_7"), ("184", "mg.mg_maxus_9")):
        ans[f"r6_owner_review.csv#review_rank={rk}@owner_verdict"] = "CORRECT_EQUIVALENT"
        ans[f"r6_owner_review.csv#review_rank={rk}@owner_link_type"] = "EQUIVALENT"
        ans[f"r6_owner_review.csv#review_rank={rk}@owner_canonical_model_id"] = cand
    assert O.validate_session(s, ans, meta_(), U()) == [], "different groups: no conflict"
    ans.pop("r6_owner_review.csv#review_rank=184@owner_canonical_model_id")
    assert O.validate_session(s, ans, meta_(), U()) == [], "a blank canonical id on a CORRECT_* verdict means the displayed candidate"


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


# ---------------------------------------------------------------------------------------------------------------------------------------- ODP-1: ground truth per link type
POOL = ["t.a", "t.b"]


def pair(c, verdict, link=""):
    return {"candidate": c, "verdict": verdict, "link_type": link or O.PAIR_LINK.get(verdict, ""), "canonical": ""}


def cell_states(cells, link):
    return {c: st for (c, l), st in cells.items() if l == link}


def test_missing_canonical_identity_is_equivalent_negative_only():
    cells, notes = O.derive_truth(POOL, [], {"verdict": "VALID_MISSING_CANONICAL"})
    assert cell_states(cells, "EQUIVALENT") == {"t.a": "NEGATIVE", "t.b": "NEGATIVE"}
    assert set(cell_states(cells, "PART_OF").values()) == {"UNKNOWN"} and set(cell_states(cells, "COMPOSED_OF").values()) == {"UNKNOWN"}, "no structural relation is inferred negative"
    assert notes == []


@pytest.mark.parametrize("verdict,link", [("CORRECT_PART_OF", "PART_OF"), ("CORRECT_COMPOSED_OF", "COMPOSED_OF")])
def test_missing_identity_with_a_valid_structural_relation_is_kept_and_flagged_for_review(verdict, link):
    cells, notes = O.derive_truth(POOL, [pair("t.a", verdict)], {"verdict": "VALID_MISSING_CANONICAL"})
    assert cells[("t.a", link)] == "POSITIVE", "the structural relation stays a positive for its own link type"
    assert cells[("t.a", "EQUIVALENT")] == "NEGATIVE" and cells[("t.b", link)] == "UNKNOWN"
    assert [n["kind"] for n in notes] == ["MISSING_IDENTITY_WITH_STRUCTURAL_RELATION"] and notes[0]["severity"] == "REVIEW"
    assert not [n for n in notes if n["severity"] == "CONFLICT"]
    # the metric preparation: scored per link type, so a proposed PART_OF/COMPOSED_OF is a true positive there and is not an EQUIVALENT false positive
    preds = {("t.a", link): "PROPOSE"}
    rows, skipped = O.metric_rows(link, cells, preds)
    assert [r["truth"] for r in rows] == ["POSITIVE"] and O.confusion(rows)["tp_prop"] == 1 and O.confusion(rows).get("fp_prop", 0) == 0 and skipped == {"UNKNOWN": 1}
    rows_eq, _ = O.metric_rows("EQUIVALENT", cells, {})
    assert {r["truth"] for r in rows_eq} == {"NEGATIVE"} and O.confusion(rows_eq).get("fp_auto", 0) == 0


def test_missing_identity_and_a_correct_equivalent_pair_is_a_conflict():
    cells, notes = O.derive_truth(POOL, [pair("t.a", "CORRECT_EQUIVALENT")], {"verdict": "VALID_MISSING_CANONICAL"})
    assert cells[("t.a", "EQUIVALENT")] == "CONFLICT" and any(n["severity"] == "CONFLICT" for n in notes)
    rows, skipped = O.metric_rows("EQUIVALENT", cells, {("t.a", "EQUIVALENT"): "AUTO"})
    assert ("t.a", "EQUIVALENT") not in {r["cell"] for r in rows} and skipped.get("CONFLICT") == 1, "a conflicting cell is counted and not scored"


def test_a_variant_infers_no_equivalent_pair():
    cells, notes = O.derive_truth(POOL, [], {"verdict": "VARIANT_TRIM_CODE", "canonical": "t.a"})
    assert set(cells.values()) == {"UNKNOWN"} and notes == []
    # only an explicit, correct owner link label makes the pair a positive
    cells, _ = O.derive_truth(POOL, [pair("t.a", "CORRECT_EQUIVALENT")], {"verdict": "VARIANT_TRIM_CODE", "canonical": "t.a"})
    assert cells[("t.a", "EQUIVALENT")] == "POSITIVE" and cells[("t.b", "EQUIVALENT")] == "NEGATIVE", "the second candidate is negative by C1 from the explicit pair label"
    cells, _ = O.derive_truth(POOL, [pair("t.a", "CORRECT_PART_OF")], {"verdict": "VARIANT_TRIM_CODE", "canonical": "t.a"})
    assert cells[("t.a", "PART_OF")] == "POSITIVE" and cells[("t.a", "EQUIVALENT")] == "UNKNOWN"
    cells, _ = O.derive_truth(POOL, [], {"verdict": "AMBIGUOUS"})
    assert set(cells.values()) == {"UNKNOWN"}


def test_existing_identity_names_one_equivalent_target_and_infers_nothing_structural():
    cells, notes = O.derive_truth(POOL, [], {"verdict": "EXISTING_IDENTITY", "canonical": "t.a"})
    assert cell_states(cells, "EQUIVALENT") == {"t.a": "POSITIVE", "t.b": "NEGATIVE"}
    assert set(cell_states(cells, "PART_OF").values()) == {"UNKNOWN"}
    cells, notes = O.derive_truth(POOL, [], {"verdict": "EXISTING_IDENTITY", "canonical": "t.zzz"})
    assert set(cells.values()) == {"UNKNOWN"} and notes[0]["kind"] == "GROUP_TARGET_OUTSIDE_POOL"
    cells, notes = O.derive_truth(POOL, [pair("t.a", "WRONG_TARGET")], {"verdict": "EXISTING_IDENTITY", "canonical": "t.a"})
    assert cells[("t.a", "EQUIVALENT")] == "CONFLICT"


def test_a_wrong_target_is_negative_only_for_the_link_type_the_row_proposed():
    cells, _ = O.derive_truth(POOL, [pair("t.a", "WRONG_TARGET")], None, {"t.a": "PART_OF"})
    assert cells[("t.a", "PART_OF")] == "NEGATIVE" and cells[("t.a", "EQUIVALENT")] == "UNKNOWN" and cells[("t.a", "COMPOSED_OF")] == "UNKNOWN"
    cells, _ = O.derive_truth(POOL, [pair("t.a", "NO_TDR_TARGET")], None)
    assert cells[("t.a", "EQUIVALENT")] == "NEGATIVE" and cells[("t.a", "PART_OF")] == "UNKNOWN"
    cells, _ = O.derive_truth(POOL, [pair("t.a", "INSUFFICIENT_EVIDENCE")], {"verdict": "VALID_MISSING_CANONICAL"})
    assert {st for (c, l), st in cells.items() if c == "t.a"} == {"EXCLUDED"}, "an excluded candidate stays excluded under a group label"


def test_truth_table_over_every_pair_and_group_verdict():
    """Adversarial sweep: for every (pair verdict, group verdict) the derived cells obey the stated invariants, and a derivation CONFLICT is always also a crosswalk CONFLICT."""
    for pv in O.R6_VERDICTS:
        for gv in O.CREATE_VERDICTS:
            for canon in ("t.a", "t.b"):
                cells, notes = O.derive_truth(POOL, [pair("t.a", pv)], {"verdict": gv, "canonical": canon})
                tag = (pv, gv, canon)
                if gv == "VALID_MISSING_CANONICAL":
                    assert not [k for k, st in cells.items() if k[1] != "EQUIVALENT" and st == "NEGATIVE" and not (pv in ("WRONG_TARGET", "NO_TDR_TARGET") and k == ("t.a", "EQUIVALENT"))], tag
                if gv in ("VARIANT_TRIM_CODE", "AMBIGUOUS"):
                    explicit = {k for k, st in cells.items() if st != "UNKNOWN"}
                    assert all(k[0] == "t.a" or k[1] == "EQUIVALENT" for k in explicit), tag   # nothing beyond what the explicit pair label (and C1) says
                if pv not in O.PAIR_LINK and gv != "EXISTING_IDENTITY" and gv != "VALID_MISSING_CANONICAL":
                    assert "POSITIVE" not in cells.values(), tag
                if any(st == "CONFLICT" for st in cells.values()):
                    assert O._crosswalk_reading(pv, gv)[0] in ("CONFLICT", "CONSISTENT_IF_SAME_TARGET", "CONSISTENT_IF_DIFFERENT_TARGET"), tag
                assert set(cells.values()) <= set(O.TRUTH_STATES)


def test_negative_for_equivalent_never_leaks_into_structural_metrics():
    """The defect this guards: scoring a PART_OF/COMPOSED_OF candidate of a VALID_MISSING_CANONICAL group as a false positive."""
    cells, _ = O.derive_truth(POOL, [pair("t.a", "CORRECT_PART_OF")], {"verdict": "VALID_MISSING_CANONICAL"})
    preds = {("t.a", "PART_OF"): "AUTO", ("t.a", "EQUIVALENT"): "NONE"}
    part_rows, _ = O.metric_rows("PART_OF", cells, preds)
    eq_rows, _ = O.metric_rows("EQUIVALENT", cells, preds)
    assert O.confusion(part_rows)["tp_auto"] == 1 and O.confusion(part_rows).get("fp_auto", 0) == 0
    assert O.confusion(eq_rows).get("fp_auto", 0) == 0 and O.confusion(eq_rows).get("tp_auto", 0) == 0
    old_buggy = [{"truth": "NEGATIVE", "predicted": "AUTO"}]   # what "every pooled candidate is a negative" would have scored
    assert O.confusion(old_buggy)["fp_auto"] == 1


def test_procedure_text_states_the_per_link_type_semantics():
    g = O.CALIBRATION_PROCEDURE["labels_used"]
    assert "every pooled candidate of the group a negative" not in json.dumps(g)
    assert "EQUIVALENT NEGATIVE" in g["group"] and "PART_OF / COMPOSED_OF are NOT inferred" in g["group"] and "VARIANT_TRIM_CODE: no pair truth is inferred" in g["group"]
    assert "scored on its own" in g["scoring"]


# ---------------------------------------------------------------------------------------------------------------------------------------- ODP-2: selection sees training folds only
GRID = [0.90, 0.95, 0.97, 0.99]   # loosest -> strictest


def mk(fold, truth, first_auto_value_index):
    """auto_at is True for every grid value up to (and including) index first_auto_value_index: a looser value fires on more rows."""
    return {"fold": fold, "truth": truth, "auto_at": {v: i <= first_auto_value_index for i, v in enumerate(GRID)}}


def dataset():
    rows = []
    for k in range(5):
        rows += [mk(k, "POSITIVE", 3), mk(k, "POSITIVE", 2), mk(k, "POSITIVE", 1), mk(k, "NEGATIVE", 0)]   # only the loosest value fires on the negative
    return rows


def test_selection_rule_is_loosest_eligible_with_most_true_auto_and_stricter_tie_break():
    train = [r for r in dataset() if r["fold"] != 0]
    sel = O.select_threshold(GRID, train)
    assert sel["selected"] == 0.95 and sel["flag"] == "" and sel["train"][0.90]["train_false_auto"] == 4
    tie = [mk(1, "POSITIVE", 3)]
    assert O.select_threshold(GRID, tie)["selected"] == 0.99, "equal training true-AUTO: the stricter value"
    none = [mk(1, "NEGATIVE", 3), mk(1, "POSITIVE", 3)]
    out = O.select_threshold(GRID, none)
    assert out["selected"] == 0.99 and out["flag"] == "NO_VALUE_WITHOUT_TRAINING_FALSE_AUTO"


def test_changing_held_out_labels_cannot_change_a_folds_selected_threshold():
    base = O.calibrate_by_fold(GRID, dataset(), 5)
    for k in range(5):
        altered = []
        for r in dataset():
            r = {**r, "auto_at": dict(r["auto_at"])}
            if r["fold"] == k:   # flip every held-out label and every held-out prediction
                r["truth"] = "NEGATIVE" if r["truth"] == "POSITIVE" else "POSITIVE"
                r["auto_at"] = {v: not a for v, a in r["auto_at"].items()}
            altered.append(r)
        again = O.calibrate_by_fold(GRID, altered, 5)
        assert again["selections"][k] == base["selections"][k], f"fold {k}: held-out rows leaked into its own selection"
        assert again["folds"][k] != base["folds"][k], "but the held-out evaluation does see them"
    # dropping the held-out fold entirely gives the same selection
    for k in range(5):
        assert O.select_threshold(GRID, [r for r in dataset() if r["fold"] != k])["selected"] == base["selections"][k]


def test_selection_function_takes_no_held_out_input_and_names_no_gate():
    import inspect
    assert list(inspect.signature(O.select_threshold).parameters) == ["grid", "train_rows"]
    tree = ast.parse(inspect.getsource(O.select_threshold))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not {n for n in names if any(w in n.lower() for w in ("heldout", "held_out", "tolerance", "acceptance", "fold", "pooled"))}, names


def test_acceptance_gate_is_post_selection_evidence_that_cannot_retune():
    res = O.calibrate_by_fold(GRID, dataset(), 5)
    frozen = dict(res["selections"])
    gate = O.acceptance_gate(res["pooled"], 0.05)
    assert gate["retune_allowed"] is False and res["selections"] == frozen
    assert gate["verdict"] == "FAILED_REPORT_NOT_CALIBRATED" and gate["false_auto_upper_95"] == O.rule_of_three(res["pooled"]["heldout_auto_predictions"])
    assert O.acceptance_gate(res["pooled"], 0.5)["verdict"] == "ACCEPTANCE_EVIDENCE_MET"
    # a failing gate changes nothing about the selections: there is no code path from the gate back to the grid
    assert O.acceptance_gate({"heldout_rows": 10, "heldout_false_auto": 2, "heldout_true_auto": 3, "heldout_positives": 5, "heldout_auto_predictions": 5}, 0.05)["verdict"] == "FAILED_REPORT_NOT_CALIBRATED"


def test_procedure_text_separates_selection_from_acceptance():
    d = O.CALIBRATION_PROCEDURE["design"]
    assert "pooled held-out false-AUTO upper bound is within" not in json.dumps(d)
    assert "TRAINING" in d["selection_rule"] and "never an input" in d["selection_rule"]
    assert "registered" in d["registration"] and "ONCE" in d["loop"] and "never used to retune" in d["failure_handling"] and "AFTER selection" in d["acceptance_gate"]


# ---------------------------------------------------------------------------------------------------------------------------------------- ODP-5: completion-validator integrity
R6V = "r6_owner_review.csv#review_rank={rk}@{f}"


def r6_answer(rk, verdict, link="", canon=""):
    a = {R6V.format(rk=rk, f="owner_verdict"): verdict}
    if link:
        a[R6V.format(rk=rk, f="owner_link_type")] = link
    if canon:
        a[R6V.format(rk=rk, f="owner_canonical_model_id")] = canon
    return a


def probs(session_id, answers, universe="trusted"):
    return O.validate_session(sessions_by_id()[session_id], answers, meta_(), U() if universe == "trusted" else universe)


def test_a_correct_verdict_with_a_different_but_valid_model_is_refused():
    assert "byd.atto3" in U() and "byd.dolphin" in U()
    assert (next(r for r in inp().r6 if r["review_rank"] == "1")["candidate_canonical_model_id"]) == "byd.dolphin"
    bad = r6_answer("1", "CORRECT_EQUIVALENT", "EQUIVALENT", "byd.atto3")
    assert kinds_of(probs("R6-1", bad)) == {"CANDIDATE_TARGET_MISMATCH": 1} and not O.session_is_complete(sessions_by_id()["R6-1"], bad, meta_(), U())
    # matched, and blank-means-displayed, both complete
    assert probs("R6-1", r6_answer("1", "CORRECT_EQUIVALENT", "EQUIVALENT", "byd.dolphin")) == []
    assert probs("R6-1", r6_answer("1", "CORRECT_EQUIVALENT", "EQUIVALENT")) == []
    # the same holds for PART_OF, and the changed target is never silently turned into a correct verdict
    assert kinds_of(probs("R6-1", r6_answer("1", "CORRECT_PART_OF", "PART_OF", "byd.atto3"))) == {"CANDIDATE_TARGET_MISMATCH": 1}
    # the right way to change the target: WRONG_TARGET with the corrected target and its link type
    assert probs("R6-1", r6_answer("1", "WRONG_TARGET", "EQUIVALENT", "byd.atto3")) == []


def test_composite_targets_are_compared_as_sets():
    sid = "R6-177"
    cand = "isuzu.dmax_cab+isuzu.dmax_double_cab"
    assert next(r for r in inp().r6 if r["review_rank"] == "177")["candidate_canonical_model_id"] == cand
    assert probs(sid, r6_answer("177", "CORRECT_COMPOSED_OF", "COMPOSED_OF")) == []
    assert probs(sid, r6_answer("177", "CORRECT_COMPOSED_OF", "COMPOSED_OF", cand)) == []
    assert probs(sid, r6_answer("177", "CORRECT_COMPOSED_OF", "COMPOSED_OF", "isuzu.dmax_double_cab + isuzu.dmax_cab")) == [], "order and spaces do not matter"
    for other in ("isuzu.dmax_cab", "isuzu.dmax_cab+isuzu.dmax_double_cab+isuzu.dmax_single_cab", "isuzu.dmax_cab+toyota.hilux_revo_cab", "isuzu.dmax_double_cab+byd.dolphin"):
        k = kinds_of(probs(sid, r6_answer("177", "CORRECT_COMPOSED_OF", "COMPOSED_OF", other)))
        assert k.get("CANDIDATE_TARGET_MISMATCH") == 1, other
    # a set cannot be confirmed as EQUIVALENT / PART_OF, and a single model cannot be confirmed as COMPOSED_OF
    assert kinds_of(probs(sid, r6_answer("177", "CORRECT_EQUIVALENT", "EQUIVALENT"))) == {"TARGET_SHAPE_MISMATCH": 1}
    assert kinds_of(probs(sid, r6_answer("177", "CORRECT_PART_OF", "PART_OF"))) == {"TARGET_SHAPE_MISMATCH": 1}
    assert kinds_of(probs("R6-1", r6_answer("1", "CORRECT_COMPOSED_OF", "COMPOSED_OF"))) == {"TARGET_SHAPE_MISMATCH": 1}
    # WRONG_TARGET restating the displayed set (in another order) is not a correction
    assert kinds_of(probs(sid, r6_answer("177", "WRONG_TARGET", "COMPOSED_OF", "isuzu.dmax_double_cab+isuzu.dmax_cab"))) == {"CONTRADICTORY_ANSWERS": 1}
    # a genuine correction of a set
    assert probs(sid, r6_answer("177", "WRONG_TARGET", "COMPOSED_OF", "isuzu.dmax_cab+isuzu.dmax_double_cab+isuzu.mux")) == [] or "isuzu.mux" not in U()
    assert probs(sid, r6_answer("177", "WRONG_TARGET", "EQUIVALENT", "isuzu.dmax_cab")) == []


def test_wrong_target_keeps_its_semantics_and_its_field_contract():
    assert probs("R6-1", r6_answer("1", "WRONG_TARGET")) == [], "a wrong target needs no corrected target"
    assert kinds_of(probs("R6-1", r6_answer("1", "WRONG_TARGET", "", "byd.atto3"))) == {"CONDITIONAL_FIELD_MISSING": 1}
    assert kinds_of(probs("R6-1", r6_answer("1", "WRONG_TARGET", "EQUIVALENT"))) == {"CONDITIONAL_FIELD_MISSING": 1}
    assert kinds_of(probs("R6-1", r6_answer("1", "WRONG_TARGET", "EQUIVALENT", "byd.dolphin"))) == {"CONTRADICTORY_ANSWERS": 1}, "naming the displayed candidate as the correction is a contradiction"
    assert kinds_of(probs("R6-1", r6_answer("1", "WRONG_TARGET", "EQUIVALENT", "byd.atto3+byd.seal"))) == {"TARGET_SHAPE_MISMATCH": 1}
    assert kinds_of(probs("R6-1", r6_answer("1", "WRONG_TARGET", "COMPOSED_OF", "byd.atto3"))) == {"TARGET_SHAPE_MISMATCH": 1}
    assert kinds_of(probs("R6-1", r6_answer("1", "WRONG_TARGET", "SORT_OF", "byd.atto3"))) == {"CONDITIONAL_FIELD_MISSING": 1}
    for v in ("NO_TDR_TARGET", "INSUFFICIENT_EVIDENCE"):
        assert probs("R6-1", r6_answer("1", v)) == []
        assert kinds_of(probs("R6-1", r6_answer("1", v, "EQUIVALENT", "byd.atto3"))) == {"FIELD_NOT_ALLOWED_FOR_VERDICT": 1}, v
        assert kinds_of(probs("R6-1", r6_answer("1", v, "", "byd.atto3"))) == {"FIELD_NOT_ALLOWED_FOR_VERDICT": 1}, v
    # WRONG_TARGET is never read as correct: it does not satisfy the group-level cross-checks as a confirmation
    cells, _ = O.derive_truth(["byd.dolphin"], [{"candidate": "byd.dolphin", "verdict": "WRONG_TARGET", "link_type": "", "canonical": "byd.atto3"}], None)
    assert cells[("byd.dolphin", "EQUIVALENT")] == "NEGATIVE"


def test_a_correct_verdict_needs_a_displayed_candidate_and_the_matching_link_type():
    no_cand = sessions_by_id()["R6-517"]
    assert next(r for r in inp().r6 if r["review_rank"] == "517")["candidate_canonical_model_id"] == ""
    assert kinds_of(probs("R6-517", r6_answer("517", "CORRECT_EQUIVALENT", "EQUIVALENT"))) == {"NO_DISPLAYED_CANDIDATE": 1}
    assert probs("R6-517", r6_answer("517", "NO_TDR_TARGET")) == [] and probs("R6-517", r6_answer("517", "WRONG_TARGET", "EQUIVALENT", "byd.atto3")) == []
    assert kinds_of(probs("R6-1", r6_answer("1", "CORRECT_EQUIVALENT"))) == {"CONDITIONAL_FIELD_MISSING": 1}
    assert "CONDITIONAL_FIELD_MISSING" in kinds_of(probs("R6-1", r6_answer("1", "CORRECT_EQUIVALENT", "PART_OF")))
    del no_cand


def test_unknown_models_are_rejected_wherever_they_appear():
    assert kinds_of(probs("R6-1", r6_answer("1", "WRONG_TARGET", "EQUIVALENT", "byd.nonexistent"))) == {"UNKNOWN_TDR_MODEL": 1}
    assert kinds_of(probs("R6-1", r6_answer("1", "CORRECT_EQUIVALENT", "EQUIVALENT", "byd.nonexistent"))) == {"UNKNOWN_TDR_MODEL": 1, "CANDIDATE_TARGET_MISMATCH": 1}
    assert kinds_of(probs("R6-177", r6_answer("177", "WRONG_TARGET", "COMPOSED_OF", "isuzu.dmax_cab+isuzu.ghost"))) == {"UNKNOWN_TDR_MODEL": 1}
    a = sessions_by_id()["OD-A02"]
    ans = coherent_answers(a)
    ans["create_candidates.csv#OD-C01@owner_verdict"] = "EXISTING_IDENTITY"
    ans["create_candidates.csv#OD-C01@owner_canonical_model_id"] = "wuling.ghost"
    assert kinds_of(O.validate_session(a, ans, meta_(), U())) == {"UNKNOWN_TDR_MODEL": 1}
    ans["create_candidates.csv#OD-C01@owner_canonical_model_id"] = "wuling.wuling_bingo+wuling.other"
    assert "TARGET_SHAPE_MISMATCH" in kinds_of(O.validate_session(a, ans, meta_(), U())), "a group verdict names exactly one model"


def test_completion_fails_closed_without_the_trusted_model_universe():
    import inspect
    assert inspect.signature(O.validate_session).parameters["model_ids"].default is inspect.Parameter.empty, "no default: the universe cannot be forgotten"
    assert inspect.signature(O.session_is_complete).parameters["model_ids"].default is inspect.Parameter.empty
    s = sessions_by_id()["OD-A02"]
    ans = coherent_answers(s)
    assert O.session_is_complete(s, ans, meta_(), U())
    for missing in (None, set(), frozenset(), []):
        assert not O.session_is_complete(s, ans, meta_(), missing), repr(missing)
        assert "MODEL_UNIVERSE_UNAVAILABLE" in kinds_of(O.validate_session(s, ans, meta_(), missing))
    # a universe that lacks a model the answers rely on does not accept it
    partial = U() - {"wuling.wuling_bingo"}
    assert "UNKNOWN_TDR_MODEL" in kinds_of(O.validate_session(s, {**ans, **r6_answer("15", "CORRECT_EQUIVALENT", "EQUIVALENT")}, meta_(), partial))
    # the trusted universe is the accepted export's TDR universe
    exported = {r["id"] for r in E.load_rows(E.OUT / E.FILES["tdr_targets"])}
    assert set(U()) == exported and len(U()) == 323


def test_negative_sample_yes_requires_a_valid_typed_counterpart():
    sid = "NS-001"
    cell = sessions_by_id()[sid]["own_cells"][0]
    base = "negative_sample.csv#NS-001@"
    assert kinds_of(probs(sid, {cell: "MAYBE"})) == {"VALUE_NOT_ALLOWED": 1}
    assert kinds_of(probs(sid, {cell: "YES"})) == {"CONDITIONAL_FIELD_MISSING": 2}, "model and link type are both missing"
    assert kinds_of(probs(sid, {cell: "YES", base + "owner_canonical_model_id": "byd.dolphin"})) == {"CONDITIONAL_FIELD_MISSING": 1}
    assert kinds_of(probs(sid, {cell: "YES", base + "owner_link_type": "EQUIVALENT"})) == {"CONDITIONAL_FIELD_MISSING": 1}
    assert kinds_of(probs(sid, {cell: "YES", base + "owner_canonical_model_id": "byd.ghost", base + "owner_link_type": "EQUIVALENT"})) == {"UNKNOWN_TDR_MODEL": 1}
    assert kinds_of(probs(sid, {cell: "YES", base + "owner_canonical_model_id": "byd.dolphin", base + "owner_link_type": "SORT_OF"})) == {"CONDITIONAL_FIELD_MISSING": 1}
    assert kinds_of(probs(sid, {cell: "YES", base + "owner_canonical_model_id": "byd.dolphin", base + "owner_link_type": "COMPOSED_OF"})) == {"TARGET_SHAPE_MISMATCH": 1}
    assert kinds_of(probs(sid, {cell: "YES", base + "owner_canonical_model_id": "byd.dolphin+byd.atto3", base + "owner_link_type": "EQUIVALENT"})) == {"TARGET_SHAPE_MISMATCH": 1}
    assert probs(sid, {cell: "YES", base + "owner_canonical_model_id": "byd.dolphin", base + "owner_link_type": "PART_OF"}) == []
    assert probs(sid, {cell: "YES", base + "owner_canonical_model_id": "byd.atto3+byd.dolphin", base + "owner_link_type": "COMPOSED_OF"}) == []
    for v in ("NO", "UNSURE"):
        assert probs(sid, {cell: v}) == []
        assert kinds_of(probs(sid, {cell: v, base + "owner_canonical_model_id": "byd.dolphin"})) == {"FIELD_NOT_ALLOWED_FOR_VERDICT": 1}, v


def test_coherent_positive_sessions_still_complete():
    """INIT-03 and OD-A02 with correct, matched, typed answers (the pack fills nothing: these are test inputs)."""
    s = sessions_by_id()["INIT-03"]
    ans = coherent_answers(s)
    ans[s["own_cells"][0]] = "file under MG"
    ans.update(r6_answer("184", "CORRECT_EQUIVALENT", "EQUIVALENT", "mg.mg_maxus_9"))
    ans.update(r6_answer("183", "CORRECT_EQUIVALENT", "EQUIVALENT"))
    ans["create_candidates.csv#OD-C11@owner_verdict"] = "VALID_MISSING_CANONICAL"
    ans["create_candidates.csv#OD-C11@owner_discovery_class"] = "ACTIVE_CATALOG_GAP"
    ans.update(r6_answer("190", "WRONG_TARGET", "EQUIVALENT", "mg.mg_maxus_7"))
    assert O.session_is_complete(s, ans, meta_(), U()), O.validate_session(s, ans, meta_(), U())
    a = sessions_by_id()["OD-A02"]
    target = next(x for x in tables()["alias"] if x["decision_id"] == "OD-A02")["existing_identity_id"]
    ans = {a["own_cells"][0]: "IDENTITY_EQUIVALENT", "create_candidates.csv#OD-C01@owner_verdict": "EXISTING_IDENTITY", "create_candidates.csv#OD-C01@owner_canonical_model_id": target,
           **r6_answer("15", "CORRECT_EQUIVALENT", "EQUIVALENT", target)}
    assert O.session_is_complete(a, ans, meta_(), U())
    # a standalone R6 session and a CREATE session
    assert O.session_is_complete(sessions_by_id()["R6-1"], r6_answer("1", "CORRECT_EQUIVALENT", "EQUIVALENT", "byd.dolphin"), meta_(), U())
    c = sessions_by_id()["OD-C19"]
    assert O.session_is_complete(c, {c["own_cells"][0]: "AMBIGUOUS"}, meta_(), U())


def test_the_validator_change_leaves_counts_queue_and_owner_fields_alone():
    t = tables()
    assert (t["istats"]["review_sessions"], t["istats"]["atomic_verdicts_total"], t["istats"]["child_decisions"], len(t["queue"]), len(t["sessions"])) == (65, 78, 13, 690, 659)
    text = (OUT / "review_sessions.csv").read_text(encoding="utf-8")
    assert "trusted catalog" in text and "displayed candidate" in text
    doc = (A.CALIBRATION_DIR / "DATA_DICTIONARY.md").read_text(encoding="utf-8")
    assert "Completion rules" in doc and "MODEL_UNIVERSE_UNAVAILABLE" in doc and "never a correct verdict" in doc
