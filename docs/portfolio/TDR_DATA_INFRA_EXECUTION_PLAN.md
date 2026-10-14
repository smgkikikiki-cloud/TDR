# TDR Data Infrastructure — Locked Work-Package Execution Order (2026-10-14)

**Authority:** `TDR_DATA_INFRA_COMPLETION_CONTRACT.md` + `data-infra.requirements.json` define successful outcomes; this file defines execution order only, not permission to merge or modify production. `TDR_DATA_INFRA_ACCEPTANCE_LEDGER.json` records evidence and owner decisions. Read all four before each task. Stale `WORK_STATE.md` / domain gate disagreements must be called out and resolved explicitly; no agent may infer a gate is open.

## Mandatory operating loop (every task / every Codex session)

1. Read `AGENTS.md`, the four files above, Master Roadmap / portfolio.plan.json, `WORK_STATE.md` and domain-specific gate documents.
2. Record: contract v1.0.0, branch/base SHA, requirement IDs, current acceptance statuses, touched files, negative tests, data readback and permitted actions. Never use the chat as the sole memory.
3. Inspect actual HEAD + production read-only first, compare with current ledger. **Reuse existing engines** rather than cloning another importer/identity/write path.
4. Make one bounded PR for one work package; testing and artifacts go in that PR. Tests are necessary but not sufficient. **No merge, migration, cutover, environment flag, or destructive cleanup without specific owner authorization**.
5. Record real evidence per ID. A PR closes a work package only, not a phase. `ACCEPTED` remains owner-only.

## Planned work packages (not yet authorized to execute in production)

| WP | Requirements | Actions / files to inspect | Exit evidence | Release boundary |
|---|---|---|---|---|
| G-0 | All IDs | Adopt completion contract, registry, ledger, AGENTS/CLAUDE pointers, CI, owner CODEOWNERS + required check | CI/negative tests + explicit branch Ruleset readback | **This PR is governance only** |
| A-1 | A-01, A-02, A-05 | Reconcile R7 Run #38572861365 and PR #246 with production; record latest scoped/class queue totals; bring roadmap, PR and work-state status into agreement | 69-month readback, full PR HEAD CI, owner gate decision | No silent merge/R8 |
| A-2 | A-04 | Adjust `lib/ice-market-engine.ts` range estimate semantics, preserve certainty/min/max | G63 (reg_trend=5, reg_est=5 vs midpoint=7.5), uncertainty, no-est and aggregation regression | Separate tested patch; not conditional on clearing queue |
| A-3 | A-03 | Make create/link/exclude transaction-safe or compensating and idempotent, remove outdated Admin Scope copy | Simulated partial failure, repeated admin action, two live identity samples already done | No production schema change without approved migration |
| B-1 | B-01..B-04 | Merged Ice deploy, member entitlement and period/source consistency, scoped member API and rollback rehearsals | Authentic Free/Pro prod smoke, market totals and gate readback | **R8 separately owner-approved** |
| C-1 | C-01, C-02, C-05 | Raise private bucket to safely fit accepted file; combine Storage upload, hash/signoff, importer, readback, R6 matcher, queue and R7 via orchestrator | One-upload/one-owner-action new-month rehearsal, corruption and retry tests | No unattended release or full runner without go |
| C-2 | C-03, C-04, C-06 | Version owner decisions and release bindings across new Ice master; carry-forward exact scopes, isolate rename/split/merge | 7.0→8.0 fixture and active-release/rollback integrity | Fix before first different-master live package |
| D-1 | D-01, D-02, D-06 | Audit Unspecified Isuzu, pickup RY, Mercedes/Rolls matcher, missing Segment/Body, approved identity snapshots | No totals dropped; source-backed enrichment + locked-row shadow diff | Price/spec source claims stay in master |
| D-2 | D-03, D-04, D-05, D-07 | Audit Ice rim/tyre/province/powertrain panels, repair Chinese EV ranking entitlement/source, adjust intelligence navigation, remove dead upload stub | Panel/use/access matrix, end-user screens and deletion dependency report | No premature dependency cleanup |
| E-1 | E-01, E-04, E-05 | Inventory actual Vehicle Master Phase 1 writer and PR drafts; align field authority, model/trim identity, observation/apply/revert | Real transaction and negative authorization tests | Legacy writer stays closed |
| E-2 | E-02, E-06, E-07 | Define Price Fetcher adapter input with per-OEM official sources, price/trim/effective-date evidence and reviewed reconcile | Fixture parse→observation→review→apply→serve→revert | Do **not** implement Price Fetcher crawler in this project |
| E-3 | E-03, E-06, E-07 | Define Spec Filler adapter at Model/Generation/Variant/Trim/field precision, units, applicability, source/version | Fixture ingest→validation→review→apply→serve→revert including lock conflicts | Do **not** implement full Spec Filler acquisition engine here |

## Known historical hazards / mandatory discriminations

- Ice parser/market-file reader is **not** OEM Price Fetcher, nor technical Spec Filler.
- `docs/WORK_STATE.md` and `docs/market-track/ROADMAP.md` on main may lag actual Production and PR #246. A doc pointer is **not** evidence the actual release was cut over.
- Scoped owner Crosswalk is keyed by Ice group + registration class; grouped RY3 approval cannot absorb RY1/RY2. Old `ice_monthly_refresh_queue` v69 bug requires v70 verified readback.
- Current scoped serving code rejects owner decisions whose `master_version` differs from latest import. Carry-forward across master version requires explicit accepted release semantics, not changing historical provenance.
- Native Ice reg_est and certainty must not be overwritten by midpoint estimates without a documented fallback.
- Treat reported R7 and PR #246 CI as real evidence to verify, **not** an owner authorization to merge or to enable `TDR_ICE_MEMBER_CUTOVER=approved`.
- Existing Vehicle Master DB is authoritative. New OEM/spec adapters must not write directly to `current_*` views, retired canonical-input tables or Ice Market fact tables.

## Stop conditions

Stop immediately and report an exact blocker if approval, source authority, release consistency, checksum, permission, idempotence or rollback evidence is missing. Keep the associated requirement OPEN/BLOCKED, even if a PR has merged. A failed acceptance test cannot be removed from the target registry to obtain a PASS.

## Outcome baseline

All 29 completion IDs initially OPEN on PR #247. Recorded historical evidence must be verified and owner-accepted separately. No claim of Phase A, B, C, D, E or PROJECT COMPLETE is authorized by this work-plan document.
