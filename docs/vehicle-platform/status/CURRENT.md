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
  *deterministically, safely, reproducibly* projectable from Git — but its own behavior, schema
  content, and existing consumers are otherwise unchanged. One schema fix was required and applied
  as a new migration file (not yet run live — see "Live result" below):
  `supabase/migration_v28_external_identity_registry_operational.sql` drops
  `canonical_object_map_verified_target_uq`, the global partial-unique index that forbade more than
  one verified row per canonical target — a real conflict with the registry's cardinality model
  (multiple external identities may legitimately bind to one canonical target). Source-key
  uniqueness and the per-row correctness check are both untouched.
- **Operational projection/sync now exists.** `tdr_bridge/external_identity_sync.py` (pure
  reconciliation logic, no I/O) and `tools/sync_external_identity_registry.py` (the live CLI,
  dry-run by default, `--apply` for the one safe mutation type — creating a missing operational
  row for a registry binding — with reread-and-prove-convergence built into `--apply`) make
  "Git truth → controlled operational projection → existing consumer" real and repeatable. It can
  never update an existing operational row, never touch a row outside the registry's own keys
  (review-state, Phase-E, unknown-verified, retired-operational-only rows all survive untouched),
  and never imports anything back into Git.
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

**Phase 1 is closed. Phase 2 (DLT v2 shadow pipeline) is not started and remains unauthorized.**

**Live result for the registry↔operational sync tool**: not run against a live Supabase project —
no server-side credentials were available in this session (confirmed: no `SUPABASE_*` environment
variables set, no local `.env`/`.env.local` with real values), consistent with every prior Phase 1
session. What *was* verified without live access: `tools/sync_external_identity_registry.py`'s
own no-credentials path (fails closed, exit 2, no fabricated output, confirmed by direct
execution); its offline registry-validation step (runs and passes independently of Supabase); and
the full reconciliation/classification/mutation-proposal/convergence logic at the pure-function
level (`tests/test_external_identity_sync.py`, 18/18 passing, including apply-idempotency and
rerun-converges-to-zero-mutations). The exact command an operator with credentials should run:

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
  `docs/REGISTRATION_MARKET_CONTRACT.md`'s explicit transition rule.
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

## Shadow paths currently active

- Phase-C canonical write pipeline shadows the legacy Supabase model editor
  (`app/admin/catalog-actions.ts` writes legacy tables first, then best-effort enqueues a
  canonical shadow command) — `docs/consolidation/PHASE_C_WRITE_PIPELINE.md`.
- No Phase 1–7 (this document's numbering) shadow pipeline exists yet — none has been started.

## Completed migration packets

| Packet | Phase | What it did |
|---|---|---|
| Phase 0 documentation + baseline | 0 | Added `docs/vehicle-platform/*`. No code/behavior change. |
| `test_enriched_release_identity_is_stable_and_covers_lifecycle_and_history` | 0 | Closed a confirmed gap: the production-published `release_enriched.enrich_release` payload had no dedicated determinism/shape test (only the base `ReleaseBuilder` output did). Added to `automotive/vehicle_master/tests/test_tdr_bridge.py`. Pure-Python, no Supabase required. |
| Phase 0 amendment: identity-graph correction + live identity baseline | 0 | Reviewer-directed correction of `MASTER_ARCHITECTURE.md`/`MIGRATION_PLAN.md`'s identity structure and Phase 1 problem statement; added `LIVE_IDENTITY_BASELINE_2026-09-15.md` recording reviewer-supplied live Mechanism A/B evidence. Documentation only, no code change. |
| Phase 1A: external-identity contract + read-only audit engine | 1 | Added `EXTERNAL_IDENTITY_CONTRACT.md`; `lib/external-identity/{types,audit,mechanism-adapters}.ts`; live SELECT-only `scripts/audit-external-identity.ts`; `scripts/check-external-identity-audit.ts` (wired into `npm run check`). No table created, no migration, no write to `canonical_object_map`, no change to `tdr_bridge/release.py` or `lib/canonical-write-shadow.ts`. |
| Phase 1A hardening: corrected invariant, duplicate anomalies, read-only boundary, live validation | 1 | Architecture-review-directed amendment. Fixed the `canonicalId`/`mappingState` contract by encoding it as a discriminated union (a `retired`/`unmatched`/`ambiguous` row may legitimately keep a contextual `canonicalId` without becoming resolved/trusted); added `InvalidMechanismBRowError` fail-closed handling for a `verified` row with a null `canonical_id`; added `AuditAnomaly`/`report.anomalies` so duplicate same-mechanism assertions under one comparability key are surfaced, never silently reduced to the first row; precisely documented the read-only boundary as code-enforced, not credential-enforced; added `PHASE_1A_LIVE_VALIDATION_2026-09-15.md` recording architecture-review-supplied live results; corrected an internal `2026-09-16` date error to `2026-09-15` across `CURRENT_STATE.md`, `MIGRATION_PLAN.md`, and this file. Documentation + pure TypeScript only — no persistence, table, migration, or consumer change. |
| Phase 1B: Git-backed external-identity registry (shadow mode) | 1 | Added `docs/vehicle-platform/EXTERNAL_IDENTITY_PERSISTENCE.md` (ownership decision record); `automotive/vehicle_master/tdr_bridge/external_identity_registry.py` (dataclasses, loader, offline validator); `integration_data/external_identity_registry.json` (seeded with exactly the one explicitly-reviewed Jaecoo binding); `tools/validate_external_identity_registry.py` (offline CLI, no Supabase); `tests/test_external_identity_registry.py` (20 tests). Clarified `EXTERNAL_IDENTITY_CONTRACT.md` that `verified`/trust level and persistence ownership are separate dimensions, without changing any Phase 1A type, classification, or test. No Supabase migration, write, or consumer change; Mechanism A's 383 derived links and the 8 Phase-E projection-owned `canonical_object_map` rows were deliberately excluded from the seed. |
| Phase 1 completion: registry↔operational reconciliation/sync + schema fix | 1 | Added `automotive/vehicle_master/tdr_bridge/external_identity_sync.py` (pure reconciliation/classification/mutation-proposal, no I/O) and `tools/sync_external_identity_registry.py` (live CLI: dry-run default, `--apply` for the one safe mutation type, reread-and-prove-convergence built in). Added `supabase/migration_v28_external_identity_registry_operational.sql` (drops `canonical_object_map_verified_target_uq`, the global unique index that conflicted with the registry's multiple-external-IDs-per-canonical-target cardinality model; source-key uniqueness and the per-row correctness check both untouched) — file created, not applied to live Supabase in this pass. Tightened `external_identity_registry.py`'s validator to require `verified_at`/`verified_by` for active `explicit_review` bindings. Added `tests/test_external_identity_sync.py` (18 tests) and `tests/test_external_identity_registry_migration.py` (6 source-text regression tests over the new migration file). No production consumer, existing Supabase behavior, or Phase 1A TypeScript contract changed. **Phase 1 is closed by this packet.** |

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
6. **`supabase/migration_v28_external_identity_registry_operational.sql` has not been applied to
   the live production Supabase project.** The file was created, reasoned about for safety (index
   drop only — no data touched, no other constraint changed — see
   `EXTERNAL_IDENTITY_PERSISTENCE.md`'s "Schema decision"), and covered by a source-text regression
   test, but this pass had no live Supabase access to apply it, and applying a migration follows
   this repository's normal deployment path rather than an ad hoc connection from an agent session.
   Until applied, `tools/sync_external_identity_registry.py --apply` would still succeed for the
   current single registry binding (it only ever needs to *insert*, and the dropped index only
   blocks a *second* verified row at the same canonical target, which does not yet exist), but a
   second binding pointing at an already-verified canonical target would fail at the database level
   until this migration is applied.
7. **The registry↔operational sync tool has not been run live.** See "Live result for the
   registry↔operational sync tool" above — predicted-safe from existing evidence, not confirmed.

## Next approved step

**None.** Phase 1 is complete; Phase 2 (`MIGRATION_PLAN.md`'s DLT v2 shadow pipeline) remains
unauthorized until a separate, explicit task authorizes it. Completing Phase 1 does not itself
authorize starting Phase 2.

Operational follow-ups that need only credentials, not new code or a new phase (safe to do at any
time, not blocking Phase 2):
- run `tools/sync_external_identity_registry.py` (dry-run, then `--apply` if clean) against the
  live production project and record the result as a dated addendum — see "Live result" above for
  the exact command and the predicted (unconfirmed) outcome;
- run `scripts/audit-external-identity.ts` similarly, per the Phase 1A parity gap above;
- apply `supabase/migration_v28_external_identity_registry_operational.sql` through this
  repository's normal deployment path.

Candidates for a future, separately-authorized **Phase 2** (not implemented, not started, not
scoped in detail here — see `MIGRATION_PLAN.md`'s Phase 2 section): the canonical DLT v2 shadow
pipeline, run alongside the current `vehreg/ingest.py`/`vehreg/dlt.py` pipeline, reconciled against
it, before anything reads from the new pipeline.

Do not start Phase 2 work from this file alone — this file records state; it does not grant
authorization.
