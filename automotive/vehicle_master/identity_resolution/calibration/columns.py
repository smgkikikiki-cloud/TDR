"""Meaning of every column of the three CSV outputs. `build` renders it as DATA_DICTIONARY.md; a test fails if a column has no entry."""
from __future__ import annotations

# (column, group, meaning). Groups: ice, lineage, legacy, v1, volume, sheet, owner.
COLUMNS: list[tuple[str, str, str]] = [
    # ---- sheet-only
    ("review_rank", "sheet", "1-based order of the row in the sheet (tier, then newest-24-month Ice units, then lifetime units)"),
    ("review_tier", "sheet", "the FIRST of the owner's seven priorities the row matches (1 legacy AUTO, 2 high-volume legacy PROPOSED, 3 suspicious known case, 4 material change under the common window, 5 PART_OF / COMPOSED_OF, 6 several viable candidates, 7 tail)"),
    ("review_tier_label", "sheet", "the tier's name"),
    ("review_tiers_matched", "sheet", "every tier the row matches, `;`-separated; the first is `review_tier`"),
    ("suspicious_cases", "sheet", "ids of the known suspicious cases the row belongs to (`dmax_vs_mux`, `ranger_granularity`, `hilux_granularity`, ...); see review.SUSPICIOUS_CASES for the source of each"),
    ("cumulative_unique_group_units_share", "sheet", "share of all 4,141,987 Ice units held by the distinct Ice groups from rank 1 down to this row; how much of the market is already covered"),
    ("question", "sheet", "the question the verdict answers; it is about the candidate on this row only"),
    ("legacy_r6_status", "legacy", "the first run's stored status for this pair (AUTO / PROPOSED); blank if the first run did not store this pair. NEVER an owner verdict"),
    ("legacy_r6_match_method", "legacy", "the first run's stored match method (SERIES / NAME / ADMIN)"),
    ("legacy_r6_row_id", "legacy", "`ice_model_crosswalk.id` of the stored row"),
    ("outcome_changed_vs_legacy", "sheet", "the group's AUTO-ness or existence of a decision differs between the first run and Contract v1 (reporting convention)"),
    ("other_candidates", "sheet", "the best other pairs of the same group (`id (name relation, series state, corr, ratio)`), to help name the right target"),
    # ---- owner
    ("owner_verdict", "owner", "BLANK. One of CORRECT_EQUIVALENT, CORRECT_PART_OF, CORRECT_COMPOSED_OF, WRONG_TARGET, NO_TDR_TARGET, INSUFFICIENT_EVIDENCE"),
    ("owner_link_type", "owner", "BLANK. The relationship the owner asserts: EQUIVALENT, PART_OF or COMPOSED_OF"),
    ("owner_canonical_model_id", "owner", "BLANK. The right TDR model (`a+b` for a COMPOSED_OF set) when the row's candidate is wrong or missing"),
    ("owner_notes", "owner", "BLANK. Free text"),
    # ---- Ice group
    ("model_group_id", "ice", "Ice `model_group_id` (market identity)"),
    ("ice_model_name", "ice", "Ice `model_name`, verbatim (not a key)"),
    ("ice_brand", "ice", "Ice brand, verbatim"),
    ("ice_identity_status", "ice", "adapter A4: `settled` (normal id), `provisional` (`...__provisional`), `unmapped_name` (`BRAND|MODEL`)"),
    ("ice_body", "ice", "Ice `body`, verbatim (blank for 649 of 1,200 groups)"),
    ("ice_segment", "ice", "Ice `segment`, verbatim"),
    ("ice_first_month", "ice", "first month (Gregorian) with an Ice row"),
    ("ice_last_month", "ice", "last month (Gregorian) with an Ice row"),
    ("ice_months_with_rows", "ice", "number of months with an Ice row"),
    ("ice_absent_in_coverage_months", "ice", "months inside the package coverage (2021-01 .. 2026-09) with no Ice row for the group: absent rows, written as null (Ice absent-row semantics are UNKNOWN)"),
    # ---- lineage
    ("lineage_roles", "lineage", "role of the group in Ice's `id_changes.csv`: OLD_/NEW_ x RENAME / MERGE / SPLIT"),
    ("lineage_events", "lineage", "the events as `TYPE:old>new share%`, `|`-separated"),
    ("lineage_ops", "lineage", "the structural operations the reference evaluator derived for the group (REDIRECT, QUARANTINE, NOOP, ...)"),
    ("lineage_quarantined", "lineage", "true when lineage withholds AUTO for the group (SPEC section 9.4)"),
    ("lineage_redirect_recorded", "lineage", "true when R6 phase 1 recorded a redirect for the group in `ice_model_group_redirects`"),
    # ---- group-level v1
    ("v1_group_outcome", "v1", "Contract v1 outcome for the whole Ice group in a fresh dry-run evaluation: AUTO, PROPOSE, AMBIGUOUS, STRUCTURAL_REVIEW, NO_CANDIDATE, INSUFFICIENT_DATA, ..."),
    ("v1_group_primary_code", "v1", "the primary reason code of that outcome"),
    ("v1_group_proposed_status", "v1", "AUTO / PROPOSED / NONE: what the engine would propose (advisory: binding is false)"),
    ("v1_group_link_type", "v1", "link type of the group's decision (blank when none)"),
    ("v1_group_targets", "v1", "target ids of the group's decision (`a+b` for a link set)"),
    ("v1_group_codes", "v1", "every reason code of the decision as `CODE:role`"),
    ("v1_group_review_queue", "v1", "review queue the decision routes to (none, crosswalk_review, discovery, structure_review)"),
    ("v1_pool_size", "v1", "number of TDR targets in the candidate pool (brand relation allowed, not deleted, status in pool)"),
    ("v1_proposable_candidates", "v1", "candidates that survive exclusions and have a strong series, a candidate name relation or a PART_OF reading"),
    ("v1_bundle_pool_size", "v1", "when no single candidate is strong, the number of pool members eligible for link-set enumeration (before the max_pool_for_enumeration cap); blank when not enumerated"),
    ("plausible_candidates", "v1", "viable candidates counting both methods: v1-proposable, or a legacy strong series, or a legacy name score >= 0.8"),
    ("legacy_candidates_evaluated", "legacy", "TDR models of the same brand (legacy rule) the first run evaluated for this group"),
    ("legacy_candidates_proposed", "legacy", "of those, how many cleared the legacy decision rule (strong series, or name >= 0.35)"),
    ("legacy_chosen", "legacy", "the candidate the first run stored for the group (blank: none)"),
    ("legacy_stored_rows", "legacy", "number of rows stored for the group (a STRUCTURE proposal counts)"),
    # ---- the pair
    ("candidate_canonical_model_id", "pair", "candidate TDR `canonical_model_id` (`a+b` for a COMPOSED_OF set; blank on a no-candidate row)"),
    ("candidate_target_count", "pair", "1, or the size of the link set"),
    ("tdr_brand", "pair", "TDR brand name"),
    ("tdr_model_name", "pair", "TDR model name(s)"),
    ("tdr_status", "pair", "TDR `vehicle_models.status` (CURRENT / HISTORICAL)"),
    ("tdr_body_type", "pair", "TDR `body_type`"),
    ("candidate_origin", "pair", "why the pair is here: LEGACY_STORED (a stored first-run row), LEGACY_CANDIDATE (the legacy rules proposed it), V1_PRIMARY / V1_ALTERNATIVE (Contract v1's decision), V1_POOL (relevant in the v1 pool); NONE on a no-candidate row"),
    # ---- legacy evidence
    ("legacy_run_selected", "legacy", "true when this pair is the matcher row the first run stored for the group"),
    ("legacy_row_id", "legacy", "`ice_model_crosswalk.id` (also set for the STRUCTURE proposal row)"),
    ("legacy_status", "legacy", "stored status (AUTO / PROPOSED)"),
    ("legacy_match_method", "legacy", "stored match method (SERIES / NAME / ADMIN)"),
    ("legacy_stored_score", "legacy", "stored `score` (correlation for SERIES, name score for NAME)"),
    ("legacy_stored_reason", "legacy", "stored `reason`, verbatim"),
    ("legacy_stored_fingerprint", "legacy", "stored sha256 `decision_fingerprint`"),
    ("legacy_stored_created_at", "legacy", "when the first run wrote the row (UTC)"),
    ("legacy_in_candidate_pool", "legacy", "true when the legacy brand rule would have evaluated this model for this group"),
    ("legacy_would_decide", "legacy", "what the legacy rule gives this pair on its own: `AUTO/SERIES`, `PROPOSED/SERIES`, `PROPOSED/NAME`, or blank (no candidate)"),
    ("legacy_correlation", "legacy", "Pearson correlation over the legacy window (TDR months with no row counted as 0); blank when undefined"),
    ("legacy_ratio", "legacy", "TDR units / Ice units over the legacy window"),
    ("legacy_name_score", "legacy", "legacy name similarity (difflib ratio on the normalised names); blank for a link set"),
    ("legacy_series_class", "legacy", "STRONG (corr >= 0.98 and ratio 0.9..1.1), WEAK, or UNDEFINED (no correlation or ratio)"),
    ("legacy_window_first", "legacy", "first month of the legacy window (Gregorian): the Ice group's 24th newest month WITH a row"),
    ("legacy_window_last", "legacy", "last month of the legacy window"),
    ("legacy_window_periods", "legacy", "the exact months the legacy run compared, `;`-separated (Gregorian), in order; a set's list is the same window"),
    ("legacy_window_months", "legacy", "months in the legacy window (24, or fewer for a young group)"),
    ("legacy_window_calendar_span_months", "legacy", "calendar months from first to last; more than `legacy_window_months` when the group has holes"),
    ("legacy_window_tdr_zero_filled_months", "legacy", "window months the TDR side had no row for and the legacy code turned into 0"),
    ("legacy_window_tdr_zero_filled_list", "legacy", "those months (2026-09 is always among them when the window reaches it: TDR registrations end at 2026-08)"),
    # ---- v1 evidence
    ("v1_link_candidate", "v1", "link type the reference evaluator reads for this pair: EQUIVALENT, PART_OF or COMPOSED_OF"),
    ("v1_brand_relation", "v1", "EXACT, ALIAS_SAME, ALIAS_RELABEL, ALIAS_RELATED, MISMATCH or UNKNOWN (SPEC section 5.1)"),
    ("v1_name_relation", "v1", "EQUAL, EQUAL_VIA_MODEL_ALIAS, EQUAL_VIA_TOKEN_EQUIV, FUZZY, SUBJECT_COARSER, SUBJECT_FINER, SIBLING, CONTRADICTION, UNAVAILABLE (SPEC section 5.3)"),
    ("v1_name_score", "v1", "token Dice score of the name relation (quantized), blank when unavailable"),
    ("v1_name_subject_tokens", "v1", "the Ice name's identity tokens after brand-prefix and generic-token removal"),
    ("v1_name_target_tokens", "v1", "the TDR name's identity tokens"),
    ("v1_series_state", "v1", "STRONG, WEAK or UNAVAILABLE over the common observation window"),
    ("v1_series_unavailable_reason", "v1", "why the series is UNAVAILABLE (SER_NO_COMMON_WINDOW, SER_OVERLAP_BELOW_PROPOSE_MIN, SER_VOLUME_BELOW_PROPOSE_MIN, SER_ZERO_VARIANCE, SER_ZERO_TOTAL)"),
    ("v1_correlation", "v1", "Pearson correlation over the common window, quantized to 6 places; blank when unavailable"),
    ("v1_ratio", "v1", "TDR units / Ice units over the common window (quantized)"),
    ("v1_monthly_fit_share", "v1", "share of common months where |TDR - Ice| <= max(3 units, 25 % of Ice) (quantized)"),
    ("v1_common_months", "v1", "months both sources observe inside the window"),
    ("v1_joint_nonzero_months", "v1", "common months where both sides are above zero"),
    ("v1_subject_units", "v1", "Ice units in the common window"),
    ("v1_target_units", "v1", "TDR units in the common window"),
    ("v1_window_first", "v1", "first month of the common window"),
    ("v1_window_last", "v1", "last month of the common window (the newest month both sources observe)"),
    ("v1_window_periods", "v1", "the exact months v1 compared, `;`-separated; blank when the series is unavailable before a window exists"),
    ("v1_semantics_gap_months", "v1", "unconfirmed-gap months (SPEC 6.2a): months of the 24-month window, inside both coverages, where a side with unconfirmed absent-row semantics has no row"),
    ("v1_gap_months_both_absent", "v1", "of those, months where both sources lack the row"),
    ("v1_gap_months_subject_only_absent", "v1", "of those, months where only Ice lacks the row"),
    ("v1_gap_months_target_only_absent", "v1", "of those, months where only TDR lacks the row"),
    ("v1_excluded_unobserved_subject", "v1", "months excluded from the comparison because Ice has no row (anywhere in coverage)"),
    ("v1_excluded_unobserved_target", "v1", "months excluded because TDR has no row (and Ice has)"),
    ("v1_excluded_outside_common_coverage", "v1", "months outside the intersection of the two coverages (for example 2026-09)"),
    ("v1_excluded_inactive_edges", "v1", "leading / trailing months where both sides are 0"),
    ("v1_excluded_outside_max_window", "v1", "common months older than the 24-month cap"),
    ("v1_lifecycle", "v1", "WITHIN, PARTIAL, DISJOINT or UNKNOWN: the share of Ice units that fall inside the TDR generations' lifetimes"),
    ("v1_lifecycle_share", "v1", "that share (quantized); blank when unknown"),
    ("v1_body_relation", "v1", "MATCH, MISMATCH or UNKNOWN between Ice `body` and TDR `body_type`"),
    ("v1_target_status", "v1", "CURRENT, HISTORICAL or UNVERIFIED (the worst member of a set)"),
    ("v1_auto_eligible", "v1", "true when no blocking code stands in the way of AUTO for this candidate"),
    ("v1_proposable", "v1", "true when the candidate survives exclusions and has a strong series, a candidate name relation or a PART_OF reading"),
    ("v1_rank_among_proposable", "v1", "order among the group's proposable candidates (series state, then name relation, then id)"),
    ("v1_is_group_primary", "v1", "true when this pair is the group's v1 decision"),
    ("v1_is_group_alternative", "v1", "true when it is one of the tied alternatives of an AMBIGUOUS decision"),
    ("v1_evaluated_standalone", "v1", "true when the pair was outside the v1 pool and was evaluated on its own"),
    ("v1_codes_supporting", "v1", "reason codes that support the pair (brand, name equal, SER_STRONG, GRAN_*)"),
    ("v1_codes_blocking", "v1", "reason codes that block AUTO for this candidate"),
    ("v1_codes_excluded", "v1", "exclusion reasons (the pair cannot be a candidate): NAME_CONTRADICTION, NAME_SIBLING_VARIANT, SERIES_DECISIVELY_WRONG, GEN_LIFECYCLE_DISJOINT, ..."),
    ("v1_codes_info", "v1", "informational codes (SER_UNOBSERVED_NOT_ZERO, ATTR_BODY_UNKNOWN, ...)"),
    # ---- comparison of the two windows
    ("series_material_change", "compare", "true when the series evidence differs materially between the legacy and the v1 window (reporting convention, see the report)"),
    ("series_material_change_why", "compare", "STRONG_FLIPS, AVAILABILITY, CORRELATION (|delta| >= 0.05), RATIO (>= 10 %)"),
    ("delta_correlation_v1_minus_legacy", "compare", "v1 correlation minus legacy correlation, when both exist"),
    # ---- volumes
    ("ice_lifetime_units", "volume", "all Ice units of the group, 2021-01 .. 2026-09. Prioritisation only, never evidence"),
    ("ice_units_last12m", "volume", "Ice units 2025-09 .. 2026-08"),
    ("ice_units_last24m", "volume", "Ice units 2024-09 .. 2026-08"),
    ("tdr_lifetime_units", "volume", "TDR units of the candidate (sum over a set), 2021-01 .. 2026-08"),
    ("tdr_units_last12m", "volume", "TDR units 2025-09 .. 2026-08"),
    ("tdr_units_last24m", "volume", "TDR units 2024-09 .. 2026-08"),
    ("tdr_first_month", "volume", "first month with a TDR row for the candidate"),
    ("tdr_last_month", "volume", "last month with a TDR row for the candidate"),
    # ---- sharing
    ("legacy_groups_claiming_this_target", "pair", "Ice groups whose stored first-run row names this TDR model (cardinality context for PART_OF)"),
    ("v1_groups_claiming_this_target", "pair", "Ice groups whose v1 decision names this TDR model"),
]

DOC = {c: (g, m) for c, g, m in COLUMNS}
GROUP_TITLES = {"sheet": "Sheet only", "owner": "Owner columns (blank)", "ice": "Ice group", "lineage": "Lineage", "legacy": "Legacy first run (R6, 2026-10-10)",
                "pair": "The candidate pair", "v1": "Contract v1 (dry run, binding: false)", "compare": "Legacy window vs v1 window", "volume": "Volumes (prioritisation only)"}


def render() -> str:
    out = ["# Data dictionary — R6 calibration outputs", "",
           "Columns of `r6_calibration_dataset.csv`, `r6_calibration_groups.csv` and `r6_owner_review.csv`. "
           "`legacy_*` is the first run (replayed and verified against the stored rows); `v1_*` is Contract v1 as a dry run; `owner_*` is blank. "
           "Periods are Gregorian `YYYY-MM` (the Ice package's Buddhist years are converted once, by the adapter). A blank cell is `null`, never 0. "
           "Generated from `columns.py`.", ""]
    for g in ("sheet", "owner", "ice", "lineage", "legacy", "pair", "v1", "compare", "volume"):
        rows = [(c, m) for c, gg, m in COLUMNS if gg == g]
        if not rows:
            continue
        out += [f"## {GROUP_TITLES[g]}", "", "| column | meaning |", "|---|---|"]
        out += [f"| `{c}` | {m.replace('|', chr(92) + '|')} |" for c, m in rows]
        out.append("")
    return "\n".join(out) + "\n"
