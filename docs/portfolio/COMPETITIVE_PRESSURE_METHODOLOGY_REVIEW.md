# Competitive Pressure Engine — methodology review v0.1 (OWNER REVIEW; NOT APPROVED)

**Date:** 2026-10-11  
**Status:** PROPOSED METHODOLOGY / NO RUNTIME OR PRODUCT APPROVAL.  
**Evidence boundary:** derived from 2026-10-08 PDI×CTPDI pricing brief, 2026-10-10 owner-locked Toolkit Spatial/UX handoff, repo `docs/vehicle-db/VEHICLE_DB_V3.md`, `docs/vehicle-db/SERVING_CONTRACT.md` and `lib/ice-market-engine.ts`. Neither a calibrated 0–100 pressure score nor an accepted product pilot is claimed.

## 0. The question and the unit of analysis

**Question:** For a dealership organization representing brand B and reference **canonical Model R**, which **credible substitute Models C** have recently improved their competitive position relative to R, by what observed changes, with what corroborating evidence, and which cases deserve investigation?

Three different objects must NEVER be equated:
1. **Market facts**: verified MSRP/offer events, registration counts, current vehicle spec/lineup.
2. **Pressure signals**: directional, evidence-supported observations **conditional on competitor substitutability** and a defined scope/time window.
3. **Causal displacement and prediction**: how many buyers R lost to C, or whether R must cut its price. This is **NOT identifiable** from dealer-independent price and registration aggregates without additional validated evidence/modeling. No V1 such claim.

This follows standard demand-substitution reasoning: competitors are close because customers plausibly switch between them, not merely because both have the same segment label. External conceptual background:
- European Commission 2024 Market Definition Notice: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A52024XC01645 (demand-side substitution; characteristics, price, intended use; observed switching stronger evidence).
- US DOJ/FTC 2023 Merger Guidelines competitive tools: https://www.justice.gov/atr/merger-guidelines/tools/evaluating-competition (customer switching/diversion, strategy and prior events as differentiated evidence).
Those sources are **frameworks, not evidence that a particular Thai vehicle pair substitutes or that TDR has measured diversion**.

## 1. Four logically separate calculations

### 1A. Substitution Graph — eligibility and directness, not a numerical loss estimate

For each (reference Model R, candidate rival Model C, market scope, model-generation/version), produce:
- `CONFIRMED_COMPARABLE`: owner/analyst-backed, evidence-traceable substitute relationship; meaningful cohort and intended use.
- `CANDIDATE_COMPARABLE`: rule-generated candidate for review (body, seats, powertrain constraints, positioning, overlapping observed price offers, generation).
- `NOT_COMPARABLE`: known mismatch for defined use case; exclude as a direct rival but possible broad benchmark.
- `UNKNOWN`: insufficient evidence; no claimed pressure ranking.
- A separate `DIRECT/ADJACENT/BENCHMARK` *relation* only if policy adopted, with an evidence/reviewer basis. Adjacency is not automatically a direct rival.

Inputs: canonical vehicle identifiers, generation & market status, real attributes and qualified MSRP / relevant offer position; optional verified observed switching research. **Same segment is only candidate discovery**. Price overlap is not a causally proven demand elasticity. User's represented brands define reference Models, NOT an artificially closed universe of rivals. Chinese and incumbent competitor vehicles are eligible when substitutable.

No automatically invented cross-price elasticity or diversion ratio. Cross-price elasticity would require historical price/volume panel with relevant confounders and a validated identification design; do not compute it from two periods or two model share changes.

### 1B. Relative Pricing Movement — observable competitive change

Keep MSRP and unconditional/general-access cash offer prices as **distinct series**, same effective date/territory/validity/price basis. For two comparable, verified **model-level representative prices** `p_r(t)` and `p_c(t)` on the **same price basis**, define:

```text
ADVANTAGE_C_VS_R(t) = p_r(t) - p_c(t)
DELTA_ADVANTAGE(t0,t1) = ADVANTAGE(t1) - ADVANTAGE(t0)
```

Positive `ADVANTAGE` means C's representative verified price is lower than R's; positive `DELTA_ADVANTAGE` means C gained **relative price advantage**, not that R lost customers. Use a **stable, explicitly versioned comparable cohort**, not shifting MSRP medians across changed trim membership. A model-level price statistic is only valid if its retail set, scope and offer completeness meet the adopted method; otherwise publish the **actual affected trim-level price event as supporting evidence** but the model price advantage is `NOT_SCORABLE`.

**Critical:** do not treat unknown discount as 0, apply local/dealer special offers to the national index, stack unverified promotions, mix tax/lease/cash finance conditions, carry expired campaigns, or use ECO Sticker price as MSRP. Permanent MSRP cuts and cash promotion changes have separate event types. Account region does NOT magically regionalize national pricing.

**Illustrative synthetic example, no Thai-market claim:** R verified representative price THB 1.15m unchanged; C 1.22m → 1.07m under same current comparable basis. C relative price advantage changes from -70k to +80k, i.e. +150k. This is a **verified price-position movement if the input really exists**, not “R will lose N sales” or “C exerts 80/100 pressure”.

**Double-count guard:** if `p` is net of cash promotions, a rise in PDI already reflected in `p` cannot be counted as another independent adverse price movement. PDI is an *explanation/market reference*, not a bonus multiplier.

### 1C. Registration-relative movement — corroborating context, not proof of substitution

For a clearly defined comparable candidate universe U, registration type/class and period window, source and geography:
```text
share_x(U,scope,t) = registered_units_x(scope,t) / registered_units_U(scope,t)
delta_share_x = share_x(t1) - share_x(t0)  # percentage points
```

Only if same `U`, same registration class (RY1 etc), same complete months, a **single coherent** Ice panel/view and approved Ice→TDR identity-link set. Use rolling 3-month observations vs comparable earlier window and/or same months in prior year as **separate comparisons**, not interchanged. Apply period completeness and minimum denominator policies **after** real-source audit, not invented thresholds.

- A rival registering more while R registers fewer **corroborates rival momentum**, but cannot prove buyers switched R→C, cannot establish individual dealership sales, and is sensitive to production/import/seasonality, model launches, supply and data quality.
- If the model maps to `PART_OF` / `COMPOSED_OF` relationships and Ice grain cannot uniquely allocate units: report the coherent Ice group/bundle, preserve unmapped counts and **refuse to manufacture individual Model units**. Segments/body are canonical TDR dimensions only through defensible joins.
- Province is **registration location**, not purchasing/dealer location. For regional context, use only currently authorized region/provinces, distinct from national pricing inputs.
- Missing source month `UNKNOWN` is not 0; do not combine '`*`' aggregate registration with constituent classes; no unapproved extrapolated share.

### 1D. Event/strategic context — never a hidden score component

- **Observed price change:** may be prioritized for investigation on its own if pair/substitute context is confirmed.
- **CTPDI** CN–TH approved matched gap: possible *strategic incentive/price-room context*, not proof of margin, future Thai discount or 90-day cut; do not mechanically add it to price-move severity. Crosswalk grain/convention still under owner review.
- **Upcoming Cars:** unlaunched models may be potential substitute threats in the **forward Events & Outlook** only, never realized current pressure.
- **Dealer Network/Geography:** verified physical franchise/site events inform **local exposure and Network Watch**. Do not inject site counts or catchment into national 0–100 pressure without a separately validated methodology. A locator disappearance is not a verified closure.
- **OEM production obligations:** only sourced incentive/context; no implied local inventory or saleable stock or required retail cut.

## 2. An honest output BEFORE a calibrated score

**Recommendation for V1 pilot:** start with a deterministic **Pressure Evidence Matrix** / ranked investigation queue with clearly labelled observed signals and coverage, then calibrate a dimensionless 0–100 score on a separately owner-reviewed historical event corpus. Keep the locked UI's score surface with **UNAVAILABLE / Pending model computation** when not validated; don't invent an arbitrary number to fill it.

A model-rival assessment can have **independent dimensions**:
- `substitution_basis` = confirmed / candidate / not comparable / unknown
- `relative_price_position` = observed advantage / deterioration / no material observed change / not scorable
- `registration_context` = supports / opposes / mixed / insufficient / not mapped
- `source_state` = verified / partial / conflict / stale / unavailable
- `review_priority` = prioritization from explicit *verified* event magnitude, timeliness and affected approved substitute relation; no uncalibrated loss probability
- `interpretation` = one short claim + separately listed observed drivers and limitations
- `action_prompt` = inspect pricing/position and consider response; **never an assertion of causality or mandatory price cut**

**Ranking (proposal):** sort deterministically by (1) eligible confirmed substitutes with new verified adverse competitive actions, (2) those with corroborating same-cohort registration divergence, (3) older/current unfavorable price positions, (4) watch-only strategic signals. Within classes, recency and absolute comparable observed gap change can break ties. Candidate substitutes display separately until reviewed. No ad hoc weights, fabricated confidence, or pseudo-statistical labels such as `HIGH 87/100`.

`NO_MATERIAL_CHANGE` may only mean no **verified material changes within monitored source scope/window**, not a proven absence of market change. `INSUFFICIENT_EVIDENCE` is separate. Contradictory data should not get auto-smoothed away.

Later, if an owner requires 0–100 score and 3-month point delta, formalize an invariant, stable time/coverage-aware, monotonic index and test it against an independent owner-annotated event set. Prove calibration by out-of-sample ranking precision, temporal consistency, missingness stress tests and field-history replay; score unit is **relative index points**, not probability, THB or sales. A pairwise index cannot simply sum into Model 0–100 or claim contributions add to 100%. Changes in monitored competitor set/universe require separately versioned baselines and historic recalculation policy.

## 3. Suggested minimal read-only API contract (PROPOSED, not repo routes)

```ts
type PressureAssessment = {
  assessmentId: string;
  referenceModelId: string;
  competitorModelId: string;
  organizationId: string;  // authorization context, not master data ownership
  asOf: string;
  retrospectiveWindow: { from: string; to: string };
  marketScope: { country: "TH"; registrationClass: string; regionCode?: string };
  comparisonSetVersion: string;
  methodologyVersion: string;
  identityLinkSetVersion: string | null;
  substituteRelation: "CONFIRMED" | "CANDIDATE" | "NOT_COMPARABLE" | "UNKNOWN";
  price: {
    sameBasisComparable: boolean;
    observedAdvantageThb: number | null;
    deltaAdvantageThb: number | null;
    eventIds: string[];
    scope: "NATIONAL" | "REGION" | "DEALER";
  };
  registrations: {
    referenceCount: number | null;
    competitorCount: number | null;
    shareDeltaPpReference: number | null;
    shareDeltaPpCompetitor: number | null;
    sourcePeriod: string | null;
    status: "SUPPORTED" | "OPPOSED" | "MIXED" | "INSUFFICIENT" | "UNMAPPED";
  };
  sourceRefs: string[];
  coverage: Record<string, number | string | null>;
  status: "OBSERVED_ADVERSE_MOVE" | "WATCH" | "NO_VERIFIED_MATERIAL_CHANGE" | "INSUFFICIENT_EVIDENCE" | "DATA_CONFLICT";
  pressureScore: number | null;  // ALWAYS null before separate approved calibration
  notes: string[];
};
```

Implementation note: separate **market/evidence computation** from **tenant access resolution**. National price and PDI/CTPDI are the same underlying indicators regardless of member region. Only the authorized registration query changes on region switch. A reference Model must stay pinned when selected rival changes. Reports use an immutable server-authorized analytic snapshot, not a browser-rendered screenshot.

## 4. Illustrative event assessment (synthetic, NOT a market claim)

| Observation | Synthetic value | Engine may conclude | Engine may NOT conclude |
|---|---|---|---|
| R and C are confirmed substitutes | reviewed link | eligible for investigation | measured switching rate |
| C reduced verified general-cash price by THB 150k while R unchanged | matched effective dates/scope | C's **relative** verified cash-price advantage grew | R must cut THB 150k |
| C's share of a comparable registration basket increased and R's fell | complete, same-class periods and joined identities | registration momentum corroborates a shift in observed relative market presence | 150k price cut **caused** that registration pattern |
| CTPDI China–TH price gap is large | approved CN pair / source / FX | strategic cross-market context | available dealer margin or next-90-day price cut |
| Nearby competitor site opens | verified event | greater observed physical rival presence in branch area | measured branch sales lost |

Customer-facing narrative *template*: “The verified nationwide general-cash offer for Model C became cheaper relative to Model R during [window]. Both models are reviewed substitutes; registrations over [comparable period] shifted in opposite directions, but do not establish purchase switching or causation. Inspect C's offer conditions and R's current commercial position.” Do not use this template when sources or comparisons are not verified.

## 5. Falsification / regression tests (minimum for first implementation)

1. Same segment and similar MSRP alone -> **CANDIDATE**, not a confirmed substitute or realized loss.
2. Wrong generation / discovered / unlaunched -> not eligible as realized pressure.
3. Reference stays pinned when competitor changes, even across page and report.
4. Only explicit verified official offers, not student/professional or finance-only, enter comparable general-cash position.
5. UNKNOWN/EXPIRED promo != zero/no discount, and no amount is carried forward blindly.
6. MSRP and cash offer changes are distinct events; one promotion visible in effective price and PDI must not be counted twice.
7. Changing trim membership doesn't make the model gain a fake relative price advantage from median-composition effects; cohort/version required.
8. 1:many / many:many Ice crosswalk does NOT duplicate registrations on multiple model IDs.
9. `*` aggregate + RY1/RY3 totals not mixed; missing months never zero-filled without a formal coverage guarantee.
10. A competitive rival gaining registrations without an adverse price change -> market momentum context, not a fake discount event.
11. A competitor price cut with no observed registration shift -> price pressure can be observed; lack of immediate shift is not proof of no pressure.
12. Same percentage-point share movement with different denominators -> coverage/denominator shown; no silent equivalence.
13. Switching Enterprise region changes only authorized registration context, not nationwide PDI/CTPDI.
14. Out-of-region province values cannot be obtained from API, PDF, tooltip, popups or cached payloads; neutral neighboring site pins still permitted.
15. High CTPDI gap cannot produce 90D predicted probability or lower-price forecast.
16. Site opening/closing observation must be verified before public network event; local geographic exposure not direct unit-sales estimate.
17. Unscored model returns `pressureScore:null` and honest UI, not `0` or fake qualitative label.
18. Two independent analysts can replay the same sources + config and get the same case order/claim; no unstated LLM weighting.
19. Source retract/correction changes a new revision but leaves prior frozen report reproducible.
20. Cross-account or unauthorized region report requests are denied server-side.

## 6. Implementation order without locking formulas

**P0 — Evidence audit:** replay 8–12 synthetic/golden **cases**; inspect current data readiness, Ice crosswalk/gate, MSRP/promotions event states and substitution evidence. NO code mutation/production.
**P1 — Pure offline components:** substitute candidate graph + approved-link fixtures; price event de-dup and basis guard; identity-safe registration context; deterministic signal cases. Run unit/property tests.
**P2 — Shadow retrospective:** sample historical vehicle competitive actions with owner-reviewed evidence; analyze false top alerts / misclassified substitutions; independently review text conclusions.
**P3 — Owner methodology decision:** approve competitor set criteria, market cohort, offer basis, temporal windows, materiality, score calibration strategy and release coverage.
**P4 — Org-scoped product integration:** after verified Ice R6→R7→R8 and entitlement design gates, expose model analysis sections 1–5 and immutable snapshot reports, with sparse signals or null score where data are insufficient.
**P5 — Optional calibrated score:** activate dimensionless numerical scoring only after independent labelled evaluation; separate 90D prediction work is OUT OF SCOPE.

No automatic PR merge, CI policy changes, product score permission, paid research/AI, production migrations or Market Track gate movement by creating this document.

## 7. All-engine methodology discipline (proposed common review rubric)

| Engine | Measure / domain truth | Identifiable from current data | What it must NOT claim | Crucial falsification test |
| --- | --- | --- | --- | --- |
| #200 Identity Resolution | link relation between external Ice group and TDR model(s) | audited group mapping with source continuity | unknown absent row=0, forced 1:1, unmatched dropped | many-to-many bundle, missing periods, no duplicated units |
| #201 Identity Bootstrap | evidence for new canonical identity | validated duplicate-negative candidate | candidate = actively sold model | dormant historical/code suffix doesn't auto-CREATE |
| #203 Catalog Maintainer | completeness, current marketed lineage and spec facts | eligibility + official completeness + cited field evidence | historical/discovered spec backfill; AI overrides admin | admin tombstones, false lineup omission, P1/P2 fairness |
| PDI | eligible Thai retail cash discount intensity & history | verified MSRP/offer per scoped trim and period | UNKNOWN=0, cash stacking assumptions, old cut = future floor | full-trim completeness, frozen cohorts, event vs post dedupe |
| CTPDI | approved comparable China/Thailand retail ratio | basis-matched CN & TH offer, FX and locked crosswalk | distributor margin/headroom or direct future discount | no matched pair => null, FX-only movement identified |
| Geography | network site/franchise/owner changes + registration geography | verified physical sites, source events & registered province | dealer sales, catchment-origin switching or closure by absence | moving sales franchise without closing site; cross-border ACL |
| Competitive Pressure | evidence-backed change in relative competitive position for one reference model | reviewed substitution + observed price movement + qualified registration context | measured customer switching/causation or uncalibrated 0–100 | rival price move vs market drift with independent sources |
| Layer 3 account relevance | why verified signals matter to an org's represented models | brand, user-region, authorized context, match graph | private org data exposed cross-tenant; fabricated action certainty | tenant isolation; empty-data/score-null; reproducible report |
| Vehicle DB governed writer | authority-safe mutations/revisions | immutable observations and explicit policy | retroactive overwrite, admin lock bypass, retired writer | deny silent writes; deterministic revert and idempotence |

**Design principle:** a numeric index is optional until its **measurement target, source identity, unit, validity window, missingness semantics and independent acceptance tests** are fixed. A polished UI is not evidence of a valid method.

## 8. Owner decisions needed before the formula is frozen

- Is the primary engine a **relative observed-position and evidence-ranked radar**, rather than a causal sales-loss estimator? (Recommended yes.)
- Is the **pairwise substitution graph** a reviewed first-class contract with `DIRECT/ADJACENT` types? (Recommended yes, statuses need owner approval.)
- Which price basis should power the default relative-position headline: verified general-cash net offers, MSRP, or two independently shown lanes? (Recommended **separate lanes**, cash evidence only when valid.)
- Which registration cohort/universe and time windows are defensible across Ice quality/mapping coverage? This needs a real coverage audit.
- For initial pilot, publish **qualitative evidence-ranked signals with `score=null`**, or require a calibrated numeric 0–100 score before any customer-facing V1? (Recommended pilot can start without invented score, preserve UI slot.)
- How to calibrate and version materiality, competitor comparability and score bands on independent owner-labelled cases?

**Nothing in this file is a blanket methodology approval.** All of these questions remain review items.
