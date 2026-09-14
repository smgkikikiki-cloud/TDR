# Migration Status — Current

Operational state for future coding agents. Keep this short. Update it in the same change that
completes or starts any migration packet.

## Current migration phase

**Phase 0 — architecture contract and parity foundation.** Documentation set created
2026-09-14 (`CURRENT_STATE.md`, `MASTER_ARCHITECTURE.md`, `INVARIANTS.md`, `MIGRATION_PLAN.md`,
this file, `BASELINE.md`), plus one narrowly-scoped regression test (see "Completed migration
packets" below). **Received architecture review; amended 2026-09-15** (see
`LIVE_IDENTITY_BASELINE_2026-09-15.md`) to incorporate two reviewer corrections:

1. **Identity-graph decision**: canonical vehicle identity is documented as a graph (Generation
   scoping two distinct children, Configuration/Variant and MarketTrim, linked optionally — not a
   strict `Configuration → MarketTrim` chain). `MASTER_ARCHITECTURE.md` and `MIGRATION_PLAN.md`
   were revised; the term "canonical identity graph" replaces "canonical vehicle spine."
2. **Live external-identity baseline recorded**: a 2026-09-15 reviewer-supplied, read-only live
   Supabase inspection found Mechanism A (383 derived Brand+Model links) and Mechanism B (1
   verified Brand/Model mapping) are not comparable registries — Mechanism A is broad/derived for
   serving, Mechanism B is a sparse, explicit write-authority gate. Recorded in
   `LIVE_IDENTITY_BASELINE_2026-09-15.md`, linked from `BASELINE.md` and `CURRENT_STATE.md`. The
   Phase 1 problem statement in `MIGRATION_PLAN.md` was rewritten around this — it is now about
   building one external-identity contract that preserves derived-vs-verified trust semantics,
   not about "reconciling" two crosswalks into agreement.

**No production behavior, schema, serving path, write path, canonical data, or application code
changed in either the 2026-09-14 pass or the 2026-09-15 amendment.** Both passes are
documentation-only (the 2026-09-14 pass also added one pure-Python regression test; the
2026-09-15 amendment added no test changes).

Phases 1–7 (`MIGRATION_PLAN.md`) remain **not authorized and not started**. This amendment does
not start Phase 1 — it only corrects Phase 0's documentation.

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
| Phase 0 amendment: identity-graph correction + live identity baseline | 0 | Reviewer-directed correction of `MASTER_ARCHITECTURE.md`/`MIGRATION_PLAN.md`'s identity structure and Phase 1 problem statement; added `LIVE_IDENTITY_BASELINE_2026-09-15.md` recording reviewer-supplied live Mechanism A/B evidence. Documentation only, no code change. |

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
3. **No automated/repeatable comparison between Mechanism A and Mechanism B exists.** A live,
   reviewer-supplied point-in-time comparison was performed manually on 2026-09-15
   (`LIVE_IDENTITY_BASELINE_2026-09-15.md`: 383 Mechanism A links, 1 verified Mechanism B link,
   0 disagreements), which resolves the *coverage/trust-semantics* uncertainty this item
   originally flagged — but no checked-in script, view, or test reproduces that comparison, so
   the result cannot be re-verified except by another manual live query, and it is a snapshot,
   not a standing guarantee (both mechanisms move independently). Building a reusable audit tool
   is explicitly named as the likely Phase 1A packet (see "Next approved step"), not implemented
   here.
4. **Whether the legacy per-model serving projection path (§9 mechanism 2 in
   `CURRENT_STATE.md`) is still operationally exercised, or has been fully superseded by the
   full-release path, is not established from repository state alone.** Both are wired, tested,
   and neither has been removed.
5. **`README.md`'s manual quick-start example calls the base `tdr_bridge.release`, not
   `tdr_bridge.release_enriched`, which is what CI/production actually publish.** Minor
   documentation drift, noted rather than fixed in Phase 0 (not a code/behavior change).

## Next approved step

**None.** Per the task brief, Phase 1 remains unauthorized until the next explicit task — this
2026-09-15 amendment corrects Phase 0's documentation only and does not authorize or start Phase 1.

The likely next packet, if and when authorized, is **Phase 1A: a pure, read-only external-identity
contract and audit abstraction** that:
- defines a shared shape/vocabulary able to represent a Mechanism-A-style derived mapping and a
  Mechanism-B-style verified mapping side by side, for the same external ID, without collapsing
  one into the other;
- ships as a read-only audit report/tool over the two existing mechanisms (no new table, no
  write path, no auto-population of `canonical_object_map`, no change to
  `lib/canonical-write-shadow.ts` or the release builder);
- makes the 2026-09-15 manual comparison in `LIVE_IDENTITY_BASELINE_2026-09-15.md` reproducible
  and re-runnable, instead of ad hoc;
- preserves Mechanism B's `verified`-only write-authority gate exactly as-is — a derived
  Mechanism A match must never become an implicit `verified` row.

Phase 1A is **not implemented by this amendment**. Do not start Phase 1/1A work from this file
alone — this file records state; it does not grant authorization.
