# CP V1 — Repository Readiness Audit + first deliverable work packets

**Observed 2026-10-11.** `main` code review only via GitHub (no Supabase row queries; no source completeness claim; no change to main). **Status: proposed owner-review plan, NOT execution approval.**

## 1. Stop writing abstract roadmaps; this is the first product slice

**Outcome sought:** A dealership representing R opens a model-level analysis. The system shows an evidence-cited adverse competitor price move and qualified registration context, with a stable selected reference, and says **NOT_SCORABLE** where proof is missing. No paid inference, no scoring formula, no prediction, no fabricated regional sales.

**Minimum working walk-through (synthetic until authorized real-data audit):**
1. Viewer belongs to org with canonical brand(s); server checks user/org/license/region.
2. Select reference Model R from org's represented brand, rival C from candidate + reviewed substitute graph; show review status.
3. Engine reads verified MSRP and *separately* verified general-cash offers on same comparable basis, source scopes/dates. If the evidence is incomplete, show price action and missingness separately rather than invent model-level price advantage.
4. Attach Ice registration market context **only** through reviewed identity, compatible periods/class/denominator, and authorized region; many-to-many ambiguity stays unallocated.
5. Engine emits `OBSERVED_ADVERSE_MOVE/WATCH/INSUFFICIENT_EVIDENCE/DATA_CONFLICT` and evidence refs, never causal sales loss.
6. UI renders the five locked Model Analysis sections, with numerical pressure score **null** before approved calibration; report snapshots are scoped and immutable when later approved.

**First customer-visible vertical slice does NOT require:** CTPDI headline, national PDI index publication, Dealer Network Watch, modeled sales capture, predictive 90D, automatic vehicle model creation. These are parallel capabilities, not blockers.

## Live source coverage update: CP-00 partial audit performed

[CP00_SOURCE_COVERAGE_AUDIT_2026-10-11.md](CP00_SOURCE_COVERAGE_AUDIT_2026-10-11.md) measured: 273/1,431 CURRENT Trims with any LIST_PRICE in ledger, 74/318 CURRENT Models with all current trims represented (not time/retail vetted), 320 LIST_PRICE rows all observed Sep 2026, and 48 promotions with no normalized cash amount or trim scope. Ice model trends cover 69 months but 0 APPROVED group→model links. **CP-00 now has actual SELECT-only evidence but is NOT complete.** 

**Delivery revision (proposed, not owner-approved):** continue CP-01 substitution fixtures and typed org/UX contracts in parallel with CP-00a source classification, but hold historical price-change headlines, PDI, 3M/12M pressure score time-series, CN price gap and dealer outcomes until their separate domain gates are satisfied. A single verified current-position snapshot may be useful, but it is not a pressure-movement series.

## 2. Actual current-main code availability

| File / path | Verified existing behavior | Reuse decision / missing contract |
| --- | --- | --- |
| `lib/canonical-data.ts` | Master-backed `getCanonicalModels`, model/trim status and current MSRP/campaign projection fields, source references. | **REUSE** for stable identity and current models; not an index-ready historical panel. |
| `lib/market-price-state.ts` | `resolveListPriceOn` uses `LIST_PRICE`, effective/observed dates, returns null on conflicting amount candidates; `resolveModelPriceBand` avoids unknown listed trims. | **REUSE pure logic by contract only** after parity tests. Historical index must NOT rely on its 1,000-row query cap. |
| `lib/market-price-state.ts` lines 115–129 | explicitly caps trims/generations/price rows at 1000 to preserve old serving behavior. | **P0 DATA COVERAGE RISK:** independently paginated, audit-ready read model required; no 'all history' claim using this route. |
| `lib/compare-canonical-data.ts` | current trim picker and compare projections, separated from bulk scan. | **REUSE identity and statuses**, not a verified general-cash normalization method. |
| `docs/vehicle-db/VEHICLE_DB_V3.md` §3/§6–7 | Price Ledger/Promotions distinct, `UNKNOWN != NO`, authority ordering, future effective dates, current AI structural proposals only. | **MANDATORY OWNER-GOVERNED**. No new write route. |
| `lib/ice-market-engine.ts` | pure Ice market slicing; model grain keyed to Ice group, optional canonical model ID for approved/AUTO mappings, unmapped group counts preserved. | **REUSE as reference** but never sum mapped Model IDs when 1:N; a primary linked Model for display is NOT evidence for unit allocation. |
| `lib/ice-market-data.ts` | explicit service-role-only `ice_*` I/O; market slices and report read logic exist; module comments state not yet wired to live pages at M4. | **REUSE read-adapter structure** on permitted gates; don't bypass R6/R7/R8 / org entitlement. |
| `docs/market-track/ROADMAP.md` + `docs/WORK_STATE.md` | R6 gate documented locked, R5 done; PR #200 recovery disagrees with recorded run state. | **BLOCK** new production crosswalk/cutover; factual read-only reconciliation first. |
| `lib/registration-analytics.ts` | existing registration view/access code; it is part of older market track and not interchangeable with Ice M4 source. | **DO NOT use** as a fallback for new Layer 3 if Ice is not authorized. |
| `lib/compare-winners.ts` | evidence-safe same-qualifier spec comparability highlighting. | **REFERENCE ONLY**; higher power or spec-field winner doesn't prove customer substitution. |
| `docs/portfolio/*` | proposed workstream contracts and synthetic pressure cases on draft PR #204. | **NOT adopted**. No runtime authority or approved commercial formula. |

**Not verified here:** real price rows/term completeness, 2021 historical campaign evidence, 2026 live source freshness, source license, current Supabase project/deployment mapping, real Ice R6 approvals, actual observed model-pair substitutes, organization auth implementation and live cost. These must be recorded as unknown rather than guessed.

## 3. Sequence of first six precise engineering deliverables (not a fixed calendar)

### CP-00 — Read-only source/data coverage report (FIRST)

**Owner:** engineering audit + independent QA; **allowed only after narrow owner task authorization**.  
**Output:** `PRICE_COVERAGE_BY_YEAR_MONTH.csv`, `OFFER_STATUS_CLASSIFICATION_AUDIT.md`, `ICE_MODEL_LINK_COVERAGE.md`, `SOURCE_READINESS.json`, each with anonymized aggregate coverage only. Assess 2021→present actual MSRP and promo evidence by time/source/scope, full-trim count, date semantics, and ledger pagination. Evaluate partner source rights. Ice mapping review strictly SELECT-only; no R6 execution.

**Pass:** can separate `KNOWN_PRICE / VERIFIED_ZERO_OFFER / UNKNOWN / EXPIRED / CONFLICT / UNAVAILABLE`; complete counts or explicit capped/unavailable status; no leaked customer/vendor credentials; re-run reproducible; no writes/paid calls.

### CP-01 — Pure substitution candidate/approval contract (OFFLINE)

No AI guess in production. Design directed reference Model→competitor candidate graph, with reviewed `CONFIRMED/CANDIDATE/UNKNOWN/NOT_COMPARABLE`, use-case/generation/version, evidence and review attribution. Initial candidates from model facts + MSRP bands (rules proposed); "same segment" only candidate. Hard negatives: trim differences, incomparable buyers/use cases, misstatus/historical/upcoming, name collisions. No auto approval and no guessed elasticity.

**Pass:** 10+ synthetic expert-review cases, symmetric/asymmetric pairs explicit, deterministic candidate replay and audit.

### CP-02 — Price/event validity and relative-price engine (OFFLINE)

Two independent lanes (MSRP, eligible verified general-cash net), strict same basis/scope/effective period and stable matched model/trim cohort. Dedup price actions; prevent PDI double count, unknown zero filling, stale campaign carrying and trim-composition false deltas. PDI headline can remain unapproved.

**Pass:** event cases `CP-01,CP-03,CP-06,CP-09,CP-10,CP-14` from proposed Golden Cases; independent arithmetic oracle and period/coverage metadata. No DB mutation.

### CP-03 — Registration corroboration adapter (OFFLINE -> read-only SHADOW after Ice gates)

Distinguish Ice group from TDR Model; handle `PART_OF/COMPOSED_OF`; class/window/universe, missing periods and region entitlement. A primary display link may never become a 1:N unit distributor. Registration shifts are evidence, never causal substitution claim.

**Pass:** `CP-05,CP-07,CP-08`, no duplicate counts, unknown mapping visible, explicit same-panel source; out-of-region negative tests.

### CP-04 — Evidence-ranked deterministic assessment (OFFLINE)

Produce enum-based pressure assessment with observation classification, driving verified price action, corroborating market context, source refs, coverage and reason codes; `pressureScore=null` unless an independent owner-approved calibration stage later. LLM, if any, is limited to wording from validated structured facts. No claimed certain price-cut predictions, probabilities or lost units.

**Pass:** all 15 pressure Golden Cases reviewed and executable (only if owner approves those expectations), stable ranking replay, adversarial unknown/conflict inputs, at least one independent human source review per sample for later shadow.

### CP-05 — Toolkit first slice / product (SEPARATE GO)

Server-scoped org account, represented brand gallery, competitor selection and five-section Model Analysis; source evidence drilldown + truthful empty states. PDF one-page/5-page A4 landscape from immutable snapshots if its entitlement/storage gate passes. Keep Website Pro billing/rights untouched; no client-only access control. Data may be labelled synthetic in internal preview, not live.

**Pass:** unauthorized cross-org/region request rejected on server; model reference pinned; historical/forward windows distinct; no misleading score or CTPDI; reviewed pilot case replayed with actual licensed source evidence before customer launch.

## 4. Start order is not the launch order

- **Now:** source coverage inspection; current PR #200/#201/#203 progress and existing website graft can continue under their gates. Owner reviews Substitution, Price basis and score publication philosophy.
- **Then (when reviewed):** CP-01 through CP-04 as bounded offline modules; price-history/offer normalization work feeds PDI separately; CTPDI manual crosswalk and Dealer Master source inventory run parallel to Pressure V1.
- **Only after source, method, access and owner gates:** CP-05 staging pilot. Geography V1.5 and Network Watch V2 follow commercially, although location/events evidence gathering starts in parallel.
- **Night Shift Enforcer later:** task packet validator/CI built only after portfolio approval, contract precedence reconciled and one bounded Claude↔Codex trial accepted.

## 5. Four product-method choices needing explicit owner acceptance (NOT approval now)

1. Competitive Pressure is an **observational relative-position radar**, not a causal unit-loss estimator.
2. A **reviewed Substitution Graph** is a real data contract distinct from PR200 Ice Identity and CN–TH CTPDI Crosswalk.
3. Price evidence has **separate MSRP and source-verified general-cash net lanes**. Don't feed inferred promo price to headline.
4. Before calibration, numerical 0–100 Pressure Score is **null / not published** (the locked UI keeps an honest pending state).

If the owner approves these four *design* choices, request a **separate bounded CP-00 read-only task go**. This PR only provides the reviewable plan and no task permission.
