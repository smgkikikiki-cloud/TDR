# PEE-2 offline shadow evaluation report (generated, deterministic)

> **Read this first.** Every number below was measured by replaying fixtures
> through the unchanged PEE-1 engine with a *scripted replay provider*. They
> describe the **seed corpus only**. None of it is evidence of precision on live
> pages, and no scenario here is owner-labelled recorded evidence.

## Fixture provenance

| evidence kind / label status | scenarios |
| --- | --- |
| `RECONSTRUCTED_FROM_PILOT_NOTES/PROPOSED_PENDING_OWNER_REVIEW` | 8 |
| `SYNTHETIC_ADVERSARIAL/PROPOSED_PENDING_OWNER_REVIEW` | 15 |

**Owner-labelled scenarios: 0.** The metrics below are therefore NOT owner-validated.

Scenarios: **23** · observations (scrapes): **70**

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
| disposition_mismatches | 0 | 0 | PASS |
| ai_call_budget_violations | 0 | 0 | PASS |
| conditions_missed | 0 | 0 | PASS |
| missed_claims | 0 | 0 | PASS |

## OPEN FINDINGS in the accepted PEE-1 engine (not fixed here)

These scenarios reproduce defects. They are excluded from the gates above (so the gates detect *new* regressions) but are included in every headline number below. Fixing them is a Chunk 1 change that needs a QA decision.

| finding | scenario | counters | still reproduces |
| --- | --- | --- | --- |
| PEE2-F1 — LIST_PRICE is the default when no qualifier is recognised: promo, restricted-audience, eco-sticker or dealer wording around the amount is not checked, so a qualified price is accepted as MSRP (and the right type refused) | s17_promo_label_after_amount | false_accepts 2, forbidden_hits 2, unsafe_resolves 1, lost_pending_events 1, p5_forbidden_hits 1, disposition_mismatches 2, missed_claims 1 | yes |
| PEE2-F1 — LIST_PRICE is the default when no qualifier is recognised: promo, restricted-audience, eco-sticker or dealer wording around the amount is not checked, so a qualified price is accepted as MSRP (and the right type refused) | s18_restricted_audience_after_amount | false_accepts 2, forbidden_hits 2, unsafe_resolves 2, lost_pending_events 1, p5_forbidden_hits 1, disposition_mismatches 2 | yes |
| PEE2-F2 — trim/model must appear in the quote and the amount in the quote, but not next to each other, so mis-paired claims validate and can resolve the change | s19_swapped_trim_amount_pairs | false_accepts 4, forbidden_hits 4, unsafe_resolves 1, lost_pending_events 1, p5_forbidden_hits 2, disposition_mismatches 2, missed_claims 2 | yes |
| PEE2-F2 — trim/model must appear in the quote and the amount in the quote, but not next to each other, so mis-paired claims validate and can resolve the change | s20_other_models_price_attributed | false_accepts 2, forbidden_hits 2, unsafe_resolves 1, lost_pending_events 1, disposition_mismatches 2, missed_claims 1 | yes |
| PEE2-F1 — LIST_PRICE is the default when no qualifier is recognised: promo, restricted-audience, eco-sticker or dealer wording around the amount is not checked, so a qualified price is accepted as MSRP (and the right type refused) | s21_eco_sticker_is_not_msrp | false_accepts 2, forbidden_hits 2, unsafe_resolves 2, lost_pending_events 1, disposition_mismatches 2 | yes |
| PEE2-F1 — LIST_PRICE is the default when no qualifier is recognised: promo, restricted-audience, eco-sticker or dealer wording around the amount is not checked, so a qualified price is accepted as MSRP (and the right type refused) | s22_dealer_price_is_not_oem_msrp | false_accepts 2, forbidden_hits 2, unsafe_resolves 2, lost_pending_events 1, disposition_mismatches 2 | yes |

## Event detection

* labelled events: 30 · detected: 24 (recall 80.0%)
* missed: 0 · lost pending retries: 6 · false events on unchanged pages: 0 (rate 0.0%)

## Claims

* labelled 130 · emitted 148 · coverage 96.9% (when the engine resolved: 96.8%) · precision 85.1%
* **false accepts 14** (rule 0, AI 14) · forbidden claims accepted 14 · missed 4 · tolerated less-specific rule claims 8
* labelled conditions 3 · missed 0

## Dispositions & review load

* UNCHANGED 23 · DETERMINISTIC 12 · AI_EXTRACTED 24 · REVIEW 11
* disposition mismatches 12 · unsafe resolves 9 · false reviews 0
* review rate 15.7% of observations · 28.57 review items / 100 observations
* by reason: CONDITIONS_NOT_INTERPRETED ×2, DATE_NOT_INTERPRETED ×1, DATE_NOT_IN_EVIDENCE ×3, EVIDENCE_NOT_FOUND ×1, NOT_VEHICLE_PRICE ×1, PRICE_TYPE_CONFLICT ×2, PROVIDER_FAILED ×1, TOKEN_BUDGET_EXHAUSTED ×1, TRIM_AMBIGUOUS ×2, UNCOVERED_AMOUNT ×6

## Distinct price events (a price event is not a scrape count)

* 70 scrapes → labelled distinct events 20 · engine distinct events 16 · matched 16 (precision 100.0%, recall 80.0%)

## P5 24-hour semantics (unchanged P5, real catalog/P4)

* labelled P5 dispositions checked 16 · mismatches 0
* P5 outcomes the labels forbid (e.g. a wrong claim reaching CONFIRMED_REPLACEMENT): checked 4 · reached 4

## Estimated usage (replay; no real model)

* AI calls 36 (51.43 / 100 observations) · cache hits 12
* tokens in 36,298 / out 6,540 (provider-reported when scripted, else the engine's character estimate)
* naive baseline (call the model on every fetch with price text): 68 calls, 75,054 input tokens → engine avoids 32 calls, input-token reduction 51.6%
* every call carries a fixed system prompt of about 891 estimated tokens (the evidence excerpts are the small remainder), so call count, not excerpt size, drives cost
* cost: not computed — no token prices were supplied and none are assumed

## Same metrics by evidence kind

The corpus is adversarial-heavy by design; the reconstructed-from-pilot-notes rows are the closer proxy for real page behaviour, and still are not live pages.

| evidence kind | observations | AI calls / 100 obs | review rate | false accepts | missed events | false events |
| --- | --- | --- | --- | --- | --- | --- |
| `RECONSTRUCTED_FROM_PILOT_NOTES` | 34 | 23.53 | 5.9% | 0 | 0 | 0 |
| `SYNTHETIC_ADVERSARIAL` | 36 | 77.78 | 25.0% | 14 | 0 | 0 |

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
| s17_promo_label_after_amount | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | disposition_mismatches×2, false_accept_ai×2, lost_pending_events×1, missed_claim×1, p5_forbidden_hits×1, unsafe_resolves×1 |
| s18_restricted_audience_after_amount | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | disposition_mismatches×2, false_accept_ai×2, lost_pending_events×1, p5_forbidden_hits×1, unsafe_resolves×2 |
| s19_swapped_trim_amount_pairs | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | disposition_mismatches×2, false_accept_ai×4, lost_pending_events×1, missed_claim×2, p5_forbidden_hits×2, unsafe_resolves×1 |
| s20_other_models_price_attributed | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | disposition_mismatches×2, false_accept_ai×2, lost_pending_events×1, missed_claim×1, unsafe_resolves×1 |
| s21_eco_sticker_is_not_msrp | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | disposition_mismatches×2, false_accept_ai×2, lost_pending_events×1, unsafe_resolves×2 |
| s22_dealer_price_is_not_oem_msrp | SYNTHETIC_ADVERSARIAL / PROPOSED_PENDING_OWNER_REVIEW | disposition_mismatches×2, false_accept_ai×2, lost_pending_events×1, unsafe_resolves×2 |
| s23_missing_offer_is_not_zero | RECONSTRUCTED_FROM_PILOT_NOTES / PROPOSED_PENDING_OWNER_REVIEW | none |
