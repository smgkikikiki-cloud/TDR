# Migration Status — Current

Operational state for future coding agents. Keep this short. Update it in the same change that
completes or starts any migration packet.

## Current migration phase

**Phase 0 is complete.** Documentation set created 2026-09-14 (`CURRENT_STATE.md`,
`MASTER_ARCHITECTURE.md`, `INVARIANTS.md`, `MIGRATION_PLAN.md`, this file, `BASELINE.md`), plus
one narrowly-scoped regression test (see "Completed migration packets" below). Received
architecture review; amended 2026-09-15 (`LIVE_IDENTITY_BASELINE_2026-09-15.md`) for two
corrections: (1) canonical vehicle identity documented as a graph (Generation scoping two
distinct children, Configuration/Variant and MarketTrim, linked optionally — not a strict
`Configuration → MarketTrim` chain; "canonical identity graph" replaces "canonical vehicle
spine"), and (2) a live, read-only Mechanism A/B inspection recorded and the Phase 1 problem
statement rewritten around derived-vs-verified trust semantics rather than "reconciling" two
crosswalks. Both the 2026-09-14 pass and the 2026-09-15 amendment were documentation-only (the
2026-09-14 pass also added one pure-Python regression test).

**Phase 1A is implemented and architecture-reviewed (2026-09-15).** Phase 1A was the narrow first
packet of Phase 1: a read-only external-identity contract and audit engine. It was implemented,
reviewed, and then **hardened** in response to review findings, all on 2026-09-15. What now
exists:

- `docs/vehicle-platform/EXTERNAL_IDENTITY_CONTRACT.md` — the vocabulary (external namespace/
  entity type/ID, canonical entity type/ID, mapping state, trust level, provenance), the
  corrected `canonicalId`/mapping-state invariant (a discriminated union — `resolved` always has a
  non-null `canonicalId` and `derived`/`verified` trust; `unmatched`/`ambiguous`/`retired` always
  have `trustLevel: "none"`, with `canonicalId` allowed to be a retained contextual value that
  never implies a resolution), the comparability rule, the audit classifications, the
  duplicate-assertion anomaly channel, and the read-only-boundary clarification (below).
- `lib/external-identity/types.ts`, `audit.ts`, `mechanism-adapters.ts` — pure TypeScript
  (no I/O): the contract types (as a discriminated union), the classification engine (now with
  `AuditAnomaly` detection for duplicate same-mechanism assertions under one comparability key —
  no such group is ever silently reduced to "the first row"), and adapters converting each
  mechanism's actual row shape into the shared contract (a Mechanism B `verified` row with a null
  `canonical_id` — invalid source data — throws `InvalidMechanismBRowError`; the batch adapter
  routes it to a visible `invalidRows` result rather than crashing or silently dropping it).
- `scripts/audit-external-identity.ts` — a live, **SELECT-only** command (no insert / update /
  delete / upsert / RPC of any kind) that reads `current_vehicle_brands`,
  `current_vehicle_models`, and `canonical_object_map` and prints a human-readable summary plus a
  deterministic JSON report, including anomalies and invalid rows when present. Fails clearly
  (exit code 2, no fabricated output) when server-side Supabase credentials are absent. Its
  read-only behavior is code-enforced (SELECT-only calls), **not** credential-enforced — it uses
  the same write-capable server-side admin credential every other admin tool in this repository
  uses; Phase 1A introduces no dedicated read-only database role or key (see
  `EXTERNAL_IDENTITY_CONTRACT.md`'s "Read-only boundary" section).
- `scripts/check-external-identity-audit.ts` — pure tests against synthetic fixtures only (no
  live-dated counts hard-coded), covering the corrected invariant and duplicate-anomaly behavior,
  wired into `npm run check`.

**Production identity behavior is unchanged.** Mechanism A (`tdr_bridge/release.py`, the
`current_*` views) and Mechanism B (`canonical_object_map`, `lib/canonical-write-shadow.ts`)
behave exactly as before Phase 1A — this packet only reads them and reports on what it reads.

**At the time Phase 1A completed, no persistence decision had been made.** Phase 1A deliberately
did not choose whether a future external-identity registry wraps an existing mechanism, replaces
one, or becomes something new. That decision was made in the very next packet — see "Phase 1 is
complete" below; do not read this paragraph as still describing the current state.

**Live audit status**: `scripts/audit-external-identity.ts` itself has still not been executed
against a live Supabase project by any Claude session — no server-side credentials have been
available in any session that has implemented or hardened Phase 1A (confirmed each time: no
`SUPABASE_*` environment variables set, no local `.env`/`.env.local` with real values). The tool
has only ever been exercised against its own synthetic test fixtures
(`scripts/check-external-identity-audit.ts`, all passing) and its no-credentials failure path
verified directly (exit 2, clear message, no live Supabase call attempted).

**Live validation was independently supplied by architecture review on 2026-09-15**, not produced
by running the checked-in CLI: the reviewer performed a separate, equivalent SELECT-only query
against the production project and supplied the result, recorded in full in
`PHASE_1A_LIVE_VALIDATION_2026-09-15.md` (383 Mechanism A assertions, 335 Mechanism B rows, 397
comparability groups, 1 exact agreement, 0 disagreements, 0 observed duplicate-assertion
anomalies). Treat that document, not this CLI's own execution history, as the current live
evidence — and treat it as a dated snapshot, not a standing guarantee.

**Phase 1 is complete (2026-09-15).** Phase 1B answered the persistence question Phase 1A
deliberately left open, and the same pass finished the reconciliation/sync infrastructure that
decision required — deliberately completed in one pass rather than split into further Phase 1
sub-packets. Full record: `docs/vehicle-platform/EXTERNAL_IDENTITY_PERSISTENCE.md`.

- **Git registry = pinned identity source of truth.**
  `automotive/vehicle_master/integration_data/external_identity_registry.json`
  (loader/validator: `tdr_bridge/external_identity_registry.py`, offline CLI:
  `tools/validate_external_identity_registry.py`, no Supabase/network required) owns pinned,
  non-reconstructible external-identity decisions and gets ordinary Git review like the rest of
  canonical Vehicle Master truth. Initial contents: exactly one binding — the `legacy_tdr` model
  mapping `e1a0b9fd-2d57-477d-b13f-1647d36d0298` → `jaecoo.jaecoo_5_ev`, `authority_basis:
  "explicit_review"` — the one `canonical_object_map` row (of nine currently `verified`) whose
  provenance is an actual named human review rather than deterministic publisher output.
- **Mechanism A remains derived.** Its 383 Brand+Model links were NOT imported — a derived,
  recomputed-every-release match is not a pinned decision. `tdr_bridge/release.py` is unchanged.
- **Phase-E rows remain projection-owned.** The 8 `canonical_object_map` rows generated by
  `apply_vehicle_serving_projection` (`status='verified', verified_by='phase-e-publisher'` — a live
  finding confirmed by reading `supabase/migration_v14_serving_projection.sql` directly) were NOT
  imported: deterministic, reconstructible serving-projection output, not reviewed decisions.
- **`canonical_object_map` remains the compatibility/operational layer**, and is now
  *deterministically, safely, reproducibly* projectable from Git — but its own behavior, schema,
  and existing consumers are unchanged, and **no Supabase migration is part of Phase 1.** An
  earlier draft of this pass proposed dropping `canonical_object_map_verified_target_uq` (the
  global partial-unique index forbidding more than one verified row per canonical target) as
  `migration_v28`; architecture review reverted that after finding the index is load-bearing for
  `apply_vehicle_serving_projection` (Phase-E), which selects its target row by `canonical_id`
  alone with no source key. The index stays. Instead, the registry's broader cardinality model
  (multiple external identities may legitimately bind to one canonical target in Git) is reconciled
  against the narrower operational constraint by **detection, not schema change** — see the next
  bullet.
- **Operational projection/sync now exists, with a representability check.**
  `tdr_bridge/external_identity_sync.py` (pure reconciliation logic, no I/O) and
  `tools/sync_external_identity_registry.py` (the live CLI, dry-run by default, `--apply` for safe
  mutations, with reread-and-prove-convergence built in) make
  "Git truth → controlled operational projection → existing consumer" real and repeatable. It can
  never update an existing operational row, never touch a row outside the registry's own keys
  (review-state, Phase-E, unknown-verified, retired-operational-only rows all survive untouched),
  and never imports anything back into Git. A new classification,
  `operational_target_uniqueness_blocker`, detects a registry state that is valid in Git but not yet
  representable under `canonical_object_map_verified_target_uq` (two active bindings sharing a
  canonical target, or a binding whose target another source key already holds verified) and
  refuses to propose or apply that write. `--apply` is fail-closed at the whole run's level:
  `mutations_to_apply()` returns zero mutations if *any* blocker exists anywhere in the run, even
  for an unrelated binding that is individually safe — closing a real partial-apply gap an earlier
  draft of this pass had. `is_phase_e_owned` detection was also tightened from OR to AND (both
  `verified_by='phase-e-publisher'` *and* the Phase-E `match_basis.basis` literal are now required
  to classify a row as Phase-E-owned; a row with only one is `verified_ownership_unknown`). See
  `EXTERNAL_IDENTITY_PERSISTENCE.md`'s "Operational representability" section for the full
  reasoning.
- **Existing consumers have not been cut over.** `tdr_bridge/release.py`,
  `lib/canonical-write-shadow.ts`, `apply_vehicle_serving_projection`, every `current_vehicle_*`
  view, registration ingestion/analytics, ECO ingestion, canonical input commands, and every
  application page/compare/member-dashboard consumer are byte-for-byte unchanged in behavior. The
  write gate may continue reading `canonical_object_map` directly — that is intentional; Phase 1's
  completed architecture is `Git truth → controlled operational projection → existing consumer`,
  not `consumer → Git file directly`.
- **Phase 1 is nevertheless complete**, because the identity authority/projection boundary
  described in `MASTER_ARCHITECTURE.md`/`EXTERNAL_IDENTITY_PERSISTENCE.md` is now established *and*
  operationally reproducible (dry-run, apply, and convergence all implemented and tested), even
  though no consumer has been switched to depend on it yet. That switch is intentionally deferred,
  separately-authorized, future work — not a blocker to closing Phase 1.

**Phase 1 is closed.**

**Phase 2 is complete, in shadow (2026-09-15).** The DLT v2 observation/resolution/fact/backfill/
parity pipeline is implemented and tested, running alongside both the existing local
`vehreg/ingest.py`/`vehreg/dlt.py` pipeline and the existing production Supabase registration
path. Full record: `DLT_V2_ARCHITECTURE.md`.

- **Observation layer** (`automotive/vehicle_master/vehreg/registration_observation.py`):
  immutable, deterministically-keyed `RegistrationObservation` rows, with adapters for DLT CKAN
  records, column-mapped CSV rows (the current DLT CSV fetcher's own output), and — for
  backfill — live Supabase `public.registrations` rows. The legacy `model_id`/`mapping_method` on
  a backfilled row are carried as parity evidence only, never as resolution input.
- **Canonical resolver** (`vehreg/resolution_v2.py`): a thin, observation-shaped wrapper over the
  unchanged, already-correct `vehreg.ingest.Resolver` — resolves directly against
  `vehreg.catalog.Catalog` text ids (never a legacy `public.models.id` uuid), stops at the deepest
  grain the source proves (BRAND/MODEL/VARIANT), never guesses across an ambiguity, and derives
  trim/battery detail for trim-detail brands (BYD, Jaecoo, Aion, Deepal, Tesla) without ever
  producing a `MarketTrim` — `Grain` has no such member, so this is structural, not a policy.
- **Fact model** (`vehreg/registration_v2_writer.py`, pure): a fact row exists only when
  resolution produced a canonical id at all; an observation whose brand could not be placed
  produces no fact, its units remaining visible only on the observation itself. A repeated
  observation is collapsed before resolution, so no batch ever double-counts.
- **Shadow schema** (`supabase/migration_v29_registration_dlt_v2_shadow.sql`): three new,
  additive, service-role-only tables (`registration_observations_v2`, `registration_facts_v2`,
  `registration_resolution_review_v2`) — no grant to `anon`/`authenticated`, no change to
  `registrations`/`registration_brand_aliases`/`registration_model_aliases`/
  `match_registration_model`/any `registration_*` analytics view, proven by source-text regression
  coverage since no live Postgres exists in this test suite.
- **Backfill** (`tools/backfill_registration_v2.py`): reads live `public.registrations`
  (paged, optional `--period-from`/`--period-to`), resolves, and — only with `--apply` — upserts
  the three shadow tables. Idempotent and resumable structurally (deterministic ids, PostgREST
  upsert), not via a checkpoint file. Dry-run (default) performs zero writes and prints counts
  before writing.
- **Parity** (`tools/registration_v2_parity.py` / `vehreg/registration_v2_parity.py`, pure
  comparison logic): compares v1 `registrations` against the v2 shadow, exactly paired by the
  legacy row's own uuid (no fuzzy label matching), and keeps four questions strictly separate —
  volume parity, identity parity, resolution-coverage difference, grain difference — per the
  explicit rule that a mapping disagreement is not automatically a unit mismatch. Only a real
  volume mismatch, a duplicate source key, or a reconciliation (units-drift) failure marks a
  report unclean.
- **No production consumer change, no read cutover.** `/api/report/registration`,
  `/api/report/market`, and every `registration_*` view/function are byte-for-byte unchanged.
  Nothing reads the v2 shadow tables in production — that is Phase 3, not started.
- **No change to `vehreg/ingest.py`/`vehreg/dlt.py`/the local SQLite warehouse.** Phase 2 is a
  second, independent Supabase-side consumer of the same `Resolver`/`Catalog`, not a replacement
  for the local pipeline.

**Phase 2 is closed.**

**Phase 3 — implementation complete; production cutover pending live gate execution
(2026-09-15).** Full record: `PHASE3_CUTOVER.md`.

- **Preflight fix 1 — observations are now actually immutable.** Phase 2's merge-upsert (keyed
  only on `observation_id`) could silently overwrite raw evidence if a source's payload changed
  under an unchanged id. Fixed at two layers: `vehreg/registration_v2_writer.py` now detects a
  same-id/different-payload conflict (within one batch, or against what is already persisted) as
  an explicit `DriftConflict`, never resolved by "keep the first," and gates the *entire* run's
  writes closed the moment one exists (`writes_to_apply` — the same whole-run fail-closed pattern
  Phase 1 established); `supabase/migration_v30_registration_v2_immutable_observations.sql` revokes
  `UPDATE`/`DELETE` on `registration_observations_v2` from `service_role` and adds a trigger that
  unconditionally rejects both. Same id + same payload is still a correct, silent no-op.
- **Preflight fix 2 — direct DLT → v2 ingest exists.** `tools/registration_v2_dlt_ingest.py`
  reads DLT's CKAN API directly (`vehreg.dlt.monthly_index`/`fetch_records`, unchanged), adapts
  with `RegistrationObservation.from_dlt_record` (unchanged), and resolves/writes through the same
  unmodified `Resolver`/`registration_v2_writer.py` every other v2 tool uses — no duplicated
  Resolver logic. Dry-run default, `--apply` required, one or more `--period` selects the
  month(s). A deterministic period/source ownership rule
  (`vehreg.registration_v2_parity.authoritative_source_for_period`, backed by
  `registration_serving_state.v2_source_boundary_period`) prevents
  `legacy_registrations_backfill` and `dlt_ckan` from both becoming authoritative v2 volume for
  the same period — enforced at read/serving time, not by refusing writes.
- **v2 serving projection.** `vehreg/registration_v2_rollup.py` (pure, mirrored in SQL by
  `registration_facts_v2_serving`): MODEL facts count directly, VARIANT facts roll up to their
  canonical model, BRAND facts are never distributed into models (stay a measurable, explicit
  "unknown/coarse" bucket), and every grain rolls up safely to brand — proven to never double-count
  or drop volume (`rollup_reconciles`).
- **Cutover compatibility — one boundary, not a rewrite.** Both `/api/report/registration` and
  `/api/report/market` already route through `lib/registration-analytics.ts`; every one of its
  seven dimension views is built on exactly three views that read `registrations`
  (`registration_analytics_coverage`, `registration_monthly_brand`, `registration_monthly_model`).
  `supabase/migration_v31_registration_v2_serving_and_cutover.sql` adds
  `registration_serving_state` (single-row switch, default `'legacy'` — applying the migration
  changes nothing), `set_registration_serving_source`/`set_registration_v2_source_boundary`
  (atomic, reversible, `security definer`, `service_role`-only), `registration_facts_v2_serving`,
  and `registration_reporting_source` — the one compatibility view, shaped like `registrations`
  plus a `canonical_model_id` passthrough, that reads legacy or v2 depending on the switch. The
  three base views are redirected to read it instead of `registrations` directly (their own
  `SELECT`/`WHERE`/`GROUP BY` unchanged) — every view built on top of them inherits the switch
  with zero changes of its own. Exactly **one line** of TypeScript changed
  (`lib/registration-analytics.ts`'s `fetchRegistrationRows`: `.from("registrations")` →
  `.from("registration_reporting_source")`); `getRegistrationAnalytics`'s dimension-view path
  needed no TypeScript change at all. `tools/registration_v2_cutover.py` (`--status`, `--switch
  {legacy,v2}`, `--set-boundary`) is the switch's operator interface — `--switch legacy` is the
  rollback path, requiring no data reconstruction, and is the identical code path as `--switch
  v2`.
- **Parity / cutover-readiness gate — reused, not duplicated.**
  `tools/registration_v2_parity.py --readiness` wraps the same `ParityReport` a plain parity run
  already builds in a new `CutoverReadinessReport`. Readiness requires: parity's own
  volume/duplicate/reconciliation cleanliness, no unresolved source-lineage ownership, and every
  `--required-periods` entry populated in v2. **100% identity agreement is explicitly not
  required** — `identity_disagreement`/`grain_difference_v2_coarser` stay visible, never block.
  One machine-readable JSON report; exit 0 ready, 1 not ready (never cut over on this), 2 could not
  run.
- **Write consolidation.** `tools/registration_v2_dlt_ingest.py` is defined as the forward
  registration ingestion path once the source-ownership boundary is set; `legacy_registrations_
  backfill` is for historical backfill only. DLT registration data still never routes through the
  canonical vehicle-market command intake (`vehreg/canonical_write.py`/`canonical_queue.py`) — ECO/
  product write paths remain fully separate, unmentioned by any file this phase adds.
- **Nothing deleted.** `registrations`, `registration_brand_aliases`,
  `registration_model_aliases`, `match_registration_model`, and every existing view/function
  remain exactly as they were, available for rollback throughout Phase 3. Deletion is Phase 4.
- **No production consumer behavior change yet.** Every migration/switch in this packet defaults
  to, or requires an explicit operator action to leave, the pre-Phase-3 behavior.

**2026-09-15 Phase 3 safety patch (still Phase 3, not a new phase).** Architecture review found
three concrete cutover blockers, fixed in place — `migration_v31` was modified directly since it
had never been applied to production, not superseded by a new migration file. Full record:
`PHASE3_CUTOVER.md`'s "2026-09-15 safety patch" note and §B/§C/§D.

1. **Serving-volume fix**: `registration_facts_v2_serving` previously started from
   `registration_facts_v2` (effectively an inner join), so a completely unresolved observation (no
   fact at all) contributed nothing to serving — its units simply vanished. Fixed to start from
   the authoritative *observation* set (`registration_observations_v2 LEFT JOIN
   registration_facts_v2`): an unresolved observation now emits a row with
   `canonical_id`/`canonical_model_id`/`canonical_brand_id`/`grain` all null and `raw_brand`/
   `raw_model`/`units` retained. `vehreg/registration_v2_rollup.py` gained `ServingRow`/
   `resolved_rollup_facts`/`unresolved_units`/`serving_reconciles` to describe the same,
   offline-testable semantics in Python.
2. **Readiness-source fix**: `build_cutover_readiness_report` previously passed *all* v2
   observations/facts into parity, so a period with both `legacy_registrations_backfill` and
   `dlt_ckan` volume could double-count even though the serving boundary selects only one. Fixed
   with `authoritative_v2_observations`/`authoritative_v2_facts` (new, in
   `vehreg/registration_v2_parity.py`), filtering readiness parity to the boundary-authoritative
   subset — mirroring exactly what `registration_facts_v2_serving` will serve — while
   `source_lineage_overlaps` still reports the excluded volume in full. A plain (non-`--readiness`)
   parity run is unaffected.
3. **Direct-canonical fix**: `registration_reporting_source` already exposed `canonical_model_id`,
   but `lib/registration-analytics.ts` never selected or used it, so a correctly-resolved v2 row
   was still sent through the reverse legacy-uuid crosswalk. Fixed minimally: `fetchRegistrationRows`
   now selects `canonical_model_id`; `canonicalizeRegistrationRows` resolves by it directly when
   present (a new `modelsByCanonicalId` map), falling back to the unchanged `model_id →
   tdr_model_id` path otherwise. No SQL dimension view or other UI code touched.

No new migration file, no Phase 3A/3B, no Phase 4 work. `migration_v31`'s serving switch still
defaults to `'legacy'` — this patch changes zero observed production behavior on its own.

**Phase 3 is implementation-complete. Production cutover has not occurred — no live credentials
were available in this session. This is deployment work pending operational execution, not
another architecture subphase (no "Phase 3A/3B" exists or is needed).**

**Live result for the DLT v2 tools (backfill, direct ingest, parity/readiness, cutover switch)**:
not run against the live production project — no server-side Supabase credentials were available
in this session (confirmed the same way as every other phase: no `SUPABASE_*` environment
variables set, no local `.env`/`.env.local` with real values). What *was* verified without live
access: every tool's own no-credentials path (fail closed, exit 2, "Nothing was read/written," no
live call attempted — `tests/test_registration_v2_tools_env.py`,
`tests/test_registration_v2_dlt_ingest.py`, `tests/test_registration_v2_cutover.py`); and the full
observation/resolution/fact-building/immutability/rollup/parity/readiness logic at the
pure-function level (see "Tests" in the completion report for the exact pass count). No migration
in this packet (`migration_v30`, `migration_v31`) has been applied to production, no backfill or
direct ingest has run against production, no readiness report has been produced against live data,
and the serving switch has never been flipped — `registration_reporting_source` therefore
currently only ever exists as `active_source = 'legacy'` wherever it is applied, meaning applying
these migrations alone changes no production behavior. The exact commands an operator with
credentials should run, in order, are in `PHASE3_CUTOVER.md` §F.

No prediction is offered for what the parity/readiness report would show against live production
data — the reviewer-supplied 2026-09-15 baseline (`PHASE_1A_LIVE_VALIDATION_2026-09-15.md`,
`LIVE_IDENTITY_BASELINE_2026-09-15.md`) covers Mechanism A/B identity assertions, not registration
fact volumes; treat production registration parity/readiness as genuinely unknown until an
operator runs the commands in `PHASE3_CUTOVER.md`.

**Live result for the registry↔operational sync tool**: not run against a live Supabase project —
no server-side credentials were available in this session (confirmed: no `SUPABASE_*` environment
variables set, no local `.env`/`.env.local` with real values), consistent with every prior Phase 1
session. What *was* verified without live access: `tools/sync_external_identity_registry.py`'s
own no-credentials path (fails closed, exit 2, no fabricated output, confirmed by direct
execution); its offline registry-validation step (runs and passes independently of Supabase); and
the full reconciliation/classification/mutation-proposal/convergence/representability-blocking
logic at the pure-function level (`tests/test_external_identity_sync.py`, all passing, including
apply-idempotency, rerun-converges-to-zero-mutations, the operational-target-uniqueness-blocker
cases, and the whole-run apply gate). The following architecture-review-supplied live facts (not
executed by this session, and no production data or schema altered to produce them) confirm the
current registry's single binding remains representable today:
`canonical_object_map_verified_target_uq` still exists in production unchanged; production
currently has zero duplicate verified canonical targets; the pinned Jaecoo model UUID
(`e1a0b9fd-2d57-477d-b13f-1647d36d0298`) still exists in `public.models`; its `canonical_object_map`
model binding is still that UUID → `jaecoo.jaecoo_5_ev`, `status='verified'`. The exact command an
operator with credentials should run:

```
cd automotive/vehicle_master
python tools/sync_external_identity_registry.py                # dry run first
python tools/sync_external_identity_registry.py --apply         # only if dry-run is clean
```

Given the live-observed state recorded in `PHASE_1A_LIVE_VALIDATION_2026-09-15.md` (the Jaecoo
model row already agrees with the registry binding), the expected dry-run result for the one
current binding is `in_sync`, zero proposed mutations — i.e. the safe/no-op case. This has not
been confirmed live in this pass; treat it as a prediction from existing evidence, not a live
result, until an operator actually runs it.

The separate, pre-existing Masterplan Phase A–J sequence
(`automotive/vehicle_master/docs/consolidation/MASTERPLAN.md`) is independent of this Phase
0–7 track — see `MIGRATION_PLAN.md`'s relationship table. Its own status, per
`REPOSITORY_CUTOVER.md`/`PHASE_C_WRITE_PIPELINE.md`, is: Phase A and B complete, Phase C live in
shadow mode (canonical write pipeline exists and is used by the queue worker and ECO promotion;
the legacy Streamlit editor still writes directly and has not been cut over), Phases D–J not
started.

## Production path still active

- Canonical vehicle facts are authored in `automotive/vehicle_master/vehreg/data/` and served
  through the release pipeline: `tdr_bridge.release_enriched` → `tdr_bridge.publish` →
  `publish_vehicle_release` RPC → `canonical_*_projection` tables → `current_*` views → app.
- The legacy per-model serving projection (`apply_vehicle_serving_projection` into
  `public.models`/`model_powertrains`/`trims`) also still exists and is still callable, gated by
  the separate `canonical_object_map` crosswalk. Not confirmed whether it is still exercised
  operationally or has been superseded in practice by the full-release path — flagged as a
  parity gap below.
- Registration ingestion into Supabase `registrations` and both registration read paths (legacy
  `/api/report/registration` and canonical-crosswalk `/api/report/market`) remain active per
  `docs/REGISTRATION_MARKET_CONTRACT.md`'s explicit transition rule. Both routes now read through
  `registration_reporting_source` (`PHASE3_CUTOVER.md` §C), which currently always resolves to the
  legacy `registrations` branch (`registration_serving_state.active_source` defaults to
  `'legacy'` and has never been switched) — so this remains, in effect, the exact same production
  path it always was, with one indirection layer that is dormant until an operator flips the
  switch.
- The canonical input queue worker (`tools/canonical_input_worker.py`, cron via
  `.github/workflows/canonical-input.yml`) and the Streamlit direct-write admin
  (`pages/7_Prices.py`) are both still active, unreconciled write paths into the same
  `vehreg/data` files (`CURRENT_STATE.md` §11 item 3).
- The external-identity registry (`integration_data/external_identity_registry.json`) and its
  reconciliation/sync tool (`tools/sync_external_identity_registry.py`) exist and are fully
  functional, but nothing in production reads the registry, and the sync tool's only effect (when
  explicitly run with `--apply`) is to create a missing `canonical_object_map` row that mirrors a
  Git binding — it does not change what any consumer reads or how. No consumer, page, or pipeline
  queries the registry directly, and none is authorized to yet.
- The DLT v2 shadow tables (`registration_observations_v2`, `registration_facts_v2`,
  `registration_resolution_review_v2`) exist as an additive, service-role-only schema (writes are
  now write-once for observations — `migration_v30` — see `PHASE3_CUTOVER.md` §A1); nothing in
  production reads them directly, and the backfill/direct-ingest tools' only effect (with
  `--apply`) is to insert/upsert rows into those three tables — neither ever writes to
  `registrations` or any other existing table.
- `registration_serving_state`/`registration_reporting_source`/`registration_facts_v2_serving`
  (`migration_v31`) exist and default to the legacy behavior (`active_source = 'legacy'`); no
  consumer's *observed* behavior changes until `tools/registration_v2_cutover.py --switch v2` is
  run against a clean readiness gate.

## Shadow paths currently active

- Phase-C canonical write pipeline shadows the legacy Supabase model editor
  (`app/admin/catalog-actions.ts` writes legacy tables first, then best-effort enqueues a
  canonical shadow command) — `docs/consolidation/PHASE_C_WRITE_PIPELINE.md`.
- Phase 2/3's DLT v2 pipeline shadows both the existing local `vehreg/ingest.py`/`vehreg/dlt.py`
  pipeline and the existing production Supabase registration path
  (`registrations`/`registration_brand_aliases`/`registration_model_aliases`/
  `match_registration_model`) — see `DLT_V2_ARCHITECTURE.md`/`PHASE3_CUTOVER.md`. The Phase 3
  cutover switch (`registration_serving_state.active_source`) now exists but remains at its
  `'legacy'` default, so this is still shadow-mode, not cut over. No other Phase 1–7 (this
  document's numbering) shadow pipeline exists yet.

## Completed migration packets

| Packet | Phase | What it did |
|---|---|---|
| Phase 0 documentation + baseline | 0 | Added `docs/vehicle-platform/*`. No code/behavior change. |
| `test_enriched_release_identity_is_stable_and_covers_lifecycle_and_history` | 0 | Closed a confirmed gap: the production-published `release_enriched.enrich_release` payload had no dedicated determinism/shape test (only the base `ReleaseBuilder` output did). Added to `automotive/vehicle_master/tests/test_tdr_bridge.py`. Pure-Python, no Supabase required. |
| Phase 0 amendment: identity-graph correction + live identity baseline | 0 | Reviewer-directed correction of `MASTER_ARCHITECTURE.md`/`MIGRATION_PLAN.md`'s identity structure and Phase 1 problem statement; added `LIVE_IDENTITY_BASELINE_2026-09-15.md` recording reviewer-supplied live Mechanism A/B evidence. Documentation only, no code change. |
| Phase 1A: external-identity contract + read-only audit engine | 1 | Added `EXTERNAL_IDENTITY_CONTRACT.md`; `lib/external-identity/{types,audit,mechanism-adapters}.ts`; live SELECT-only `scripts/audit-external-identity.ts`; `scripts/check-external-identity-audit.ts` (wired into `npm run check`). No table created, no migration, no write to `canonical_object_map`, no change to `tdr_bridge/release.py` or `lib/canonical-write-shadow.ts`. |
| Phase 1A hardening: corrected invariant, duplicate anomalies, read-only boundary, live validation | 1 | Architecture-review-directed amendment. Fixed the `canonicalId`/`mappingState` contract by encoding it as a discriminated union (a `retired`/`unmatched`/`ambiguous` row may legitimately keep a contextual `canonicalId` without becoming resolved/trusted); added `InvalidMechanismBRowError` fail-closed handling for a `verified` row with a null `canonical_id`; added `AuditAnomaly`/`report.anomalies` so duplicate same-mechanism assertions under one comparability key are surfaced, never silently reduced to the first row; precisely documented the read-only boundary as code-enforced, not credential-enforced; added `PHASE_1A_LIVE_VALIDATION_2026-09-15.md` recording architecture-review-supplied live results; corrected an internal `2026-09-16` date error to `2026-09-15` across `CURRENT_STATE.md`, `MIGRATION_PLAN.md`, and this file. Documentation + pure TypeScript only — no persistence, table, migration, or consumer change. |
| Phase 1B: Git-backed external-identity registry (shadow mode) | 1 | Added `docs/vehicle-platform/EXTERNAL_IDENTITY_PERSISTENCE.md` (ownership decision record); `automotive/vehicle_master/tdr_bridge/external_identity_registry.py` (dataclasses, loader, offline validator); `integration_data/external_identity_registry.json` (seeded with exactly the one explicitly-reviewed Jaecoo binding); `tools/validate_external_identity_registry.py` (offline CLI, no Supabase); `tests/test_external_identity_registry.py` (20 tests). Clarified `EXTERNAL_IDENTITY_CONTRACT.md` that `verified`/trust level and persistence ownership are separate dimensions, without changing any Phase 1A type, classification, or test. No Supabase migration, write, or consumer change; Mechanism A's 383 derived links and the 8 Phase-E projection-owned `canonical_object_map` rows were deliberately excluded from the seed. |
| Phase 1 completion: registry↔operational reconciliation/sync | 1 | Added `automotive/vehicle_master/tdr_bridge/external_identity_sync.py` (pure reconciliation/classification/mutation-proposal, no I/O) and `tools/sync_external_identity_registry.py` (live CLI: dry-run default, `--apply` for safe mutations, reread-and-prove-convergence built in). Tightened `external_identity_registry.py`'s validator to require `verified_at`/`verified_by` for active `explicit_review` bindings. Added `tests/test_external_identity_sync.py`. No production consumer, existing Supabase behavior, or Phase 1A TypeScript contract changed. No Supabase migration added. |
| Phase 1 correction: operational representability + apply fail-closed gate + Phase-E ownership tightening | 1 | Architecture-review-directed correction. Reverted an earlier draft's `migration_v28` (would have dropped `canonical_object_map_verified_target_uq`, which is load-bearing for `apply_vehicle_serving_projection`'s canonical_id-only row selection) — deleted the migration file and its regression test entirely; no Supabase migration is part of Phase 1. Added `operational_target_uniqueness_blocker` detection (`_compute_uniqueness_blockers()` in `external_identity_sync.py`) so a Git registry state that is not representable under the existing unique index is reported before any write, instead of weakening the DB constraint. Added `mutations_to_apply()` as a whole-run fail-closed gate for `--apply`: any blocker anywhere means zero mutations applied that run, closing a partial-apply gap in the previous packet. Tightened `is_phase_e_owned` from OR to AND (both `verified_by` and `match_basis.basis` now required). Added new tests to `tests/test_external_identity_sync.py` for all of the above. Updated `EXTERNAL_IDENTITY_PERSISTENCE.md`, `MIGRATION_PLAN.md`, and this file to remove the `migration_v28` claims and document operational representability instead. No Phase-E change, no other production consumer change. **Phase 1 remains closed after this correction.** |
| Phase 2: DLT v2 shadow pipeline (observation/resolution/fact/backfill/parity) | 2 | Added `docs/vehicle-platform/DLT_V2_ARCHITECTURE.md`. Added `automotive/vehicle_master/vehreg/registration_observation.py` (deterministic observation ids, three adapters: DLT CKAN, mapped CSV, legacy `registrations` row), `vehreg/resolution_v2.py` (thin wrapper over the unchanged `vehreg.ingest.Resolver`, resolving to Vehicle Master text ids, never a legacy uuid), `vehreg/registration_v2_writer.py` (pure batch builder, no I/O), `vehreg/registration_v2_parity.py` (pure volume/identity/coverage/grain comparison, kept strictly separate). Added `supabase/migration_v29_registration_dlt_v2_shadow.sql` (three additive, service-role-only tables — `registration_observations_v2`, `registration_facts_v2`, `registration_resolution_review_v2` — no change to any existing registration object, no grant to anon/authenticated; file created, not applied to live Supabase in this pass). Added live CLIs `tools/backfill_registration_v2.py` (dry-run default, `--apply` to upsert, deterministic/idempotent/resumable) and `tools/registration_v2_parity.py` (read-only dual-run report). Added `tests/test_registration_observation_v2.py`, `tests/test_resolution_v2.py`, `tests/test_registration_v2_writer.py`, `tests/test_registration_v2_parity.py`, `tests/test_registration_dlt_v2_shadow_migration.py`, `tests/test_registration_v2_tools_env.py` (83 new tests). No change to `vehreg/ingest.py`/`vehreg/dlt.py`/the local SQLite warehouse, `registrations`/`registration_brand_aliases`/`registration_model_aliases`/`match_registration_model`/any `registration_*` view, Phase-E, or Phase 1's external-identity registry. No production consumer switched to read v2. **Phase 2 is closed by this packet, in shadow.** |
| Phase 3: registration migration cutover infrastructure (preflight fixes, direct DLT ingest, v2 serving, reversible cutover switch, readiness gate) | 3 | Added `docs/vehicle-platform/PHASE3_CUTOVER.md`. **Preflight**: rewrote `vehreg/registration_v2_writer.py`'s `build_batch` for two-pass same-id/conflicting-payload detection (`DriftConflict`), added `plan_observation_writes`/`writes_to_apply` (the whole-run fail-closed apply gate); added `supabase/migration_v30_registration_v2_immutable_observations.sql` (revokes UPDATE/DELETE on `registration_observations_v2` from `service_role`, adds a rejecting trigger). Added `automotive/vehicle_master/tools/registration_v2_dlt_ingest.py` (direct DLT→v2 CLI, reuses `vehreg.dlt`/`Resolver`/`registration_v2_writer` unchanged). **Serving**: added `vehreg/registration_v2_rollup.py` (pure MODEL/VARIANT/BRAND-safe rollup) and extended `vehreg/registration_v2_parity.py` with `authoritative_source_for_period`/`find_source_lineage_overlaps`/`find_unresolved_source_ownership`/`build_cutover_readiness_report` (reuses `ParityReport`, not a new validator). **Cutover**: added `supabase/migration_v31_registration_v2_serving_and_cutover.sql` (`registration_serving_state` single-row switch defaulting to `'legacy'`, `set_registration_serving_source`/`set_registration_v2_source_boundary` atomic RPCs, `registration_facts_v2_serving`, `registration_reporting_source` compatibility view, and `create or replace` of `registration_analytics_coverage`/`registration_monthly_brand`/`registration_monthly_model` to read the compatibility view instead of `registrations` directly — SELECT/WHERE/GROUP BY unchanged). Added `automotive/vehicle_master/tools/registration_v2_cutover.py` (`--status`/`--switch`/`--set-boundary`). Changed exactly one line of `lib/registration-analytics.ts` (`fetchRegistrationRows`'s `.from("registrations")` → `.from("registration_reporting_source")`); `getRegistrationAnalytics`'s dimension-view path needed no TypeScript change. Extended `tools/registration_v2_parity.py` with `--readiness`/`--required-periods`. Added `tests/test_registration_v2_immutability.py`, `tests/test_registration_v2_immutability_migration.py`, `tests/test_registration_v2_dlt_ingest.py`, `tests/test_registration_v2_rollup.py`, `tests/test_registration_v2_serving_cutover_migration.py`, `tests/test_registration_v2_cutover.py`, plus extensions to `tests/test_registration_v2_parity.py`/`tests/test_registration_v2_writer.py`/`tests/test_registration_v2_tools_env.py` (see completion report for the exact new-test count). No production consumer behavior changed (every switch defaults to/requires an explicit flip to leave legacy behavior); `registrations`/alias tables/`match_registration_model`/every existing view remain undeleted. **Phase 3 is implementation-complete; production cutover pending live gate execution — not started/executed in this pass.** |
| Phase 3 safety patch: serving-volume fix + readiness-source fix + direct-canonical fix | 3 | Architecture-review-directed correction, modified `migration_v31` in place (never applied to production). **Serving**: `registration_facts_v2_serving` rewritten from `registration_facts_v2 JOIN registration_observations_v2` to `registration_observations_v2 LEFT JOIN registration_facts_v2`, so a completely unresolved observation still contributes a row (all canonical fields null, raw_brand/raw_model/units retained) instead of vanishing from serving entirely; `vehreg/registration_v2_rollup.py` gained `ServingRow`/`resolved_rollup_facts`/`unresolved_units`/`serving_reconciles` to keep the Python reference and the SQL view describing the same semantics. **Readiness**: added `authoritative_v2_observations`/`authoritative_v2_facts` to `vehreg/registration_v2_parity.py`; `build_cutover_readiness_report` now computes parity against the boundary-authoritative v2 subset only (mirroring what `registration_facts_v2_serving` will actually serve), while `source_lineage_overlaps` still reports excluded volume in full — closing a double-count risk when both `legacy_registrations_backfill` and `dlt_ckan` have volume for one period. Plain (non-readiness) parity is unaffected. **Market-slice**: `lib/registration-analytics.ts`'s `fetchRegistrationRows` now selects `canonical_model_id`; `canonicalizeRegistrationRows` resolves a v2 row directly by canonical id (new `modelsByCanonicalId` map) before falling back to the unchanged `model_id → tdr_model_id` path — no SQL dimension view touched. Extended `tests/test_registration_v2_rollup.py`, `tests/test_registration_v2_parity.py`, and `tests/test_registration_v2_serving_cutover_migration.py` (see completion report for the exact new-test count); no dedicated TS test for the market-slice fix (`lib/registration-analytics.ts` cannot be imported by this repository's alias-free offline `check-*.ts` convention — verified via `tsc --noEmit` plus direct code-path review instead, see `PHASE3_CUTOVER.md` §G). No new migration file, no Phase 3A/3B, no Phase 4 work. **Phase 3 remains implementation-complete after this patch; production cutover still pending live gate execution.** |

## Known parity gaps (from Phase 0, updated as later packets affect them)

1. **No test exercises `publish_vehicle_release` or `rollback_vehicle_release`.** Both are
   Postgres functions in `supabase/migration_v15_canonical_vehicle_release.sql`; this repository
   has no local/offline Postgres test harness. Closing this requires either a dockerized
   Postgres in CI or a live Supabase project reachable from tests — out of scope for Phase 0.
2. **Whether `migration_v15`'s `registrations` RLS replacement (paid-only) is actually applied
   to the live production Supabase project is unverified.** `PHASE_A_BASELINE.md`/
   `LIVE_SUPABASE_VERIFICATION.md` (2026-09-09) confirmed the *prior* anon-read policy was live;
   this pass could not re-verify against a live project (no credentials available in this
   session). See `BASELINE.md`.
3. **Resolved by Phase 1A (hardened)**: a reusable, checked-in, tested comparison now exists
   (`scripts/audit-external-identity.ts` + `lib/external-identity/`), superseding the "no
   automated/repeatable comparison" gap this item previously flagged, and an independent live
   validation of its semantics was supplied by architecture review on 2026-09-15
   (`PHASE_1A_LIVE_VALIDATION_2026-09-15.md`: 397 comparability groups, 1 exact agreement, 0
   disagreements, 0 observed anomalies). What remains open: the checked-in CLI itself has still
   never been executed against production by any Claude session (see "Live audit status" above) —
   running it directly and recording the result as a dated addendum is the natural next check-in,
   not a new packet. Both the 2026-09-15 reviewer validation and the earlier
   `LIVE_IDENTITY_BASELINE_2026-09-15.md` comparison remain point-in-time snapshots, not standing
   guarantees (both mechanisms move independently).
4. **Whether the legacy per-model serving projection path (§9 mechanism 2 in
   `CURRENT_STATE.md`) is still operationally exercised, or has been fully superseded by the
   full-release path, is not established from repository state alone.** Both are wired, tested,
   and neither has been removed.
5. **`README.md`'s manual quick-start example calls the base `tdr_bridge.release`, not
   `tdr_bridge.release_enriched`, which is what CI/production actually publish.** Minor
   documentation drift, noted rather than fixed in Phase 0 (not a code/behavior change).
6. **Resolved / retracted**: an earlier draft of the Phase 1 completion packet proposed
   `supabase/migration_v28_external_identity_registry_operational.sql`, dropping
   `canonical_object_map_verified_target_uq`. Architecture review found that index load-bearing for
   `apply_vehicle_serving_projection`'s (Phase-E) canonical_id-only row selection, and the draft
   migration was reverted and deleted, not merely left unapplied — no Supabase migration is part of
   Phase 1. In its place, `tdr_bridge/external_identity_sync.py` detects a registry state that is
   not representable under the existing index (`operational_target_uniqueness_blocker`) and refuses
   to write it, rather than changing the database constraint. The registry's current single binding
   is fully representable today (see "Live result" above), so this does not block Phase 1; a future
   registry entry that would violate the index is caught by this detection before any write is
   attempted. Changing the DB invariant itself would require first redesigning Phase-E's model-row
   selection semantics — out of scope here, and not needed for current registry contents.
7. **The registry↔operational sync tool has not been run live.** See "Live result for the
   registry↔operational sync tool" above — predicted-safe from existing evidence, not confirmed.
8. **The DLT v2 backfill/parity tools have not been run live**, so production registration parity
   (v1 `registrations` vs the v2 shadow) is genuinely unknown, not predicted-safe — see "Live
   result for the DLT v2 tools" above and `PHASE3_CUTOVER.md` §F for the exact commands. This is
   recorded as ordinary deployment work an operator with credentials performs next, not a design
   gap or a reason to treat Phase 2/3 as incomplete: the infrastructure is implemented and tested;
   only its first live run against production is outstanding.
9. **`migration_v30`/`migration_v31` have not been applied to the live production project, and
   the registration serving switch has never been flipped.** No cutover readiness report has been
   produced against live data, so whether the gate would actually be clean is unknown, not
   predicted-safe. Applying the two migrations alone is expected to be a no-op for every current
   consumer (`registration_serving_state.active_source` defaults to `'legacy'`) — but that
   expectation itself has not been confirmed live, and should be, before proceeding to `--switch
   v2`. See `PHASE3_CUTOVER.md` §F for the exact command order.

## Next approved step

**None as new code.** Phase 1, 2, and 3 implementation are complete. Phase 3's **production
cutover** is deployment/operational work pending live credentials — not blocked on any further
implementation, and not itself a new phase to authorize (this is explicitly not "Phase 3A/3B";
see `PHASE3_CUTOVER.md` §H). The next retirement/cleanup step — which the task authorizing this
packet calls "Phase 4," while `MIGRATION_PLAN.md`'s own pre-existing Phase 0 sequence assigns that
role to **Phase 7 — Legacy decommissioning** (Phases 4–6 there are unrelated work — see
`PHASE3_CUTOVER.md`'s "Next phase" note for the numbering tension, stated plainly rather than
silently resolved) — remains unauthorized until a separate, explicit task authorizes it, and per
Invariant 13 must not begin before a demonstrated, live cutover period.

Operational follow-ups that need only credentials, not new code or a new phase (safe to do at any
time, not blocking Phase 4):
- run `tools/sync_external_identity_registry.py` (dry-run, then `--apply` if clean) against the
  live production project and record the result as a dated addendum — see the Phase 1 "Live
  result" above for the exact command and the predicted (unconfirmed) outcome;
- run `scripts/audit-external-identity.ts` similarly, per the Phase 1A parity gap above;
- follow `PHASE3_CUTOVER.md` §F's exact command order end to end: apply
  `migration_v29`/`migration_v30`/`migration_v31`, dry-run then apply the backfill, dry-run then
  apply direct DLT ingest for the current period, set the source-ownership boundary, run
  `tools/registration_v2_parity.py --readiness`, and — **only if the gate reports
  `is_ready_for_cutover: true`** — run `tools/registration_v2_cutover.py --switch v2`, then
  smoke-test `/api/report/registration`/`/api/report/market`. No outcome is predicted for any of
  this; production registration parity/readiness is unknown until it actually runs. Rollback at
  any point is `tools/registration_v2_cutover.py --switch legacy` — no data reconstruction
  required.

Candidates for a future, separately-authorized **Phase 4** (not implemented, not started, not
scoped in detail here — see `MIGRATION_PLAN.md`'s Phase 3/4 sections and `PHASE3_CUTOVER.md`
§H "Next phase"): retiring `registrations`/the alias tables/`match_registration_model`/the legacy
dashboard views, only after a demonstrated live cutover period and a proven rollback, per
Invariant 13.

Do not start Phase 4 work, and do not switch the production cutover live, from this file alone —
this file records state; it does not grant authorization or substitute for the readiness gate.
