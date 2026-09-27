"""Retail lifecycle semantics for serving releases.

The serving policy is intentionally simple and operator-owned, with one
authority ranked above everything else:

* an explicit HISTORICAL model or an ended generation always forces HISTORICAL;
* for a model with an explicit approved current-retail set
  (vehreg/current_retail.py), CURRENT membership is decided by that set alone
  -- a trim in it is CURRENT, a trim not in it is never CURRENT no matter what
  source evidence, owner-directory rows, verified fragments or old prices say
  about it (an existing HUMAN HISTORICAL disposition on a non-member is still
  honored, since that is a stricter claim, never a way back to CURRENT);
* for every other model (no approved set yet -- the common case during
  migration), the legacy owner policy keeps applying unchanged: canonical
  identity/catalog presence is CURRENT by default, an explicit HUMAN trim
  lifecycle decision can mark one trim CURRENT/HISTORICAL, and a missing price
  is price debt, not lifecycle debt.

This lets showroom-lineup repairs happen model by model: approving one
model's current-retail set switches ONLY that model onto the strict "approved
set is the whole truth" rule, and every untouched model keeps behaving
exactly as it does today.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

from vehreg.catalog import DATA_DIR, DEFAULT_YEAR
from vehreg.current_retail import load_current_retail_index
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
    # Loaded once for the whole build, not once per model: current_retail.json
    # is one file, and re-reading/re-validating it (which re-loads Catalog)
    # once per distinct model_id would turn one release build into as many
    # redundant catalog loads as there are explicitly managed models.
    approved_index = load_current_retail_index(data_dir=data_dir, year=year)

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

        approved = approved_index.get(model_id)

        if model_status.get(model_id) == "HISTORICAL" or generation_historical:
            trim["status"] = "HISTORICAL"
        elif approved is not None:
            # Explicitly managed model: the approved set is the sole authority
            # on CURRENT membership. Source evidence, owner-directory rows,
            # verified fragments, reconciliation state and old prices have no
            # vote here at all -- not even as a fallback.
            if trim_id in approved:
                trim["status"] = "CURRENT"
            elif trim_id in decisions and decisions[trim_id].get("status") == "HISTORICAL":
                # A non-member may still carry its own HUMAN HISTORICAL
                # disposition -- that is a stricter claim than "just not
                # approved," never a route back to CURRENT, so it is honored.
                trim["status"] = "HISTORICAL"
                trim["retail_lifecycle_review"] = {
                    key: decisions[trim_id][key]
                    for key in ("reviewer", "reviewed_at", "source_ref", "notes")
                }
            else:
                trim["status"] = "UNVERIFIED"
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
