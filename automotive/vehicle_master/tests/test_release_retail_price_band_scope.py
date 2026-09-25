from __future__ import annotations

import json
from pathlib import Path

from tdr_bridge.release import ReleaseBuilder
from vehreg.model_operational_state import upsert_model_operational_state

YEAR = 2026
MODEL_ID = "jaecoo.jaecoo_5_ev"
CURRENT_TRIM = "jaecoo.jaecoo_5_ev.j5.trim.ultra_bev"
RETIRED_TRIM = "jaecoo.jaecoo_5_ev.j4.trim.legacy_bev"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed(tmp_path: Path, *, current_price: int | None = 699_000,
         retired_price: int | None = 999_999) -> Path:
    """A two-generation model: an ended J4 with a very different historical
    price, and a current (not ended) J5. Proves retail_price_min/max can
    only ever reflect the current generation, however loud the historical
    price is."""
    data = tmp_path / "data"
    _write_json(data / str(YEAR) / "models" / "jaecoo.json", {
        "brand": {
            "id": "jaecoo", "name_en": "Jaecoo", "name_th": "เจคู",
            "brand_segment": "MASS", "oem_group": "Chery", "brand_origin": "CN",
            "trim_detail": True, "aliases": [],
        },
        "models": [{
            "id": "jaecoo_5_ev", "name_en": "Jaecoo 5 EV", "name_th": "เจคู 5",
            "nameplate": "Jaecoo 5", "body_type": "CROSSOVER",
            "cab_type": "NOT_APPLICABLE", "registration_type": "",
            "market_scope": "CORE", "aliases": [],
            "retail_status": "CURRENT",
            "retail_checked_at": "2026-09-11",
            "retail_source": "https://example.test/j5/model",
            "generations": [
                {
                    "code": "J4", "segment": "B", "seats": 5,
                    "launched": "2023-01-01", "ended": "2025-01-01",
                    "variants": [{
                        "id": "legacy", "name": "Legacy", "powertrain": "BEV",
                        "drivetrain": "FWD", "engine_cc": None, "battery_kwh": 50.0,
                        "price_thb": None, "price_min_thb": None, "price_max_thb": None,
                        "import_type": "CBU", "origin_country": "CN",
                        "price_note": "", "aliases": [],
                    }],
                    "trims": [{
                        "id": "legacy_bev", "name": "Legacy", "variant": "Legacy",
                        "powertrain": "BEV", "drivetrain": "FWD", "battery_kwh": 50.0,
                        "seats": 5, "aliases": [], "source_refs": {},
                    }],
                },
                {
                    "code": "J5", "segment": "B", "seats": 5,
                    "launched": "2025-08-19", "ended": None,
                    "variants": [{
                        "id": "bev_cbu", "name": "58.9 kWh BEV CBU", "powertrain": "BEV",
                        "drivetrain": "FWD", "engine_cc": None, "battery_kwh": 58.9,
                        "price_thb": None, "price_min_thb": None, "price_max_thb": None,
                        "import_type": "CBU", "origin_country": "CN",
                        "price_note": "", "aliases": [],
                    }],
                    "trims": [{
                        "id": "ultra_bev", "name": "Ultra", "variant": "58.9 kWh BEV CBU",
                        "powertrain": "BEV", "drivetrain": "FWD", "battery_kwh": 58.9,
                        "seats": 5, "aliases": [], "source_refs": {},
                    }],
                },
            ],
        }],
    })
    prices = []
    if retired_price is not None:
        prices.append({"trim_id": RETIRED_TRIM, "amount_thb": retired_price,
                       "price_type": "LIST_PRICE", "effective_from": "2024-01-01",
                       "observed_at": "2024-01-01", "source": "seed"})
    if current_price is not None:
        prices.append({"trim_id": CURRENT_TRIM, "amount_thb": current_price,
                       "price_type": "LIST_PRICE", "effective_from": "2026-01-01",
                       "observed_at": "2026-01-01", "source": "seed"})
    if prices:
        _write_json(data / str(YEAR) / "market" / "prices" / "canonical_seed.json",
                    {"prices": prices})
    return data


def _model_row(tmp_path: Path, **seed_kwargs) -> dict:
    data = _seed(tmp_path, **seed_kwargs)
    release = ReleaseBuilder({}, data_dir=data, year=YEAR).build()
    return next(m for m in release["models"] if m["canonical_id"] == MODEL_ID)


def test_retail_price_band_excludes_a_historical_generations_price(tmp_path: Path):
    model = _model_row(tmp_path, current_price=699_000, retired_price=999_999)
    assert model["retail_price_min"] == 699_000
    assert model["retail_price_max"] == 699_000


def test_retail_price_band_is_none_when_only_the_historical_generation_has_a_price(tmp_path: Path):
    model = _model_row(tmp_path, current_price=None, retired_price=999_999)
    assert model["retail_price_min"] is None
    assert model["retail_price_max"] is None


def test_retail_price_band_is_none_when_model_is_under_maintenance(tmp_path: Path):
    data = _seed(tmp_path, current_price=699_000, retired_price=None)
    upsert_model_operational_state(
        data_dir=data, year=YEAR, model_id=MODEL_ID, action="under_maintenance",
        reviewer="ops", reviewed_at="2026-09-24", write=True,
    )
    release = ReleaseBuilder({}, data_dir=data, year=YEAR).build()
    model = next(m for m in release["models"] if m["canonical_id"] == MODEL_ID)
    assert model["retail_price_min"] is None
    assert model["retail_price_max"] is None
