# PEE-2 offline shadow evaluation report (generated, deterministic)

> **Read this first.** Every number below was measured by replaying fixtures
> through the unchanged PEE-1 engine with a *scripted replay provider*. They
> describe the **seed corpus only**. None of it is evidence of precision on live
> pages, and no scenario here is owner-labelled recorded evidence.

## Verdicts (two different questions)

* **Regression gates:** PASS — the engine still behaves as the labelled scenarios require.
* **Operational readiness: BLOCKED** — A green regression suite is not safety acceptance and not operational readiness.

| readiness requirement | met | detail |
| --- | --- | --- |
| regression_gates_pass | yes | every regression gate passes |
| no_open_findings | yes | no OPEN safety finding |
| owner_labelled_scenarios | **NO** | 0 owner-labelled scenarios; proposed minimum 30 |
| recorded_snapshot_scenarios | **NO** | 0 owner-labelled permission-cleared recorded snapshots; proposed minimum 10 |
| distinct_sources | **NO** | 0 distinct recorded sources; proposed minimum 3 |
| owner_authorization | **NO** | no explicit owner authorization (granted outside this tool, never inferred) |

## Fixture provenance

| evidence kind / label status | scenarios |
| --- | --- |
| `RECONSTRUCTED_FROM_PILOT_NOTES/PROPOSED_PENDING_OWNER_REVIEW` | 8 |
| `SYNTHETIC_ADVERSARIAL/PROPOSED_PENDING_OWNER_REVIEW` | 19 |

**Owner-labelled scenarios: 0.** The metrics below are therefore NOT owner-validated.

Scenarios: **27** · observations (scrapes): **80**

## Safety counters (proposed zero-tolerance gates — not adopted)

Computed over the regression scenarios, i.e. every scenario that is not an OPEN finding below.

| counter | value | limit | |
| --- | --- | --- | --- |
| false_accepts | 0 | 0 | PASS |
| forbidden_hits | 0 | 0 | PASS |
| unsafe_resolves | 0 | 0 | PASS |
| lost_pending_events | 0 | 0 | PASS |
| missed_events | 0 | 0 | PASS |
| false_events | 0 | 0 | PASS |
| unscripted_calls | 0 | 0 | PASS |
| unused_scripted_replies | 0 | 0 | PASS |
| p5_mismatches | 0 | 0 | PASS |
| p5_forbidden_hits | 0 | 0 | PASS |
| forbidden_stored | 0 | 0 | PASS |
| disposition_mismatches | 0 | 0 | PASS |
| ai_call_budget_violations | 0 | 0 | PASS |
| conditions_missed | 0 | 0 | PASS |
| missed_claims | 0 | 0 | PASS |

## Findings in the PEE-1 engine

None open.

Former findings, now enforced as ordinary regressions (their scenarios are inside the gates):

* **PEE2-F1** — LIST_PRICE was the default when no qualifier was recognised (promo, restricted-audience, eco-sticker, dealer or previous-price wording): s17_promo_label_after_amount, s18_restricted_audience_after_amount, s21_eco_sticker_is_not_msrp, s22_dealer_price_is_not_oem_msrp
* **PEE2-F2** — model, trim, amount and type were not required to form one local price fact (swapped pairs and cross-model attribution validated): s19_swapped_trim_amount_pairs, s20_other_models_price_attributed

## Event detection

* labelled events: 33 · detected: 33 (recall 100.0%)
* missed: 0 · lost pending retries: 0 · false events on unchanged pages: 0 (rate 0.0%)

## Claims

* labelled 144 · emitted 152 · coverage 100.0% (when the engine resolved: 100.0%) · precision 94.7%
* **false accepts 0** (rule 0, AI 0) · forbidden claims accepted 0 · missed 0 · tolerated less-specific rule claims 8
* labelled conditions 3 · missed 0

## Dispositions & review load

* UNCHANGED 20 · DETERMINISTIC 12 · AI_EXTRACTED 23 · REVIEW 25
* disposition mismatches 0 · unsafe resolves 0 · false reviews 0
* review rate 31.2% of observations · 62.5 review items / 100 observations
* by reason: CONDITIONS_NOT_INTERPRETED ×2, DATE_NOT_INTERPRETED ×1, DATE_NOT_IN_EVIDENCE ×3, EVIDENCE_NOT_FOUND ×1, FACT_NOT_BOUND ×6, NOT_VEHICLE_PRICE ×1, PRICE_TYPE_CONFLICT ×5, PRICE_TYPE_NOT_ALLOWED ×2, PRICE_TYPE_UNSUPPORTED ×5, PROVIDER_FAILED ×1, TOKEN_BUDGET_EXHAUSTED ×1, TRIM_AMBIGUOUS ×2, UNCOVERED_AMOUNT ×20

## Distinct price events (a price event is not a scrape count)

* 80 scrapes → labelled distinct events 21 · engine distinct events 21 · matched 21 (precision 100.0%, recall 100.0%)

## P5 24-hour semantics (unchanged P5, real catalog/P4)

* labelled P5 dispositions checked 16 · mismatches 0
* P5 outcomes the labels forbid (a rejected claim reaching P5 at all, or reaching CONFIRMED_REPLACEMENT): checked 19 · reached 0
* rejected claims found in the engine's success cache or stored interpretation (what is re-emitted later): 0

## Estimated usage (replay; no real model)

* AI calls 49 (61.25 / 100 observations) · cache hits 9
* tokens in 62,729 / out 9,961 (provider-reported when scripted, else the engine's character estimate)
* naive baseline (call the model on every fetch with price text): 78 calls, 106,839 input tokens → engine avoids 29 calls, input-token reduction 41.3%
* every call carries a fixed system prompt of about 1158 estimated tokens (the evidence excerpts are the small remainder), so call count, not excerpt size, drives cost
* cost: not computed — no token prices were supplied and none are assumed

## Same metrics by evidence kind

The corpus is adversarial-heavy by design; the reconstructed-from-pilot-notes rows are the closer proxy for real page behaviour, and still are not live pages.

| evidence kind | observations | AI calls / 100 obs | review rate | false accepts | missed events | false events |
| --- | --- | --- | --- | --- | --- | --- |
| `RECONSTRUCTED_FROM_PILOT_NOTES` | 34 | 23.53 | 5.9% | 0 | 0 | 0 |
| `SYNTHETIC_ADVERSARIAL` | 46 | 89.13 | 50.0% | 0 | 0 | 0 |

## Findings per scenario

| scenario | evidence / labels | issues |
| --- | --- | --- |
| s01_home_cards_stable | RECONSTRUCTED_FROM_PILOT_NOTES / PROPOSED_PENDING_OWNER_REVIEW | none |
| s02_home_price_cut_p5_24h | RECONSTRUCTED_FROM_PILOT_NOTES / PROPOSED_PENDING_OWNER_REVIEW | none |
| s03_promo_terms_only_change | RECONSTRUCTED_FROM_PILOT_NOTES / PROPOSED_PENDING_OWNER_REVIEW | none |
| s04_promo_window_extended | RECONSTRUCTED_FROM_PILOT_NOTES / PROPOSED_PENDING_OWNER_REVIEW | none |
| s05_buyer_guide_promo_move | RECONSTRUCTED_FROM_PILOT_NOTES / PROPOSED_PENDING_OWNER_REVIEW | none |
| s06_home_multi_model | RECONSTRUCTED_FROM_PILOT_NOTES / PROPOSED_PENDING_OWNER_REVIEW | none |
| s07_finance_conditional_not_msrp | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s08_estimated_not_list | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s09_deposit_and_instalment_noise | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s10_ambiguous_bare_max | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s11_hallucinated_evidence | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s12_noise_storm_one_real_change | RECONSTRUCTED_FROM_PILOT_NOTES / PROPOSED_PENDING_OWNER_REVIEW | none |
| s13_missing_dates_stay_unknown | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s14_daily_budget_exhaustion | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s15_provider_outage_bounded_retries | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s16_ai_claim_p5_24h_reobservation | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s17_promo_label_after_amount | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s18_restricted_audience_after_amount | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s19_swapped_trim_amount_pairs | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s20_other_models_price_attributed | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s21_eco_sticker_is_not_msrp | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s22_dealer_price_is_not_oem_msrp | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s23_missing_offer_is_not_zero | RECONSTRUCTED_FROM_PILOT_NOTES / PROPOSED_PENDING_OWNER_REVIEW | none |
| s24_shared_model_row_fails_closed | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s25_neighbouring_wording_does_not_leak | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s26_bare_price_wording_is_unproven | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
| s27_previous_price_is_not_current | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | none |
