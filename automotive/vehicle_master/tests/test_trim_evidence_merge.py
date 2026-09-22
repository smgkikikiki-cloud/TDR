import json

import pytest

from vehreg.catalog import CatalogError
from vehreg.trim_reconciliation import apply_canonical_trim_overlay
from tdr_bridge.trim_fragments import apply_verified_trim_fragments


CANONICAL_ID = "acme.echo.e1.trim.premium_bev"


def _release():
    return {
        "year": 2026,
        "as_of": "2026-09-22",
        "brands": [{"canonical_id": "acme", "name_en": "Acme"}],
        "models": [{
            "canonical_id": "acme.echo",
            "brand_id": "acme",
            "name_en": "Echo",
        }],
        "generations": [{
            "canonical_id": "acme.echo.e1",
            "model_id": "acme.echo",
        }],
        "market_trims": [{
            "canonical_id": CANONICAL_ID,
            "model_id": "acme.echo",
            "generation_id": "acme.echo.e1",
            "variant_id": "acme.echo.e1.line_1",
            "name": "Premium",
            "powertrain": "BEV",
            "status": "current",
            "payload": {
                "specs": {
                    "id": CANONICAL_ID,
                    "generation_id": "acme.echo.e1",
                    "name": "Premium",
                    "powertrain": "BEV",
                    "variant_id": "acme.echo.e1.line_1",
                    "aliases": [],
                    "source_refs": {"eco": ["eco:001"]},
                    "length_mm": 4800,
                    "drivetrain": "UNKNOWN",
                },
                "current_list_price": 999000,
                "price_history": [{"amount": 999000}],
            },
            "current_list_price": 999000,
            "campaign_quote": {"cash": 949000},
            "price_history": [{"amount": 999000}],
            "source_refs": {"eco": ["eco:001"]},
        }],
        "counts": {"market_trims": 1},
    }


def _incoming(*, specs=None):
    return {
        "id": "premium_bev",
        "model_id": "acme.echo",
        "generation_id": "acme.echo.e1",
        "name": "Acme Echo Premium",
        "powertrain": "BEV",
        "aliases": ["Premium EV"],
        "source_refs": {"official_oem": ["https://example.test/echo"]},
        "specs": specs or {"drivetrain": "AWD", "battery_kwh": 62},
    }


def _root(tmp_path):
    root = tmp_path / "2026" / "market" / "trims"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_owner_overlay_merges_same_trim_and_preserves_base_facts(tmp_path):
    (_root(tmp_path) / "canonical.json").write_text(
        json.dumps({"schema_version": 1, "trims": [_incoming()]}),
        encoding="utf-8",
    )

    out = apply_canonical_trim_overlay(_release(), data_dir=tmp_path, year=2026)

    assert out["counts"]["market_trims"] == 1
    trim = out["market_trims"][0]
    assert trim["canonical_id"] == CANONICAL_ID
    assert trim["variant_id"] == "acme.echo.e1.line_1"
    assert trim["current_list_price"] == 999000
    assert trim["campaign_quote"] == {"cash": 949000}
    assert trim["price_history"] == [{"amount": 999000}]
    assert trim["source_refs"] == {
        "eco": ["eco:001"],
        "official_oem": ["https://example.test/echo"],
    }
    specs = trim["payload"]["specs"]
    assert specs["length_mm"] == 4800
    assert specs["drivetrain"] == "AWD"
    assert specs["battery_kwh"] == 62
    assert specs["source_refs"] == trim["source_refs"]
    assert "Premium EV" in specs["aliases"]
    assert "Acme Echo Premium" in specs["aliases"]


def test_owner_overlay_rejects_populated_spec_conflict(tmp_path):
    (_root(tmp_path) / "canonical.json").write_text(
        json.dumps({
            "schema_version": 1,
            "trims": [_incoming(specs={"length_mm": 4900})],
        }),
        encoding="utf-8",
    )

    with pytest.raises(CatalogError, match="conflicting spec length_mm"):
        apply_canonical_trim_overlay(_release(), data_dir=tmp_path, year=2026)


def test_verified_fragment_uses_same_merge_semantics(tmp_path):
    (_root(tmp_path) / "canonical_verified_test.json").write_text(
        json.dumps({"schema_version": 1, "trims": [_incoming()]}),
        encoding="utf-8",
    )

    out = apply_verified_trim_fragments(_release(), data_dir=tmp_path, year=2026)

    assert out["counts"]["market_trims"] == 1
    trim = out["market_trims"][0]
    assert trim["current_list_price"] == 999000
    assert trim["payload"]["specs"]["drivetrain"] == "AWD"
    assert trim["payload"]["specs"]["battery_kwh"] == 62
    assert trim["source_refs"]["eco"] == ["eco:001"]
    assert trim["source_refs"]["official_oem"] == ["https://example.test/echo"]


def test_verified_fragment_rejects_identity_conflict(tmp_path):
    row = _incoming()
    row["powertrain"] = "PHEV"
    (_root(tmp_path) / "canonical_verified_test.json").write_text(
        json.dumps({"schema_version": 1, "trims": [row]}),
        encoding="utf-8",
    )

    with pytest.raises(CatalogError, match="conflicting powertrain"):
        apply_verified_trim_fragments(_release(), data_dir=tmp_path, year=2026)
