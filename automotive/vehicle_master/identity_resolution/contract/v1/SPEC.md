# TDR Identity Resolution Contract — SPEC v1

**Status: DRAFT for owner review. Not in force. Nothing reads this contract in production.**
Companion files in this directory: `policy.yaml` (every tunable), `reason_codes.yaml` (the code registry),
`taxonomy.yaml` (the edge-case taxonomy as data), `record.schema.json` (engine input), `decision.schema.json`
(engine output), `case.schema.json` + `cases.jsonl` (the golden corpus), `../render.py` (generates the appendices below).

Keywords MUST, MUST NOT, SHOULD, MAY are used in their RFC 2119 sense.

---

## 0. Purpose, scope, ground rules

### 0.1 Purpose

Decide, for every identity published by an **external provider** (provider #1: Ice `model_group_id`), how it relates
to a **TDR canonical entity** (v1: `vehicle_models.canonical_id`) — and say *why*, with evidence a human can audit and a
machine can replay. The subsystem is permanent and provider-agnostic: Ice is an adapter (§3), not a dependency of the engine.

### 0.2 What the provider does and does not give us

Ice's package guidance (`สำหรับ_AI/tdr-package-import/SKILL.md` §3) covers **Ice-internal identity continuity**: `id_changes.csv`
says that one Ice `model_group_id` was renamed, merged or split into another. It does **not** give an Ice `model_group` →
TDR `canonical_model` mapping, and Ice does not ship its DLT raw-name table. **TDR owns the mapping policy.** This contract
is that policy.

### 0.3 Non-goals (v1)

- No production wiring, no database schema, no migration, no re-run of R6, no start of R7 (docs/market-track/ROADMAP.md).
- No engine implementation (the corpus is the executable specification the engine will be built against).
- No segment comparison (TDR owns its segment definitions — VEHICLE_DB_V3 §14.3).
- No model-code family rules (e.g. teaching the engine that `E300` belongs to `E-Class`). v1 reports these as `NO_CANDIDATE`
  and flags them for discovery; a family-rule extension is a future MINOR policy bump with its own corpus rows.
- No reverse coverage report (TDR models with no provider identity).

### 0.4 Ground rules (the architecture, as rules)

1. **Policy is data.** Every threshold, alias, allow-list, ordering and routing rule lives in `policy.yaml`. The engine MUST NOT
   carry its own copy of any of them. Each behaviour-bearing key in `policy.yaml` is pinned by at least one corpus case (§14.5).
2. **The engine is generic.** It consumes a *snapshot* (`record.schema.json`) and nothing else: no Ice column names, no
   Buddhist years, no `|` or `__provisional` string parsing, no Supabase client, no clock.
3. **Providers are adapters** (§3). All provider-specific meaning is converted before the engine sees it.
4. **Contract and engine are versioned apart.** `contract/v1` is immutable once adopted; changes ship as `v2` or as a policy
   version bump (§16).
5. **Every edge case is a corpus row, never a Python branch** (§14.4).

---

## 1. Vocabulary

| Term | Meaning |
|---|---|
| **Provider** | An external source of vehicle identities and evidence. v1: `ice`. |
| **Subject** | The provider-side identity being resolved (Ice: one `model_group`). |
| **Target** | A TDR-side canonical entity (v1: one `vehicle_models` row). |
| **Snapshot** | One consistent input: subjects, targets, existing mappings, lineage events, a source version, an `as_of_period`. |
| **Mapping** | A persisted link (subject, target) with a state (§10.1). Many targets may map to one subject; a target maps to at most one *active* subject. |
| **Candidate** | A target (or a *bundle* of 2–3 targets) the engine considers for a subject. |
| **Evidence tuple** | The brand, name, series, attribute, structure and margin evidence for one candidate (`decision.schema.json#/$defs/evidence`). |
| **Decision** | The engine's output for one subject (`record_type: resolution`). |
| **Structural operation** | A provider-lineage action (`record_type: structural_operation`). |
| **Refusal** | The engine declining to run (`record_type: refusal`). |
| **Observed / unobserved** | A series month with a number is observed (0 is a real zero); `null` is unobserved and is never read as zero. |
| **Common observation window** | The months both series observe (§6.2). |
| **Quarantine** | Withholding AUTO for a subject whose history a provider identity change restated (§9.4). |

---

## 2. Invariants

These hold for every conforming engine, whatever the policy says.

**Authority.** Evidence and decisions are ordered; a lower rung never silently overrides a higher one:

1. `HUMAN_LOCK` (state LOCKED) — 2. `HUMAN_APPROVED` (state APPROVED) — 3. `PROVIDER_STRUCTURE` (lineage events, §9) —
4. `HUMAN_REJECTED` (state REJECTED) — 5. `STATISTICAL_SERIES` (§6) — 6. `LEXICAL` (brand/name, §5) — 7. `ATTRIBUTE_ADVISORY` (body, lifecycle, §6.9).

- **I1 — AUTO is not APPROVED.** The engine emits `proposed_status ∈ {AUTO, PROPOSED, NONE}` only. `APPROVED`, `LOCKED` and `REJECTED` are human
  actions and appear only inside `existing_state`. AUTO is a *revocable machine link*: it is recomputed every run and demoted (§10) when
  it stops passing the AUTO gates.
- **I2 — Protected rows are never silently changed.** A mapping in state APPROVED or LOCKED is never created, updated, demoted, moved or
  deleted by an engine decision. The write matrix (§10.2) answers `BLOCK_REPORT`. Provider lineage may *carry* a protected mapping to
  a renamed identity only as a recorded lineage move, and only as `policy.lineage.protected` allows (§9.3). "Silently" means *without a record
  naming the reason codes, the prior state and the new state*.
- **I3 — Provider structure outranks statistics.** A statistical result can never create, move or delete what a lineage event established, and can
  never lift a quarantine (§9.4). The divergence is recorded (`AUTH_STRUCTURE_OVER_STATISTICS`), not obeyed.
- **I4 — The engine never zero-fills.** A month that is not observed is excluded from the comparison; it is never turned into 0 (§6.2).
- **I5 — Absence of data never excludes a candidate.** Only affirmative evidence (§8.1) excludes. Insufficient evidence yields
  `INSUFFICIENT_DATA`, not `NO_CANDIDATE`.
- **I6 — Name alone is never AUTO.** (VEHICLE_DB_V3 §14.2.)
- **I7 — A strong series never rescues a contradicting name.** (`policy.lexical.series_only`.)
- **I8 — Determinism.** The output is a pure function of (snapshot, policy). No wall clock, no randomness, no network, no dependence on input
  list order. Output lists are sorted (§12.2). Re-running on identical input yields byte-identical records.
- **I9 — Idempotence.** Applying the same snapshot twice (or a lineage event already recorded in `applied_event_keys`) changes nothing.
- **I10 — Every record is explainable.** A resolution carries exactly one `primary` reason code, whose registry entry lists the outcome in
  `primary_for`; every code used exists in `reason_codes.yaml`; every role used is allowed for that code.
- **I11 — A strong-but-not-AUTO decision names its blocker.** `PROPOSE_SERIES_STRONG_CAPPED` carries at least one `blocking` code; `AUTO_ALL_GATES_PASSED`
  carries none.
- **I12 — One target, one active subject.** At most one subject holds a given target in an *active* state (AUTO, APPROVED, LOCKED) at a time. The reverse
  (one subject, several targets) is allowed. Contested claims are resolved by §7.5, never by arbitration order.
- **I13 — Provider data is never edited.** The engine does not recompute or correct provider numbers (`SKILL.md` §5).
- **I14 — Time is Gregorian ISO `YYYY-MM` inside the engine.** Adapters convert; the engine refuses an impossible year (§4.3).
- **I15 — Ties break on ids.** Where an output list needs an order, ties break on `target_id` / `entity_id` ascending (byte order).

---

## 3. Provider adapters

An adapter turns one provider package into a `snapshot`. It contains no matching logic. Every obligation below is a MUST; the Ice
specifics are in `README.md`.

| # | Obligation |
|---|---|
| A1 | Convert every period to Gregorian ISO `YYYY-MM` exactly once (Ice: Buddhist year − 543). |
| A2 | Produce dense series (`start`, `counts`). **Zero-fill only inside the source's own declared coverage**, and only where the provider semantics say an absent row is a true zero (Ice: `reg_trend` ships no zero rows — 0 of 262,985 rows have a count ≤ 0 — so an absent row inside `reg_range` is read as 0; this interpretation is to be confirmed by Ice). Outside the declared coverage emit `null`. If coverage cannot be stated, set `coverage_declared: false`. |
| A3 | Flag partial periods (`partial_periods`) whenever the source knows a month is incomplete. |
| A4 | Map the provider's identity forms to `identity_status`: `settled`, `provisional`, `unmapped_name` (Ice: normal id / `…__provisional` / `BRAND\|MODEL`). The engine never parses ids. |
| A5 | Provide the subject's primary `brand` and every brand the provider observed for it (`brands_observed`; Ice: distinct `reg_trend.brand` values). |
| A6 | Provide `display_name` verbatim (Ice `model_name`; it is **not** a key). Provide `attributes.body` verbatim, `null` when absent. |
| A7 | Translate provider identity changes to `lineage_event`s (Ice: เปลี่ยนรหัส → RENAME, รวม → MERGE, แยก → SPLIT) and supply `share_of_old_pct` as given. Ice states that this figure is *for ordering and successor choice only, never an official number*. If the provider names a successor outright, set `successor_id`. |
| A8 | Set `lineage.source_present` truthfully and `lineage.declared_identity_change` whenever the provider's own change log declares an identity change (Ice: a CHANGELOG row with `entity = crosswalk`). Never infer events from prose. |
| A9 | Set `source_version.label` to a stable, human-traceable label (Ice: `ice:2569-09:v3:M7.0`) and fill `attributes` with the provider's own fields. |
| A10 | Provide the TDR side the same way: targets with brand, display name, status, body type, generation lifetimes and (optionally) a registrations series with its coverage. A target with no registrations has no `series`. |
| A11 | Never alter a number, deduplicate a row, or drop an identity to make validation pass. |

---

## 4. Input and output contracts

### 4.1 Input

`record.schema.json#/$defs/snapshot`. The engine MUST refuse (a `refusal` record, §4.3) rather than guess when the snapshot is malformed.

### 4.2 Output

`decision.schema.json`. Exactly one of `resolution`, `structural_operation`, `refusal`. A resolution contains: contract and policy version
(+ policy digest, §11.3), provider, `source_version`, subject, `outcome`, `proposed_status`, `method`, `target.ids`, `reason_codes`,
the **evidence tuple**, the **comparison** (exactly which months were used and why others were not), `existing_state`, `alternatives`, `review`, `writes`
and two **fingerprints** (§11).

### 4.3 Refusals

A refusal means "no decisions were emitted for this run": `INPUT_SOURCE_VERSION_MISSING`, `INPUT_DUPLICATE_SUBJECT_ID`, `INPUT_PERIOD_CALENDAR_INVALID`
(a period year outside `time.valid_year_range`, typically a Buddhist year that escaped the adapter), `INPUT_NEGATIVE_COUNT`,
`INPUT_POLICY_VERSION_UNSUPPORTED`, and `LIN_SOURCE_MISSING` (§9.1). A refusal is not an outcome; it never writes anything.

---

## 5. Lexical evidence: brand and name

### 5.1 Brand relation

1. A brand's **compact key** is its NFKC, case-folded form with every character that is not a letter, digit or Thai character removed
   (`MERCEDES BENZ`, `Mercedes-Benz`, `MercedesBenz` → `mercedesbenz`; `ZX AUTO` = `ZXAUTO`).
2. `aliases.brand` lists alias classes. A compact key belongs to **at most one SAME/RELABEL class** (a class id and a brand key live in different
   namespaces — an engine MUST NOT let a class id equal a brand key). `SAME` = spelling variants of one marque; `RELABEL` = one marque sold under two labels;
   `RELATED` = parent/child/joint-venture, not equivalent. RELATED classes are evaluated *between* SAME/RELABEL classes: each member is first mapped to its
   SAME/RELABEL class if it has one.
3. The relation between a subject brand `s` and a target brand `t` is the first that applies:
   `UNKNOWN` (either side blank, or a value in `lexical.unavailable_name_values`) → `EXACT` (equal compact keys) → `ALIAS_SAME` / `ALIAS_RELABEL`
   (same SAME/RELABEL class) → `ALIAS_RELATED` (both map into one RELATED class) → `MISMATCH`.
4. A subject may carry several brands (`brands_observed`). The relation is the **best** across `brand` and `brands_observed`
   (EXACT > ALIAS_SAME > ALIAS_RELABEL > ALIAS_RELATED > MISMATCH). Multi-brand subjects get `SUBJ_MULTI_BRAND`.
5. Only `candidates.brand_relations_auto_eligible` relations may be AUTO; `ALIAS_RELATED` is capped at PROPOSED (`BRND_ALIAS_RELATED`).
6. `BRND_MISMATCH` is recorded (info) when a target of an *unrelated* brand has a candidate-grade name relation to the subject — a false friend that brand
   matching correctly refused (e.g. a Toyota "City" for Honda "City"). It never creates a candidate.

### 5.2 Name tokens

`name_tokens(name, brand)`:

1. NFKC, case-fold. Replace every character in `lexical.token_boundary_characters` (and whitespace) by a space; **delete** every other character that is not a letter, digit or
   Thai character (`e:N1` → `en1`, `3.0` → `3 0`). No transliteration of Thai.
2. Split on spaces.
3. **Strip a brand prefix, token-wise.** Take the spellings of the brand (the brand string plus every member of its SAME/RELABEL class; when comparing two names, the
   union of both sides' spellings and the subject's observed brands), tokenize each the same way, and remove the **longest** spelling that is an exact leading
   token sequence — only if at least one token remains. Never strip characters: `MG4 EV` keeps `mg4`; `MINI` is not stripped to nothing.
4. Drop tokens in `lexical.generic_tokens` (`series`, `class`).
5. The name is **unavailable** if no token remains or its compact form is in `lexical.unavailable_name_values` (`ไม่ระบุ`, `unknown`, `n/a`).

### 5.3 Name relation

For subject tokens `A` and target tokens `B` (both available), the relation is the first that applies:

1. `EQUAL` — the compact forms (tokens concatenated) are equal. (`D-Max` = `DMAX` = `D Max`.)
2. `EQUAL_VIA_MODEL_ALIAS` — equal through a pair in `aliases.model` whose `brand_alias_ids` contains the alias id of the brand relation (§5.4).
3. `EQUAL_VIA_TOKEN_EQUIV` — equal after mapping each token to the first member of its group in `lexical.token_equivalences` (`ev`/`electric`).
4. `FUZZY` — `lexical.fuzzy_token.enabled`, and every token that differs is paired with a differing token of the other side, each of length ≥
   `min_token_length`, at edit distance exactly one. Tokens shorter than that get no tolerance.
5. `SUBJECT_COARSER` — `A` is a proper subset of `B` (the subject is the broader nameplate: Ice `Hilux Travo` vs TDR `Hilux Travo Cab`).
6. `SUBJECT_FINER` — `A` is a proper superset of `B` (Ice `City Hatchback` vs TDR `City`).
7. `SIBLING` — `A` and `B` share at least one token and each has a token the other lacks (`Hilux Revo` / `Hilux Travo`).
8. `CONTRADICTION` — `A` and `B` share no token (`D-Max` / `MU-X`, `3 Series` / `X3`).
9. `UNAVAILABLE` — either name is unavailable.

**Score.** The Sørensen–Dice coefficient over the token sets (equivalence-mapped, fuzzy-paired tokens counted as matches): `2·|A∩B| / (|A|+|B|)`, quantized (§6.7). Every
`EQUAL*` relation scores `1.0`. The score is informational and feeds the evidence-fingerprint bands; **the relation drives decisions.** (VEHICLE_DB_V3 §14.2's
"name ≥ 0.8" is satisfied by construction: AUTO requires an `EQUAL*` relation, which scores 1.0. The legacy character-ratio metric is retired — see §15.)

**Roles.** `auto_relations` may be AUTO; `candidate_relations` may carry a name-only PROPOSE; `veto_relations` (`SIBLING`, `CONTRADICTION`) exclude the candidate; `SUBJECT_COARSER`
and `SUBJECT_FINER` are *granularity* relations: never AUTO, never a name-only candidate, but a strong series still makes them PROPOSE candidates, and they feed bundles (§7.3)
and provider-finer detection (§7.4).

### 5.4 Scoped model aliases

An `aliases.model` entry is an explicit pair `[subject name, target name]`, matched on normalized tokens in either orientation, valid only when the brand relation
is an alias relation whose alias id is in the entry's `brand_alias_ids`. It exists for cases like Ice `9` (brand MG Maxus) ↔ TDR `Mifa 9` (brand MAXUS). It is never a general fuzzy rule.

### 5.5 Unspecified names

A subject whose name is unavailable (e.g. `ISUZU|ไม่ระบุ`, 12,508 lifetime units) has **no name evidence**: it can be PROPOSED on a strong series alone, never AUTO (`NAME_UNAVAILABLE`
is then a `blocking` code), and never by name.

---

## 6. Series and attribute evidence

### 6.1 Input semantics

A series is dense: `counts[i]` is the month `start + i`. `0` = observed zero. `null` = **unobserved**. `partial_periods` lists months the source flags incomplete.
`coverage_declared: false` means the source cannot say what it covers.

### 6.2 The common observation window

Inputs: subject series `S`, target series `T` (or the sum of a bundle, §6.8), `series.window.*`.

1. If either series is absent → unavailable, `SER_NO_COMMON_WINDOW`. If either has `coverage_declared: false` → unavailable, `SER_COVERAGE_UNDECLARED`.
2. Coverage of a series = the months its array spans. If the two coverages differ, record `SER_COVERAGE_ASYMMETRIC` (info). **Only months inside both coverages can be compared.**
3. If `series.window.exclude_partial_periods`, a month flagged partial by *either* source is excluded from both (`SER_PARTIAL_PERIOD_EXCLUDED`).
4. A month inside both coverages that is `null` on either side is excluded (`SER_UNOBSERVED_NOT_ZERO`, info). It is **not** zero.
5. The remaining months, sorted, are the **common observation months** `C`. If `C` is empty → unavailable, `SER_NO_COMMON_WINDOW`.
6. **Trim.** If `series.window.trim_inactive_edges`: drop leading and trailing months where **both** series are 0 (`SER_WINDOW_TRIMMED_INACTIVE`). If nothing remains → unavailable, `SER_ZERO_TOTAL`.
7. **Anchor and cap.** The anchor is the **last month of the trimmed `C`** — the newest month *both* series observe — not the provider's newest month. Keep the months of `C`
   within `series.window.max_months` of the anchor (the `max_months` calendar months ending at the anchor). Older common months are excluded `outside_max_window`.

The legacy matcher windows on the provider's newest 24 months and zero-fills what the TDR side lacks (`build_paired_series`); that *manufactures* evidence and is exactly what §6.2 forbids.

### 6.3 Statistics

Over the kept months `P` (n = |P|), with `x` = subject counts and `y` = target counts: `subject_units = Σx`, `target_units = Σy`, `joint_nonzero_months = #{x>0 ∧ y>0}`,
`ratio = Σy / Σx` (target over subject), `correlation` = Pearson, `monthly_fit_share` = the share of months with `|y − x| ≤ max(abs_tolerance_units, rel_tolerance·x)`.

### 6.4 Usability, in this order (the first that applies makes the series unavailable)

`SER_ZERO_TOTAL` (Σx = 0) → `SER_OVERLAP_BELOW_PROPOSE_MIN` (n or joint months below `series.minimums.propose`) → `SER_VOLUME_BELOW_PROPOSE_MIN` (either side's units below it) →
`SER_ZERO_VARIANCE` (either side constant). An unavailable series reports `correlation`, `ratio` and `monthly_fit_share` as `null`.

### 6.5 The strong gate

All comparisons use **quantized** values (§6.7), bounds inclusive: `correlation ≥ series.strong.correlation_min`, `ratio_min ≤ ratio ≤ ratio_max`, `monthly_fit_share ≥ monthly_fit.min_share_of_months`
→ `STRONG` (`SER_STRONG`); otherwise `WEAK`. Failure codes: `SER_CORRELATION_BELOW_STRONG`, `SER_RATIO_OUT_OF_BAND`, and `SER_MONTHLY_FIT_FAIL` **only when correlation and ratio both pass** (it
exists to catch a correlation driven by one outlier month). A usable series below `series.minimums.auto` additionally carries `SER_OVERLAP_BELOW_AUTO_MIN` / `SER_VOLUME_BELOW_AUTO_MIN` (blocking).

### 6.6 What the gate is not

A high correlation with a wrong ratio is never strong (`D-Max`/`MU-X` share seasonality). Equal totals with an unrelated profile are never strong. A single huge month cannot carry a series.

### 6.7 Quantization

Every correlation, ratio, share and score is rounded **half-even on the shortest-repr decimal expansion** to `quantization.places` (6) before it is compared with a threshold, stored in the
evidence tuple, or hashed. `0.9799996` is `0.980000` and passes; `0.9799994` is `0.979999` and fails.

### 6.8 Bundles

The series of a bundle is the sum of its members' series over the months all members observe (a `null` in any member makes that month unobserved). Everything in §6.2–6.5 applies to the sum.

### 6.9 Attribute evidence (advisory: it can cap, never confirm)

1. **Body.** `MISMATCH` only when the provider's label is in `attributes.body.compatibility`, the target has a body type other than `OTHER`/unset, and the target's type is not in the label's compatible set.
   Everything else is `UNKNOWN` (`ATTR_BODY_UNKNOWN`; 649 of 1,200 M7.0 groups have a blank body). A mismatch caps AUTO (`ATTR_BODY_MISMATCH`).
2. **Lifecycle (generation mismatch).** With the target's generations (each `launched`/`ended`, either may be open): a month is *inside* if some generation covers it, widened by
   `attributes.lifecycle.grace_months` on both ends (an open end is unbounded). `share` = the subject's units in inside months ÷ all its units (over its whole series, not only the common window).
   `WITHIN` if share ≥ `within_min_share`; `DISJOINT` if share < `disjoint_max_share` (the target is **excluded**, `GEN_LIFECYCLE_DISJOINT`); otherwise `PARTIAL` (caps AUTO, `GEN_LIFECYCLE_PARTIAL`).
   No generations, no series or zero units → `UNKNOWN` (`GEN_LIFECYCLE_UNKNOWN`, no effect).
3. **Target status.** A status in `attributes.target_status.cap_proposed` caps AUTO (`ATTR_TARGET_UNVERIFIED`). Statuses in `candidates.target_statuses_in_pool` are in the pool.
4. A bundle takes the worst member value of each attribute.

### 6.10 The evidence tuple

`{brand, name, series, attributes, structure, margin}` — every member present, `null` where it could not be computed. `margin` carries the runner-up ids and the two deltas (§8.3) when a runner-up exists.

---

## 7. Candidates

### 7.1 Subject quality

- `identity_status ∈ subject_quality.never_auto_identity_statuses` (`provisional`, `unmapped_name`) → never AUTO (`SUBJ_PROVISIONAL`, `SUBJ_UNMAPPED_NAME`, blocking).
- An unavailable name → `SUBJ_UNSPECIFIED_NAME` (info) and no name evidence.
- Another subject in the snapshot with the same display name → `SUBJ_DUPLICATE_DISPLAY_NAME` (info). The display name is never used to identify the subject.

### 7.2 The pool

The pool is every target whose brand relation is in `candidates.brand_relations_allowed`, whose status is in `candidates.target_statuses_in_pool`, and (if `exclude_deleted_targets`)
not deleted. An unusable subject brand → `NO_CANDIDATE` with primary `BRND_UNKNOWN`; no TDR brand relates → `BRND_NOT_IN_TDR`; a related TDR brand exists but nothing is eligible → `NO_CANDIDATE_EMPTY_POOL`.

### 7.3 Bundles (many TDR models → one subject)

If **no single candidate is `STRONG`** and `candidates.bundle.enabled`: take the pool targets whose name relation is in `candidates.bundle.member_name_relations`, ordered by `target_id`,
truncated to `max_pool_for_enumeration`; enumerate combinations of 2…`max_members`; a combination whose summed series (§6.8) is `STRONG` becomes a candidate. A bundle is **never AUTO**; it is `PROPOSE` with
`PROPOSE_BUNDLE`, `SER_BUNDLE_STRONG` and `CARD_MANY_TO_ONE_ALLOWED`. A combination whose ratio exceeds the band is `SER_BUNDLE_OVERSHOOT` and is excluded. The search is bounded and deterministic;
a split wider than `max_members` is out of v1 scope and surfaces as `NO_CANDIDATE`/`INSUFFICIENT_DATA` with a discovery flag.

This is the only way the engine can discover `hilux_travo_cab + hilux_travo_double_cab → toyota-hilux-travo`: each part alone has a ratio near 0.5.

### 7.4 Provider finer than TDR

The provider splits what TDR holds as one model (`honda-city` + `honda-city-hatchback` vs a single TDR `City`). VEHICLE_DB_V3 §14.2 allows a target at most one active subject, so this cannot be a mapping.

- **Single-subject rule.** A candidate whose name relation is in `granularity.provider_finer.subject_name_relations` (`SUBJECT_FINER`), with a usable series and `ratio > min_ratio_above` (the target is clearly bigger), is *provider-finer*.
- **Sum rule** (arbitration, §8.6). If `arbitration_bundle_check`, ≥ 2 subjects that each relate to one target by `EQUAL*` or `SUBJECT_FINER`, whose **summed** series against that target is `STRONG`, are all provider-finer.
- A provider-finer subject with no `STRONG` single candidate is `STRUCTURAL_REVIEW` / `STRUCTURAL_PROVIDER_FINER`. Nothing is forced onto one group; the owner decides whether TDR should split the model.

### 7.5 Cardinality and contested targets

- A target that another subject holds **APPROVED/LOCKED** is excluded (`CARD_TARGET_ACTIVE_ELSEWHERE`). If the subject would otherwise be AUTO-eligible against it (strong series, `auto_relations`, auto-eligible brand), the result is not silence but
  `STRUCTURAL_REVIEW` / `STRUCTURAL_APPROVED_CLAIM_CONFLICT`, high priority: either the approved mapping or the new subject is wrong, and a human decides. Nothing is changed.
- A target held only by an **AUTO** row is not a veto; it is *contested* at arbitration (§8.6).
- A target missing or deleted while an APPROVED/LOCKED mapping points at it → `CARD_TARGET_MISSING` (blocking), the mapping untouched, high-priority structure review.
- A subject that already holds a protected mapping may gain another target only as `PROPOSED` (`CARD_BUNDLE_EXTENDS_PROTECTED`).

---

## 8. Decision

### 8.1 Per-candidate flags

For each candidate (a target or a bundle):

- **Excluded** (affirmative evidence), recording every code that applies: name relation in `veto_relations` (unless `series_only.allow_with_name_veto` and the series is `STRONG`) → `NAME_SIBLING_VARIANT` / `NAME_CONTRADICTION`;
  lifecycle `DISJOINT`; bundle overshoot; held APPROVED/LOCKED by another subject; or **series decisively wrong** — series usable and `WEAK`, the name relation not in `candidate_relations`, the candidate not provider-finer, and
  `correlation < data_sufficiency.series_decisively_wrong.correlation_below` or `ratio` outside `ratio_outside` (inclusive).
- **Suppressed**: the pair's existing state is `REJECTED` and its stored evidence fingerprint equals the newly computed one (§11.2). Suppressed is not excluded; it is remembered.
- **Proposable** = not excluded, not suppressed, and (series `STRONG` or name relation in `candidate_relations`).
- **AUTO-eligible** = proposable ∧ brand relation in `brand_relations_auto_eligible` ∧ series `STRONG` ∧ name relation in `auto_relations` ∧ series meets `series.minimums.auto` ∧ body ≠ `MISMATCH` ∧ lifecycle ∈ {`WITHIN`,`UNKNOWN`} ∧
  target status ∉ `cap_proposed` ∧ subject identity status ∉ `never_auto_identity_statuses` ∧ not quarantined ∧ not extending a protected subject ∧ not a bundle ∧ pair state ≠ `REJECTED`.
- **Blocking codes** of a proposable, non-AUTO candidate: every gate above that failed, as the registry's `blocking` codes.

### 8.2 Outcome, in this order

1. The subject has an APPROVED/LOCKED mapping → `PROTECTED_HOLD` (§10.3).
2. No candidates → `NO_CANDIDATE` (primary per §7.2).
3. Some non-excluded, non-suppressed candidate is provider-finer and no proposable candidate is `STRONG` → `STRUCTURAL_REVIEW` / `STRUCTURAL_PROVIDER_FINER`.
4. No proposable candidate:
   a. a protected-claim candidate (§7.5) → `STRUCTURAL_REVIEW` / `STRUCTURAL_APPROVED_CLAIM_CONFLICT`;
   b. only suppressed candidates remain → `SUPPRESSED` / `SUPPRESSED_REJECTED_UNCHANGED`;
   c. at least one candidate survives (not excluded, not suppressed) → `INSUFFICIENT_DATA` / `INSUFFICIENT_DATA_NO_BASIS` — the reason codes of the best survivor's series are attached;
   d. otherwise → `NO_CANDIDATE` / `NO_CANDIDATE_ALL_EXCLUDED`, with the exclusion codes attached.
5. Otherwise rank (§8.3). A tie at the top → `AMBIGUOUS` / `AMBIGUOUS_CANDIDATES_WITHIN_MARGIN`. Else the best is `AUTO` (`AUTO_ALL_GATES_PASSED`) if AUTO-eligible, else `PROPOSE`:
   `PROPOSE_BUNDLE` for a bundle, `PROPOSE_SERIES_STRONG_CAPPED` when the series is `STRONG`, `PROPOSE_NAME_MATCH_SERIES_NOT_STRONG` otherwise (method `NAME`).
6. Arbitration across subjects (§8.6).

### 8.3 Ranking and margin

Candidates are ordered lexicographically by `candidates.ranking.tier_order`: AUTO-eligible first; then series state (`series_state_order`); lifecycle (`lifecycle_order`); name relation (`name_relation_order`); smaller `|ln ratio|`;
larger correlation; finally `target_id` ascending (ordering only — see I15). **Raw scores of different kinds are never compared** (a correlation is not a name score).

Two candidates **tie** if their (AUTO-eligible, series state, lifecycle, name relation) are equal and, when both have a usable series, `|Δcorrelation| < margin.correlation_delta_min` **and**
`| |ln ratio₁| − |ln ratio₂| | < margin.abs_ln_ratio_delta_min`. A tie at the top is `AMBIGUOUS`: nothing is auto-linked, every tied candidate is listed in `alternatives`, and each is written as a `PROPOSED` candidate row.
Two TDR models that normalize to one nameplate (`GEN_SAME_NAMEPLATE_MULTI_TARGET`, info) separate only through lifecycle.

### 8.4 AUTO

AUTO is the conjunction in §8.1. It is a machine link that the next run may withdraw. It never means approved (I1).

### 8.5 Review routing

`review.queue` starts at `review.routing[outcome]` and `required` is true unless the queue is `none`. Refinements: a `NO_CANDIDATE` subject (other than `BRND_UNKNOWN`) with ≥ `subject_quality.discovery.catalog_gap_min_units` units gets
`DISCOVERY_CATALOG_GAP` and queue `discovery`; a `NO_CANDIDATE`/`INSUFFICIENT_DATA` subject carrying a `review.discovery_subject_flags` code with ≥ `provisional_min_units` units goes to `discovery`; a `PROTECTED_HOLD` whose evidence contradicts
or whose target is missing goes to `structure_review`. `priority` is `high` iff the record carries a code in `review.high_priority_codes`. `question` SHOULD be a short templated sentence for `STRUCTURAL_REVIEW` and `AMBIGUOUS`.

### 8.6 Arbitration (cross-subject)

Run after every subject is decided, on the final per-subject results:

1. **Provider-finer by sum** (§7.4): applied first.
2. **Contested AUTO**: if ≥ 2 subjects are `AUTO` on the same target, none is. Each becomes `AMBIGUOUS` / `AMBIGUOUS_TARGET_CONTESTED`. The outcome depends on the set of subjects, never on iteration order.

### 8.7 Reason-code roles

Exactly one `primary` (§I10). `blocking` codes explain what held a candidate below a stronger outcome; `supporting` codes are evidence in favour; `info` is context. A code may only take roles its registry entry lists.

---

## 9. Provider structure (lineage)

Lineage is processed **before** any matching, against the pre-change state, and all events are read **simultaneously** (never chained).

### 9.1 Source

If `lineage.declared_identity_change` and not `lineage.source_present` → refuse with `LIN_SOURCE_MISSING` (the M6.0 trial declared crosswalk-type changes without `id_changes.csv`). Nothing is inferred from prose.

### 9.2 Events and operations

| Event | Old id retired (absent from the snapshot)? | Operations |
|---|---|---|
| RENAME / MERGE | yes (if the old id is still live Ice leaves this undefined; v1 produces no operation for it and records it as an open question) | `REDIRECT old→new` (`LIN_RENAME_FOLLOWED` / `LIN_MERGE_FOLLOWED`), then `MOVE_MAPPINGS old→new` for the rows §9.3 allows |
| SPLIT, old id **live** | no | `NOOP` (`LIN_SPLIT_PARENT_RETAINED`), no redirect; quarantine parent and child; `FLAG_MAPPING_REVIEW` for the parent's active mappings (`LIN_PARENT_MAPPING_REVIEW`); a `CANDIDATE_HINT` STRUCTURE card (§9.5) |
| SPLIT, old id **retired**, several successors | yes | `REDIRECT old→successor` where successor is the provider's explicit `successor_id`, else the largest `share_of_old_pct`, ties broken by `new_id` ascending (`LIN_REDIRECT_RETIRED_SPLIT`, `LIN_TIE_BREAK_ID_ASC`); mappings are **not** moved — they are flagged for review |

Ice's published rule for retired split parents is exactly this ("redirect to the new id with the highest `share_of_old_pct`; ties: `new_model_group_id` ascending; if the old id is still in dims, keep it, no redirect").
In M7.0 it applies to three ids: `mercedes-benz-mercedes-benz-amg-g` (6 successors), `…-amg-cls` (6) and `toyota-toyota-gr` (3).

**Guards.** An id that is both old and new in the batch is fine: every event is read against the pre-change snapshot, none is chained (`LIN_NO_CHAIN`; M7.0: `mini-mini-cooper-ev`, `mini-mini-jcw-rhd`, `mini-mini-jcw-convertible`). A redirect
whose target is not live is an `ERROR` operation (`LIN_TARGET_NOT_LIVE`) — a live id is never found by chasing redirects. Retired ids that redirect into each other are an `ERROR` (`LIN_CYCLE_NO_REDIRECT`); mutual splits between *live* ids are legal.
An event whose key (`TYPE:old>new`) is in `applied_event_keys` is a `NOOP` (`LIN_ALREADY_APPLIED`; I9). A retired id ending `__provisional` is additionally recorded `LIN_PROVISIONAL_PROMOTED`.

### 9.3 Mappings of a retired id

For RENAME/MERGE each row under the old id is moved to the new id as a recorded lineage move, unless it needs the owner: `policy.lineage.protected.approved` and `.locked` are `follow_with_lineage` (move, `LIN_PROTECTED_FOLLOWED_WITH_LINEAGE` for APPROVED)
or `require_owner_ack` (a `FLAG_MAPPING_REVIEW` with `LIN_PROTECTED_NEEDS_OWNER_ACK`, `requires_owner_ack: true`, nothing moves). Defaults: APPROVED follows, LOCKED waits. A move that would give one target two active subjects stays
put and is flagged (`LIN_MOVE_TARGET_CONFLICT`). REJECTED rows follow the identity (a rejection is a fact about the pair).

### 9.4 Quarantine

`policy.lineage.quarantine` decides which subjects a snapshot's events quarantine (split parents and children, merge targets; rename targets are off by default). A quarantined subject cannot be AUTO in the snapshot in which the event is first applied
(`LIN_EVIDENCE_QUARANTINE`, blocking; with a strong series also `AUTH_STRUCTURE_OVER_STATISTICS`). Once the event key is in `applied_event_keys` the quarantine ends. Rationale: Ice's replace-whole-set import already contains the restated history
(e.g. the DLT name `COROLLA` moved between `toyota-corolla-cross` and `toyota-corolla-altis`), while TDR's own registrations are attributed by TDR's resolution — the two series legitimately disagree until the owner reviews the pair.

### 9.5 STRUCTURE cards replace copied rows

VEHICLE_DB_V3 §14.2 asks for a "STRUCTURE card" when a split happens. v63 implements it by copying the parent's TDR target onto the child as a `PROPOSED` row with `match_method = 'ADMIN'`. Such a row is wrong whenever the parent's target is a different
model (copying `toyota_corolla_cross` onto `toyota-corolla-altis`). v1 raises the **question** instead (`CANDIDATE_HINT`, `LIN_SPLIT_CHILD_INHERITED_CANDIDATE`): it carries the parent's target ids for the reviewer and creates no mapping row.
The child is resolved on its own evidence (quarantined). `policy.lineage.split_child_structure_card` switches the card off.

---

## 10. State and write planning

### 10.1 States

A (subject, target) pair is `NONE` (no row), `PROPOSED`, `AUTO`, `APPROVED`, `LOCKED` or `REJECTED`. `APPROVED`, `LOCKED` and `REJECTED` are human decisions. The v63 table has no `LOCKED`; its de-facto lock is `match_method = 'ADMIN'`
(see README "Compatibility").

### 10.2 The write matrix

`policy.state.write_matrix[existing pair state][engine decision for that pair]` → action. The decision is `AUTO`, `PROPOSE`, or `ABSENT` (the engine no longer produces the pair). `REJECTED` additionally keys on whether the evidence fingerprint moved.
The matrix is complete (every cell decided) and pinned by one corpus case per cell. Highlights: AUTO×PROPOSE → `DEMOTE_TO_PROPOSED` (`STATE_AUTO_DEMOTED`); PROPOSED×ABSENT → `MARK_STALE` (`STATE_CANDIDATE_STALE`, never deleted);
APPROVED/LOCKED×anything → `BLOCK_REPORT`; REJECTED×{AUTO,PROPOSE}: unchanged evidence → `SUPPRESS`, changed → `REOPEN_AS_PROPOSED` — **never straight to AUTO** (`STATE_REJECTED_REOPENED`, blocking).

### 10.3 Protected subjects

If the subject holds an APPROVED/LOCKED mapping the outcome is `PROTECTED_HOLD` (`PROTECTED_HOLD_APPROVED` / `_LOCKED`) with `AUTH_HUMAN_OVER_ENGINE`. The engine still measures the protected pair: `STATE_EVIDENCE_CONFIRMS` if its series is `STRONG`;
`STATE_EVIDENCE_CONTRADICTS` if `WEAK` with correlation below `data_sufficiency.series_decisively_wrong.correlation_below` or ratio outside `ratio_outside` — reported, high priority, never applied; otherwise inconclusive. Additional proposable targets are listed as `PROPOSED` alternatives (`CARD_BUNDLE_EXTENDS_PROTECTED`).

### 10.4 Candidate rows change; mappings do not

Candidate and evidence rows MAY change on every run (refresh, promote, demote, mark stale). Protected rows MUST NOT (I2). The DB-level RPC remains the last line of defence and is never relaxed to suit the engine.

---

## 11. Fingerprints

### 11.1 Canonical form

Canonical JSON: UTF-8, keys sorted, separators `,` and `:`, no whitespace, `ensure_ascii = false`, **no floats anywhere** (any non-integer quantity is a quantized decimal *string*, §6.7). A float in a payload is an error (`float_in_payload`).
`fingerprint = sha256(canonical_json(payload))`, lowercase hex.

### 11.2 Two fingerprints

- **`fingerprints.decision`** — provenance of *this exact decision*: contract version, policy version and digest, provider, `source_version.label`, subject, outcome, status, method, sorted `target_ids`, sorted unique `reason_codes`, the quantized evidence
  tuple and the comparison periods (`payload.v = "decision-fp/1"`). Re-running on identical input reproduces it byte for byte.
- **`fingerprints.evidence`** — the **suppression key** for REJECTED pairs (`payload.v = "evidence-fp/1"`): contract version, provider, subject, sorted `target_ids`, and the **bands** of the evidence — brand relation, name relation, name-score band, series state, correlation band,
  ratio band, common-months band, body, lifecycle, target status — plus the structure block (quarantine flag and sorted lineage event keys). Band labels follow `fingerprint.bands` (lower-inclusive: `"<e0"`, `"[e0,e1)"`, …, `">=e_last"`; an unavailable series uses the label `"n/a"` for correlation and ratio).
  It contains **no period list and no source version**, so a rolling window or a new package alone cannot un-suppress a rejection, while a genuine change (a band crossed, the series state flipped, a quarantine) does.

The legacy `decision_fingerprint` embeds `master_version`, so it changes with every package and a REJECTED row is re-proposed every time; that is the defect §11.2 removes.

### 11.3 Policy digest

`policy.digest` = sha256 of `policy.yaml`'s UTF-8 bytes with LF line endings. Any edit to the file changes every decision fingerprint; changing the file without bumping `policy.version` is detectable.

---

## 12. Output

### 12.1 Records

One `resolution` per subject (sorted by `entity_id`), then the `structural_operation`s (sorted by `op`, `old_id`, `new_id`), or a single `refusal`. For a `QUARANTINE` operation `old_id` is the quarantined subject and `new_id` is `null`; its
`event_type` is the type of the (first) event that caused it. `authority` is always `PROVIDER_STRUCTURE`.

### 12.2 Ordering

Every list in an output is sorted: reason codes by (role order primary, blocking, supporting, info; then code), `target.ids`, `alternatives` by `target_ids`, `writes` by `target_id`.

### 12.3 Properties every conforming engine MUST satisfy (executed for every `resolve` case)

- **Order independence:** shuffling subjects, targets, mappings and events yields identical records.
- **Idempotence:** feeding the engine's own persisted outcome (as `existing_mappings`) back in changes no decision except as the write matrix prescribes (an AUTO row that still passes is `REFRESH_EVIDENCE`).
- **Schema conformance:** every record validates against `decision.schema.json`.
- **Registry conformance:** I10 and I11.

---

## 13. Edge-case taxonomy

`taxonomy.yaml` is the exhaustive list (Appendix C), grouped into baseline outcomes, subject quality, brand, name, series, granularity, cardinality, lineage, state, authority, fingerprints and input integrity — each entry with its origin
(`owner_report_r6`, `ice_m7_data`, `design`), the evidence it rests on, the contract's handling and the reason codes involved. The contract commits to handling every entry; a test enforces that each is exercised by the corpus.

---

## 14. The golden corpus

### 14.1 Shape

`cases.jsonl`: one JSON object per line (`case.schema.json`). `kind` selects the layer under test:

| Kind | Layer | Input → Expect |
|---|---|---|
| `resolve` | end to end | snapshot → per-subject decision expectations (+ operations, or a refusal) |
| `classify` | decision core | a pre-computed evidence tuple per candidate → decision expectation |
| `window` | §6.2–6.5 | two series → common window, excluded months, statistics, state |
| `series_gate` | §6.5 | a statistics tuple → state and codes |
| `lineage` | §9 | events + live ids + mappings → operations |
| `brand_relation`, `name_tokens`, `name_relation` | §5 | strings → relation / tokens |
| `body_relation`, `lifecycle_relation` | §6.9 | → relation |
| `protection` | §10.2 | (state, decision, fingerprint flag) → action |
| `band`, `fingerprint` | §11 | value → band label; payload → digest |

### 14.2 Expectation semantics

`expect` states only invariants the contract promises. Anything not listed is unconstrained. `include`/`exclude` are reason-code sets; `target_ids` and `alternatives_min` are exact/minimum; `evidence` maps a dotted path
(`evidence.series.ratio`, `comparison.common_window.months`) to a value or a `{min,max}` range; `lineage` expectations are *must-be-present* unless `exact: true`.

### 14.3 What a conformance runner does

For each case: validate it against `case.schema.json`; build the engine input; run the layer; compare per §14.2; for `resolve` also run §12.3; for every decision check I10/I11 and validate against `decision.schema.json`.
Until the engine exists the contract tests (`tests/identity_resolution/`) check what can be checked without it: schema validity, registry/taxonomy/policy consistency, the arithmetic expectations (windows, gates, bands, lifecycle, body, write matrix, fingerprints) against an independent reference
(`tests/identity_resolution/ir_reference.py`), and coverage (every taxonomy id and every reason code is exercised; policy-key pinning is §14.5).

### 14.4 How new bugs enter

A discovered defect or surprise is **not** fixed by a Python special case. In order: (1) add a taxonomy entry (or extend one), (2) add a failing corpus case that reproduces it with the smallest input, (3) change policy or engine until it passes, (4) if behaviour changed, bump the policy version.
A case's `origin` records where it came from; `owner_report_r6` cases are reproduced from the stated mechanism and should be replaced with the real review-sheet rows when those are available.

### 14.5 Policy coverage

Every behaviour-bearing policy key must be pinned: flipping any single value must fail at least one case. This was verified for v1 by an exhaustive single-key mutation sweep against a throwaway prototype of this SPEC (not committed; see README "Verification"). It becomes a CI check once the engine exists. Removing the last case that pins a key is a review finding.

---

## 15. Compatibility facade and deliberate deviations

`vehreg/ice_crosswalk.py` and `tools/ice_crosswalk_match.py` stay untouched and live. During migration they become facades over the engine; until then v1 is a specification only. These are the places v1 **deliberately differs** from the legacy matcher or
from VEHICLE_DB_V3 §14.2, each needing the owner's decision (README "Decisions for the owner"):

| # | Legacy / §14.2 | v1 | Why |
|---|---|---|---|
| D1 | "last 24 monthly totals" of Ice; absent months are 0 | newest 24 months of the **common** window; never zero-fill; trim inactive edges | time-window bias |
| D2 | name = `SequenceMatcher` ratio; AUTO at ≥ 0.8; candidate floor 0.35 | token relations; AUTO needs an `EQUAL*` relation; contradictions and siblings are vetoes | `D-Max`→`MU-X` (0.44 ≥ 0.35), `Hilux Revo`≈`Hilux Travo` (0.86 ≥ 0.8) |
| D3 | brand prefix removed by `startswith` on the exact brand string | whole-token removal through the brand's alias class | `MG4 EV`→`4 ev`; `Mercedes GLC` under `MERCEDES BENZ` |
| D4 | strong series + name ≥ 0.8 = AUTO | additionally: minimum months/units, monthly fit, no body/lifecycle contradiction, settled subject, not quarantined, unique within margin | volume-light and restated groups were auto-linkable |
| D5 | split → copy the parent's target onto the child as `PROPOSED`/`ADMIN` | a review question (STRUCTURE card); the child resolves on its own evidence | wrong proposals such as Corolla Cross → Corolla Altis |
| D6 | fingerprint includes `master_version` | two fingerprints; the suppression key has no window or version | a REJECTED row was re-proposed every package |
| D7 | a retired id split to several successors has no redirect (check constraint admits RENAME/MERGE only) | redirect to the largest-share successor | Ice's published rule; 3 ids in M7.0 |
| D8 | one TDR model with two Ice groups: the best one wins silently | `STRUCTURAL_REVIEW` | `honda-city` + `honda-city-hatchback` |
| D9 | candidates considered one at a time | bounded bundle search among name-affine same-brand models | `hilux_travo_cab` + `hilux_travo_double_cab` |
| D10 | several candidates → keep the best by rank, drop the rest | tie inside the margin → `AMBIGUOUS`, all listed | silent loss of the alternative |
| D11 | `LOCKED` does not exist (`ADMIN` is the de-facto lock) | `LOCKED` is a logical state; migration to be decided | explicit freeze |
| D12 | APPROVED rows move silently on a rename | recorded lineage move (or owner ack by policy) | I2 |
| D13 | brand aliases live in a DB table | aliases live in `policy.yaml` (git-reviewed, versioned, tested); the DB table, if kept, is a read model | aliases are policy |

---

## 16. Versioning and change control

- `contract/v1/` is immutable once adopted. A breaking change is `v2`.
- `policy.version` (SemVer): **MAJOR** — an outcome class can change for existing input; **MINOR** — a new alias/allow-list entry or a new key with a no-op default; **PATCH** — comments/wording only.
- A policy change MUST ship with the corpus rows that pin it (§14.4, §14.5) and an owner decision. A `policy.digest` mismatch against `policy.version` is a release blocker (engine milestone).
- The engine refuses a policy version it does not implement (`INPUT_POLICY_VERSION_UNSUPPORTED`).

---

## 17. Open questions for the owner

See `README.md` → "Decisions for the owner". The thresholds marked `proposal` in the policy provenance are **not calibrated on production data** (the first R6 run's review rows are not in the repository); they should be reviewed against the real review sheet before adoption.

---

## Appendix A — Policy key index

Generated from `policy.yaml` (`python -m identity_resolution.contract.render --write`). Provenance: **inherited** = from an owner-approved document; **observed** = read from the real M7.0 package; **proposal** = new in this design, uncalibrated; **assumption** = depends on an unverified fact.

<!-- BEGIN GENERATED:policy-index -->
| Policy key | Value | Provenance |
|---|---|---|
| `quantization.places` | `6` | proposal |
| `time.valid_year_range` | `[1900, 2200]` | proposal |
| `series.window.max_months` | `24` | inherited |
| `series.window.trim_inactive_edges` | `true` | proposal |
| `series.window.exclude_partial_periods` | `true` | proposal |
| `series.strong.correlation_min` | `0.98` | inherited |
| `series.strong.ratio_min` | `0.9` | inherited |
| `series.strong.ratio_max` | `1.1` | inherited |
| `series.minimums.auto.common_months` | `12` | proposal |
| `series.minimums.auto.joint_nonzero_months` | `10` | proposal |
| `series.minimums.auto.units_each_side` | `120` | proposal |
| `series.minimums.propose.common_months` | `6` | proposal |
| `series.minimums.propose.joint_nonzero_months` | `4` | proposal |
| `series.minimums.propose.units_each_side` | `30` | proposal |
| `series.monthly_fit.abs_tolerance_units` | `3` | proposal |
| `series.monthly_fit.rel_tolerance` | `0.25` | proposal |
| `series.monthly_fit.min_share_of_months` | `0.75` | proposal |
| `lexical.token_boundary_characters` | `" -_/.,()+"` | proposal |
| `lexical.generic_tokens` | `["series", "class"]` | observed |
| `lexical.token_equivalences` | `[["ev", "electric"], ["hatch", "hatchback"], ["hev", "hybrid"]]` | assumption |
| `lexical.unavailable_name_values` | `["ไม่ระบุ", "unknown", "n/a"]` | observed |
| `lexical.fuzzy_token.enabled` | `true` | proposal |
| `lexical.fuzzy_token.min_token_length` | `6` | proposal |
| `lexical.name.auto_relations` | `["EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV"]` | proposal |
| `lexical.name.candidate_relations` | `["EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV", "FUZZY"]` | proposal |
| `lexical.name.veto_relations` | `["SIBLING", "CONTRADICTION"]` | proposal |
| `lexical.series_only.allow_with_name_veto` | `false` | proposal |
| `aliases.brand` | `(8 entries — see policy.yaml)` | observed |
| `aliases.model` | `(1 entries — see policy.yaml)` | inherited |
| `attributes.body.compatibility` | `(11 entries — see policy.yaml)` | observed |
| `attributes.lifecycle.grace_months` | `6` | proposal |
| `attributes.lifecycle.within_min_share` | `0.8` | proposal |
| `attributes.lifecycle.disjoint_max_share` | `0.2` | proposal |
| `attributes.target_status.cap_proposed` | `["UNVERIFIED"]` | proposal |
| `subject_quality.never_auto_identity_statuses` | `["provisional", "unmapped_name"]` | proposal |
| `subject_quality.discovery.catalog_gap_min_units` | `500` | proposal |
| `subject_quality.discovery.provisional_min_units` | `30` | proposal |
| `candidates.brand_relations_allowed` | `["EXACT", "ALIAS_SAME", "ALIAS_RELABEL", "ALIAS_RELATED"]` | proposal |
| `candidates.brand_relations_auto_eligible` | `["EXACT", "ALIAS_SAME", "ALIAS_RELABEL"]` | proposal |
| `candidates.target_statuses_in_pool` | `["CURRENT", "HISTORICAL", "UNVERIFIED"]` | proposal |
| `candidates.exclude_deleted_targets` | `true` | proposal |
| `candidates.bundle.enabled` | `true` | proposal |
| `candidates.bundle.max_members` | `3` | proposal |
| `candidates.bundle.max_pool_for_enumeration` | `12` | proposal |
| `candidates.bundle.member_name_relations` | `["EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV", "SUBJECT_COARSER"]` | proposal |
| `candidates.ranking.tier_order` | `(6 entries — see policy.yaml)` | proposal |
| `candidates.ranking.series_state_order` | `["STRONG", "WEAK", "UNAVAILABLE"]` | proposal |
| `candidates.ranking.lifecycle_order` | `["WITHIN", "UNKNOWN", "PARTIAL"]` | proposal |
| `candidates.ranking.name_relation_order` | `(7 entries — see policy.yaml)` | proposal |
| `candidates.margin.correlation_delta_min` | `0.01` | proposal |
| `candidates.margin.abs_ln_ratio_delta_min` | `0.05` | proposal |
| `granularity.provider_finer.subject_name_relations` | `["SUBJECT_FINER"]` | proposal |
| `granularity.provider_finer.min_ratio_above` | `1.1` | proposal |
| `granularity.provider_finer.arbitration_bundle_check` | `true` | proposal |
| `lineage.quarantine.split_parent` | `true` | proposal |
| `lineage.quarantine.split_child` | `true` | proposal |
| `lineage.quarantine.merge_target` | `true` | proposal |
| `lineage.quarantine.rename_target` | `false` | proposal |
| `lineage.split_child_structure_card` | `true` | proposal |
| `lineage.protected.approved` | `"follow_with_lineage"` | proposal |
| `lineage.protected.locked` | `"require_owner_ack"` | proposal |
| `state.write_matrix` | `(6 entries — see policy.yaml)` | proposal |
| `data_sufficiency.series_decisively_wrong.correlation_below` | `0.5` | proposal |
| `data_sufficiency.series_decisively_wrong.ratio_outside` | `[0.5, 2.0]` | proposal |
| `fingerprint.bands` | `(4 entries — see policy.yaml)` | proposal |
| `review.routing` | `(8 entries — see policy.yaml)` | proposal |
| `review.discovery_subject_flags` | `["SUBJ_PROVISIONAL", "SUBJ_UNMAPPED_NAME"]` | proposal |
| `review.high_priority_codes` | `(3 entries — see policy.yaml)` | proposal |
<!-- END GENERATED:policy-index -->

## Appendix B — Reason-code registry

Generated from `reason_codes.yaml`.

<!-- BEGIN GENERATED:reason-codes -->
| Code | Kind | Roles | Effect | Primary for | Summary |
|---|---|---|---|---|---|
| `AUTO_ALL_GATES_PASSED` | decision | primary | none | AUTO | Every AUTO gate passed (SPEC §8.4). AUTO is a revocable machine link, never an approval. |
| `PROPOSE_SERIES_STRONG_CAPPED` | decision | primary | none | PROPOSE | Series evidence is strong but at least one blocking code keeps the candidate from AUTO. |
| `PROPOSE_NAME_MATCH_SERIES_NOT_STRONG` | decision | primary | none | PROPOSE | Name and brand agree but the series is weak or unavailable. Name alone is never AUTO. |
| `PROPOSE_BUNDLE` | decision | primary | none | PROPOSE | No single TDR model fits but a bundle of 2..max_members TDR models does. Bundles are PROPOSED at most. |
| `AMBIGUOUS_CANDIDATES_WITHIN_MARGIN` | decision | primary | forces_review | AMBIGUOUS | Two or more candidates tie at the top tier inside the policy margin; none is selected. |
| `AMBIGUOUS_TARGET_CONTESTED` | decision | primary | forces_review | AMBIGUOUS | Two subjects would each take the same TDR target as their active mapping; neither is auto-linked. |
| `STRUCTURAL_PROVIDER_FINER` | decision | primary | forces_review | STRUCTURAL_REVIEW | The provider splits what TDR holds as one model (e.g. sedan + hatchback); the one-target-one-group rule cannot express it. |
| `STRUCTURAL_APPROVED_CLAIM_CONFLICT` | decision | primary | forces_review | STRUCTURAL_REVIEW | This subject strongly fits a TDR target already held APPROVED/LOCKED by another subject. Nothing is changed; the owner decides. |
| `NO_CANDIDATE_ALL_EXCLUDED` | decision | primary | none | NO_CANDIDATE | Every brand-compatible candidate is excluded by affirmative evidence. |
| `NO_CANDIDATE_EMPTY_POOL` | decision | primary | none | NO_CANDIDATE | The TDR brand exists but offers no eligible model. |
| `INSUFFICIENT_DATA_NO_BASIS` | decision | primary | none | INSUFFICIENT_DATA | A candidate survives but no evidence reaches PROPOSE; re-evaluate when data accrues. |
| `PROTECTED_HOLD_APPROVED` | decision | primary | blocks_write | PROTECTED_HOLD | The subject has an APPROVED mapping. The engine reports evidence and changes nothing. |
| `PROTECTED_HOLD_LOCKED` | decision | primary | blocks_write | PROTECTED_HOLD | The subject has a LOCKED mapping. The engine reports evidence and changes nothing. |
| `SUPPRESSED_REJECTED_UNCHANGED` | decision | primary | suppresses | SUPPRESSED | A human REJECTED this pair and its evidence fingerprint has not moved; it is not re-proposed. |
| `SUBJ_PROVISIONAL` | decision | blocking, info | cap_proposed | — | The subject id is provisional (provider expects to replace it); never AUTO. |
| `SUBJ_UNMAPPED_NAME` | decision | blocking, info | cap_proposed | — | The subject is a raw-name group the provider has not assigned to a principal model; never AUTO. |
| `SUBJ_UNSPECIFIED_NAME` | decision | info | name_unavailable | — | The subject's display name is a non-name ("ไม่ระบุ"/blank); name evidence is unavailable. |
| `SUBJ_DUPLICATE_DISPLAY_NAME` | decision | info | none | — | Another subject in the snapshot shares this display name; the display name is not a key. |
| `SUBJ_MULTI_BRAND` | decision | info, supporting | none | — | The provider registered this subject under several brands; any observed brand may satisfy brand matching. |
| `BRND_EXACT` | decision | supporting | none | — | Brand compact keys are identical. |
| `BRND_ALIAS_SAME` | decision | supporting | none | — | Brands are spelling variants of one marque (alias relation SAME). |
| `BRND_ALIAS_RELABEL` | decision | supporting | none | — | Brands are one marque under two labels (alias relation RELABEL, e.g. Deepal/Changan). |
| `BRND_ALIAS_RELATED` | decision | blocking | cap_proposed | — | Brands are related (parent/child/joint venture) but not equivalent; PROPOSED at most. |
| `BRND_MISMATCH` | decision | info | veto_candidate | — | Brands are unrelated; the target is not a candidate. |
| `BRND_UNKNOWN` | decision | primary, info | veto_candidate | NO_CANDIDATE | The subject has no usable brand; no candidate pool can be formed. |
| `BRND_NOT_IN_TDR` | decision | primary, info | none | NO_CANDIDATE | The subject's brand has no counterpart in the TDR catalog. |
| `BRND_PREFIX_STRIPPED` | decision | info | none | — | A leading brand-spelling token sequence was removed from a model name before comparison. |
| `NAME_EQUAL` | decision | supporting | none | — | Normalized token sets (or compact forms) are identical. |
| `NAME_EQUAL_VIA_MODEL_ALIAS` | decision | supporting | none | — | Equal only through a scoped model-name alias (aliases.model). |
| `NAME_EQUAL_VIA_TOKEN_EQUIV` | decision | supporting | none | — | Equal only through a declared token equivalence (e.g. ev = electric). |
| `NAME_FUZZY_TOKEN` | decision | blocking | cap_proposed | — | Equal only through a one-edit typo tolerance on a long token; PROPOSED at most. |
| `NAME_CONTAINMENT_SUBJECT_COARSER` | decision | blocking, info | cap_proposed | — | The subject's name tokens are a proper subset of the target's (the subject is the broader nameplate). |
| `NAME_CONTAINMENT_SUBJECT_FINER` | decision | blocking, info | cap_proposed | — | The target's name tokens are a proper subset of the subject's (the subject is the narrower nameplate). |
| `NAME_SIBLING_VARIANT` | decision | info | veto_candidate | — | Both names share a stem but each carries a distinguishing token the other lacks (Hilux Revo / Hilux Travo). |
| `NAME_CONTRADICTION` | decision | info | veto_candidate | — | Names carry disjoint distinguishing tokens (D-Max / MU-X, 3 Series / X3). |
| `NAME_UNAVAILABLE` | decision | blocking, info | name_unavailable | — | One side has no usable name (blocking when a strong series would otherwise have been AUTO). |
| `NAME_ONLY_NOT_AUTO` | decision | blocking | cap_proposed | — | Lexical agreement without strong series evidence can never be AUTO (§14.2). |
| `SER_STRONG` | decision | supporting | none | — | Correlation, ratio and monthly-fit gates all pass over the common window. |
| `SER_CORRELATION_BELOW_STRONG` | decision | blocking | cap_proposed | — | Correlation is below series.strong.correlation_min. |
| `SER_RATIO_OUT_OF_BAND` | decision | blocking | cap_proposed | — | Target/subject unit ratio is outside [ratio_min, ratio_max]. |
| `SER_MONTHLY_FIT_FAIL` | decision | blocking | cap_proposed | — | Shape and level pass but too few individual months track within tolerance (outlier-driven correlation). |
| `SER_NO_COMMON_WINDOW` | decision | info | series_unavailable | — | The two series share no observed period after trimming and exclusions. |
| `SER_COVERAGE_UNDECLARED` | decision | info | series_unavailable | — | A series arrived without declared coverage; its absent months cannot be read as zero or as unobserved. |
| `SER_COVERAGE_ASYMMETRIC` | decision | info | none | — | The two sources cover different spans; only the common observation window was compared. |
| `SER_WINDOW_TRIMMED_INACTIVE` | decision | info | none | — | Leading and/or trailing months where both sides are zero were dropped from the window. |
| `SER_PARTIAL_PERIOD_EXCLUDED` | decision | info | none | — | One or more periods flagged partial by a source were excluded from the window. |
| `SER_OVERLAP_BELOW_AUTO_MIN` | decision | blocking | cap_proposed | — | Common months or joint non-zero months are below the AUTO minimums. |
| `SER_OVERLAP_BELOW_PROPOSE_MIN` | decision | info | series_unavailable | — | Common months or joint non-zero months are below the PROPOSE minimums; series evidence is unusable. |
| `SER_VOLUME_BELOW_AUTO_MIN` | decision | blocking | cap_proposed | — | Units on at least one side of the window are below the AUTO minimum. |
| `SER_VOLUME_BELOW_PROPOSE_MIN` | decision | info | series_unavailable | — | Units on at least one side of the window are below the PROPOSE minimum; series evidence is unusable. |
| `SER_ZERO_VARIANCE` | decision | info | series_unavailable | — | One side is constant over the window; correlation is undefined. |
| `SER_ZERO_TOTAL` | decision | info | series_unavailable | — | The subject has zero units in the window; the ratio is undefined. |
| `SER_UNOBSERVED_NOT_ZERO` | decision | info | none | — | Unobserved months (null) inside a series were left out of the comparison, not read as zero. |
| `SER_BUNDLE_STRONG` | decision | supporting | none | — | The summed series of a TDR bundle passes the strong gates against the subject. |
| `SER_BUNDLE_OVERSHOOT` | decision | blocking | veto_candidate | — | Adding a member pushes the bundle ratio above ratio_max; that bundle is rejected. |
| `ATTR_BODY_MISMATCH` | decision | blocking | cap_proposed | — | Both sides state a body type and they are not compatible. |
| `ATTR_BODY_UNKNOWN` | decision | info | none | — | At least one side has no usable body type; body is not used. |
| `ATTR_TARGET_UNVERIFIED` | decision | blocking | cap_proposed | — | The TDR target has status UNVERIFIED. |
| `GEN_LIFECYCLE_DISJOINT` | decision | info | veto_candidate | — | Almost none of the subject's units fall inside the target's lifetime (generation mismatch). |
| `GEN_LIFECYCLE_PARTIAL` | decision | blocking | cap_proposed | — | Only part of the subject's units fall inside the target's lifetime. |
| `GEN_LIFECYCLE_UNKNOWN` | decision | info | none | — | The target has no generation dates; lifecycle is not used. |
| `GEN_SAME_NAMEPLATE_MULTI_TARGET` | decision | info | none | — | Several TDR models share the same normalized nameplate (e.g. one per generation). |
| `CARD_MANY_TO_ONE_ALLOWED` | decision | supporting, info | none | — | Several TDR models may map to one provider subject (the TDR side is finer). |
| `CARD_TARGET_ACTIVE_ELSEWHERE` | decision | info | veto_candidate | — | The TDR target is actively mapped (APPROVED/LOCKED) to a different subject. |
| `CARD_TARGET_MISSING` | decision | blocking, info | forces_review | — | An existing mapping points at a TDR target that is deleted or absent. |
| `CARD_BUNDLE_EXTENDS_PROTECTED` | decision | blocking | cap_proposed | — | The candidate would add a member to a subject that already holds a protected mapping; PROPOSED at most. |
| `DISCOVERY_CATALOG_GAP` | decision | info | forces_review | — | A sizeable subject has no TDR counterpart; probably a catalog gap, routed to discovery. |
| `LIN_RENAME_FOLLOWED` | structural | primary, info | emits_operation | REDIRECT, MOVE_MAPPINGS | A provider RENAME retires the old id; mappings and the redirect follow the new id. |
| `LIN_MERGE_FOLLOWED` | structural | primary, info | emits_operation | REDIRECT, MOVE_MAPPINGS | A provider MERGE retires the old id into one surviving id; mappings and the redirect follow. |
| `LIN_SPLIT_PARENT_RETAINED` | structural | primary, info | none | NOOP | A provider SPLIT leaves the old id live; it is not redirected. |
| `LIN_REDIRECT_RETIRED_SPLIT` | structural | primary | emits_operation | REDIRECT | A retired id split to several successors is redirected to the successor chosen by successor_selection. |
| `LIN_TIE_BREAK_ID_ASC` | structural | info | none | — | Successor shares tied; the lexicographically first new id was chosen. |
| `LIN_NO_CHAIN` | structural | info | none | — | An id is both old and new in the batch; every event was read against the pre-change state, none chained. |
| `LIN_CYCLE_NO_REDIRECT` | structural | primary | emits_operation | ERROR | Retired ids redirect to each other in a cycle; no redirect is written. |
| `LIN_TARGET_NOT_LIVE` | structural | primary | emits_operation | ERROR | The redirect target is not present in the live snapshot; redirects are never chained to find one. |
| `LIN_SOURCE_MISSING` | refusal | primary | refuses_run | — | The provider declares an identity change but ships no machine-readable lineage source; nothing is inferred. |
| `LIN_ALREADY_APPLIED` | structural | primary | none | NOOP | This exact event was applied in an earlier snapshot; re-applying is a no-op. |
| `LIN_PROTECTED_FOLLOWED_WITH_LINEAGE` | structural | info | none | — | An APPROVED mapping followed the identity change as a recorded lineage move, not a silent rewrite. |
| `LIN_PROTECTED_NEEDS_OWNER_ACK` | structural | primary | forces_review | FLAG_MAPPING_REVIEW | An identity change touches a protected mapping whose policy is require_owner_ack (LOCKED by default); nothing moves until the owner acknowledges. |
| `LIN_MOVE_TARGET_CONFLICT` | structural | primary, info | forces_review | FLAG_MAPPING_REVIEW | Moving this mapping would break one-active-group-per-TDR-model; it stays on the old id and is flagged. |
| `LIN_EVIDENCE_QUARANTINE` | both | primary, blocking | cap_proposed | QUARANTINE | The subject's history was restated by an identity change this snapshot; AUTO is withheld. |
| `LIN_PROVISIONAL_PROMOTED` | structural | info | none | — | A provisional id was replaced by its principal id. |
| `LIN_PARENT_MAPPING_REVIEW` | structural | primary | forces_review | FLAG_MAPPING_REVIEW | A split parent's existing mapping needs review because part of its units moved away. |
| `LIN_SPLIT_CHILD_INHERITED_CANDIDATE` | structural | primary | forces_review | CANDIDATE_HINT | A split raises a STRUCTURE card (review question) asking whether the parent's TDR target also covers the new child. It is a hint, never a mapping row. |
| `STATE_EVIDENCE_CONFIRMS` | decision | supporting | none | — | Fresh evidence agrees with the existing protected mapping. |
| `STATE_EVIDENCE_CONTRADICTS` | decision | info | forces_review | — | Fresh evidence disagrees with an existing protected mapping. Reported, never applied. |
| `STATE_REJECTED_REOPENED` | decision | blocking, info | cap_proposed | — | A rejected pair's evidence fingerprint moved; it may be re-proposed, never auto-linked. |
| `STATE_AUTO_DEMOTED` | decision | info | none | — | An existing AUTO mapping no longer passes the AUTO gates and is demoted to PROPOSED. |
| `STATE_CANDIDATE_STALE` | decision | info | none | — | An existing PROPOSED candidate is no longer produced by the engine and is marked stale. |
| `AUTH_STRUCTURE_OVER_STATISTICS` | decision | info | none | — | Provider-supplied structure decided where statistics disagree; the statistics were recorded, not obeyed. |
| `AUTH_HUMAN_OVER_ENGINE` | decision | info | blocks_write | — | A human decision outranks the engine's finding; the engine's finding is recorded only. |
| `INPUT_SOURCE_VERSION_MISSING` | refusal | primary | refuses_run | — | The snapshot has no source version label; decisions could not be traced. |
| `INPUT_DUPLICATE_SUBJECT_ID` | refusal | primary | refuses_run | — | Two subjects share an id within one snapshot. |
| `INPUT_PERIOD_CALENDAR_INVALID` | refusal | primary | refuses_run | — | A series period is outside time.valid_year_range (e.g. a Buddhist year in a Gregorian series). |
| `INPUT_NEGATIVE_COUNT` | refusal | primary | refuses_run | — | A series contains a negative count. |
| `INPUT_POLICY_VERSION_UNSUPPORTED` | refusal | primary | refuses_run | — | The requested policy version is not the one this engine build implements. |
<!-- END GENERATED:reason-codes -->

## Appendix C — Edge-case taxonomy

Generated from `taxonomy.yaml`.

<!-- BEGIN GENERATED:taxonomy -->
| Id | Edge case | Origin | Reason codes |
|---|---|---|---|
| `CORE-01` | Clean match | design | `AUTO_ALL_GATES_PASSED`, `BRND_EXACT`, `NAME_EQUAL`, `SER_STRONG` |
| `CORE-02` | Strong series held back by one blocking condition | design | `PROPOSE_SERIES_STRONG_CAPPED` |
| `SUBJ-01` | Provisional subject id | ice_m7_data | `SUBJ_PROVISIONAL` |
| `SUBJ-02` | Raw-name subject with no principal model (BRAND\|MODEL) | ice_m7_data | `SUBJ_UNMAPPED_NAME`, `INSUFFICIENT_DATA_NO_BASIS` |
| `SUBJ-03` | Display name is a non-name | ice_m7_data | `SUBJ_UNSPECIFIED_NAME`, `NAME_UNAVAILABLE` |
| `SUBJ-04` | Display name is not a key | ice_m7_data | `SUBJ_DUPLICATE_DISPLAY_NAME` |
| `SUBJ-05` | Subject registered under several brands | ice_m7_data | `SUBJ_MULTI_BRAND` |
| `BRND-01` | Brand spelling and format variants | ice_m7_data | `BRND_EXACT`, `BRND_ALIAS_SAME` |
| `BRND-02` | Same marque under another label | ice_m7_data | `BRND_ALIAS_RELABEL` |
| `BRND-03` | Related but not equivalent brands | design | `BRND_ALIAS_RELATED` |
| `BRND-04` | Same model name under unrelated brands | ice_m7_data | `BRND_MISMATCH` |
| `BRND-05` | Provider brand absent from the TDR catalog | ice_m7_data | `BRND_NOT_IN_TDR` |
| `BRND-06` | Provider brand unusable | design | `BRND_UNKNOWN` |
| `BRND-07` | Brand prefix inside the model name | ice_m7_data | `BRND_PREFIX_STRIPPED` |
| `NAME-01` | Separator and case variants | ice_m7_data | `NAME_EQUAL` |
| `NAME-02` | Distinct nameplates of one brand | owner_report_r6 | `NAME_CONTRADICTION`, `NO_CANDIDATE_ALL_EXCLUDED` |
| `NAME-03` | Number-versus-letter prefix trap | ice_m7_data | `NAME_CONTRADICTION` |
| `NAME-04` | Sibling variants sharing a stem | ice_m7_data | `NAME_SIBLING_VARIANT` |
| `NAME-05` | Subject name is the broader nameplate | ice_m7_data | `NAME_CONTAINMENT_SUBJECT_COARSER` |
| `NAME-06` | Subject name is the narrower nameplate | ice_m7_data | `NAME_CONTAINMENT_SUBJECT_FINER` |
| `NAME-07` | Generic descriptor tokens | ice_m7_data | `NAME_EQUAL` |
| `NAME-08` | Declared token equivalence | design | `NAME_EQUAL_VIA_TOKEN_EQUIV` |
| `NAME-09` | Scoped model-name alias | ice_m7_data | `NAME_EQUAL_VIA_MODEL_ALIAS` |
| `NAME-10` | One-edit typo in a long token | design | `NAME_FUZZY_TOKEN` |
| `NAME-11` | Name unavailable or non-Latin only | ice_m7_data | `NAME_UNAVAILABLE`, `NAME_ONLY_NOT_AUTO` |
| `NAME-12` | Provider groups by trim code | ice_m7_data | `NAME_CONTRADICTION` |
| `NAME-13` | Name-only agreement | owner_report_r6 | `NAME_ONLY_NOT_AUTO`, `PROPOSE_NAME_MATCH_SERIES_NOT_STRONG` |
| `SER-01` | The two sources cover different spans | owner_report_r6 | `SER_COVERAGE_ASYMMETRIC` |
| `SER-02` | Window anchored on the provider's newest month | owner_report_r6 | `SER_COVERAGE_ASYMMETRIC`, `SER_STRONG` |
| `SER-03` | Leading zeros before a launch | ice_m7_data | `SER_WINDOW_TRIMMED_INACTIVE` |
| `SER-04` | Trailing zeros after a discontinuation | design | `SER_WINDOW_TRIMMED_INACTIVE` |
| `SER-05` | Unobserved months inside a series | ice_m7_data | `SER_UNOBSERVED_NOT_ZERO` |
| `SER-06` | Partial period | design | `SER_PARTIAL_PERIOD_EXCLUDED` |
| `SER-07` | Coverage not declared | design | `SER_COVERAGE_UNDECLARED` |
| `SER-08` | No common window | design | `SER_NO_COMMON_WINDOW` |
| `SER-09` | Too few common months | ice_m7_data | `SER_OVERLAP_BELOW_PROPOSE_MIN`, `SER_OVERLAP_BELOW_AUTO_MIN` |
| `SER-10` | Too few units | ice_m7_data | `SER_VOLUME_BELOW_PROPOSE_MIN`, `SER_VOLUME_BELOW_AUTO_MIN` |
| `SER-11` | Constant series | design | `SER_ZERO_VARIANCE` |
| `SER-12` | Subject has zero units in the window | design | `SER_ZERO_TOTAL` |
| `SER-13` | Right shape, wrong level | owner_report_r6 | `SER_RATIO_OUT_OF_BAND` |
| `SER-14` | Right level, wrong shape | design | `SER_CORRELATION_BELOW_STRONG` |
| `SER-15` | Threshold boundaries | design | `SER_STRONG`, `SER_CORRELATION_BELOW_STRONG`, `SER_RATIO_OUT_OF_BAND` |
| `SER-16` | Outlier-driven correlation | design | `SER_MONTHLY_FIT_FAIL` |
| `SER-17` | Several TDR models sum to one subject | ice_m7_data | `SER_BUNDLE_STRONG`, `PROPOSE_BUNDLE`, `CARD_MANY_TO_ONE_ALLOWED` |
| `SER-18` | Bundle overshoots the subject | design | `SER_BUNDLE_OVERSHOOT` |
| `GRAN-01` | Provider finer than TDR (one TDR model, several provider groups) | ice_m7_data | `STRUCTURAL_PROVIDER_FINER` |
| `GRAN-02` | Body type disagrees | owner_report_r6 | `ATTR_BODY_MISMATCH`, `ATTR_BODY_UNKNOWN` |
| `GRAN-03` | Generation / lifecycle disjoint | owner_report_r6 | `GEN_LIFECYCLE_DISJOINT`, `GEN_LIFECYCLE_PARTIAL`, `GEN_LIFECYCLE_UNKNOWN` |
| `GRAN-04` | Same nameplate, several TDR models (one per generation) | design | `GEN_SAME_NAMEPLATE_MULTI_TARGET` |
| `GRAN-05` | Unverified target | design | `ATTR_TARGET_UNVERIFIED` |
| `CARD-01` | Conflicting candidates within the margin | owner_report_r6 | `AMBIGUOUS_CANDIDATES_WITHIN_MARGIN` |
| `CARD-02` | Two subjects claim one TDR target | design | `AMBIGUOUS_TARGET_CONTESTED` |
| `CARD-03` | Target already held by a protected mapping | design | `CARD_TARGET_ACTIVE_ELSEWHERE` |
| `CARD-04` | Strong evidence for a protected target held by another subject | design | `STRUCTURAL_APPROVED_CLAIM_CONFLICT` |
| `CARD-05` | Missing canonical target (catalog gap) | ice_m7_data | `NO_CANDIDATE_ALL_EXCLUDED`, `DISCOVERY_CATALOG_GAP` |
| `CARD-06` | Mapped TDR target no longer exists | design | `CARD_TARGET_MISSING` |
| `CARD-07` | New member for a subject that already has a protected mapping | design | `CARD_BUNDLE_EXTENDS_PROTECTED` |
| `CARD-08` | Brand exists in TDR but offers no eligible model | design | `NO_CANDIDATE_EMPTY_POOL` |
| `CARD-09` | Nothing excludes a candidate but nothing supports one | ice_m7_data | `INSUFFICIENT_DATA_NO_BASIS` |
| `LIN-01` | Rename (เปลี่ยนรหัส) | ice_m7_data | `LIN_RENAME_FOLLOWED` |
| `LIN-02` | Merge (รวม) | ice_m7_data | `LIN_MERGE_FOLLOWED` |
| `LIN-03` | Split where the parent stays live | ice_m7_data | `LIN_SPLIT_PARENT_RETAINED`, `LIN_EVIDENCE_QUARANTINE`, `LIN_PARENT_MAPPING_REVIEW`, `LIN_SPLIT_CHILD_INHERITED_CANDIDATE` |
| `LIN-04` | Split where the parent is retired | ice_m7_data | `LIN_REDIRECT_RETIRED_SPLIT`, `LIN_PARENT_MAPPING_REVIEW` |
| `LIN-05` | Equal shares among successors | ice_m7_data | `LIN_TIE_BREAK_ID_ASC` |
| `LIN-06` | An id that is both old and new in one file | ice_m7_data | `LIN_NO_CHAIN` |
| `LIN-07` | Mutual splits between live ids | ice_m7_data | `LIN_NO_CHAIN`, `LIN_SPLIT_PARENT_RETAINED`, `LIN_EVIDENCE_QUARANTINE` |
| `LIN-08` | Redirect cycle among retired ids | design | `LIN_CYCLE_NO_REDIRECT` |
| `LIN-09` | Redirect target not live | design | `LIN_TARGET_NOT_LIVE` |
| `LIN-10` | Identity change declared but no machine-readable source | ice_m7_data | `LIN_SOURCE_MISSING` |
| `LIN-11` | Re-applying an already applied event | ice_m7_data | `LIN_ALREADY_APPLIED` |
| `LIN-12` | Provisional id promoted to a principal id | ice_m7_data | `LIN_PROVISIONAL_PROMOTED`, `LIN_RENAME_FOLLOWED` |
| `LIN-13` | Rename touches an APPROVED mapping | design | `LIN_PROTECTED_FOLLOWED_WITH_LINEAGE` |
| `LIN-14` | Rename touches a LOCKED mapping | design | `LIN_PROTECTED_NEEDS_OWNER_ACK` |
| `LIN-15` | Move would break one-active-group-per-target | ice_m7_data | `LIN_MOVE_TARGET_CONFLICT` |
| `LIN-16` | History restated by an identity change | ice_m7_data | `LIN_EVIDENCE_QUARANTINE` |
| `LIN-17` | Provider's explicit successor | design | `LIN_REDIRECT_RETIRED_SPLIT` |
| `STATE-01` | APPROVED mapping is held | design | `PROTECTED_HOLD_APPROVED` |
| `STATE-02` | LOCKED mapping is held | design | `PROTECTED_HOLD_LOCKED` |
| `STATE-03` | Fresh evidence versus a protected mapping | design | `STATE_EVIDENCE_CONFIRMS`, `STATE_EVIDENCE_CONTRADICTS`, `AUTH_HUMAN_OVER_ENGINE` |
| `STATE-04` | AUTO is not APPROVED | design | `STATE_AUTO_DEMOTED` |
| `STATE-05` | Rejected pair, evidence unchanged | design | `SUPPRESSED_REJECTED_UNCHANGED` |
| `STATE-06` | Rejected pair, evidence changed | design | `STATE_REJECTED_REOPENED` |
| `STATE-07` | Candidate no longer produced | design | `STATE_CANDIDATE_STALE` |
| `STATE-08` | Write matrix coverage | design | `AUTH_HUMAN_OVER_ENGINE` |
| `AUTH-01` | Provider structure disagrees with statistics | design | `AUTH_STRUCTURE_OVER_STATISTICS` |
| `FP-01` | Deterministic decision fingerprint | design | — |
| `FP-02` | Suppression key independent of the rolling window | design | — |
| `FP-03` | No floats in fingerprint payloads | design | — |
| `FP-04` | Band edges | design | — |
| `FP-05` | Order independence and idempotence | design | — |
| `INPUT-01` | Duplicate subject id | design | `INPUT_DUPLICATE_SUBJECT_ID` |
| `INPUT-02` | Missing source version | design | `INPUT_SOURCE_VERSION_MISSING` |
| `INPUT-03` | Calendar mix-up (Buddhist year in a Gregorian series) | owner_report_r6 | `INPUT_PERIOD_CALENDAR_INVALID` |
| `INPUT-04` | Negative count | design | `INPUT_NEGATIVE_COUNT` |
| `INPUT-05` | Unsupported policy version | design | `INPUT_POLICY_VERSION_UNSUPPORTED` |
<!-- END GENERATED:taxonomy -->
