"""The shadow run: stand-in unit tests, and invariants of the real run on the pinned M7.0 package (skipped if the package file is absent)."""
from __future__ import annotations

import collections
import copy
import hashlib
import json
from pathlib import Path

import pytest

import ib_support as S
from identity_bootstrap import shadow
from identity_bootstrap.shadow import package, report, run as shadow_run, stand_in

PKG_PATH = shadow_run.DEFAULT_PACKAGE
needs_package = pytest.mark.skipif(not PKG_PATH.exists(), reason="pinned Ice package not in this checkout")


def toks(*names):
    return [n.split() for n in names]


def test_name_relation_vocabulary():
    rel = stand_in.name_relation
    assert rel(["dmax"], ["dmax"]) == "EQUAL"
    assert rel(["d", "max"], ["d", "max"]) == "EQUAL"
    assert rel(["mg4", "ev"], ["mg4", "electric"]) == "EQUAL_VIA_TOKEN_EQUIV"
    assert rel(["city", "hatchback"], ["city"]) == "SUBJECT_FINER"
    assert rel(["hilux", "travo"], ["hilux", "travo", "cab"]) == "SUBJECT_COARSER"
    assert rel(["hilux", "revo"], ["hilux", "travo"]) == "SIBLING"
    assert rel(["d", "max"], ["mu", "x"]) == "CONTRADICTION"
    assert rel([], ["x"]) == "UNAVAILABLE"
    assert rel(["fortunar"], ["fortuner"]) == "FUZZY"


def test_refined_relations_do_not_call_a_version_a_typo():
    assert stand_in.name_relation(["xc60"], ["xc90"], refined=False) == "FUZZY", "the IR draft's rule calls a one-digit difference a typo"
    assert stand_in.name_relation(["xc60"], ["xc90"], refined=True) == "CONTRADICTION"
    assert stand_in.name_relation(["db11"], ["db12"], refined=True) == "CONTRADICTION"
    assert stand_in.name_relation(["gr", "yaris"], ["gr", "corolla"], refined=True, non_distinctive=frozenset({"gr"})) == "CONTRADICTION"
    assert stand_in.name_relation(["hilux", "revo"], ["hilux", "travo"], refined=True) == "SIBLING"


def test_the_stand_in_is_labelled_as_a_stand_in():
    assert "STAND-IN" in stand_in.__doc__ and "STAND-IN" in shadow.__doc__


@needs_package
def test_a_package_that_is_not_the_pinned_one_is_refused(tmp_path):
    other = tmp_path / "TDR_FULL_other.zip"
    other.write_bytes(PKG_PATH.read_bytes() + b"x")
    with pytest.raises(package.PackageError):
        package.load(other)


@pytest.fixture(scope="module")
def runs():
    if not PKG_PATH.exists():
        pytest.skip("pinned Ice package not in this checkout")
    a = shadow_run.run("A")
    b = shadow_run.run("B", pkg=a["package"])
    return a, b


@needs_package
def test_the_run_covers_all_1200_groups_and_is_the_pinned_package(runs):
    a, b = runs
    assert a["package"]["sha256"] == package.PINNED["sha256"]
    assert len(a["decisions"]) == len(b["decisions"]) == 1200
    assert collections.Counter(s["identity_status"] for s in a["snapshot"]["subjects"]) == {"settled": 495, "unmapped_name": 591, "provisional": 114}
    assert {d["outcome"] for d in a["decisions"]} <= set(S.OUTCOMES)
    assert S.validate_input(a["snapshot"]) == []


@needs_package
def test_golden_shadow_numbers(runs):
    """Pinned so that any change to a word list, a pattern, the stand-in or the engine is a visible, reviewed change to these numbers."""
    a, b = runs
    count = lambda r: dict(collections.Counter(d["outcome"] for d in r["decisions"]))
    assert count(a) == {"CREATE_IDENTITY": 78, "IDENTITY_REVIEW": 94, "HOLD": 1028}
    assert count(b) == {"CREATE_IDENTITY": 78, "IDENTITY_REVIEW": 385, "HOLD": 737}


@needs_package
def test_only_plans_never_writes(runs):
    for r in runs:
        creates = [d for d in r["decisions"] if d["outcome"] == "CREATE_IDENTITY"]
        assert all(d["write_plan"] and d["identity"] for d in creates)
        assert all(d["write_plan"] is None and d["identity"] is None for d in r["decisions"] if d["outcome"] != "CREATE_IDENTITY")
        assert all(S.validate_decision(d) == [] for d in r["decisions"])
        for d in creates:
            shell = next(o for o in d["write_plan"]["operations"] if o["op"] == "INSERT_IDENTITY_SHELL")["values"]
            assert set(shell) == set(S.policy()["writes"]["shell_columns"])
            assert shell["identity_state"] == "DISCOVERED" and shell["enrichment_state"] == "PENDING"
            assert d["write_plan"]["apply_mode"] == "PROPOSE"


@needs_package
def test_creates_are_the_same_whether_or_not_the_resolver_stand_in_filters_first(runs):
    a, b = runs
    ids = lambda r: {d["subject"]["entity_id"] for d in r["decisions"] if d["outcome"] == "CREATE_IDENTITY"}
    assert ids(a) == ids(b), "Bootstrap's own duplicate defences must catch what the resolver would have mapped"


@needs_package
def test_no_unsettled_identity_is_ever_created(runs):
    for r in runs:
        status = {s["entity_id"]: s["identity_status"] for s in r["snapshot"]["subjects"]}
        for d in r["decisions"]:
            if d["outcome"] == "CREATE_IDENTITY":
                assert status[d["subject"]["entity_id"]] == "settled"
            if status[d["subject"]["entity_id"]] != "settled":
                assert d["outcome"] == "HOLD"


@needs_package
def test_volume_never_decides_on_the_real_data(runs):
    a, _ = runs
    base = [(d["subject"]["entity_id"], d["outcome"], d["reason_codes"], d["identity"]) for d in a["decisions"]]
    for fill in (0, 3, 10_000_000):
        snap = copy.deepcopy(a["snapshot"])
        for s in snap["subjects"]:
            s["units"] = fill
        out = S.run_decide(snap, impl="engine")
        assert [(d["subject"]["entity_id"], d["outcome"], d["reason_codes"], d["identity"]) for d in out] == base


@needs_package
def test_engine_and_oracle_agree_on_all_1200_real_subjects(runs):
    for r in runs:
        assert S.run_decide(copy.deepcopy(r["snapshot"]), impl="oracle") == r["decisions"]


@needs_package
def test_the_real_run_is_deterministic_and_the_report_is_byte_stable(runs, tmp_path):
    a, b = runs
    first = report.analyse(a, b)
    again = report.analyse(shadow_run.run("A", pkg=a["package"]), shadow_run.run("B", pkg=a["package"]))
    for s in (first, again):
        s.pop("inputs")["engine_seconds"]
    assert json.dumps(first, sort_keys=True) == json.dumps(again, sort_keys=True)


@needs_package
def test_the_known_mutual_split_is_held_not_guessed(runs):
    a, _ = runs
    by = {d["subject"]["entity_id"]: d for d in a["decisions"]}
    for gid in ("mini-mini-cooper-ev", "mini-mini-jcw-convertible"):
        assert by[gid]["outcome"] == "HOLD" and "LINEAGE_UNRESOLVED" in by[gid]["reason_codes"]


@needs_package
def test_the_brief_examples_on_real_names(runs):
    a, b = runs
    by = {m: {d["subject"]["entity_id"]: d for d in r["decisions"]} for m, r in (("A", a), ("B", b))}
    for mode in "AB":
        for gid in ("mercedes-benz-mercedes-benz-e300", "NISSAN|BVL2RTYD23FHP A", "honda-city-hatchback", "toyota-hilux-revo"):
            assert by[mode][gid]["outcome"] != "CREATE_IDENTITY" and by[mode][gid]["write_plan"] is None, (mode, gid)
        assert by[mode]["ISUZU|ไม่ระบุ"]["outcome"] == "HOLD" and "NAME_UNSPECIFIED" in by[mode]["ISUZU|ไม่ระบุ"]["reason_codes"]
        assert by[mode]["NISSAN|BVL2RTYD23FHP A"]["primary_reason"] == "PROVIDER_RAW_NAME"
    e300 = by["B"]["mercedes-benz-mercedes-benz-e300"]["reason_codes"]
    assert "POSSIBLE_MODEL_CODE" in e300 and "DUPLICATE_CANONICAL_SUSPECTED" in e300
    assert {"PROVIDER_FINER_THAN_TDR", "POSSIBLE_BODY_VARIANT"} <= set(by["B"]["honda-city-hatchback"]["reason_codes"])


@needs_package
def test_the_shadow_run_is_read_only(runs, tmp_path):
    watched = [PKG_PATH, *sorted(shadow_run.DEFAULT_MODELS.glob("*.json")), shadow_run.DEFAULT_LEGACY]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    a, b = runs
    summary = report.analyse(a, b)
    paths = report.write_files(summary, a, b, tmp_path)
    assert {p.name for p in paths} == {"decisions.csv", "summary.json", "REPORT.md", "plans_sample.json"} and all(tmp_path in p.parents for p in paths)
    assert {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in watched} == before


@needs_package
def test_the_committed_results_match_the_run(runs, tmp_path):
    """The reviewed REPORT.md / decisions.csv in the repo are exactly what the current code produces."""
    committed = Path(shadow_run.__file__).parent / "results" / "2569-09_v3_M7.0"
    if not committed.exists():
        pytest.skip("results not committed yet")
    a, b = runs
    refined = {"A": shadow_run.run("A", pkg=a["package"], refined=True), "B": shadow_run.run("B", pkg=a["package"], refined=True)}
    summary = report.analyse(a, b, refined=refined)
    report.write_files(summary, a, b, tmp_path)
    for name in ("decisions.csv", "REPORT.md"):
        assert (tmp_path / name).read_text(encoding="utf-8") == (committed / name).read_text(encoding="utf-8"), f"{name} is stale: re-run python -m identity_bootstrap.shadow --out {committed}"
