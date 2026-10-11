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
#: The producer's TDR snapshot inputs, vendored unchanged and bound by MANIFEST.sources.tdr_inputs: they carry what the routing actually reads (brand, status, deleted, aliases).
TDR_INPUT_FILES = ("tdr_models.json", "tdr_brands.json", "ice_brand_aliases.json")
BRAND_RELATIONS = ("EXACT", "ALIAS_SAME", "ALIAS_RELABEL", "ALIAS_RELATED")


class ExportError(RuntimeError):
    """The export is missing, altered, mismatched or out of universe. Callers must stop; nothing may be inferred."""


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise ExportError(msg)


class RelationExport:
    def __init__(self, manifest: dict, subjects: dict, tdr: dict, ice_ice: dict, ice_tdr: dict, tdr_models: dict | None = None, tdr_brands: dict | None = None, allowed_statuses: tuple = ()):
        self.manifest, self.subjects, self.tdr, self.ice_ice, self.ice_tdr = manifest, subjects, tdr, ice_ice, ice_tdr
        self.tdr_models = tdr_models or {}              # canonical_id -> the producer's TDR model record (brand_id, name_en, status, deleted, aliases), hash-bound
        self.tdr_brands = tdr_brands or {}              # brand canonical_id -> the producer's TDR brand record
        self.allowed_statuses = tuple(allowed_statuses)
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
        raw.update({f"tdr_inputs/{n}": (directory / "tdr_inputs" / n).read_bytes() for n in TDR_INPUT_FILES})
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
    # the producer's TDR snapshot: hash-bound, and it must be what the TDR universe id names (consumer contract section 3, item 5)
    for n in TDR_INPUT_FILES:
        _need(_sha(raw[f"tdr_inputs/{n}"]) == m["sources"]["tdr_inputs"][n], f"tdr_inputs/{n}: sha256 differs from MANIFEST.sources.tdr_inputs")
    _need(pin["tdr_universe_id"] == "tdr_vehicle_models:sha256-" + m["sources"]["tdr_inputs"]["tdr_models.json"][:16], "the TDR universe id does not name tdr_models.json")
    tdr_models_l, tdr_brands_l = json.loads(raw["tdr_inputs/tdr_models.json"]), json.loads(raw["tdr_inputs/tdr_brands.json"])
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
    models = {x["canonical_id"]: x for x in tdr_models_l}
    brands = {x["canonical_id"]: x for x in tdr_brands_l}
    _need(set(models) == set(tdr) and len(models) == len(tdr_models_l), "tdr_models.json and tdr_targets.jsonl are different universes")
    bname = {k: b["name_en"] for k, b in brands.items()}
    for cid, x in models.items():
        t = tdr[cid]
        _need(t["name"] == x["name_en"] and t["status"] == x["status"] and t["deleted"] == x["deleted"] and t["brand"] == bname.get(x["brand_id"]), f"tdr_targets.jsonl differs from the bound TDR snapshot for {cid!r}")
    return RelationExport(m, subjects, tdr, {r["k"]: r for r in ii_l}, {r["k"]: r for r in it_l}, models, brands, tuple(sorted(allowed_status)))


def _alias_multiset(aliases) -> list[str]:
    return sorted(a.strip() for a in aliases if a and a.strip())


def verify_universe(export: RelationExport, ice_rows: list[dict], catalog: dict) -> None:
    """The shadow's own input must be exactly the export's universes (consumer contract section 6 item 2), and every TDR field the routing or the brand resolution relies on
    (brand, name, status, deleted, aliases) must equal the producer's hash-bound snapshot. A changed alias or status therefore fails closed instead of silently changing
    OWNER_REVIEW routing. Brand `aliases` used for Ice-brand resolution are NOT in the producer snapshot; they are covered by the subject-level brand parity check instead."""
    got = {r["model_group_id"]: r for r in ice_rows}
    _need(set(got) == set(export.subjects), f"Ice universe differs: {len(set(got) ^ set(export.subjects))} ids")
    for gid, r in got.items():
        s = export.subjects[gid]
        _need(s["name"] == r["model_name"] and s["brand"] == r["brand"] and r["brand"] in s["brands_observed"], f"SUBJECT_DIFFERS: {gid!r}")
    mine = {i["canonical_id"]: i for i in catalog["identities"]}
    _need(set(mine) == set(export.tdr), f"TDR universe differs: {sorted(set(mine) ^ set(export.tdr))[:5]}")
    historical = set(catalog.get("historical", ()))
    for cid, i in mine.items():
        x = export.tdr_models[cid]
        _need(export.tdr[cid]["name"] == i["name_en"] and export.tdr[cid]["deleted"] == bool(i.get("deleted")), f"TDR target differs: {cid!r}")
        _need(i["brand_id"] == x["brand_id"], f"TDR_BRAND_DIFFERS: {cid!r}: {i['brand_id']!r} != {x['brand_id']!r}")
        _need(i["name_en"] == x["name_en"] and bool(i.get("deleted")) == x["deleted"], f"TDR_FIELD_DIFFERS: {cid!r}")
        _need((x["status"] == "HISTORICAL") == (cid in historical), f"TDR_STATUS_DIFFERS: {cid!r}: producer {x['status']!r}")
        _need(_alias_multiset(catalog["aliases"].get(cid, [])) == _alias_multiset(x.get("aliases", [])), f"TDR_ALIASES_DIFFER: {cid!r}: {catalog['aliases'].get(cid)!r} != {x.get('aliases')!r}")
    brands = catalog["brands"]
    _need(set(brands) == set(export.tdr_brands), f"TDR brand universe differs: {sorted(set(brands) ^ set(export.tdr_brands))[:5]}")
    for bid, b in brands.items():
        _need(b["name_en"] == export.tdr_brands[bid]["name_en"] and not export.tdr_brands[bid]["deleted"], f"TDR_BRAND_DIFFERS: {bid!r}")


def alias_binding_summary(export: RelationExport) -> dict:
    return {"models": len(export.tdr_models), "models_with_aliases": sum(1 for x in export.tdr_models.values() if _alias_multiset(x.get("aliases", []))),
            "alias_strings": sum(len(_alias_multiset(x.get("aliases", []))) for x in export.tdr_models.values()), "brands": len(export.tdr_brands),
            "tdr_inputs_sha256": {n: export.manifest["sources"]["tdr_inputs"][n] for n in TDR_INPUT_FILES}, "statuses": dict(collections_counter(x["status"] for x in export.tdr_models.values()))}


def collections_counter(it):
    import collections
    return collections.Counter(it)


def brand_pool_mismatches(brand: dict, pool: list[str], export: RelationExport, subject_id: str) -> list[str]:
    """Is the shadow's brand resolution consistent with the export's brand relations and pool semantics for THIS subject? Not just 'resolved?' / 'empty?':
    - brand unresolved but a pool exists, or resolved but the pool is empty;
    - a pool member of a brand the shadow neither resolved nor declared as family (wrong-but-non-null resolution);
    - a pool member's brand relation (`br`) that contradicts the shadow's relation for that brand (EXACT / ALIAS_SAME for the resolved brand, the declared relation for a family brand);
    - an allowed (non-deleted, in-pool status) model of the resolved or family brand that the export pool lacks."""
    bid = brand.get("brand_id")
    reasons: list[str] = []
    if not bid:
        if pool:
            reasons.append("BRAND_RESOLUTION_VS_POOL: the export has a pool but the shadow does not resolve the brand")
        return reasons
    if not pool:
        return ["BRAND_RESOLUTION_VS_POOL: the shadow resolves the brand to a TDR brand but the export pool is empty (brand relation not allowed)"]
    declared = {bid: brand.get("relation")} | {f["brand_id"]: f["relation"] for f in brand.get("family", ())}
    for tid in pool:
        c = export.tdr_models[tid]["brand_id"]
        br = export.ice_tdr[f"{subject_id}|{tid}"]["br"]
        if c not in declared:
            reasons.append(f"BRAND_RESOLUTION_VS_POOL: pool member {tid} is brand {c!r}, but the shadow resolved {bid!r} (family {sorted(declared)[1:] or 'none'})")
        elif br != declared[c]:
            reasons.append(f"BRAND_RESOLUTION_VS_POOL: pool member {tid} has export brand relation {br}, the shadow says {declared[c]} for brand {c!r}")
    in_pool = set(pool)
    for c in declared:
        missing = sorted(t for t, x in export.tdr_models.items() if x["brand_id"] == c and not x["deleted"] and x["status"] in export.allowed_statuses and t not in in_pool)
        if missing:
            reasons.append(f"BRAND_RESOLUTION_VS_POOL: the export pool lacks allowed model(s) of resolved brand {c!r}: {missing[:3]}")
    return reasons
