import json
from pathlib import Path

from tdr_bridge.historical_state import build_historical_model_state

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / "integration_data" / "crosswalk_overrides.json"


def _baseline(payload, model_id, year):
    return next(
        row for row in payload["model_year_baselines"]
        if row["canonical_model_id"] == model_id and row["catalog_year"] == year
    )


def _changes(payload, model_id):
    return [row for row in payload["monthly_changes"] if row["canonical_model_id"] == model_id]


def test_historical_projection_uses_year_catalog_baselines_and_sparse_changes():
    aliases = json.loads(OVERRIDES.read_text(encoding="utf-8"))["source_aliases"]
    payload = build_historical_model_state(source_aliases=aliases)
    assert payload["catalog_years"] == [2021, 2022, 2023, 2024, 2025, 2026]
    assert payload["model_year_baselines"]
    assert payload["monthly_changes"]
    assert payload["aliased_seed_rows"] == 1

    # The baseline is deliberately year-specific rather than copied from the
    # current serving model snapshot.
    dolphin_2023 = _baseline(payload, "byd.dolphin", 2023)
    assert dolphin_2023["origin_country"] == "CN"
    assert dolphin_2023["import_type"] == "CBU"

    # Reviewed transition points remain sparse and carry forward downstream.
    jaecoo = _changes(payload, "jaecoo.jaecoo_5_ev")
    assert [(row["effective_month"], row["origin_country"], row["import_type"]) for row in jaecoo] == [
        ("2025-09", "CN", "CBU"),
        ("2026-03", "TH", "CKD"),
    ]
    jaecoo_7 = _changes(payload, "jaecoo.jaecoo_7")
    assert len(jaecoo_7) == 1
    assert jaecoo_7[0]["effective_month"] == "2025-05"
    assert "source unit id=chery.jaecoo_j7" in jaecoo_7[0]["note"]

    forester = _changes(payload, "subaru.forester")
    assert [(row["effective_month"], row["origin_country"], row["import_type"]) for row in forester] == [
        ("2022-01", "TH", "CKD"),
        ("2025-01", "JP", "CBU"),
    ]
    i5 = _changes(payload, "bmw.i5")
    assert [(row["effective_month"], row["origin_country"], row["import_type"]) for row in i5] == [
        ("2023-01", "DE", "CBU"),
        ("2026-01", "TH", "CKD"),
    ]
