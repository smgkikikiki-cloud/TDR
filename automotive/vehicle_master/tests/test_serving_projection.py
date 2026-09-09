from datetime import date

from vehreg.serving_projection import build_model_serving_projection


def test_jaecoo_5_projection_preserves_variant_vs_market_trim_grain():
    payload = build_model_serving_projection(
        "jaecoo.jaecoo_5_ev", as_of=date(2026, 9, 9)
    )

    model = payload["model"]
    assert payload["canonical_model_id"] == "jaecoo.jaecoo_5_ev"
    assert payload["canonical_generation_id"] == "jaecoo.jaecoo_5_ev.j5"
    assert model["generation"] == "J5"
    assert model["body_type"] == "Crossover"
    assert model["segment"] == "B"
    assert model["launch_date"] == "2025-08-19"
    assert model["launch_month"] == 8
    assert model["launch_quarter"] == "Q3"
    assert model["powertrains"] == ["BEV"]

    # Analytical variants and retail grades remain two different grains.
    assert len(payload["variants"]) == 3
    assert len(payload["trims"]) == 4
    assert all(row["canonical_id"] for row in payload["variants"])
    assert all(row["canonical_id"] for row in payload["trims"])
    assert all(row["canonical_variant_id"] for row in payload["trims"])


def test_mixed_import_routes_do_not_become_fake_model_level_truth():
    payload = build_model_serving_projection(
        "jaecoo.jaecoo_5_ev", as_of=date(2026, 9, 9)
    )
    model = payload["model"]

    # J5 has CBU and CKD analytical variants (plus one route not asserted).
    # The old TDR row said simply CKD/TH; the canonical projection must not.
    assert model["production_type"] is None
    assert model["production_country"] is None

    routes = {(v["import_type"], v["origin_country"]) for v in payload["variants"]}
    assert ("CBU", "CN") in routes
    assert ("CKD", "TH") in routes


def test_only_current_list_price_is_projected_to_serving_price_cache():
    payload = build_model_serving_projection(
        "jaecoo.jaecoo_5_ev", as_of=date(2026, 9, 9)
    )
    trims = {row["name"]: row for row in payload["trims"]}

    # ECO Sticker evidence is not MSRP; estimated price is not MSRP either.
    assert trims["Long Range Dynamic"]["price_baht"] is None
    assert trims["Long Range Max"]["price_baht"] is None
    assert trims["ULTRA"]["price_baht"] is None

    # Only the official LIST_PRICE survives into the serving cache.
    assert trims["MAX+"]["price_baht"] == 699000
    assert trims["MAX+"]["list_price_source"] == "official_oem"

    # Partial trim coverage cannot masquerade as a complete model price range.
    assert payload["model"]["retail_price_min"] is None
    assert payload["model"]["retail_price_max"] is None


def test_projection_hash_is_stable_for_same_served_facts():
    first = build_model_serving_projection(
        "jaecoo.jaecoo_5_ev", as_of=date(2026, 9, 9)
    )
    second = build_model_serving_projection(
        "jaecoo.jaecoo_5_ev", as_of=date(2026, 9, 10)
    )

    # A later calendar day alone does not churn the serving projection.
    assert first["projection_hash"] == second["projection_hash"]
