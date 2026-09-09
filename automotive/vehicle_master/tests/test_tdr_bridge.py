import json
from datetime import date
from pathlib import Path

from tdr_bridge.release import ReleaseBuilder


ROOT = Path(__file__).resolve().parents[1]


def build_release():
    inventory = json.loads((ROOT / "integration_data/tdr_2026-09-09.json").read_text(encoding="utf-8"))
    overrides = json.loads((ROOT / "integration_data/crosswalk_overrides.json").read_text(encoding="utf-8"))
    return ReleaseBuilder(inventory, canonical_revision="test-revision", overrides=overrides).build(
        as_of=date(2026, 9, 9)
    )


def test_all_canonical_models_crosswalk_without_creating_registration_trims():
    release = build_release()
    assert release["counts"]["models"] == 321
    assert release["crosswalk"]["counts"] == {
        "mapped_brands": 62,
        "mapped_models": 321,
        "review_items": 6,
    }
    assert "registrations" not in release
    assert all(trim["model_id"] in release["crosswalk"]["models"] for trim in release["market_trims"])


def test_market_trim_price_campaign_and_status_are_distinct_fields():
    release = build_release()
    fronx = next(trim for trim in release["market_trims"] if trim["canonical_id"] == "suzuki.fronx.frx.trim.glx_1_5l_mhev_6at")
    assert fronx["status"] == "current"
    assert fronx["current_list_price"]["amount_thb"] == 749000
    options = fronx["campaign_quote"]["campaign_options"]
    assert {option["amount_thb"] for option in options} == {649000, 669000}
    assert all(option["conditions"]["text"] for option in options)


def test_release_identity_is_stable_for_the_same_inputs():
    first = build_release()
    second = build_release()
    assert first["release_id"] == second["release_id"]
    assert first["source_hash"] == second["source_hash"]

