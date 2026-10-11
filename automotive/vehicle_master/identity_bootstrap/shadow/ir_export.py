"""PR #200's full pair-level relation export, consumed fail-closed.

Identity Resolution owns every lexical relation. Its pinned producer commit published, for the same M7.0 snapshot, the relation of EVERY evaluated pair (all nine kinds, both
populations), each subject's candidate pool and the tokens compared. This module vendors those bytes unchanged (`universe/ir_relation_export/`), verifies them against the pins
below (consumer contract sections 3, 4 and 6), and exposes direct lookups. It computes no relation, defaults no pair, and invents nothing: a pair the export does not carry is an
`ExportError` for the caller to report, never a CONTRADICTION."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).parent
DIR = HERE / "universe" / "ir_relation_export"

PIN = {
    "producer_pr": 200,
    "producer_commit": "eed76aa6ad6380afea60d604e5e7eac87abedb06",
    "schema_version": "ir-relation-export/1",
    "export_id": "ir-rev4-m7.0-relations/1",
    "consumer_contract_version": "ir-relation-export-consumer/1",
    "ice_universe_id": "ice:2569-09:v3:M7.0",
    "ice_package_sha256": "c558d2d4cc3ed667f8b30ea028dbb66c4030cdce4e7daabe735df870cb94677d",
    "tdr_universe_id": "tdr_vehicle_models:sha256-e75f970a6957fd42",
    "contract": {"adoption_binding": False, "status": "draft_not_frozen", "revision": 4, "policy_version": "1.0.0", "version": "v1"},
}
PIN_MANIFEST_SHA256 = "e9d74e05ce9c09ad59bad2654d16fbb74e06969e929b7415b5e55a0fc2d2e0b8"      # sha256 of the vendored MANIFEST.json bytes at the producer commit
RELATIONS = ("EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV", "FUZZY", "SUBJECT_COARSER", "SUBJECT_FINER", "SIBLING", "CONTRADICTION", "UNAVAILABLE")
FLIP = {"SUBJECT_COARSER": "SUBJECT_FINER", "SUBJECT_FINER": "SUBJECT_COARSER"}
DATA_FILES = ("ice_subjects.jsonl", "tdr_targets.jsonl", "pairs_ice_ice.jsonl", "pairs_ice_tdr.jsonl")
STATIC_FILES = ("CONSUMER_CONTRACT.md", "relation_export.schema.json")
BRAND_RELATIONS = ("EXACT", "ALIAS_SAME", "ALIAS_RELABEL", "ALIAS_RELATED")


class ExportError(RuntimeError):
    """The export is missing, altered, mismatched or out of universe. Callers must stop; nothing may be inferred."""


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise ExportError(msg)


class RelationExport:
    def __init__(self, manifest: dict, subjects: dict, tdr: dict, ice_ice: dict, ice_tdr: dict):
        self.manifest, self.subjects, self.tdr, self.ice_ice, self.ice_tdr = manifest, subjects, tdr, ice_ice, ice_tdr
        self.consulted_ice_ice: set[str] = set()       # every key a caller actually read: lets a run PROVE it read the whole evaluated population
        self.consulted_ice_tdr: set[str] = set()
        self.by_brand: dict[str, list[str]] = {}
        for sid, s in subjects.items():
            self.by_brand.setdefault(s["brand"], []).append(sid)
        self.rows_by_subject_tdr: dict[str, list[dict]] = {}
        for r in ice_tdr.values():
            self.rows_by_subject_tdr.setdefault(r["a"], []).append(r)
        self.rows_by_subject_ice: dict[str, list[dict]] = {}
        for r in ice_ice.values():
            self.rows_by_subject_ice.setdefault(r["a"], []).append(r)
            self.rows_by_subject_ice.setdefault(r["b"], []).append(r)

    # ---- direct lookups: the only way the shadow obtains a relation
    def relation_ice_tdr(self, subject_id: str, canonical_id: str) -> str:
        row = self.ice_tdr.get(f"{subject_id}|{canonical_id}")
        if row is not None:
            self.consulted_ice_tdr.add(row["k"])
        if row is None:
            raise ExportError(f"PAIR_NOT_EVALUATED ice x tdr: {subject_id!r} / {canonical_id!r}")
        return row["r"]

    def relation_ice_ice(self, first_id: str, second_id: str) -> str:
        """Relation of `first_id` to `second_id`. The export stores the smaller id first; the reverse orientation swaps COARSER <-> FINER."""
        _need(first_id != second_id, "an Ice subject is not paired with itself")
        a, b = (first_id, second_id) if first_id < second_id else (second_id, first_id)
        row = self.ice_ice.get(f"{a}|{b}")
        if row is None:
            raise ExportError(f"PAIR_NOT_EVALUATED ice x ice: {first_id!r} / {second_id!r}")
        _need(row["a"] == a and row["b"] == b, "key does not match its fields")
        self.consulted_ice_ice.add(row["k"])
        r = row["r"]
        return r if a == first_id else FLIP.get(r, r)

    def pool(self, subject_id: str) -> list[str]:
        return self.subjects[subject_id]["pool"]

    def peers(self, subject_id: str) -> list[str]:
        """Ice peers of a subject in the evaluated population (same Ice brand string), in code-point order."""
        brand = self.subjects[subject_id]["brand"]
        return sorted(p for p in self.by_brand[brand] if p != subject_id)


def _read_lines(blob: bytes, name: str) -> list[dict]:
    _need(blob.endswith(b"\n") or not blob, f"{name}: no trailing newline")
    out = []
    for i, line in enumerate(blob.decode("utf-8").split("\n")[:-1], 1):
        try:
            out.append(json.loads(line))
        except ValueError as e:
            raise ExportError(f"{name}:{i}: invalid JSON") from e
        _need(line == json.dumps(out[-1], sort_keys=True, separators=(",", ":"), ensure_ascii=False), f"{name}:{i}: not in the canonical byte form")
    return out


def load(directory: Path = DIR, pin: dict | None = None, pin_manifest_sha256: str | None = None) -> RelationExport:
    pin = pin or PIN
    pin_manifest = pin_manifest_sha256 or PIN_MANIFEST_SHA256
    try:
        raw = {n: (directory / n).read_bytes() for n in ("MANIFEST.json", *DATA_FILES, *STATIC_FILES)}
    except OSError as e:
        raise ExportError(f"export file missing: {e}") from e
    # 1. manifest and versions (consumer contract section 3, items 1-3)
    _need(_sha(raw["MANIFEST.json"]) == pin_manifest, "MANIFEST.json sha256 differs from the pin")
    m = json.loads(raw["MANIFEST.json"])
    for k in ("schema_version", "export_id", "consumer_contract_version"):
        _need(m.get(k) == pin[k], f"{k}: {m.get(k)!r} != pinned {pin[k]!r}")
    _need(m["contract"] == pin["contract"], f"contract block differs from the pin: {m['contract']}")
    _need(m["contract"]["adoption_binding"] is False and m["contract"]["status"] == "draft_not_frozen", "the producer contract must be a draft with binding false")
    # 4. every file
    for n in DATA_FILES:
        meta = m["files"][n]
        _need(_sha(raw[n]) == meta["sha256"] and len(raw[n]) == meta["bytes"] and raw[n].count(b"\n") == meta["lines"], f"{n}: sha256/bytes/lines differ from the manifest")
    for n in STATIC_FILES:
        _need(_sha(raw[n]) == m["static_files"][n]["sha256"] and len(raw[n]) == m["static_files"][n]["bytes"], f"{n}: differs from the manifest")
    # 5. universes
    _need(m["universes"]["ice"]["id"] == pin["ice_universe_id"], "Ice universe id differs from the pin")
    _need(m["sources"]["ice_package"]["sha256"] == pin["ice_package_sha256"], "Ice package sha256 differs from the pin")
    _need(m["universes"]["tdr"]["id"] == pin["tdr_universe_id"], "TDR universe id differs from the pin")
    # records
    subs_l, tdr_l = _read_lines(raw["ice_subjects.jsonl"], "ice_subjects"), _read_lines(raw["tdr_targets.jsonl"], "tdr_targets")
    ii_l, it_l = _read_lines(raw["pairs_ice_ice.jsonl"], "pairs_ice_ice"), _read_lines(raw["pairs_ice_tdr.jsonl"], "pairs_ice_tdr")
    _need(len(subs_l) == m["universes"]["ice"]["subjects"] == 1200 and len(tdr_l) == m["universes"]["tdr"]["targets"] == 323, "universe sizes differ")
    ids = [s["id"] for s in subs_l]
    _need(ids == sorted(ids) and len(set(ids)) == len(ids), "ice_subjects not sorted/unique by id")
    tids = [t["id"] for t in tdr_l]
    _need(tids == sorted(tids) and len(set(tids)) == len(tids), "tdr_targets not sorted/unique by id")
    subjects, tdr = {s["id"]: s for s in subs_l}, {t["id"]: t for t in tdr_l}
    allowed_status = set(m["policy_echo"]["candidates.target_statuses_in_pool"])
    # pairs: shape, keys, ordering, digest, counts (section 2 and 3 item 7)
    import collections
    for name, rows, pop in (("pairs_ice_ice", ii_l, "ice_ice"), ("pairs_ice_tdr", it_l, "ice_tdr")):
        keys = []
        for r in rows:
            _need(set(r) >= {"a", "b", "k", "r", "s", "ta", "tb", "n"} and r["r"] in RELATIONS, f"{name}: malformed record {r.get('k')!r}")
            _need(r["k"] == f"{r['a']}|{r['b']}", f"{name}: key does not equal a|b for {r['k']!r}")
            _need((r["s"] is None) == (r["r"] == "UNAVAILABLE"), f"{name}: score/UNAVAILABLE inconsistent for {r['k']!r}")
            keys.append(r["k"])
        order = [(r["a"], r["b"]) for r in rows]
        _need(order == sorted(order) and len(set(keys)) == len(keys), f"{name}: not sorted by (a, b) or keys not unique")
        _need(_sha("\n".join(keys).encode("utf-8")) == m["populations"][pop]["key_digest_sha256"], f"{name}: key digest differs")
        _need(len(rows) == m["populations"][pop]["pairs"] == m["populations"][pop]["expected_pairs"], f"{name}: pair count differs")
        counted = collections.Counter(r["r"] for r in rows)
        _need({k: counted.get(k, 0) for k in RELATIONS} == {k: m["populations"][pop]["relation_counts"].get(k, 0) for k in RELATIONS}, f"{name}: relation counts differ from the manifest")
    # Ice x Ice completeness: exactly the unordered same-brand-string pairs, smaller id first
    by_brand: dict[str, list[str]] = {}
    for s in subs_l:
        by_brand.setdefault(s["brand"], []).append(s["id"])
    _need(len(by_brand) == m["populations"]["ice_ice"]["brand_strings"], "brand string count differs")
    expected = sum(len(v) * (len(v) - 1) // 2 for v in by_brand.values())
    _need(expected == len(ii_l), "Ice x Ice population is not the full same-brand-string pair set")
    for r in ii_l:
        _need(r["a"] < r["b"] and r["a"] in subjects and r["b"] in subjects and subjects[r["a"]]["brand"] == subjects[r["b"]]["brand"], f"out-of-universe or cross-brand Ice x Ice pair {r['k']!r}")
    # Ice x TDR: rows == union of pools; pool membership rules; per-subject accounting
    rows_by = collections.defaultdict(list)
    for r in it_l:
        _need(r["a"] in subjects and r["b"] in tdr, f"out-of-universe Ice x TDR pair {r['k']!r}")
        _need(r.get("br") in BRAND_RELATIONS, f"Ice x TDR pair without an allowed brand relation {r['k']!r}")
        rows_by[r["a"]].append(r["b"])
    empty = 0
    for sid, s in subjects.items():
        pool = s["pool"]
        _need(pool == sorted(pool) and len(set(pool)) == len(pool), f"{sid!r}: pool not sorted/unique")
        _need(sorted(rows_by.get(sid, [])) == pool, f"{sid!r}: pool differs from its pair rows")
        _need(len(pool) + sum(s["pool_excluded"].values()) == len(tdr), f"{sid!r}: pool + excluded != TDR universe")
        for t in pool:
            _need(not tdr[t]["deleted"] and tdr[t]["status"] in allowed_status, f"{sid!r}: pool member {t!r} breaks the pool rule")
        empty += not pool
    _need(empty == m["populations"]["ice_tdr"]["subjects_with_empty_pool"], "empty-pool count differs")
    _need(max(len(s["pool"]) for s in subs_l) == m["populations"]["ice_tdr"]["max_pool_size"], "max pool size differs")
    return RelationExport(m, subjects, tdr, {r["k"]: r for r in ii_l}, {r["k"]: r for r in it_l})


def verify_universe(export: RelationExport, ice_rows: list[dict], tdr_identities: list[dict]) -> None:
    """The shadow's own input must be exactly the export's universes (consumer contract section 6 item 2): same Ice groups with the same name and brand, same TDR models."""
    got = {r["model_group_id"]: r for r in ice_rows}
    _need(set(got) == set(export.subjects), f"Ice universe differs: {len(set(got) ^ set(export.subjects))} ids")
    for gid, r in got.items():
        s = export.subjects[gid]
        _need(s["name"] == r["model_name"] and s["brand"] == r["brand"] and r["brand"] in s["brands_observed"], f"SUBJECT_DIFFERS: {gid!r}")
    mine = {i["canonical_id"]: i for i in tdr_identities}
    _need(set(mine) == set(export.tdr), f"TDR universe differs: {sorted(set(mine) ^ set(export.tdr))[:5]}")
    for cid, i in mine.items():
        _need(export.tdr[cid]["name"] == i["name_en"] and export.tdr[cid]["deleted"] == bool(i.get("deleted")), f"TDR target differs: {cid!r}")
