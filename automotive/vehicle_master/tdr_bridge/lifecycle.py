"""Fail-closed retail lifecycle semantics for serving releases.

Canonical identity and retail currentness are different claims. Vehicle Master
may know a MarketTrim because ECO/homologation evidence proves that the grade
exists, but that does not prove a Thai buyer can order it today.

Precedence is deliberately strict:

* canonical Model.retail_status owns model lifecycle.
* historical parent model / ended generation always forces HISTORICAL.
* explicit HUMAN trim lifecycle review owns CURRENT/HISTORICAL next.
* absent a review, a real current canonical LIST_PRICE may establish CURRENT.
* everything else remains UNVERIFIED.

Missing evidence never becomes CURRENT, and an open-ended old price cannot
silently override a newer HUMAN historical review.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

from vehreg.catalog import DATA_DIR, DEFAULT_YEAR
from vehreg.retail_lifecycle_review import load_trim_lifecycle_decisions

_ALLOWED = {"CURRENT", "HISTORICAL", "UNVERIFIED"}


def _status(value: object, default: str = "UNVERIFIED") -> str:
    # Exact canonical enum spelling only. The old serving bridge emitted
    # lowercase `current` as a free default; accepting case-insensitively would
    # silently resurrect that trust bug.
    normalized = str(value or default).strip()
    return normalized if normalized in _ALLOWED else default


def _positive_amount(price: object) -> bool:
    if not isinstance(price, dict):
        return False
    try:
        amount = float(price.get("amount_thb") or 0)
    except (TypeError, ValueError):
        return False
    return amount > 0


def apply_retail_lifecycle(
    release: dict[str, Any],
    *,
    data_dir: Path | str = DATA_DIR,
    year: int = DEFAULT_YEAR,
) -> dict[str, Any]:
    """Return a copy whose model/trim status is evidence-backed and fail-closed."""
    out = deepcopy(release)
    as_of = date.fromisoformat(str(out.get("as_of") or ""))
    decisions = {
        row["trim_id"]: row
        for row in load_trim_lifecycle_decisions(data_dir=data_dir, year=year)
    }

    model_status: dict[str, str] = {}
    for model in out.get("models", []):
        payload = model.get("payload") if isinstance(model, dict) else None
        canonical = _status(payload.get("retail_status") if isinstance(payload, dict) else None)
        model["status"] = canonical
        model_status[str(model.get("canonical_id") or "")] = canonical

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
                # Release validation owns malformed canonical dates. Do not
                # promote the trim while lifecycle evidence is unreadable.
                generation_historical = False

        if model_status.get(model_id) == "HISTORICAL" or generation_historical:
            trim["status"] = "HISTORICAL"
        elif trim_id in decisions:
            trim["status"] = _status(decisions[trim_id].get("status"))
            trim["retail_lifecycle_review"] = {
                key: decisions[trim_id][key]
                for key in ("reviewer", "reviewed_at", "source_ref", "notes")
            }
        elif _positive_amount(trim.get("current_list_price")):
            trim["status"] = "CURRENT"
        else:
            trim["status"] = "UNVERIFIED"

    return out


__all__ = ["apply_retail_lifecycle"]
