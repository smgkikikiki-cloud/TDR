# TDR portfolio control room — Master Roadmap v1.0 (OWNER APPROVED)

**Owner signoff:** 2026-10-11 · **State:** `OWNER_APPROVED` · **Scope:** approved portfolio design (operational gates separately closed). GitHub PR #204 records main adoption.

**Approved entrypoint:** [TDR_MASTER_ROADMAP_V1.md](TDR_MASTER_ROADMAP_V1.md). The owner reviewed the complete portfolio roadmap and approved its architecture, scope and sequencing on 2026-10-11. Main adoption is tracked in [PR #204](https://github.com/smgkikikiki-cloud/TDR/pull/204); agent bootstrap and CI enforcement require a separate committed and verified change. No execution permission, CI activation or production gate is implicitly granted.

## Read and authority order

1. `AGENTS.md` and `docs/WORK_STATE.md`: vehicle-master boundaries, persisted execution state, retired writers.
2. For Ice work, `docs/market-track/ROADMAP.md` **current gate** plus explicit owner approval.
3. For canonical Vehicle Master work, `docs/vehicle-db/VEHICLE_DB_V3.md` and the relevant current field registry; a proposal in PR #203 cannot amend V3 §4.
4. For existing website design, `docs/MERGE_DECISIONS.md` takes precedence over `design/GRAFT_PLAN.md`, then the page specs, and over older inconsistent `docs/PRODUCT_ACCESS.md` language where they conflict. **Do not implement a disagreement by silently choosing a winner across domains**; report it.
5. For standalone B2B Toolkit design, the 2026-10-10 owner-locked Spatial/UX handoff governs locked behavior **as historical design evidence**; it is not yet an adopted in-repository implementation contract. Port approved decisions only after owner review. Conflicts involving actual product entitlements/billing must be surfaced.
6. This folder: owner-approved portfolio architecture and scope via `TDR_MASTER_ROADMAP_V1.md`. Detailed unvalidated formulas, ambiguous operational state, budget, rights and execution tasks remain blocked by their named domain gates. This roadmap does not override higher-priority domain rules.

## Read this first (approved roadmap)

Start with [TDR_MASTER_ROADMAP_V1.md](TDR_MASTER_ROADMAP_V1.md) for the approved plan, then [OWNER_REVIEW.md](OWNER_REVIEW.md) for the decision record, and [G0_RECONCILIATION.md](G0_RECONCILIATION.md) for the unresolved execution blockers. **Roadmap approval and permission to run work are separate things.**

## CP-00 actual read-only evidence (October 11, 2026)

[CP00_SOURCE_COVERAGE_AUDIT_2026-10-11.md](CP00_SOURCE_COVERAGE_AUDIT_2026-10-11.md) now contains real Supabase SELECT-only counts and status, with explicit unresolved source/validity caveats: 1,431 CURRENT trims but only 273 have a matching LIST_PRICE; 320 LIST_PRICE observations all in Sep 2026; only 4 promotion rows date-window-cover the audit date, none yet a verified net cash offer; Ice has 69 months of reg trend but 0 owner-APPROVED crosswalk records (490 total). **CP-00 evidence round 1 is partial, NOT a methodology/production approval.**

## Current product readiness finding

[CP_V1_REPOSITORY_READINESS_AND_FIRST_SLICE.md](CP_V1_REPOSITORY_READINESS_AND_FIRST_SLICE.md) inventories actual current-main Price/Vehicle/Ice code and proposes CP-00...CP-05 evidence-to-product work packets. **No owner approval or execution rights granted.** It flags the existing market-price adapter's explicit 1,000-row cap, which must not be treated as a complete historical price source.

## Folder index

- [TDR_MASTER_ROADMAP_V1.md](TDR_MASTER_ROADMAP_V1.md): **OWNER-APPROVED master development roadmap v1.0** (branch-local until merge).
- [OWNER_REVIEW.md](OWNER_REVIEW.md): owner decision signoff and specific unapproved execution gates.
- [ENGINE_VALIDITY_AND_DEPENDENCIES.md](ENGINE_VALIDITY_AND_DEPENDENCIES.md): six measurement/evidence/falsification gates, integration requirements, and a staged delivery graph; proposed for review.
- [PRICING_ENGINES_METHODOLOGY_REVIEW.md](PRICING_ENGINES_METHODOLOGY_REVIEW.md): PDI and CTPDI source/price-basis/FX/missingness rules and adversarial tests; formulas not approved.
- [SPATIAL_NETWORK_METHODOLOGY_REVIEW.md](SPATIAL_NETWORK_METHODOLOGY_REVIEW.md): source-backed dealer Site/Franchise/Operator identity, event detection and region ACL; proposed for review.
- [PRESSURE_GOLDEN_CASES.proposed.json](PRESSURE_GOLDEN_CASES.proposed.json): 15 **synthetic, non-executable** QA examples; never infer owner approval.
- [COMPETITIVE_PRESSURE_METHODOLOGY_REVIEW.md](COMPETITIVE_PRESSURE_METHODOLOGY_REVIEW.md): draft observable-pressure methodology, formulas/tests, and whole-engine validity rubric. **Requires owner review; scoring remains unapproved.**
- [G0_RECONCILIATION.md](G0_RECONCILIATION.md): observed states, conflicts, required decisions and evidence, including the R6/run discrepancy and migration number collision.
- [DOMAIN_BOUNDARIES.md](DOMAIN_BOUNDARIES.md): workstream contracts, data and product boundaries, dependency gates, first vertical slice, detailed owner-locked Toolkit behavior.
- [portfolio.plan.json](portfolio.plan.json): **non-executable** candidate queue/dependency catalog for a future Enforcer.

## G0 release decision

- **Discovery / evidence reconciliation:** documented; no repository runtime changed.
- **Portfolio roadmap owner signoff:** ACHIEVED 2026-10-11; v1.0 architecture and dependency direction approved, main adoption tracked in PR #204.
- **Enforcer portfolio autonomy:** BLOCKED; `portfolio.plan.json` must never be interpreted as an executable job manifest.
- **Market Track:** preserve `CURRENT_GATE=R6_PRODUCTION_CROSSWALK` and `PRODUCTION_CROSSWALK_ALLOWED=false` until owner-controlled reconciliation and authorization.
- **Vehicle Master:** Phase 0 complete, Phase 1 governed writer absent. No proposed data-mutation job is ready.
- **PR #200, #201 and #203:** draft work on separate branches, not adopted production contracts.

No changes to `AGENTS.md`, `WORK_STATE.md`, `VEHICLE_DB_V3.md`, `MERGE_DECISIONS.md`, `design/`, `supabase/`, production DB, payment configuration, workflow automation or deployed services are made by G0.

## To exit G0 *operational* gate

Owner **has approved the roadmap**; do not ask for global portfolio approval again. The remaining actions are reconcile conflict C01–C04 as appropriate for their affected workstreams, adopt the roadmap into `main` under a separately permitted merge, update bootstrap/CI rules in a separately reviewed change, and approve the first scoped nonproduction task. Enforcer must never infer permission from the roadmap alone.
