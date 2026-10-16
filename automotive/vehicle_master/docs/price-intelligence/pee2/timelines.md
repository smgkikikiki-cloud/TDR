# PEE-2 event timelines (generated, deterministic)

## s01_home_cards_stable — Homepage price cards re-fetched with only page noise changing

role `PRICE_LIST` · evidence `RECONSTRUCTED_FROM_PILOT_NOTES` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | DETERMINISTIC | FIRST_SEEN | MAX+ 699,000 LIST<br>ULTRA 809,000 ESTIMATED | – | – | 0 | – | MAX+ LIST 699,000: NO_CHANGE<br>ULTRA ESTIMATED 809,000: NO_CHANGE |
| o2 | 2026-10-06T11:00 | UNCHANGED | – | MAX+ 699,000 LIST<br>ULTRA 809,000 ESTIMATED | – | – | 0 | – | MAX+ LIST 699,000: NO_CHANGE<br>ULTRA ESTIMATED 809,000: NO_CHANGE |
| o3 | 2026-10-07T12:00 | UNCHANGED | – | MAX+ 699,000 LIST<br>ULTRA 809,000 ESTIMATED | – | – | 0 | – | MAX+ LIST 699,000: NO_CHANGE<br>ULTRA ESTIMATED 809,000: NO_CHANGE |

## s02_home_price_cut_p5_24h — List price cut seen twice 25h apart, then cut again

role `PRICE_LIST` · evidence `RECONSTRUCTED_FROM_PILOT_NOTES` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | DETERMINISTIC | FIRST_SEEN | MAX+ 699,000 LIST<br>ULTRA 809,000 ESTIMATED | – | – | 0 | – | MAX+ LIST 699,000: NO_CHANGE<br>ULTRA ESTIMATED 809,000: NO_CHANGE |
| o2 | 2026-10-06T11:00 | DETERMINISTIC | AMOUNTS | MAX+ 679,000 LIST<br>ULTRA 809,000 ESTIMATED | – | – | 0 | – | MAX+ LIST 679,000: PENDING_REPLACEMENT<br>ULTRA ESTIMATED 809,000: NO_CHANGE |
| o3 | 2026-10-07T12:00 | UNCHANGED | – | MAX+ 679,000 LIST<br>ULTRA 809,000 ESTIMATED | – | – | 0 | – | MAX+ LIST 679,000: CONFIRMED_REPLACEMENT<br>ULTRA ESTIMATED 809,000: NO_CHANGE |
| o4 | 2026-10-08T09:00 | DETERMINISTIC | AMOUNTS | MAX+ 669,000 LIST<br>ULTRA 809,000 ESTIMATED | – | – | 0 | – | MAX+ LIST 669,000: PENDING_REPLACEMENT<br>ULTRA ESTIMATED 809,000: NO_CHANGE |

## s03_promo_terms_only_change — Open-ended promotion: terms change, prices identical

role `PROMOTION` · evidence `RECONSTRUCTED_FROM_PILOT_NOTES` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | DETERMINISTIC | FIRST_SEEN | MAX+ 599,000 CAMPAIGN<br>MAX+ 699,000 LIST<br>ULTRA 699,000 CAMPAIGN<br>ULTRA 809,000 ESTIMATED | – | – | 0 | – | – |
| o2 | 2026-10-06T11:00 | AI_EXTRACTED | CONDITIONS | MAX+ 599,000 CAMPAIGN<br>MAX+ 699,000 LIST<br>ULTRA 699,000 CAMPAIGN<br>ULTRA 809,000 ESTIMATED | – | – | 1 | – | – |
| o3 | 2026-10-07T12:00 | UNCHANGED | – | MAX+ 599,000 CAMPAIGN<br>MAX+ 699,000 LIST<br>ULTRA 699,000 CAMPAIGN<br>ULTRA 809,000 ESTIMATED | – | – | 0 | hit | – |
| o4 | 2026-10-08T14:00 | REVIEW | CONDITIONS | MAX+ 599,000 CAMPAIGN<br>MAX+ 699,000 LIST<br>ULTRA 699,000 CAMPAIGN<br>ULTRA 809,000 ESTIMATED | – | CONDITIONS_NOT_INTERPRETED | 1 | – | – |
| o5 | 2026-10-09T16:00 | AI_EXTRACTED | CONDITIONS | MAX+ 599,000 CAMPAIGN<br>MAX+ 699,000 LIST<br>ULTRA 699,000 CAMPAIGN<br>ULTRA 809,000 ESTIMATED | – | – | 1 | – | – |

## s04_promo_window_extended — Campaign window extended across a month boundary

role `PROMOTION` · evidence `RECONSTRUCTED_FROM_PILOT_NOTES` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-08-21T09:00 | DETERMINISTIC | FIRST_SEEN | MAX+ 579,000 CAMPAIGN 2026-08-21→2026-08-30<br>MAX+ 699,000 LIST<br>ULTRA 669,000 CAMPAIGN 2026-08-21→2026-08-30<br>ULTRA 789,000 LIST | – | – | 0 | – | – |
| o2 | 2026-08-28T10:00 | AI_EXTRACTED | DATES,LABELS | MAX+ 579,000 CAMPAIGN<br>MAX+ 699,000 LIST<br>ULTRA 669,000 CAMPAIGN<br>ULTRA 789,000 LIST | MAX+ 579,000 CAMPAIGN 2026-08-21→2026-09-06<br>ULTRA 669,000 CAMPAIGN 2026-08-21→2026-09-06 | – | 1 | – | – |
| o3 | 2026-08-29T11:00 | UNCHANGED | – | MAX+ 579,000 CAMPAIGN<br>MAX+ 699,000 LIST<br>ULTRA 669,000 CAMPAIGN<br>ULTRA 789,000 LIST | MAX+ 579,000 CAMPAIGN 2026-08-21→2026-09-06<br>ULTRA 669,000 CAMPAIGN 2026-08-21→2026-09-06 | – | 0 | hit | – |
| o4 | 2026-09-03T10:00 | REVIEW | DATES | MAX+ 579,000 CAMPAIGN<br>MAX+ 699,000 LIST<br>ULTRA 669,000 CAMPAIGN<br>ULTRA 789,000 LIST | – | DATE_NOT_INTERPRETED,DATE_NOT_IN_EVIDENCE,DATE_NOT_IN_EVIDENCE | 1 | – | – |
| o5 | 2026-09-04T10:00 | AI_EXTRACTED | DATES | MAX+ 579,000 CAMPAIGN<br>MAX+ 699,000 LIST<br>ULTRA 669,000 CAMPAIGN<br>ULTRA 789,000 LIST | MAX+ 579,000 CAMPAIGN 2026-08-21→2026-09-13<br>ULTRA 669,000 CAMPAIGN 2026-08-21→2026-09-13 | – | 1 | – | – |

## s05_buyer_guide_promo_move — Buyer-guide table: only one promo figure moves

role `BLOG` · evidence `RECONSTRUCTED_FROM_PILOT_NOTES` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | DETERMINISTIC | FIRST_SEEN | LONG RANGE DYNAMIC 589,000 CAMPAIGN<br>LONG RANGE DYNAMIC 629,000 LIST<br>LONG RANGE MAX 639,000 CAMPAIGN<br>LONG RANGE MAX 679,000 LIST<br>MAX+ 579,000 CAMPAIGN<br>MAX+ 699,000 LIST<br>ULTRA 669,000 CAMPAIGN<br>ULTRA 789,000 LIST | – | – | 0 | – | – |
| o2 | 2026-10-06T11:00 | DETERMINISTIC | AMOUNTS | LONG RANGE DYNAMIC 589,000 CAMPAIGN<br>LONG RANGE DYNAMIC 629,000 LIST<br>LONG RANGE MAX 639,000 CAMPAIGN<br>LONG RANGE MAX 679,000 LIST<br>MAX+ 569,000 CAMPAIGN<br>MAX+ 699,000 LIST<br>ULTRA 669,000 CAMPAIGN<br>ULTRA 789,000 LIST | – | – | 0 | – | – |
| o3 | 2026-10-07T12:00 | UNCHANGED | – | LONG RANGE DYNAMIC 589,000 CAMPAIGN<br>LONG RANGE DYNAMIC 629,000 LIST<br>LONG RANGE MAX 639,000 CAMPAIGN<br>LONG RANGE MAX 679,000 LIST<br>MAX+ 569,000 CAMPAIGN<br>MAX+ 699,000 LIST<br>ULTRA 669,000 CAMPAIGN<br>ULTRA 789,000 LIST | – | – | 0 | – | – |

## s06_home_multi_model — Multi-model homepage: other models' prices are not P3's job

role `PRICE_LIST` · evidence `RECONSTRUCTED_FROM_PILOT_NOTES` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | AI_EXTRACTED | FIRST_SEEN | MAX+ 699,000 LIST<br>ULTRA 809,000 ESTIMATED | 2WD MAX 859,000 LIST<br>MAX+ 709,000 LIST | – | 1 | – | – |
| o2 | 2026-10-06T11:00 | UNCHANGED | – | MAX+ 699,000 LIST<br>ULTRA 809,000 ESTIMATED | 2WD MAX 859,000 LIST<br>MAX+ 709,000 LIST | – | 0 | hit | – |
| o3 | 2026-10-07T12:00 | AI_EXTRACTED | AMOUNTS | MAX+ 689,000 LIST<br>ULTRA 809,000 ESTIMATED | 2WD MAX 859,000 LIST<br>MAX+ 709,000 LIST | – | 1 | – | – |

## s07_finance_conditional_not_msrp — Finance-conditional price must never become MSRP

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | REVIEW | FIRST_SEEN | – | – | PRICE_TYPE_CONFLICT,UNCOVERED_AMOUNT | 1 | – | – |
| o2 | 2026-10-06T11:00 | AI_EXTRACTED | FIRST_SEEN | – | MAX+ 599,000 FINANCE | – | 1 | – | – |
| o3 | 2026-10-07T12:00 | UNCHANGED | – | – | MAX+ 599,000 FINANCE | – | 0 | hit | – |

## s08_estimated_not_list — An estimated price must not be accepted as MSRP

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | REVIEW | FIRST_SEEN | – | – | PRICE_TYPE_CONFLICT,UNCOVERED_AMOUNT | 1 | – | – |
| o2 | 2026-10-06T11:00 | AI_EXTRACTED | FIRST_SEEN | – | ULTRA 809,000 ESTIMATED | – | 1 | – | – |

## s09_deposit_and_instalment_noise — Down payment / instalment amounts are not vehicle prices

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | REVIEW | FIRST_SEEN | – | MAX+ 699,000 LIST | NOT_VEHICLE_PRICE | 1 | – | – |
| o2 | 2026-10-06T11:00 | AI_EXTRACTED | FIRST_SEEN | – | MAX+ 699,000 LIST | – | 1 | – | – |

## s10_ambiguous_bare_max — Bare 'MAX' is ambiguous against MAX+ / LONG RANGE MAX (P4)

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | REVIEW | FIRST_SEEN | – | – | TRIM_AMBIGUOUS,UNCOVERED_AMOUNT | 1 | – | – |
| o2 | 2026-10-06T11:00 | REVIEW | FIRST_SEEN | – | – | TRIM_AMBIGUOUS,UNCOVERED_AMOUNT | 1 | – | – |

## s11_hallucinated_evidence — A claim quoting text that is not on the page

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | REVIEW | FIRST_SEEN | – | – | EVIDENCE_NOT_FOUND,UNCOVERED_AMOUNT | 1 | – | – |
| o2 | 2026-10-06T11:00 | AI_EXTRACTED | FIRST_SEEN | – | MAX+ 699,000 LIST | – | 1 | – | – |

## s12_noise_storm_one_real_change — Eight scrapes, noise on every page, one real price cut

role `PRICE_LIST` · evidence `RECONSTRUCTED_FROM_PILOT_NOTES` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-01T10:01 | DETERMINISTIC | FIRST_SEEN | MAX+ 699,000 LIST<br>ULTRA 809,000 ESTIMATED | – | – | 0 | – | – |
| o2 | 2026-10-02T10:02 | UNCHANGED | – | MAX+ 699,000 LIST<br>ULTRA 809,000 ESTIMATED | – | – | 0 | – | – |
| o3 | 2026-10-03T10:03 | UNCHANGED | – | MAX+ 699,000 LIST<br>ULTRA 809,000 ESTIMATED | – | – | 0 | – | – |
| o4 | 2026-10-04T10:04 | UNCHANGED | – | MAX+ 699,000 LIST<br>ULTRA 809,000 ESTIMATED | – | – | 0 | – | – |
| o5 | 2026-10-05T10:05 | UNCHANGED | – | MAX+ 699,000 LIST<br>ULTRA 809,000 ESTIMATED | – | – | 0 | – | – |
| o6 | 2026-10-06T10:06 | DETERMINISTIC | AMOUNTS | MAX+ 689,000 LIST<br>ULTRA 809,000 ESTIMATED | – | – | 0 | – | – |
| o7 | 2026-10-07T10:07 | UNCHANGED | – | MAX+ 689,000 LIST<br>ULTRA 809,000 ESTIMATED | – | – | 0 | – | – |
| o8 | 2026-10-08T10:08 | UNCHANGED | – | MAX+ 689,000 LIST<br>ULTRA 809,000 ESTIMATED | – | – | 0 | – | – |

## s13_missing_dates_stay_unknown — No stated end date: unknown stays unknown, year is never invented

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | AI_EXTRACTED | FIRST_SEEN | – | MAX+ 599,000 CAMPAIGN | – | 1 | – | – |
| o2 | 2026-10-06T11:00 | REVIEW | CONDITIONS | – | – | CONDITIONS_NOT_INTERPRETED,DATE_NOT_IN_EVIDENCE,UNCOVERED_AMOUNT | 1 | – | – |
| o3 | 2026-10-07T12:00 | AI_EXTRACTED | CONDITIONS | – | MAX+ 599,000 CAMPAIGN | – | 1 | – | – |

## s14_daily_budget_exhaustion — Daily call cap reached mid-day; change stays pending until reset

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | AI_EXTRACTED | FIRST_SEEN | – | MAX+ 699,000 LIST | – | 1 | – | – |
| o2 | 2026-10-05T12:00 | AI_EXTRACTED | AMOUNTS | – | MAX+ 689,000 LIST | – | 1 | – | – |
| o3 | 2026-10-05T14:00 | REVIEW | AMOUNTS | – | – | TOKEN_BUDGET_EXHAUSTED | 0 | – | – |
| o4 | 2026-10-06T10:00 | AI_EXTRACTED | AMOUNTS | – | MAX+ 679,000 LIST | – | 1 | – | – |

## s15_provider_outage_bounded_retries — Provider outage: bounded retries, then recovery

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | REVIEW | FIRST_SEEN | – | – | PROVIDER_FAILED | 3 | – | – |
| o2 | 2026-10-05T11:00 | AI_EXTRACTED | FIRST_SEEN | – | MAX+ 699,000 LIST | – | 1 | – | – |
| o3 | 2026-10-06T12:00 | UNCHANGED | – | – | MAX+ 699,000 LIST | – | 0 | hit | – |

## s16_ai_claim_p5_24h_reobservation — AI-read list price replaces the ledger; P5 confirms it 25h later with no new call

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | AI_EXTRACTED | FIRST_SEEN | – | MAX+ 679,000 LIST | – | 1 | – | MAX+ LIST 679,000: PENDING_REPLACEMENT |
| o2 | 2026-10-06T11:00 | UNCHANGED | – | – | MAX+ 679,000 LIST | – | 0 | hit | MAX+ LIST 679,000: CONFIRMED_REPLACEMENT |
| o3 | 2026-10-07T12:00 | AI_EXTRACTED | AMOUNTS | – | MAX+ 669,000 LIST | – | 1 | – | MAX+ LIST 669,000: PENDING_REPLACEMENT |

## s17_promo_label_after_amount — Promo label written after the amount must not become MSRP

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | REVIEW | FIRST_SEEN | – | – | PRICE_TYPE_CONFLICT,UNCOVERED_AMOUNT | 1 | – | – |
| o2 | 2026-10-06T11:00 | AI_EXTRACTED | FIRST_SEEN | – | MAX+ 599,000 CAMPAIGN | – | 1 | – | MAX+ CAMPAIGN 599,000: REVIEW |
| o3 | 2026-10-07T12:00 | UNCHANGED | – | – | MAX+ 599,000 CAMPAIGN | – | 0 | hit | MAX+ CAMPAIGN 599,000: REVIEW |

## s18_restricted_audience_after_amount — A restricted-audience price is not a general MSRP

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | REVIEW | FIRST_SEEN | – | – | PRICE_TYPE_UNSUPPORTED,UNCOVERED_AMOUNT | 1 | – | – |
| o2 | 2026-10-06T11:00 | REVIEW | FIRST_SEEN | – | – | PRICE_TYPE_UNSUPPORTED,UNCOVERED_AMOUNT | 1 | – | – |

## s19_swapped_trim_amount_pairs — Trims and amounts swapped inside one quoted row

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | REVIEW | FIRST_SEEN | – | – | FACT_NOT_BOUND,FACT_NOT_BOUND,UNCOVERED_AMOUNT | 1 | – | – |
| o2 | 2026-10-06T11:00 | AI_EXTRACTED | FIRST_SEEN | – | MAX+ 699,000 LIST<br>ULTRA 789,000 LIST | – | 1 | – | MAX+ LIST 699,000: NO_CHANGE<br>ULTRA LIST 789,000: NO_CHANGE |
| o3 | 2026-10-07T12:00 | UNCHANGED | – | – | MAX+ 699,000 LIST<br>ULTRA 789,000 LIST | – | 0 | hit | MAX+ LIST 699,000: NO_CHANGE<br>ULTRA LIST 789,000: NO_CHANGE |

## s20_other_models_price_attributed — Another model's price attributed to JAECOO 5 EV

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | REVIEW | FIRST_SEEN | – | ULTRA 809,000 LIST | FACT_NOT_BOUND,UNCOVERED_AMOUNT | 1 | – | ULTRA LIST 809,000: NO_CHANGE |
| o2 | 2026-10-06T11:00 | AI_EXTRACTED | FIRST_SEEN | – | ULTRA 809,000 LIST<br>MAX+ 709,000 LIST | – | 1 | – | ULTRA LIST 809,000: NO_CHANGE<br>MAX+ LIST 709,000: REVIEW |

## s21_eco_sticker_is_not_msrp — ECO-sticker price must never become an OEM MSRP (roadmap P-1)

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | REVIEW | FIRST_SEEN | – | – | PRICE_TYPE_CONFLICT,UNCOVERED_AMOUNT | 1 | – | – |
| o2 | 2026-10-06T11:00 | REVIEW | FIRST_SEEN | – | – | PRICE_TYPE_NOT_ALLOWED,UNCOVERED_AMOUNT | 1 | – | – |

## s22_dealer_price_is_not_oem_msrp — A dealer's own price must not become the OEM MSRP

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | REVIEW | FIRST_SEEN | – | – | PRICE_TYPE_CONFLICT,UNCOVERED_AMOUNT | 1 | – | – |
| o2 | 2026-10-06T11:00 | REVIEW | FIRST_SEEN | – | – | PRICE_TYPE_NOT_ALLOWED,UNCOVERED_AMOUNT | 1 | – | – |

## s23_missing_offer_is_not_zero — An offer vanishing from a page is not a price of zero or an expiry

role `PROMOTION` · evidence `RECONSTRUCTED_FROM_PILOT_NOTES` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | DETERMINISTIC | FIRST_SEEN | MAX+ 599,000 CAMPAIGN<br>MAX+ 699,000 LIST<br>ULTRA 699,000 CAMPAIGN<br>ULTRA 809,000 ESTIMATED | – | – | 0 | – | – |
| o2 | 2026-10-06T11:00 | DETERMINISTIC | AMOUNTS,CONDITIONS,DATES,LABELS | – | – | – | 0 | – | – |
| o3 | 2026-10-07T12:00 | UNCHANGED | – | – | – | – | 0 | – | – |

## s24_shared_model_row_fails_closed — A model named once for several prices cannot be bound to the second

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | REVIEW | FIRST_SEEN | – | MAX+ 699,000 LIST | FACT_NOT_BOUND,UNCOVERED_AMOUNT | 1 | – | – |
| o2 | 2026-10-06T11:00 | REVIEW | FIRST_SEEN | – | MAX+ 699,000 LIST | FACT_NOT_BOUND,UNCOVERED_AMOUNT | 1 | – | – |

## s25_neighbouring_wording_does_not_leak — A neighbour's promo / finance wording must not change an MSRP

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | AI_EXTRACTED | FIRST_SEEN | – | LONG RANGE MAX 679,000 LIST<br>MAX+ 599,000 CAMPAIGN<br>MAX+ 699,000 LIST<br>ULTRA 649,000 FINANCE | – | 1 | – | – |
| o2 | 2026-10-06T11:00 | UNCHANGED | – | – | LONG RANGE MAX 679,000 LIST<br>MAX+ 599,000 CAMPAIGN<br>MAX+ 699,000 LIST<br>ULTRA 649,000 FINANCE | – | 0 | hit | – |

## s26_bare_price_wording_is_unproven — Bare 'ราคา' is not affirmative MSRP evidence (owner policy item)

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | REVIEW | FIRST_SEEN | – | – | PRICE_TYPE_UNSUPPORTED,UNCOVERED_AMOUNT | 1 | – | – |
| o2 | 2026-10-06T11:00 | AI_EXTRACTED | FIRST_SEEN | – | MAX+ 699,000 LIST | – | 1 | – | – |

## s27_previous_price_is_not_current — A struck-through previous price must not become the list price

role `CURRENT_MODEL_PAGE` · evidence `SYNTHETIC_ADVERSARIAL` · labels `PROPOSED_PENDING_OWNER_REVIEW`

| obs | t | status | changes | rule | AI | review | calls | cache | P5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| o1 | 2026-10-05T10:00 | REVIEW | FIRST_SEEN | – | – | FACT_NOT_BOUND,PRICE_TYPE_UNSUPPORTED,UNCOVERED_AMOUNT | 1 | – | – |
| o2 | 2026-10-06T11:00 | REVIEW | FIRST_SEEN | – | – | PRICE_TYPE_UNSUPPORTED,UNCOVERED_AMOUNT | 1 | – | – |

