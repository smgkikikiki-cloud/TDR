# Contract v1 — change log

Contract v1 is a **draft and is not frozen**. Nothing reads it in production. Entries are newest first; each names the
files it touched and the corpus rows that pin the change (SPEC §14.4).

## owner decision & calibration preparation pack (2026-10-11) — no contract change

**No contract file changed** (policy, capabilities, registry, taxonomy, schemas, SPEC, corpus and the relation export are exactly as accepted; `binding: false`, not frozen). Added `identity_resolution/calibration/owner_decision_pack.py` and `owner_decision_pack/`: the reconciliation of `r6_owner_review.csv` with PR #201's 82-row provisional CREATE set (two verdict vocabularies kept apart), nine catalog-alias collisions, eight unresolved brand-resolution cases plus the Maxus filing collision, the R6 priority view with a coverage-defined starter batch and brand-separated folds, the 82 CREATE candidates by risk tier, a weighted negative sample, the pending-threshold sensitivity table, the calibration entry requirements and procedure, and a first wave of 65 owner actions. All owner fields are blank; machine suggestions are `*_NON_AUTHORITATIVE`. Four PR #201 data files are vendored as byte pins. Tests: `test_ir_owner_decision_pack.py`.

## relation export for PR #201 (2026-10-11) — no contract change

**No contract file changed** (policy, capabilities, registry, taxonomy, schemas, SPEC and corpus are exactly rev 4; `binding: false`, not frozen). Added `identity_resolution/calibration/relation_export/`: the complete, deterministic, versioned pair-level export of the M7.0 name relations (Ice × Ice 26,505 pairs, Ice × TDR 12,412, all nine relation kinds), the subjects' candidate pools and tokens, the reference evaluator's dry-run outcomes, a manifest pinning the source blobs, a schema and `CONSUMER_CONTRACT.md` (the hand-off: keys, ordering, pinning, pool reading, replacing `ir_rev4.adjudicate` with lookups, when `IR_PARITY_UNRESOLVED` may clear). `lexical_pass.ice_ice_population` was factored out so the population is defined once (no behaviour change). New tests: `test_ir_relation_export.py` (coverage, nine-kind parity, pair-for-pair against the evaluator, byte stability, provenance; runs without the package). No rule, policy value, corpus case or sensitivity run changed.

## rev 4 — lexical-relation correction (2026-10-11)

The owner authorised a correction pass on the name-relation ladder after the M7 lexical/relation analysis. Recorded as the accepted owner decision `od_lexical_relation_correction`; **still a draft, NOT frozen**, `binding: false`. Production, DB state, mappings, R6/R7, migrations, engine wiring, PR #201, adoption binding and the freeze state were not touched.

- **FUZZY (SPEC §5.3 step 4).** New `lexical.fuzzy_token.allow_tokens_with_digits: false`: a token that contains a digit is never paired as a typo (`KDH222R`/`KDH223R`, `Mazda2`/`Mazda3`, `Mazda6`/`Mazda6e`). Letters-only typos keep the tolerance (`Canival`/`Carnival`); a digit in a token both names share is irrelevant.
- **SIBLING (step 7).** New `lexical.distinctive_token`: SIBLING needs at least one distinctive shared token, otherwise the pair is CONTRADICTION. Distinctive = at least `min_length` (3) long, not purely numeric, not in the descriptor vocabulary (`non_distinctive`: body / powertrain / trim / generation / market) and not a descriptor shape (`non_distinctive_patterns`: `4x2`, `V10`, `25hev`, `Gen2`, `Mk4`). Generic and policy-driven — no model is named in the evaluator (a test scans for it); `V`/`CX`/`GR`/`RS`/`HR` are excluded by the length floor, `30` by the numeric rule, `AMG` by the trim vocabulary. `required_for_relations: [SIBLING]` is the owner's scope; containment relations are not included (reported, see below).
- **Model aliases (§5.4).** An `aliases.model` entry may be scoped by `brands` (the brand relation must be EXACT / ALIAS_SAME and the brand one of them) instead of a brand alias id. New entry `honda_model_synonyms`: `Jazz` ↔ `Fit`, `Stepwagon` ↔ `Step WGN` (whole names, either orientation).
- **New invariant I19 — a lexical tightening never promotes** (SPEC §2). AUTO needs an `EQUAL*` relation; no tightening creates one; the only new `EQUAL*` pairs are the synonyms. Pinned by `test_ir_lexical_invariants.py`: per name pair (never more permissive than rev 3, which is re-derived live by `lexical_pass.rev3_rules()`), per `resolve` case (new AUTO only for the two listed synonym cases), and on the real snapshot (same 69 AUTO groups).
- **Corpus.** 508 → 562 cases (+54, written before the rules; 37 fail against the rev 3 evaluator, 17 pin behaviour that must not move); taxonomy `NAME-14`…`NAME-17` (112 → 116 entries); reason-code summaries of `NAME_FUZZY_TOKEN`, `NAME_SIBLING_VARIANT`, `NAME_CONTRADICTION` reworded (no code added or removed).
- **Adoption.** New owner decision; `lexical_fuzzy_digits` and `lexical_distinctive_rule` are `owner_accepted` (the owner's rules); `lexical_distinctive_min_length` (calibration) and `lexical_distinctive_vocabulary` (design choice) are the pass's proposals and stay `pending` (28 pending entries, was 26). Policy sweep: 300 single-key mutations (was 198), 218 caught; 82 survive = 2 equivalent mutants + 80 single words of the descriptor vocabulary that no case pins individually (each class, each pattern and the floor are pinned). 347 of 562 cases depend on a pending value.
- **Measured on the real M7.0 package** (`calibration/lexical_pass/`, before = rev 3 re-derived live, independent of the PR #201 stand-in): FUZZY 54 → 7 Ice×Ice, 9 → 2 Ice×TDR; SIBLING 1,152 → 307 and 184 → 55; groups in a same-provider structural conflict 522 → 322 (settled 109 → 55); 2 of 1,200 engine decisions changed and AUTO is the same 69 groups. Newly exposed CREATE risk: `mazda-mazda6e` PROPOSE → NO_CANDIDATE (a wrong proposal to `mazda.mazda6` withdrawn); 177 groups released from a structural conflict are NO_CANDIDATE. The Honda synonyms add one name-only PROPOSE (`honda-honda-stepwagon` → `honda.step_wgn`, flagged against `honda-step-wgn`'s AUTO) and no AUTO.
- **Calibration outputs regenerated** from the committed inputs with the rev 4 evaluator (`calibration/build.py`; the inputs, the legacy columns and the blank owner columns are unchanged) and the sensitivity run repeated with eight new variants for the new keys. Not changed: the recovered rows, the replay (489/489 exact), the owner-review sheet's ordering rule.
- Known gaps, reported and not fixed (the owner's scope): containment (`SUBJECT_COARSER`/`SUBJECT_FINER`) resting only on descriptor tokens (Ice×Ice 15 + 16, Ice×TDR 7 + 19); five Toyota catalog codes that differ in one *letter* remain FUZZY; the synonyms are whole-name pairs (`Jazz Hybrid`, `Step Wagon` are not covered).

## calibration data milestone (2026-10-11) — no contract change

**No contract file changed** (policy, capabilities, registry, taxonomy, schemas, SPEC and corpus are exactly rev 3; `adoption.yaml` changed only in one comment). Status stays **draft, NOT frozen**, `binding: false`.

- Added `identity_resolution/calibration/`: the first-run R6 rows recovered read-only from production (490 `ice_model_crosswalk` rows, 50 redirects, the matcher's inputs) with provenance and hashes; an offline replay that reproduces all 489 stored matcher rows exactly; a calibration dataset (legacy evidence vs Contract v1 on the common observation window), the owner-adjudication sheet `r6_owner_review.csv` (owner columns blank), a sensitivity run on the real data, a data dictionary and `CALIBRATION_REPORT.md`.
- Added tests: `test_ir_calibration.py` (25) and `test_ir_reference_evaluator.py` (3); the directory now has 340 passing tests and 1 skipped.
- `calibration/ref_eval_*.py` is a reference transcription of the SPEC used to produce the v1 columns. It is **not** the engine: no persistence, no adapter registry, no CLI, no production import, the engine gate is unchanged.
- Nothing is calibrated: no owner label exists. Ice and TDR absent-row semantics stay UNKNOWN.

## rev 3 — owner decisions (2026-10-11)

The owner decided the open points. Recorded as `owner_decisions` in `adoption.yaml`; **still a draft, NOT frozen**, `binding: false`.

- **Accepted:** the three link types, the two cardinality rules (C1, C2) as v1, bundles as real atomic link sets (not review-only), and `link_type` in the persistence identity — logical contract only, no DDL/migration/write path.
- **New invariant I18 — stored overlaps are reported, never auto-repaired.** Decision-procedure step 0 (SPEC §8.2) now also covers a stored overlap *between two subjects* contrary to C2 (previously only C1 within one subject and broken sets): every subject involved gets `STRUCTURAL_REVIEW` / `STRUCTURAL_STORED_CLAIMS_INCONSISTENT` and nothing is written — a stored AUTO row overlapping a protected claim is no longer demoted by the write matrix. Corpus: `resolve.stored-overlap-*`, `resolve.stored-parts-sharing-a-target-are-not-an-overlap`; taxonomy `CARD-14`.
- **Ice absent-row semantics stay UNKNOWN** until Ice explicitly confirms (standing decision, tripwire test).
- **TDR registrations traced instead of assumed:** `provider_capabilities.yaml` gains a `trace` (five pipeline stages, each `guarantee: none`) and `upgrade_requires`; verdict **UNKNOWN stays**. A confirmed `ABSENT_IS_ZERO` must now carry a `coverage_guarantee` (schema + test). A test re-reads the committed DLT snapshots and fails if they ever contradict the evidence (explicit zero row; gap-free month chain; no interior label holes). `Q-TDR-ABSENT-ROW` is answered by the trace.
- **Adoption bookkeeping:** `owner_decisions` (8 entries, tests tie `binding: true` to lifting the standing ones); `candidates_bundle_rules` split into `candidates_bundle_enabled` (`owner_accepted`) and `candidates_bundle_members` (`pending`); `provisional_keys` now lists only `pending` entries.
- Counts: 508 cases (was 505), 112 taxonomy entries (was 111), 104 reason codes; 312 contract tests; policy sweep 198 mutations (196 caught + 2 equivalent); 27 structural controls, all caught.

## rev 2 — owner review (2026-10-11)

The owner accepted the architecture in principle and asked for three contract-level fixes before adoption, a wording
change and an adoption gate. Status stays `draft_not_frozen`.

### 1. Missing-row semantics are capability data (was: assumed)

- **Before:** SPEC A2 said an Ice absent row inside `reg_range` "is read as 0 … to be confirmed by Ice". The assumption
  lived in the adapter text and the taxonomy (SER-05) and would have zero-filled evidence nobody had confirmed.
- **Now:** `provider_capabilities.yaml` (+ `capabilities.schema.json`) declares `series.absent_row` per source as
  `ABSENT_IS_ZERO | ABSENT_IS_UNOBSERVED | UNKNOWN` with a `confirmed | unconfirmed` status. **Ice: UNKNOWN / unconfirmed**
  (hypothesis `ABSENT_IS_ZERO`, open question `Q-ICE-ABSENT-ROW`). **TDR registrations: UNKNOWN / unconfirmed**
  (`Q-TDR-ABSENT-ROW`). A zero may be written only for `ABSENT_IS_ZERO` + `confirmed`.
- `record.schema.json`: a series may carry `absent_rows {source, semantics, confirmed, months}`.
- Engine: months lost only to an unconfirmed missing-row meaning are excluded (never zero), counted as
  `semantics_gap_months`, reported as `SER_MISSING_ROW_SEMANTICS_UNCONFIRMED`, and cap AUTO above
  `series.absent_row.auto_max_unconfirmed_gap_months` (0). Refusals `INPUT_CAPABILITY_MISMATCH` and
  `INPUT_ABSENT_ROW_ZERO_UNCONFIRMED` guard the boundary.
- New invariant **I4a** (no assumed zero), SPEC §3.2 and §6.2a. Corpus: `densify.*`, `window.absent-row-*`, `resolve.absent-row-*`.

### 2. Cardinality separates identity, aggregation and granularity (was: one target, one subject)

- **Before:** a provider-finer subject (Ice `honda-city-hatchback` against one TDR `City`) could only be a
  `STRUCTURAL_REVIEW` / `STRUCTURAL_PROVIDER_FINER` — a forced "TDR must split" question.
- **Now:** three link types (SPEC §7.0): `EQUIVALENT` (1:1), `COMPOSED_OF` (one subject, a set of targets), `PART_OF`
  (many subjects, one target). Two active claims conflict iff they belong to one subject (C1) or share a target unless both
  are `PART_OF` (C2). `PART_OF` and `COMPOSED_OF` are never AUTO.
- Removed codes: `STRUCTURAL_PROVIDER_FINER`, `CARD_MANY_TO_ONE_ALLOWED`. Renamed: `PROPOSE_BUNDLE` → `PROPOSE_COMPOSED_OF`,
  `CARD_BUNDLE_EXTENDS_PROTECTED` → `CARD_EXTENDS_PROTECTED`. New: `PROPOSE_PART_OF`, `GRAN_PROVIDER_FINER`,
  `GRAN_PROVIDER_COARSER`, `SER_PARTS_SUM_STRONG`, `CARD_CLAIM_CONFLICTS_AUTO`, `CARD_LINK_TYPE_CONFLICTS_PROTECTED`,
  `STRUCTURAL_STORED_CLAIMS_INCONSISTENT`.
- Policy: `granularity.provider_finer` → `granularity.part_of` (`arbitration_bundle_check` → `arbitration_sum_check`).
- Decision/write/alternative records carry `link_type` (+ `set_id`); `resolution.link` states the asserted relationship.
  Corpus: `claim_conflict.*`, `resolve.provider-finer-*`, `resolve.parts-*`, `classify.part-of-*`.

### 3. Bundles are true link sets (was: independent PROPOSED rows)

- **Decision:** a `COMPOSED_OF` bundle is persisted as **one link set** — N atomic rows sharing a deterministic `set_id`
  and `set_size`. The write matrix runs once per set and every member row receives the same action; humans approve, reject
  or lock the set, never a member; an incomplete or mixed-state stored set is `STRUCTURAL_REVIEW`, never repaired.
  Claim identity (existing state, suppression, fingerprints) is `(subject, link_type, sorted targets)`.
- SPEC §10.5 is the storage contract (logical shape; no DDL, no migration is made here). The review-only alternative is
  recorded as a fallback decision in `adoption.yaml` / README, not implemented. Corpus: `resolve.link-set-*`, `fingerprint.link-set-*`.

### 4. Wording

- "exhaustive edge cases" → "complete for the known taxonomy classes and corpus-extensible" (SPEC §13, `taxonomy.yaml`
  header, README). The taxonomy gains `completeness: complete_for_known_classes_and_corpus_extensible`.

### 5. Adoption gate (uncalibrated proposal thresholds are not adopted)

- `adoption.yaml`: `binding: false`; every `proposal` / `assumption` value of `policy.yaml` belongs to exactly one entry
  (`calibration` | `representation` | `design_choice`) with status `pending` and what would settle it. Invariant **I16**: a run
  under a non-binding policy is a dry run (advisory writes, no persisted AUTO). `policy_ref.binding` is on every record.
- Cases whose expectation moves when a provisional value moves carry `provisional_keys` (generated by the single-key
  policy-mutation sweep). A test forbids `binding: true` while any entry is `pending`.

### Housekeeping

- Policy `revision: 2`, `status: draft_not_frozen`; `policy.version` stays `1.0.0` until the contract is frozen.
- Generated SPEC appendices regenerated (new Appendix D: provider capabilities, Appendix E: adoption gate); corpus rebuilt: 505 cases (was 424) in 15 kinds
  (new: `densify`, `claim_conflict`), 111 taxonomy entries (was 95), 104 reason codes (was ~96). `providers/base.py` now also checks capability data at the adapter boundary.
- Verification: contract tests 308 pass; single-key policy sweep 198 mutations, 196 caught + 2 equivalent; 26 structural mutation controls all caught (README §4).

## rev 1 — initial draft (2026-10-10)

Architecture, SPEC v1, policy v1, reason-code registry, taxonomy, schemas and the golden corpus, for owner review.
