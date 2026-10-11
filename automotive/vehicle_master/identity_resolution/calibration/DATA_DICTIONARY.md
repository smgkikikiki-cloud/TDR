# Data dictionary — R6 calibration outputs

Columns of `r6_calibration_dataset.csv`, `r6_calibration_groups.csv` and `r6_owner_review.csv`. `legacy_*` is the first run (replayed and verified against the stored rows); `v1_*` is Contract v1 as a dry run; `owner_*` is blank. Periods are Gregorian `YYYY-MM` (the Ice package's Buddhist years are converted once, by the adapter). A blank cell is `null`, never 0. Generated from `columns.py`.

## Sheet only

| column | meaning |
|---|---|
| `review_rank` | 1-based order of the row in the sheet (tier, then newest-24-month Ice units, then lifetime units) |
| `review_tier` | the FIRST of the owner's seven priorities the row matches (1 legacy AUTO, 2 high-volume legacy PROPOSED, 3 suspicious known case, 4 material change under the common window, 5 PART_OF / COMPOSED_OF, 6 several viable candidates, 7 tail) |
| `review_tier_label` | the tier's name |
| `review_tiers_matched` | every tier the row matches, `;`-separated; the first is `review_tier` |
| `suspicious_cases` | ids of the known suspicious cases the row belongs to (`dmax_vs_mux`, `ranger_granularity`, `hilux_granularity`, ...); see review.SUSPICIOUS_CASES for the source of each |
| `cumulative_unique_group_units_share` | share of all 4,141,987 Ice units held by the distinct Ice groups from rank 1 down to this row; how much of the market is already covered |
| `question` | the question the verdict answers; it is about the candidate on this row only |
| `outcome_changed_vs_legacy` | the group's AUTO-ness or existence of a decision differs between the first run and Contract v1 (reporting convention) |
| `other_candidates` | the best other pairs of the same group (`id (name relation, series state, corr, ratio)`), to help name the right target |

## Owner columns (blank)

| column | meaning |
|---|---|
| `owner_verdict` | BLANK. One of CORRECT_EQUIVALENT, CORRECT_PART_OF, CORRECT_COMPOSED_OF, WRONG_TARGET, NO_TDR_TARGET, INSUFFICIENT_EVIDENCE |
| `owner_link_type` | BLANK. The relationship the owner asserts: EQUIVALENT, PART_OF or COMPOSED_OF |
| `owner_canonical_model_id` | BLANK. The right TDR model (`a+b` for a COMPOSED_OF set) when the row's candidate is wrong or missing |
| `owner_notes` | BLANK. Free text |

## Ice group

| column | meaning |
|---|---|
| `model_group_id` | Ice `model_group_id` (market identity) |
| `ice_model_name` | Ice `model_name`, verbatim (not a key) |
| `ice_brand` | Ice brand, verbatim |
| `ice_identity_status` | adapter A4: `settled` (normal id), `provisional` (`...__provisional`), `unmapped_name` (`BRAND\|MODEL`) |
| `ice_body` | Ice `body`, verbatim (blank for 649 of 1,200 groups) |
| `ice_segment` | Ice `segment`, verbatim |
| `ice_first_month` | first month (Gregorian) with an Ice row |
| `ice_last_month` | last month (Gregorian) with an Ice row |
| `ice_months_with_rows` | number of months with an Ice row |
| `ice_absent_in_coverage_months` | months inside the package coverage (2021-01 .. 2026-09) with no Ice row for the group: absent rows, written as null (Ice absent-row semantics are UNKNOWN) |

## Lineage

| column | meaning |
|---|---|
| `lineage_roles` | role of the group in Ice's `id_changes.csv`: OLD_/NEW_ x RENAME / MERGE / SPLIT |
| `lineage_events` | the events as `TYPE:old>new share%`, `\|`-separated |
| `lineage_ops` | the structural operations the reference evaluator derived for the group (REDIRECT, QUARANTINE, NOOP, ...) |
| `lineage_quarantined` | true when lineage withholds AUTO for the group (SPEC section 9.4) |
| `lineage_redirect_recorded` | true when R6 phase 1 recorded a redirect for the group in `ice_model_group_redirects` |

## Legacy first run (R6, 2026-10-10)

| column | meaning |
|---|---|
| `legacy_r6_status` | the first run's stored status for this pair (AUTO / PROPOSED); blank if the first run did not store this pair. NEVER an owner verdict |
| `legacy_r6_match_method` | the first run's stored match method (SERIES / NAME / ADMIN) |
| `legacy_r6_row_id` | `ice_model_crosswalk.id` of the stored row |
| `legacy_candidates_evaluated` | TDR models of the same brand (legacy rule) the first run evaluated for this group |
| `legacy_candidates_proposed` | of those, how many cleared the legacy decision rule (strong series, or name >= 0.35) |
| `legacy_chosen` | the candidate the first run stored for the group (blank: none) |
| `legacy_stored_rows` | number of rows stored for the group (a STRUCTURE proposal counts) |
| `legacy_run_selected` | true when this pair is the matcher row the first run stored for the group |
| `legacy_row_id` | `ice_model_crosswalk.id` (also set for the STRUCTURE proposal row) |
| `legacy_status` | stored status (AUTO / PROPOSED) |
| `legacy_match_method` | stored match method (SERIES / NAME / ADMIN) |
| `legacy_stored_score` | stored `score` (correlation for SERIES, name score for NAME) |
| `legacy_stored_reason` | stored `reason`, verbatim |
| `legacy_stored_fingerprint` | stored sha256 `decision_fingerprint` |
| `legacy_stored_created_at` | when the first run wrote the row (UTC) |
| `legacy_in_candidate_pool` | true when the legacy brand rule would have evaluated this model for this group |
| `legacy_would_decide` | what the legacy rule gives this pair on its own: `AUTO/SERIES`, `PROPOSED/SERIES`, `PROPOSED/NAME`, or blank (no candidate) |
| `legacy_correlation` | Pearson correlation over the legacy window (TDR months with no row counted as 0); blank when undefined |
| `legacy_ratio` | TDR units / Ice units over the legacy window |
| `legacy_name_score` | legacy name similarity (difflib ratio on the normalised names); blank for a link set |
| `legacy_series_class` | STRONG (corr >= 0.98 and ratio 0.9..1.1), WEAK, or UNDEFINED (no correlation or ratio) |
| `legacy_window_first` | first month of the legacy window (Gregorian): the Ice group's 24th newest month WITH a row |
| `legacy_window_last` | last month of the legacy window |
| `legacy_window_periods` | the exact months the legacy run compared, `;`-separated (Gregorian), in order; a set's list is the same window |
| `legacy_window_months` | months in the legacy window (24, or fewer for a young group) |
| `legacy_window_calendar_span_months` | calendar months from first to last; more than `legacy_window_months` when the group has holes |
| `legacy_window_tdr_zero_filled_months` | window months the TDR side had no row for and the legacy code turned into 0 |
| `legacy_window_tdr_zero_filled_list` | those months (2026-09 is always among them when the window reaches it: TDR registrations end at 2026-08) |

## The candidate pair

| column | meaning |
|---|---|
| `candidate_canonical_model_id` | candidate TDR `canonical_model_id` (`a+b` for a COMPOSED_OF set; blank on a no-candidate row) |
| `candidate_target_count` | 1, or the size of the link set |
| `tdr_brand` | TDR brand name |
| `tdr_model_name` | TDR model name(s) |
| `tdr_status` | TDR `vehicle_models.status` (CURRENT / HISTORICAL) |
| `tdr_body_type` | TDR `body_type` |
| `candidate_origin` | why the pair is here: LEGACY_STORED (a stored first-run row), LEGACY_CANDIDATE (the legacy rules proposed it), V1_PRIMARY / V1_ALTERNATIVE (Contract v1's decision), V1_POOL (relevant in the v1 pool); NONE on a no-candidate row |
| `legacy_groups_claiming_this_target` | Ice groups whose stored first-run row names this TDR model (cardinality context for PART_OF) |
| `v1_groups_claiming_this_target` | Ice groups whose v1 decision names this TDR model |

## Contract v1 (dry run, binding: false)

| column | meaning |
|---|---|
| `v1_group_outcome` | Contract v1 outcome for the whole Ice group in a fresh dry-run evaluation: AUTO, PROPOSE, AMBIGUOUS, STRUCTURAL_REVIEW, NO_CANDIDATE, INSUFFICIENT_DATA, ... |
| `v1_group_primary_code` | the primary reason code of that outcome |
| `v1_group_proposed_status` | AUTO / PROPOSED / NONE: what the engine would propose (advisory: binding is false) |
| `v1_group_link_type` | link type of the group's decision (blank when none) |
| `v1_group_targets` | target ids of the group's decision (`a+b` for a link set) |
| `v1_group_codes` | every reason code of the decision as `CODE:role` |
| `v1_group_review_queue` | review queue the decision routes to (none, crosswalk_review, discovery, structure_review) |
| `v1_pool_size` | number of TDR targets in the candidate pool (brand relation allowed, not deleted, status in pool) |
| `v1_proposable_candidates` | candidates that survive exclusions and have a strong series, a candidate name relation or a PART_OF reading |
| `v1_bundle_pool_size` | when no single candidate is strong, the number of pool members eligible for link-set enumeration (before the max_pool_for_enumeration cap); blank when not enumerated |
| `plausible_candidates` | viable candidates counting both methods: v1-proposable, or a legacy strong series, or a legacy name score >= 0.8 |
| `v1_link_candidate` | link type the reference evaluator reads for this pair: EQUIVALENT, PART_OF or COMPOSED_OF |
| `v1_brand_relation` | EXACT, ALIAS_SAME, ALIAS_RELABEL, ALIAS_RELATED, MISMATCH or UNKNOWN (SPEC section 5.1) |
| `v1_name_relation` | EQUAL, EQUAL_VIA_MODEL_ALIAS, EQUAL_VIA_TOKEN_EQUIV, FUZZY, SUBJECT_COARSER, SUBJECT_FINER, SIBLING, CONTRADICTION, UNAVAILABLE (SPEC section 5.3) |
| `v1_name_score` | token Dice score of the name relation (quantized), blank when unavailable |
| `v1_name_subject_tokens` | the Ice name's identity tokens after brand-prefix and generic-token removal |
| `v1_name_target_tokens` | the TDR name's identity tokens |
| `v1_series_state` | STRONG, WEAK or UNAVAILABLE over the common observation window |
| `v1_series_unavailable_reason` | why the series is UNAVAILABLE (SER_NO_COMMON_WINDOW, SER_OVERLAP_BELOW_PROPOSE_MIN, SER_VOLUME_BELOW_PROPOSE_MIN, SER_ZERO_VARIANCE, SER_ZERO_TOTAL) |
| `v1_correlation` | Pearson correlation over the common window, quantized to 6 places; blank when unavailable |
| `v1_ratio` | TDR units / Ice units over the common window (quantized) |
| `v1_monthly_fit_share` | share of common months where \|TDR - Ice\| <= max(3 units, 25 % of Ice) (quantized) |
| `v1_common_months` | months both sources observe inside the window |
| `v1_joint_nonzero_months` | common months where both sides are above zero |
| `v1_subject_units` | Ice units in the common window |
| `v1_target_units` | TDR units in the common window |
| `v1_window_first` | first month of the common window |
| `v1_window_last` | last month of the common window (the newest month both sources observe) |
| `v1_window_periods` | the exact months v1 compared, `;`-separated; blank when the series is unavailable before a window exists |
| `v1_semantics_gap_months` | unconfirmed-gap months (SPEC 6.2a): months of the 24-month window, inside both coverages, where a side with unconfirmed absent-row semantics has no row |
| `v1_gap_months_both_absent` | of those, months where both sources lack the row |
| `v1_gap_months_subject_only_absent` | of those, months where only Ice lacks the row |
| `v1_gap_months_target_only_absent` | of those, months where only TDR lacks the row |
| `v1_excluded_unobserved_subject` | months excluded from the comparison because Ice has no row (anywhere in coverage) |
| `v1_excluded_unobserved_target` | months excluded because TDR has no row (and Ice has) |
| `v1_excluded_outside_common_coverage` | months outside the intersection of the two coverages (for example 2026-09) |
| `v1_excluded_inactive_edges` | leading / trailing months where both sides are 0 |
| `v1_excluded_outside_max_window` | common months older than the 24-month cap |
| `v1_lifecycle` | WITHIN, PARTIAL, DISJOINT or UNKNOWN: the share of Ice units that fall inside the TDR generations' lifetimes |
| `v1_lifecycle_share` | that share (quantized); blank when unknown |
| `v1_body_relation` | MATCH, MISMATCH or UNKNOWN between Ice `body` and TDR `body_type` |
| `v1_target_status` | CURRENT, HISTORICAL or UNVERIFIED (the worst member of a set) |
| `v1_auto_eligible` | true when no blocking code stands in the way of AUTO for this candidate |
| `v1_proposable` | true when the candidate survives exclusions and has a strong series, a candidate name relation or a PART_OF reading |
| `v1_rank_among_proposable` | order among the group's proposable candidates (series state, then name relation, then id) |
| `v1_is_group_primary` | true when this pair is the group's v1 decision |
| `v1_is_group_alternative` | true when it is one of the tied alternatives of an AMBIGUOUS decision |
| `v1_evaluated_standalone` | true when the pair was outside the v1 pool and was evaluated on its own |
| `v1_codes_supporting` | reason codes that support the pair (brand, name equal, SER_STRONG, GRAN_*) |
| `v1_codes_blocking` | reason codes that block AUTO for this candidate |
| `v1_codes_excluded` | exclusion reasons (the pair cannot be a candidate): NAME_CONTRADICTION, NAME_SIBLING_VARIANT, SERIES_DECISIVELY_WRONG, GEN_LIFECYCLE_DISJOINT, ... |
| `v1_codes_info` | informational codes (SER_UNOBSERVED_NOT_ZERO, ATTR_BODY_UNKNOWN, ...) |

## Legacy window vs v1 window

| column | meaning |
|---|---|
| `series_material_change` | true when the series evidence differs materially between the legacy and the v1 window (reporting convention, see the report) |
| `series_material_change_why` | STRONG_FLIPS, AVAILABILITY, CORRELATION (\|delta\| >= 0.05), RATIO (>= 10 %) |
| `delta_correlation_v1_minus_legacy` | v1 correlation minus legacy correlation, when both exist |

## Volumes (prioritisation only)

| column | meaning |
|---|---|
| `ice_lifetime_units` | all Ice units of the group, 2021-01 .. 2026-09. Prioritisation only, never evidence |
| `ice_units_last12m` | Ice units 2025-09 .. 2026-08 |
| `ice_units_last24m` | Ice units 2024-09 .. 2026-08 |
| `tdr_lifetime_units` | TDR units of the candidate (sum over a set), 2021-01 .. 2026-08 |
| `tdr_units_last12m` | TDR units 2025-09 .. 2026-08 |
| `tdr_units_last24m` | TDR units 2024-09 .. 2026-08 |
| `tdr_first_month` | first month with a TDR row for the candidate |
| `tdr_last_month` | last month with a TDR row for the candidate |

