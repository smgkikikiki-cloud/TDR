import json
from datetime import date
from pathlib import Path

from tdr_bridge.release import ReleaseBuilder
from tdr_bridge.release_enriched import SEMANTIC_KEYS, enrich_release


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


def test_enriched_release_identity_is_stable_and_covers_lifecycle_and_history():
    # This is the payload tdr_bridge.publish actually ships to
    # publish_vehicle_release in production (vehicle-release.yml calls
    # release_enriched, not the bare ReleaseBuilder output). The base-release
    # determinism test above does not exercise this wrapper at all, so a
    # change that only breaks enrich_release's hashing/lifecycle/history
    # attachment could pass CI while corrupting what actually gets published.
    base = build_release()
    overrides = json.loads((ROOT / "integration_data/crosswalk_overrides.json").read_text(encoding="utf-8"))
    source_aliases = overrides.get("source_aliases", {})
    first = enrich_release(dict(base), source_aliases=source_aliases)
    second = enrich_release(dict(base), source_aliases=source_aliases)

    assert first["release_id"] == second["release_id"]
    assert first["source_hash"] == second["source_hash"]

    # Enrichment must be substantive, not decorative: it has to change the
    # semantic payload (and therefore the hash) relative to the bare release,
    # or a caller that forgets to enrich would silently publish an
    # under-specified release with the same identity.
    assert first["release_id"] != base["release_id"]
    assert first["source_hash"] != base["source_hash"]

    assert "historical_model_state" in first
    assert set(SEMANTIC_KEYS).issubset(first.keys())
    # apply_retail_lifecycle is fail-closed: every trim must land on an
    # explicit, evidence-backed status rather than silently inheriting an
    # "active generation implies current" default.
    for trim in first["market_trims"]:
        assert trim["status"] in {"CURRENT", "HISTORICAL", "UNVERIFIED"}

