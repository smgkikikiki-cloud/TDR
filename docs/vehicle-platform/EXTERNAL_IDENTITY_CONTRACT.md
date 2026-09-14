# External Identity Contract (Phase 1A)

**Status: read-only, non-authoritative, observational infrastructure.** This contract does not
change what Mechanism A or Mechanism B do, does not decide which one is a future database of
record, and does not write anywhere. It exists so the question "what does each mechanism
currently assert, and where do they actually agree or disagree" is mechanically answerable
instead of answered by a one-off manual query (as it was for
`LIVE_IDENTITY_BASELINE_2026-09-15.md`).

This document assumes familiarity with `CURRENT_STATE.md` §10 (structural description of
Mechanism A and Mechanism B) and `MASTER_ARCHITECTURE.md` (the target canonical identity graph).
It does not repeat that material — it defines the vocabulary and rules the code in
`lib/external-identity/` implements.

## Relationship to Mechanism A and Mechanism B

- **Mechanism A** — the release-build crosswalk, exposed live through
  `current_vehicle_brands.tdr_brand_id` / `current_vehicle_models.tdr_model_id`
  (`supabase/migration_v15_canonical_vehicle_release.sql`), produced by
  `tdr_bridge/release.py`'s `_brand_crosswalk`/`_model_crosswalk` from the committed TDR
  integration inventory plus reviewed overrides. Broad, deterministic, derived — used today for
  serving/read integration (the public catalog, and the registration-market read path via
  `lib/admin-registration-market.ts`).
- **Mechanism B** — `canonical_object_map` (`supabase/migration_v12_canonical_write_pipeline.sql`).
  Sparse, explicit, human-verified — used today as the write-authority gate in
  `lib/canonical-write-shadow.ts`, which requires `status == 'verified'` and a non-null
  `canonical_id` before a legacy model save becomes an executable canonical shadow write.

This contract does not touch either mechanism's tables, schema, or behavior. It only defines a
shared shape that a read of either mechanism's rows can be converted *into*, for comparison.

## Vocabulary

Implemented in `lib/external-identity/types.ts`. Each concept is independent of the others —
none is inferable from another, and the code never infers one from another.

| Concept | Type | Values / shape | Notes |
|---|---|---|---|
| External namespace | `ExternalNamespace` | `"legacy_tdr"` | Only one exists today. The type is a union specifically so a future namespace (a different legacy system, a different registration authority) can be added without redesigning the contract — none is implemented speculatively in this packet. |
| External entity type | `ExternalEntityType` | `brand \| model \| model_powertrain \| trim` | Normalized, singular. `canonical_object_map.source_table` uses TDR's raw Supabase table names (`brands`, `models`, `model_powertrains`, `trims`); the normalization table is `SOURCE_TABLE_TO_EXTERNAL_ENTITY_TYPE` in `lib/external-identity/mechanism-adapters.ts`. |
| External ID | `string` | the legacy UUID | `canonical_object_map.source_id`, or `current_vehicle_{brands,models}.tdr_{brand,model}_id`. |
| Canonical entity type | `CanonicalEntityType` | `brand \| model \| generation \| variant \| market_trim` | Matches `canonical_object_map.canonical_entity_type`'s existing check constraint exactly — no new values invented. **`variant` is not renamed to `Configuration`** — see "Relationship to the identity graph" below. |
| Canonical ID | `string \| null` | canonical Vehicle Master slug ID | Null exactly when `mappingState` is not `resolved`. |
| Mapping state | `MappingState` | `resolved \| unmatched \| ambiguous \| retired` | The *semantic* state of a mapping attempt — did this mechanism land on one specific canonical entity, or not, and if not, why. Independent of trust level. |
| Trust level | `TrustLevel` | `derived \| verified \| none` | How much authority the assertion carries. `unmatched`/`ambiguous`/`retired` always carry `none`. A `resolved` mapping is `derived` (Mechanism A today) or `verified` (Mechanism B's `status = 'verified'` today) — nothing else. |
| Mechanism / provenance | `Provenance` | `{ mechanism, matchBasis?, verifiedBy?, verifiedAt?, notes? }` | Which mechanism produced the assertion, and whatever the source data can actually prove about how. |

### Why mapping state and trust level are two separate fields

Collapsing them loses exactly the distinction this packet exists to preserve. A `resolved`
mapping can be `derived` (Mechanism A: matched by name/alias/override, never itself sufficient
to authorize a write) or `verified` (Mechanism B: a human explicitly confirmed it). Treating
"resolved" as synonymous with "trustworthy" would silently grant Mechanism A's derived matches
write authority; treating "not verified" as synonymous with "not resolved" would misdescribe
every one of Mechanism A's 383 (as of 2026-09-15) working, broad-coverage crosswalk links as if
they didn't exist. Neither collapse is acceptable per `INVARIANTS.md` rule 8.

### A derived match never becomes verified by this contract

Nothing in `lib/external-identity/` sets `trustLevel: "verified"` except a direct pass-through
of Mechanism B's own `status = 'verified'` row. There is no code path — including agreement with
a verified assertion — that upgrades a `derived` assertion's trust level. See "trust
non-escalation" in the audit engine's test suite (`scripts/check-external-identity-audit.ts`).

## Mechanism A's structural limitation, made explicit

Mechanism A, as observed live through Supabase, can only ever produce `resolved` assertions. A
canonical brand/model either has a non-null `tdr_brand_id`/`tdr_model_id` (an assertion exists)
or it doesn't (no assertion — not an "unmatched" assertion). This is because
`tdr_bridge/release.py`'s own unmatched/ambiguous crosswalk candidates (its `review` list —
`AMBIGUOUS`/`UNMATCHED`/`BROKEN_OVERRIDE`/`UNMATCHED_TDR`) are never written to Supabase; they
exist only in the release JSON artifact uploaded by `vehicle-release.yml`, not in any table this
contract can read. Mechanism B, by contrast, enumerates legacy TDR rows explicitly and so can
represent all four mapping states. This asymmetry is real, not a contract limitation to "fix" —
it is documented here so a reader of an audit report doesn't misread "no Mechanism A assertion"
as "Mechanism A looked and found nothing," when it may simply not have looked at all from this
contract's vantage point.

## Comparability rule

Two assertions may be compared to each other **only when they agree on all four**:

1. `namespace`
2. `externalEntityType` (normalized)
3. `externalId`
4. `canonicalEntityType`

Only once all four match does it make sense to compare `canonicalId`. This tuple is the
**comparability key** (`comparabilityKey()` in `lib/external-identity/types.ts`), and it is also
the grouping key the audit engine uses — every assertion that shares a comparability key lands in
the same group; nothing that doesn't share one is ever compared.

**Why canonical entity type must be part of the key**: the same external legacy `models.id` can
legitimately have a Mechanism A assertion at `model` scope (this legacy model corresponds to
canonical model X) and, independently, a Mechanism B assertion at `generation` scope (this legacy
model's row was used as evidence for canonical generation Y) — Mechanism B's
`canonical_entity_type` column exists precisely because one legacy source row can inform more than
one canonical entity type. Comparing those two assertions as if they were rival answers to the
same question would be wrong; they are answers to two different questions that happen to share a
source ID. See "Audit classifications" below, case "non-comparable at another canonical entity
level."

## Audit classifications

Implemented in `lib/external-identity/audit.ts`, `auditAssertions()`. Every comparability group
(at most one Mechanism A assertion and at most one Mechanism B assertion per group, guaranteed by
`tdr_bridge/release.py`'s construction and by `canonical_object_map`'s
`unique (source_table, source_id, canonical_entity_type)` index respectively) resolves to exactly
one of:

| Classification | Meaning | Condition |
|---|---|---|
| `exact_agreement` | Both mechanisms assert the same canonical ID at this scope. | Mechanism A present, Mechanism B `verified`, same `canonicalId`. |
| `disagreement` | Both mechanisms assert *different* canonical IDs at this scope. | Mechanism A present, Mechanism B `verified`, different `canonicalId`. |
| `derived_only` | Only a derived (Mechanism A) assertion exists; Mechanism B has no opinion at all at this scope. | Mechanism A present, Mechanism B absent. |
| `verified_only` | Only a verified (Mechanism B) assertion exists; Mechanism A has no opinion at this scope. | Mechanism B `verified`, Mechanism A absent. |
| `mechanism_b_unmatched` | Mechanism B looked and could not match — regardless of whether Mechanism A already has a derived answer. | Mechanism B `status = 'unmatched'`. |
| `mechanism_b_ambiguous` | Mechanism B found more than one candidate and could not pick one — no winner is ever inferred, even if Mechanism A has an opinion. | Mechanism B `status = 'ambiguous'`. |
| `mechanism_b_retired` | Mechanism B's mapping was explicitly retired. | Mechanism B `status = 'retired'`. |

Two further, non-classification-affecting fields on every finding:

- `assertions` — every assertion in the group, verbatim, never mutated. This is where "what does
  each mechanism actually assert, with what trust level and provenance" lives; the classification
  is a summary label on top of this, not a replacement for it.
- `otherCanonicalEntityTypesForSameExternalId` — the set of *other* canonical entity types this
  same external ID has assertions at, outside this group. This is how "non-comparable verified
  assertions at another canonical entity level" is surfaced: not as a classification value (since
  each such assertion already has its own correct classification in its own group), but as
  cross-reference visibility so an operator sees the full picture for one external ID without the
  engine ever conflating two different scopes into one verdict.

**Deliberately not implemented**: a "winner" field, a merged/collapsed canonical ID, or any
per-external-ID summary that picks one mechanism's answer over the other's. Different future
consumers need different trust thresholds (a read-integration consumer may accept `derived`; a
write-sensitive consumer must require `verified`); baking in one answer here would pre-empt that
decision. See `MIGRATION_PLAN.md`'s Phase 1 problem statement.

## Examples

**Exact agreement.** Legacy model UUID `u1`. Mechanism A: `{externalId: "u1", canonicalEntityType: "model", canonicalId: "jaecoo.jaecoo_5_ev", trustLevel: "derived"}`. Mechanism B: `{externalId: "u1", canonicalEntityType: "model", canonicalId: "jaecoo.jaecoo_5_ev", status: "verified", trustLevel: "verified"}`. → one finding, `exact_agreement`, both assertions present, both trust levels untouched.

**Non-comparable, not a disagreement.** Legacy model UUID `u2`. Mechanism A: `{externalId: "u2", canonicalEntityType: "model", canonicalId: "toyota.hilux_revo_double_cab"}`. Mechanism B: `{externalId: "u2", canonicalEntityType: "generation", canonicalId: "toyota.hilux_revo_double_cab.ah30", status: "verified"}`. → **two** findings: one at `model` scope (`derived_only`, since no Mechanism B assertion exists at `model` scope for `u2`), one at `generation` scope (`verified_only`, since no Mechanism A assertion exists at `generation` scope — Mechanism A never asserts at generation scope at all). Each finding's `otherCanonicalEntityTypesForSameExternalId` lists the other, so an operator sees both without either being mislabeled `disagreement`.

**Unmatched, never verified.** Legacy model UUID `u3`, `canonical_object_map` row `status: "unmatched"`, `canonical_id: null`. → `mechanism_b_unmatched`, `trustLevel: "none"`. Even if a Mechanism A assertion for `u3` exists (the very common current-day case — most of the 326 `unmatched` Mechanism B model rows recorded on 2026-09-15 likely overlap with Mechanism A's 321 resolved model links), the classification stays `mechanism_b_unmatched`, not `exact_agreement` or `derived_only` — Mechanism A's presence is visible in `assertions`, not hidden, but it never upgrades or reclassifies Mechanism B's stated state.

## Future compatibility (not designed here)

This contract's types are written so that:

- a future **external namespace** (a different legacy system, a different registration source)
  can be added as another value of `ExternalNamespace` without changing the comparability rule or
  classification logic;
- a future **Phase 2 canonical DLT v2 shadow pipeline** or **Phase 4 generic source
  observation/resolution infrastructure** (`MIGRATION_PLAN.md`) could, if and when authorized,
  produce assertions in this same shape from a third mechanism, and the audit engine's grouping/
  classification logic would not need to change to accommodate a third mechanism producing
  `derived` or `verified` assertions — only `MechanismId` would grow a new value and
  `classify()` would need a documented rule for the new combination;
- the canonical identity graph (`MASTER_ARCHITECTURE.md`) already anticipates `MarketTrim` having
  an optional, evidence-backed link to `Variant`/`Configuration` rather than a mandatory one —
  this contract's `canonicalEntityType` vocabulary already includes both `variant` and
  `market_trim` as independent values for exactly this reason, so a future MarketTrim↔Configuration
  assertion would not require a new type.

None of the above is implemented, scoped, or authorized by Phase 1A. Recording the shape's
extensibility here is not a commitment to build any specific extension.

## Non-goals of this contract (restated from the Phase 1A task)

This contract and its audit engine do not: create a new Supabase table; alter
`canonical_object_map`; add a database migration; backfill or auto-verify any mapping; write
Mechanism A data into Mechanism B; change `tdr_bridge/release.py`, `lib/canonical-write-shadow.ts`,
the legacy editor, any serving consumer, registration ingestion/analytics, or any canonical ID;
rename `Variant`; restructure `MarketTrim`; or choose which mechanism (or a new one) becomes an
eventual persistence layer. That decision is explicitly deferred — see `MIGRATION_PLAN.md`'s
Phase 1 section and `status/CURRENT.md`.
