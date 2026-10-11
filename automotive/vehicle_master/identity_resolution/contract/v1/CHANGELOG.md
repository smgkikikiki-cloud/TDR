# Contract v1 — change log

Contract v1 is a **draft and is not frozen**. Nothing reads it in production. Entries are newest first; each names the
files it touched and the corpus rows that pin the change (SPEC §14.4).

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
