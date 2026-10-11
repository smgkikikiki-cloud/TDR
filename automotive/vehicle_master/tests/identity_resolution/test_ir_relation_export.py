"""The complete pair-level relation export (`calibration/relation_export/`) is exactly what the PR #200 reference evaluator says, and nothing is missing.

PR #201 asked for every name relation of the pinned M7.0 snapshot, not only the ones rev 4 changed. These tests pin, for both populations (Ice x Ice, Ice x TDR):

  * coverage: the exported pairs are the evaluator's actual comparison populations, with no pair and no candidate-pool member omitted;
  * parity: all nine relation kinds, pair for pair, against `ref_eval_core.name_relation` / `ref_eval_resolve.resolve`, and the nine counts against the rev 4 results;
  * determinism and provenance: canonical bytes, manifest hashes, pinned source blobs;
  * independence: no Identity Bootstrap stand-in logic, no second matcher.

Everything not marked `needs_package` runs from committed files only (the export itself, `calibration/inputs/` and the committed rev 4 measurement); the one test that
regenerates the export from the archived M7.0 package is skipped when the package is absent. Nothing here changes a rule.
"""
from __future__ import annotations

import ast
import collections
import functools
import itertools
import json
import re
from pathlib import Path

import pytest

import ir_support as S
from identity_resolution.calibration import adapters as A
from identity_resolution.calibration import lexical_pass as L
from identity_resolution.calibration import ref_eval_core as P
from identity_resolution.calibration import relation_export as E
from identity_resolution.contract import schema_subset as sc

DIR = E.OUT
PACKAGE = A.REPO_ROOT / A.PACKAGE_RELATIVE
needs_package = pytest.mark.skipif(not PACKAGE.exists(), reason="the archived M7.0 package is not in this checkout")

NINE = ["EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV", "FUZZY", "SUBJECT_COARSER", "SUBJECT_FINER", "SIBLING", "CONTRADICTION", "UNAVAILABLE"]
#: The rev 4 results (LEXICAL_PASS_REPORT.md section 3; PR #200 CI-verified at 1f73aee18), typed here on purpose: the export must reproduce them, not define them.
REV4_ICE_ICE = {"EQUAL": 4, "EQUAL_VIA_MODEL_ALIAS": 2, "EQUAL_VIA_TOKEN_EQUIV": 1, "FUZZY": 7, "SUBJECT_COARSER": 78, "SUBJECT_FINER": 40, "SIBLING": 307, "CONTRADICTION": 25339, "UNAVAILABLE": 727}
REV4_ICE_TDR = {"EQUAL": 239, "EQUAL_VIA_MODEL_ALIAS": 1, "EQUAL_VIA_TOKEN_EQUIV": 1, "FUZZY": 2, "SUBJECT_COARSER": 58, "SUBJECT_FINER": 35, "SIBLING": 55, "CONTRADICTION": 11783, "UNAVAILABLE": 238}


# ---------------------------------------------------------------------------------------------------------------------------------------- loaders (cached)
@functools.lru_cache(maxsize=None)
def manifest() -> dict:
    return json.loads((DIR / "MANIFEST.json").read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def rows(name: str) -> tuple:
    return tuple(E.load_rows(DIR / E.FILES[name]))


@functools.lru_cache(maxsize=None)
def schema() -> dict:
    return json.loads((DIR / "relation_export.schema.json").read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def subjects() -> dict:
    return {r["id"]: r for r in rows("ice_subjects")}


@functools.lru_cache(maxsize=None)
def targets() -> dict:
    return {r["id"]: r for r in rows("tdr_targets")}


@functools.lru_cache(maxsize=None)
def ext() -> dict:
    return A.load_extracts()


@functools.lru_cache(maxsize=None)
def rev4() -> dict:
    return json.loads((L.DIR / "after_rev4.json").read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def regenerated() -> dict:
    """The whole export rebuilt WITHOUT the package: names and brands from the committed subject list, TDR side from the committed inputs, a series-free snapshot.
    Every relation and every pool is recomputed by the evaluator (`resolve`); only the dry-run `outcome` needs the series and is therefore absent."""
    m = manifest()
    blobs = {k: v for k, v in m["sources"]["ice_package"].items() if k in ("bytes", "dims_model_group_csv_sha256", "reg_trend_csv_sha256")}
    return E.build(subjects=E.subjects_from_export(DIR), ext=ext(), as_of=m["universes"]["ice"]["as_of_period"], blobs=blobs)


def counts(population_rows) -> dict:
    c = collections.Counter(r["r"] for r in population_rows)
    return {k: c.get(k, 0) for k in NINE}


# ---------------------------------------------------------------------------------------------------------------------------------------- inventory and schema
def test_the_export_directory_is_exactly_the_documented_inventory():
    on_disk = {p.name for p in DIR.iterdir() if p.is_file()}
    assert on_disk == set(E.FILES.values()) | {"MANIFEST.json"} | set(E.STATIC_FILES)
    assert set(manifest()["files"]) == set(E.FILES.values())
    for name, meta in manifest()["files"].items():
        assert meta["bytes"] > 0 and meta["lines"] > 0, name


def test_every_record_validates_against_the_versioned_schema():
    doc = schema()
    assert not sc.unsupported_keywords(doc), "the schema must stay inside the subset the stdlib validator implements"
    assert doc["$id"] == E.SCHEMA_VERSION == manifest()["schema_version"]
    problems = [f"manifest: {e}" for e in sc.validate(manifest(), {"$ref": "#/$defs/manifest"}, root=doc)]
    for name, definition in (("ice_subjects", "ice_subject"), ("tdr_targets", "tdr_target"), ("pairs_ice_ice", "ice_ice_pair"), ("pairs_ice_tdr", "ice_tdr_pair")):
        ref = {"$ref": f"#/$defs/{definition}"}
        for i, record in enumerate(rows(name)):
            errors = sc.validate(record, ref, root=doc)
            if errors:
                problems.append(f"{name}[{i}]: {errors[:2]}")
                if len(problems) > 10:
                    break
    assert not problems, problems


def test_the_manifest_pins_versions_and_the_non_binding_draft_state():
    m = manifest()
    assert m["schema_version"] == "ir-relation-export/1" and m["export_id"] == "ir-rev4-m7.0-relations/1" and m["consumer_contract_version"] == "ir-relation-export-consumer/1"
    assert m["contract"] == {"version": "v1", "revision": S.policy()["policy"]["revision"], "policy_version": S.policy()["policy"]["version"], "status": "draft_not_frozen",
                             "adoption_binding": S.adoption()["binding"]} and m["contract"]["adoption_binding"] is False and m["contract"]["revision"] == 4
    assert m["universes"]["ice"] == {"id": "ice:2569-09:v3:M7.0", "subjects": 1200, "as_of_period": "2026-09"}
    assert m["universes"]["tdr"]["targets"] == len(targets()) == 323 and m["universes"]["tdr"]["id"].startswith("tdr_vehicle_models:sha256-")
    assert m["sources"]["ice_package"]["sha256"] == A.PACKAGE_SHA256 and m["sources"]["ice_package"]["path"] == A.PACKAGE_RELATIVE
    assert m["relation_order"] == NINE and m["outcomes_included"] is True
    assert not re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", json.dumps(m)), "no generation timestamp in the manifest"


# ---------------------------------------------------------------------------------------------------------------------------------------- determinism and provenance
def test_every_file_is_in_canonical_bytes_and_matches_its_manifest_entry():
    assert (DIR / "MANIFEST.json").read_bytes() == E.manifest_bytes(manifest())
    for name in E.FILES.values():
        data = (DIR / name).read_bytes()
        meta = manifest()["files"][name]
        assert E.sha256(data) == meta["sha256"] and len(data) == meta["bytes"] and data.count(b"\n") == meta["lines"], name
        assert data.endswith(b"\n") and b"\r" not in data, name
        text = data.decode("utf-8")
        for line in text.splitlines():
            assert E.canonical_line(json.loads(line)) == line, f"{name}: a record is not in canonical form"
        assert not re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", text), f"{name} carries a timestamp"
    assert set(manifest()["static_files"]) == set(E.STATIC_FILES)
    for name, meta in manifest()["static_files"].items():
        data = (DIR / name).read_bytes()
        assert E.sha256(data) == meta["sha256"] and len(data) == meta["bytes"], f"{name} changed after the manifest was generated: regenerate the export"
    assert E.verify(DIR) == [], E.verify(DIR)


def test_the_pinned_source_blobs_are_the_committed_files():
    pinned = manifest()["sources"]
    for relative, digest in pinned["evaluator_and_contract"].items():
        assert E.file_sha256(E.repo_file(relative)) == digest, f"{relative} changed after the export was generated: regenerate it"
    assert set(pinned["evaluator_and_contract"]) == set(E.SOURCE_PATHS)
    inputs_manifest = json.loads((A.INPUTS_DIR / "MANIFEST.json").read_text(encoding="utf-8"))["files"]
    for name, digest in pinned["tdr_inputs"].items():
        assert E.file_sha256(A.INPUTS_DIR / name) == digest, name
        assert inputs_manifest[name]["sha256"] == digest, f"{name}: the export pins a different blob than calibration/inputs/MANIFEST.json"
    assert pinned["tdr_inputs"]["tdr_models.json"][:16] == manifest()["universes"]["tdr"]["id"].rsplit("-", 1)[1]
    assert re.fullmatch(r"[0-9a-f]{64}", pinned["ice_package"]["dims_model_group_csv_sha256"]) and re.fullmatch(r"[0-9a-f]{64}", pinned["ice_package"]["reg_trend_csv_sha256"])


def test_pair_keys_are_stable_unique_and_ordered():
    for name, digest_of in (("pairs_ice_ice", "ice_ice"), ("pairs_ice_tdr", "ice_tdr")):
        data = rows(name)
        keys = [r["k"] for r in data]
        assert keys == [f"{r['a']}|{r['b']}" for r in data] and len(set(keys)) == len(keys)
        assert [(r["a"], r["b"]) for r in data] == sorted((r["a"], r["b"]) for r in data), f"{name} is not in (a, b) code-point order"
        assert E.key_digest(keys) == manifest()["populations"][digest_of]["key_digest_sha256"]
    assert all(r["a"] < r["b"] for r in rows("pairs_ice_ice")), "Ice x Ice: the smaller id first"
    assert all("|" not in r["b"] for r in rows("pairs_ice_tdr")), "no TDR canonical id contains the key separator"
    assert [r["id"] for r in rows("ice_subjects")] == sorted(subjects()) and [r["id"] for r in rows("tdr_targets")] == sorted(targets())
    assert sum("|" in s for s in subjects()) == 591 and max(s.count("|") for s in subjects()) == 1, "Ice ids contain the separator: consumers must not split a key"


# ---------------------------------------------------------------------------------------------------------------------------------------- coverage
def test_ice_ice_coverage_is_every_pair_inside_each_ice_brand_string():
    by_brand = collections.defaultdict(list)
    for sid, s in subjects().items():
        by_brand[s["brand"]].append(sid)
    expected = {f"{a}|{b}" for ids in by_brand.values() for a, b in itertools.combinations(sorted(ids), 2)}        # built without the evaluator
    got = {r["k"] for r in rows("pairs_ice_ice")}
    assert got == expected, f"missing {len(expected - got)}, extra {len(got - expected)}"
    assert len(got) == len(rows("pairs_ice_ice")) == manifest()["populations"]["ice_ice"]["pairs"] == manifest()["populations"]["ice_ice"]["expected_pairs"] == 26505
    assert manifest()["populations"]["ice_ice"]["brand_strings"] == len(by_brand)
    assert len(subjects()) == manifest()["universes"]["ice"]["subjects"] == 1200


def test_ice_tdr_coverage_is_every_member_of_every_subjects_candidate_pool():
    pol = S.policy()["candidates"]
    universe = list(targets().values())
    assert len(universe) == len(ext()["models"]) == 323 and len({t["id"] for t in universe}) == 323
    by_subject = collections.defaultdict(set)
    for r in rows("pairs_ice_tdr"):
        by_subject[r["a"]].add(r["b"])
    total = 0
    for sid, s in subjects().items():
        pool, excluded = set(), collections.Counter()
        for t in universe:
            rel = P.brand_relation(s["brand"], t["brand"], tuple(s["brands_observed"]))[0]
            if rel not in pol["brand_relations_allowed"]:
                excluded["brand_not_allowed"] += 1
            elif t["deleted"] and pol["exclude_deleted_targets"]:
                excluded["deleted"] += 1
            elif t["status"] not in pol["target_statuses_in_pool"]:
                excluded["status_not_in_pool"] += 1
            else:
                pool.add(t["id"])
        assert s["pool"] == sorted(pool) == sorted(by_subject.get(sid, set())), f"{sid}: pool, policy filter and exported pairs disagree"
        assert s["pool_excluded"] == {"brand_not_allowed": excluded["brand_not_allowed"], "deleted": excluded["deleted"], "status_not_in_pool": excluded["status_not_in_pool"]}
        assert len(s["pool"]) + sum(s["pool_excluded"].values()) == len(universe), sid
        total += len(pool)
    assert total == len(rows("pairs_ice_tdr")) == manifest()["populations"]["ice_tdr"]["pairs"] == manifest()["populations"]["ice_tdr"]["expected_pairs"] == 12412
    assert sum(1 for s in subjects().values() if not s["pool"]) == manifest()["populations"]["ice_tdr"]["subjects_with_empty_pool"] == 226
    assert set(by_subject) <= set(subjects())


def test_a_subject_with_no_pool_is_a_brand_not_in_tdr_and_every_other_subject_has_rows():
    for sid, s in subjects().items():
        if not s["pool"]:
            assert s["best_relation"] is None and s["best_targets"] == [] and s["related"] == {}
            assert s["outcome"]["primary_code"] in ("BRND_NOT_IN_TDR", "BRND_UNKNOWN"), (sid, s["outcome"]["primary_code"])
        else:
            assert s["best_relation"] in NINE


# ---------------------------------------------------------------------------------------------------------------------------------------- the nine kinds
def test_all_nine_relation_kinds_are_exported_and_match_the_rev4_results_exactly():
    for population, file, expected in (("ice_ice", "pairs_ice_ice", REV4_ICE_ICE), ("ice_tdr", "pairs_ice_tdr", REV4_ICE_TDR)):
        from_rows = counts(rows(file))
        assert list(from_rows) == NINE and all(from_rows[k] > 0 for k in NINE), f"{population}: every kind, including CONTRADICTION and UNAVAILABLE, is exported"
        assert from_rows == expected, population
        assert manifest()["populations"][population]["relation_counts"] == from_rows
        assert rev4()[population]["relations"] == from_rows, f"{population}: the export disagrees with lexical_pass/after_rev4.json"
        assert sum(from_rows.values()) == manifest()["populations"][population]["pairs"]


def test_the_three_kinds_after_rev4_json_lists_agree_with_the_export_key_for_key():
    for population, file in (("ice_ice", "pairs_ice_ice"), ("ice_tdr", "pairs_ice_tdr")):
        listed = rev4()[f"{population}_relation_pairs"]
        exported = {r["k"]: r["r"] for r in rows(file) if r["r"] in ("FUZZY", "SIBLING", "EQUAL_VIA_MODEL_ALIAS")}
        assert exported == listed, population


def test_the_exported_decisions_are_the_committed_reference_run():
    for sid, s in subjects().items():
        outcome, primary, targets_, link, flag = rev4()["decisions"][sid]
        o = s["outcome"]
        assert (o["outcome"], o["primary_code"], "+".join(o["target_ids"]), o["link_type"], int("CARD_CLAIM_CONFLICTS_AUTO" in {c for c, _ in o["codes"]})) == (outcome, primary, targets_, link, flag), sid
    assert collections.Counter(s["outcome"]["outcome"] for s in subjects().values()) == collections.Counter(rev4()["decision_summary"]["outcomes"])


def test_best_relation_and_related_candidates_follow_the_exported_rows():
    by_subject = collections.defaultdict(dict)
    for r in rows("pairs_ice_tdr"):
        by_subject[r["a"]][r["b"]] = r["r"]
    for sid, s in subjects().items():
        rel = by_subject.get(sid, {})
        if rel:
            best = min(rel.values(), key=NINE.index)
            assert s["best_relation"] == best and s["best_targets"] == sorted(t for t, r in rel.items() if r == best), sid
        assert s["related"] == {k: sorted(t for t, r in rel.items() if r == k) for k in NINE if k not in ("CONTRADICTION", "UNAVAILABLE") and any(r == k for r in rel.values())}, sid


# ---------------------------------------------------------------------------------------------------------------------------------------- pair for pair against the evaluator
def test_every_exported_ice_ice_row_is_what_the_evaluator_returns_for_those_names():
    bad = []
    for r in rows("pairs_ice_ice"):
        a, b = subjects()[r["a"]], subjects()[r["b"]]
        obs = tuple(a["brands_observed"])
        rel, score, ta, tb = P.name_relation(a["name"], a["brand"], b["name"], b["brand"], obs)
        flags = E._flags(a["name"], a["brand"], b["name"], b["brand"], obs)
        if (rel, None if score is None else P.q(score), ta, tb, flags) != (r["r"], r["s"], r["ta"], r["tb"], r["n"]):
            bad.append(r["k"])
    assert not bad, f"{len(bad)} Ice x Ice rows differ from the evaluator, e.g. {bad[:3]}"


def test_every_exported_ice_tdr_row_is_what_the_evaluator_returns_for_those_names():
    bad = []
    for r in rows("pairs_ice_tdr"):
        s, t = subjects()[r["a"]], targets()[r["b"]]
        obs = tuple(s["brands_observed"])
        rel, score, ta, tb = P.name_relation(s["name"], s["brand"], t["name"], t["brand"], obs)
        flags = E._flags(s["name"], s["brand"], t["name"], t["brand"], obs)
        if (rel, None if score is None else P.q(score), ta, tb, flags, P.brand_relation(s["brand"], t["brand"], obs)[0]) != (r["r"], r["s"], r["ta"], r["tb"], r["n"], r["br"]):
            bad.append(r["k"])
    assert not bad, f"{len(bad)} Ice x TDR rows differ from the evaluator, e.g. {bad[:3]}"


def test_the_export_equals_a_fresh_evaluator_run_over_the_committed_universe():
    """The evaluator's own comparison populations: Ice x Ice from the population definition, Ice x TDR from the single-target pools `resolve` builds. Rebuilt here from the
    committed subject list and TDR inputs only (no package) and compared byte for byte with the committed pair, subject and target files."""
    fresh = regenerated()
    for name in ("pairs_ice_ice.jsonl", "pairs_ice_tdr.jsonl", "tdr_targets.jsonl"):
        assert fresh[name] == (DIR / name).read_bytes(), f"{name} differs from a fresh evaluator run"
    committed = [json.loads(line) for line in (DIR / "ice_subjects.jsonl").read_text(encoding="utf-8").splitlines()]
    rebuilt = [json.loads(line) for line in fresh["ice_subjects.jsonl"].decode("utf-8").splitlines()]
    assert [{k: v for k, v in c.items() if k != "outcome"} for c in committed] == rebuilt, "subject records (everything except the series-dependent outcome) differ"
    fresh_manifest = json.loads(fresh["MANIFEST.json"])
    for key in ("populations", "universes", "relation_order", "policy_echo", "evaluator", "ordering", "static_files"):
        assert fresh_manifest[key] == manifest()[key], key
    assert fresh_manifest["sources"] == manifest()["sources"] and fresh_manifest["contract"] == manifest()["contract"]


def test_the_export_populations_equal_the_measurement_populations_of_the_rev4_pass():
    """`lexical_pass` is the code that produced the committed rev 4 counts; the export must cover exactly its populations."""
    universe = E.subjects_from_export(DIR)
    ice = E.ice_like(universe)
    oracle = L.Oracle(S.policy())
    measured_ice = {(x[3], x[4]): x[0] for x in L.ice_ice(ice, oracle)}
    assert measured_ice == {(r["a"], r["b"]): r["r"] for r in rows("pairs_ice_ice")}
    measured_tdr = {(x[3], x[4]): x[0] for x in L.ice_tdr(ice, ext())}
    assert measured_tdr == {(r["a"], r["b"]): r["r"] for r in rows("pairs_ice_tdr")}
    assert len(measured_ice) == 26505 and len(measured_tdr) == 12412


def test_an_ice_ice_row_can_be_read_from_either_side_by_swapping_only_coarser_and_finer():
    """CONSUMER_CONTRACT section 2: the reverse orientation is the same row with SUBJECT_COARSER <-> SUBJECT_FINER; verified against the evaluator for every pair."""
    flip = {"SUBJECT_COARSER": "SUBJECT_FINER", "SUBJECT_FINER": "SUBJECT_COARSER"}
    bad = []
    for r in rows("pairs_ice_ice"):
        a, b = subjects()[r["a"]], subjects()[r["b"]]
        rel = P.name_relation(b["name"], b["brand"], a["name"], a["brand"], tuple(b["brands_observed"]))[0]
        if rel != flip.get(r["r"], r["r"]):
            bad.append(r["k"])
    assert not bad, bad[:5]


@needs_package
def test_regenerating_from_the_archived_package_reproduces_every_committed_byte():
    ice = A.load_ice_package()
    assert ice["sha256"] == manifest()["sources"]["ice_package"]["sha256"]
    blobs = E.package_blobs()
    assert {k: manifest()["sources"]["ice_package"][k] for k in blobs} == blobs
    fresh = E.build(ice=ice, ext=ext(), blobs=blobs)
    for name, data in fresh.items():
        assert data == (DIR / name).read_bytes(), f"{name}: the committed export is stale; run: python -m identity_resolution.calibration.relation_export build"
    assert E.subjects_from_ice(ice) == E.subjects_from_export(DIR), "the committed subject list is not the package's"


# ---------------------------------------------------------------------------------------------------------------------------------------- independence
def test_every_relation_flows_from_the_evaluator_and_nowhere_else(monkeypatch):
    """Replace the evaluator's `name_relation` with a sentinel and rebuild a slice of the export: every Ice x Ice and Ice x TDR relation, score and token becomes the sentinel's,
    so the export cannot be carrying a relation from a second matcher (or from a cache)."""
    wanted = {"HONDA", "MAZDA", "MG", "MAXUS"}
    universe = [s for s in E.subjects_from_export(DIR) if s["brand"] in wanted]
    assert 20 < len(universe) < 200
    monkeypatch.setattr(P, "name_relation", lambda *a, **k: ("SIBLING", 0.25, ["sentinel"], ["sentinel-peer"]))
    built = E.build(subjects=universe, ext=ext(), as_of="2026-09", blobs={})
    for name in ("pairs_ice_ice.jsonl", "pairs_ice_tdr.jsonl"):
        records = [json.loads(line) for line in built[name].decode("utf-8").splitlines()]
        assert records and all((r["r"], r["s"], r["ta"], r["tb"]) == ("SIBLING", 0.25, ["sentinel"], ["sentinel-peer"]) for r in records), name


def test_the_export_code_imports_nothing_from_the_bootstrap_stand_in_and_defines_no_matcher():
    source = Path(E.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules, relative_names = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative_names |= {a.name for a in node.names}
            else:
                modules.add(node.module)
    assert modules <= {"argparse", "hashlib", "io", "json", "zipfile", "pathlib", "__future__", "identity_resolution.contract"}, modules
    assert relative_names == {"adapters", "lexical_pass", "ref_eval_core", "ref_eval_resolve"}, relative_names
    for forbidden in ("identity_bootstrap", "ir_rev4", "adjudicate"):
        assert forbidden not in source.lower(), forbidden
    # no function of the export module computes a relation: relations only ever come back from P.name_relation / resolve
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert not {n for n in names if any(w in n for w in ("fuzzy", "sibling", "lev", "dice", "contradiction", "equal"))}, names
    # and nothing else in the identity_resolution package refers to the Bootstrap
    for path in S.IR_ROOT.rglob("*.py"):
        assert "identity_bootstrap" not in path.read_text(encoding="utf-8"), path


def test_committed_artifact_checks_do_not_need_the_private_package():
    """Only the explicitly marked regeneration test may touch the archived M7.0 package; everything else runs from committed files."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")):
        marked = any(isinstance(d, ast.Name) and d.id == "needs_package" for d in fn.decorator_list)
        uses = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        if not marked:
            assert not uses & {"load_ice_package", "package_blobs", "subjects_from_ice"}, f"{fn.name} needs the package but is not marked"


def test_the_consumer_contract_states_what_the_export_contains():
    text = (DIR / "CONSUMER_CONTRACT.md").read_text(encoding="utf-8")
    for needle in (E.CONSUMER_CONTRACT_VERSION, E.SCHEMA_VERSION, E.EXPORT_ID, "b132a86c0bf2f17f53d80b70b4c158efe4b9e69d", "IR_PARITY_UNRESOLVED", "ir_rev4.adjudicate", "POOL_MISMATCH",
                   "PAIR_NOT_EVALUATED", "Never split a key", "SUBJECT_COARSER", "adoption.binding: false", "NOT frozen", "26,505", "12,412", "591", "226"):
        assert needle in text, needle
    for name in list(E.FILES.values()) + ["MANIFEST.json", "relation_export.schema.json"]:
        assert name in text, name
    for relation in NINE:
        assert relation in text, relation
    for label, expected in (("Ice × Ice", REV4_ICE_ICE), ("Ice × TDR", REV4_ICE_TDR)):
        line = next(l for l in text.splitlines() if l.startswith(f"| {label} |"))
        cells = [int(c.replace(",", "")) for c in line.strip("|").split("|")[1:]]
        assert cells == [expected[k] for k in NINE] + [sum(expected.values())], label
    assert "Automatic CREATE stays out of scope" in text
