# Graft Plan — evidence-reconciled UI/UX overhaul

**Owner design decision:** 2026-10-01, this Graft is the full Website/Website Pro overhaul, not a reskin.

**Evidence refresh:** 2026-10-14 against main SHA c2715cbee494ae076b2582ef99f2bbc590b5dd99; PR #173/#220/#246 heads are in the Phase A baseline.
**Roadmap authority:** approved TDR Master Roadmap v1.0. portfolio.plan.json remains execution.enabled=false. This is an implementation handoff only. It grants no task, merge, migration, deployment, billing, Ice gate or Production permission.

## 0. Scope and invariants

This Graft covers the original consumer/member website, Website Pro and Layer 1–2 catalog and analysis surfaces. It does not include the standalone Layer 3 Dealership Toolkit. Dealer prioritization, CRM, inventory, leads, branch sales and organization reporting remain in that separate product.

1. **Full overhaul:** Market/Intelligence, Compare, Analysis and Home integrations are part of this UX cycle.
2. **UI and data release are separate:** build final layouts and states against versioned typed adapters. A blocked source can gate integration/release, not unrelated UI design.
3. **No legacy fallback in new Ice UI:** new Market/Intelligence views must not import legacy registration output or switch to it on Ice errors. Keep current main route behavior until separately approved cutover.
4. **Authority:** Vehicle Master owns canonical identity and classification. Its segment and body_type override Ice; preserve Ice values only as raw source evidence. Ice registrations and class-scoped links are separate market evidence.
5. **Truthful states:** loading, locked, empty, partial/unmapped and unavailable/error are distinct. Never use mockup values as data, treat UNKNOWN as zero/no, hide coverage, or put protected data in the DOM behind a visual blur.
6. **Compare:** preserve canonical trim identity, ?trims= and ?models= deep links, server quota and evidence-safe winner logic in lib/compare-winners.ts. Redesign the whole presentation; do not retain old layout only for compatibility.
7. **Canonical boundary:** read Vehicle Master through its accepted current_* serving contract. Pages and APIs do not write those views. automotive/vehicle_master is engine/tooling, not canonical file data.
8. **Price Fetcher is separate:** it collects OEM price/spec sources; it is not an Ice package reader/importer.
9. **Billing and owner authority — G0-C03 OPEN:** Current `main` implements Stripe in `lib/plans.ts`/`lib/billing.ts` and the current code catalog lists ฿1,290 monthly / ฿2,970 quarterly / ฿9,480 annually. However `docs/MERGE_DECISIONS.md` records an owner-approved Omise + ฿1,099/month / ฿11,490/year + revised 30-day-OTP Freemium model. `docs/portfolio/G0_RECONCILIATION.md` C03 explicitly identifies this as an unresolved decision-vs-implementation conflict. **Neither set is silently revoked or activated by this UI plan.** Provider-neutral layout/components can proceed; price/provider/checkout/trial/entitlement presentation is owner-gated pending a separately recorded superseding decision, compatibility and existing-subscriber review. This UI plan changes no payment behavior.
10. **Gates:** R6→R7→R8 and C01/C02 remain domain/governance evidence gates. Roadmap v1.0 does not authorize their execution. UI completion never implies Ice cutover, schema deployment or Production readiness.

## 1. Current state and authority

The exact main tree, PR inventory and subsystem states are in [PHASE_A_BASELINE.md](../docs/ui-overhaul/PHASE_A_BASELINE.md). The complete route map is in [PAGE_DATA_CONTRACT_MATRIX.md](../docs/ui-overhaul/PAGE_DATA_CONTRACT_MATRIX.md); contradictions are in [ARCHITECTURE_CONTRADICTIONS.md](../docs/ui-overhaul/ARCHITECTURE_CONTRADICTIONS.md).

- Main /market uses getPublicMarket() from lib/public-market.ts; /member/market and /api/report/market use the legacy member market path. PR #246 adds Ice scoped-reader/crosswalk and report changes, but is Draft and unmerged.
- Main Home uses catalog, getHomeMarket, published research and shared plans. Draft #173 has temporary market/Analysis states; it merges last, after final data contracts are wired.
- Main Compare has a canonical picker, quota-accounted result and evidence-safe winner policy. Replace only the presentation.
- Main /research has published preview, protected full read, quota and Admin authoring. Map P14/P15 to this runtime before considering a second table or storage pipeline.
- Main /upcoming redirects to /models. Draft #220 supplies a static R0 contract/preview, not a live table, writer, Admin or route. Its migration names are stale and reserve no version.
- Three Pro commitment plans and Stripe are current **implementation facts**, not a resolution of G0-C03 against the owner-approved Omise / revised-price / Freemium decisions; live Price IDs/configuration are unverified.
- Main has token/design migration for Shell, shared components, Models, Brands and Search. design/migrated.json is not a complete page acceptance list.

## 2. Work order and Graft rows 0–15

One future implementation task per approved bounded slice, unless the owner explicitly combines them. Independent UI lanes can proceed in parallel. This document does not dispatch future work.

| Row | Page/workstream | Disposition | Readiness/dependency |
|---:|---|---|---|
| 0 | Main check repair | Reverify current main; fix only observed failure. | READY_TO_REVERIFY. |
| 1 | Design foundation | Keep existing tokens/check infrastructure. | Maintain shared checks. |
| 2 | Tokens/fonts | Adapt only proven gaps. | Owner go; check:design and visual proof. |
| 3 | Shell/navigation | Adapt shell and route families. | Verify redirect target before changing a route. |
| 4 | Shared components | Keep/adapt existing components. | Add accessibility and screen-size evidence. |
| 5 | Home P01 (#173) | Adapt; Draft, merges last. | Final Market/Analysis contracts, no placeholders, shared body/plan source. |
| 6 | Models P02–P04 | Keep data engine; adapt remaining UI. | Canonical serving contract; no inferred facts. |
| 7 | Brands/Search P05–P07 | Keep data engine; adapt remaining UI. | Canonical reads and stable URLs. |
| 8 | Compare P08 | Replace full presentation; keep compare engine/policy. | tdr.compare-ui.v1; quota/winner/URL tests. |
| 9 | Pricing/Auth P18–P21 | Adapt provider-neutral UI to current runtime where safe; do not decide commercial policy. | G0-C03 owner decision before final plan prices, provider, checkout and trial/Free copy; preserve live access and billing until separately authorized. |
| 10 | Static P22–P26 | Keep active news/companies; add only approved content/routes. | Owner copy, contact recipient, legal review. |
| 11 | Intelligence P09–P12 | Replace UI against typed Ice adapter; hold live wiring. | R6/R7/R8, release/coverage evidence, owner cutover go. |
| 12 | Upcoming P16–P17/Admin | Adapt R0 contract; no current full routes/writer. | Source/rights/status/history decisions and authorized migration allocation. |
| 13 | Analysis P14–P15/Home cards | Adapt current Research pipeline first. | Verify shape/privacy before new schema. |
| 14 | Omise/provider PR | Do not implement an independent provider migration under UI Graft; track owner-approved Omise proposal as unresolved G0-C03, not cancelled. | Provider/pricing/subscriber migration needs a separately authorized billing task; no provider change in UI PR. |
| 15 | Ice panels 1–4/Info/CSV | Separate import/panel/export scope from #246. | Owner schema/rights/access/export contract and independent Ice acceptance. |

Exact paths, denylist, tests and exit criteria are in [PR_EXECUTION_MATRIX.md](../docs/ui-overhaul/PR_EXECUTION_MATRIX.md). Page/API contracts are in [PAGE_DATA_CONTRACT_MATRIX.md](../docs/ui-overhaul/PAGE_DATA_CONTRACT_MATRIX.md).

## 3. Merge and release criteria

Every future UI PR must pass npm run check and npm run check:design; contract fixtures and privacy/quota/security tests; backward-compatible URL behavior; explicit unsupported-filter handling; and 8 screenshots at 1440/1024/834/390 × light/dark for each changed page. Include keyboard, contrast and mobile-overflow review.

Independent review is required before merge. The PR description records UI_COMPLETE, CONTRACT_READY, INTEGRATED, PREVIEW_QA or PRODUCTION_RELEASED separately. Production requires the separate domain/owner gate and real source/config verification. A Draft PR, static preview, repository migration or green typecheck does not imply deployment or production activation.

## 4. Phase A review

Evidence and acceptance are in [PHASE_A_ACCEPTANCE.md](../docs/ui-overhaul/PHASE_A_ACCEPTANCE.md). Reviewer and owner decisions are separate. Until then this plan is a handoff; all roadmap, billing, data and release gates remain intact.
