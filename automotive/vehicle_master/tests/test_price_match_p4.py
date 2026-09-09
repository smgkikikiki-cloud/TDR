from __future__ import annotations

import vehreg.price_match as price_match
from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from vehreg.price_match import TrimMatchMethod, TrimMatchState, match_trim_diagnostic
from vehreg.pricefeed import PriceClaim, match_trim
from vehreg.pricing import PriceType


J5_MODEL = "jaecoo.jaecoo_5_ev"
J5_TRIMS = {
    "LONG RANGE DYNAMIC": "jaecoo.jaecoo_5_ev.j5.trim.long_range_dynamic_bev",
    "LONG RANGE MAX": "jaecoo.jaecoo_5_ev.j5.trim.long_range_max_bev",
    "MAX+": "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev",
    "ULTRA": "jaecoo.jaecoo_5_ev.j5.trim.ultra_bev",
}


def _claim(trim: str, *, model: str = "JAECOO 5 EV") -> PriceClaim:
    return PriceClaim(
        claim_id=f"p4-{trim}",
        document_id="sha256:" + "a" * 64,
        source_id="official_jaecoo_th",
        brand_raw="JAECOO",
        model_raw=model,
        trim_raw=trim,
        amount_thb=699_000,
        price_type=PriceType.LIST_PRICE,
    )


def test_live_j5_raw_grades_resolve_to_canonical_market_trims() -> None:
    catalog = Catalog.load(DATA_DIR, DEFAULT_YEAR)

    for raw, expected in J5_TRIMS.items():
        result = match_trim_diagnostic(catalog, _claim(raw))
        assert result.state is TrimMatchState.EXACT
        assert result.model_id == J5_MODEL
        assert result.trim_id == expected
        assert result.candidate_ids == (expected,)
        assert result.method in {
            TrimMatchMethod.EXACT_NAME,
            TrimMatchMethod.EXACT_ALIAS,
        }


def test_j5_max_plus_written_as_words_uses_canonical_alias() -> None:
    catalog = Catalog.load(DATA_DIR, DEFAULT_YEAR)

    result = match_trim_diagnostic(catalog, _claim("MAX PLUS"))

    assert result.state is TrimMatchState.EXACT
    assert result.trim_id == J5_TRIMS["MAX+"]
    assert result.method is TrimMatchMethod.EXACT_ALIAS


def test_unmapped_grade_never_guesses_a_j5_trim() -> None:
    catalog = Catalog.load(DATA_DIR, DEFAULT_YEAR)

    result = match_trim_diagnostic(catalog, _claim("PREMIUM AWD"))

    assert result.state is TrimMatchState.UNMAPPED
    assert result.model_id == J5_MODEL
    assert result.trim_id is None
    assert result.candidate_ids == ()
    assert result.method is TrimMatchMethod.NO_GRADE_MATCH


def test_unknown_model_is_unmapped_before_grade_matching() -> None:
    catalog = Catalog.load(DATA_DIR, DEFAULT_YEAR)

    result = match_trim_diagnostic(catalog, _claim("MAX+", model="NOT A REAL JAECOO"))

    assert result.state is TrimMatchState.UNMAPPED
    assert result.model_id is None
    assert result.trim_id is None
    assert result.method is TrimMatchMethod.NO_MODEL


def test_ambiguous_candidates_are_reported_without_breaking_tie(monkeypatch) -> None:
    catalog = Catalog.load(DATA_DIR, DEFAULT_YEAR)
    left = J5_TRIMS["LONG RANGE DYNAMIC"]
    right = J5_TRIMS["LONG RANGE MAX"]

    monkeypatch.setattr(
        price_match,
        "match_trim",
        lambda *args, **kwargs: (None, tuple(sorted((left, right)))),
    )

    result = match_trim_diagnostic(catalog, _claim("LONG RANGE"))

    assert result.state is TrimMatchState.AMBIGUOUS
    assert result.trim_id is None
    assert result.candidate_ids == tuple(sorted((left, right)))
    assert result.method is TrimMatchMethod.AMBIGUOUS_PARTIAL


def test_p4_wrapper_preserves_production_matcher_answer() -> None:
    catalog = Catalog.load(DATA_DIR, DEFAULT_YEAR)
    claim = _claim("MAX+")

    legacy_trim, legacy_candidates = match_trim(catalog, claim)
    result = match_trim_diagnostic(catalog, claim)

    assert result.trim_id == legacy_trim
    assert result.candidate_ids == legacy_candidates
