# TDR portfolio control room — G0 reconciliation (DRAFT)

**Snapshot:** 2026-10-11 · **State:** `REVIEW_REQUIRED` / **NOT adopted** · **Scope:** documentation only.

This folder inventories shared development workstreams and their interfaces; it is **not** a new source of operational authority. It does not supersede owner decisions, grant an agent permission to execute, or advance any existing roadmap gate. In particular, creating or merging this documentation must not automatically enable a task runner.

## Read and authority order

1. `AGENTS.md` and `docs/WORK_STATE.md`: vehicle-master boundaries, persisted execution state, retired writers.
2. For Ice work, `docs/market-track/ROADMAP.md` **current gate** plus explicit owner approval.
3. For canonical Vehicle Master work, `docs/vehicle-db/VEHICLE_DB_V3.md` and the relevant current field registry; a proposal in PR #203 cannot amend V3 §4.
4. For existing website design, `docs/MERGE_DECISIONS.md` takes precedence over `design/GRAFT_PLAN.md`, then the page specs, and over older inconsistent `docs/PRODUCT_ACCESS.md` language where they conflict. **Do not implement a disagreement by silently choosing a winner across domains**; report it.
5. For standalone B2B Toolkit design, the 2026-10-10 owner-locked Spatial/UX handoff governs locked behavior **as historical design evidence**; it is not yet an adopted in-repository implementation contract. Port approved decisions only after owner review. Conflicts involving actual product entitlements/billing must be surfaced.
6. This folder: *derived, provisional portfolio mapping only*. Every unapproved formula, status, new interface and scheduling target is a proposal.

## Read this first (owner review)

Start with [OWNER_REVIEW.md](OWNER_REVIEW.md): three short passes covering (A) what each workstream must do, (B) proposed sequencing and first Layer 3 product, and (C) governance roles **for design only**. All three verdicts are PENDING; do not treat the roadmap as approved.

## Folder index

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
- **Cross-domain owner adoption:** NOT achieved.
- **Enforcer portfolio autonomy:** BLOCKED; `portfolio.plan.json` must never be interpreted as an executable job manifest.
- **Market Track:** preserve `CURRENT_GATE=R6_PRODUCTION_CROSSWALK` and `PRODUCTION_CROSSWALK_ALLOWED=false` until owner-controlled reconciliation and authorization.
- **Vehicle Master:** Phase 0 complete, Phase 1 governed writer absent. No proposed data-mutation job is ready.
- **PR #200, #201 and #203:** draft work on separate branches, not adopted production contracts.

No changes to `AGENTS.md`, `WORK_STATE.md`, `VEHICLE_DB_V3.md`, `MERGE_DECISIONS.md`, `design/`, `supabase/`, production DB, payment configuration, workflow automation or deployed services are made by G0.

## To exit G0

Owner reviews the conflict register, resolves the critical blockers, selects the first bounded nonproduction task and explicitly authorizes the corresponding narrow implementation contract. The Enforcer may then receive individual scoped packets; it may not infer go from a merged portfolio file.
