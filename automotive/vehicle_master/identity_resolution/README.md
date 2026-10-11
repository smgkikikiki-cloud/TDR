# TDR Identity Resolution

A permanent, provider-agnostic subsystem that decides how an **external vehicle identity** (provider #1: an Ice `model_group`) relates to a
**TDR canonical entity** (`vehicle_models`), with evidence a human can audit and a machine can replay.

> **Status: Contract v1 is a DRAFT, revision 3 — NOT FROZEN.** The owner accepted the architecture in principle and asked for three contract-level
> fixes (below) before adoption; they are made here, the contract is **not** frozen, and the uncalibrated `proposal` thresholds are **not adopted**
> (`contract/v1/adoption.yaml`, `binding: false`). This directory holds the contract, the golden corpus, the architecture and the contract-level tooling.
> There is **no resolver**, nothing reads this in production, no database state was touched, R6 was not re-run and R7 was not started.
> `vehreg/ice_crosswalk.py` and `tools/ice_crosswalk_match.py` are unchanged and remain the live matcher. (A test fails if any production module imports this package.)

## What revision 3 adds (owner decisions of 2026-10-11)

The owner answered the open points. They are recorded as `owner_decisions` in [`adoption.yaml`](contract/v1/adoption.yaml) (and listed in SPEC Appendix E); the contract is **still not frozen**.

| Decision | Status | Effect |
|---|---|---|
| Accept the three link types `EQUIVALENT`, `PART_OF`, `COMPOSED_OF` | accepted | SPEC §7.0 is part of the draft contract, no longer a proposal |
| Accept the two cardinality rules as v1 (C1 one active claim per subject; C2 a target claimed whole is claimed once, parts may share) | accepted | pinned by `claim_conflict.*` and a brute-force grid test |
| Keep bundles as real atomic link sets, not review-only | accepted | `candidates.bundle.enabled` is `owner_accepted`; the review-only branch is closed |
| Extend persistence identity with `link_type`; legacy overlapping claims are **reported, never auto-repaired** | accepted (logical contract only — no DDL, migration or write path) | new invariant **I18**; step 0 of the decision procedure now also reports a stored overlap **between two subjects** (e.g. a stored AUTO row overlapping a protected claim is no longer demoted by the write matrix); `resolve.stored-overlap-*` |
| Ice absent-row semantics stay `UNKNOWN` until Ice explicitly confirms | standing | tripwire test; `Q-ICE-ABSENT-ROW` remains the only open provider question |
| TDR registrations: do not assume — **trace the source pipeline**; declare absent = zero only if complete month × dimension coverage is contractually guaranteed | standing; **result: stays `UNKNOWN`** | `provider_capabilities.yaml` → `trace` (five stages, none guarantees coverage) and `upgrade_requires`; a confirmed `ABSENT_IS_ZERO` must now name its `coverage_guarantee` |
| `binding` stays `false`; every provisional threshold is non-authoritative until calibrated against the real R6 review data | standing | `provisional_keys` now lists only still-`pending` entries |
| Do not freeze; wait for CI; then stop for threshold and data-semantics calibration | standing | this revision stops there |

### The TDR registrations trace (why it stays UNKNOWN)

Repository read only — no database was queried, so production table contents are not evidenced. Stage by stage, with references in `provider_capabilities.yaml`:

1. **Source.** DLT's CKAN dataset publishes one resource per month with rows `(class, brand, model label, count)`. Only classes RY1/RY2/RY3 are kept (2026-01: 609 of 1,421 rows). DLT never publishes a zero row (0 of 25,379 rows across the 48 committed monthly exports) and 1,307 of 1,639 labels seen in two or more months have interior months with no row. DLT states no completeness promise, and the repo holds two defects: the 2023-12 resource returned December 2022's payload and the 2026-02 resource was part-published (6 rows).
2. **Month coverage.** The source differs by month — API export, long-form workbook snapshots, a classless pivot for 2026-08 that cannot split class-dependent nameplates. TDR's own market contract treats a missing calendar month as missing (rejected, never zero); there is no model × month grid anywhere.
3. **Loader.** `ingest_registration_snapshot` validates format, period and a non-negative count and replaces the period atomically; it checks nothing against an expected grid.
4. **Attribution.** A canonical model is attributed only through reviewed aliases; ambiguous or unknown labels stay `NULL` and are never redistributed (98–99 % of units mapped in 2026-01..07, lower for the pivot month; v2 is "intentionally more conservative" than v1). A model-month can be absent because its units sit at brand grain or unresolved.
5. **Series and serving.** The matcher sums attributed rows by (model, period); serving can come from the legacy table or the v2 projection, and holds less history than the warehouse.

A statement that DLT omits unregistered combinations would make *label-level* absence meaningful; it would not make *canonical-model-month* absence meaningful, because attribution is open. `trace.upgrade_requires` lists the four things that would have to become contractual (a DLT/TDR completeness guarantee, a per-month load manifest, attribution closure, a single serving source). The test `test_the_trace_evidence_in_the_committed_dlt_snapshots_still_holds` fails if the committed snapshots ever contradict the evidence (e.g. an explicit zero row).

**Practical consequence, unchanged:** until Ice and TDR meet a guarantee like that, a pair with an in-coverage hole in the last 24 months can be PROPOSED but never AUTO (`series.absent_row.auto_max_unconfirmed_gap_months = 0`, itself still provisional).

## What revision 2 changed (owner review)

| Owner point | Before (rev 1) | Now (rev 2) | Where |
|---|---|---|---|
| **1. Missing-row semantics must be capability data** | The Ice adapter was specified to read an absent `reg_trend` row inside `reg_range` as **0**, "to be confirmed" | What an absent row means is **declared data** per source (`provider_capabilities.yaml`): Ice **UNKNOWN / unconfirmed** (hypothesis `ABSENT_IS_ZERO`, open question `Q-ICE-ABSENT-ROW`), TDR registrations **UNKNOWN / unconfirmed**. A zero may be written only for `ABSENT_IS_ZERO` + `confirmed`. Unconfirmed gaps are `null`, left out, counted (`semantics_gap_months`), reported and cap AUTO; a snapshot that claims more than the file grants, or zero-fills a gap, is refused | SPEC I4a, §3.2, §6.2a; `provider_capabilities.yaml`; `densify.*`, `window.absent-row-*`, `resolve.absent-row-*` |
| **2. Identity vs aggregation/granularity** | One rule ("a target has at most one active subject") — a provider-finer subject could only become a `STRUCTURAL_REVIEW` asking TDR to split | Three **link types**: `EQUIVALENT` (1:1), `COMPOSED_OF` (one subject = a set of targets), `PART_OF` (many subjects may share one target). Two active claims conflict only under C1 (one claim per subject) and C2 (a target claimed whole is claimed once; parts may share). `honda-city` + `honda-city-hatchback` → both `PROPOSE` `PART_OF` `honda_city`; no TDR split forced | SPEC §7.0, §7.3–7.5, §8.6; `claim_conflict.*`, `resolve.parts-*` |
| **3. Bundle persistence** | A bundle was N independent `PROPOSED` rows | A bundle is a **link set**: one decision, one deterministic `set_id`, one write action applied to every row, atomic storage, human action on the set, a broken stored set is `STRUCTURAL_REVIEW` (never repaired). The **review-only** alternative is documented as a fallback, not built (decision 8 below) | SPEC §7.3, §10.5, §10.6, I17; `resolve.link-set-*`, `fingerprint.link-set-*` |
| Wording | the taxonomy was described as listing *all* edge cases | "complete for the known taxonomy classes and corpus-extensible" — it does not claim no other situation exists | SPEC §13, `taxonomy.yaml` |
| **Do not adopt uncalibrated thresholds** | Proposal values read as the policy | `adoption.yaml`: every `proposal`/`assumption` value is in exactly one entry (calibration / representation / design choice), `binding: false`; a non-binding run is a **dry run** (I16); cases that depend on a provisional value carry `provisional_keys` | SPEC §14.6, App. E |

`contract/v1/CHANGELOG.md` has the full list of added, renamed and removed codes and files.

## Reading order

1. This file — architecture, evidence base, decisions for the owner.
2. [`contract/v1/SPEC.md`](contract/v1/SPEC.md) — the normative contract (sections 0–17 + generated appendices).
3. [`contract/v1/policy.yaml`](contract/v1/policy.yaml) — every tunable, with provenance (inherited / observed / proposal / assumption); [`adoption.yaml`](contract/v1/adoption.yaml) — the gate that says which of them are **not** adopted yet.
4. [`contract/v1/provider_capabilities.yaml`](contract/v1/provider_capabilities.yaml) — what each source's data means (today: nothing about missing rows is confirmed).
5. [`contract/v1/taxonomy.yaml`](contract/v1/taxonomy.yaml) and [`reason_codes.yaml`](contract/v1/reason_codes.yaml) — the edge cases and the code registry.
6. [`contract/v1/cases.jsonl`](contract/v1/cases.jsonl) — the golden corpus (the engine's executable specification).
7. [`contract/v1/decision.schema.json`](contract/v1/decision.schema.json), [`record.schema.json`](contract/v1/record.schema.json), [`case.schema.json`](contract/v1/case.schema.json), [`capabilities.schema.json`](contract/v1/capabilities.schema.json); [`CHANGELOG.md`](contract/v1/CHANGELOG.md).

## 1. Architecture

```
                         ┌───────────────────────────── contract/v1 (versioned, immutable once adopted) ─────────────────────────────┐
                         │ SPEC.md  policy.yaml  adoption.yaml  provider_capabilities.yaml  reason_codes  taxonomy  *.schema.json  cases │
                         └───────────────▲───────────────────────────────▲───────────────────────────────────────────▲───────────────┘
                                         │ reads (no numbers in code)    │ validates                                  │ regression suite
   provider package                      │                               │                                            │
   (Ice TDR_FULL zip) ──► providers/ice.py ──► SNAPSHOT ──► engine/ ───────┴──► DECISION / STRUCTURAL_OPERATION / REFUSAL ───┘
                         adapter: all provider      (generic input:      normalize → lineage → candidates → evidence →     (generic output: reason codes,
                         meaning is converted       subjects, targets,   decision → arbitration → write planning            evidence tuple, comparison periods,
                         here, nothing else         series, lineage)     (pure, deterministic, no I/O, no clock)           policy+source version, fingerprints)
                                                                                                    │
                                                                                                    ▼  a WRITE PLAN, never a write
                                                                       writer (separate, later) ──► candidate store / mapping store
                                                                       the DB RPC stays the last line of defence for APPROVED/LOCKED
```

| Layer | Responsibility | Knows about Ice? | Status |
|---|---|---|---|
| `contract/v1/` | Policy, registries, schemas, corpus. The only place a number, alias or threshold may live. | No (Ice appears only as data) | **this deliverable** |
| `contract/loader.py`, `schema_subset.py`, `render.py` | Strict loading (duplicate keys are errors), a stdlib validator for the schema subset the contract uses, SPEC appendix generation | No | **this deliverable** |
| `providers/base.py` | The generic adapter interface: `SubjectSource` (provider side) and `TargetSource` (TDR side) protocols, and `assemble_snapshot`, which validates the result against `record.schema.json` **and against `provider_capabilities.yaml`** (no claimed semantics the contract does not grant, no zero-filled unconfirmed gap) at the boundary | No | **this deliverable** (interface + boundary checks only) |
| `providers/ice.py` | Ice package → snapshot (Buddhist→Gregorian, sparse→dense **under the declared capability: a missing row is `null` unless the capability is confirmed `ABSENT_IS_ZERO` — today it is not**, `__provisional`/`BRAND\|MODEL` → `identity_status`, `id_changes.csv` → lineage events) | **Yes — the only place** | planned |
| `engine/normalize.py` | brand keys, name tokens, relations (SPEC §5) | No | planned |
| `engine/candidates.py` | pool, bundles (`COMPOSED_OF` link sets), parts (`PART_OF`), link types and the C1/C2 cardinality rules (SPEC §7) | No | planned |
| `engine/evidence.py` | common window, statistics, attributes (SPEC §6) | No | planned |
| `engine/decision.py` | flags, outcome, ranking, margin, review routing (SPEC §8) | No | planned |
| `engine/resolver.py` | lineage → per-subject → arbitration → write plan → fingerprints | No | planned |
| `cli.py` | `resolve --snapshot … --policy …`, `check-corpus` | No | planned |
| writer / persistence | applies a write plan to the stores | No | out of scope; needs its own gate |

The two providers of a comparison are symmetric in shape: the **subject** side (Ice) and the **counterpart** side (TDR's own registrations and catalog) both arrive as series with declared coverage; the engine treats neither as special.

**Separation, concretely.** The engine takes `(snapshot, policy)` and returns records. It has no Supabase client, no file I/O, no clock, no Ice column names. Everything that changes a decision is a key in `policy.yaml`; a test sweep (§4) shows that flipping any single behaviour-bearing key fails at least one golden case, so "a number hiding in Python" cannot go unnoticed.

**Candidate rows change; mappings do not.** The write matrix (SPEC §10.2) is data: an existing AUTO row may be refreshed, demoted or promoted; a PROPOSED row may go stale; an APPROVED or LOCKED row is only ever `BLOCK_REPORT`ed. `AUTO` is a revocable machine link and is never `APPROVED`.

## 2. How the first-run R6 flaws map to the contract

| Defect (owner report) | Mechanism (verified against the repo) | Where it is handled | Corpus |
|---|---|---|---|
| Time-window bias | `tools/ice_crosswalk_match._recent_periods` takes the newest 24 *Ice* months, and `build_paired_series` turns any month the TDR side lacks into 0 | SPEC §6.2: newest 24 months of the **common** window; null ≠ 0; trim inactive edges; minimums | `SER-01..06`, `window.*`, `resolve.window-*` |
| Granularity mismatch | candidates are scored one TDR model at a time (`match_one_group`), so `cab + double_cab → travo` is undiscoverable; one TDR model ↔ two Ice groups (`City` / `City Hatchback`) is silently resolved to one | SPEC §7.3 bundles = `COMPOSED_OF` link sets; §7.4 provider-finer = `PART_OF` claims that may share a target (no forced TDR split) | `SER-17`, `GRAN-01/06`, `CARD-10`, `resolve.hilux-travo-*`, `resolve.parts-*` |
| Ice absent row read as zero | `build_paired_series` zero-fills a month the TDR side lacks, and the rev-1 Ice adapter text assumed `absent = 0` | SPEC I4a, §3.2, §6.2a: capability data; unconfirmed gaps are `null`, counted, reported and cap AUTO | `SER-19/20/21`, `INPUT-06/07`, `window.absent-row-*`, `densify.*` |
| Weak brand normalization | `normalize_model_name` strips the brand by `startswith` on the exact brand string: `MG4 EV` → `4 ev`; `Mercedes GLC` is not stripped under `MERCEDES BENZ` | SPEC §5.1–5.2: compact keys, alias classes, whole-token prefix removal | `BRND-01..07`, `brand_relation.*`, `name_tokens.*` |
| `D-Max → MU-X` | reproduced offline: `'d max'` vs `'mu x'` scores **0.44** with `SequenceMatcher`, above `NAME_CANDIDATE_FLOOR = 0.35`, so a NAME-only PROPOSED row is written | SPEC §5.3: `CONTRADICTION` is a veto; a strong series cannot rescue it (`series_only.allow_with_name_veto = false`) | `NAME-02`, `name_relation.dmax-vs-mux`, `resolve.dmax-not-mux` |
| `Hilux Revo ≈ Hilux Travo` | legacy score **0.86** ≥ the 0.8 AUTO threshold | `SIBLING` veto | `NAME-04` |
| Conflicting candidates | the best candidate is kept and the rest dropped without a trace | SPEC §8.3: tie inside the margin → `AMBIGUOUS`, all listed | `CARD-01`, `classify.ambiguous-*` |
| Retired split parents have no redirect | `ice_model_group_redirects.change_type` admits only RENAME/MERGE; M7.0 has 3 such ids (15 rows) | SPEC §9.2: redirect to the largest-share successor (Ice's published rule) | `LIN-04`, `lineage.split-retired-*` |
| Split "STRUCTURE proposals" copy the parent's target onto the child | `ice_crosswalk_apply_id_change` inserts `(new_id, same canonical)` as `PROPOSED/ADMIN` | SPEC §9.5: a review question (STRUCTURE card), not a mapping row | `LIN-03`, `lineage.split-live-parent-corolla` |
| A REJECTED row is re-proposed every package | `decision_fingerprint` includes `master_version` | SPEC §11.2: a banded evidence fingerprint with no window and no source version | `FP-02`, `STATE-05/06` |

## 3. Evidence base (all verified from the repository's own copy of the R5-imported package)

`data/packages/2569-09/v3_M7.0/TDR_FULL_2569-09_v3_M7.0.zip` (sha256 `c558d2d4…94677d`, the package live since R5). Read-only; nothing was imported or written.

- **1,200** `model_group`s: **495** normal ids, **114** `__provisional`, **591** `BRAND|MODEL`. `model_name` is not a key (38 groups are named `ไม่ระบุ`).
- Data sufficiency: **735** groups have rows in fewer than 6 months (87 in 6–11, 98 in 12–23, 280 in ≥ 24); **912** groups hold < 120 lifetime units yet only **0.21 %** of all 4,141,987 units; **239** groups first appear in the last 24 months; **518** have months with no row between their first and last month; **0 of 262,985** `reg_trend` rows have a count ≤ 0 (Ice ships no zero rows). That is consistent with "absent = zero" **and** with "absent = not reported"; none of the package documents inspected says which, so it is recorded as an **unconfirmed capability** (`Q-ICE-ABSENT-ROW`), not as a fact. TDR's own `docs/REGISTRATION_MARKET_CONTRACT.md` rejects a window with a missing calendar month rather than reading it as zero (`Q-TDR-ABSENT-ROW`).
- `id_changes.csv`: **81** rows (31 รวม, 31 แยก, 19 เปลี่ยนรหัส), **63** distinct old ids — **53 retired, 10 still live**; **15** SPLIT rows come from **3 retired** ids (`…-amg-g` ×6, `…-amg-cls` ×6, `toyota-toyota-gr` ×3); **3** ids are both old and new in the file (`mini-mini-cooper-ev`, `-jcw-rhd`, `-jcw-convertible`), and `mini-mini-cooper-ev` ↔ `mini-mini-jcw-convertible` split into each other.
- Brands: `MERCEDES BENZ` / `MERCEDES` / `BENZ` / `MERCEDES AMG` / `MERCEDESBENZ MAYBACH`; `ZXAUTO` / `ZX AUTO`; `DFSK` / `DSFK` (typo); Deepal models are filed under `CHANGAN`; Maxus vans are registered under **MG** (`maxus-mifa-7`: 934 units, all MG; `maxus-mifa-9`: 1,961 MG + 2 MAXUS; `maxus-maxus-v80`: 119 MG + 16 MAXUS).
- Body: 649 of 1,200 groups have a blank `body`.
- Ice's own guidance (`สำหรับ_AI/tdr-package-import/SKILL.md` §3) covers only Ice-internal id continuity; it states the DLT raw-name table is *not* in the package.

To re-check these yourself (extract to a fresh directory; the interpreter runs isolated):

```bash
D=$(mktemp -d) && python3 -I -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" \
  data/packages/2569-09/v3_M7.0/TDR_FULL_2569-09_v3_M7.0.zip "$D" && ls "$D"        # id_changes.csv, panels/, …
```

**State discrepancy, not resolved here.** `docs/WORK_STATE.md` and `docs/market-track/ROADMAP.md` still say *R6 has not been started*. The owner reports that R6 ran once and produced candidate rows. The review rows are not in the repository, so the `owner_report_r6` corpus cases are **reproduced from the stated mechanism and the repo code**, not from row data; replace them with real rows when the review sheet is available. This task did not edit R6/R7 gate state.

## 4. Verification performed — and what it does not prove

Committed (`tests/identity_resolution/`, run by the existing `vehicle-master-engine` CI job: PyYAML + pytest only):

- schemas use only keywords the stdlib validator implements, every `$ref` resolves, and (when `jsonschema` is installed) the real validator agrees on all cases;
- policy, registry and taxonomy are internally consistent (provenance on every key, complete write matrix, protected rows are `BLOCK_REPORT`, every reason code belongs to a taxonomy entry, …);
- **capability data and the adoption gate** (rev 2): `provider_capabilities.yaml` validates against its schema and a test is the tripwire that fails if any source is marked as having confirmed "absent row = zero"; every `proposal`/`assumption` value belongs to exactly one `adoption.yaml` entry; `binding: true` is impossible while an entry is `pending`; the adapter boundary (`providers/base.py`) refuses a series that claims unconfirmed semantics or zero-fills an unconfirmed gap;
- the corpus (**508 cases**, 15 kinds, including `densify` for adapter obligation A2 and `claim_conflict` for the C1/C2 cardinality rules) validates, covers **every taxonomy id** (112) and asserts **every reason code** (104), names every defect class the task listed with an end-to-end case, and its arithmetic expectations (windows incl. the semantics gap, gates, bands, lifecycle, body, write matrix, fingerprints and link-set ids, densification, claim conflicts — a brute-force check of the C1/C2 grid) are **recomputed by an independent reference** (`ir_reference.py`);
- SPEC.md cannot drift: its appendices are generated from the YAML and compared, and prose mentions of reason codes / policy keys must exist;
- no production module imports the subsystem; an `engine/` directory cannot appear without a conformance runner.

Not committed (throwaway, in the working scratchpad): a prototype of the SPEC's decision procedure, revised for link types, link sets and capability data. All 508 corpus cases agree with it. Two sweeps were run against the committed corpus:

- **198 single-key policy mutations** (every behaviour-bearing key flipped, halved, doubled, incremented or dropped, one at a time): 196 caught; the 2 survivors are equivalent mutants (dropping the last element of an ordering list changes nothing). The sweep also produced each case's `provisional_keys` — **309 of 508 cases depend on at least one still-pending value**, which is the honest size of "the corpus pins mechanics, not calibrated numbers".
- **27 structural controls** (rule-level mutations that are not policy keys — e.g. "the sum rule ignores an individually STRONG member", "parts conflict with parts", "an incomplete stored set is tolerated", "a confirmed gap counts", "a PART_OF claim can be AUTO", "a stored overlap between two subjects is not reported"): every one is caught by at least one case. One survivor from the first pass (the set-size check was masked by the set-id check) was fixed by changing the case, not the rule.

**It proves the SPEC and the corpus are consistent with each other, not that the rules are right** — it has the same author. The rules need the owner's review and, for thresholds, calibration on real data. With `jsonschema` installed the suite additionally checks that the real Draft 2020-12 validator agrees with the stdlib one on every case (verified for this revision: 312 tests pass, 1 skipped = the engine gate).

**Not verified:** how TDR files Range Rover / GWM sub-brands (alias provenance `assumption`); whether TDR's `body_type` and generation dates are populated; any behaviour on production data; **whether an absent Ice or TDR row means zero** (`Q-ICE-ABSENT-ROW`, `Q-TDR-ABSENT-ROW` — unconfirmed capability data, so the contract treats it as unobserved and caps AUTO).

## 5. Compatibility and migration path

Each step needs its own owner gate. None is part of this deliverable.

| Phase | What | Gate |
|---|---|---|
| 0 | **Contract + corpus + tooling (this)** | owner review |
| 1 | `engine/` + `providers/ice.py` + the conformance runner; offline, no DB; the corpus passes 100 % | owner approves the contract |
| 2 | **Shadow mode**: run on a fixture of the R6 inputs, write nothing, diff against the legacy review sheet; **calibrate the `proposal` thresholds per `adoption.yaml`** (a dry run: `binding` stays false); get Ice's and TDR's answers on missing rows | owner reads the diff; every `adoption.yaml` entry `calibrated` / `owner_accepted` before `binding: true` and before the contract is frozen |
| 3 | Persistence: a writer applying write plans; storage for candidate/evidence rows vs mappings; **`link_type` / `set_id` / `set_size` and the active-claim constraints (SPEC §10.6)**; `LOCKED`; redirects for retired splits; the evidence fingerprint column | schema/migration gate (never before R6's own gate) |
| 4 | Facades: `vehreg/ice_crosswalk.py` / `tools/ice_crosswalk_match.py` delegate to the engine; the legacy review CSV is generated from decisions | cutover gate |

Mapping to the v63 tables (no change made):

| v63 | v1 |
|---|---|
| `ice_model_crosswalk.status` AUTO/APPROVED/PROPOSED/REJECTED | same states; **LOCKED** is new (v63's de-facto lock is `match_method = 'ADMIN'`) |
| `match_method` SERIES/NAME/ADMIN | `method` SERIES/NAME/NONE; ADMIN means "a human set it" and is no longer used to label machine STRUCTURE proposals |
| `score` (one number) | the evidence tuple |
| `decision_fingerprint` | two fingerprints (`decision`, `evidence`) |
| `reason` (text) | reason codes + roles |
| `master_version` | `source_version.label` |
| row key `(subject, target)` | claim key `(provider, subject, target, link_type)`; a `COMPOSED_OF` claim is N rows with a shared `set_id` / `set_size`; legacy rows read as `EQUIVALENT` (so a legacy subject with two active rows is a reported C1 violation) |
| unique index: one active group per TDR model | implements C2 for `EQUIVALENT` only; `PART_OF` / `COMPOSED_OF` need constraints of their own, enforced when a row becomes active |
| `ice_model_group_redirects` (RENAME/MERGE only) | needs a SPLIT-successor kind |
| `ice_brand_aliases` | superseded by `policy.aliases` (git-reviewed); the table could become a read model |

Naming note: `vehreg/retail_lineup_*` already has an unrelated *field* called `identity_resolution`; there is no module or package of that name, so nothing collides.

## 6. Decisions for the owner

Numbered for reference; each says what v1 assumes and what I recommend. Items 7–9 were decided on 2026-10-11 (struck through). The rest is open: the contract stays a draft and `adoption.yaml` stays non-binding until they — and the threshold calibration — are settled.

1. **Accept the deliberate deviations D1–D15 in SPEC §15.** The two that change owner-approved text are D2 (token relations replace the §14.2 similarity score; "name ≥ 0.8" becomes "name relation is EQUAL-class") and D5 (a split raises a review question instead of copying a row). New in rev 2: D14 (no assumed zero) and D15 (cardinality by link type). *Recommend: accept.*
2. **Calibrate before adopting — the thresholds are provisional, not adopted.** `adoption.yaml` lists every `proposal`/`assumption` value (11 `calibration` entries, 1 `representation`, 14 `design_choice`) as `pending`. They are defensible defaults, not measured values. *Recommend: share the R6 review CSV and your APPROVED rows (the "label set" described in `adoption.yaml`); it also replaces the reproduced `owner_report_r6` cases.*
3. **Alias authority.** v1 makes `policy.yaml` the source and treats the DB table as a read model. Please confirm the `assumption` aliases (Range Rover/Land Rover, GWM sub-brands) and the token equivalences (`ev`=`electric`, `hatch`=`hatchback`, `hev`=`hybrid`).
4. **MG-registered Maxus vans.** v1 treats MG↔MAXUS as RELATED (PROPOSED at most) because Ice files `maxus-mifa-7/9`, `maxus-v80` under **MG** while TDR's brand is MAXUS. Do you want a scoped rule that makes exactly those AUTO-eligible?
5. **`LOCKED`.** Add it as a real state (recommended) or keep `ADMIN` as the lock?
6. **Protected rows and a rename.** v1 lets an APPROVED mapping follow a rename as a recorded lineage move and makes a LOCKED one wait for the owner (`policy.lineage.protected`). Prefer owner acknowledgement for APPROVED too?
7. ~~**Link types and cardinality.**~~ **Decided 2026-10-11: accepted** (`od_link_types`, `od_cardinality_rules`).
8. ~~**Bundle persistence.**~~ **Decided 2026-10-11: real atomic link sets, not review-only** (`od_atomic_link_sets`).
9. ~~**Storage contract and legacy rows.**~~ **Decided 2026-10-11: `link_type` joins the persistence identity; legacy overlapping claims are reported and never auto-repaired** (`od_persistence_link_type_identity`, I18). Still open and out of scope: the actual migration — widening the row key with `link_type`, adding `set_id`/`set_size`, and the active-claim constraints (SPEC §10.6) — needs its own schema/migration gate.
10. **Retired split parents** (3 ids in M7.0) need a place for their redirect (`ice_model_group_redirects` rejects them today).
11. **Trim-code groups** (`mercedes-benz-e300`, `-c350`, …; 4,473 units for E300 alone). v1 refuses to link `E300` to `E-Class` and flags it for discovery. Add family rules later (recommended) or scope them now?
12. **Questions for Ice and for TDR (not blockers, but they decide how many pairs can ever be AUTO).** `Q-ICE-ABSENT-ROW` (open; stays `UNKNOWN` until Ice explicitly confirms): in `reg_trend.csv`, does a model_group with no row for a month inside `reg_range` mean zero registrations or no data? `Q-TDR-ABSENT-ROW` is **answered by the trace**: `UNKNOWN`; only a contractual month × dimension guarantee (the four `upgrade_requires` items) would change it. Until then any pair with an in-coverage hole in the last 24 months is capped at PROPOSED (`series.absent_row.auto_max_unconfirmed_gap_months = 0`, itself provisional). Also: what does an id_changes RENAME/MERGE mean when the old id is still in `dims`? Is `share_of_old_pct` ever to be shown?
13. **State docs.** `WORK_STATE.md` still says R6 is not started; reconcile it when you decide how the first run is recorded.

## 7. Not done, deliberately

No engine, adapter, CLI, persistence, migration or workflow; no change to `vehreg/ice_crosswalk.py`, `tools/ice_crosswalk_match.py`, `supabase/`, `.github/`, any `ice_*` table, any mapping, `PRODUCTION_*` flag or roadmap gate; no R6 re-run; no R7; no database or network access beyond reading the repository.

## 8. Working with the contract

```bash
cd automotive/vehicle_master
python -m pytest -q tests/identity_resolution                       # the contract suite
python -m identity_resolution.contract.render --write               # regenerate SPEC appendices after editing policy/registry/taxonomy
python -m identity_resolution.contract.render --check               # CI-style check
```

**Adding an edge case** (SPEC §14.4): add or extend a taxonomy entry → add a failing corpus line with the smallest input → change policy (or, later, the engine) until it passes → bump `policy.version` if behaviour moved → regenerate the appendices. Never a Python special case.
