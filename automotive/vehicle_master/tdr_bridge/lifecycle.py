"""Fail-closed retail lifecycle semantics for serving releases.

Canonical identity and retail currentness are different claims.  Vehicle Master
may know a MarketTrim because ECO/homologation evidence proves that the grade
exists, but that does not prove a Thai buyer can order it today.

This module normalizes the release after the base bridge has assembled identity,
price and generation facts:

* model status comes only from canonical ``Model.retail_status`` embedded in the
  model payload; legacy TDR editorial status never gets to promote a model.
* a trim in a generation/model that is explicitly historical is HISTORICAL.
* a trim with a real current canonical LIST_PRICE is CURRENT evidence.
* everything else is UNVERIFIED until a separate retail-lifecycle review says
  otherwise (added by the review workflow, not inferred here).

The important property is asymmetric: missing evidence never becomes CURRENT.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any

_ALLOWED = {"CURRENT", "HISTORICAL", "UNVERIFIED"}


def _status(value: object, default: str = "UNVERIFIED") -> str:
    normalized = str(value or default).strip().upper()
    return normalized if normalized in _ALLOWED else default


def _positive_amount(price: object) -> bool:
    if not isinstance(price, dict):
        return False
    try:
        amount = float(price.get("amount_thb") or 0)
    except (TypeError, ValueError):
        return False
    return amount > 0


def apply_retail_lifecycle(release: dict[str, Any]) -> dict[str, Any]:
    """Return a copy whose model/trim status is evidence-backed and fail-closed."""
    out = deepcopy(release)
    as_of = date.fromisoformat(str(out.get("as_of") or ""))

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
        model_id = str(trim.get("model_id") or "")
        generation = generations.get(str(trim.get("generation_id") or ""), {})
        ended = str(generation.get("ended") or "").strip()
        generation_historical = False
        if ended:
            try:
                generation_historical = date.fromisoformat(ended) <= as_of
            except ValueError:
                # Release validation owns malformed canonical dates.  Do not
                # promote the trim while the lifecycle evidence is unreadable.
                generation_historical = False

        if model_status.get(model_id) == "HISTORICAL" or generation_historical:
            trim["status"] = "HISTORICAL"
        elif _positive_amount(trim.get("current_list_price")):
            trim["status"] = "CURRENT"
        else:
            trim["status"] = "UNVERIFIED"

    return out


__all__ = ["apply_retail_lifecycle"]
