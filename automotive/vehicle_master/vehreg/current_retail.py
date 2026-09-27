"""Sparse, authoritative CURRENT-retail-set sidecar for MarketTrim membership.

Retail identity (Catalog.trims, plus the append-only market/trims overlay and
fragment grains) answers "what MarketTrim identities does Vehicle Master know
about." It has never answered "which of those are the showroom lineup right
now" -- that question used to be inferred per trim (a HUMAN trim_review.json
decision, else current-by-default/price-by-default depending on the lifecycle
policy of the day) with no single place recording the OWNER's actual approved
lineup for a model.

This module is that place, and only that place. A model absent here has no
opinion -- callers must fall back to whatever the legacy per-trim policy
already does. A model present here is fully authoritative: its listed
canonical trim ids are the entire CURRENT set, full stop. No source evidence,
owner-directory row, verified fragment, or price fact may add to it.

An approved id must already resolve in the base Catalog (Catalog.trims) at
the time it is approved -- retail_scope.py's price eligibility and
vehreg.pricefeed's own name/alias matching both index off Catalog, so an
identity that only exists in the overlay/fragment grain is invisible to
either and could never actually be matched or displayed even if "approved."
A repair batch that introduces a brand-new current trim must therefore
materialize it into Catalog (an ordinary UPSERT_MODEL_BUNDLE command) before
or within the same canonical input batch as the REPLACE_CURRENT_RETAIL_SET
command that approves it -- see vehreg/input_pipeline.py.
"""
from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
from typing import Any

from .catalog import Catalog, DATA_DIR, DEFAULT_YEAR


class CurrentRetailError(ValueError):
    pass


def current_retail_path(data_dir: Path | str = DATA_DIR, year: int = DEFAULT_YEAR) -> Path:
    return Path(data_dir) / str(year) / "market" / "trims" / "current_retail.json"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _validated_date(value: str, label: str) -> str:
    try:
        return date.fromisoformat(str(value or "")).isoformat()
    except ValueError as exc:
        raise CurrentRetailError(f"{label} must be YYYY-MM-DD") from exc


def _validated_source_ref(value: str) -> str:
    source_ref = str(value or "").strip()
    if not source_ref.startswith(("https://", "http://")):
        raise CurrentRetailError("source_ref must be an http(s) URL")
    return source_ref


def _validated_reviewer(value: str) -> str:
    reviewer = str(value or "").strip()
    if not reviewer or reviewer.lower() in {"system", "agent", "agent-proposed"}:
        raise CurrentRetailError("current-retail-set approval requires an explicit HUMAN/owner actor")
    return reviewer


def validate_current_retail_sets(payload: dict[str, Any], *,
                                 data_dir: Path | str = DATA_DIR,
                                 year: int = DEFAULT_YEAR) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("schema_version", 1) != 1:
        raise CurrentRetailError("current_retail schema_version must be 1")
    rows = payload.get("models")
    if not isinstance(rows, list):
        raise CurrentRetailError("current_retail models must be an array")
    catalog = Catalog.load(data_dir, year)
    seen_models: set[str] = set()
    allowed = {"model_id", "trim_ids", "reviewer", "reviewed_at", "source_ref", "notes"}
    checked: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise CurrentRetailError(f"current_retail model[{index}] must be an object")
        unknown = set(raw) - allowed
        if unknown:
            raise CurrentRetailError(f"current_retail model[{index}] unknown fields: {sorted(unknown)}")
        model_id = str(raw.get("model_id") or "").strip()
        if model_id not in catalog.models:
            raise CurrentRetailError(f"current_retail model[{index}] unknown model_id {model_id!r}")
        if model_id in seen_models:
            raise CurrentRetailError(f"duplicate current_retail entry for {model_id}")
        seen_models.add(model_id)

        raw_trim_ids = raw.get("trim_ids")
        if not isinstance(raw_trim_ids, list) or not raw_trim_ids:
            raise CurrentRetailError(f"current_retail {model_id}: trim_ids must be a nonempty array")
        trim_ids: list[str] = []
        seen_trims: set[str] = set()
        for trim_id in raw_trim_ids:
            trim_id = str(trim_id or "").strip()
            if not trim_id:
                raise CurrentRetailError(f"current_retail {model_id}: trim_ids entries must be nonempty")
            if trim_id in seen_trims:
                raise CurrentRetailError(f"current_retail {model_id}: duplicate trim_id {trim_id!r}")
            seen_trims.add(trim_id)
            trim = catalog.trims.get(trim_id)
            if trim is None:
                raise CurrentRetailError(
                    f"current_retail {model_id}: unknown MarketTrim {trim_id!r} -- "
                    "an approved current trim must already exist in the base Catalog "
                    "(materialize it with UPSERT_MODEL_BUNDLE first, in the same batch "
                    "if needed); an overlay-only or fragment-only identity is not a "
                    "valid approved current id"
                )
            generation = catalog.generations.get(trim.generation_id)
            if generation is None or generation.model_id != model_id:
                raise CurrentRetailError(
                    f"current_retail {model_id}: MarketTrim {trim_id!r} does not belong to this model"
                )
            trim_ids.append(trim_id)

        checked.append({
            "model_id": model_id,
            "trim_ids": sorted(trim_ids),
            "reviewer": _validated_reviewer(str(raw.get("reviewer") or "")),
            "reviewed_at": _validated_date(str(raw.get("reviewed_at") or ""), "reviewed_at"),
            "source_ref": _validated_source_ref(str(raw.get("source_ref") or "")),
            "notes": str(raw.get("notes") or "").strip(),
        })
    return sorted(checked, key=lambda row: row["model_id"])


def load_current_retail_sets(*, data_dir: Path | str = DATA_DIR,
                             year: int = DEFAULT_YEAR) -> list[dict[str, Any]]:
    path = current_retail_path(data_dir, year)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CurrentRetailError(f"cannot read {path}: {exc}") from exc
    return validate_current_retail_sets(payload, data_dir=data_dir, year=year)


def load_current_retail_index(*, data_dir: Path | str = DATA_DIR,
                              year: int = DEFAULT_YEAR) -> dict[str, frozenset[str]]:
    """model_id -> its approved CURRENT trim ids, for every EXPLICITLY managed model.

    A model with no row here is simply absent from the returned dict -- callers
    must treat that as "no opinion, use legacy behavior," never as "empty set."
    """
    return {
        row["model_id"]: frozenset(row["trim_ids"])
        for row in load_current_retail_sets(data_dir=data_dir, year=year)
    }


def resolve_approved_current_trim_ids(model_id: str, *, data_dir: Path | str = DATA_DIR,
                                      year: int = DEFAULT_YEAR) -> frozenset[str] | None:
    """The single answer to "what is CURRENT for this model," or None.

    None means this model has no explicit approved set yet -- the caller's own
    legacy fallback applies. A frozenset (even an empty one, though the loader
    never actually produces one since trim_ids is required nonempty) is always
    the complete and exclusive CURRENT membership for that model.

    For a single ad-hoc lookup only. A caller resolving this for every trim in
    a release build (tdr_bridge/lifecycle.py, vehreg/retail_scope.py) must call
    load_current_retail_index() ONCE for the whole build instead -- this
    function re-reads and re-validates the whole sidecar (which re-loads
    Catalog) on every call, and calling it once per model would turn one
    release build into as many redundant catalog loads as there are
    explicitly managed models.
    """
    return load_current_retail_index(data_dir=data_dir, year=year).get(model_id)


def replace_current_retail_set(*, data_dir: Path | str = DATA_DIR,
                               year: int = DEFAULT_YEAR,
                               model_id: str,
                               trim_ids: list[str],
                               reviewer: str,
                               reviewed_at: str,
                               source_ref: str,
                               notes: str = "",
                               write: bool = False) -> dict[str, Any]:
    """Replace one model's entire approved CURRENT set in a single write.

    Not a merge: the supplied trim_ids become the WHOLE set for this model,
    which is the whole point -- "replace the showroom lineup" is one call, not
    one call per retired trim. Every id is validated against Catalog.trims
    (see validate_current_retail_sets) before anything is written.
    """
    existing = load_current_retail_sets(data_dir=data_dir, year=year)
    merged = [row for row in existing if row["model_id"] != model_id]
    merged.append({
        "model_id": str(model_id or "").strip(),
        "trim_ids": list(trim_ids),
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "source_ref": source_ref,
        "notes": notes,
    })
    candidate = {"schema_version": 1, "models": merged}
    checked = validate_current_retail_sets(candidate, data_dir=data_dir, year=year)
    canonical = {"schema_version": 1, "models": checked}
    before = {"schema_version": 1, "models": existing}
    changed = canonical != before
    destination = current_retail_path(data_dir, year)
    if write and changed:
        _atomic_json(destination, canonical)
    approved_row = next(row for row in checked if row["model_id"] == model_id)
    return {
        "written": bool(write and changed),
        "changed": changed,
        "path": str(destination),
        "model_id": model_id,
        "trim_ids": approved_row["trim_ids"],
    }


__all__ = [
    "CurrentRetailError",
    "current_retail_path",
    "load_current_retail_index",
    "load_current_retail_sets",
    "replace_current_retail_set",
    "resolve_approved_current_trim_ids",
    "validate_current_retail_sets",
]
