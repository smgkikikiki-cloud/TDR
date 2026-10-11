# TDR workstream functional boundaries and integration contracts

**Status:** G0 PROPOSED; an architecture inventory, not authorization for implementation or a new data-master.

## Product architecture

```text
External inputs: Ice market panels | official OEM/TH price | official CN price/FX | dealer observations
                              |
Source-preserving ingestion + evidence/version/coverage
                              |
┌─────────────────────────────┴──────────────────────────────┐
│ Ice: registrations and market groups                       │
│ TDR Supabase Vehicle Master: canonical vehicle facts       │
│ Thai price/campaign ledgers + separate derived event history│
│ CN price evidence + reviewed CN–TH crosswalk                │
│ Dealer site/franchise/operator history                     │
└─────────────┬──────────────────────┬───────────────────────┘
              |                      |
 #200 reviewed identity links    #201 identity bootstrap (DISCOVERED only)
              |                      |
 Ice market read models       #203 retail audit -> spec enrichment
              |
    PDI | CTPDI | province/spatial + network change analytics
              |
    accountable, scoped Layer 3 interpretation
       /                                      \
 TDR website / Pro L1–2                Dealership Toolkit L3
   existing website                     distinct org/team app
```

Canonical market registration rows remain Ice/registration facts; identity links may join to a TDR model but must not manufacture registration counts at Retail Trim grain. Vehicle Master identity grain is Brand → Model → Generation → {Variant, MarketTrim}; Variant is *not* MarketTrim's structural parent. National price indicators remain national when a user changes region.

## 01 / PR #200 — Identity Resolution

- **Purpose:** reconcile Ice `model_group_id` to *existing* TDR canonical models; handle `EQUIVALENT`, `PART_OF`, `COMPOSED_OF`, atomic relationship bundles, historical redirects, explicit unmatched states.
- **Input:** package-versioned Ice group/time series; canonical model universe, aliases, known lineage, source coverage semantics, owner labels.
- **Output contract candidate:** `identity_link_set_id`, `link_type`, `ice_group_ids[]`, `canonical_model_ids[]`, `evidence_refs[]`, `source_snapshot_id`, `decision_status`, `policy_version`, review attribution; unresolved groups never disappear from aggregates.
- **Stage:** draft contract/calibration evidence only; no new resolver; 560 owner-review rows have blank verdicts (PR #200).
- **Gate:** contract adoption + calibrated labelled corpus + explicit R6 authorization are **separate** actions; do not assume PR #200 must replace the preexisting R6 matcher.

## 02 / PR #201 — Identity Bootstrap

- **Purpose:** candidate novelty resolution *after* existing-identity link and duplicate defenses. A candidate CREATE is not a live showroom model.
- **Input:** unmatched external group, reviewed identity-link set / duplicate checks, source metadata.
- **Output:** `HOLD | REVIEW | PROPOSE_CREATE_DISCOVERED`, stable external identity and reason codes; no automatic current retail assertion or enrichment.
- **Stage:** offline engine/adapter and 1,200 group shadow; 67 CREATE candidates still require adjudication.
- **Gate:** governed writer + adopted structural permissions for any production CREATE; offline analysis is independent.

## 03 / PR #203 — Autonomous Vehicle Catalog Maintainer

- **Purpose:** maintain existing current-market vehicle lineup and priority spec coverage; **not** the historical price backfill system.
- **Queue A — Retail Audit:** unknown current lineup -> source-completeness review, source-confirmed current trims and explicit conflicts.
- **Queue B — Spec Enrichment:** only eligible confirmed CURRENT marketed trims; grouped model/document research and applicable P1/P2 fields. Separate priorities with anti-starvation.
- **Output:** reason-coded model/document jobs, immutable evidence and `FACT/REVIEW/PROPOSE_ADD/PROPOSE_SOFT_RETIRE/HOLD`. Admin-locked values and null tombstones remain unfilled. No automatic enrich for HISTORICAL, retired, UNVERIFIED or DISCOVERED.
- **Stage:** draft fixture-only offline simulator; requested correction round for import/CI, gaps, completeness, conflicts, queue fairness and job identity not verified closed.
- **Gate:** no network/paid inference/production writer/cron before separately authorized stages. V3 §4 still says AI structural trim changes are proposals.

## 04 / Replacement Market Engine UI and original TDR Website / Pro

- **Purpose:** original website displays vehicle facts/comparison, market analytics and informational Upcoming Cars (Layers 1–2), including existing Pro capabilities. No personalized dealership Layer 3 is moved here.
- **Input:** Vehicle Master serving views; typed market read adapter from Ice behind frozen serving contract; current site user/entitlement rules.
- **Output:** final design-system pages, canonical trim URL/compare identity, access/coverage/locked/empty/loading states; correct market numbers.
- **Gate:** design presentation can be built before data cutover, respecting `design/GRAFT_PLAN.md`; Ice live wiring only R8 after R6 owner-reviewed crosswalk and R7 real-data acceptance. No legacy market data fallback for new UI.

## 05 / PDI — Thailand retail cash discount intensity

- **Owner-approved scope in 2026-10-08 pricing brief:** China-origin HEV/PHEV/REEV/BEV; Japan-origin ICE/HEV/BEV only for admitted models; any CURRENT Trim with official MSRP **strictly below THB 2m** admits the model, then *all* CURRENT marketed trims enter; representative MSRP is median; frozen history must remain visible; student/professional and restricted offers excluded.
- **Dependencies:** verified Thai official MSRP and current Retail Trim membership, sourced general-retail promotional cash evidence, promotion effective periods, market universe snapshots, offer/price event dedupe, historical availability/coverage.
- **Proposed (unadopted):** median eligible cash discount / median MSRP and equal-model weighting; nonconfirmed 0 cannot substitute for UNKNOWN; no invented bundle stacking.
- **Historical target:** evidence-based MSRP, discount and event chronology from 2564/2021 where actually observable. Do not assume 2021 completeness; this work is separate from #203 current-only maintenance.
- **Output:** versioned methodology, model/index result + coverage, like-for-like movement, price event trail and frozen snapshots. A price event is not a count of scrapes/reposts.

## 06 / CTPDI — China–Thailand retail price differences

- **Purpose:** explain approved *comparable* CN/TH retail pricing gap, not OEM margin or mechanically remaining headroom.
- **Input:** independently sourced CN retail price + currency/FX basis; TH canonical price; evidence; explicit manually admin-reviewed APPROVED+LOCKED CN–TH vehicle crosswalk (e.g. Yuan Plus / ATTO 3 as illustrative only).
- **Output:** pair ID/version, market/spec/price-basis comparability, FX as-of and gap convention, source references, null when no comparable pair. Future automatch optional, not a V1 blocker.
- **Unresolved methodology collision:** the pricing brief uses reviewed comparable pairs and price-basis-specific ratios; an earlier Toolkit handoff describes model×generation×powertrain, per-country median current trim MSRP. Do not silently implement either interpretation as an adopted production standard. Resolve grain and headline convention with owner before scoring.

## 07 / Dealer Geography / spatial domain

- **Three *data capabilities*:** dealer site/brand franchise/operator master and history; verified network-change event evidence; spatial/market queries. These are **not three unrelated products or separate global navigation destinations**.
- **Owner-locked UX:** **one Spatial workspace**, 60–70% map canvas on desktop, one thematic layer, one collapsible inspector; Dealer Geography and Competitive Network Watch are **local modes** sharing master/map. Market Watch has Pricing/Network Events/Upcoming Cars tabs; Upcoming threats are timeline-first, not arbitrary map pins.
- **Inputs:** owner/site/operator/franchise effective periods with evidence; geocoded site and comparable time bases; Ice registrations province/model with reviewed crosswalk as appropriate.
- **Interpretation:** provincial registrations are not dealer sales or purchase locality; do not compute branch performance by dividing province registrations by site count. Source absence cannot declare dealer closed; distinguish site operation vs franchise entitlement vs operator changes. Catchments reflect verified route/accessibility, not proven trade flow.
- **Region security:** Enterprise users select active region independently; in-region provinces may be explored. Nearby out-of-region dealer site directory attributes may appear, but NO out-of-region registration totals, derived trends or shares in map, API, report or tooltips.
- **Phasing:** V1 design contracts, V1.5 verified geography, V2 network-change monitoring as data becomes credible. Final visual pixels and network impact formulas are NOT locked.

## 08 / Layer 3 standalone Dealership Toolkit

- **Owner-locked boundary:** organization-billed separate B2B app; same verified auth identity may be reused but separate product entitlement from Website Pro; named member/team, only represented canonical brand IDs and primary region at setup, with verified branch selection permitted. No customer-entered stock, deals, CRM, orders, dealer sales reports, custom scoring weights or predictive inputs.
- **Flagship V1:** Competitive Pressure; owner-locked Model Analysis V1 order: (1) Pressure Overview, (2) Competitive Landscape, (3) Pressure Investigation, (4) Regional Market Context, (5) Events & Outlook.
- **PDF owner lock:** A4 landscape, one-page Executive Brief and five-page Full Analysis, no blank cover, assembled from immutable analytical snapshot (not UI screenshot).
- **UX:** organization/team roles, server-side ACL on views/exports; user-specific active region, source/freshness/coverage, evidence drill-through, historical 3M versus future 90D distinguished. Pressure scoring/formula and confidence thresholds NOT locked; do not invent 90D forecasts.
- **Commercial:** THB 5,900/month, THB 59,000/year and 5-seat limit in prior handoff are *proposals only*. Website Pro entitlements and prices unchanged by Toolkit; applicable website billing/design owner decisions still apply.

## X / Vehicle Master Phase 1 governed writer — enabling capability, not a ninth sellable product

- **Input:** properly validated immutable observations and approved structural proposals.
- **Output:** reconcile → authority-safe apply or propose, revision/change log/revert, admin locks/tombstones.
- **Stage:** not implemented on main (Phase 0 only). It does **not** block read-only pricing research, pure PDI arithmetic, geography prototypes, or UI design; it DOES block PR201 production CREATE and catalog fact/trim production mutation.
- **Conflict:** autonomous structural trim ADD/SOFT-DISCONTINUE is proposed by PR203; V3 §4 still requires proposals. Only a separately adopted permission amendment may change that.

## Cross-domain data envelope (proposed; validate per interface)

For any derived scored data, carry when applicable: `source_snapshot_id`, `canonical_model_id`, `ice_model_group_id`, `identity_link_set_version`, `observation/effective timestamps`, `geographic_scope`, `retail_scope`, `source_refs`, `coverage`, `methodology_version`, `universe_version`, and distinct `UNKNOWN/NOT_APPLICABLE/VERIFIED_ZERO/CONFLICT` states. *Absence from a source is not evidence of zero or termination.*

## Delivery dependencies (no invented 10-week promises)

1. **G0 Portfolio contracts:** reconcile source precedence and conflicts below. Does not authorize production.
2. **G1 Offline engine reliability:** correct #203 CI/import/fairness/identity; calibrate #200/#201 where labels exist; define typed UI adapters. Each PR remains draft until its independent gate passes.
3. **G2 Evidence foundations:** Price Event/Frozen history including sparse 2021 records; initial dealer network source ledger; manually approved CN–TH pair tests; writer policy/observation contracts; original UI final-state layouts can continue.
4. **G3 Measurable engines:** PDI based on *approved* methodology; CTPDI based on locked comparable pairs; spatial verified joins; separate Ice R6→R7→R8 sequence only on authorized gates.
5. **G4 V1 user slice:** login into company team → choose own brand / authorized region → view sourced model/competitor pricing and registrations with evidence → inspect Model Analysis five sections; reporting and tenant isolation verified. CTPDI/Network Watch optional extensions for this slice, not fabricated prerequisites.
6. **G5 Operations:** reliable nightly queue, idempotency, observed-event monitoring, auditability, source freshness and cost control, owner authorization for each class of action.

**G0's gate is not fulfilled merely by this document being written.** See [G0_RECONCILIATION.md](G0_RECONCILIATION.md).
