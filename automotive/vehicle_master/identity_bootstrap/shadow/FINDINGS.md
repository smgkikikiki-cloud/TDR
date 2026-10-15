# Relation-first brand parity (after `30d2618`): the producer's typed brand relation and pool lead

**Rule applied (owner decision INIT-01/02):** the brand, the brand relation and the brand family Bootstrap is given now come **only** from the producer's pool and typed brand relation (`br`) of the subject's own Ice x TDR rows (`ir_export.producer_brand`). The local brand/catalog-alias table (`stand_in.local_brand_hint`) is a **diagnostic and a spelling source**: it can neither add a pool member nor change a relation, and a test fails if it does (`test_misleading_local_brand_aliases_cannot_control_...`, `test_the_brand_given_to_bootstrap_never_consults_...`, and the real-snapshot `test_a_misleading_catalog_alias_changes_the_parity_verdict_but_never_the_bootstrap_input`: the whole snapshot stays byte-equal). The producer export (rev 4, `eed76aa6`), its pin and the 38,917 relations are untouched; no rev 5 export is invented.

**Result: 8 -> 1 unresolved (1,199 / 1,200 clear).** Bootstrap outcomes did not move (82 CREATE / 127 REVIEW / 991 HOLD in A, 82 / 365 / 753 in B); the 82-row adjudication set, the dispatch manifest, the nine mandatory catalog-alias reviews and `maxus-maxus-v80` are byte-identical to the accepted head. Eight rows changed (reason codes only; `transitions_vs_30d2618a.csv`):

| Subject | Producer pool | Typed relation | Before (30d2618a) | After | Parity verifiable? |
|---|---|---|---|---|---|
| `MERCEDES AMG\|SL 43`, `...\|SL 55 4MATIC`, `MERCEDESBENZ MAYBACH\|S680 4 M` | `mercedes_benz` x 19 (all of its allowed models) | `ALIAS_RELATED` | local table had no brand -> `BRAND_NOT_IN_TDR`; parity unresolved | brand `mercedes_benz` `ALIAS_RELATED` -> `STRUCTURAL_CONFLICT`; parity resolved | yes: the producer states relation and pool, every pair read |
| `RANGE ROVER\|AUTOBIOGRAPHY P400E LWB`, `...\|EVOQUE 2 2 SD4 DYNAMIC`, `...\|EVOQUE 2 2L SD4` | `land_rover` x 4 | `ALIAS_RELATED` | same | brand `land_rover` `ALIAS_RELATED` -> `STRUCTURAL_CONFLICT`; resolved | yes |
| `maxus-maxus-epc1a` | `mg` x 18 | `ALIAS_RELATED` | same | brand `mg` `ALIAS_RELATED` -> `STRUCTURAL_CONFLICT`; resolved | yes |
| `JETOUR\|ไม่ระบุ` | **empty** (`BRND_NOT_IN_TDR`) | none | local catalog alias hinted `chery` `ALIAS_SAME`, so no brand code | brand `NOT_IN_TDR` -> `BRAND_NOT_IN_TDR`; **still unresolved** | **no (INSUFFICIENT_DATA)**: rev4 has no typed relation; the hint is not adopted. A `chery_jetour RELATED` relation exists only in a later producer policy, not in a versioned consumer export here: a version gap, not a verified fact |

* `ALIAS_RELATED` is only ever a suspicion (Bootstrap policy: `STRUCTURAL_CONFLICT`, never creatable), so none of the seven can become a CREATE; none is in the dispatch manifest. rev5's conditional AUTO-eligibility for RELATED does **not** retroactively authorize any rev4 AUTO or CREATE.
* **Genuine side effect to read correctly:** the structural-conflict tally moves A 17 -> 24 and B 48 -> 55 solely because these seven now carry the engine's `STRUCTURAL_CONFLICT` code. They are **brand-level** conflicts (listed under `of_which_brand_level_alias_related`), not new name-structure conflicts; the name-structure set is unchanged.
* New fail-closed checks: a producer pool whose brand relation is not uniform, whose primary brand is ambiguous, whose `br` is not a typed brand relation, that lacks an allowed model of its brand, or that contains a member without a producer row all make the subject `IR_PARITY_UNRESOLVED` (`BRAND_RESOLUTION_VS_POOL`); a local hint that disagrees with the producer is `BRAND_LOCAL_HINT_DISAGREES`; a local hint with an empty producer pool is `INSUFFICIENT_DATA`. The Bootstrap brand must also equal the producer's view.
* Not changed: PR #200, the lexical rules, the rev4 export, any owner field, `activation_authorized=false` on every dispatch record (blockers `OWNER_APPROVAL_PENDING`, `GOVERNED_WRITER_NOT_BUILT`), no CREATE authorization.

---

# Full-parity QA correction (after `bd14ce0`): TDR snapshot binding and brand parity

No outcome moved: 82 CREATE / 127 REVIEW / 991 HOLD (A), 82 / 365 / 753 (B); the 82-row provisional set, the nine mandatory catalog-alias reviews, all 38,917 exported relations and the producer pin (`eed76aa6`) are unchanged. Two verification gaps were closed.

1. **TDR universe is bound to the producer's hashed snapshot.** The export carries only id/name/status for TDR models, but the routing also reads brand ids and catalog **aliases**. The producer's own inputs (`calibration/inputs/tdr_models.json`, `tdr_brands.json`, `ice_brand_aliases.json`) are vendored byte-for-byte under `shadow/universe/ir_relation_export/tdr_inputs/`, hash-checked against `MANIFEST.sources.tdr_inputs`, and must be what the TDR universe id names (`sha256-e75f970a6957fd42…`). `verify_universe` now compares, per model, brand id, name, deleted, status (HISTORICAL vs CURRENT) and the alias multiset against that snapshot, and brand ids/names for all 62 brands: **a changed alias or status fails closed** (`TDR_ALIASES_DIFFER`, `TDR_STATUS_DIFFERS`, `TDR_BRAND_DIFFERS`) instead of silently changing OWNER_REVIEW routing. Bound: 323 models (296 with aliases, 662 alias strings, 318 CURRENT / 5 HISTORICAL). Not bound: brand-level `aliases` the shadow uses to resolve an Ice brand string (the producer snapshot has none); they are covered by item 2. Aliases are still only echoed to the owner, never treated as automatic equivalence.
2. **Subject-level brand parity checks the resolved brand, not just "resolved?" / "empty pool?".** For every subject it compares the shadow's brand (id, relation, declared family) with the export's pool: each pool member's brand must be the resolved brand or a declared family brand, each member's export brand relation (`br`) must equal the shadow's relation for that brand (EXACT / ALIAS_SAME / the declared family relation), and every allowed (non-deleted, in-pool status) model of the resolved/family brand must be in the pool. A wrong-but-non-null brand is a mismatch (tested on real subjects and on the real snapshot). Result on the real run: the same **1,192 clear, 8 unresolved** (`JETOUR|ไม่ระบุ`; `MERCEDES AMG` ×2, `MERCEDESBENZ MAYBACH`, `RANGE ROVER` ×3 and `maxus-maxus-epc1a`, whose pools exist but whose brands the shadow does not resolve) — parity is not proven for them, so they stay unresolved.

---

# Final reconciliation against PR #200's full pair-level relation export (`eed76aa6`)

**Pin.** PR #200 commit `eed76aa6ad6380afea60d604e5e7eac87abedb06`, export `ir-rev4-m7.0-relations/1`, schema `ir-relation-export/1`, consumer contract `ir-relation-export-consumer/1`, `MANIFEST.json` sha256 `e9d74e05ce9c09ad59bad2654d16fbb74e06969e929b7415b5e55a0fc2d2e0b8`, producer contract draft / `adoption.binding: false`. The producer's seven files are vendored byte-for-byte under `shadow/universe/ir_relation_export/` and verified fail-closed at load (manifest pin, per-file sha256/bytes/lines, versions, universes, key digests, ordering, the full same-brand Ice×Ice population, pool membership rules, per-subject coverage). A test also checks them against the git objects when present.

**The stand-in matcher is gone.** `StandIn` now only resolves brands and the mode-A activation switch; every Ice×TDR relation is a lookup over the subject's export pool and every Ice×Ice relation a whole-key lookup (smaller id first; COARSER/FINER flipped on reversal; ids containing `|` are never split). A pair the export lacks raises `PAIR_NOT_EVALUATED`; nothing defaults to CONTRADICTION; an empty pool (226 subjects) yields no relation and is never a CREATE authorisation. `ir_rev4` (the partial bridge) and the local diagnostics that re-judged names were deleted.

## Parity

- **Lexical:** all 26,505 Ice×Ice and 12,412 Ice×TDR pairs were read; 439 + 391 non-CONTRADICTION/UNAVAILABLE relations reached Bootstrap; zero snapshot relations absent from or relabelled against the export; relation counts equal the manifest for **all nine kinds** in both populations (the old EQUAL 299 vs 239, COARSER 46 vs 58, FINER 45 vs 35 and TOKEN_EQUIV 0 vs 1 disagreements are gone).
- **Candidate pools:** the shadow compared exactly the export pools (0 outside, 0 unread). The old stand-in candidate set (every model of the resolved brand family) differed from the pools for 8 subjects: 7 with a pool but no brand resolved by the shadow (`MERCEDES AMG`, `MERCEDESBENZ MAYBACH`, `RANGE ROVER` ×3) and 1 resolved by the shadow but with an empty pool (`JETOUR|ไม่ระบุ`), plus `maxus-maxus-epc1a`.
- **Subjects:** 1,192 meet every consumer-contract requirement and clear `IR_PARITY_UNRESOLVED`; **8 stay unresolved** with the exact reason `BRAND_RESOLUTION_VS_POOL` (shadow brand resolution vs the export pool). `OWNER_APPROVAL_PENDING` and `GOVERNED_WRITER_NOT_BUILT` are untouched for all.
- **Reference evaluator vs Bootstrap (reported separately):** IR NO_CANDIDATE→82 Bootstrap CREATE; IR AUTO→69 HOLD; IR PROPOSE→174 HOLD / 21 REVIEW; IR INSUFFICIENT_DATA→33 HOLD / 20 REVIEW; one divergence to inspect (`audi-audi-a1`: IR NO_CANDIDATE but mode A diverts it as a lexical duplicate). No CREATE where IR's dry run found a candidate.

## Result (mode A / mode B)

| | b132a86 | Final |
|---|---|---|
| CREATE | 73 / 72 | **82 / 82** |
| REVIEW | 89 / 375 | 127 / 365 |
| HOLD | 1,038 / 753 | 991 / 753 |
| STRUCTURAL_CONFLICT groups | 9 / 48 | 17 / 48 |

77 subjects changed (`transitions_vs_b132a86.csv`: previous/new decision, TDR candidate ids, relation evidence, codes). CREATE **removed (1): `maxus-mifa-7`** — its sibling `maxus-mifa-9` is now a lexical duplicate in the batch, so both go to structural conflict/review. CREATE **added (10)**: Audi A8L, Audi S3, BYD e6, Isuzu CAB4, Jaecoo J5, Jaecoo J7, VW Multivan, VW ID.Buzz, Wuling Binguo — all nine lost an EQUAL that the old stand-in took from the **TDR catalog's own `aliases`** (e.g. `audi.a8` aliases `A8L`) which the IR evaluator does not compare (name_en only) — plus **BMW X2** (lost SUBJECT_COARSER to `bmw.ix2`; a different car). 38 mode-A HOLDs became REVIEWs for the same reason. Registrations (information only): added CREATEs 27,010 lifetime / 25,714 last 12 months; removed 934 / 698.

## Existing-identity collisions

- **Catalog-alias collisions (9):** the nine above are flagged `POSSIBLE_EXISTING_IDENTITY_CATALOG_ALIAS` in the routing/review layer — catalog data echoed to the owner (exact alias = provider name), **not a relation, never passed to the engine, no PR #200 rule re-implemented** — and routed to mandatory OWNER_REVIEW. For two of them the legacy R6 matcher had itself linked the group (status AUTO: Audi A8L→`audi.a8`, Binguo→`wuling.wuling_bingo`), now flagged `LEGACY_R6_AUTO_MATCH`. An interface request to PR #200 about catalog aliases is recorded in `IR_FULL_PARITY_INTERFACE_REQUEST.md`.
- **Maxus/MG:** `maxus-maxus-v80` stays CREATE with mandatory owner review (provider-id label `maxus` is a token of `mg.mg_maxus_7/9`); `maxus-mifa-7` is no longer a CREATE.
- **Routing of the CREATE set:** CURRENT_DISCOVERY 9 / ACTIVITY_UNCLASSIFIED 63 / OWNER_REVIEW 10 (was 9 / 62 / 2). Market activity (Ice absent rows UNKNOWN): UNKNOWN 70, ACTIVE 9, DECLINING 3; the ABSENT_IS_ZERO what-if (not authoritative) would have 25 INACTIVE_INFERRED. Every record keeps `activation_authorized = NO`.

## Unresolved

8 subjects with a brand-resolution/pool disagreement; the TDR-catalog-alias gap in the IR evaluator (open interface question to PR #200); `audi-audi-a1` mode-A divergence; BMW X2 and the other lexically-clean suspects (BMW M2–M5, Foton BJ1041, Sokon CRC50, Toyota TR, Genesis G80) await owner labels; Ice absent-row semantics; owner approval and the governed writer. The 82-row set is **provisional**; the owner fields are blank.

---

# Small correction after `cac76d6`: explicit zero in an incomplete month; projection is not authorization

- **Market activity:** an *explicit* zero-registration row in an incomplete trailing month was still counted as a zero (only missing rows were guarded). `resolve_series` now makes any zero — explicit or inferred — in a period after `complete_through` unknown; positive counts there still show activity. Synthetic regression tests added. No M7 result moved (the package has no explicit zero rows): routing stays 9 current / 62 unclassified / 2 owner-review.
- **Current-discovery lane = projection only.** Every dispatch record, `dispatch_manifest.csv` row and adjudication row now carries `activation_authorized = NO` and the blockers `IR_PARITY_UNRESOLVED | OWNER_APPROVAL_PENDING | GOVERNED_WRITER_NOT_BUILT`; no code path can set it true, and a test enforces that.
- **Separate issue, not fixed here:** the central *TDR Enforcer PR Admission* workflow fails on this legacy PR head because its Stage-1 test files are absent. PR #201 neither copies Enforcer scripts nor disables the check; this is a central Enforcer compatibility issue.

---

# QA correction round after `2d56112` (partial parity, cross-brand risk, dispatch boundary, portable tests)

All shadow measurements and the provisional adjudication rows are unchanged; owner fields stay blank. Added, not changed: labels, a routing layer and tests.

1. **Parity is PARTIAL, and now says so.** The PR #200 export carries pair ids for FUZZY / SIBLING / EQUAL_VIA_MODEL_ALIAS only; the stand-in still generates EQUAL, TOKEN_EQUIV, COARSER, FINER (Ice×TDR EQUAL 299 vs 239, COARSER 46 vs 58, FINER 45 vs 35; Ice×Ice TOKEN_EQUIV 0 vs 1). The 73 CREATEs are a **stand-in scenario estimate, not the Resolver's output**. Every one of the 1,200 verdicts carries `IR_PARITY_UNRESOLVED` with its reasons (`results/…/ir_parity_unresolved.csv` lists the subjects with subject-specific reasons — an unchanged-kind relation IR does not list, or a stand-in FUZZY/SIBLING dropped because the export lacks it — and the adjudication CSV has `ir_parity_status` / `ir_parity_reasons`). `IR_FULL_PARITY_INTERFACE_REQUEST.md` asks PR #200 for a complete nine-kind pair export as a separate later change; nothing of #200's rules is implemented here.
2. **Maxus/MG is explicit.** `maxus-mifa-7` and `maxus-maxus-v80` carry `POSSIBLE_EXISTING_IDENTITY_CROSS_BRAND` with mandatory OWNER_REVIEW, raised by a generic evidence rule in the *routing layer* (`routing/signals.py`; no brand or model is named): the provider id's leading label (`maxus`) is not an Ice-brand spelling (`MG`) but is a whole token of existing identities under the resolved brand (`mg.mg_maxus_7`, `mg.mg_maxus_9`); Mifa 7's sibling Mifa 9 is already EQUAL to `mg.mg_maxus_9` (alias `mifa 9`) and R6 proposed `mg.mg_maxus_7` (0.62). Over all 1,200 subjects the rule fires on exactly these three (Mifa 9 is a HOLD). They are kept out of the current lane. Advisory (non-blocking) hints list the 8 CREATEs with a legacy R6 PROPOSED target ≥ 0.6 (Acty→City, MX-30→CX-30, Mazda6e→Mazda6, 5008→3008, …) — noisy, shown for the owner, never decisive. Lists: `cross_brand_review.csv`.
3. **Dispatch boundary.** `routing.project` / `dispatch_all` is a pure projection after the engine (decisions and write plans untouched, tested): only a CREATE can be dispatched; `CURRENT_DISCOVERY` only for ACTIVE / DECLINING / REACTIVATED without a mandatory review; INACTIVE_INFERRED → `HISTORICAL_INACTIVE`; UNKNOWN / unrecognised → `ACTIVITY_UNCLASSIFIED`; mandatory review → `OWNER_REVIEW`. Result on the 73: **9 current-discovery** (was 10: Mifa 7 left), 62 unclassified, 2 owner-review (`dispatch_manifest.csv`). Completeness: the newest package period (2569-09) is **assumed** complete (final package status; there is no per-month flag), and the classifier now takes `complete_through`: an incomplete trailing month can never supply a true zero (tested with synthetic sequences: confirmed four-zero, unconfirmed UNKNOWN, sporadic trickles, relaunch override, incomplete month).
4. **Portable coverage.** `test_ib_committed_artifacts.py` (15 tests) checks the committed export (content hash), counts, transitions manifest (recomputed from the two committed decision CSVs), structural-conflict movement, the adjudication set, review routing, dispatch manifest and market activity — **without** the archived package or the PR #200 git objects. A `conftest.py` prints an explicit skip report (and writes `$GITHUB_STEP_SUMMARY`). With the package hidden the suite is 2,912 passed / 57 skipped (25 need the package; 32 are by-design parameter skips); with it, 32 skipped.
5. **Mode B** is a force-activate-all **stress scenario**, not an upper bound: extra activated subjects can create batch conflicts (that is why B has 72 CREATE vs A's 73). `B ⊆ A` is an observation on this snapshot only and is labelled so in the report and tests.

---

# Post-PR-#200-rev-4 rerun (consumed from the pinned export; read-only; recommendations only)

Relations come from PR #200 commit `1f73aee1834697cbd439291d0074293c30446e5b` (rev 4: no FUZZY across digit tokens, SIBLING needs a distinctive shared token, Honda-scoped Jazz↔Fit and Stepwagon↔Step WGN). `shadow/ir_rev4.py` vendors **its published relation output** (`calibration/lexical_pass/after_rev4.json`, sha256-pinned; a test re-reads the blobs from the commit) — **no PR #200 rule is re-implemented or forked here**; the stand-in's own milestone-2 "refined" what-if (a local clone of those rules) was deleted. The stand-in now supplies only the pair population (a deliberate superset) and the relations rev 4 did not touch; every FUZZY / SIBLING / EQUAL_VIA_MODEL_ALIAS verdict is IR's. Same engine, policy v2, package, TDR universe as milestone 3 (`baseline_m3/` is frozen). `REPORT.md` §0 has every table; `transitions_vs_m3.csv` has all 74 changed groups.

| | Milestone 3 (A / B) | Post-rev-4 (A / B) |
|---|---|---|
| CREATE | 67 / 67 | **73 / 72** |
| REVIEW | 89 / 380 | 89 / 375 |
| HOLD | 1,044 / 753 | 1,038 / 753 |
| STRUCTURAL_CONFLICT groups | 24 / 105 | **9 / 48** |

- **Relation parity:** 316 exported ice×ice and 58 ice×tdr pairs all present with IR's relation; ice×ice FUZZY 7/7, SIBLING 307/307, EQUAL_VIA_MODEL_ALIAS 2/2; ice×tdr FUZZY 2/2, SIBLING 55/55, EQUAL_VIA_MODEL_ALIAS 1/1 (stand-in/IR). Zero FUZZY/SIBLING pairs outside the export.
- **CREATEs that disappeared (3):** Honda Jazz, Honda Fit, Honda Stepwagon. Jazz and Fit are now one vehicle in two Ice groups (`EQUAL_VIA_MODEL_ALIAS`) → both `IDENTITY_REVIEW / STRUCTURAL_CONFLICT`; TDR has neither, so a single identity may still be owed, but never two. Stepwagon ≡ TDR `honda.step_wgn` → `HOLD / NOT_ACTIVATED` (A), reviewed in B. These were *not* false merely for being old.
- **CREATEs that appeared (9):** Mazda MX-30, Mazda6e, Nissan BE-1, Peugeot 5008, VW T-Roc, VW T-Cross, Volvo ES90 (all expected: a digit-only FUZZY/SIBLING objection fell away), **plus Maxus V80 and Maxus Mifa 7**. TDR holds the Maxus models under brand `mg` (`mg.mg_maxus_7`, `mg.mg_maxus_9`); the only link was a shared digit, so they are now clean — **a brand-family gap (Maxus↔MG), not a Bootstrap rule**, and likely EXISTING_IDENTITY for Mifa 7 (legacy R6 proposed `mg.mg_maxus_7`, score 0.62). Left for the owner; I did not add a Maxus→MG family locally.
- **The 177 NO_CANDIDATE groups PR #200 released:** 115 are unsettled raw ids and 30 provisional (HOLD by contract), 32 settled. Only **7** are Bootstrap CREATEs in either mode: five of the new ones above (MX-30, Mazda6e, BE-1, T-Roc, T-Cross) plus Honda N-BOX and VW Tiguan, which were already CREATE. 7 are reviewed in A (11 in B; POSSIBLE_MODEL_CODE for Lexus RZ/ES codes, duplicates, body variant), the rest are held. Not all 177 are candidates.
- **Mode B ⊆ mode A, no longer equal.** `maxus-mifa-7` is CREATE in A only: its sibling `maxus-mifa-9` is diverted by the resolver stand-in, so no batch conflict forms. The old "CREATE sets identical" invariant is replaced by the subset invariant (tested).
- **Unresolved risks:** (1) seven ice×tdr pairs where IR says SIBLING but the stand-in alone had a stronger unchanged-kind relation (e.g. Ford Ranger Raptor↔`ford.ranger_double_cab` EQUAL via a catalog alias): IR wins, outcomes moved (Ranger Raptor HOLD→REVIEW); unchanged-kind counts also differ from IR's (EQUAL 299 vs 239) — a stand-in/IR population disagreement that rev 4 did not touch; (2) Maxus↔MG family (above); (3) BMW M2–M5, Foton BJ1041, Sokon CRC50, Toyota TR, Genesis G80 remain lexically clean and unexplained, as before; (4) Jazz/Fit need an owner decision on the single identity to create.

**Market-activity routing (absent rows UNKNOWN):** 73 CREATEs → actual `UNKNOWN 63, ACTIVE 9, DECLINING 1` (lanes ACTIVITY_UNCLASSIFIED 63, CURRENT_DISCOVERY 10); what-if ABSENT_IS_ZERO (not authoritative) `INACTIVE_INFERRED 23, UNKNOWN 34, ACTIVE 9, DECLINING 7`. Routing never changed an outcome.

**Provisional adjudication set** (`review/create_adjudication.csv`, 73 rows; 9 added, 3 removed vs milestone 3, 64 unchanged): every machine field filled, `owner_verdict / owner_canonical_model_id / owner_discovery_class / owner_notes` blank, machine suggestions in `*_NON_AUTHORITATIVE` columns. Not final: QA first.

---

# Shadow run findings — Ice `2569-09` v3 M7.0, milestone 3 (read-only; recommendations only)

Numbers come from `results/2569-09_v3_M7.0/` (`REPORT.md` §0 has the before/after tables; `summary.json` and `decisions.csv` have the data; a test fails if they go stale). The milestone-2 baseline is frozen in `baseline_m2/`.
**Nothing was written to Supabase, no identity was created, no persistence, no enrichment bot, serving / PR #200 / R6 / R7 untouched.** Registration volume is informational throughout and never changes an outcome.
`analyst_notes.yaml` is my judgement, **not ground truth**; the owner-labelled truth set (`review/create_adjudication.csv`) is what any later CREATE-permission calibration must use.

## Universe: what "fullest canonical Vehicle Master" turned out to be

The live Vehicle Master was read with `SELECT` inside `begin transaction read only` (record: `universe/vehicle_master_live_2026-10-11.json`). It holds **323 models / 62 brands**: CURRENT 318, HISTORICAL 5, **no deleted/withdrawn rows, no UNVERIFIED, no DISCOVERED/pending state — the schema has no `identity_state` column yet**. It is identical to the repo file snapshot milestone 2 used on every identity-bearing field (ids, brand, English name, aliases, state). So:

- CREATEs removed because the fuller universe already contained them: **0**. The full Vehicle Master did **not** materially reduce CREATE; the milestone-2 "upper bound" caveat is closed, not the CREATE problem.
- What the fuller universe adds is the 5 HISTORICAL ids and reservation of all 323 slugs in the collision check.
- Still missing (does not exist in the schema): DISCOVERED/pending identities, UNVERIFIED models, deleted/withdrawn ids. When those exist the adapter must feed them; the snapshot already has `identity_state` and `deleted` fields for them.
- R6 `ice_model_crosswalk` (490 rows) was read for the 67 remaining CREATEs (`universe/r6_crosswalk_for_create_candidates.json`): 34 groups have a legacy **PROPOSED** row (none matched/approved), 33 have none. Informational only; the engine never reads it.

## Before / after (mode A / mode B)

| | Before (policy v1) | After (policy v2) |
|---|---|---|
| CREATE_IDENTITY | 78 / 78 | **67 / 67** |
| IDENTITY_REVIEW | 94 / 385 | 89 / 380 |
| HOLD | 1,028 / 737 | 1,044 / 753 |
| CREATE units, all time / last 12 m | 47,391 / 10,624 | 46,816 / 10,272 |
| STRUCTURAL_CONFLICT groups | 29 / 110 | 24 / 105 |

Transition matrix (identical in A and B): CREATE→CREATE 67, CREATE→HOLD 7, CREATE→REVIEW 4, REVIEW→HOLD 9 (the same registration codes now caught earlier as raw codes); **CREATEs added: 0**.

## What each new rule did (single-rule ablation: only that rule off, all else equal)

| Rule | CREATEs removed | Collateral |
|---|---|---|
| R1 hyphenated chassis/registration-code segment | 7 (six Hino `FG8JJ1A-JJT`…, Toyota `KUN51R-NKPSYT`) | 9 REVIEW→HOLD (codes already flagged; reason now exact). 0 hits on settled non-code names; D-Max, MX-30, Genesis G80, Deepal, Chery C5 EV, MINE `MTS-MT30` unaffected (pinned by corpus) |
| R2 powertrain suffix glued to a digit token | 1 (JAC `T8EV`) → REVIEW `POSSIBLE_POWERTRAIN_DERIVATIVE` | none |
| R4 displacement / trim code (`630i`, `530e`, `264GL`) | 1 (McLaren `750S`) → REVIEW `POSSIBLE_MODEL_CODE`, clearable by tier-2 evidence or an admin directive (pinned) | 47 already-HOLD raw names gain the code; 2 REVIEWs gain it |
| Truncation (soft) | 2 (Chery `Q`, Jeep `Grand`) → REVIEW `POSSIBLE_TRUNCATED_NAME` | 6 REVIEWs gain the code; never HOLD |
| Year range + context | 0 on M7 (no M7 name was misread as a year) — Peugeot 2008 is pinned by the corpus | — |
| Sub-brand spellings / brand family | **0 on M7**: the stand-in already drops sub-brand aliases and pools Changan/Deepal. They are defence-in-depth, pinned by corpus cases, not by this run | — |

Honest read: the real-data gain is 11 CREATEs (14%); two further rules do nothing on this package and exist because the contract must hold for adapters that do not pre-filter.

## Remaining CREATE candidates: 67 (all in `review/create_adjudication.csv`, `owner_label` blank)

Informational activity split: **DORMANT_LEGACY 59** (33,882 lifetime / 173 last-12-month units), **RECENT_DISCOVERY 3** — Jaecoo J6, Zeekr 7X, Foton eView (11,695 / 9,859) — **ACTIVE_ESTABLISHED 5** (1,239 / 240). All 67 are tier 0 (provider identity only): `NEW_IDENTITY_CONFIRMED` means "no defence fired", not "verified new vehicle".

### Remaining suspected false-CREATE classes (analyst reading, 11 of 67, 15,402 units — not ground truth)

| Class | Groups | Why no rule catches it |
|---|---|---|
| Same car under two names | Honda Jazz + Honda Fit; Honda Stepwagon (TDR holds `honda.step_wgn`) | needs a brand-scoped model-synonym table — belongs to Identity Resolution (PR #200), sent there |
| Performance variants | BMW M2/M3/M4/M5 | owner decision whether TDR models M cars separately; lexically they are clean nameplates |
| Provider code vs nameplate | Foton `BJ1041`, Sokon `CRC50` | a letters+digits code with no hyphen and no suffix pattern; indistinguishable from `T8`/`S660` without evidence |
| Short / unclear name | Toyota `TR` | two letters; the truncation rule needs ≥2 compact chars, so it passes |
| Brand attribution | Genesis G80 filed under Hyundai | sub-brand under parent: not a duplicate of anything in TDR; needs a brand-family *model-placement* decision |
| Discontinued legacy models | many of the 59 dormant ones (Vios, March, Note, Urvan, Leaf, Corvette…) | real cars; whether TDR wants them is a catalogue-scope decision, not a defect |

### Suspected false REVIEW / HOLD

- Relation noise from the stand-in (which follows PR #200 §5.3): SIBLING on non-distinctive tokens and FUZZY across digit tokens cause STRUCTURAL_CONFLICT (24 in A). Sent to PR #200 as a separate pass; what-if with stricter relations: CREATE 74, REVIEW 88, HOLD 1,038 (A), structural conflicts 7 (A) / 49 (B).
- **Cross-PR CREATE risk exposed by the stricter relations:** +7 CREATEs (Mazda MX-30, Mazda 6e, Nissan BE-1, Peugeot 5008, VW T-Roc, VW T-Cross, Volvo ES90). BMW 630i, Volvo 264GL and 264GLE — which were in the milestone-2 what-if (+10) — are now held by R4, which is what R4 was for. The remaining seven look like real models absent from TDR, but they are **unlabelled**; include them in the owner truth set.
- Honda S660 (real model) is still held as `POSSIBLE_MODEL_CODE`; legitimate names with `EV`/`Plus`/`Sport`/`GT` are caught by other reasons today.
- 591 `BRAND|MODEL` ids are held as unsettled by contract; 158 have a clean-looking name — a provider-side settling task, not Bootstrap's.

## Is the CREATE path ready for owner-labelled truth-set calibration?

Yes for building the truth set; **no** for granting production CREATE permission. The rules are policy-driven, mutation-tested and agree with an independent oracle, but 67 CREATEs are tier 0 and the only real-data evidence on their precision is my unlabelled reading. Next step is the owner filling `owner_label` on `review/create_adjudication.csv` (and the seven stricter-relation CREATEs), then measuring false-CREATE rate per class before any permission decision.
