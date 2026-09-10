"""Derived historical model state for TDR serving analytics.

This module intentionally reuses the Vehicle Master catalog/dimension builders
instead of parsing model JSON independently. Each catalog year is the baseline
for that year's registration facts; reviewed monthly production-state changes
are then carried forward from their effective month by the web analytics layer.

The output is a serving projection only. Canonical source-of-truth remains the
year catalogs plus ``data/research/monthly_production_state.csv``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from vehreg.catalog import Catalog, DATA_DIR, available_years
from vehreg.db import connect, rebuild_dimension
from vehreg.monthly_state import ensure_schema as ensure_monthly_schema
from vehreg.state_seed import load_seed_csv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_SEED = ROOT / "data" / "research" / "monthly_production_state.csv"


def build_historical_model_state(
    *,
    data_dir: Path | str = DATA_DIR,
    seed_path: Path | str = DEFAULT_STATE_SEED,
    source_aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return deterministic year baselines plus sparse reviewed change-points."""
    data_dir = Path(data_dir)
    conn = connect(":memory:")
    ensure_monthly_schema(conn)
    years = available_years(data_dir)
    for year in years:
        rebuild_dimension(conn, Catalog.load(data_dir, year))

    report = load_seed_csv(conn, seed_path, unit_aliases=source_aliases)
    if report["errors"]:
        conn.close()
        raise ValueError("historical production-state seed errors: " + "; ".join(report["errors"]))

    baselines = [dict(row) for row in conn.execute(
        "SELECT unit_id AS canonical_model_id, catalog_year, origin_country, import_type "
        "FROM dim_unit WHERE grain='MODEL' ORDER BY catalog_year, unit_id"
    )]
    changes = [dict(row) for row in conn.execute(
        "SELECT unit_id AS canonical_model_id, effective_month, origin_country, import_type, note "
        "FROM monthly_vehicle_state WHERE grain='MODEL' "
        "ORDER BY effective_month, unit_id"
    )]
    conn.close()
    return {
        "catalog_years": years,
        "model_year_baselines": baselines,
        "monthly_changes": changes,
        "seed_rows": report["rows"],
        "aliased_seed_rows": report["aliased"],
    }
