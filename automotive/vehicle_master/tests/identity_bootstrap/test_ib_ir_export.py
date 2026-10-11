"""PR #200's full relation export, consumed fail-closed. PORTABLE: needs neither the archived M7.0 package nor the PR #200 git objects (the export bytes are vendored and hash-pinned)."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from identity_bootstrap.shadow import ir_export, run as shadow_run, stand_in, tdr_catalog
from identity_bootstrap.shadow.ir_export import ExportError, RELATIONS

SRC = ir_export.DIR
RESULTS = Path(ir_export.__file__).parent / "results" / "2569-09_v3_M7.0"


@pytest.fixture(scope="module")
def export():
    return ir_export.load()


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canon(r: dict) -> str:
    return json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ------------------------------------------------------------------------------------------------------------- the pin and the universe
def test_the_vendored_bytes_are_the_pinned_producer_export(export):
    m = export.manifest
    assert ir_export.PIN["producer_commit"] == "eed76aa6ad6380afea60d604e5e7eac87abedb06" and ir_export.PIN["producer_pr"] == 200
    assert sha((SRC / "MANIFEST.json").read_bytes()) == ir_export.PIN_MANIFEST_SHA256
    assert (m["schema_version"], m["export_id"], m["consumer_contract_version"]) == ("ir-relation-export/1", "ir-rev4-m7.0-relations/1", "ir-relation-export-consumer/1")
    assert m["contract"]["adoption_binding"] is False and m["contract"]["status"] == "draft_not_frozen" and m["contract"]["revision"] == 4
    assert m["universes"]["ice"]["id"] == "ice:2569-09:v3:M7.0" and m["universes"]["tdr"]["id"] == "tdr_vehicle_models:sha256-e75f970a6957fd42"
    assert m["sources"]["ice_package"]["sha256"] == "c558d2d4cc3ed667f8b30ea028dbb66c4030cdce4e7daabe735df870cb94677d"
    for name in (*ir_export.DATA_FILES, *ir_export.STATIC_FILES):
        meta = m["files"].get(name) or m["static_files"][name]
        assert sha((SRC / name).read_bytes()) == meta["sha256"]


def test_all_nine_kinds_in_both_populations_and_the_counts_of_the_manifest(export):
    for pop, rows, n in (("ice_ice", export.ice_ice, 26505), ("ice_tdr", export.ice_tdr, 12412)):
        counts = collections.Counter(r["r"] for r in rows.values())
        assert len(rows) == n and set(counts) == set(RELATIONS), pop
        assert {k: counts[k] for k in RELATIONS} == {k: export.manifest["populations"][pop]["relation_counts"].get(k, 0) for k in RELATIONS}
    assert (len(export.subjects), len(export.tdr)) == (1200, 323)
    assert sum(1 for s in export.subjects.values() if not s["pool"]) == 226


def test_pair_completeness_ordering_keys_and_per_subject_coverage(export):
    keys = list(export.ice_ice)
    assert keys == [f"{r['a']}|{r['b']}" for r in export.ice_ice.values()] and [(r["a"], r["b"]) for r in export.ice_ice.values()] == sorted((r["a"], r["b"]) for r in export.ice_ice.values())
    for sid in export.subjects:
        peers = export.peers(sid)
        assert len(export.rows_by_subject_ice.get(sid, [])) == len(peers)                       # (brand string size) - 1 rows involve the subject
        assert [r["b"] for r in sorted(export.rows_by_subject_tdr.get(sid, []), key=lambda r: r["b"])] == export.pool(sid)
        assert len(export.pool(sid)) + sum(export.subjects[sid]["pool_excluded"].values()) == 323


def test_ids_containing_the_pipe_are_looked_up_by_the_whole_key(export):
    piped = [s for s in export.subjects if "|" in s]
    assert len(piped) == 591
    pair = next(r for r in export.ice_ice.values() if r["a"].count("|") == 1 and r["b"].count("|") == 1)
    assert pair["k"].count("|") == 3 and export.relation_ice_ice(pair["a"], pair["b"]) == pair["r"]
    row = next(r for r in export.ice_tdr.values() if "|" in r["a"])
    assert export.relation_ice_tdr(row["a"], row["b"]) == row["r"]


def test_orientation_reversal_flips_only_coarser_and_finer(export):
    flips = 0
    for r in export.ice_ice.values():
        fwd, rev = export.relation_ice_ice(r["a"], r["b"]), export.relation_ice_ice(r["b"], r["a"])
        assert fwd == r["r"]
        assert rev == ir_export.FLIP.get(r["r"], r["r"])
        flips += r["r"] in ir_export.FLIP
    assert flips == 78 + 40
    ex = next(r for r in export.ice_ice.values() if r["r"] == "SUBJECT_COARSER")
    assert export.relation_ice_ice(ex["b"], ex["a"]) == "SUBJECT_FINER"


def test_a_missing_pair_is_an_error_never_a_contradiction(export):
    sid = next(iter(export.subjects))
    with pytest.raises(ExportError, match="PAIR_NOT_EVALUATED"):
        export.relation_ice_tdr(sid, "no.such_model")
    other_brand = next(s for s in export.subjects if export.subjects[s]["brand"] != export.subjects[sid]["brand"])
    with pytest.raises(ExportError, match="PAIR_NOT_EVALUATED"):
        export.relation_ice_ice(sid, other_brand)                            # different Ice brand strings: not evaluated, so NOT a CONTRADICTION
    with pytest.raises(ExportError):
        export.relation_ice_ice(sid, sid)
    notpooled = next(t for t in export.tdr if t not in set(export.pool(sid)))
    with pytest.raises(ExportError, match="PAIR_NOT_EVALUATED"):
        export.relation_ice_tdr(sid, notpooled)                              # outside the pool: not compared, not a relation


def test_the_honda_synonyms_and_the_digit_fuzzy_corrections_are_in_the_export(export):
    assert export.relation_ice_ice("honda-honda-fit", "honda-jazz") == "EQUAL_VIA_MODEL_ALIAS"
    assert export.relation_ice_tdr("honda-honda-stepwagon", "honda.step_wgn") == "EQUAL_VIA_MODEL_ALIAS"
    assert export.relation_ice_ice("volvo-volvo-xc60", "volvo-volvo-xc90") not in ("FUZZY", "EQUAL")


def test_the_universe_matches_the_committed_shadow_input_without_the_archived_package(export):
    rows = list(csv.DictReader((RESULTS / "decisions.csv").open(encoding="utf-8")))
    ir_export.verify_universe(export, rows, tdr_catalog.load(shadow_run.DEFAULT_MODELS, shadow_run.DEFAULT_LEGACY, True))


def catalog():
    import copy
    return copy.deepcopy(tdr_catalog.load(shadow_run.DEFAULT_MODELS, shadow_run.DEFAULT_LEGACY, True))


def test_a_different_ice_or_tdr_universe_is_refused(export):
    rows = list(csv.DictReader((RESULTS / "decisions.csv").open(encoding="utf-8")))
    cat = catalog()
    with pytest.raises(ExportError, match="Ice universe differs"):
        ir_export.verify_universe(export, rows[:-1], cat)
    renamed = [dict(r) for r in rows]
    renamed[5]["model_name"] += " x"
    with pytest.raises(ExportError, match="SUBJECT_DIFFERS"):
        ir_export.verify_universe(export, renamed, cat)
    short = {**cat, "identities": cat["identities"][:-1]}
    with pytest.raises(ExportError, match="TDR universe differs"):
        ir_export.verify_universe(export, rows, short)


# ------------------------------------------------------------------------------------------------------------- finding 1: the TDR fields the routing reads are bound to the producer snapshot
def verify(export, mutate):
    rows = list(csv.DictReader((RESULTS / "decisions.csv").open(encoding="utf-8")))
    cat = catalog()
    mutate(cat)
    ir_export.verify_universe(export, rows, cat)


def test_the_bound_tdr_snapshot_is_vendored_hash_checked_and_named_by_the_universe_id(export):
    for n in ir_export.TDR_INPUT_FILES:
        assert sha((SRC / "tdr_inputs" / n).read_bytes()) == export.manifest["sources"]["tdr_inputs"][n]
    assert export.manifest["universes"]["tdr"]["id"].endswith(export.manifest["sources"]["tdr_inputs"]["tdr_models.json"][:16])
    assert len(export.tdr_models) == 323 and len(export.tdr_brands) == 62 and set(export.allowed_statuses) == {"CURRENT", "HISTORICAL", "UNVERIFIED"}
    assert export.tdr_models["audi.a8"]["aliases"] == ["A8L", "A8"]
    assert ir_export.alias_binding_summary(export)["alias_strings"] == 662


def test_the_real_catalog_matches_the_bound_snapshot_on_brand_status_and_aliases(export):
    verify(export, lambda cat: None)


@pytest.mark.parametrize("mutate,match", [
    (lambda c: c["aliases"].__setitem__("audi.a8", ["A8"]), "TDR_ALIASES_DIFFER: 'audi.a8'"),                                   # an alias removed: the A8L collision would vanish
    (lambda c: c["aliases"].__setitem__("audi.a8", ["A8L", "A8", "A8 Long"]), "TDR_ALIASES_DIFFER"),                              # an alias added
    (lambda c: c["aliases"].__setitem__("wuling.wuling_bingo", ["bingo"]), "TDR_ALIASES_DIFFER"),
    (lambda c: c["aliases"].__setitem__("audi.a1", ["A1L"]), "TDR_ALIASES_DIFFER"),                                             # an alias on a model that had none
    (lambda c: c.__setitem__("historical", [*c["historical"], "audi.a8"]), "TDR_STATUS_DIFFERS: 'audi.a8'"),                    # CURRENT -> HISTORICAL
    (lambda c: c.__setitem__("historical", c["historical"][1:]), "TDR_STATUS_DIFFERS"),                                         # HISTORICAL -> CURRENT
    (lambda c: next(i for i in c["identities"] if i["canonical_id"] == "audi.a8").__setitem__("brand_id", "bmw"), "TDR_BRAND_DIFFERS: 'audi.a8'"),
    (lambda c: next(i for i in c["identities"] if i["canonical_id"] == "audi.a8").__setitem__("name_en", "A8 L"), "TDR target differs"),
    (lambda c: next(i for i in c["identities"] if i["canonical_id"] == "audi.a8").__setitem__("deleted", True), "TDR target differs"),
    (lambda c: c["brands"]["audi"].__setitem__("name_en", "Audi AG"), "TDR_BRAND_DIFFERS: 'audi'"),
    (lambda c: c["brands"].pop("audi"), "TDR brand universe differs"),
])
def test_a_changed_brand_status_or_alias_fails_closed_instead_of_changing_the_routing(export, mutate, match):
    with pytest.raises(ExportError, match=match):
        verify(export, mutate)


def test_a_changed_alias_would_otherwise_have_changed_owner_review_routing(export):
    """Why the binding matters: the catalog-alias evidence reads exactly these aliases. Removing 'A8L' from audi.a8 would drop Audi A8L out of mandatory owner review."""
    from identity_bootstrap.routing import signals
    cat = catalog()
    subs = [{"entity_id": "audi-audi-a8l", "display_name": "Audi A8L", "identity_status": "settled", "relations": [], "brand": {"raw": "AUDI", "brand_id": "audi", "relation": "EXACT", "spellings": ["Audi", "AUDI"]}}]
    from identity_bootstrap.engine.lexical import Lexicon
    from identity_bootstrap.contract import loader
    lex = Lexicon(loader.load_policy())
    hit = signals.catalog_alias_evidence(subs, cat, lambda g: ["audi.a8"], lex.tokens, ["audi-audi-a8l"])
    assert hit["audi-audi-a8l"][0]["alias"] == "A8L"
    cat["aliases"]["audi.a8"] = ["A8"]
    assert signals.catalog_alias_evidence(subs, cat, lambda g: ["audi.a8"], lex.tokens, ["audi-audi-a8l"]) == {}
    with pytest.raises(ExportError):
        verify(export, lambda c: c["aliases"].__setitem__("audi.a8", ["A8"]))              # ...which is exactly what the binding refuses


def test_the_vendored_tdr_snapshot_cannot_be_altered_or_swapped(tmp_path):
    for n in ir_export.TDR_INPUT_FILES:
        d = copy_export(tmp_path / n.replace(".", "_"))
        blob = bytearray((d / "tdr_inputs" / n).read_bytes())
        blob[len(blob) // 2] ^= 0x01
        (d / "tdr_inputs" / n).write_bytes(bytes(blob))
        with pytest.raises(ExportError, match="tdr_inputs"):
            ir_export.load(d)
    d = copy_export(tmp_path / "gone")
    (d / "tdr_inputs" / "tdr_models.json").unlink()
    with pytest.raises(ExportError, match="missing"):
        ir_export.load(d)


def test_a_snapshot_edited_consistently_with_its_manifest_hash_is_still_refused_by_the_universe_id(tmp_path):
    d = copy_export(tmp_path)
    models = json.loads((d / "tdr_inputs" / "tdr_models.json").read_text(encoding="utf-8"))
    models[0]["aliases"] = [*models[0]["aliases"], "extra"]
    blob = json.dumps(models, ensure_ascii=False).encode("utf-8")
    (d / "tdr_inputs" / "tdr_models.json").write_bytes(blob)
    m = json.loads((d / "MANIFEST.json").read_text(encoding="utf-8"))
    m["sources"]["tdr_inputs"]["tdr_models.json"] = sha(blob)
    mb = (json.dumps(m, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode()
    (d / "MANIFEST.json").write_bytes(mb)
    with pytest.raises(ExportError, match="TDR universe id|does not name"):
        ir_export.load(d, pin_manifest_sha256=sha(mb))


def test_targets_that_disagree_with_the_bound_snapshot_are_refused(tmp_path):
    d = copy_export(tmp_path)
    mh = rewrite(d, "tdr_targets.jsonl", lambda r: [{**x, "status": "HISTORICAL"} if x["id"] == "audi.a8" else x for x in r])
    with pytest.raises(ExportError, match="differs from the bound TDR snapshot"):
        ir_export.load(d, pin_manifest_sha256=mh)


# ------------------------------------------------------------------------------------------------------------- finding 2: brand parity against the export's brand relations and pools
def first_subject(export, brand_id, only=True):
    for sid in export.subjects:
        pool = export.pool(sid)
        brands = {export.tdr_models[t]["brand_id"] for t in pool}
        if pool and ((brands == {brand_id}) if only else (brand_id in brands)):
            return sid
    raise AssertionError(brand_id)


def test_the_correct_brand_resolution_has_no_mismatch_on_real_subjects(export):
    sid = first_subject(export, "honda")
    assert ir_export.brand_pool_mismatches({"brand_id": "honda", "relation": "EXACT"}, export.pool(sid), export, sid) == []
    sid = first_subject(export, "changan", only=False)
    family = [{"brand_id": "deepal", "relation": "ALIAS_RELABEL", "spellings": ["Deepal"]}]
    assert ir_export.brand_pool_mismatches({"brand_id": "changan", "relation": "EXACT", "family": family}, export.pool(sid), export, sid) == []


def test_a_wrong_but_non_null_brand_resolution_is_a_mismatch(export):
    sid = first_subject(export, "honda")
    out = ir_export.brand_pool_mismatches({"brand_id": "toyota", "relation": "EXACT"}, export.pool(sid), export, sid)
    assert out and all(x.startswith("BRAND_RESOLUTION_VS_POOL") for x in out)
    assert any("is brand 'honda', but the shadow resolved 'toyota'" in x for x in out) and any("lacks allowed model(s) of resolved brand 'toyota'" in x for x in out)


def test_a_declared_family_must_match_the_export_and_an_undeclared_one_is_a_mismatch(export):
    sid = first_subject(export, "changan", only=False)
    pool = export.pool(sid)
    assert any(export.ice_tdr[f"{sid}|{t}"]["br"] == "ALIAS_RELABEL" for t in pool)
    no_family = ir_export.brand_pool_mismatches({"brand_id": "changan", "relation": "EXACT"}, pool, export, sid)
    assert any("deepal" in x and "shadow resolved 'changan'" in x for x in no_family)
    wrong_relation = ir_export.brand_pool_mismatches({"brand_id": "changan", "relation": "EXACT", "family": [{"brand_id": "deepal", "relation": "ALIAS_SAME"}]}, pool, export, sid)
    assert any("export brand relation ALIAS_RELABEL, the shadow says ALIAS_SAME" in x for x in wrong_relation)


def test_a_relation_that_contradicts_the_export_brand_relation_is_a_mismatch(export):
    sid = first_subject(export, "honda")
    out = ir_export.brand_pool_mismatches({"brand_id": "honda", "relation": "ALIAS_SAME"}, export.pool(sid), export, sid)
    assert out and any("export brand relation EXACT, the shadow says ALIAS_SAME" in x for x in out)


def test_resolved_with_an_empty_pool_and_unresolved_with_a_pool_stay_unresolved_with_the_exact_reason(export):
    empty = next(s for s in export.subjects if not export.pool(s))
    assert ir_export.brand_pool_mismatches({"brand_id": "honda", "relation": "EXACT"}, [], export, empty)[0].endswith("but the export pool is empty (brand relation not allowed)")
    sid = first_subject(export, "honda")
    assert ir_export.brand_pool_mismatches({"brand_id": None, "relation": "NOT_IN_TDR"}, export.pool(sid), export, sid) == ["BRAND_RESOLUTION_VS_POOL: the export has a pool but the shadow does not resolve the brand"]
    assert ir_export.brand_pool_mismatches({"brand_id": None, "relation": "NOT_IN_TDR"}, [], export, empty) == []


def test_a_pool_that_lacks_an_allowed_model_of_the_resolved_brand_is_a_mismatch(export):
    sid = first_subject(export, "honda")
    cut = export.pool(sid)[1:]
    out = ir_export.brand_pool_mismatches({"brand_id": "honda", "relation": "EXACT"}, cut, export, sid)
    assert any("lacks allowed model(s) of resolved brand 'honda'" in x for x in out), out


def test_deleted_and_out_of_pool_status_models_are_not_demanded_of_the_pool():
    exp, ids, _ = synthetic_export()
    exp.tdr_models = {"x.m0": {"brand_id": "x", "status": "CURRENT", "deleted": False}, "x.m1": {"brand_id": "x", "status": "CURRENT", "deleted": True},
                      "x.m2": {"brand_id": "x", "status": "WITHDRAWN", "deleted": False}, **{f"x.m{n}": {"brand_id": "y", "status": "CURRENT", "deleted": False} for n in range(3, 9)}}
    exp.allowed_statuses = ("CURRENT", "HISTORICAL", "UNVERIFIED")
    for k, r in exp.ice_tdr.items():
        r["br"] = "EXACT"
    pool = ["x.m0"]
    assert ir_export.brand_pool_mismatches({"brand_id": "x", "relation": "EXACT"}, pool, exp, ids[0]) == []
    exp.tdr_models["x.m1"]["deleted"] = False
    assert any("lacks allowed model" in r for r in ir_export.brand_pool_mismatches({"brand_id": "x", "relation": "EXACT"}, pool, exp, ids[0]))


@pytest.mark.skipif(not (RESULTS / "summary.json").exists(), reason="results not committed")
def test_the_eight_unresolved_subjects_are_preserved_and_the_report_binds_the_aliases():
    s = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))["m5"]["parity"]
    assert (s["subjects"]["resolved"], s["subjects"]["unresolved"]) == (1192, 8)
    assert s["tdr_universe_binding"]["alias_strings"] == 662 and s["tdr_universe_binding"]["models_with_aliases"] == 296 and s["tdr_universe_binding"]["statuses"] == {"CURRENT": 318, "HISTORICAL": 5}


# ------------------------------------------------------------------------------------------------------------- fail closed on altered / mismatched data
def copy_export(tmp_path: Path) -> Path:
    d = tmp_path / "ir"
    shutil.copytree(SRC, d)
    return d


def rewrite(d: Path, name: str, fn) -> str:
    """Mutate a data file consistently (records re-serialised canonically) and fix the manifest's sha/bytes/lines so ONLY the structural checks can catch it. Returns the new manifest sha256."""
    recs = [json.loads(l) for l in (d / name).read_text(encoding="utf-8").split("\n")[:-1]]
    recs = fn(recs)
    blob = ("\n".join(canon(r) for r in recs) + "\n").encode("utf-8")
    (d / name).write_bytes(blob)
    m = json.loads((d / "MANIFEST.json").read_text(encoding="utf-8"))
    m["files"][name] = {"bytes": len(blob), "lines": len(recs), "sha256": sha(blob)}
    mb = (json.dumps(m, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    (d / "MANIFEST.json").write_bytes(mb)
    return sha(mb)


def test_any_altered_byte_of_any_file_is_refused(tmp_path):
    for name in (*ir_export.DATA_FILES, *ir_export.STATIC_FILES, "MANIFEST.json"):
        d = copy_export(tmp_path / name.replace(".", "_"))
        blob = bytearray((d / name).read_bytes())
        blob[len(blob) // 2] ^= 0x01
        (d / name).write_bytes(bytes(blob))
        with pytest.raises(ExportError):
            ir_export.load(d)


def test_a_missing_file_is_refused(tmp_path):
    d = copy_export(tmp_path)
    (d / "pairs_ice_tdr.jsonl").unlink()
    with pytest.raises(ExportError, match="missing"):
        ir_export.load(d)


@pytest.mark.parametrize("key,value,match", [("export_id", "ir-rev5-m7.0-relations/1", "export_id"), ("schema_version", "ir-relation-export/2", "schema_version"),
                                            ("producer_commit", "x", None), ("ice_universe_id", "ice:2569-10:v1:M8.0", "Ice universe id"),
                                            ("ice_package_sha256", "0" * 64, "Ice package sha256"), ("tdr_universe_id", "tdr_vehicle_models:sha256-0000000000000000", "TDR universe id")])
def test_a_pin_mismatch_is_refused(key, value, match):
    pin = {**ir_export.PIN, key: value}
    if match is None:
        pin["producer_commit"] = value
        assert ir_export.load(pin=pin) is not None, "the commit is provenance, checked by the manifest hash, not by a runtime string"
        return
    with pytest.raises(ExportError, match=match):
        ir_export.load(pin=pin)


def test_a_wrong_manifest_pin_is_refused():
    with pytest.raises(ExportError, match="MANIFEST.json sha256 differs"):
        ir_export.load(pin_manifest_sha256="0" * 64)


def test_a_binding_or_frozen_producer_contract_is_refused(tmp_path):
    d = copy_export(tmp_path)
    m = json.loads((d / "MANIFEST.json").read_text(encoding="utf-8"))
    m["contract"]["adoption_binding"] = True
    mb = (json.dumps(m, indent=1, sort_keys=True) + "\n").encode()
    (d / "MANIFEST.json").write_bytes(mb)
    with pytest.raises(ExportError, match="contract block differs|draft with binding false"):
        ir_export.load(d, pin_manifest_sha256=sha(mb))


@pytest.mark.parametrize("name,fn,match", [
    ("pairs_ice_ice.jsonl", lambda r: r[:-1], "pair count|key digest|full same-brand"),
    ("pairs_ice_ice.jsonl", lambda r: [r[1], r[0], *r[2:]], "not sorted"),
    ("pairs_ice_ice.jsonl", lambda r: [{**r[0], "r": "NOT_A_RELATION"}, *r[1:]], "malformed"),
    ("pairs_ice_ice.jsonl", lambda r: [{**r[0], "k": "wrong|key"}, *r[1:]], "key does not equal"),
    ("pairs_ice_ice.jsonl", lambda r: [{**r[0], "b": "ZZZ|OUT OF UNIVERSE", "k": r[0]["a"] + "|ZZZ|OUT OF UNIVERSE"}, *r[1:]], "key digest|out-of-universe|not sorted"),
    ("pairs_ice_ice.jsonl", lambda r: [{**r[0], "r": "SIBLING" if r[0]["r"] != "SIBLING" else "EQUAL"}, *r[1:]], "relation counts"),
    ("pairs_ice_tdr.jsonl", lambda r: r[:-1], "pair count|key digest|pool differs"),
    ("pairs_ice_tdr.jsonl", lambda r: [{**r[0], "b": "no.such_model", "k": r[0]["a"] + "|no.such_model"}, *r[1:]], "out-of-universe|key digest|not sorted"),
    ("pairs_ice_tdr.jsonl", lambda r: [{**r[0], "br": "NOPE"}, *r[1:]], "allowed brand relation"),
    ("ice_subjects.jsonl", lambda r: [{**r[0], "pool": ["audi.a1"]}, *r[1:]], "pool differs|pool \\+ excluded"),
    ("ice_subjects.jsonl", lambda r: [{**r[0], "pool_excluded": {"brand_not_allowed": 1, "deleted": 0, "status_not_in_pool": 0}}, *r[1:]], "pool \\+ excluded"),
    ("ice_subjects.jsonl", lambda r: r[:-1], "universe sizes"),
    ("tdr_targets.jsonl", lambda r: r[:-1], "universe sizes"),
    ("tdr_targets.jsonl", lambda r: [{**x, "deleted": True} if x["id"] == "audi.a1" else x for x in r], "breaks the pool rule"),
])
def test_consistently_rehashed_but_structurally_wrong_data_is_refused(tmp_path, name, fn, match):
    d = copy_export(tmp_path)
    mh = rewrite(d, name, fn)
    with pytest.raises(ExportError, match=match):
        ir_export.load(d, pin_manifest_sha256=mh)


def test_a_cross_brand_ice_pair_and_a_non_canonical_byte_form_are_refused(tmp_path):
    d = copy_export(tmp_path)
    def cross(recs):
        first = recs[0]
        other = next(s for s in json.loads("[" + ",".join((d / "ice_subjects.jsonl").read_text(encoding="utf-8").split("\n")[:-1]) + "]") if s["brand"] != "ABARTH")
        a, b = sorted([first["a"], other["id"]])
        return sorted([*recs[1:], {**first, "a": a, "b": b, "k": f"{a}|{b}"}], key=lambda r: (r["a"], r["b"]))
    mh = rewrite(d, "pairs_ice_ice.jsonl", cross)
    with pytest.raises(ExportError):
        ir_export.load(d, pin_manifest_sha256=mh)
    d2 = copy_export(tmp_path / "b")
    lines = (d2 / "tdr_targets.jsonl").read_text(encoding="utf-8").split("\n")
    lines[0] = json.dumps(json.loads(lines[0]), sort_keys=True, indent=1)                    # same data, not the canonical byte form
    (d2 / "tdr_targets.jsonl").write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(ExportError):
        ir_export.load(d2)


# ------------------------------------------------------------------------------------------------------------- the stand-in only looks up
def synthetic_export():
    """A tiny export exercising all nine kinds in BOTH populations, with ids that contain '|' and a reversed Ice x Ice orientation."""
    ids = sorted(["B|ALPHA", "B|BETA", "B|GAMMA", "B|DELTA", "B|EPS", "B|ZETA", "B|ETA", "B|THETA", "B|IOTA", "B|KAPPA"])
    kinds = list(RELATIONS)
    subjects = {i: {"id": i, "brand": "B", "name": i, "brands_observed": ["B"], "pool": [], "pool_excluded": {}} for i in ids}
    ii = {}
    for x in range(len(ids)):                                  # the full evaluated population: every pair of the brand string, CONTRADICTION unless the test sets a kind
        for y in range(x + 1, len(ids)):
            a, b = ids[x], ids[y]
            ii[f"{a}|{b}"] = {"a": a, "b": b, "k": f"{a}|{b}", "r": "CONTRADICTION", "s": 0.0}
    for n, rel in enumerate(kinds):
        a, b = ids[0], ids[n + 1]
        ii[f"{a}|{b}"] = {"a": a, "b": b, "k": f"{a}|{b}", "r": rel, "s": None if rel == "UNAVAILABLE" else 0.5}
    tdr = {f"x.m{n}": {"id": f"x.m{n}"} for n in range(9)}
    it = {}
    subjects[ids[0]]["pool"] = sorted(tdr)
    for n, rel in enumerate(kinds):
        it[f"{ids[0]}|x.m{n}"] = {"a": ids[0], "b": f"x.m{n}", "k": f"{ids[0]}|x.m{n}", "r": rel, "s": 0.5, "tb": []}
    return ir_export.RelationExport({}, subjects, tdr, ii, it), ids, kinds


def test_the_stand_in_passes_on_exactly_the_exported_relations_for_all_nine_kinds_in_both_populations():
    exp, ids, kinds = synthetic_export()
    cat = tdr_catalog.load(shadow_run.DEFAULT_MODELS, shadow_run.DEFAULT_LEGACY, True)
    from identity_bootstrap.contract import loader
    si = stand_in.StandIn(cat, loader.load_policy(), exp)
    tr = {r["peer_id"]: r["name_relation"] for r in si.target_relations(ids[0])}
    assert tr == {f"x.m{n}": rel for n, rel in enumerate(kinds) if rel not in ("CONTRADICTION", "UNAVAILABLE")}, "explicit CONTRADICTION/UNAVAILABLE are 'no objection', the other seven are passed on unchanged"
    sr = si.subject_relations(ids)
    assert {r["peer_id"]: r["name_relation"] for r in sr[ids[0]]} == {ids[n + 1]: rel for n, rel in enumerate(kinds) if rel not in ("CONTRADICTION", "UNAVAILABLE")}
    assert all(not v for g, v in sr.items() if g != ids[0]), "each pair is stated once, from the smaller id"
    assert exp.relation_ice_ice(ids[1 + kinds.index("SUBJECT_COARSER")], ids[0]) == "SUBJECT_FINER"           # reversal flips
    assert exp.relation_ice_ice(ids[1 + kinds.index("SUBJECT_FINER")], ids[0]) == "SUBJECT_COARSER"
    assert len(exp.consulted_ice_ice) == 45 and len(exp.consulted_ice_tdr) == 9


def test_the_stand_in_raises_on_a_pair_the_export_does_not_carry():
    exp, ids, _ = synthetic_export()
    exp.ice_ice.pop(f"{ids[0]}|{ids[3]}")
    cat = tdr_catalog.load(shadow_run.DEFAULT_MODELS, shadow_run.DEFAULT_LEGACY, True)
    from identity_bootstrap.contract import loader
    si = stand_in.StandIn(cat, loader.load_policy(), exp)
    with pytest.raises(ExportError, match="PAIR_NOT_EVALUATED"):
        si.subject_relations(ids)


def test_an_empty_pool_yields_no_relation_and_is_not_a_create_authorization():
    exp, ids, _ = synthetic_export()
    cat = tdr_catalog.load(shadow_run.DEFAULT_MODELS, shadow_run.DEFAULT_LEGACY, True)
    from identity_bootstrap.contract import loader
    si = stand_in.StandIn(cat, loader.load_policy(), exp)
    assert exp.pool(ids[1]) == [] and si.target_relations(ids[1]) == []
    from identity_bootstrap.routing import project
    d = {"subject": {"entity_id": ids[1]}, "outcome": "CREATE_IDENTITY"}
    assert project(d, "ACTIVE")["activation_authorized"] is False


def test_no_stand_in_matcher_or_partial_export_bridge_remains():
    import importlib
    import inspect
    src = inspect.getsource(stand_in) + inspect.getsource(shadow_run)
    for gone in ("def name_relation", "adjudicate", "TOKEN_EQUIVALENCE", "FUZZY_MIN_TOKEN", "_edit1", "refined"):
        assert gone not in src, gone
    with pytest.raises(ImportError):
        importlib.import_module("identity_bootstrap.shadow.ir_rev4")
    assert not (Path(ir_export.__file__).parent / "universe" / "ir_rev4").exists()


def test_the_vendored_files_are_byte_identical_to_the_producer_commit_when_it_is_present():
    """Skips (visibly, in the skip report) in an isolated checkout without the PR #200 git object; the hash pins above already hold the same facts offline."""
    import subprocess
    repo = Path(ir_export.__file__).resolve().parents[4]
    if subprocess.run(["git", "-C", str(repo), "cat-file", "-e", ir_export.PIN["producer_commit"]], capture_output=True).returncode != 0:
        pytest.skip("PR #200 commit not present in this clone")
    base = "automotive/vehicle_master/identity_resolution/calibration/relation_export"
    for name in ("MANIFEST.json", *ir_export.DATA_FILES, *ir_export.STATIC_FILES):
        blob = subprocess.run(["git", "-C", str(repo), "show", f"{ir_export.PIN['producer_commit']}:{base}/{name}"], check=True, capture_output=True).stdout
        assert blob == (SRC / name).read_bytes(), name
