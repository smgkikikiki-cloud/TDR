# R6 Ice Scoped Crosswalk v2 — offline implementation contract (draft)

**Status:** design/fixture branch only; not adopted migration, no production DDL/writes, no R7/R8 cutover. Independent PR against `main`, coordinating with [R6 PR #229](https://github.com/smgkikikiki-cloud/TDR/pull/229) and relying on its frozen owner evidence under `data/packages/ice_crosswalk_r6_offline_recovery_M7.0/`. Repository portfolio gate `execution.enabled=false`, `PRODUCTION_CROSSWALK_ALLOWED=false`. Resolve C01 production R6 provenance and C02 migration numbering before publishing DDL.

## The problem to fix

The live v63 schema enforces `UNIQUE(canonical_model_id) WHERE status IN ('AUTO','APPROVED')`; this prohibits owner-approved **many Ice groups → one canonical vehicle identity**. Its group-level row cannot express **the same Ice group → different canonical identities for different registration classes**. R6 owner shadow currently has 430 exact approved group overrides, of which 117 source groups reuse 35 canonical targets. Shadow `99.5309%` is target availability **including legacy PROPOSED and unmaterialized shadow identities**, not actual approved production coverage. Do not cut over under that percentage.

## Source grain and authoritative mapping

For each Ice registration row, use the compound key `(model_group_id, reg_type)` where `reg_type` is the **actual DLT category** stored by Ice: `รย.1`, `รย.2`, `รย.3`, etc. Human-readable `RY1`/`RY2`/`RY3` are accepted only at ingestion and normalized **one-to-one** into these native values. Do not automatically treat RY2 as RY1; this only occurs if there is an explicit reviewed row with `รย.2 → Double Cab`.

A v2 mapping decision has `(group_id, reg_type_scope, action, canonical_model_id, owner evidence, Ice master_version)`:
- `reg_type_scope = รย.N`: applies only to that registration class.
- `reg_type_scope = ALL`: fallback for a *non-split* Ice group. An exact scope overrides ALL.
- An Ice group flagged **scoped-only** (pickup requiring body split) must have a separate reviewed resolution for each class. An ALL alias or legacy mapping **must never** fill an unreviewed class in a scoped-only group.
- `APPROVED`: an existing, governed Vehicle Master canonical ID is confirmed for the scope. The same canonical ID can serve **many distinct Ice groups**; only `(group_id, scope)` requires a single definitive approved target.
- `EXCLUDED`: owner has explicitly removed this Ice scope from accepted coverage, without deleting its historical registration facts.
- `PENDING`: a frozen directive exists but cannot yet be served; do **not** silently fall back to prior AUTO/PROPOSED.
- Materialization not finished: record `PENDING_MATERIALIZATION`, not `NO_CANDIDATE` or a new manual task. New vehicles can only be created through a separately authorized structural writer; price-only `migration_v66` is not that writer.

**Provenance:** owner decision reference and source package/master version are mandatory. Matchers may emit proposals, but may not assign `OWNER/APPROVED` authority to data merely because correlation is high, or because a source is included in the 244-row worklist. The 244 decisions (92 link, 63 retain AUTO, 51 exclude, 38 create) are frozen and cannot be re-adjudicated by scoring. The 1,200-row overlay and original evidence must remain traceable.

## Consumer precedence and safety

Effective mapping resolution is `(exact scoped owner decision) > (ALL owner decision for non-scoped-only group) > (unique legacy active AUTO/APPROVED) > UNMAPPED`.

- V2 owner `APPROVED` wins over legacy old crosswalk; `EXCLUDED` and `PENDING` explicitly suppress old mappings.
- `PROPOSED` and `REJECTED` never count toward **approved** coverage and never fill absent targets.
- If there are multiple conflicting legacy active canonical IDs for one group, stop with `AMBIGUOUS_LEGACY_ACTIVE`, not an arbitrary lexical-first match.
- An unmaterialized canonical target cannot be used as a production mapping. Keep `PENDING_MATERIALIZATION` with exact owner provenance.
- No registration fact is ever dropped: excluded, unmatched, ambiguous, or pending data stays in the raw totals and the `ไม่ระบุ` bucket for derived dimensions.
- Aggregate Ice facts by `(period, province, reg_type, model_group_id)` exactly once before mapping. Do not multiply facts when multiple source groups join one canonical. The model breakdown **remains Ice model_group_id**, with canonical ID attached as metadata *per scope*. If a combined Ice group has different mappings by class, it cannot publish a single group-level canonical ID unless all non-excluded classes agree.
- Segment/body aggregations must resolve each raw row's scoped canonical ID **before** reducing; aggregating by group first is wrong for mixed pickups. Brand/registration_type/powertrain must remain Ice authoritative; never infer engine/body from registration weights.
- Existing v63 readers can remain as a compatibility path until a *separate approved* reader-cutover step. Do not silently blend old and new statuses or double count unit totals.

## Draft DB shape (not deployable yet)

See `ICE_SCOPED_CROSSWALK_V2_SQL_DRAFT.sql` for a **non-versioned design candidate**. Reserve a migration number only after C02 reconciliation. The draft uses:

`ice_model_crosswalk_scoped` with `PRIMARY KEY (model_group_id, reg_type_scope)`, status `APPROVED|EXCLUDED|PENDING`, `canonical_model_id` with FK to `vehicle_models` for APPROVED, `pending_target_id` for unmaterialized target, `master_version`, immutable provenance (`decision_ref`, `source_sha256`), timestamps, and private service-role read policy. It **does not alter/drop** the v63 active-canonical unique index, v63 rows, production consumers, or any vehicle master table.

Reviewer must specify: exact writer authorization contract, migration number, atomic backfill with 244/1200 parity evidence, means to avoid v63/v2 crosswalk split-brain, transaction/rollback strategy, service-reader query performance, Ice future-import redirects, and how `reg_type` scope interacts with RY2 policy.

## Executable offline adapter / tests

`automotive/vehicle_master/vehreg/ice_scoped_crosswalk.py` is a **pure** resolver. It takes frozen `OwnerScope` decisions (never inferred from scores), optional legacy active rows, materialized ID set, scoped-only group IDs and a single M7 master version. It outputs one row per aggregated `(group,reg_type)`. It can be unit-tested without Supabase credentials or DDL.

`automotive/vehicle_master/tests/test_ice_scoped_crosswalk.py` covers many Ice groups → one target, pickup scoping and RY2, owner exclusion, Serena, protected/pending identities, old ambiguous AUTO, unapproved PROPOSED, source/master-version locks and no duplicated grain. These tests **do not** certify SQL migration behavior or actual TypeScript consumer cutover; those require follow-up DB tests and end-to-end fixture tests before Phase 2 exit.

## Parallel TypeScript market reader (offline only)

`lib/ice-scoped-crosswalk.ts` independently applies the same reviewed owner-first semantics to **each** Ice `reg_trend` fact (period × province × reg_type × model_group_id). Unlike the Python fixture adapter, it deliberately allows repeated model/reg_type pairs across legitimate time/province dimensions and preserves every fact exactly once. It exposes `IceScopedResolver.resolveRows`, `scopedDimensionTotals`, `scopedCoverage` and `primaryCanonicalForScopedGroup`. The latter returns null if a group is split across canonical identities or has unresolved non-excluded classes; a whole-group model ID must not be fabricated from mixed cab classes.

`scripts/check-ice-scoped-crosswalk.ts` exercises its many-to-one aliases, independently reviewed RY2, mixed pickup classes, segment/body reconciliation, owner exclusion, Serena, PROPOSED exclusion from approved coverage, missing canonical targets, frozen master version and ambiguous group-level metadata. It is included in `npm run check`; **no production read path imports this module yet**. The SQL draft remains unnumbered and unapplied pending C01/C02.

## Acceptance gates

1. Current PR #229 remains draft until its complete CI checks are green, no changes to the frozen 244 data.
2. Offline resolver tests pass, no writes/network; inspect independent CI on the new stacked draft PR.
3. Schema proposal reviewed and reservation conflict C02 resolved before numbering/applying any migration. No production DDL under this draft.
4. Implement and test a dedicated scoped server-side reader and M4 consumer path (especially segment/body) behind a controlled release gate; demonstrate **identical Ice raw totals**, no double count and correct mixed-class pickup behavior.
5. Materialize only genuinely absent owner-approved identities through a governed structural Vehicle Master writer after explicit authorization; `migration_v66` price writer is not a model CREATE writer.
6. R6 approved/serving coverage ≥99.1% on **fixed 4,141,987** registration denominator without credit for PROPOSED, shadow-only identity targets, or unapproved class splits. Report exclusions-adjusted coverage separately and never replace the fixed KPI.
7. Stop at the governance gate; no prod crosswalk writes, R7/R8, deploy or merge without separate owner approval.