"""Complete, deterministic, pair-level export of the M7.0 name relations, for consumers of Identity Resolution (first consumer: PR #201).

    cd automotive/vehicle_master
    python -m identity_resolution.calibration.relation_export build     # needs the archived M7.0 package; writes calibration/relation_export/
    python -m identity_resolution.calibration.relation_export verify    # offline, no package: the committed export is self-consistent and still what the evaluator says

What it is. Every relation in the export is produced by the existing reference evaluator (`ref_eval_core.name_relation`, and for Ice × TDR the single-target
candidate pools that `ref_eval_resolve.resolve` itself builds). This module decides nothing: it enumerates populations (Ice × Ice through
`lexical_pass.ice_ice_population`, Ice × TDR through the evaluator's own pools), calls the evaluator, and writes what came back. It imports nothing from the
Identity Bootstrap stand-in and contains no matcher. It is not the engine and changes no rule (contract v1 rev 4, `binding: false`, not frozen).

What it contains (`relation_export/`):
    MANIFEST.json            versions, source-blob sha256, universes, policy echo, file inventory, relation counts, coverage, cross-checks
    relation_export.schema.json   the record schemas (versioned)
    CONSUMER_CONTRACT.md     the hand-off: keys, ordering, pinning, candidate-pool reading, the lookup that replaces a stand-in, when a subject may clear
    ice_subjects.jsonl       the Ice universe, one record per model group: tokens, candidate pool, best/related relations, reference-evaluator outcome
    tdr_targets.jsonl        the TDR universe, one record per vehicle model, so pool membership can be re-derived
    pairs_ice_ice.jsonl      every evaluated Ice × Ice pair, all nine relation kinds
    pairs_ice_tdr.jsonl      every evaluated Ice × TDR pair (the candidate pool of each subject), all nine relation kinds

Determinism. Sorted keys, compact separators, UTF-8, one record per line, `\\n` line ends, no timestamps; ordering is (subject id, peer id) in code-point order.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path

from identity_resolution.contract import loader

from . import adapters as A
from . import lexical_pass as L
from . import ref_eval_core as P
from . import ref_eval_resolve as R

SCHEMA_VERSION = "ir-relation-export/1"
EXPORT_ID = "ir-rev4-m7.0-relations/1"
CONSUMER_CONTRACT_VERSION = "ir-relation-export-consumer/1"
OUT = A.CALIBRATION_DIR / "relation_export"

#: The nine relation kinds in SPEC 5.3 ladder order. The export carries all of them for both populations (zero counts included).
RELATIONS = list(L.RELATIONS)
#: Relations that are "no lexical link": a pair with one of these is not a related candidate.
UNRELATED = ("CONTRADICTION", "UNAVAILABLE")

FILES = {
    "ice_subjects": "ice_subjects.jsonl",
    "tdr_targets": "tdr_targets.jsonl",
    "pairs_ice_ice": "pairs_ice_ice.jsonl",
    "pairs_ice_tdr": "pairs_ice_tdr.jsonl",
}
STATIC_FILES = ("CONSUMER_CONTRACT.md", "relation_export.schema.json")
#: Repo-relative sources whose bytes the export pins: change any of them and the export must be regenerated.
SOURCE_PATHS = [
    "automotive/vehicle_master/identity_resolution/calibration/adapters.py",
    "automotive/vehicle_master/identity_resolution/calibration/lexical_pass.py",
    "automotive/vehicle_master/identity_resolution/calibration/ref_eval_core.py",
    "automotive/vehicle_master/identity_resolution/calibration/ref_eval_resolve.py",
    "automotive/vehicle_master/identity_resolution/calibration/relation_export.py",
    "automotive/vehicle_master/identity_resolution/contract/v1/policy.yaml",
    "automotive/vehicle_master/identity_resolution/contract/v1/provider_capabilities.yaml",
]
#: Committed TDR-side inputs the snapshot is built from (calibration/inputs/, hashes also in inputs/MANIFEST.json).
INPUT_FILES = ["tdr_models.json", "tdr_brands.json", "tdr_generations.json", "tdr_registrations_series.json", "r6_redirects.json", "ice_brand_aliases.json", "extract_meta.json"]
SNAPSHOT_SOURCE = {"label": "ice:2569-09:v3:M7.0", "attributes": {"period": "2569-09", "package_version": "3", "master_version": "7.0"}}
ICE_UNIVERSE_ID = "ice:2569-09:v3:M7.0"


# ----------------------------------------------------------------------------------------------------------------------------- bytes
def canonical_line(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def to_bytes(rows: list) -> bytes:
    return "".join(canonical_line(r) + "\n" for r in rows).encode("utf-8")


def manifest_bytes(manifest: dict) -> bytes:
    return (json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes())


def repo_file(relative: str) -> Path:
    return A.REPO_ROOT / relative


def key_digest(keys: list[str]) -> str:
    return sha256("\n".join(keys).encode("utf-8"))


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ----------------------------------------------------------------------------------------------------------------------------- universes
def subjects_from_ice(ice: dict) -> list[dict]:
    return [{"id": g["model_group_id"], "name": g["model_name"], "brand": g["brand"], "brands_observed": list(ice["brands_observed"].get(g["model_group_id"], []))}
            for g in sorted(ice["groups"], key=lambda g: g["model_group_id"])]


def subjects_from_export(directory: Path = OUT) -> list[dict]:
    return [{k: r[k] for k in ("id", "name", "brand", "brands_observed")} for r in load_rows(directory / FILES["ice_subjects"])]


def ice_like(subjects: list[dict]) -> dict:
    """The part of the package dict the population definition reads, rebuilt from a subject list (so the committed export can be re-evaluated without the package)."""
    return {"groups": [{"model_group_id": s["id"], "model_name": s["name"], "brand": s["brand"]} for s in subjects],
            "brands_observed": {s["id"]: list(s["brands_observed"]) for s in subjects}}


def series_free_snapshot(subjects: list[dict], ext: dict, as_of: str) -> dict:
    """A snapshot with names, brands and targets but no series: enough for every NAME relation and for each subject's candidate pool (neither reads a series)."""
    targets = A.build_targets(ext)
    for t in targets:
        t.pop("series", None)
    return {
        "contract_version": "v1", "policy_version": loader.load_policy()["policy"]["version"], "provider": A.PROVIDER, "source_version": SNAPSHOT_SOURCE,
        "as_of_period": as_of, "existing_mappings": [], "targets": targets,
        "subjects": [{"entity_kind": "model_group", "entity_id": s["id"], "display_name": s["name"], "brand": s["brand"], "brands_observed": list(s["brands_observed"]),
                      "identity_status": A.identity_status(s["id"])} for s in subjects],
    }


# ----------------------------------------------------------------------------------------------------------------------------- records
def _flags(sname, sbrand, tname, tbrand, observed) -> list[int]:
    """[subject brand prefix stripped, peer brand prefix stripped, subject name unavailable, peer name unavailable], from the evaluator's own `name_tokens`
    called exactly as `name_relation` calls it (each side with the other side's brand and the subject's observed brands as extra prefix spellings)."""
    _, s_stripped, s_avail = P.name_tokens(sname, sbrand, extra=(tbrand, *observed))
    _, t_stripped, t_avail = P.name_tokens(tname, tbrand, extra=(sbrand, *observed))
    return [int(s_stripped), int(t_stripped), int(not s_avail), int(not t_avail)]


def pair_rows_ice_ice(subjects: list[dict]) -> list[dict]:
    rows = []
    for a, c, obs in L.ice_ice_population(ice_like(subjects)):
        rel, score, ta, tc = P.name_relation(a["model_name"], a["brand"], c["model_name"], c["brand"], obs)
        rows.append({"k": f"{a['model_group_id']}|{c['model_group_id']}", "a": a["model_group_id"], "b": c["model_group_id"], "r": rel,
                     "s": None if score is None else P.q(score), "ta": ta, "tb": tc,
                     "n": _flags(a["model_name"], a["brand"], c["model_name"], c["brand"], obs)})
    rows.sort(key=lambda r: (r["a"], r["b"]))
    return rows


def pair_rows_ice_tdr(snapshot: dict, res: dict) -> list[dict]:
    """Every single-target candidate of every subject's pool, exactly as `resolve` built it (relation, score and tokens are its `evidence.name`)."""
    subjects = {s["entity_id"]: s for s in snapshot["subjects"]}
    targets = {t["target_id"]: t for t in snapshot["targets"]}
    rows = []
    for sid, cands in res["pools"].items():
        subj = subjects[sid]
        obs = tuple(subj.get("brands_observed", []))
        for c in cands:
            if len(c["target_ids"]) != 1:
                continue                      # link-set (bundle) candidates are combinations of pool members, not pool members
            tid = c["target_ids"][0]
            t = targets[tid]
            name = c["evidence"]["name"]
            rows.append({"k": f"{sid}|{tid}", "a": sid, "b": tid, "br": c["evidence"]["brand"]["relation"], "r": name["relation"], "s": name["score"],
                         "ta": name["subject_tokens"], "tb": name["target_tokens"],
                         "n": _flags(subj["display_name"], subj["brand"], t["display_name"], t["brand"], obs)})
    rows.sort(key=lambda r: (r["a"], r["b"]))
    return rows


def _excluded_counts(subj: dict, snapshot: dict, pool: set[str]) -> dict:
    """Why each non-pool TDR model is not in this subject's pool, by the three candidate-pool rules of SPEC 4 (policy `candidates.*`). The builder checks that
    pool + excluded accounts for the whole TDR universe and that the pool equals what `resolve` built, so this can never drift from the evaluator."""
    pol = loader.load_policy()["candidates"]
    out = {"brand_not_allowed": 0, "deleted": 0, "status_not_in_pool": 0}
    for t in snapshot["targets"]:
        if t["target_id"] in pool:
            continue
        rel = P.brand_relation(subj["brand"], t["brand"], tuple(subj.get("brands_observed", [])))[0]
        if rel not in pol["brand_relations_allowed"]:
            out["brand_not_allowed"] += 1
        elif t["deleted"] and pol["exclude_deleted_targets"]:
            out["deleted"] += 1
        else:
            out["status_not_in_pool"] += 1
    return out


def best_of(relations: dict[str, str]) -> tuple[str | None, list[str]]:
    if not relations:
        return None, []
    best = min(relations.values(), key=RELATIONS.index)
    return best, sorted(t for t, r in relations.items() if r == best)


def subject_rows(subjects: list[dict], snapshot: dict, res: dict, pairs: list[dict], with_outcomes: bool) -> list[dict]:
    by_subject: dict[str, dict[str, str]] = {s["id"]: {} for s in subjects}
    for p in pairs:
        by_subject[p["a"]][p["b"]] = p["r"]
    snap_subjects = {s["entity_id"]: s for s in snapshot["subjects"]}
    n_targets = len(snapshot["targets"])
    rows = []
    for s in subjects:
        rel = by_subject[s["id"]]
        pool = set(rel)
        resolve_pool = {c["target_ids"][0] for c in res["pools"][s["id"]] if len(c["target_ids"]) == 1}
        if pool != resolve_pool:
            raise AssertionError(f"{s['id']}: exported pool differs from the evaluator's pool")
        excluded = _excluded_counts(snap_subjects[s["id"]], snapshot, pool)
        if len(pool) + sum(excluded.values()) != n_targets:
            raise AssertionError(f"{s['id']}: pool {len(pool)} + excluded {excluded} does not account for {n_targets} TDR models")
        toks, stripped, avail = P.name_tokens(s["name"], s["brand"])
        best, best_targets = best_of(rel)
        related: dict[str, list[str]] = {}
        for tid, r in sorted(rel.items()):
            if r not in UNRELATED:
                related.setdefault(r, []).append(tid)
        row = {"id": s["id"], "name": s["name"], "brand": s["brand"], "brands_observed": s["brands_observed"], "tokens": toks, "prefix_stripped": bool(stripped),
               "name_available": bool(avail), "pool": sorted(pool), "pool_excluded": excluded, "best_relation": best, "best_targets": best_targets, "related": related}
        if with_outcomes:
            d = res["decisions"][s["id"]]
            row["outcome"] = {"outcome": d["outcome"], "primary_code": d.get("primary") or "", "target_ids": list(d.get("target_ids") or []), "link_type": d.get("link_type") or "",
                              "codes": sorted([c, role] for c, role in d["codes"])}
        rows.append(row)
    return rows


def target_rows(snapshot: dict) -> list[dict]:
    return [{"id": t["target_id"], "brand": t["brand"], "name": t["display_name"], "status": t["status"], "deleted": bool(t["deleted"])}
            for t in sorted(snapshot["targets"], key=lambda t: t["target_id"])]


# ----------------------------------------------------------------------------------------------------------------------------- build
def relation_counts(rows: list[dict]) -> dict:
    counts = {r: 0 for r in RELATIONS}
    for row in rows:
        counts[row["r"]] += 1
    return counts


def expected_ice_ice_pairs(subjects: list[dict]) -> int:
    """Independent of the evaluator: the number of unordered pairs inside each Ice brand string."""
    sizes: dict[str, int] = {}
    for s in subjects:
        sizes[s["brand"]] = sizes.get(s["brand"], 0) + 1
    return sum(n * (n - 1) // 2 for n in sizes.values())


def source_hashes(ice_blobs: dict | None) -> dict:
    inputs = {n: file_sha256(A.INPUTS_DIR / n) for n in INPUT_FILES}
    return {
        "ice_package": {"path": A.PACKAGE_RELATIVE, "sha256": A.PACKAGE_SHA256, **(ice_blobs or {})},
        "tdr_inputs": inputs,
        "evaluator_and_contract": {p: file_sha256(repo_file(p)) for p in SOURCE_PATHS},
    }


def static_file_entries(directory: Path = OUT) -> dict:
    """sha256 / size of the hand-written files shipped with the export (the schema and the consumer contract), so a consumer can pin them too."""
    out = {}
    for name in STATIC_FILES:
        data = (directory / name).read_bytes()
        out[name] = {"sha256": sha256(data), "bytes": len(data)}
    return out


def package_blobs(path: Path | None = None) -> dict:
    """sha256 of the inner members the names and the series come from (the dims table and the registration trend), plus the archive itself."""
    path = Path(path) if path else A.REPO_ROOT / A.PACKAGE_RELATIVE
    raw = path.read_bytes()
    outer = zipfile.ZipFile(io.BytesIO(raw))

    def panel(prefix):
        (name,) = [n for n in outer.namelist() if n.startswith(f"panels/{prefix}_") and n.endswith(".zip")]
        return zipfile.ZipFile(io.BytesIO(outer.read(name)))
    return {"bytes": len(raw), "dims_model_group_csv_sha256": sha256(panel("dims").read("dims/model_group.csv")),
            "reg_trend_csv_sha256": sha256(panel("reg_trend").read("data/reg_trend.csv"))}


def build(ice: dict | None = None, ext: dict | None = None, subjects: list[dict] | None = None, as_of: str | None = None, blobs: dict | None = None) -> dict[str, bytes]:
    """The whole export as {file name: bytes}.

    With `ice` (the archived package) the snapshot carries the real series and each subject gets the reference evaluator's outcome. With only `subjects`
    (the committed `ice_subjects.jsonl`) the snapshot is series-free: every relation, pool and pool count is identical, `outcome` is omitted."""
    ext = ext or A.load_extracts()
    if ice is not None:
        subjects = subjects_from_ice(ice)
        snapshot = A.build_snapshot(ice, ext)
    else:
        snapshot = series_free_snapshot(subjects, ext, as_of)
    res = R.resolve(snapshot)
    if "refusal" in res:
        raise RuntimeError(res["refusal"])
    ice_ice = pair_rows_ice_ice(subjects)
    ice_tdr = pair_rows_ice_tdr(snapshot, res)
    srows = subject_rows(subjects, snapshot, res, ice_tdr, with_outcomes=ice is not None)
    trows = target_rows(snapshot)
    payload = {FILES["ice_subjects"]: to_bytes(srows), FILES["tdr_targets"]: to_bytes(trows),
               FILES["pairs_ice_ice"]: to_bytes(ice_ice), FILES["pairs_ice_tdr"]: to_bytes(ice_tdr)}

    pol = loader.load_policy()
    pool_sizes = [len(r["pool"]) for r in srows]
    brand_groups: dict[str, int] = {}
    for s in subjects:
        brand_groups[s["brand"]] = brand_groups.get(s["brand"], 0) + 1
    tdr_hash = file_sha256(A.INPUTS_DIR / "tdr_models.json")
    manifest = {
        "schema_version": SCHEMA_VERSION, "export_id": EXPORT_ID, "consumer_contract_version": CONSUMER_CONTRACT_VERSION,
        "contract": {"version": "v1", "revision": pol["policy"]["revision"], "policy_version": pol["policy"]["version"], "status": pol["policy"]["status"],
                     "adoption_binding": loader.load_adoption()["binding"]},
        "universes": {"ice": {"id": ICE_UNIVERSE_ID, "subjects": len(srows), "as_of_period": snapshot["as_of_period"]},
                      "tdr": {"id": f"tdr_vehicle_models:sha256-{tdr_hash[:16]}", "targets": len(trows)}},
        "sources": source_hashes(blobs if blobs is not None else (package_blobs() if ice is not None else None)),
        "evaluator": {"relation": "calibration.ref_eval_core.name_relation", "ice_tdr_population": "calibration.ref_eval_resolve.resolve()['pools'] (single-target candidates)",
                      "ice_ice_population": "calibration.lexical_pass.ice_ice_population (same Ice brand string, smaller model_group_id first)",
                      "outcome": "calibration.ref_eval_resolve.resolve()['decisions'] on the series-carrying snapshot (dry run, binding false)"},
        "policy_echo": {"candidates.brand_relations_allowed": pol["candidates"]["brand_relations_allowed"], "candidates.exclude_deleted_targets": pol["candidates"]["exclude_deleted_targets"],
                        "candidates.target_statuses_in_pool": pol["candidates"]["target_statuses_in_pool"],
                        "lexical.name": pol["lexical"]["name"], "lexical.fuzzy_token": pol["lexical"]["fuzzy_token"],
                        "lexical.distinctive_token.required_for_relations": pol["lexical"]["distinctive_token"]["required_for_relations"]},
        "relation_order": RELATIONS,
        "ordering": "records sorted by (a, b) in code-point order; ice_subjects and tdr_targets by id; JSON keys sorted; compact separators; UTF-8; one record per line; no timestamps",
        "populations": {
            "ice_ice": {"file": FILES["pairs_ice_ice"], "pairs": len(ice_ice), "expected_pairs": expected_ice_ice_pairs(subjects), "brand_strings": len(brand_groups),
                        "relation_counts": relation_counts(ice_ice), "key_digest_sha256": key_digest([r["k"] for r in ice_ice])},
            "ice_tdr": {"file": FILES["pairs_ice_tdr"], "pairs": len(ice_tdr), "expected_pairs": sum(pool_sizes), "subjects": len(srows),
                        "subjects_with_empty_pool": sum(1 for n in pool_sizes if n == 0), "max_pool_size": max(pool_sizes), "relation_counts": relation_counts(ice_tdr),
                        "key_digest_sha256": key_digest([r["k"] for r in ice_tdr])},
        },
        "outcomes_included": ice is not None,
        "files": {name: {"sha256": sha256(b), "bytes": len(b), "lines": b.count(b"\n")} for name, b in sorted(payload.items())},
        "static_files": static_file_entries(),
    }
    payload["MANIFEST.json"] = manifest_bytes(manifest)
    return payload


def write(payload: dict[str, bytes], directory: Path = OUT) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in payload.items():
        (directory / name).write_bytes(data)


# ----------------------------------------------------------------------------------------------------------------------------- verify (offline)
def verify(directory: Path = OUT) -> list[str]:
    """Problems found in the committed export, using only committed files. Empty = consistent. (The tests do more; this is the quick gate.)"""
    problems = []
    manifest = json.loads((directory / "MANIFEST.json").read_text(encoding="utf-8"))
    if manifest_bytes(manifest) != (directory / "MANIFEST.json").read_bytes():
        problems.append("MANIFEST.json is not in canonical form")
    for name, meta in manifest["files"].items():
        data = (directory / name).read_bytes()
        if sha256(data) != meta["sha256"] or len(data) != meta["bytes"] or data.count(b"\n") != meta["lines"]:
            problems.append(f"{name} does not match its manifest entry")
    for name, meta in manifest["static_files"].items():
        data = (directory / name).read_bytes()
        if sha256(data) != meta["sha256"] or len(data) != meta["bytes"]:
            problems.append(f"{name} changed since the manifest was generated")
    for relative, digest in {**manifest["sources"]["evaluator_and_contract"]}.items():
        if file_sha256(repo_file(relative)) != digest:
            problems.append(f"{relative} changed since the export was generated")
    for name, digest in manifest["sources"]["tdr_inputs"].items():
        if file_sha256(A.INPUTS_DIR / name) != digest:
            problems.append(f"calibration/inputs/{name} changed since the export was generated")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sub.add_parser("verify")
    args = ap.parse_args(argv)
    if args.cmd == "build":
        ice, ext = A.load_ice_package(), A.load_extracts()
        payload = build(ice=ice, ext=ext, blobs=package_blobs())
        write(payload)
        m = json.loads(payload["MANIFEST.json"])
        print(json.dumps({"populations": {k: {"pairs": v["pairs"], "relation_counts": v["relation_counts"]} for k, v in m["populations"].items()},
                          "files": m["files"]}, indent=1, sort_keys=True))
        return 0
    problems = verify()
    print("\n".join(problems) if problems else "relation export is consistent with its manifest and its pinned sources")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
