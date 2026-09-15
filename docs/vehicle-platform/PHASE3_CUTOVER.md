# Phase 3 — Registration Migration: Cutover Infrastructure

**Status: implementation complete and tested. Production cutover is pending a live readiness
gate — no Supabase credentials were available in this session (see "Live result" below), so
nothing described here has been applied to, or switched on, the live production project.**

**2026-09-15 safety patch.** Architecture review found three concrete cutover blockers in the
original Phase 3 pass, all fixed in place (`migration_v31` had never been applied to production,
so it was corrected directly rather than superseded by a new migration):

1. `registration_facts_v2_serving` started from `registration_facts_v2` (an inner join), so a
   completely unresolved observation — no fact at all — contributed nothing to serving. Fixed to
   start from the authoritative *observation* set, `LEFT JOIN`ing the optional fact (§B).
2. `build_cutover_readiness_report` passed **all** v2 observations/facts into parity, so a period
   with both `legacy_registrations_backfill` and `dlt_ckan` volume could double-count even though
   the serving boundary intentionally selects only one. Fixed to filter to the authoritative
   subset before computing parity, while keeping excluded rows visible in
   `source_lineage_overlaps` (§D).
3. The market-slice path (`lib/registration-analytics.ts`) never selected/used
   `registration_reporting_source`'s existing `canonical_model_id` column, so a v2-resolved row
   was still sent through the reverse legacy-uuid crosswalk. Fixed minimally: select the column,
   resolve by it directly when present, fall back to the unchanged legacy path otherwise (§C).

This is a safety patch to Phase 3, not a new phase — no new migration file, no Phase 3A/3B, no
Phase 4 work.

This document records Phase 3:

```
DLT → immutable observation v2 → canonical resolution/fact v2 → production registration
analytics/API
```

with a reversible cutover, per `MIGRATION_PLAN.md`'s Phase 3 intent and Invariant 12. It assumes
familiarity with `MASTER_ARCHITECTURE.md`, `INVARIANTS.md`, `DLT_V2_ARCHITECTURE.md` (Phase 2),
and `status/CURRENT.md`, and does not restate that material.

## A. Two Phase-2 preflight gaps, fixed

### A1 — `registration_observations_v2` is now actually immutable

Phase 2 granted `service_role` full CRUD on all three shadow tables and wrote observations with a
merge-upsert keyed only on `observation_id`. That let a changed source payload under an unchanged
id silently overwrite the original evidence. Fixed at two independent layers:

- **Write-side** (`vehreg/registration_v2_writer.py`): `build_batch` now groups an input list by
  `observation_id` in two passes. A group with one distinct `payload_hash` is the existing,
  correct idempotent-repeat case (collapsed to one row, one resolution). A group with more than
  one distinct hash is a `DriftConflict` (`source="within_batch"`) — **none** of its occurrences
  produce a row; "must fail, not keep the first silently" is enforced structurally, not by
  convention. `plan_observation_writes(batch, existing_payload_hashes)` then checks every
  surviving id against what a live caller already fetched from the database: not-yet-seen → plain
  insert; same hash already persisted → `unchanged` (no-op); different hash already persisted →
  `DriftConflict(source="existing")`. `writes_to_apply(batch, plan)` is the same whole-run
  fail-closed gate Phase 1 established (`mutations_to_apply`): **any** drift conflict anywhere —
  within the batch or against what is persisted — means zero writes for the entire run, not even
  for unrelated, individually-clean ids. Fact/review rows remain freely upsertable for any
  non-conflicting id, since they are derived and may always be regenerated.
- **DB-side** (`supabase/migration_v30_registration_v2_immutable_observations.sql`): `service_role`
  loses `UPDATE`/`DELETE` on `registration_observations_v2` entirely (only `SELECT`/`INSERT`
  remain), and a `BEFORE UPDATE OR DELETE` trigger unconditionally raises — defense in depth
  beyond grants alone, without building an event-sourcing system.

Both `tools/backfill_registration_v2.py` and the new `tools/registration_v2_dlt_ingest.py` (below)
were updated to this plan/apply shape: they fetch existing hashes for the batch's ids, plan, print
the plan, and only ever plain-`INSERT` a row already classified as new.

### A2 — Direct DLT → v2 ingest exists

`tools/registration_v2_dlt_ingest.py` is the forward ingestion path DLT v2 was always missing: it
reads DLT's own CKAN API directly (`vehreg.dlt.monthly_index`/`fetch_records`/
`REGISTRATION_BY_THAI_TYPE` — unchanged, the exact functions `vehreg.dlt.fetch_month` already
uses), adapts each RY1/RY2/RY3 record with `RegistrationObservation.from_dlt_record` (unchanged
from Phase 2), and resolves/writes through the same unmodified `vehreg.ingest.Resolver` and
`vehreg/registration_v2_writer.py` every other v2 tool uses — no Resolver logic is duplicated.
Dry-run by default; `--apply` required to write; one or more `--period YYYY-MM` selects the
month(s).

**Source-lineage ownership** (preventing `legacy_registrations_backfill` and `dlt_ckan` from both
becoming authoritative v2 volume for the same period) is a simple, deterministic period/source
rule, not a source-priority framework:
`vehreg.registration_v2_parity.authoritative_source_for_period(period, boundary_period)` — a
period on or before the configured boundary is `legacy_registrations_backfill`-authoritative,
after it is `dlt_ckan`-authoritative; with no boundary configured (the default), every period is
still backfill-authoritative. The boundary lives in exactly one place —
`registration_serving_state.v2_source_boundary_period` (§B) — and is enforced at **read/serving
time**, in `registration_facts_v2_serving` (§B) and in the readiness gate
(`find_source_lineage_overlaps`/`find_unresolved_source_ownership`, §D), not by refusing writes:
writing a period's DLT observations/facts into the shadow tables is always safe (immutable,
idempotent, inspectable); which source's volume actually *counts* as authoritative is a read-time
decision made in one place.

## B. v2 serving projection

**The authoritative *observation* is the volume source of truth; fact resolution is optional.**
`registration_facts_v2_serving` is `registration_observations_v2 LEFT JOIN registration_facts_v2`
(filtered to the period-authoritative `source_kind`, §A2), never the reverse. Before the safety
patch it started from `registration_facts_v2` (effectively an inner join), so a completely
unresolved observation — brand not found at all, no fact row exists — contributed nothing to
serving; its units simply vanished from every downstream total. `registration_facts_v2`'s own
primary key is `observation_id` (`migration_v29`), so the `LEFT JOIN` can never fan out — every
authoritative observation contributes its units exactly once, resolved or not.

For a completely unresolved observation, `registration_facts_v2_serving` now emits a row with
`canonical_id`/`canonical_model_id`/`canonical_brand_id`/`grain` all `NULL` and `raw_brand`/
`raw_model`/`units` retained from the observation itself (never from the missing fact). For a
BRAND-grain fact, `canonical_brand_id` is populated and `canonical_model_id` stays `NULL` — never
distributed into a model. MODEL/VARIANT behavior is unchanged from the original pass.

`vehreg/registration_v2_rollup.py` (pure, offline-testable) is the reference implementation this
SQL mirrors:

- a MODEL-grain fact counts directly, at its own canonical id.
- a VARIANT-grain fact rolls up to its canonical model (`model_component` — the first two
  dot-segments of its id, reused unchanged from `vehreg/registration_v2_parity.py`).
- a BRAND-grain fact is **never** distributed across the brand's models — it stays a brand-only,
  explicitly measurable "unknown/coarse" bucket (`unknown_coarse_volume_by_brand`), visible even
  when a report asks for MODEL grain, never silently dropped (Invariant 15).
- every grain rolls up safely to brand (`brand_level_rollup`) — a brand total is always a plain
  `sum(units) group by canonical_brand_id`, no separate "unknown" bucket needed there, because
  brand is always known whenever anything deeper is.
- (safety patch) a completely unresolved observation's units are tracked separately
  (`unresolved_units`) and are neither dropped nor folded into any grain bucket.

`RollupFact`/`model_level_rollup`/`brand_level_rollup`/`unknown_coarse_volume_by_brand`/
`rollup_reconciles` describe only already-resolved facts (unchanged from the original pass); the
new `ServingRow`/`resolved_rollup_facts`/`unresolved_units`/`serving_reconciles` describe the
broader, observation-driven shape the corrected view now emits. Because each fact corresponds to
exactly one observation, no unit is ever counted under two buckets, and none is dropped:
`model_level_rollup + unknown_coarse_volume_by_brand + unresolved_units == sum of every serving
row's units`, exactly, proven by
`tests/test_registration_v2_rollup.py::test_resolved_plus_unresolved_serving_units_reconcile_to_observation_total`.

## C. Cutover compatibility

**One boundary, not a rewrite of every consumer.** Inspecting every current registration
consumer found that both `/api/report/registration` and `/api/report/market` already route
through the same shared library, `lib/registration-analytics.ts` — `getRegistrationAnalytics`
(dimension views: `registration_analytics_coverage`, `registration_brand_share`,
`registration_model_share`, `registration_model_mom`, `registration_monthly_segment`,
`registration_monthly_powertrain`, `registration_chinese_bev_rank`) and
`getRegistrationMarketSlice` (raw-row fetch + in-process canonicalization via
`current_vehicle_models`/`current_vehicle_brands`/`registration_brand_aliases`). Every one of
those seven dimension views is built, directly or transitively, on exactly three views that read
`registrations`: `registration_analytics_coverage`, `registration_monthly_brand`,
`registration_monthly_model`.

`supabase/migration_v31_registration_v2_serving_and_cutover.sql` introduces:

- **`registration_serving_state`** — a single-row config table (the same pattern
  `canonical_vehicle_state` already uses for the Vehicle Master release pointer):
  `active_source` (`'legacy' | 'v2'`, default `'legacy'`) and `v2_source_boundary_period`.
  Applying this migration changes zero behavior until an operator explicitly flips it.
- **`set_registration_serving_source(text)`** / **`set_registration_v2_source_boundary(text)`** —
  the atomic, reversible switch: each is a single `UPDATE` of that one row, inside a `security
  definer` function, `service_role`-only. Switching `active_source` back to `'legacy'` is instant
  and needs no data reconstruction, because `registrations` is never written by any part of the v2
  pipeline or this switch.
- **`registration_facts_v2_serving`** — the v2 serving projection (§B).
- **`registration_reporting_source`** — **the one compatibility boundary**: a view shaped like
  `registrations` (plus a `canonical_model_id` passthrough and a `fact_source` tag), that reads
  `registrations` when `active_source = 'legacy'` and the v2 serving projection when
  `active_source = 'v2'`. A v2-sourced row's `model_id` is a **best-effort reverse crosswalk**
  (`current_vehicle_models.tdr_model_id`) of its `canonical_model_id`, purely so every existing
  `model_id`-keyed view/join keeps working unmodified — nothing in the v2 resolution pipeline
  itself ever treats that uuid as canonical (`DLT_V2_ARCHITECTURE.md`). A v2 BRAND-grain fact
  (`canonical_model_id` null) presents as `model_id` null — identically to legacy's own
  "unmapped" representation, the same honest coarsening, not a new concept. Where no legacy model
  row exists for a v2-only canonical model, the reverse crosswalk is null too — a known, documented
  compatibility-layer limitation (the model still counts at brand grain and is fully visible in
  the native v2 serving projection; only the legacy-shaped compatibility view coarsens it).
- **`registration_analytics_coverage`/`registration_monthly_brand`/`registration_monthly_model`**
  redefined to read `registration_reporting_source` instead of `registrations` directly — their
  `SELECT`/`WHERE`/`GROUP BY` logic is byte-for-byte unchanged, only the `FROM` target moves. Every
  view built on top of these three inherits the switch with **zero changes of its own**.

**TypeScript**: `lib/registration-analytics.ts`'s `fetchRegistrationRows` (the only place in the TS
layer that reads `registrations` directly) reads `registration_reporting_source` instead —
`.from("registrations")` → `.from("registration_reporting_source")`. `getRegistrationAnalytics`'s
dimension-view path needs **no TypeScript change at all**, since it already queries the view names
that are now switch-aware at the SQL layer.

**Safety patch fix #3**: `registration_reporting_source` already exposed `canonical_model_id`, but
`fetchRegistrationRows` did not select it and `canonicalizeRegistrationRows` never used it — so a
correctly-resolved v2 row was still sent through the reverse legacy-uuid crosswalk
(`model_id → current_vehicle_models.tdr_model_id`) a second time, gaining nothing from having a
direct canonical id available. Fixed minimally: `fetchRegistrationRows` now also selects
`canonical_model_id`; `canonicalizeRegistrationRows` builds a second lookup map
(`modelsByCanonicalId`, keyed by `current_vehicle_models.canonical_id`) alongside the existing
`modelsByTdrId`, and resolves `row.canonical_model_id ? modelsByCanonicalId.get(...) :
(row.model_id ? modelsByTdrId.get(...) : undefined)` — a v2 row with a canonical id needs no legacy
uuid at all; a legacy row (`canonical_model_id` always null while `active_source = 'legacy'`) falls
through to the exact, unchanged prior behavior; a row with neither stays unresolved and renders as
`"UNKNOWN"`/`canonically_mapped: false`, exactly as before — never guessed. No SQL dimension view
and no other part of the registration UI was touched.

`tools/registration_v2_cutover.py` is the switch's operator interface: `--status`, `--switch
{legacy,v2}`, `--set-boundary YYYY-MM|none`. It performs no readiness check itself — it is a dumb,
honest switch, deliberately kept separate from the gate (§D) so the two stay independently
auditable. `--switch legacy` is the rollback path; it is the identical code path as `--switch v2`
(the same RPC, the opposite argument), not a special case.

## D. Parity / cutover-readiness gate

**Reused, not duplicated.** `tools/registration_v2_parity.py --readiness` wraps the *same*
`ParityReport` a plain parity run already builds
(`vehreg.registration_v2_parity.build_parity_report`) in a new
`CutoverReadinessReport`/`build_cutover_readiness_report` — no second, redundant validator.
Cutover eligibility (`is_ready_for_cutover`) requires:

- `parity.is_clean` — volume reconciliation clean (no period/registration-type mismatch), no
  duplicate `(source_kind, source_ref)`, no reconciliation (units-drift) failure.
- no source-drift blocker in the observation write plan (§A1) — enforced upstream at write time,
  not re-checked here (a blocked write never lands in the shadow tables to begin with).
- **no unresolved source-lineage ownership** (§A2) — a period with volume under both
  `legacy_registrations_backfill` and `dlt_ckan` and no boundary configured to adjudicate it.
- **every required period populated in v2** — `--required-periods` names the periods a cutover
  needs; any missing one blocks readiness.

**Safety patch fix #2 — readiness parity now mirrors what serving will actually count.** Before
the patch, `build_cutover_readiness_report` passed *every* v2 observation/fact into
`build_parity_report`, so a period straddling the source-ownership boundary (e.g. both a
`legacy_registrations_backfill` row and a `dlt_ckan` row for the same period) could sum both
sides' volume even though `registration_facts_v2_serving` would only ever serve one of them —
readiness could pass on a total the running system would never actually produce. Fixed:
`authoritative_v2_observations(v2_observations, boundary_period)` filters to exactly the
`(source_kind, period)` combinations `authoritative_source_for_period` selects (the same rule the
SQL serving view applies, and — like it — never treats `dlt_csv` as an ownership participant), and
`authoritative_v2_facts` filters facts *through their owning observation's id* — never by
independently inferring ownership from a fact, since `V2FactRow` does not even carry
`source_kind`. `build_cutover_readiness_report` now builds `parity` from this authoritative
subset, and `missing_required_periods` is computed from the authoritative subset's own periods —
"some shadow row exists somewhere" no longer counts as required-period coverage.

`source_lineage_overlaps` (§A2) is unaffected — computed from the *full*, unfiltered
`v2_observations` — so the excluded volume stays fully visible for an operator to inspect, even
though it no longer contributes to `parity` or `missing_required_periods`. A **plain** parity run
(`tools/registration_v2_parity.py` without `--readiness`) is also unaffected: it still calls
`build_parity_report` directly over all shadow data, unchanged — this fix touches only the
readiness path.

**100% identity agreement is explicitly not required.** `identity_disagreement` and
`grain_difference_v2_coarser` stay fully visible in the report's `pairs_by_classification` and
never appear in `blockers` — v2 being intentionally more conservative than v1's legacy crosswalk
is not, by itself, a readiness failure; only real volume/duplicate/reconciliation/ownership/
coverage problems are
(`tests/test_registration_v2_parity.py::test_identity_disagreement_alone_does_not_block_readiness`).

Output is one machine-readable JSON report (`summary.blockers`, `summary.is_ready_for_cutover`,
plus the full parity breakdown and the source-lineage overlaps). Exit code: `0` ready, `1` not
ready (never cut over on this), `2` could not run at all.

## E. Write consolidation

**`tools/registration_v2_dlt_ingest.py` is the forward registration ingestion path.** Once a
period's DLT observations have been ingested through it and the source-ownership boundary has
been advanced past `public.registrations`' last historical month, new DLT months should stop
flowing into `registrations` via `ingest_registration_snapshot` and instead flow only through this
direct path. `legacy_registrations_backfill` (`tools/backfill_registration_v2.py`) exists for
historical backfill only and is not the forward path.

Nothing here routes DLT registration data through the canonical vehicle-market command intake
(`vehreg/canonical_write.py`/`vehreg/canonical_queue.py`) — that remains ECO/product write-path
territory, untouched and unmentioned by any file this phase adds. `registrations`,
`registration_brand_aliases`, `registration_model_aliases`, `match_registration_model`, and every
existing `registration_*` view/function are **not deleted** — they remain available for rollback
throughout Phase 3. Deletion is Phase 4 (below), and only after a demonstrated, live cutover
period.

## F. Live result

**No live Supabase credentials are available in this session** — confirmed the same way every
prior phase confirmed it: no `SUPABASE_*` environment variable set, no local `.env`/`.env.local`
with real values. `tools/backfill_registration_v2.py`, `tools/registration_v2_dlt_ingest.py`,
`tools/registration_v2_parity.py` (plain and `--readiness`), and `tools/registration_v2_cutover.py`
all fail closed on every action attempted without credentials — verified directly
(`tests/test_registration_v2_tools_env.py`, `tests/test_registration_v2_dlt_ingest.py`,
`tests/test_registration_v2_cutover.py`). No migration in this packet has been applied to
production, no backfill/direct-ingest has run against production, no readiness report has been
produced against live data, and the serving switch has never been flipped. This is **implementation
complete; production cutover pending live gate execution** — not another architecture phase.

### Deployment order (required, not just suggested)

Application code (`lib/registration-analytics.ts`) already references
`registration_reporting_source`, which **does not exist in production until `migration_v31` is
applied** — so DB migrations must land, in order, before the application code that reads the view
they create. The full order:

1. Merge/apply DB migrations, **in order**, `migration_v29` → `migration_v30` → the corrected
   `migration_v31`, while the serving switch still defaults to `'legacy'` (it does — applying all
   three changes zero observed behavior on its own).
2. Deploy the application code that reads `registration_reporting_source`
   (`lib/registration-analytics.ts`). Steps 1 and 2 may land in the same release, but step 1's
   migrations must be applied first — deploying step 2 against a database that has not yet run
   `migration_v31` means `registration_reporting_source` does not exist and every registration
   query fails.
3. Historical backfill, dry-run: `python tools/backfill_registration_v2.py`.
4. Historical backfill, apply: `python tools/backfill_registration_v2.py --apply`.
5. Choose and set the source-ownership boundary:
   `python tools/registration_v2_cutover.py --set-boundary <last-backfilled-period>`.
6. Direct-DLT-ingest the appropriate shadow period(s), dry-run then apply:
   `python tools/registration_v2_dlt_ingest.py --period <YYYY-MM>` then `... --apply`.
7. Run the readiness gate:
   `python tools/registration_v2_parity.py --readiness --required-periods <...>`.
8. **Only if** readiness exits `0` (equivalently, `summary.is_ready_for_cutover: true`), flip the
   switch: `python tools/registration_v2_cutover.py --switch v2`.
9. Smoke-test `/api/report/registration` and `/api/report/market`.
10. On any regression at step 9 (or at any later point), immediately roll back:
    `python tools/registration_v2_cutover.py --switch legacy` — no data reconstruction required,
    since `registrations` was never written by any part of this pipeline or by the switch itself.

```
cd automotive/vehicle_master

# 1. apply migrations, in order (normal deployment path, not from this session)
#    supabase/migration_v29_registration_dlt_v2_shadow.sql            (Phase 2)
#    supabase/migration_v30_registration_v2_immutable_observations.sql
#    supabase/migration_v31_registration_v2_serving_and_cutover.sql   (corrected, safety-patched)

# 2. deploy application code that reads registration_reporting_source (already merged to this branch)

# 3-4. backfill
python tools/backfill_registration_v2.py                 # dry run
python tools/backfill_registration_v2.py --apply

# 5. source-ownership boundary
python tools/registration_v2_cutover.py --set-boundary 2026-08

# 6. direct DLT ingest for the period(s) after the boundary
python tools/registration_v2_dlt_ingest.py --period 2026-09
python tools/registration_v2_dlt_ingest.py --period 2026-09 --apply

# 7. readiness gate
python tools/registration_v2_parity.py --readiness --required-periods 2026-01,2026-02,...,2026-09

# 8. switch reads only if the gate is clean (exit 0, is_ready_for_cutover: true)
python tools/registration_v2_cutover.py --switch v2

# 9. smoke-test /api/report/registration and /api/report/market

# 10. rollback at any point, no data reconstruction:
python tools/registration_v2_cutover.py --switch legacy
```

## G. Tests

Focused suites were run during implementation; the full suite runs exactly once at the end of this
packet (see the completion report for the pass count). Original-pass coverage: `tests/
test_registration_v2_immutability.py` (idempotent no-op, within-batch and against-existing drift
conflicts, the global apply gate, derived rows still upsert for clean ids), `tests/
test_registration_v2_immutability_migration.py` (grants/trigger source-text regression), `tests/
test_registration_v2_dlt_ingest.py` (classification reuse, skipped-class accounting, argument/
credential guards), `tests/test_registration_v2_serving_cutover_migration.py` (switch defaults to
legacy, service-role-only single-UPDATE functions, the redirected views change only their `FROM`
target, no grant to `anon`/`authenticated`, no mutation of `registrations`), `tests/
test_registration_v2_cutover.py` (argument validation, no-credentials fail-closed, rollback is the
identical switch mechanism as cutover).

**Safety patch coverage**: `tests/test_registration_v2_rollup.py` extended with
`ServingRowUnresolvedObservationTests` (completely unresolved observation survives serving,
BRAND-grain survives without model allocation, MODEL/VARIANT unchanged, resolved + unresolved
serving units reconcile to authoritative observation units). `tests/test_registration_v2_parity.py`
extended with backfill/DLT overlap where only the boundary-selected source counts toward
authoritative parity, the excluded overlap staying reported, an authoritative total matching the
legacy total letting readiness pass, and a non-authoritative-only required period correctly *not*
satisfying required coverage (`CutoverReadinessReportTests`/`AuthoritativeFilteringTests`).
`tests/test_registration_v2_serving_cutover_migration.py` extended to assert the serving view now
reads `FROM registration_observations_v2 o ... LEFT JOIN registration_facts_v2 f`, never the
reverse, and that units/raw_brand/raw_model come from the observation, not the fact.

**Fix #3 (TypeScript) has no automated test in this repository.** `lib/registration-analytics.ts`
imports via the `@/` path alias (`@/lib/supabase`, `@/lib/historical-model-state`,
`@/lib/registration-market`), which only Next.js's own bundler/`tsc` resolve — this repository's
existing offline TS test convention (`node --experimental-strip-types scripts/check-*.ts`, no test
runner dependency) only ever exercises alias-free lib files, and every existing `check-*.ts` script
respects that boundary. Building a custom module-resolution loader to force this one file through
that convention was judged out of proportion for a "fix this minimally" patch. Verification for fix
#3 is `tsc --noEmit` (part of `npm run check` — it fully resolves `@/` aliases and would catch a
type error in the new `modelsByCanonicalId` map or the `row.canonical_model_id` fallback) plus
direct code review of the three required properties, traced against the exact `canonicalizeRegistrationRows`
code path: (1) a v2 row's `model` lookup now happens via `modelsByCanonicalId.get(row.canonical_model_id)`
before any `model_id` is consulted, so no legacy uuid is required; (2) a legacy row always has
`canonical_model_id: null` while `active_source = 'legacy'` (the SQL view only ever populates it in
the `'v2'` branch), so it falls through to the untouched `row.model_id ? modelsByTdrId.get(...) :
undefined` branch, byte-for-byte the prior logic; (3) a row with neither `canonical_model_id` nor
`model_id` resolves `model` to `undefined`, which was already the exact "unresolved" path
(`brand_name`/`model_name` fall back to raw text or `"UNKNOWN"`, `canonically_mapped: false`) —
unchanged, never guessed.

## H. What Phase 3 explicitly does not do

- **No production cutover.** No credentials, no live run — see §F.
- **No deletion.** `registrations`, the alias tables, `match_registration_model`, and every
  existing view/function remain exactly as they were. Deletion is Phase 4.
- **No change to ECO/product canonical write paths.** DLT registration ingestion stays a fully
  separate write path, as it always was.
- **No `vehreg/ingest.py`/`vehreg/dlt.py`/local-warehouse behavior change** — every DLT v2 tool
  reuses these unchanged, exactly as Phase 2 established.
- **No Phase 3A/3B.** This is one pass, per the authorizing task's explicit instruction; the only
  genuine split is the one already named above — implementation complete now, live cutover
  execution pending credentials.

## Next phase

**Legacy retirement/cleanup**, after a demonstrated, live cutover period and per Invariant 13 (no
destructive migration without a verified rollback path already proven). Not started, not scoped in
detail here.

**A numbering note, stated plainly rather than silently resolved**: the task that authorized this
packet names this next step "Phase 4." `MIGRATION_PLAN.md`'s own pre-existing sequence (fixed in
Phase 0, before this packet) assigns that role to **Phase 7 — Legacy decommissioning**, with
Phases 4–6 reserved for unrelated work (generic source/observation infrastructure + ECO
convergence; canonical command/write-path consolidation; Variant/Configuration + MarketTrim + DLT-
detail semantic consolidation). This packet does not renumber or redefine `MIGRATION_PLAN.md`'s
existing Phase 4–7 — that would be an undiscussed redesign of Phase 0's plan, out of scope here.
Reconciling the two numbering schemes (or confirming the newer instruction supersedes the older
plan for this specific step) is a small, explicit documentation decision for whoever authorizes the
retirement work next; it does not block or change anything this packet implemented.
