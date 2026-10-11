# TDR Identity Bootstrap — Contract v1 (normative, DRAFT for owner review)

Status: **draft**. This is a contract, a corpus and tests, with an offline engine (`engine/`), the Ice adapter (`providers/ice.py`) and a read-only
shadow run (`shadow/`) that conform to it. There is no persistence, no migration, no database access and no enrichment bot. Nothing in production imports this package (a test enforces it). The appendices are generated from `policy.yaml`,
`reason_codes.yaml`, `taxonomy.yaml` and `lifecycle.yaml`; do not edit them by hand (`python -m identity_bootstrap.contract.render --write`).

Words **MUST**, **MUST NOT**, **SHOULD** are normative.

---

## 0. Purpose, scope, ground rules

### 0.1 Purpose

Identity Resolution answers: *does this external identity correspond to an existing TDR canonical vehicle?* When the honest answer is
"no, and it is a vehicle TDR does not have", Bootstrap decides whether TDR can **safely** establish that the vehicle exists and, if so, plans the
creation of a **minimal canonical identity** (a `DISCOVERED` shell) and the hand-off to a separate enrichment subsystem.

### 0.2 The core invariant

**Identity existence and vehicle enrichment are different problems.** Bootstrap establishes only: a canonical identity exists, its brand, its
name, its source lineage, its initial lifecycle state. It MUST NOT infer or invent any other attribute. Every attribute not listed in
`writes.shell_columns` stays absent (SQL `NULL`). A plan that carries a field in `writes.forbidden_attribute_fields` is a contract violation (tested).

### 0.3 Non-goals (v1)

No enrichment, no brand creation, no publication, no consumer-catalog change, no merge or deletion of any existing TDR entity, no mapping
between a provider id and an *existing* canonical model (that is Identity Resolution), no production write, no migration. Registration
volume is never an input to an outcome.

### 0.4 Ground rules

1. **Refuse over guess.** `HOLD` or `IDENTITY_REVIEW` is always preferred to a questionable canonical identity.
2. **"No candidate" is not "new model".** Absence of a crosswalk candidate is necessary, never sufficient.
3. **Conservative about identity, indifferent to completeness.** Missing attributes never block creation; a doubtful *identity* always does.
4. **Everything that changes a decision is a key in `policy.yaml`** (word lists, patterns, mappings, thresholds). Code holds no vocabulary.
5. **A decision is a pure function of `(snapshot, policy)`.** No clock, run id, I/O or randomness. Run id and timestamps enter only in `finalize` at apply time.
6. **A bug becomes a corpus case**, never a Python exception (§16).

---

## 1. Vocabulary

| Term | Meaning |
|---|---|
| **Provider / subject** | An external source of vehicle identities / one such identity (Ice: a `model_group`). |
| **Resolution** | The Identity Resolution v1 result for a subject (PR #200). Bootstrap consumes only its projection (§15). |
| **Identity** | A canonical vehicle in TDR (a `vehicle_models` row) in some lifecycle state. |
| **Shell** | The minimal identity Bootstrap plans: brand, name, ids, `DISCOVERED`/`PENDING`. |
| **Alias** | A binding from a provider id to a canonical id. Provider ids are aliases, never keys. |
| **Identity key** | `brand_id | compact name tokens` (§4.3): what makes two spellings the same identity. |
| **Decision** | One output record per subject: `CREATE_IDENTITY`, `IDENTITY_REVIEW` or `HOLD` (§7). |
| **Write plan** | The preconditions and operations a governed writer would execute for a `CREATE_IDENTITY`. A plan is data; this contract writes nothing. |
| **Review fingerprint** | Hash of the *question* a review asks (§12.3). An admin answer binds to it. |

---

## 2. Invariants

| # | Invariant |
|---|---|
| I1 | A shell is created only from a `NO_CANDIDATE` resolution, and only when no HOLD or REVIEW code survives (§6). |
| I2 | No attribute outside `writes.shell_columns` is ever in a plan. Unknown stays `NULL`. |
| I3 | Volume (`units`) is read only to compute the review priority band and alert. Changing `units` to any value never changes outcome, codes, ids or plan (tested for every corpus case). |
| I4 | The canonical id depends only on `(brand_id, canonical name)`. Not on the provider id, source version, row order, run, clock or volume (§10). |
| I5 | Ids are never auto-suffixed, never reused (deleted and `WITHDRAWN` rows keep theirs), and never changed by a rename. |
| I6 | Reprocessing never creates a second identity: same subject, same plan, or a different spelling all converge on the same row or are rejected by a precondition (§11). |
| I7 | A provider rename, split or merge never creates a duplicate and never merges, deletes or rewrites an existing TDR identity. |
| I8 | Order independence: shuffling subjects, relations or their orientation never changes any decision. Neither of two creatable subjects that collide "wins". |
| I9 | Source-version independence: decision fingerprints, ids and outcomes do not depend on `source_version`. Only provenance references carry it. |
| I10 | Only a `PUBLISHED` identity is visible in the consumer catalog (§5). Bootstrap never publishes. |
| I11 | Provenance is append-only and is never written by the enrichment subsystem; it survives enrichment (§12.4). |
| I12 | Writes follow the governed Vehicle Master write path; until that exists, `apply_mode` is `PROPOSE` (§13). |
| I13 | A `HOLD` or `IDENTITY_REVIEW` record never carries a write plan, an identity or a creator type. |

---

## 3. Architecture and subsystem boundary

```
 External provider (Ice, ...)
        │  adapter (provider-specific, elsewhere)
        ▼
 Identity Resolution  ── existing canonical target? ── yes ──► mapping (AUTO / PROPOSED / ...)   [PR #200, not modified here]
        │ no: outcome NO_CANDIDATE  +  projection (§15)
        ▼
 Identity Bootstrap  (this contract; independently testable; no import from Identity Resolution)
        │   gates G0..G7 (§6)  ·  batch arbitration (§8)  ·  lineage (§9)  ·  id allocation (§10)
        ├── HOLD            nothing to decide; re-evaluate on new input
        ├── IDENTITY_REVIEW a human decides; the question is queued, ordered by volume band
        └── CREATE_IDENTITY write plan ──► governed Vehicle Master writer (later; own gate) ──► DISCOVERED shell
                                                                                    │ same transaction
                                                                                    ▼
                                                                  VEHICLE_IDENTITY_CREATED (outbox)
                                                                                    ▼
                                                                  Enrichment subsystem (separate; not built here)
```

**Package boundary.** `automotive/vehicle_master/identity_bootstrap/` (contract, README, INTEGRATION) and
`automotive/vehicle_master/tests/identity_bootstrap/`. It imports nothing from `vehreg/` except, in a later engine, the single slug rule named in
`allocation.local_segment_function` (the reference oracle in the tests does import it; ENGINE_RULES forbids a second implementation). It does not
import Identity Resolution: the two meet only through data (§15), so either can be tested alone and there is no cycle.

---

## 4. Input and the lexical layer

### 4.1 Input

`input.schema.json#/$defs/snapshot`. The engine MUST refuse the whole run (a refusal record, no decisions) when: the policy version is not the engine's
(`INPUT_POLICY_VERSION_UNSUPPORTED`); `source_version.label` is blank (`INPUT_SOURCE_VERSION_MISSING`); two subjects share `(provider, entity_id)`
(`INPUT_DUPLICATE_SUBJECT_ID`); a subject carries no resolution (`INPUT_RESOLUTION_MISSING`); the provider declares identity changes without a
machine-readable source (`INPUT_LINEAGE_SOURCE_MISSING`); the snapshot violates the schema (`INPUT_SCHEMA_INVALID`), including two relation records that
contradict each other.

`identities` is every existing `vehicle_models` row in any state, deleted or not (ids stay reserved). `bindings` is every existing alias.
`relations` are subject→peer **name relations oriented as in Identity Resolution v1 §5.3** (`SUBJECT_FINER` = the subject's name contains the peer's)
and are supplied by the resolution layer; Bootstrap does not recompute them. A relation between two subjects may be stated from either side.

### 4.2 Name tokens (pinned)

`name_tokens(name, spellings)`: NFKC, case-fold; every character in `lexical.token_boundary_characters` and whitespace becomes a space; every other
character that is not a letter, digit or Thai character is deleted; split on spaces; remove the **longest** brand spelling that is an exact leading token
sequence, **only if at least one token remains** (`MG4 EV` keeps `mg4`; a model named like its brand keeps its name); drop `lexical.generic_tokens`.
`spellings` is the brand's `raw` value plus `spellings`. This is Identity Resolution §5.2 restricted to what Bootstrap needs; the day the two
disagree, Identity Resolution wins and this section is re-pinned.

### 4.3 Canonical name and identity key

`canonical_name`: the display name with the same whole-word brand prefix removed (original casing kept, whitespace collapsed). `identity_key`:
`brand_id` + `|` + the concatenated tokens. An existing identity's key is computed with the *subject's* brand spellings, so a legacy model named
`Jaecoo 5 EV` collides with a new `Jaecoo 5 EV`.

---

## 5. Lifecycle

Two separate axes (appendix D): `identity_state` ∈ `DISCOVERED`, `ENRICHING`, `VERIFIED`, `PUBLISHED`, `WITHDRAWN` and `enrichment_state` ∈ `PENDING`,
`IN_PROGRESS`, `COMPLETE`, `BLOCKED`, with a closed list of legal pairs. Neither is the existing `vehicle_models.status` (`CURRENT`/`HISTORICAL`/
`UNVERIFIED`), which says whether the car is on sale.

`DISCOVERED` means TDR recognises a real canonical vehicle identity. It does **not** mean its attributes are complete or that it may appear in the
consumer catalog. Internal market data and external crosswalks MAY reference a `DISCOVERED` identity; consumer publication is a separate gate
(`PUBLISH`, admin only, requires `VERIFIED`). Bootstrap performs exactly one lifecycle act: `CREATE` into (`DISCOVERED`, `PENDING`). Skipping states and
publishing from `DISCOVERED` are forbidden transitions (tested). `WITHDRAWN` ids are never reused.

---

## 6. Eligibility procedure

Gates run per subject in this order. Each gate may fire reason codes (appendix B). Nothing short-circuits except G0's `NOT_ACTIVATED`.

| Gate | Fires | Rule |
|---|---|---|
| **G0 activation** | `NOT_ACTIVATED`, `STRUCTURAL_CONFLICT` | The resolution outcome MUST equal `activation.required_ir_outcome`. `STRUCTURAL_REVIEW` raises `STRUCTURAL_CONFLICT` and continues; every other outcome stops with `NOT_ACTIVATED`. |
| **G1 subject** | `PROVIDER_IDENTITY_PROVISIONAL`, `PROVIDER_RAW_NAME`, `NAME_UNSPECIFIED`, `BRAND_UNKNOWN`, `BRAND_NOT_IN_TDR`, `STRUCTURAL_CONFLICT` | `identity_status` other than `settled` maps through `subject.status_codes`. A separator in the id or name, or a registration-code-shaped token, is `PROVIDER_RAW_NAME` even if the adapter said `settled`. No usable token, or a placeholder name, is `NAME_UNSPECIFIED`. A brand relation not in `brand.creatable_relations` maps through `brand.relation_codes`. |
| **G2 state** | `IDENTITY_ALREADY_DISCOVERED`, `DUPLICATE_CANONICAL_SUSPECTED`, `IDENTITY_PREVIOUSLY_WITHDRAWN` | An existing binding for `(provider, entity_id)`, or an identity of the same brand with the same identity key: pending states → already discovered; `VERIFIED`/`PUBLISHED`/legacy → duplicate suspected; `WITHDRAWN` → previously withdrawn. |
| **G3 lineage** | `LINEAGE_CONTINUITY_EXISTING_IDENTITY`, `LINEAGE_UNRESOLVED`, `PROVIDER_LINEAGE_AMBIGUOUS` | §9. |
| **G4 relations** | per `relations.*_codes` and `batch.*` | Subject→target by peer-state class (§8.1); subject→subject §8.2. |
| **G5 shape** | `POSSIBLE_MODEL_CODE`, `POSSIBLE_TRIM_NOT_MODEL`, `POSSIBLE_POWERTRAIN_DERIVATIVE`, `POSSIBLE_BODY_VARIANT`, `POSSIBLE_GENERATION_VARIANT` | Lexicon and patterns in `shape.*` applied to the subject's own tokens (and displacement patterns to the display name). Lexical, so always only a suspicion. |
| **G6 evidence** | `INSUFFICIENT_IDENTITY_EVIDENCE` | Evaluated only if no HOLD code has fired. The provider MUST be in `evidence.providers` with `may_create`, a valid item of its `base_kind` MUST exist (known kind, non-blank `ref`), and the best valid tier MUST reach `evidence.required_tier.create_clean`. |
| **G7 allocation** | `CANONICAL_ID_COLLISION`, `NAME_UNSPECIFIED` | §10, only for subjects that survive clearing. |

### 6.1 Folding

The outcome is the strongest route among the surviving codes: any `HOLD` code → `HOLD`; else any `REVIEW` code → `IDENTITY_REVIEW`; else
`CREATE_IDENTITY` with `NEW_IDENTITY_CONFIRMED`. The primary reason is the surviving code of that route with the lowest `primary_rank`.
`reason_codes` are the surviving codes and informational codes ordered by `(primary_rank, code)`.

### 6.2 Clearing

Before folding, codes may be cleared, in this order, and every clearing is recorded in `evidence_basis.cleared_flags`:

1. **By evidence.** If an item of tier ≥ `evidence.soft_clear.min_tier` carries the attestation `evidence.soft_clear.required_attestation`, every fired code whose
   registry `clearable` is `evidence` or `evidence_or_admin` is cleared (`FLAG_CLEARED_BY_EVIDENCE`). Only the **lexical** shape suspicions are clearable this way.
   Evidence about the real world cannot settle how TDR models its own catalog, nor a provider's own doubt about its identity.
2. **By admin.** An `admin_directives` entry with `action: CREATE_IDENTITY` whose `review_fingerprint` equals this subject's current review fingerprint
   clears every code marked `admin` or `evidence_or_admin` (`ADMIN_STRUCTURE_DECISION_APPLIED`; `creator_type` becomes `admin`). Codes marked `never` survive and add
   `ADMIN_DECISION_CANNOT_CLEAR_HARD_FLAG`. A directive bound to a different fingerprint is ignored: changed evidence reopens the question.
   `DO_NOT_CREATE` bound to the current fingerprint yields `HOLD` / `ADMIN_DECLINED` and is not raised again.

### 6.3 Evidence tiers

Tier 0 provider identity (settled, structurally clean); 1 independent second provider; 2 regulatory record, homologation, Eco Sticker; 3 official manufacturer,
distributor, price list, launch material (`evidence.kind_tiers`). The decision records exactly what justified creation: `evidence_basis.tier`, `kinds`,
`refs`, `cleared_flags`. Research is never required to *build* the architecture; v1 creation needs only tier 0.

---

## 7. Outcomes

| Outcome | Meaning | Carries |
|---|---|---|
| `CREATE_IDENTITY` | A shell may be created. | identity, write plan, event, creator type |
| `IDENTITY_REVIEW` | A human must decide; nothing is created. | review block (queue, priority band, alert) |
| `HOLD` | Nothing to decide yet (wait for the provider, for evidence, or the case is already handled). | review block; no queue for silent holds |

Reason codes (appendix B) carry `route`, `clearable` and `primary_rank`. Codes are never renamed; a changed meaning is a new code.

### 7.1 Volume

`units` selects a band (`priority.bands`) used only for `review.priority_band` and the alert `HIGH_VOLUME_UNRESOLVED` on non-create, non-silent outcomes.
It is never a creation criterion in either direction: a model with 3 registrations is created; a raw name with 4,300 is held and alerted.

---

## 8. Batch-level arbitration

Decisions are made on the whole snapshot, never row by row. Before any creation: existing identities (all states), pending identities, current subjects,
existing bindings, lineage events, and the relations among them are consulted.

### 8.1 Subject versus existing or pending identities (`TARGET` relations)

The relation is classed by `relations.name_classes` and the peer by `relations.peer_state_classes`; the code comes from `canonical_codes`, `pending_codes` or
`withdrawn_codes`. Equal-class names are duplicates; `SUBJECT_FINER` → `PROVIDER_FINER_THAN_TDR`; `SUBJECT_COARSER` → `PROVIDER_COARSER_THAN_TDR`; `SIBLING` →
`EXISTING_IDENTITY_SUSPECTED`. `CONTRADICTION` and `UNAVAILABLE` are no relation. The brand is part of identity, so the same name under another brand is no relation.

### 8.2 Subject versus subject (same snapshot)

A peer that is itself held by a gate in `batch.ignore_peers_holding` (provisional, raw, unspecified, unknown brand) is ignored: junk never blocks a clean subject.
Otherwise, for one provider: equal names → `STRUCTURAL_CONFLICT` + `DUPLICATE_CANONICAL_SUSPECTED` on **both**; containment → `STRUCTURAL_CONFLICT` on the finer
member only (`Honda City` is created; `Honda City Hatchback` is a question); siblings → `STRUCTURAL_CONFLICT` on both. Across providers, equal names **coalesce**:
among subjects that are otherwise creatable, one representative (best `(provider_priority, provider, entity_id)`) carries the plan with every other subject as an
`ADDITIONAL` alias and tier-1 corroboration (`MULTI_PROVIDER_CORROBORATION`); each other member is `HOLD` / `IDENTITY_COALESCED`. A pair of which one member is not
creatable does not coalesce.

### 8.3 Collisions between creators

After allocation, two representatives that derive the same canonical id, slug or identity key both receive `CANONICAL_ID_COLLISION`. There is no first-wins.

---

## 9. Provider lineage

The snapshot's lineage events are read simultaneously against the pre-change state (never chained). `lineage.actions` maps each case to one of: `HOLD_CONTINUITY`,
`REVIEW_AMBIGUOUS`, `PROCEED_WITH_RETIRED_ALIAS`, `HOLD_UNRESOLVED`.

| Case (subject is…) | Action | Why |
|---|---|---|
| new id of a `RENAME`, old id bound to an identity | `HOLD_CONTINUITY` | The identity continues; no new model; a suggested alias binding is attached. |
| new id of a `RENAME`, old id unbound | `PROCEED_WITH_RETIRED_ALIAS` | Plain new identity; the old id is kept as a `RETIRED_PREDECESSOR` alias. |
| new id of a `MERGE`, old ids bound to exactly one identity | `HOLD_CONTINUITY` | Continues that identity. |
| new id of a `MERGE`, old ids bound to several identities | `REVIEW_AMBIGUOUS` | TDR identities are never merged automatically. |
| new id of a `MERGE`, no old id bound | `PROCEED_WITH_RETIRED_ALIAS` | All old ids become retired aliases. |
| parent or child of any `SPLIT`, applied or not | `REVIEW_AMBIGUOUS` | Whether the child is a distinct TDR model is a human decision; the parent entity is never duplicated. |
| old id of a rename/merge that is still a live subject | `REVIEW_AMBIGUOUS` | Provider semantics undefined (open question to Ice). |
| on a cycle of events | `HOLD_UNRESOLVED` | Cannot be read without guessing. |

`HOLD_CONTINUITY` → `LINEAGE_CONTINUITY_EXISTING_IDENTITY`; `REVIEW_AMBIGUOUS` → `PROVIDER_LINEAGE_AMBIGUOUS`; `HOLD_UNRESOLVED` → `LINEAGE_UNRESOLVED`.
Declared changes without a machine-readable source refuse the run; nothing is inferred from prose.

---

## 10. Canonical id allocation

1. `canonical_name` and `brand_id` as in §4.3. The local segment is `allocation.local_segment_function` of the canonical name — the **one** TDR slug rule, never
   reimplemented here (it folds Thai marks and strips corporate words; ENGINE_RULES §3 item 1). A segment in `allocation.forbidden_local_segments` (`unnamed`) → `NAME_UNSPECIFIED`.
2. `canonical_id = {brand_id}.{local}` (`allocation.id_format`); `slug = {brand_id}-{local}` with `_`→`-`.
3. A collision is any existing row — in any state, **deleted or `WITHDRAWN` included** — with that canonical id or slug. The same identity key is not a collision; it is §6 G2.
   A collision yields `CANONICAL_ID_COLLISION` → `IDENTITY_REVIEW`. v1 has no auto-suffix: a suffix would hide exactly the slug folding that produced the collision.
4. The id never changes when a name later changes (VEHICLE_DB_V3 §3); provider ids are aliases; source versions are provenance only.

---

## 11. Idempotency and concurrency

Three keys: `idempotency_key` = hash of `(provider, entity_id)`; `identity_key` (§4.3); `canonical_id`. The writer enforces, in one transaction per plan:

1. take `lock_key` (a per-brand advisory lock; **every** model-creating path, including admin, MUST take it);
2. verify every `preconditions` entry (`brand_exists`, `canonical_id_absent`, `slug_absent`, `identity_key_absent`, `alias_absent_or_same`, `brand_identity_digest`);
3. if the identity already exists with the same decision fingerprint and identity key → `ALREADY_APPLIED` (no write, no second event);
4. otherwise any violated precondition → `STALE:<kind>`: the plan is **discarded and the subject re-decided on fresh state**, never forced;
5. insert shell, aliases, provenance, outbox event and mapping intent together; unique constraints (canonical id, slug, `(brand_id, identity_key)`, `(provider, external_id)`, `event_id`) are the last line of defence.

`brand_identity_digest` covers the brand's `(canonical_id, state, deleted)` rows: any change in the brand since the decision makes the plan stale. After a successful apply the
next run sees the binding and returns `IDENTITY_ALREADY_DISCOVERED`. A plan that is `STALE` because an admin created the model meanwhile re-decides as `NOT_ACTIVATED` or a duplicate suspicion.

---

## 12. Output

### 12.1 Records

`decision.schema.json`: one `decision` per subject ordered by `(provider, entity_id)`, or one `refusal` for the run. A decision holds contract and policy
version + digest, provider, source version, subject, outcome, primary reason, reason codes, evidence basis, creator type, identity (create only), existing identity,
suggested binding (informational; Bootstrap never binds a provider id to an *existing* identity), batch group, review block, write plan (create only) and fingerprints.

### 12.2 Write plan

Operations (`writes.operations`): `RESERVE_CANONICAL_ID`, `INSERT_IDENTITY_SHELL` (only `writes.shell_columns`), `INSERT_EXTERNAL_ALIAS`, `INSERT_PROVENANCE`, `ENQUEUE_EVENT`,
`PROPOSE_ORIGIN_MAPPING` (state `AUTO`, method `ORIGIN`, applied by the Identity Resolution mapping writer, not by Bootstrap). Each carries an idempotency key. `apply_mode`
is `PROPOSE` (an admin approves a card) until the owner amends VEHICLE_DB_V3 §4 to let a deterministic machine actor create hidden shells; the plan is identical in both modes.
`deferred_fields` (`run_id`, `created_at`, `actor`, `occurred_at`) are filled by `finalize` at apply time and nowhere else.

### 12.3 Fingerprints

Canonical JSON (sorted keys, compact, UTF-8), SHA-256. `fingerprints.decision` covers the policy digest, review fingerprint, outcome, codes, evidence tier/kinds/cleared flags and
the identity id. `fingerprints.review` covers the question: provider, entity id, brand, identity key, the fired non-informational codes and the relation signature.
Neither contains `units`, `source_version`, `first_seen_period`, evidence `refs`, run id or time (`fingerprint.never_in_fingerprints`).

### 12.4 Provenance

The `INSERT_PROVENANCE` row answers *why does this canonical vehicle exist?*: provider, external id, source version, first seen period (earliest across coalesced subjects),
reason codes, decision fingerprint, evidence tier/kinds/refs, policy and contract version, creator type (`machine`/`admin`), identity key, apply mode, and at apply time run id,
timestamp and actor. It lives in an append-only table the enrichment subsystem never writes (`lifecycle.provenance_immutable_after`).

---

## 13. Persistence boundary

The write path is specified, not built; see `../../INTEGRATION.md` for the analysis of the live schema, the smallest change required, the conflicts found and the proposal.
In short: the live `vehicle_models` cannot safely hold a `DISCOVERED` row today; no migration is proposed for execution; no governed write layer exists yet (Phase 1).

---

## 14. Hand-off: `VEHICLE_IDENTITY_CREATED`

`event.schema.json`. Enqueued in the same transaction as the identity (transactional outbox, `event.outbox`), delivered at least once, ordered per `canonical_model_id`, consumer idempotent
on `event_id` (hash of event name, version and canonical id, so one identity yields one event for ever). Payload: canonical id, canonical name, brand id, `DISCOVERED`/`PENDING`,
source (provider, external id, source version, first seen period), all aliases, creation record (reason codes, decision fingerprint, creator type, evidence, policy/contract version,
apply mode), and `enrichment_hints`: known names, **excluded neighbours** (identities a human decided this is not) and **unverified provider hints** (never written to Vehicle Master).
The enrichment subsystem turns the event into an `agent_jobs` row of kind `ENRICH_IDENTITY` (VEHICLE_DB_V3 §3); it claims (`CLAIM`), may release or block, and proposes `VERIFY`.
That subsystem is out of scope.

---

## 15. Interface with Identity Resolution (PR #200 stays untouched)

Bootstrap consumes, per subject, `resolution.outcome`, `resolution.reason_codes`, brand resolution (`brand_id`, relation) and `relations`. The amendments requested of
Identity Resolution, as a proposal only, are in `../../INTEGRATION.md` §3. Until they land an adapter can build every field from the existing IR record
(`alternatives`, `excluded_by`, brand codes), so the two subsystems are testable and shippable independently.

---

## 16. The golden corpus and how bugs enter

`cases.jsonl`, one object per line (`case.schema.json`), kinds `decide`, `apply`, `allocate`, `lifecycle`. Tests require: every case validates; every taxonomy id and every
non-refusal reason code is asserted by at least one case; every `decide` input validates against `input.schema.json` and every output against `decision.schema.json`/`event.schema.json`;
the reference oracle (`tests/identity_bootstrap/ib_reference.py`) reproduces every expectation; and these properties hold for **every** case: volume independence, order independence,
source-version independence, determinism, no attribute outside the shell, `HOLD`/`REVIEW` carry no plan, one `CREATE` per canonical id, apply → re-decide converges.
The oracle was written by the author of the contract: agreement shows consistency, not that the rules are right.

**A new bug:** add or extend a taxonomy entry → add a failing corpus line with the smallest input → change `policy.yaml` (or, later, the engine) until it passes → bump `version` if behaviour
moved → regenerate the appendices. Never a Python special case.

---

## 17. Versioning

`contract/v1/` is immutable once adopted; a behavioural change is `v2/` with a migration note. Within a version the policy `version` integer changes with any behaviour-bearing key.
The policy digest is in every decision.

---

## 18. Open questions for the owner

See `README.md` §6.

---

## Appendix A — Policy index

<!-- BEGIN GENERATED: policy_index -->
| Key | Value | Provenance |
|---|---|---|
| `activation.required_ir_outcome` | `"NO_CANDIDATE"` | inherited |
| `activation.structural_review_outcome` | `"STRUCTURAL_REVIEW"` | inherited |
| `subject.creatable_identity_statuses` | `["settled"]` | observed |
| `subject.status_codes` | `{"provisional": "PROVIDER_IDENTITY_PROVISIONAL", "unmapped_name": "PROVIDER_RAW_NAME"}` | observed |
| `subject.unavailable_name_values` | `["ไม่ระบุ", "unknown", "na", "none", "other", "อื่นๆ"]` | observed |
| `subject.raw_name` | `{"separator_characters": ["\|"], "registration_code_token_pattern": "^(?=.*[a-z])(?=.*[0-9])[a-z0-9]{9,}$"}` | observed |
| `brand.creatable_relations` | `["EXACT", "ALIAS_SAME", "ALIAS_RELABEL"]` | proposal |
| `brand.relation_codes` | `{"UNKNOWN": "BRAND_UNKNOWN", "NOT_IN_TDR": "BRAND_NOT_IN_TDR", "ALIAS_RELATED": "STRUCTURAL_CONFLICT"}` | proposal |
| `lexical.token_boundary_characters` | `["-", "_", "/", ".", "+", "&", "\|", "(", ")"]` | observed |
| `lexical.generic_tokens` | `["series", "class"]` | observed |
| `shape.model_code` | `{"token_patterns": ["^[a-z]{1,3}[0-9]{3}[a-z]{0,3}$"]}` | proposal |
| `shape.trim` | `{"tokens": ["sport", "sports", "premium", "luxury", "limited", "edition", "plus", "pro", "ultra", "base", "standard", "deluxe", "comfort", "elite", "exclusive", "signature", "gt", "gti", "rs", "amg", "ex", "lx"]}` | proposal |
| `shape.powertrain` | `{"tokens": ["ev", "bev", "hev", "phev", "mhev", "hybrid", "electric", "diesel", "petrol", "gasoline", "turbo", "cng", "lpg", "awd", "4wd", "2wd", "fwd", "rwd", "4x4", "4x2", "cvt", "dct", "manual"], "name_patterns": ["(?<![0-9])[0-9]\\.[0-9]{1,2}[a-z]?(?![0-9])"]}` | proposal |
| `shape.body` | `{"tokens": ["hatchback", "hatch", "sedan", "wagon", "estate", "coupe", "convertible", "cabriolet", "roadster", "cab", "double", "single", "smart", "pickup", "van", "suv", "mpv", "crossover", "truck"]}` | proposal |
| `shape.generation` | `{"tokens": ["new", "facelift", "refresh", "redesign", "generation", "gen", "โฉมใหม่", "ไมเนอร์เชนจ์", "เจนใหม่"], "token_patterns": ["^gen[0-9]+$", "^mk[0-9]+$", "^mk[ivx]+$", "^(19\|20)[0-9]{2}$", "^[0-9]{1,2}(st\|nd\|rd\|th)$"]}` | proposal |
| `shape.codes` | `{"model_code": "POSSIBLE_MODEL_CODE", "trim": "POSSIBLE_TRIM_NOT_MODEL", "powertrain": "POSSIBLE_POWERTRAIN_DERIVATIVE", "body": "POSSIBLE_BODY_VARIANT", "generation": "POSSIBLE_GENERATION_VARIANT"}` | proposal |
| `relations.name_classes` | `{"duplicate": ["EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV", "FUZZY"], "finer": ["SUBJECT_FINER"], "coarser": ["SUBJECT_COARSER"], "sibling": ["SIBLING"], "ignored": ["CONTRADICTION", "UNAVAILABLE"]}` | proposal |
| `relations.peer_state_classes` | `{"DISCOVERED": "pending", "ENRICHING": "pending", "VERIFIED": "canonical", "PUBLISHED": "canonical", "WITHDRAWN": "withdrawn", "legacy": "canonical"}` | proposal |
| `relations.canonical_codes` | `{"duplicate": "DUPLICATE_CANONICAL_SUSPECTED", "finer": "PROVIDER_FINER_THAN_TDR", "coarser": "PROVIDER_COARSER_THAN_TDR", "sibling": "EXISTING_IDENTITY_SUSPECTED"}` | proposal |
| `relations.pending_codes` | `{"duplicate": "IDENTITY_ALREADY_DISCOVERED", "finer": "EXISTING_IDENTITY_SUSPECTED", "coarser": "EXISTING_IDENTITY_SUSPECTED", "sibling": "EXISTING_IDENTITY_SUSPECTED"}` | proposal |
| `relations.withdrawn_codes` | `{"duplicate": "IDENTITY_PREVIOUSLY_WITHDRAWN"}` | proposal |
| `batch.ignore_peers_holding` | `["PROVIDER_IDENTITY_PROVISIONAL", "PROVIDER_RAW_NAME", "NAME_UNSPECIFIED", "BRAND_UNKNOWN"]` | proposal |
| `batch.same_provider` | `{"duplicate": ["STRUCTURAL_CONFLICT", "DUPLICATE_CANONICAL_SUSPECTED"], "finer": ["STRUCTURAL_CONFLICT"], "sibling": ["STRUCTURAL_CONFLICT"]}` | proposal |
| `batch.cross_provider` | `{"duplicate": "COALESCE", "finer": ["STRUCTURAL_CONFLICT"], "sibling": ["STRUCTURAL_CONFLICT"]}` | proposal |
| `batch.provider_priority` | `["ice", "dlt"]` | proposal |
| `lineage.actions` | `{"rename_old_bound": "HOLD_CONTINUITY", "rename_old_unbound": "PROCEED_WITH_RETIRED_ALIAS", "merge_old_bound_to_one": "HOLD_CONTINUITY", "merge_old_bound_to_many": "REVIEW_AMBIGUOUS", "merge_none_bound": "PROCEED_WITH_RETIRED_ALIAS", "split_any_role": "REVIEW_AMBIGUOUS", "cycle": "HOLD_UNRESOLVED"}` | proposal |
| `evidence.kind_tiers` | `{"PROVIDER_IDENTITY": 0, "SECOND_PROVIDER_IDENTITY": 1, "REGULATORY_RECORD": 2, "HOMOLOGATION": 2, "ECO_STICKER": 2, "OFFICIAL_PRICE_LIST": 3, "OFFICIAL_DISTRIBUTOR": 3, "OFFICIAL_LAUNCH_MATERIAL": 3, "OFFICIAL_MANUFACTURER": 3}` | proposal |
| `evidence.providers` | `{"ice": {"may_create": true, "base_kind": "PROVIDER_IDENTITY"}, "dlt": {"may_create": true, "base_kind": "SECOND_PROVIDER_IDENTITY"}}` | proposal |
| `evidence.required_tier` | `{"create_clean": 0}` | proposal |
| `evidence.soft_clear` | `{"min_tier": 2, "required_attestation": "is_model_nameplate"}` | proposal |
| `evidence.corroboration_kind` | `"SECOND_PROVIDER_IDENTITY"` | proposal |
| `allocation.id_format` | `"{brand_id}.{local}"` | inherited |
| `allocation.local_segment_function` | `"vehreg.normalize.slug"` | inherited |
| `allocation.forbidden_local_segments` | `["unnamed"]` | inherited |
| `allocation.canonical_name` | `{"strip_brand_prefix": true, "collapse_whitespace": true}` | inherited |
| `allocation.collision_resolution` | `"REVIEW"` | inherited |
| `allocation.tombstones_reserve_ids` | `true` | inherited |
| `admin.directive_actions` | `["CREATE_IDENTITY", "DO_NOT_CREATE"]` | proposal |
| `admin.creator_type_machine` | `"machine"` | proposal |
| `admin.creator_type_admin` | `"admin"` | proposal |
| `writes.apply_mode` | `"PROPOSE"` | inherited |
| `writes.actor_kind` | `"BOOTSTRAP"` | inherited |
| `writes.required_permission` | `"CREATE_DISCOVERED_SHELL"` | inherited |
| `writes.initial_state` | `{"identity_state": "DISCOVERED", "enrichment_state": "PENDING"}` | inherited |
| `writes.shell_columns` | `["canonical_id", "brand_id", "slug", "name_en", "identity_state", "enrichment_state"]` | inherited |
| `writes.forbidden_attribute_fields` | `["segment", "body_type", "cab_type", "registration_type", "market_scope", "powertrain", "market_position", "production", "launch_date", "engine", "motor", "battery", "price", "retail_price_min", "retail_price_max", "platform", "origin_country", "description", "name_th", "generation_id"]` | inherited |
| `writes.operations` | `["RESERVE_CANONICAL_ID", "INSERT_IDENTITY_SHELL", "INSERT_EXTERNAL_ALIAS", "INSERT_PROVENANCE", "ENQUEUE_EVENT", "PROPOSE_ORIGIN_MAPPING"]` | inherited |
| `writes.lock_key` | `"identity_bootstrap:{brand_id}"` | inherited |
| `writes.conflict_policy` | `"DO_NOTHING_VERIFY_SAME"` | inherited |
| `event.name` | `"VEHICLE_IDENTITY_CREATED"` | inherited |
| `event.version` | `1` | inherited |
| `event.outbox` | `"vehicle_identity_events"` | inherited |
| `event.delivery` | `"at_least_once"` | inherited |
| `event.include_provider_hints` | `true` | inherited |
| `priority.bands` | `[{"min_units": 0, "band": "LOW"}, {"min_units": 100, "band": "MEDIUM"}, {"min_units": 2000, "band": "HIGH"}]` | proposal |
| `priority.unknown_units_band` | `"UNRANKED"` | proposal |
| `priority.queues` | `{"IDENTITY_REVIEW": "identity_review", "HOLD": "identity_hold_watch"}` | proposal |
| `priority.silent_hold_codes` | `["NOT_ACTIVATED", "IDENTITY_ALREADY_DISCOVERED", "IDENTITY_COALESCED", "ADMIN_DECLINED", "LINEAGE_CONTINUITY_EXISTING_IDENTITY"]` | proposal |
| `priority.alert_bands` | `["HIGH"]` | proposal |
| `fingerprint.algorithm` | `"sha256"` | proposal |
| `fingerprint.decision_includes_policy_digest` | `true` | proposal |
| `fingerprint.never_in_fingerprints` | `["units", "source_version", "first_seen_period", "run_id", "created_at"]` | proposal |
<!-- END GENERATED: policy_index -->

## Appendix B — Reason-code registry

<!-- BEGIN GENERATED: reason_codes -->
| Code | Area | Kind | Route | Clearable | Rank | Meaning |
|---|---|---|---|---|---|---|
| `NOT_ACTIVATED` | ACTIVATION | gate | HOLD | never | 10 | Identity Resolution did not end in NO_CANDIDATE for this subject (it AUTO/PROPOSEd, was AMBIGUOUS, PROTECTED, SUPPRESSED or INSUFFICIENT_DATA); Bootstrap has nothing to do. |
| `IDENTITY_ALREADY_DISCOVERED` | STATE | gate | HOLD | never | 11 | This external identity is already bound to an identity, or an identity with the same brand and name key already exists in DISCOVERED/ENRICHING/VERIFIED/PUBLISHED. Idempotent no-op. |
| `IDENTITY_COALESCED` | STATE | gate | HOLD | never | 12 | Another subject in this batch (a second provider) names the same identity; one plan creates it and carries this subject as an additional alias. |
| `LINEAGE_CONTINUITY_EXISTING_IDENTITY` | LINEAGE | gate | HOLD | never | 13 | Provider lineage (rename, or a merge of ids bound to one identity) shows this subject continues an identity that already exists; a new TDR model is never created. A suggested alias binding is attached. |
| `LINEAGE_UNRESOLVED` | LINEAGE | gate | HOLD | never | 14 | The provider's identity-change graph for this subject is cyclic or otherwise cannot be read without guessing. |
| `ADMIN_DECLINED` | STATE | gate | HOLD | never | 15 | An admin answered the review for this exact fingerprint with DO_NOT_CREATE; it is not raised again unless the evidence changes. |
| `PROVIDER_IDENTITY_PROVISIONAL` | SUBJECT | gate | HOLD | never | 20 | The provider itself marks the identity provisional (Ice '__provisional' or 'BRAND\|MODEL'); wait for the provider to settle it. |
| `PROVIDER_RAW_NAME` | SUBJECT | gate | HOLD | never | 21 | The identity is an unresolved raw registration name or code (identity_status unmapped_name, a separator in the id, or a registration-code-shaped token). |
| `NAME_UNSPECIFIED` | SUBJECT | gate | HOLD | never | 22 | The name is blank, 'ไม่ระบุ', 'unknown' or an equivalent placeholder, or no token remains after brand-prefix removal. |
| `BRAND_UNKNOWN` | SUBJECT | gate | HOLD | never | 23 | The brand is blank, a placeholder, or cannot be resolved to a single TDR brand. |
| `INSUFFICIENT_IDENTITY_EVIDENCE` | EVIDENCE | gate | HOLD | never | 30 | The evidence presented does not reach the tier the classification of this subject requires, or the provider is not allowed to create identities, or no citable evidence reference exists. |
| `BRAND_NOT_IN_TDR` | SUBJECT | flag | REVIEW | never | 40 | The brand is clean but TDR has no such brand. Creating a brand is a separate governed action; Bootstrap never creates one. |
| `STRUCTURAL_CONFLICT` | ACTIVATION | flag | REVIEW | admin | 41 | Identity Resolution raised a structural review, or subjects in this batch are structurally ambiguous with each other (equal, sibling or containing names from one provider). |
| `DUPLICATE_CANONICAL_SUSPECTED` | RELATION | flag | REVIEW | never | 42 | The name is equal (exact, alias, token-equivalent or one-edit fuzzy) to an existing canonical model or alias of the same brand family. Bind it; do not create it. |
| `EXISTING_IDENTITY_SUSPECTED` | RELATION | flag | REVIEW | admin | 43 | The name shares a nameplate stem with an existing or pending identity (sibling names, a rename or rebadge candidate); it may be a variant, generation or alias of it. |
| `PROVIDER_FINER_THAN_TDR` | RELATION | flag | REVIEW | admin | 44 | The subject's name contains an existing TDR model's name plus extra tokens (Honda City Hatchback vs TDR City); the provider may be finer-grained than TDR's deliberate model. |
| `PROVIDER_COARSER_THAN_TDR` | RELATION | flag | REVIEW | admin | 45 | The subject's name is contained in an existing TDR model's name (Hilux Travo vs TDR Hilux Travo Cab); the provider aggregates what TDR splits. |
| `IDENTITY_PREVIOUSLY_WITHDRAWN` | STATE | flag | REVIEW | admin | 46 | A WITHDRAWN identity with the same brand and name key exists; it is never silently re-created or reinstated. |
| `PROVIDER_LINEAGE_AMBIGUOUS` | LINEAGE | flag | REVIEW | admin | 47 | The subject takes part in a provider SPLIT, or in a MERGE of ids bound to different identities; whether it is a distinct TDR model is a human decision. No TDR entity is created, merged or duplicated automatically. |
| `POSSIBLE_MODEL_CODE` | SHAPE | flag | REVIEW | evidence_or_admin | 50 | A token has the shape of a model/displacement code (E300, C350) rather than a nameplate. |
| `POSSIBLE_TRIM_NOT_MODEL` | SHAPE | flag | REVIEW | evidence_or_admin | 51 | A token is a trim or grade word (Sport, Premium, Limited, Pro, Max, ...). |
| `POSSIBLE_POWERTRAIN_DERIVATIVE` | SHAPE | flag | REVIEW | evidence_or_admin | 52 | A token is an engine/powertrain/drivetrain word or displacement (EV, HEV, 2.4, AWD, Diesel). |
| `POSSIBLE_BODY_VARIANT` | SHAPE | flag | REVIEW | evidence_or_admin | 53 | A token is a body-style or cab word (Hatchback, Sedan, Double Cab). |
| `POSSIBLE_GENERATION_VARIANT` | SHAPE | flag | REVIEW | evidence_or_admin | 54 | A token is a generation, facelift or model-year marker (Gen 2, Mk3, New, 2025). |
| `CANONICAL_ID_COLLISION` | ALLOCATION | flag | REVIEW | never | 60 | The deterministic canonical id is already taken by a different identity (or two creatable subjects in this batch derive the same id). Ids are never auto-suffixed. |
| `NEW_IDENTITY_CONFIRMED` | OUTCOME | decision | CREATE | never | 90 | Settled, structurally clean provider identity with no credible existing counterpart; evidence tier requirement met. |
| `FLAG_CLEARED_BY_EVIDENCE` | INFO | info | NONE | never | 95 | A lexical suspicion was cleared by tier>=2 evidence attesting a model nameplate. The cleared codes are listed in the evidence basis. |
| `ADMIN_STRUCTURE_DECISION_APPLIED` | INFO | info | NONE | never | 96 | An admin CREATE_IDENTITY decision bound to this review fingerprint cleared admin-clearable review codes. |
| `ADMIN_DECISION_CANNOT_CLEAR_HARD_FLAG` | INFO | info | NONE | never | 97 | An admin directive was present but a code that no directive can clear is still firing; the directive had no effect on it. |
| `MULTI_PROVIDER_CORROBORATION` | INFO | info | NONE | never | 98 | Two or more providers independently named the same identity in this batch (evidence tier 1). |
| `INPUT_SCHEMA_INVALID` | INPUT | refusal | REFUSE | never | 100 | The snapshot does not validate against input.schema.json. |
| `INPUT_SOURCE_VERSION_MISSING` | INPUT | refusal | REFUSE | never | 101 | source_version.label is empty; provenance could not be written. |
| `INPUT_DUPLICATE_SUBJECT_ID` | INPUT | refusal | REFUSE | never | 102 | Two subjects share (provider, entity_id). |
| `INPUT_POLICY_VERSION_UNSUPPORTED` | INPUT | refusal | REFUSE | never | 103 | snapshot.policy_version is not the policy version the engine holds. |
| `INPUT_RESOLUTION_MISSING` | INPUT | refusal | REFUSE | never | 104 | A subject carries no Identity Resolution result. Bootstrap never runs on raw provider subjects. |
| `INPUT_LINEAGE_SOURCE_MISSING` | INPUT | refusal | REFUSE | never | 105 | The provider declared identity changes but supplied no machine-readable lineage source; nothing is inferred from prose. |
<!-- END GENERATED: reason_codes -->

## Appendix C — Edge-case taxonomy

<!-- BEGIN GENERATED: taxonomy -->
| Id | Expected outcome | Codes | Edge case |
|---|---|---|---|
| `NEW-01` | CREATE_IDENTITY | `NEW_IDENTITY_CONFIRMED` | Genuinely new clean model with a known brand |
| `NEW-02` | CREATE_IDENTITY | `NEW_IDENTITY_CONFIRMED` | New model with very low (or zero or unknown) registration volume |
| `NEW-03` | CREATE_IDENTITY | `NEW_IDENTITY_CONFIRMED` | Same nameplate under another brand (rebadge) is a separate identity |
| `NEW-04` | CREATE_IDENTITY | `NEW_IDENTITY_CONFIRMED` | Canonical name derivation (whole-token brand prefix |
| `NEW-05` | CREATE_IDENTITY | `NEW_IDENTITY_CONFIRMED` | Spelling variants of one nameplate produce one identity key |
| `VOL-01` | CREATE_IDENTITY | `NEW_IDENTITY_CONFIRMED` | Low volume never prevents creation |
| `VOL-02` | HOLD | `PROVIDER_RAW_NAME` | High volume never causes creation of a raw identity; it only raises the alert band |
| `ACT-01` | HOLD | `NOT_ACTIVATED` | Identity Resolution found |
| `ACT-02` | IDENTITY_REVIEW | `STRUCTURAL_CONFLICT` | Identity Resolution raised a structural review |
| `SUBJ-01` | HOLD | `PROVIDER_IDENTITY_PROVISIONAL` | Provisional provider identity |
| `SUBJ-02` | HOLD | `PROVIDER_RAW_NAME` | Raw registration name or code |
| `SUBJ-03` | HOLD | `NAME_UNSPECIFIED` | Blank |
| `SUBJ-04` | HOLD | `NAME_UNSPECIFIED` | A name the TDR slug rule reduces to nothing |
| `BRND-01` | HOLD | `BRAND_UNKNOWN` | Blank or unresolved brand |
| `BRND-02` | IDENTITY_REVIEW | `BRAND_NOT_IN_TDR` | Clean brand that TDR does not have |
| `BRND-03` | IDENTITY_REVIEW | `STRUCTURAL_CONFLICT` | Only a RELATED brand attribution (Maxus vans filed under MG) |
| `REL-01` | IDENTITY_REVIEW | `DUPLICATE_CANONICAL_SUSPECTED` | Exact duplicate of an existing canonical model |
| `REL-02` | IDENTITY_REVIEW | `DUPLICATE_CANONICAL_SUSPECTED` | Spelling or format variant |
| `REL-03` | IDENTITY_REVIEW | `DUPLICATE_CANONICAL_SUSPECTED` | Alias under a relabelled brand |
| `REL-04` | IDENTITY_REVIEW | `PROVIDER_FINER_THAN_TDR` | Subject name contains an existing model (trim |
| `REL-05` | IDENTITY_REVIEW | `PROVIDER_COARSER_THAN_TDR` | Subject name is contained in existing model names |
| `REL-06` | IDENTITY_REVIEW | `EXISTING_IDENTITY_SUSPECTED` | Sibling names sharing a nameplate stem with an existing model |
| `REL-07` | IDENTITY_REVIEW | `EXISTING_IDENTITY_SUSPECTED` | Sibling of a DISCOVERED or ENRICHING identity |
| `REL-08` | CREATE_IDENTITY | `NEW_IDENTITY_CONFIRMED` | Brand is part of identity |
| `GRAN-01` | IDENTITY_REVIEW | `PROVIDER_FINER_THAN_TDR`, `STRUCTURAL_CONFLICT` | Provider finer than TDR (City / City Hatchback) |
| `GRAN-02` | IDENTITY_REVIEW | `PROVIDER_COARSER_THAN_TDR` | Provider coarser than TDR (Hilux Travo vs Cab / Double Cab) |
| `SHP-01` | IDENTITY_REVIEW | `POSSIBLE_TRIM_NOT_MODEL` | Trim or grade mistaken for a model |
| `SHP-02` | IDENTITY_REVIEW | `POSSIBLE_MODEL_CODE` | Model or displacement code mistaken for a model |
| `SHP-03` | IDENTITY_REVIEW | `POSSIBLE_POWERTRAIN_DERIVATIVE` | Engine |
| `SHP-04` | IDENTITY_REVIEW | `POSSIBLE_BODY_VARIANT` | Body-style or cab variant |
| `SHP-05` | IDENTITY_REVIEW | `POSSIBLE_GENERATION_VARIANT` | Generation |
| `EVD-01` | HOLD | `INSUFFICIENT_IDENTITY_EVIDENCE` | No citable evidence |
| `EVD-02` | HOLD | `INSUFFICIENT_IDENTITY_EVIDENCE` | Provider not onboarded as a creation basis |
| `EVD-03` | CREATE_IDENTITY | `FLAG_CLEARED_BY_EVIDENCE` | Tier-2 evidence attesting a nameplate clears a lexical suspicion (and only that) |
| `EVD-04` | IDENTITY_REVIEW | `EXISTING_IDENTITY_SUSPECTED` | Evidence about the real world cannot settle TDR's own structure or a hard flag |
| `EVD-05` | CREATE_IDENTITY | `MULTI_PROVIDER_CORROBORATION` | Two providers name the same identity |
| `STATE-01` | HOLD | `IDENTITY_ALREADY_DISCOVERED` | Same external identity seen again |
| `STATE-02` | HOLD | `IDENTITY_ALREADY_DISCOVERED` | Different external id for an identity that already exists |
| `STATE-03` | HOLD | `IDENTITY_ALREADY_DISCOVERED` | Simultaneous discovery of the same identity by two workers |
| `STATE-04` | IDENTITY_REVIEW | `IDENTITY_PREVIOUSLY_WITHDRAWN` | Same key as a WITHDRAWN identity |
| `STATE-05` | CREATE_IDENTITY | `NEW_IDENTITY_CONFIRMED` | Source version changes; decision |
| `STATE-06` | HOLD | `IDENTITY_ALREADY_DISCOVERED` | Canonical identity created after discovery began (stale plan) |
| `ID-01` | CREATE_IDENTITY | `NEW_IDENTITY_CONFIRMED` | Id is brand + '.' + the one TDR slug of the canonical name |
| `ID-02` | CREATE_IDENTITY | `NEW_IDENTITY_CONFIRMED` | Id never depends on the provider id |
| `ID-03` | IDENTITY_REVIEW | `CANONICAL_ID_COLLISION` | Slug collision between different names |
| `ID-04` | IDENTITY_REVIEW | `CANONICAL_ID_COLLISION` | Deleted |
| `ID-05` | IDENTITY_REVIEW | `CANONICAL_ID_COLLISION` | Two creatable subjects derive the same id in one batch |
| `ID-06` | HOLD | `NAME_UNSPECIFIED` | Degenerate slug |
| `ID-07` | CREATE_IDENTITY | `NEW_IDENTITY_CONFIRMED` | Different spellings keep different id strings but share one identity key |
| `BATCH-01` | IDENTITY_REVIEW | `STRUCTURAL_CONFLICT` | Containment between subjects in one batch |
| `BATCH-02` | IDENTITY_REVIEW | `STRUCTURAL_CONFLICT` | Sibling subjects in one batch |
| `BATCH-03` | IDENTITY_REVIEW | `STRUCTURAL_CONFLICT`, `DUPLICATE_CANONICAL_SUSPECTED` | Equal names from one provider |
| `BATCH-04` | CREATE_IDENTITY | `NEW_IDENTITY_CONFIRMED` | Junk peers never block a clean subject |
| `BATCH-05` | HOLD | `IDENTITY_COALESCED` | Cross-provider duplicates coalesce into one plan |
| `BATCH-06` | IDENTITY_REVIEW | `CANONICAL_ID_COLLISION` | Order inside the batch never picks a winner |
| `LIN-01` | HOLD | `LINEAGE_CONTINUITY_EXISTING_IDENTITY` | Rename of a bound id |
| `LIN-02` | CREATE_IDENTITY | `NEW_IDENTITY_CONFIRMED` | Rename of an unbound id |
| `LIN-03` | HOLD | `LINEAGE_CONTINUITY_EXISTING_IDENTITY` | Merge whose old ids are bound to one identity |
| `LIN-04` | IDENTITY_REVIEW | `PROVIDER_LINEAGE_AMBIGUOUS` | Merge whose old ids are bound to several identities |
| `LIN-05` | CREATE_IDENTITY | `NEW_IDENTITY_CONFIRMED` | Merge of ids TDR never bound |
| `LIN-06` | IDENTITY_REVIEW | `PROVIDER_LINEAGE_AMBIGUOUS` | Split (parent or child) |
| `LIN-07` | HOLD | `LINEAGE_UNRESOLVED` | Split cycle |
| `LIN-08` | HOLD | - | Declared identity changes without a machine-readable source (refusal INPUT_LINEAGE_SOURCE_MISSING) |
| `ADM-01` | CREATE_IDENTITY | `ADMIN_STRUCTURE_DECISION_APPLIED` | Admin CREATE_IDENTITY bound to the review fingerprint |
| `ADM-02` | IDENTITY_REVIEW | `EXISTING_IDENTITY_SUSPECTED` | A directive bound to another fingerprint is ignored |
| `ADM-03` | HOLD | `ADMIN_DECLINED` | Admin DO_NOT_CREATE is remembered |
| `ADM-04` | HOLD | `ADMIN_DECISION_CANNOT_CLEAR_HARD_FLAG` | No directive clears a hard flag or a duplicate |
| `INP-01` | HOLD | - | Refusal INPUT_SOURCE_VERSION_MISSING |
| `INP-02` | HOLD | - | Refusal INPUT_DUPLICATE_SUBJECT_ID |
| `INP-03` | HOLD | - | Refusal INPUT_POLICY_VERSION_UNSUPPORTED |
| `INP-04` | HOLD | - | Refusal INPUT_RESOLUTION_MISSING |
| `INP-05` | HOLD | - | Refusal INPUT_SCHEMA_INVALID (contradictory relation records) |
| `PERSIST-01` | CREATE_IDENTITY | - | Applying a plan twice writes once |
| `PERSIST-02` | CREATE_IDENTITY | - | Concurrent plans cannot create two identities |
| `PERSIST-03` | CREATE_IDENTITY | - | Preconditions make a plan stale; staleness means re-decide |
| `LIFE-01` | CREATE_IDENTITY | - | Lifecycle transitions and who may perform them |
| `EVT-01` | CREATE_IDENTITY | `NEW_IDENTITY_CONFIRMED` | VEHICLE_IDENTITY_CREATED carries everything the enrichment subsystem needs |
| `EVT-02` | CREATE_IDENTITY | `ADMIN_STRUCTURE_DECISION_APPLIED` | Excluded neighbours travel with the event |
<!-- END GENERATED: taxonomy -->

## Appendix D — Lifecycle

<!-- BEGIN GENERATED: lifecycle -->
| Transition | From | To | Actors | Proposal for | Guard |
|---|---|---|---|---|---|
| `CREATE` | `null` | `["DISCOVERED", "PENDING"]` | BOOTSTRAP, ADMIN | BOOTSTRAP | `bootstrap_decision_is_CREATE_IDENTITY_and_plan_preconditions_hold` |
| `CLAIM` | `["DISCOVERED", "PENDING"]` | `["ENRICHING", "IN_PROGRESS"]` | ENRICHMENT, ADMIN | - | `lease_acquired` |
| `RELEASE` | `["ENRICHING", "IN_PROGRESS"]` | `["DISCOVERED", "PENDING"]` | ENRICHMENT, ADMIN | - | `lease_expired_or_released` |
| `BLOCK` | `["ENRICHING", "IN_PROGRESS"]` | `["DISCOVERED", "BLOCKED"]` | ENRICHMENT, ADMIN | - | `enrichment_cannot_proceed` |
| `VERIFY` | `["ENRICHING", "IN_PROGRESS"]` | `["VERIFIED", "COMPLETE"]` | ADMIN, ENRICHMENT | ENRICHMENT | `vehicle_master_model_rules_pass_and_evidence_recorded` |
| `PUBLISH` | `["VERIFIED", "COMPLETE"]` | `["PUBLISHED", "COMPLETE"]` | ADMIN | - | `publication_gate_passes` |
| `UNPUBLISH` | `["PUBLISHED", "COMPLETE"]` | `["VERIFIED", "COMPLETE"]` | ADMIN | - | `none` |
| `WITHDRAW` | `["DISCOVERED", "ENRICHING", "VERIFIED"]` | `["WITHDRAWN", null]` | ADMIN | - | `no_published_dependents` |
| `REINSTATE` | `["WITHDRAWN"]` | `["DISCOVERED", "PENDING"]` | ADMIN | - | `admin_decision_recorded` |

| Surface | Sees identities in state |
|---|---|
| `consumer_catalog` | PUBLISHED |
| `public_links` | PUBLISHED |
| `external_crosswalk_target` | DISCOVERED, ENRICHING, VERIFIED, PUBLISHED |
| `internal_market_engine` | DISCOVERED, ENRICHING, VERIFIED, PUBLISHED |
| `admin_ui` | DISCOVERED, ENRICHING, VERIFIED, PUBLISHED, WITHDRAWN |
| `enrichment_queue` | DISCOVERED, ENRICHING |
| `backup_export` | DISCOVERED, ENRICHING, VERIFIED, PUBLISHED, WITHDRAWN |
| `identity_resolution_pool` | DISCOVERED, ENRICHING, VERIFIED, PUBLISHED |
<!-- END GENERATED: lifecycle -->
