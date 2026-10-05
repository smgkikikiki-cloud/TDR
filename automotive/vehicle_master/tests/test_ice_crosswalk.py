"""Pure-function tests for vehreg/ice_crosswalk.py (Market Track M3).

Every test here uses synthetic fixtures -- no real Ice Full Package has been imported
(docs/WORK_STATE.md, M2 state), so there is no real reg_trend/registrations data to test
against. See docs/vehicle-db/VEHICLE_DB_V3.md §14.2 for the rules each test name cites.
"""
from __future__ import annotations

from vehreg import ice_crosswalk as xwalk


def _constant_strong_series(n: int = 24, scale: float = 1.0) -> tuple[list[float], list[float]]:
    ice = [100.0 + i for i in range(n)]
    legacy = [(100.0 + i) * scale for i in range(n)]
    return ice, legacy


# ---------------------------------------------------------------------------
# §14.2 acceptance table
# ---------------------------------------------------------------------------

def test_strong_series_and_high_name_similarity_is_auto():
    ice, legacy = _constant_strong_series()
    series = xwalk.evaluate_series(ice, legacy)
    assert series.strong is True
    decision = xwalk.decide_match(series=series, name_score=0.95)
    assert decision is not None
    assert decision.status == "AUTO"
    assert decision.match_method == "SERIES"


def test_high_name_score_but_weak_series_is_proposed_never_auto():
    # Totally uncorrelated series (weak/no relationship).
    ice = [100.0, 50.0, 200.0, 10.0, 80.0]
    legacy = [5.0, 90.0, 3.0, 150.0, 20.0]
    series = xwalk.evaluate_series(ice, legacy)
    assert series.strong is False
    decision = xwalk.decide_match(series=series, name_score=0.97)
    assert decision is not None
    assert decision.status == "PROPOSED"
    assert decision.match_method == "NAME"


def test_strong_series_but_low_name_similarity_is_proposed():
    ice, legacy = _constant_strong_series()
    series = xwalk.evaluate_series(ice, legacy)
    assert series.strong is True
    decision = xwalk.decide_match(series=series, name_score=0.2)
    assert decision is not None
    assert decision.status == "PROPOSED"
    assert decision.match_method == "SERIES"


def test_no_candidate_at_all_returns_none():
    ice = [100.0, 50.0, 200.0, 10.0, 80.0]
    legacy = [5.0, 90.0, 3.0, 150.0, 20.0]
    series = xwalk.evaluate_series(ice, legacy)
    decision = xwalk.decide_match(series=series, name_score=0.1)
    assert decision is None


def test_series_strong_requires_both_correlation_and_ratio():
    # Perfectly correlated but the legacy side is 3x the Ice side -- ratio out of range.
    ice = [100.0 + i for i in range(24)]
    legacy = [(100.0 + i) * 3 for i in range(24)]
    series = xwalk.evaluate_series(ice, legacy)
    assert series.correlation is not None and series.correlation > 0.999
    assert series.strong is False


def test_pearson_correlation_is_none_for_zero_variance_or_too_few_points():
    assert xwalk.pearson_correlation([1.0], [1.0]) is None
    assert xwalk.pearson_correlation([5.0, 5.0, 5.0], [1.0, 2.0, 3.0]) is None


def test_total_ratio_is_none_when_ice_total_is_zero():
    assert xwalk.total_ratio([0.0, 0.0], [10.0, 20.0]) is None


# ---------------------------------------------------------------------------
# Known false-match traps (§14.2 "Known traps")
# ---------------------------------------------------------------------------

def test_bmw_3_does_not_auto_match_bmw_x3_from_name_alone():
    name_a = xwalk.normalize_model_name("BMW 3 Series", "BMW")
    name_b = xwalk.normalize_model_name("BMW X3", "BMW")
    score = xwalk.name_similarity(name_a, name_b)
    assert score < xwalk.NAME_AUTO_THRESHOLD
    # Even granting a generous (but not strong) series reading, this must never be AUTO.
    weak_series = xwalk.evaluate_series([10.0, 20.0, 15.0], [12.0, 18.0, 14.0])
    decision = xwalk.decide_match(series=weak_series, name_score=score)
    assert decision is None or decision.status != "AUTO"


def test_deepal_and_changan_normalize_to_the_same_alias_group():
    alias_map = {"deepal": "deepal_changan", "changan": "deepal_changan"}
    assert xwalk.normalize_brand("Deepal", alias_map) == xwalk.normalize_brand("Changan", alias_map)
    assert xwalk.normalize_brand("Deepal", alias_map) == "deepal_changan"


def test_mg_maxus_and_maxus_normalize_to_the_same_alias_group():
    alias_map = {"mg maxus": "maxus_mifa", "maxus": "maxus_mifa"}
    assert xwalk.normalize_brand("MG Maxus", alias_map) == xwalk.normalize_brand("MAXUS", alias_map)
    assert xwalk.normalize_brand("  mg maxus  ", alias_map) == "maxus_mifa"


def test_normalize_brand_without_an_alias_entry_is_just_lowercased_and_trimmed():
    assert xwalk.normalize_brand("Toyota", {}) == "toyota"


# ---------------------------------------------------------------------------
# Maxus/Mifa model-name alias (§14.2 "MG Maxus 7/9 <-> MAXUS Mifa 7/9" -- the
# brand alias alone does not fix this, since the *model names* don't resemble
# each other textually even once brand is accounted for)
# ---------------------------------------------------------------------------

def test_maxus_7_aliases_to_mifa_7_within_the_maxus_mifa_group():
    assert xwalk.apply_model_name_alias("7", "maxus_mifa") == "mifa 7"


def test_maxus_9_aliases_to_mifa_9_within_the_maxus_mifa_group():
    assert xwalk.apply_model_name_alias("9", "maxus_mifa") == "mifa 9"


def test_an_already_aliased_name_passes_through_unchanged():
    assert xwalk.apply_model_name_alias("mifa 7", "maxus_mifa") == "mifa 7"


def test_model_name_alias_is_scoped_to_its_own_brand_group_only():
    # "7" means nothing special outside the maxus_mifa alias_group -- this must
    # never become a generic fuzzy rule that could merge unrelated models.
    assert xwalk.apply_model_name_alias("7", "toyota") == "7"
    assert xwalk.apply_model_name_alias("7", "") == "7"


def test_maxus_7_and_mifa_7_become_name_similar_once_aliased():
    ice_name = xwalk.apply_model_name_alias(xwalk.normalize_model_name("7", "MG Maxus"), "maxus_mifa")
    tdr_name = xwalk.apply_model_name_alias(xwalk.normalize_model_name("MAXUS Mifa 7", "MAXUS"), "maxus_mifa")
    assert xwalk.name_similarity(ice_name, tdr_name) == 1.0


def test_maxus_7_cannot_auto_match_mifa_9_even_though_the_short_strings_look_similar():
    # "mifa 7" vs "mifa 9" differ by one digit in a six-character string, so raw
    # name_similarity alone cannot reliably tell them apart (same situation as the
    # bmw_3/bmw-x3 trap) -- it is the *series* requirement in decide_match that must
    # block this, exactly as it does for that trap, not the name score by itself.
    ice_name = xwalk.apply_model_name_alias(xwalk.normalize_model_name("7", "MG Maxus"), "maxus_mifa")
    tdr_name = xwalk.apply_model_name_alias(xwalk.normalize_model_name("MAXUS Mifa 9", "MAXUS"), "maxus_mifa")
    name_score = xwalk.name_similarity(ice_name, tdr_name)
    weak_series = xwalk.evaluate_series([10.0, 20.0, 15.0], [12.0, 3.0, 40.0])
    decision = xwalk.decide_match(series=weak_series, name_score=name_score)
    assert decision is None or decision.status != "AUTO"


# ---------------------------------------------------------------------------
# decision_rank (§14.2 signal priority -- PR #188 review round 2)
# ---------------------------------------------------------------------------

def test_decision_rank_auto_always_beats_proposed_regardless_of_raw_scores():
    auto = xwalk.MatchDecision(
        status="AUTO", match_method="SERIES", correlation=0.981, ratio=1.0, name_score=0.81, reason="r")
    proposed_name_only = xwalk.MatchDecision(
        status="PROPOSED", match_method="NAME", correlation=None, ratio=None, name_score=1.0, reason="r")
    assert xwalk.decision_rank(auto) > xwalk.decision_rank(proposed_name_only)


def test_decision_rank_series_proposed_beats_name_proposed_even_with_a_lower_raw_score():
    series_proposed = xwalk.MatchDecision(
        status="PROPOSED", match_method="SERIES", correlation=0.99, ratio=1.0, name_score=0.1, reason="r")
    name_proposed = xwalk.MatchDecision(
        status="PROPOSED", match_method="NAME", correlation=0.1, ratio=0.1, name_score=1.0, reason="r")
    assert xwalk.decision_rank(series_proposed) > xwalk.decision_rank(name_proposed)


def test_decision_rank_ties_within_the_same_status_and_method_break_on_correlation():
    stronger = xwalk.MatchDecision(
        status="PROPOSED", match_method="SERIES", correlation=0.97, ratio=1.0, name_score=0.1, reason="r")
    weaker = xwalk.MatchDecision(
        status="PROPOSED", match_method="SERIES", correlation=0.90, ratio=1.0, name_score=0.1, reason="r")
    assert xwalk.decision_rank(stronger) > xwalk.decision_rank(weaker)


def test_match_decision_primary_score_is_correlation_for_series_and_name_score_for_name():
    series = xwalk.MatchDecision(
        status="AUTO", match_method="SERIES", correlation=0.99, ratio=1.0, name_score=0.9, reason="r")
    name = xwalk.MatchDecision(
        status="PROPOSED", match_method="NAME", correlation=0.1, ratio=0.1, name_score=0.9, reason="r")
    assert series.primary_score == 0.99
    assert name.primary_score == 0.9


def test_decide_match_always_carries_the_full_evidence_tuple_not_just_the_deciding_signal():
    # A NAME decision still carries whatever (weak) correlation/ratio the series
    # comparison produced; a SERIES decision still carries name_score -- nothing
    # computed during evaluation is silently dropped.
    weak_series = xwalk.evaluate_series([10.0, 20.0, 15.0], [1.0, 2.0, 50.0])
    decision = xwalk.decide_match(series=weak_series, name_score=0.9)
    assert decision.match_method == "NAME"
    assert decision.correlation == weak_series.correlation
    assert decision.ratio == weak_series.ratio

    strong_series = xwalk.evaluate_series([100.0 + i for i in range(24)], [100.0 + i for i in range(24)])
    decision2 = xwalk.decide_match(series=strong_series, name_score=0.1)
    assert decision2.match_method == "SERIES"
    assert decision2.name_score == 0.1


# ---------------------------------------------------------------------------
# decision_fingerprint sensitivity (PR #188 review round 2: a change to ratio
# alone, or name_score alone, must also change the fingerprint)
# ---------------------------------------------------------------------------

def test_decision_fingerprint_changes_when_only_the_ratio_changes():
    base = dict(
        model_group_id="g", canonical_model_id="c", correlation=0.99, name_score=0.9, master_version="M5")
    fp1 = xwalk.decision_fingerprint(ratio=1.0, **base)
    fp2 = xwalk.decision_fingerprint(ratio=1.05, **base)
    assert fp1 != fp2


def test_decision_fingerprint_changes_when_only_the_name_score_changes():
    base = dict(
        model_group_id="g", canonical_model_id="c", correlation=0.99, ratio=1.0, master_version="M5")
    fp1 = xwalk.decision_fingerprint(name_score=0.81, **base)
    fp2 = xwalk.decision_fingerprint(name_score=0.95, **base)
    assert fp1 != fp2


# ---------------------------------------------------------------------------
# Name normalization / similarity plumbing
# ---------------------------------------------------------------------------

def test_normalize_model_name_strips_brand_prefix_and_punctuation():
    assert xwalk.normalize_model_name("Toyota Hilux Travo!!", "Toyota") == "hilux travo"


def test_name_similarity_identical_strings_is_one():
    assert xwalk.name_similarity("hilux travo", "hilux travo") == 1.0


def test_name_similarity_both_empty_is_one_one_empty_is_zero():
    assert xwalk.name_similarity("", "") == 1.0
    assert xwalk.name_similarity("", "x") == 0.0


# ---------------------------------------------------------------------------
# Many-TDR-models-to-one-Ice-group summation
# ---------------------------------------------------------------------------

def test_sum_monthly_series_combines_multiple_tdr_models_for_one_group():
    cab = {"2569-06": 10.0, "2569-07": 12.0}
    double_cab = {"2569-06": 5.0, "2569-07": 8.0}
    combined = xwalk.sum_monthly_series([cab, double_cab])
    assert combined == {"2569-06": 15.0, "2569-07": 20.0}


def test_build_paired_series_defaults_missing_periods_to_zero():
    periods = ["2569-06", "2569-07", "2569-08"]
    ice = {"2569-06": 10.0, "2569-08": 30.0}
    legacy = {"2569-07": 5.0}
    xs, ys = xwalk.build_paired_series(periods, ice, legacy)
    assert xs == [10.0, 0.0, 30.0]
    assert ys == [0.0, 5.0, 0.0]


# ---------------------------------------------------------------------------
# Decision fingerprint (rejected-mapping staleness)
# ---------------------------------------------------------------------------

def test_decision_fingerprint_is_stable_for_identical_inputs():
    kwargs = dict(
        model_group_id="toyota-hilux-travo", canonical_model_id="toyota-hilux-travo-cab",
        correlation=0.99, ratio=1.0, name_score=0.9, master_version="M5")
    assert xwalk.decision_fingerprint(**kwargs) == xwalk.decision_fingerprint(**kwargs)


def test_decision_fingerprint_changes_when_master_version_changes():
    base = dict(
        model_group_id="toyota-hilux-travo", canonical_model_id="toyota-hilux-travo-cab",
        correlation=0.99, ratio=1.0, name_score=0.9)
    fp1 = xwalk.decision_fingerprint(master_version="M5", **base)
    fp2 = xwalk.decision_fingerprint(master_version="M6", **base)
    assert fp1 != fp2


# ---------------------------------------------------------------------------
# Discovery (§14.2 "Ongoing, on every Ice import")
# ---------------------------------------------------------------------------

def test_a_brand_new_model_group_id_enters_discovery_as_new():
    assert xwalk.discovery_flags("some-new-group", set()) == ["NEW"]


def test_a_known_model_group_id_is_not_flagged_new():
    assert xwalk.discovery_flags("known-group", {"known-group"}) == []


def test_provisional_model_group_with_pipe_is_flagged():
    assert "PROVISIONAL" in xwalk.discovery_flags("toyota-new|camry", {"toyota-new|camry"})


def test_provisional_model_group_with_suffix_is_flagged():
    assert "PROVISIONAL" in xwalk.discovery_flags("toyota-camry__provisional", {"toyota-camry__provisional"})


def test_a_new_and_provisional_group_gets_both_flags():
    flags = xwalk.discovery_flags("brand-new|group", set())
    assert flags == ["NEW", "PROVISIONAL"]


# ---------------------------------------------------------------------------
# Buddhist/Gregorian calendar conversion
# ---------------------------------------------------------------------------

def test_buddhist_period_to_gregorian_year_month():
    assert xwalk.buddhist_period_to_gregorian_year_month("2569-08") == "2026-08"


def test_gregorian_date_to_buddhist_period_accepts_a_full_date():
    assert xwalk.gregorian_date_to_buddhist_period("2026-08-01") == "2569-08"


def test_gregorian_date_to_buddhist_period_accepts_year_month_only():
    assert xwalk.gregorian_date_to_buddhist_period("2026-08") == "2569-08"


def test_calendar_conversion_round_trips():
    assert xwalk.gregorian_date_to_buddhist_period(
        xwalk.buddhist_period_to_gregorian_year_month("2569-08") + "-01") == "2569-08"


# ---------------------------------------------------------------------------
# id_changes.csv parsing (SKILL.md §3)
# ---------------------------------------------------------------------------

def test_parse_id_change_row_rename():
    row = xwalk.parse_id_change_row({
        "old_model_group_id": "old-1", "new_model_group_id": "new-1",
        "reg_moved_all_periods": "true", "share_of_old_pct": "100", "type": "เปลี่ยนรหัส"})
    assert row.type == "เปลี่ยนรหัส"
    assert row.reg_moved_all_periods is True
    assert row.share_of_old_pct == 100.0


def test_parse_id_change_row_split_has_optional_share():
    row = xwalk.parse_id_change_row({
        "old_model_group_id": "old-1", "new_model_group_id": "new-1",
        "reg_moved_all_periods": "false", "share_of_old_pct": "35.5", "type": "แยก"})
    assert row.type == "แยก"
    assert row.reg_moved_all_periods is False
    assert row.share_of_old_pct == 35.5


def test_parse_id_change_row_rejects_unknown_type():
    try:
        xwalk.parse_id_change_row({
            "old_model_group_id": "old-1", "new_model_group_id": "new-1",
            "reg_moved_all_periods": "true", "share_of_old_pct": "", "type": "unknown"})
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an unknown id_changes type")


# ---------------------------------------------------------------------------
# One-time review sheet (§14.2 "4.")
# ---------------------------------------------------------------------------

def test_build_review_rows_orders_by_group_then_canonical_with_none_last():
    records = [
        {"model_group_id": "b-group", "proposed_canonical_model_id": "x"},
        {"model_group_id": "a-group", "proposed_canonical_model_id": None},
        {"model_group_id": "a-group", "proposed_canonical_model_id": "y"},
    ]
    ordered = xwalk.build_review_rows(records)
    assert [(r["model_group_id"], r["proposed_canonical_model_id"]) for r in ordered] == [
        ("a-group", "y"), ("a-group", None), ("b-group", "x"),
    ]


def test_build_review_rows_only_includes_the_documented_columns():
    rows = xwalk.build_review_rows([{"model_group_id": "g", "proposed_canonical_model_id": "c", "extra": "ignored"}])
    assert set(rows[0]) == set(xwalk.REVIEW_SHEET_COLUMNS)
    assert "extra" not in rows[0]
