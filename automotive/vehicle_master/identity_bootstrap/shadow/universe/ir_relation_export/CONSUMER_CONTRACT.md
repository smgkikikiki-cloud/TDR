# Consumer contract — Identity Resolution relation export

**Contract version:** `ir-relation-export-consumer/1` · **Schema:** `ir-relation-export/1` · **Export id:** `ir-rev4-m7.0-relations/1`
**Producer:** PR #200 (Identity Resolution Contract v1 rev 4 — a **draft, NOT frozen**, `adoption.binding: false`).
**First consumer:** PR #201 (Identity Bootstrap shadow). This document answers `IR_FULL_PARITY_INTERFACE_REQUEST.md` (PR #201 at `b132a86c0bf2f17f53d80b70b4c158efe4b9e69d`).

**What this is.** For the pinned M7.0 snapshot, every name relation the reference evaluator computes — **all nine kinds, for every evaluated pair of both populations** — with the
tokens each side was compared on, each subject's candidate pool, and the evaluator's dry-run outcome. Every relation was produced by `calibration/ref_eval_core.name_relation` (and,
for Ice × TDR, by the candidate pools `calibration/ref_eval_resolve.resolve` itself builds). **There is no second matcher in this export.** It decides nothing, changes no rule,
creates nothing, and its `outcome` fields are a dry run (invariant I16): they are not approvals and not a CREATE authorisation.

**What is not here.** Registration data, activity, volume, series, owner labels, and any relation for a pair the evaluator did not evaluate (see "Candidate pool").

## 1. Paths and schemas

All under `automotive/vehicle_master/identity_resolution/calibration/relation_export/`.

| File | Records | Content |
|---|---:|---|
| `MANIFEST.json` | 1 | versions, source-blob hashes, universe ids, policy echo, file inventory (sha256 / bytes / lines), relation counts, coverage, ordering |
| `relation_export.schema.json` | – | record schemas (`ir-relation-export/1`), in the subset `contract/schema_subset.py` validates |
| `ice_subjects.jsonl` | 1,200 | the Ice universe (one per model group): normalized tokens, **candidate pool**, best / related relations, reference-evaluator outcome |
| `tdr_targets.jsonl` | 323 | the TDR universe (one per vehicle model): id, brand, name, status, deleted |
| `pairs_ice_ice.jsonl` | 26,505 | every evaluated Ice × Ice pair |
| `pairs_ice_tdr.jsonl` | 12,412 | every evaluated Ice × TDR pair (= the union of the subjects' pools) |

Pair record (`pairs_*.jsonl`), keys sorted, compact JSON, one per line:

| Field | Meaning |
|---|---|
| `k` | the pair key `"<a>\|<b>"` |
| `a`, `b` | the two ids. Ice × Ice: `a < b` (smaller `model_group_id` first). Ice × TDR: `a` = Ice `model_group_id`, `b` = TDR `canonical_id` |
| `r` | the relation: `EQUAL`, `EQUAL_VIA_MODEL_ALIAS`, `EQUAL_VIA_TOKEN_EQUIV`, `FUZZY`, `SUBJECT_COARSER`, `SUBJECT_FINER`, `SIBLING`, `CONTRADICTION`, `UNAVAILABLE` |
| `s` | Dice score, 6 places (`null` only when `r` is `UNAVAILABLE`); informational — **the relation drives decisions** (SPEC §5.3) |
| `ta`, `tb` | the normalized tokens of `a` and of `b` **as used in this comparison** (brand prefix already stripped, generic tokens dropped) |
| `n` | `[a's brand prefix stripped, b's brand prefix stripped, a's name unavailable, b's name unavailable]`, 0/1 |
| `br` | Ice × TDR only: the brand relation that admitted the target to the pool (`EXACT`, `ALIAS_SAME`, `ALIAS_RELABEL`, `ALIAS_RELATED`) |

`SUBJECT_COARSER` means the tokens of `a` are a proper subset of `b`'s (`a` is the broader nameplate); `SUBJECT_FINER` the reverse.

## 2. Pair keys and ordering

* **Key** = `a + "|" + b`, exactly as in `lexical_pass/after_rev4.json` (`ice_ice_relation_pairs`, `ice_tdr_relation_pairs`), so a key valid there is valid here. For the three kinds that file lists (`FUZZY`, `SIBLING`, `EQUAL_VIA_MODEL_ALIAS`) the relations are identical (a test pins it).
* **Never split a key.** 591 of the 1,200 Ice ids contain a `|` (`KIA|CANIVAL`, unmapped-name groups), so an Ice × Ice key can contain two or three. Look a pair up by the whole string, or by the `(a, b)` fields. (An Ice × TDR key can be split on its **last** `|`: no TDR canonical id contains one.)
* **Ordering.** Records are sorted by `(a, b)` in Unicode code-point order (= UTF-8 byte order); `ice_subjects.jsonl` and `tdr_targets.jsonl` by `id`. Keys are unique. `MANIFEST.populations.*.key_digest_sha256` is the sha256 of the keys joined with `\n` in file order.
* **Orientation.** One row per unordered Ice × Ice pair, in the orientation above. For the reverse orientation `(b, a)` read the same row and swap `SUBJECT_COARSER` ↔ `SUBJECT_FINER`; every other kind is symmetric. This was verified for all 26,505 pairs by re-running the evaluator with the arguments swapped (a test pins it).
* **Bytes.** Sorted keys, `separators=(",", ":")`, UTF-8 (`ensure_ascii=false`), `\n` line ends, no timestamps. Regenerating from the same inputs gives the same bytes.

## 3. Hash and version pinning

Pin **all** of the following; fail closed if any differs.

1. The producer commit you vendored from, and `sha256(MANIFEST.json)`.
2. `schema_version == "ir-relation-export/1"`, `export_id == "ir-rev4-m7.0-relations/1"`, `consumer_contract_version == "ir-relation-export-consumer/1"`.
3. `contract.adoption_binding == false`, `contract.status == "draft_not_frozen"`, `contract.revision == 4`, `contract.policy_version`.
4. Each file's `sha256`, `bytes` and `lines` from `MANIFEST.files`, recomputed from the bytes you hold — and the schema and this document through `MANIFEST.static_files`.
5. The universes: `universes.ice.id == "ice:2569-09:v3:M7.0"` (the M7.0 package, `sources.ice_package.sha256 == c558d2d4…677d`, plus the hashes of its `dims/model_group.csv` and `data/reg_trend.csv`), `universes.tdr.id` (`tdr_vehicle_models:sha256-<first 16 of the tdr_models.json sha256>`) and `sources.tdr_inputs`. A shadow run on another package or another TDR extract is a **different universe**: it must not read this export.
6. `sources.evaluator_and_contract`: the sha256 of the evaluator, population definition, policy and capability files the relations came from. They let you tell that the producer's rules moved since this export (the producer's own test fails on any drift).
7. Counts: `populations.ice_ice.pairs == 26505`, `populations.ice_tdr.pairs == 12412` and the nine `relation_counts` of each (they must equal what you count from the rows).

A new rule, evaluator, policy, package or TDR extract on the producer side means a **new `export_id`** (or `schema_version` if the record shape changed). Never read a mixture of two exports.

## 4. Candidate-pool interpretation

* **Ice × Ice population** = every pair of Ice groups with the **same Ice brand string** (`brand`). Pairs across different brand strings were **not evaluated**; the absence of a row is not a `CONTRADICTION`. Expected pairs per brand string are `n(n−1)/2` (`MANIFEST.populations.ice_ice.expected_pairs`).
* **Ice × TDR population** = for each subject, its **pool**: the TDR models the evaluator compared. A TDR model is in the pool iff its brand relation to the subject is in `policy.candidates.brand_relations_allowed` (`EXACT`, `ALIAS_SAME`, `ALIAS_RELABEL`, `ALIAS_RELATED`), it is not deleted (`exclude_deleted_targets`) and its status is in `target_statuses_in_pool` (`MANIFEST.policy_echo`). `ice_subjects[].pool` lists the pool; it equals the `b` of the subject's rows in `pairs_ice_tdr.jsonl`. `pool_excluded` counts, per reason, the TDR models left out; `len(pool) + sum(pool_excluded) == universes.tdr.targets` for every subject.
* **A TDR model outside the pool was not compared.** It has no relation — not `CONTRADICTION`, not `UNAVAILABLE`. A subject whose pool is empty (226 in this snapshot: its brand does not exist in TDR) has **no Ice × TDR relation at all**; it is the reference evaluator's `BRND_NOT_IN_TDR`, not a lexical verdict.
* A pool member always has a row, whatever its relation: the 11,783 `CONTRADICTION` and 238 `UNAVAILABLE` pairs are in the file. `ALIAS_RELATED` brand pairs are in the pool but the evaluator caps them at PROPOSE (`br` tells you).
* `best_relation` / `best_targets` / `related` are a convenience summary of the subject's own rows in SPEC §5.3 ladder order (`MANIFEST.relation_order`, best first); `related` omits `CONTRADICTION` and `UNAVAILABLE`. They are derived from the rows, not a second opinion; read the rows when you need a specific pair.
* `outcome` (`outcome`, `primary_code`, `target_ids`, `link_type`, `codes`) is the reference evaluator's **dry-run** decision on the series-carrying snapshot, equal to `lexical_pass/after_rev4.json` `decisions`. It is context for comparison, not an instruction.

## 5. Replacing `ir_rev4.adjudicate` with direct lookups

`adjudicate(base, pair_relation)` takes a stand-in relation `base` and lets the rev 4 pair maps override it. With this export **there is no `base`**:

```python
# index once, after verifying section 3
ice_ice = {r["k"]: r for r in read_jsonl("pairs_ice_ice.jsonl")}
ice_tdr = {r["k"]: r for r in read_jsonl("pairs_ice_tdr.jsonl")}
subjects = {s["id"]: s for s in read_jsonl("ice_subjects.jsonl")}

def relation_ice_tdr(subject_id, canonical_id):
    return ice_tdr[f"{subject_id}|{canonical_id}"]["r"]        # KeyError  ->  not evaluated  ->  IR_PARITY_UNRESOLVED, never CONTRADICTION

def relation_ice_ice(first_id, second_id):                    # first_id < second_id in code-point order, else swap and flip COARSER/FINER
    return ice_ice[f"{first_id}|{second_id}"]["r"]
```

* Delete the stand-in's generation of `EQUAL`, `EQUAL_VIA_TOKEN_EQUIV`, `SUBJECT_COARSER`, `SUBJECT_FINER`, `FUZZY`, `SIBLING`, `EQUAL_VIA_MODEL_ALIAS` **and** its "a pair PR #200 does not list is a CONTRADICTION" rule. A pair is `CONTRADICTION` only when its row says so.
* Enumerate the pairs your verdict needs from the **export**, not from the stand-in: a subject's Ice × TDR candidates are `subjects[id]["pool"]`; its Ice × Ice peers are the other subjects with the same `brand`.
* If the stand-in considered a pair (or a candidate) that is not in the export, that is a **population difference to report**, not a relation to fill in: record it (`POOL_MISMATCH` / `PAIR_NOT_EVALUATED`) and leave the subject unresolved.
* The old stand-in numbers (Ice × TDR `EQUAL` 299 vs 239, `SUBJECT_COARSER` 46 vs 58, `SUBJECT_FINER` 45 vs 35, Ice × Ice `EQUAL_VIA_TOKEN_EQUIV` 0 vs 1) must disappear as a by-product: after the swap your counts equal `MANIFEST.populations.*.relation_counts` for **all nine kinds**, or something is still reading a non-export relation.

| Population | EQUAL | …ALIAS | …TOKEN_EQUIV | FUZZY | COARSER | FINER | SIBLING | CONTRADICTION | UNAVAILABLE | total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Ice × Ice | 4 | 2 | 1 | 7 | 78 | 40 | 307 | 25,339 | 727 | 26,505 |
| Ice × TDR | 239 | 1 | 1 | 2 | 58 | 35 | 55 | 11,783 | 238 | 12,412 |

## 6. When a subject may clear `IR_PARITY_UNRESOLVED`

A subject may clear **only when all** of these hold; otherwise it keeps `IR_PARITY_UNRESOLVED` with the named reason.

1. **Export verified** (section 3: hashes, versions, universe ids, `adoption_binding == false`). If not: every subject stays unresolved (`EXPORT_NOT_VERIFIED`).
2. **Same subject.** `subjects[id]` exists and its `name`, `brand` and `brands_observed` equal the shadow's input for that group (`SUBJECT_NOT_IN_EXPORT` / `SUBJECT_DIFFERS`).
3. **Every Ice × TDR relation the verdict uses was read from `pairs_ice_tdr.jsonl`** by key, and every TDR id the shadow treats as a candidate is in `subjects[id]["pool"]` (`POOL_MISMATCH`). An empty pool clears the lexical part only as "no TDR relation exists".
4. **Every Ice × Ice relation the verdict uses was read from `pairs_ice_ice.jsonl`** by key, and the number of rows involving the subject equals `(size of its brand string) − 1` (`PAIR_NOT_EVALUATED`).
5. **No relation of any of the nine kinds was generated, approximated or defaulted by the consumer** for this subject.
6. The subject's verdict does not depend on a relation the export does not carry (`UNAVAILABLE` names are exported as `UNAVAILABLE`; unavailable is a relation, not a gap).

Clearing `IR_PARITY_UNRESOLVED` removes **only** the lexical-parity uncertainty. It does not approve a CREATE, does not make the dry-run `outcome` binding, and says nothing about registration data, activity, volume or owner labels. Automatic CREATE stays out of scope.

## 7. Known uncertainties

* The export is the reference evaluator's reading (a transcription of SPEC §5; same author as the SPEC), not a ground truth about the vehicles.
* The descriptor vocabulary, length floor and patterns behind `SIBLING` are the producer's proposals (`pending` in `adoption.yaml`); changing them is a new export.
* Containment (`SUBJECT_COARSER`/`SUBJECT_FINER`) resting on descriptor tokens is unchanged by rev 4 (15 + 16 Ice × Ice, 7 + 19 Ice × TDR) and is exported as the evaluator says it.
* The TDR universe is the 2026-10-11 read-only extract committed under `calibration/inputs/`; a later TDR catalog is a different universe.

## 8. Producer-side checks (for the record)

`tests/identity_resolution/test_ir_relation_export.py` runs without the private M7.0 package: it recomputes both populations from the committed subject list and TDR inputs and compares them pair-for-pair with the evaluator, checks the nine counts against `after_rev4.json`, the byte-stable canonical form, the manifest hashes and the pinned source hashes. Regenerate with `python -m identity_resolution.calibration.relation_export build` (needs the package); check with `… verify`.
