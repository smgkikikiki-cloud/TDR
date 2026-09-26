"""Retail lifecycle semantics for serving releases.

The serving policy is intentionally simple and operator-owned:

* canonical identity/catalog presence is treated as CURRENT by default;
* an explicit HISTORICAL model or an ended generation forces HISTORICAL;
* an explicit HUMAN trim lifecycle decision can mark one trim CURRENT/HISTORICAL;
* otherwise a trim remains CURRENT whether or not a price has been found yet.

This keeps price coverage honest in the direction the owner actually wants: a
missing price is price debt, not lifecycle debt. Cars stop being searched only
when the operator explicitly archives them (or records a generation end date).
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

from vehreg.catalog import DATA_DIR, DEFAULT_YEAR
from vehreg.retail_lifecycle_review import load_trim_lifecycle_decisions

_ALLOWED = {"CURRENT", "HISTORICAL", "UNVERIFIED"}


def _status(value: object, default: str = "CURRENT") -> str:
    normalized = str(value or default).strip().upper()
    return normalized if normalized in _ALLOWED else default


def apply_retail_lifecycle(
    release: dict[str, Any],
    *,
    data_dir: Path | str = DATA_DIR,
    year: int = DEFAULT_YEAR,
) -> dict[str, Any]:
    """Return a copy using CURRENT-by-default, manual-archive lifecycle rules."""
    out = deepcopy(release)
    as_of = date.fromisoformat(str(out.get("as_of") or ""))
    decisions = {
        row["trim_id"]: row
        for row in load_trim_lifecycle_decisions(data_dir=data_dir, year=year)
    }

    # Historical is an explicit operator claim. Everything else in the active
    # catalog remains searchable/current by default; legacy UNVERIFIED values
    # do not create a second manual verification queue anymore.
    model_status: dict[str, str] = {}
    for model in out.get("models", []):
        payload = model.get("payload") if isinstance(model, dict) else None
        canonical = _status(payload.get("retail_status") if isinstance(payload, dict) else None)
        resolved = "HISTORICAL" if canonical == "HISTORICAL" else "CURRENT"
        model["status"] = resolved
        model_status[str(model.get("canonical_id") or "")] = resolved

    generations = {
        str(row.get("canonical_id") or ""): row
        for row in out.get("generations", [])
        if isinstance(row, dict)
    }
    for trim in out.get("market_trims", []):
        if not isinstance(trim, dict):
            continue
        trim_id = str(trim.get("canonical_id") or "")
        model_id = str(trim.get("model_id") or "")
        generation = generations.get(str(trim.get("generation_id") or ""), {})
        ended = str(generation.get("ended") or "").strip()
        generation_historical = False
        if ended:
            try:
                generation_historical = date.fromisoformat(ended) <= as_of
            except ValueError:
                # Release validation owns malformed dates. Do not invent a
                # historical state from an unreadable value.
                generation_historical = False

        if model_status.get(model_id) == "HISTORICAL" or generation_historical:
            trim["status"] = "HISTORICAL"
        elif trim_id in decisions:
            trim["status"] = _status(decisions[trim_id].get("status"))
            trim["retail_lifecycle_review"] = {
                key: decisions[trim_id][key]
                for key in ("reviewer", "reviewed_at", "source_ref", "notes")
            }
        else:
            trim["status"] = "CURRENT"

    return out


__all__ = ["apply_retail_lifecycle"]
