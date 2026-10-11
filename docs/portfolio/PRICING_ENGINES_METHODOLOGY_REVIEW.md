# TDR Pricing Engines: PDI + CTPDI — measurement design review v0.1

**Review status:** PROPOSED; no formulas/thresholds beyond existing explicit owner locks are adopted by this file. No executable source code, no data writes, no market publication.  
**Design source:** TDR PDI×CTPDI Retail Pricing Intelligence Master Brief v0.7 (2026-10-08); `docs/portfolio/DOMAIN_BOUNDARIES.md`; Vehicle Master V3.

## P0. One pricing evidence plane, separate calculations

```text
Vehicle Master: canonical model/trim, applicable status, official MSRP ledger
Official/eligible campaign evidence: offer terms, scope, stacking, validity
China retail price evidence / currency FX          owner-approved CN–TH crosswalk
                ↓                              ↓
Observation ledger (facts as observed; effective_at != observed_at; source ID)
                ↓
Event dedupe + corrections + frozen universe + quality/missingness
             /                                   \
 PDI Thai discount intensity             CTPDI comparable cross-market ratio
             \                                   /
       Layer 3 pressure uses them as separate typed signals
```

**Never write source facts from a calculated index.** Event ledger is an evidence-preserving derived read model. Do not make PR #203 the 2021 historical price backfill worker: its current retail audit intentionally excludes historical/discontinued trim spec enrichment.

Every observation must distinguish `observed_at`, `effective_from`, `effective_to?`, `recorded_at` and corrections. A posted online price observed today could have been in force since an earlier effective date; **unknown effective date remains null**, not necessarily today's price action.

**Live coverage observation (2026-10-11):** [CP00_SOURCE_COVERAGE_AUDIT_2026-10-11.md](CP00_SOURCE_COVERAGE_AUDIT_2026-10-11.md) found only 273/1,431 CURRENT Trims with a matching LIST_PRICE ledger row, all 320 LIST_PRICE observations in one month (September 2026), and no normalized promotion amounts across 48 options. Consequently **the following formulas remain proposed only**; current whole-market PDI/monthly discount trend cannot be published from these inputs. Do not backfill `VERIFIED_ZERO` or manufacture dated price actions.

## P1. PDI construct — not a general price war mood gauge

**Owner-locked inclusion universe** (2026-10-08 owner product decisions):
- Brand origin China: HEV/PHEV/REEV/BEV.
- Brand origin Japan: ICE/HEV/BEV for **models admitted by explicit approved rules**; no auto-invented Japanese whitelist.
- A model enters when at least one CURRENT general-retail marketed Trim official MSRP is **strictly < THB 2,000,000**.
- Once model enters, **all** CURRENT general-retail Trims of the model are included, including trims MSRP >2m.
- Model representative MSRP is median of included trim MSRP, midpoint-average for even counts.
- Preserve all historic records/frozen snapshots, including retired models and not-scorable records; exclude student/professional and group-specific offers from national mainstream cash discount.

**Open owner decisions:** numerator and published index methodology, equal-model aggregation, freshness thresholds, Japan admission detail, model-universe publication coverage, offer treatment such as guaranteed cashback and cash bundles. These may be prototyped as alternatives, not silently locked.

### Candidate model formula from v0.7 (NOT approved)

For all current eligible Trim set T_m,t at t, with source-verified general-retail cash amount D_i:
```text
R_m,t = median(MSRP_i,t across ALL T_m,t)
C_m,t = median(D_i,t across ALL T_m,t)
PDI_m,t = 100 * C_m,t / R_m,t
```
Only score when **all** included Trim MSRP and relevant offer-state observations are usable (verified discount or `VERIFIED_ZERO`). `UNKNOWN`, `CONFLICT`, `EXPIRED`, no evidence of no-offer, or unverified stacking must prevent the model headline score, while coverage detail stays visible. `NOT_APPLICABLE` is not silently a discount zero.

**Measurement semantics:** this is the ratio of two Model-level medians, not a median transaction's realized discount rate and not `median(D_i / MSRP_i)`. Even `median(MSRP_i - D_i)` is generally not equal to `median(MSRP_i) - median(D_i)`; the former is the correct paired median-net-offer summary.

**Interpretation test:** a model with trims [1.49,1.79,2.09,2.49] million THB and verified general cash [100k,0,200k,300k] has median MSRP 1.94m, median cash 150k and candidate model PDI 7.73195876%. It is **not** evidence of a purchasable THB 1.79m median trim nor a specific consumer discount of 150k.

### PDI must output companion series, not one mysterious number

- **Cash discount level/intensity:** candidate PDI, native percentage.
- **Structural MSRP change:** permanent manufacturer list-price events, not cash discount numerator.
- **Net comparable offer price:** per-Trim MSRP minus verified eligible cash offer (never combine unmatched medians as a purchasable price).
- **Discount breadth:** verified discounted count / fully observed eligible denominator (else explicit partial).
- **Like-for-like move:** fixed model/trim cohorts where both periods are measurable; headline change may reflect universe composition. Label `RAW_CHANGE` and `LIKE_FOR_LIKE_CHANGE` separately.
- **Event count:** deduplicated actions (campaign single model cut across five trims = one model event), not captures/posts/scrapes. Same timestamped action may have several affected trims.
- **Frozen history:** original source/eligibility/method snapshots are immutable; late correction yields explicit revision, not silent old value replacement.

**Important causal boundary:** a high observed cash discount does not prove OEM loss, production inventory volume or future MSRP cuts. If model-level source completeness is poor, the honest output is `PARTIAL/NOT_SCORABLE`, with covered numerator/denominator, not a biased median of whichever trims are easiest to find.

### PDI adversarial tests

| ID | Input | Required behavior |
| --- | --- | --- |
| PDI-01 | MSRP 1.99m and 2.39m | Admit model and **both** trims |
| PDI-02 | MSRP 2.00m and 2.39m | Exclude; lower promotional price does not trigger entry |
| PDI-03 | one of four Trim discounts UNKNOWN | no model PDI score; preserve 3/4 verified coverage |
| PDI-04 | zero-offer verified evidence vs no discovered source | `VERIFIED_ZERO=0`; `UNKNOWN=null` |
| PDI-05 | 80k +20k offers unproven stackable | do not sum |
| PDI-06 | original offer expires and is not observed again | do not carry it forward |
| PDI-07 | five trims in one nationwide action | one model event plus affected Trim list |
| PDI-08 | official MSRP cut, cash discount unchanged | no invented cash-discount increase event |
| PDI-09 | extra high-priced trim enters, all same matched cohort pricing unchanged | raw median may change; like-for-like movement = zero |
| PDI-10 | full current-score publication with 2021 no data | current score may exist; 2021 frozen explorer shows `NO_SOURCE/UNKNOWN` not invented backfill |
| PDI-11 | competing local quote vs national campaign | local is separate source scope; no national contamination |
| PDI-12 | median-of-ratios vs ratio-of-medians different | report only methodology-selected formula with clear label/version |

## C0. CTPDI construct — observed cross-market pricing difference, NOT cash headroom

**Owner-locked infrastructure:** Admin-reviewed APPROVED + LOCKED China↔Thailand identity crosswalk; no automatch as prerequisite to initial product. Pairing subject must document model/generation/powertrain/comparable specification and variant rationale. A single raw Chinese name string cannot confer approval. Thai identity is canonical Vehicle Master, not overridden by China catalog naming.

Two different possible product constructs must not be conflated:
1. **Matched comparable pair gap:** for explicitly reviewed candidate pair and matched MSRP/cash basis; descriptive comparability grade and source conditions.
2. **Model/model-generation/powertrain headline:** a summary across reviewed pairs or per-country representative prices; aggregation and target grain are **not resolved** between prior product briefs.

### Candidate pair formula (not yet owner's published convention)

```text
P_TH = source-confirmed comparable consumer retail price in THB
P_CN = source-confirmed comparable consumer retail price in CNY
FX   = THB per CNY at named agreed measurement date
r    = P_TH / (P_CN * FX)
GAP_PCT       = (r - 1) * 100         # parity 0%
PARITY100     = r * 100              # parity 100
```

Both representations encode the same ratio; **do not switch published display/series units without a methodology/version decision**. `r=1.35` means a **+35% consumer retail price gap on defined basis**, not distributor profit, avoidable tax, future discount or 'margin 35%'.

Price basis modes:
- `LIST_VS_LIST` (comparable official country consumer MSRP basis, all stated taxes/conditions documented).
- `NET_CASH_VS_NET_CASH` only when both individual matched vehicles have verified, valid, comparable general-retail cash offers.
- `MIXED/UNKNOWN`: do not calculate a misleading comparison.
- Never use model-wide PDI to subtract from pair-level Thai MSRP to synthesize a matched offer.
- If trims/spec differ materially, `NO_COMPARABLE_PAIR` or lower-grade informational comparator where approved; no fake zero.
- CN pair refresh must audit originally reviewed identity after model/generation/powertrain or specifications change; use approved locked crosswalk version.

**Mathematically exact FX attribution for positive comparable prices:**
```text
ln(r_t / r_0) = ln(P_TH,t / P_TH,0) - ln(P_CN,t / P_CN,0) - ln(FX_t / FX_0)
```
This is an identity **attribution of measured multiplicative ratio changes**, not a causal decomposition of why OEMs priced their vehicles. Expose separate list/cash-price and FX movements; missing data breaks attribution.

**Example:** if TH and CN list prices are unchanged but THB per CNY falls by 10%, `r` rises by factor 1/0.9 = 1.111..., despite neither OEM changing sticker price. Calling that 'Thai price suddenly cut-proof' or 'OEM raised profit' would be false.

### CTPDI adversarial tests

| ID | Input | Required behavior |
| --- | --- | --- |
| CTP-01 | similar vehicle name but crosswalk unapproved | `NO_APPROVED_PAIR` |
| CTP-02 | Yuan PLUS ↔ ATTO 3 example only | no live mapping without owner-reviewed lock |
| CTP-03 | trim specs materially different | no blind headline ratio |
| CTP-04 | CN MSRP and TH cash campaign, mismatched basis | no computed list-gap or net-gap |
| CTP-05 | TH model PDI exists, CN net cash unknown | no inferred adjusted CN/TH gap |
| CTP-06 | pair price and FX positive, r=1.35 | GAP=+35%, PARITY100=135 per approved output convention |
| CTP-07 | only FX changes | independent FX contribution, OEM sticker price change=0 |
| CTP-08 | crosswalk locked pair becomes different generation | flag re-review; preserve historical pair snapshots |
| CTP-09 | missing P_CN or stale FX | null with source status |
| CTP-10 | two pairs with different comparability grades | do not average into model headline without approved aggregation |

## C1. Interaction with Competitive Pressure

Competitive Pressure may cite PDI as **market-wide cash-discount context** and CTPDI as **cross-market pricing context**, but:
- It must compute its own *relative competitive price advantage* on coherent TH basis/cohort.
- A competitor's observed net-offer cut already includes the same cash change summarized by PDI. PDI must not be added as a second independent signal of that cut.
- High CTPDI does not establish the amount that the Thai price **can** or **will** be cut.
- A validated national index does not change just because a Toolkit user changes Active Region; registration context is a separate geographic series.
- The pressure ranking should retain underlying facts even when PDI/CTPDI headline publication is blocked by coverage/owner gates.

## C2. Governance and pilot build order

1. **Read-only upstream audit:** actual vehicle price/campaign tables, effective dates, source classes, 2021–present evidence distribution, current Retail Trim lifecycle and completeness. No assumption historical coverage is complete.
2. **Golden fixture models:** prove PDI-01..12 and CTP-01..10, including stale/conflict/missingness.
3. **Offer/Event Ledger interface:** separate observations, effective events, correction history, coverage and frozen cohort snapshots.
4. **Read-only deterministic pure calculation:** implement candidate PDI and ratio as two `EXPERIMENTAL_UNPUBLISHED` output paths only after separately approved task scope.
5. **Owner methodology gate:** lock Japanese admission, discount bundle policy, per-model score, market weights, index coverage/freshness, comparable pairs/headline grain, ratio output convention and price bases.
6. **Verified samples and release gate:** no production index or Layer 3 pricing claim without source trace, basis/coverage checks and approved publish authorization.

**Gates do not block unrelated Ice R6 owner state reconciliation, existing website UI design or nonpricing read-only catalog work.**
