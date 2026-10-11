# OWNER REVIEW — TDR Development Roadmap (first-pass, NOT APPROVED)

**Date:** 2026-10-11
**Purpose:** enable a *human* product-roadmap review before agent enforcement.  
**Current decision:** `REVIEW_PENDING`. Creating this review sheet, discussing it, or merging an informational PR is NOT an approval of methodology, code execution, R6, migrations, deployments or paid services.

## What the owner is being asked to review

Please review in **three small passes**. It is NOT necessary to sign off on all unresolved engineering details at once.

### PASS A — What are we building? (product and functional boundaries)

| Workstream | Expected function | Review status |
| --- | --- | --- |
| PR #200 / Identity Resolution | link Ice groups to **existing** TDR canonical models; EQUIVALENT / PART_OF / COMPOSED_OF, audited many-to-many bundles | architecture summarized; contract/thresholds not frozen |
| PR #201 / Identity Bootstrap | identify external models **not yet** in Vehicle Master; propose `DISCOVERED` identity after duplicate defenses | offline engine; no automatic current retail or production create |
| PR #203 / Catalog Maintainer | Queue A verify actual currently retailed Thai lineup; Queue B fill missing applicable specs for confirmed current trims; preserve locks/authority | offline simulator draft; Chunk 1 corrections/CI need review |
| Original TDR UI / Ice engine | overhaul original public/Pro Layer 1–2 UI; Market UI consumes Ice via typed adapter only when Ice gate allows | existing graft sequence and current market gate apply |
| PDI | sourced Thai national retail cash discount index, versioned universe, historical price events and coverage | some inclusion rules owner-locked; arithmetic/publication rules proposed |
| CTPDI | reviewed CN–TH comparable price gap with manual Admin Approve & Lock crosswalk, FX and traceable evidence | pair-vs-aggregate grain and headline convention unresolved |
| Geography | Dealer Site/Franchise/Operator evidence + network change tracker + spatial analytics; not branch-sales estimates | spatial navigation owner-locked; data source completeness not verified |
| Layer 3 Dealership Toolkit | standalone B2B org/team product; own brands + region; Competitive Pressure, Spatial workspace, Network Watch, snapshot PDF | key UX locked; pressure scoring and billing/seat terms unapproved |

**Additional enabling dependency (not product #9):** Vehicle Master Phase 1 governed writer; needed for future canonical mutations from #201/#203, **not** a blocker for offline audits, UX, pure PDI/CTPDI calculations or sourced spatial read models.

**New methodology review set (all proposed; approval not inferred):**
- [ENGINE_VALIDITY_AND_DEPENDENCIES.md](ENGINE_VALIDITY_AND_DEPENDENCIES.md): M0–M5 method gates for all Engines, identity and evidence safety, cross-workstream dependencies.
- [COMPETITIVE_PRESSURE_METHODOLOGY_REVIEW.md](COMPETITIVE_PRESSURE_METHODOLOGY_REVIEW.md): audited substitutability → relative offer advantage → contextual market registration → evidence-ranked assessment. No invented score.
- [PRICING_ENGINES_METHODOLOGY_REVIEW.md](PRICING_ENGINES_METHODOLOGY_REVIEW.md): explicit PDI/CTPDI unit/FX/coverage/method collision and events.
- [SPATIAL_NETWORK_METHODOLOGY_REVIEW.md](SPATIAL_NETWORK_METHODOLOGY_REVIEW.md): dealer site/brand/operator and verified network events, province registration fallacy and region masking.
- [PRESSURE_GOLDEN_CASES.proposed.json](PRESSURE_GOLDEN_CASES.proposed.json): 15 synthetic expected-outcome examples; no executable job permissions.

**Methodology choices awaiting owner verdict:** Should V1 pressure be an evidence-ranked observational radar (recommended), should reviewed substitute relationships be a first-class graph (recommended), should MSRP and verified cash-net be separate lanes (recommended), and should the 0–100 score remain null until independently calibrated (recommended)? **Do not treat this review attachment as permission to implement or to alter the existing locked five-section model-analysis UX.**

**Owner question A:** Are these functions and product boundaries faithful to the intended TDR architecture? The existence of this table does NOT imply 'approved'.

**Methodology attachment for review (not approved):** [COMPETITIVE_PRESSURE_METHODOLOGY_REVIEW.md](COMPETITIVE_PRESSURE_METHODOLOGY_REVIEW.md). Recommends demand-substitution gate → comparable documented price movement → qualified registration corroboration → evidence-ranked signal; no guessed causal sales loss or 0–100 score. Also gives a falsifiability rubric for other engines. This document does **not** mark Pass A approved.

### PASS B — Proposed *ordering*, not a 10-week deadline

- **Track I, already underway:** leave PR #200, #201 and #203 as independently scoped draft branches; complete their existing approved correction/calibration reviews first. The original TDR website UI continues according to the existing GRAFT_PLAN and owner go per row. Keep those four streams distinct.
- **Track II, can begin as review/spec while Track I proceeds:** price-history observation and event/coverage audit since BE 2564 (do not invent completeness), PDI frozen-universe/method draft, CTPDI manually reviewed crosswalk and FX contract, Dealer Master evidence model, standalone Toolkit organization+access/UX read contracts.
- **Track III, implementation only when feature gates pass:** adopted PDI methodology -> calculated versioned index; approved CTPDI matching/grain -> calculated gap; verified dealer network -> spatial derived views; governed writer -> controlled canonical edit workflows; R6 reviewed -> R7 acceptance -> owner-authorized R8 cutover.
- **First commercial Layer 3 slice:** account/org sign in, choose represented brand and authorized region, view traceable competitor movement and regional *registrations* in fixed five-section Model Analysis with honest missing-data states. CTPDI, Network Watch and unsupported future prediction must NOT be prerequisites or fabricated inputs.

**Important correction to the draft G0 plan:** C01–C04 are *not a reason to freeze every unrelated offline project*. Treat conflicts as **domain-specific activation blockers**:
- C01 blocks R6/R7/R8 execution and publication, not pure offline PR #203 gap detection.
- C02 blocks new migrations, not UI sketches or read-only source audits.
- C03 blocks billing/entitlement mutations, not Vehicle Identity or PDI pure-function fixtures.
- C04 blocks publishable CTPDI meaning, not inspecting raw CN/TH price evidence.

**Owner decision recorded 2026-10-11 — APPROVED, LIMITED TO PRODUCT ROLLOUT ORDER:** Competitive Pressure is the **first** Layer 3 product to pilot/release; **Dealer Geography follows**, then **Competitive Network Watch**. All three must advance progressively and follow through to delivery, rather than leaving Geography/Network Watch as indefinite backlog ideas. Shared Spatial workspace is still one product workspace with two local modes. **Schedule interpretation:** staged customer release **does not require sequential design or foundational engineering**: Dealer Master, spatial contracts, network event evidence and UX can progress in parallel while Competitive Pressure is built. No fixed dates, formula adoption, production activation, gate overrides or autonomous work have been approved by this statement. The order of the latter two is the working interpretation of "ไล่ตามมาเรื่อยๆ", consistent with prior V1.5/V2 design handoff, and remains open to revision if the owner directs a different order.

**Still to review for Pass B:** cross-project integration milestones, exact dependency gates, and timelines. **Still to review for Pass A:** remaining workstream functional boundaries.

### PASS C — Who controls what?

- **Owner:** product scope, methodologies, pricing/licensing, permission amendments, R6/R8, migrations, production and merge approval.
- **Claude Code:** implement approved bounded tasks on its own branch.
- **Codex:** independent QA, regression tests and specific fix requests against the same owner-approved contract; does not independently rewrite the contract.
- **Deterministic Enforcer (future):** checks task ID, exact pinned SHA, referenced contract versions, approved file scope, allowed tools, per-domain gate, tests, retry count and budget; never decides product strategy.
- **GitHub CI (future):** validates task manifest & file diff; branch protection makes required checks mandatory. Prompt-only acknowledgements never prove compliance.
- **No automatic CI/Enforcer enabled now:** `docs/portfolio/portfolio.plan.json` has `execution.enabled=false` and an empty queue.

**Owner question C:** Once A and B are approved, do we approve *designing* this governance system? This question is separate from enabling night-shift automation.

## Matters requiring evidence/explicit future decisions — not assumed approved

1. **R6 contradiction:** PR #200 contains retrieved historical production-R6 output while `WORK_STATE.md` says R6 not started. Independent read-only reconciliation required; no authorized gate change inferred.
2. **Migration v57/v58 conflict:** older GRAFT_PLAN reserves values already used by Vehicle Master; verify deployed/merged migration ledger before drafting new migrations.
3. **Consumer Website Pro/payment:** MERGE_DECISIONS v PRODUCT_ACCESS/Stripe implementation descriptions differ. Do not change live billing on a guess.
4. **CTPDI published grain:** comparable pair calculation vs model-generation-powertrain median description must be reconciled.
5. **PDI:** median cash numerator, equal-model weighting, Japan whitelist, freshness/coverage publication criteria not fully locked.
6. **Toolkit:** account scoring and 90D outlook method, commercial plan/seat count not locked; locked layout/one spatial workspace/A4-landscape PDF shape remain protected.
7. **Dealer Master:** closure/change evidence and regional privacy acceptance unresolved.
8. **PR #203:** latest correction round test/CI outcome and reviewer acceptance needed before expansion.

## Immediate G0 review record (fill only with explicit owner feedback)

| Pass | Owner verdict | Notes |
| --- | --- | --- |
| A — Product functions | **PENDING** | |
| B — Roadmap ordering / first Layer 3 slice | **PARTIALLY APPROVED** | Competitive Pressure first; Dealer Geography and Network Watch follow progressively; dependencies/dates pending |
| C — Governance roles (design only) | **PENDING** | |

**After Pass A:** record approved differences as narrow patches in this draft PR; do not mark unrelated decisions approved.  
**After Pass B:** freeze only reviewed functional/dependency contracts and prepare scoped G1 tasks; do not start or merge by implication.  
**After Pass C:** design Enforcer preflight and CI gates in a *separate* proposal; never execute the portfolio directly.
