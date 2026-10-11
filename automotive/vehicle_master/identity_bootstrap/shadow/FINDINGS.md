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
