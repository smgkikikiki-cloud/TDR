# Migration Status — Current

Operational state for future coding agents. Keep this short. Update it in the same change that
completes or starts any migration packet.

## Current migration phase

**Phase 0 — architecture contract and parity foundation.** Completed by this pass (2026-09-14):
documentation set created (`CURRENT_STATE.md`, `MASTER_ARCHITECTURE.md`, `INVARIANTS.md`,
`MIGRATION_PLAN.md`, this file, `BASELINE.md`), plus one narrowly-scoped regression test added
(see "Completed migration packets" below). No architecture, schema, or behavior change.

Phases 1–7 (`MIGRATION_PLAN.md`) are **not authorized and not started**.

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

## Known parity gaps (things Phase 0 could not close)

1. **No test exercises `publish_vehicle_release` or `rollback_vehicle_release`.** Both are
   Postgres functions in `supabase/migration_v15_canonical_vehicle_release.sql`; this repository
   has no local/offline Postgres test harness. Closing this requires either a dockerized
   Postgres in CI or a live Supabase project reachable from tests — out of scope for Phase 0.
2. **Whether `migration_v15`'s `registrations` RLS replacement (paid-only) is actually applied
   to the live production Supabase project is unverified.** `PHASE_A_BASELINE.md`/
   `LIVE_SUPABASE_VERIFICATION.md` (2026-09-09) confirmed the *prior* anon-read policy was live;
   this pass could not re-verify against a live project (no credentials available in this
   session). See `BASELINE.md`.
3. **Mechanism A vs. Mechanism B crosswalk reconciliation does not exist.** No report or test
   compares `current_vehicle_models.tdr_model_id` (Mechanism A) against `canonical_object_map`
   (Mechanism B) for disagreement. This is Phase 1's stated problem to solve, not Phase 0's to
   fix — recorded here so it isn't lost.
4. **Whether the legacy per-model serving projection path (§9 mechanism 2 in
   `CURRENT_STATE.md`) is still operationally exercised, or has been fully superseded by the
   full-release path, is not established from repository state alone.** Both are wired, tested,
   and neither has been removed.
5. **`README.md`'s manual quick-start example calls the base `tdr_bridge.release`, not
   `tdr_bridge.release_enriched`, which is what CI/production actually publish.** Minor
   documentation drift, noted rather than fixed in Phase 0 (not a code/behavior change).

## Next approved step

**None.** Per the task brief, only Phase 0 is authorized. The next step is for a human (or a
separately-authorized task) to review this documentation set and explicitly approve starting
Phase 1 (`MIGRATION_PLAN.md`) — most likely scoped narrowly to the Mechanism A/B crosswalk
reconciliation report named in parity gap 3 above, since it requires no behavior change and
would close the most concretely-identified duplication.

Do not start Phase 1 work from this file alone. This file records state; it does not grant
authorization.
