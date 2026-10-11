# Engine Review Gates — how a TDR analytic engine earns the right to be deployed

**State:** G0 proposal only. This is a **review checklist** for owner adoption, NOT active CI or an Enforcer permission.  
**Scope:** PR200, PR201, PR203, PDI, CTPDI, Competitive Pressure, Geography/Network Watch and their Layer 3 interpretation. UI rendering and sales launch are separately gated.

## Six-test methodology envelope (M0–M5)

An analytic engine is ready to use only when it can answer all six questions.

1. **M0 — Construct:** what *observable* quantity/relation is this computing? What unit, subject grain, geographic/retail scope, clock and expected business question? No unnamed 'pressure' or 'opportunity' magic number.
2. **M1 — Evidence sufficiency:** which source fields and provenance exist? What coverage/accuracy/freshness limits are known? What data combination is impossible? Missing/unknown != zero, unpublished / only in draft != known.
3. **M2 — Identity/unit consistency:** how many-to-many canonical/model-group relationships, source panel grain, trim/model, site/franchise/operator, FX, and geographic denominator work without hidden double counting?
4. **M3 — Deterministic method:** formula or versioned rule, baseline/cohort, frozen snapshots, correction policy and confidence/coverage semantics. A model or LLM can write explanation from the computed evidence, not silently create a numerical ground truth.
5. **M4 — Falsification:** explicit counterexamples, independent reference calculation where possible, unknown/conflict/staleness cases, cross-tenant negative tests, source correction/replay, OOD/holdout comparisons when a model is used.
6. **M5 — Commercial interpretation:** what does the measure **not** prove; exact sentence a dealer can act on; when must UI say `NOT_SCORABLE` or `NO_VERIFIED_CHANGE`; which owner approval is required for publishing a claim?

### Applied reviews

| Engine | Required construct | Candidate acceptance artifact | Hard stop |
| --- | --- | --- | --- |
| PR200 | link relations at Ice group ↔ TDR model grain | labelled calibration, stable relation bundles, gap semantics, R6 reconciliation | owner-unlabelled thresholds cannot become resolved identity |
| PR201 | existence/novelty candidate, not sale | shadow and negative CREATE labels | no structural write before V3 writer, verified identity, permission |
| PR203 | current retail completeness and applicable spec evidence | complete-source negative tests, two fair queues, locks, stable job IDs, CI in both dirs | no historical spec enrichment/unsafe trim write/paid calls unapproved |
| PDI | native cash discount intensity in eligible national retail universe | full-trim coverage, discount-status + provenance, like-for-like/frozen, event dedupe | no unknown discount = zero, no formula publication before approval |
| CTPDI | matched CN–TH retail price gap on basis/versioned FX | locked pair fixtures, price-base consistency, FX-only tests | no unmatched ratio, no margin or headroom promise |
| Competitive Pressure | relative observed change conditional on reviewed substitution | golden casebook, movement arithmetic, same-grain registration corroboration, holdout ranking | no causal displacement nor arbitrary 0–100 without calibration |
| Geography | physically verified site/franchise/owner relations and registered-province context | source change event and location evidence, region masking, MAUP caveat | no branch sales inference/closure by locator disappearance |
| Network Watch | audited network change with detected vs actual effective time | reviewed event lifecycle, event dedupe, before/after relationship, revised histories | no candidate-only public closures or branch-sales causality |
| Layer 3 | account-specific evidence prioritization, own represented models, selected authorized region | org server-side ACL, actual evidence drilldown, immutable snapshot/report, no-data states | no fabricated forecast or cross-tenant access |


## Non-interchangeable relationship graphs — three different questions

| Relationship | Graph edge answers | Allowed target/authority | Forbidden inference |
| --- | --- | --- | --- |
| **Ice→TDR Identity Resolution** (PR200) | “Which canonical Model(s) explain this Ice model_group_id?” | Versioned, reviewed group/Model identity link (`EQUIVALENT/PART_OF/COMPOSED_OF`) | A matching Ice group is not automatically a rival or a separately priced trim |
| **CN→TH CTPDI Crosswalk** | “Are these China and Thailand-market vehicle definitions sufficiently equivalent for cross-market retail price measurement?” | Admin-approved locked comparable pair; match method, generation/spec/price-basis evidence | A shared model/family name neither proves equivalence nor defines a Thai-market substitute |
| **TH reference→TH competitor Substitution Graph** | “Would these *distinct* available Thai-market models plausibly compete for the same buyer/use case?” | Reviewable conditional directed pair/context, even if both vehicles belong to different brands/segments | A substitute is not identical across Ice/CN data; confirmed product presence does not measure diversion ratio |

**Separate graph storage/keys and review policies.** Do not call a single generic `vehicle_match` result sufficient for all three economic questions. None of the three automatically sets the others to approved.

**Universe distinction:** PDI's strict any-trim MSRP <THB 2m inclusion rule governs **PDI computation only**. It must NOT trim Competitive Pressure's pool of relevant substitutes; a buyer may cross-shop a relevant vehicle outside that index universe. Likewise, CTPDI `NO_COMPARABLE_PAIR` does not mean a Thai competitor is irrelevant. A Competitive Pressure rival may have `PDI_NOT_ELIGIBLE` and `CTPDI_NO_PAIR` yet remain a valid observed price/market competitor if other evidence supports it.

## Shared data consistency laws

### D1. Identity

No master identity may be created from Ice group presence alone. `Ice group ↔ TDR model` is an association, not a copy of the registration data into Vehicle Master. Retired/status-unknown trims do not become current automatically. `EQUIVALENT / PART_OF / COMPOSED_OF` require explicit relationship cardinality and nonduplicating aggregation.

### D2. Dual-time evidence

At least three clocks are explicit: `observed_at` (source captured), `effective_at` (business price/franchise change begins if known), and `published_at` (TDR accepted exposure). Price changes and network changes can be learned late. No UI rewrites history as though TDR knew something before it was observed.

### D3. Composition

Never combine data at different grains without an approved map: trim price vs model index, Ice model-group vs TDR model, provincial registration vs branch site, CN variant vs TH variant, brand price action vs individual model headline.

### D4. Governance

A source observation is not an owner-approved fact and a derived metric is not an independent source. No LLM can approve itself. `UNKNOWN`, `NOT_APPLICABLE`, `VERIFIED_ZERO`, `CONFLICT`, `SOURCE_STALE` mean different things; local definitions must map to explicit shared statuses.

### D5. Production publication

No customer-facing historical index or alert without source IDs, coverage denominator, as-of, methodology version and rights/entitlement. No data claim may depend on UI-only authorization. No Night Shift preflight task is authorized by the existence of this file.

## Cross-engine dependencies for actual development

```text
             Vehicle Master canonical identity + retailer trim set
                         |          |
         PR200 reviewed Ice links     Price observation + campaign ledger
                 |                      |
       Ice registration read model    PDI source discount + price events
                 |                      |
                 +--- Substitution Graph + Relative Price Position
                                         |
                       Qualified Registration Context
                                         |
                            Competitive Pressure Signals
                                         |
                   Org/Team Entitlement + Model Analysis
                                         |
              Layer 3 Competitive Pressure V1 + PDF

 CN source/FX + admin locked CN–TH crosswalk -> CTPDI -> optional V1 pricing context
 Dealer Site/Franchise/Operator/evidence -> Geography V1.5 -> Network Watch V2
 PR201 Bootstrap -> (later governed writer) -> discovered identities
 PR203 Retail Audit -> (later governed writer) -> maintained current catalog
```

**Important dependency correction:** A pre-event *substitute-candidate graph* and read-only pressure price-event path can be built with documented evidence while the full PDI/CTPDI Headline and geographic catalogs are unfinished. However, live regional per-model registration must wait for defensible Ice identity/read authority (R6 reviewed and R7 accepted; final website market cutover R8 is separately owner approved).

### Suggested upcoming owner reviews in order

A. Confirm core pressure output: *rank evidence-supported competitive movements*, not alleged unit sales loss or forecast.  
B. Confirm substitution graph is a first-class, versioned domain, starting as a reviewed candidate graph and allowing direct/adjacent/benchmark relations only with demonstrated basis.  
C. Select default price presentation: **two independent lanes** — official MSRP and verified general-cash net offers — with no blended arbitrary number.  
D. Decide that an uncalibrated 0–100 is **null in V1 evidence pilot**, whereas UX slot remains for future calibrated score (OR require score + calibration before public pilot).  
E. PDI/CN–TH methodology and geography data gates reviewed in their respective documents; no implied cross-project approval.

Decision A–D are **recommendations, not yet owner-approved**. A previous message approving order (Pressure→Geography→Network) does not approve these methodology decisions.

## Pilot-evaluation design: methods must be independently refutable

1. **Fix the observation cutoff**: reconstruct only evidence available at historic as-of time; prevent future price list, late Ice package, late news corrections or review decisions from leaking into historical testing.
2. **Owner-labelled cases:** with actual source rights, review pairs/market events independently; split training/calibration from test period or models, not merely random duplicated listings.
3. **Candidate substitute quality:** compute agreement and disputed pairs with explicit reviewer rationales; random negatives and difficult near-neighbor controls.
4. **Price event quality:** precision of verified general-cash offer vs unqualified ads, event dedupe, stale and conditional campaign capture; distinguish source *availability* from asserted `VERIFIED_ZERO`.
5. **Signal rankings:** measure whether withheld owner-reviewed important competitive changes are surfaced within top-N; compare with simpler baselines (only new price cuts; all same-segment model pairs). A more complicated formula must beat a simple and transparent baseline.
6. **Robustness:** simulate source outages, FX-only shocks, changing trim sets, many-to-many identity, registration class/year alignment, region ACL, dealer directory omissions.
7. **UI value:** one verified material movement and its evidence is actionable; three fabricated alerts are not. No pilot KPI claims unless instrumented and benchmarked.

## Deliverable gate (proposed)

A specific engine may advance from `DESIGN_REVIEW` to `OFFLINE_ENGINE` when the owner has approved its narrow construct/rules, its input coverage has been audited enough for fixtures and it has a bounded Task Packet. From `OFFLINE_ENGINE` to `SHADOW` requires independent tests. From `SHADOW` to `CUSTOMER` additionally requires source entitlement, governance, live-data inspection and explicit owner go. There is **no implicit automatic step**.

Existing PR #200/#201/#203 retain their own gate policies, not a replacement by this general proposal.
