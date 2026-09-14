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

**Phase 1A is implemented (2026-09-16).** Phase 1A was the narrow first packet of Phase 1: a
read-only external-identity contract and audit engine. What now exists:

- `docs/vehicle-platform/EXTERNAL_IDENTITY_CONTRACT.md` — the vocabulary (external namespace/
  entity type/ID, canonical entity type/ID, mapping state, trust level, provenance), the
  comparability rule, and the audit classifications.
- `lib/external-identity/types.ts`, `audit.ts`, `mechanism-adapters.ts` — pure TypeScript
  (no I/O): the contract types, the classification engine, and adapters converting each
  mechanism's actual row shape into the shared contract.
- `scripts/audit-external-identity.ts` — a live, **SELECT-only** command (no insert / update /
  delete / upsert / RPC of any kind) that reads `current_vehicle_brands`,
  `current_vehicle_models`, and `canonical_object_map` and prints a human-readable summary plus a
  deterministic JSON report. Fails clearly (exit code 2, no fabricated output) when server-side
  Supabase credentials are absent.
- `scripts/check-external-identity-audit.ts` — pure tests against synthetic fixtures only (no
  2026-09-15 counts hard-coded), wired into `npm run check`.

**Production identity behavior is unchanged.** Mechanism A (`tdr_bridge/release.py`, the
`current_*` views) and Mechanism B (`canonical_object_map`, `lib/canonical-write-shadow.ts`)
behave exactly as before Phase 1A — this packet only reads them and reports on what it reads.

**No persistence migration has begun.** Phase 1A does not choose whether a future
external-identity registry wraps an existing mechanism, replaces one, or becomes something new —
see `MIGRATION_PLAN.md`'s Phase 1 section. **That decision, and the rest of Phase 1, remain
unauthorized and unstarted; Phase 1A completing does not authorize it.**

**Live audit status**: not run against a live Supabase project in this pass — no server-side
credentials were available in this session (confirmed: no `SUPABASE_*` environment variables
set). The tool was exercised against its own synthetic test fixtures only
(`scripts/check-external-identity-audit.ts`, all passing) and its no-credentials failure path was
verified directly (`node --experimental-strip-types scripts/audit-external-identity.ts` exits 2
with a clear message, no live Supabase call attempted). No live result exists to compare against
`LIVE_IDENTITY_BASELINE_2026-09-15.md` as of this pass.

Phases 1B (rest of Phase 1) and 2–7 (`MIGRATION_PLAN.md`) remain **not authorized and not
started**.

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
| Phase 1A: external-identity contract + read-only audit engine | 1 | Added `EXTERNAL_IDENTITY_CONTRACT.md`; `lib/external-identity/{types,audit,mechanism-adapters}.ts`; live SELECT-only `scripts/audit-external-identity.ts`; `scripts/check-external-identity-audit.ts` (wired into `npm run check`). No table created, no migration, no write to `canonical_object_map`, no change to `tdr_bridge/release.py` or `lib/canonical-write-shadow.ts`. |

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
3. **Resolved by Phase 1A**: a reusable, checked-in comparison now exists
   (`scripts/audit-external-identity.ts` + `lib/external-identity/`), superseding the "no
   automated/repeatable comparison" gap this item previously flagged. What remains open: the tool
   has not yet been run against live production data in any pass (see "Live audit status" above)
   — the 2026-09-15 manual comparison in `LIVE_IDENTITY_BASELINE_2026-09-15.md` is therefore still
   the only live evidence on record, and it remains a point-in-time snapshot, not a standing
   guarantee (both mechanisms move independently). Running the new tool against a live project and
   recording the result as a dated addendum is the natural next check-in, not a new packet.
4. **Whether the legacy per-model serving projection path (§9 mechanism 2 in
   `CURRENT_STATE.md`) is still operationally exercised, or has been fully superseded by the
   full-release path, is not established from repository state alone.** Both are wired, tested,
   and neither has been removed.
5. **`README.md`'s manual quick-start example calls the base `tdr_bridge.release`, not
   `tdr_bridge.release_enriched`, which is what CI/production actually publish.** Minor
   documentation drift, noted rather than fixed in Phase 0 (not a code/behavior change).

## Next approved step

**None.** Phase 1A is complete; the rest of Phase 1 remains unauthorized until a separate,
explicit task authorizes it. Completing Phase 1A does not itself authorize continuing Phase 1.

Candidates for a future, separately-authorized **Phase 1B** (not implemented, not started, not
scoped in detail here):
- run `scripts/audit-external-identity.ts` against the live production project and record the
  result as a dated addendum (this needs only credentials, not new code);
- use that live result plus `EXTERNAL_IDENTITY_CONTRACT.md`'s vocabulary to actually decide the
  Phase 1 persistence question — wrap an existing mechanism, replace one, or introduce a new
  canonical abstraction — which Phase 1A deliberately left open;
- if a persistence decision is made, design (not yet implement) the migration path for any
  existing `canonical_object_map` `verified` rows and any Mechanism A consumer that would need to
  read the new abstraction instead.

Do not start Phase 1B work from this file alone — this file records state; it does not grant
authorization.
