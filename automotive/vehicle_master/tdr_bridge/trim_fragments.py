"""Apply verified retail-trim batches without rewriting the base evidence bundle.

The first owner-directory reconciliation lives in vehreg's canonical.json and
reconciliation.json.  Later verified batches are append-only fragments named
canonical_*.json and reconciliation_*.json.  This keeps small research passes
reviewable while preserving deterministic serving releases.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Mapping

from vehreg.catalog import CatalogError, DATA_DIR, DEFAULT_YEAR
from vehreg.taxonomy import Powertrain
from vehreg.trim_reconciliation import (
    TrimResolutionStatus,
    UNRESOLVED_EXEMPTIONS,
    load_reconciliation_state,
)

_SCHEMA_VERSION = 1
_LOCAL_ID = re.compile(r"^[a-z0-9][a-z0-9_]*$")


def _root(data_dir: Path | str, year: int) -> Path:
    return Path(data_dir) / str(year) / "market" / "trims"


def _load(path: Path, key: str) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise CatalogError(f"{path}: unsupported schema {payload.get('schema_version')!r}")
    rows = payload.get(key)
    if not isinstance(rows, list):
        raise CatalogError(f"{path}: {key} must be an array")
    return rows


def _canonical_fragment_paths(data_dir: Path | str, year: int) -> list[Path]:
    return sorted(_root(data_dir, year).glob("canonical_*.json"))


def _reconciliation_fragment_paths(data_dir: Path | str, year: int) -> list[Path]:
    return sorted(_root(data_dir, year).glob("reconciliation_*.json"))


def _source_refs(raw: object, label: str) -> dict[str, list[str]]:
    if not isinstance(raw, Mapping) or not raw:
        raise CatalogError(f"{label}: source_refs must be a nonempty object")
    out: dict[str, list[str]] = {}
    for key, values in raw.items():
        source = str(key).strip()
        values = [values] if isinstance(values, str) else values
        if not source or not isinstance(values, list):
            raise CatalogError(f"{label}: invalid source_refs")
        refs = [str(ref).strip() for ref in values if str(ref).strip()]
        if not refs:
            raise CatalogError(f"{label}: source_refs entries must be nonempty")
        out[source] = list(dict.fromkeys(refs))
    return out


def apply_verified_trim_fragments(
    release: Mapping,
    *,
    data_dir: Path | str = DATA_DIR,
    year: int = DEFAULT_YEAR,
) -> dict:
    """Append exact, evidence-backed MarketTrim identities from small batches."""
    out = deepcopy(dict(release))
    paths = _canonical_fragment_paths(data_dir, year)
    if not paths:
        return out

    models = {
        str(row.get("canonical_id") or ""): row
        for row in out.get("models", []) if isinstance(row, Mapping)
    }
    generations = {
        str(row.get("canonical_id") or ""): row
        for row in out.get("generations", []) if isinstance(row, Mapping)
    }
    brands = {
        str(row.get("canonical_id") or ""): row
        for row in out.get("brands", []) if isinstance(row, Mapping)
    }
    existing_ids = {
        str(row.get("canonical_id") or "")
        for row in out.get("market_trims", []) if isinstance(row, Mapping)
    }
    additions: list[dict] = []

    for path in paths:
        for raw in _load(path, "trims"):
            if not isinstance(raw, Mapping):
                raise CatalogError(f"{path}: trim row must be an object")
            local_id = str(raw.get("id") or "").strip()
            model_id = str(raw.get("model_id") or "").strip()
            generation_id = str(raw.get("generation_id") or "").strip()
            name = str(raw.get("name") or "").strip()
            if not _LOCAL_ID.fullmatch(local_id):
                raise CatalogError(f"{path}: invalid trim id {local_id!r}")
            model = models.get(model_id)
            generation = generations.get(generation_id)
            if model is None:
                raise CatalogError(f"{path}: {local_id}: unknown model {model_id!r}")
            if generation is None or str(generation.get("model_id") or "") != model_id:
                raise CatalogError(f"{path}: {local_id}: generation not under model")
            if not name:
                raise CatalogError(f"{path}: {local_id}: name required")
            try:
                powertrain = Powertrain.parse(raw.get("powertrain"))
            except ValueError as exc:
                raise CatalogError(f"{path}: {local_id}: invalid powertrain") from exc
            if powertrain is Powertrain.UNKNOWN:
                raise CatalogError(f"{path}: {local_id}: exact powertrain required")
            if raw.get("variant_id") not in (None, ""):
                raise CatalogError(f"{path}: {local_id}: variant_id must stay empty")
            refs = _source_refs(raw.get("source_refs"), f"{path}:{local_id}")
            canonical_id = f"{generation_id}.trim.{local_id}"
            if canonical_id in existing_ids:
                raise CatalogError(f"{path}: duplicate canonical trim {canonical_id}")
            existing_ids.add(canonical_id)

            aliases = raw.get("aliases") or []
            specs = raw.get("specs") or {}
            if not isinstance(aliases, list) or not all(isinstance(x, str) for x in aliases):
                raise CatalogError(f"{path}: {local_id}: aliases must be strings")
            if not isinstance(specs, Mapping):
                raise CatalogError(f"{path}: {local_id}: specs must be an object")
            brand = brands.get(str(model.get("brand_id") or ""), {})
            spec_payload = {
                "id": canonical_id,
                "generation_id": generation_id,
                "name": name,
                "powertrain": powertrain.value,
                "variant_id": None,
                "aliases": aliases,
                "source_refs": refs,
                **dict(specs),
            }
            additions.append({
                "canonical_id": canonical_id,
                "model_id": model_id,
                "generation_id": generation_id,
                "variant_id": None,
                "name": name,
                "powertrain": powertrain.value,
                "status": "UNVERIFIED",
                "payload": {
                    "catalog_year": year,
                    "price_as_of": out.get("as_of"),
                    "model_id": model_id,
                    "model": model.get("name_en"),
                    "brand": brand.get("name_en"),
                    "specs": spec_payload,
                    "current_list_price": None,
                    "price_history": [],
                    "ecosticker_evidence": None,
                    "comparable_specs": [],
                },
                "current_list_price": None,
                "campaign_quote": {},
                "price_history": [],
                "source_refs": refs,
            })

    out["market_trims"] = sorted(
        list(out.get("market_trims", [])) + additions,
        key=lambda row: str(row.get("canonical_id") or ""),
    )
    counts = dict(out.get("counts") or {})
    counts["market_trims"] = len(out["market_trims"])
    out["counts"] = counts
    return out


def load_reconciliation_with_overrides(
    data_dir: Path | str = DATA_DIR,
    year: int = DEFAULT_YEAR,
) -> dict:
    """Return base owner reconciliation with later explicit model overrides."""
    base = load_reconciliation_state(data_dir=data_dir, year=year)
    order = [str(row.get("model_id") or "") for row in base.get("models", [])]
    rows = {str(row.get("model_id") or ""): dict(row) for row in base.get("models", [])}

    for path in _reconciliation_fragment_paths(data_dir, year):
        for raw in _load(path, "models"):
            if not isinstance(raw, Mapping):
                raise CatalogError(f"{path}: reconciliation row must be an object")
            model_id = str(raw.get("model_id") or "").strip()
            if model_id not in rows:
                raise CatalogError(f"{path}: override references untracked model {model_id!r}")
            if raw.get("supersedes") is not True:
                raise CatalogError(f"{path}: {model_id}: supersedes=true required")
            try:
                TrimResolutionStatus(str(raw.get("status") or ""))
            except ValueError as exc:
                raise CatalogError(f"{path}: {model_id}: invalid status") from exc
            count = raw.get("source_trim_count")
            refs = raw.get("source_refs")
            reason = str(raw.get("reason") or "").strip()
            if type(count) is not int or count < 0:
                raise CatalogError(f"{path}: {model_id}: invalid source_trim_count")
            if not isinstance(refs, list) or not refs or not all(isinstance(x, str) and x.strip() for x in refs):
                raise CatalogError(f"{path}: {model_id}: nonempty source_refs required")
            if not reason:
                raise CatalogError(f"{path}: {model_id}: reason required")
            replacement = dict(raw)
            replacement.pop("supersedes", None)
            rows[model_id] = replacement

    return {"schema_version": _SCHEMA_VERSION, "models": [rows[model_id] for model_id in order]}


def _flatten_refs(trim: Mapping) -> set[str]:
    refs = trim.get("source_refs")
    if not isinstance(refs, Mapping):
        return set()
    out: set[str] = set()
    for values in refs.values():
        values = [values] if isinstance(values, str) else values
        if isinstance(values, list):
            out.update(str(value).strip() for value in values if str(value).strip())
    return out


def release_reconciliation_report_with_overrides(
    release: Mapping,
    *,
    data_dir: Path | str = DATA_DIR,
    year: int = DEFAULT_YEAR,
) -> dict:
    state = load_reconciliation_with_overrides(data_dir=data_dir, year=year)
    model_ids = {
        str(row.get("canonical_id") or "")
        for row in release.get("models", []) if isinstance(row, Mapping)
    }
    trims_by_model: dict[str, list[Mapping]] = {}
    for trim in release.get("market_trims", []):
        if isinstance(trim, Mapping):
            trims_by_model.setdefault(str(trim.get("model_id") or ""), []).append(trim)

    rows: list[dict] = []
    blockers: list[dict] = []
    counts: dict[str, int] = {}
    for raw in state.get("models", []):
        model_id = str(raw.get("model_id") or "")
        declared = str(raw.get("status") or "")
        source_refs = {str(ref).strip() for ref in raw.get("source_refs") or [] if str(ref).strip()}
        source_count = int(raw.get("source_trim_count") or 0)
        canonical_rows = trims_by_model.get(model_id, [])
        source_backed = [trim for trim in canonical_rows if _flatten_refs(trim) & source_refs]
        promoted = len(source_backed)
        unresolved = max(source_count - promoted, 0)
        effective = "CANONICAL" if unresolved == 0 else declared
        row = {
            "model_id": model_id,
            "source_trim_count": source_count,
            "canonical_trim_count": len(canonical_rows),
            "canonical_source_trim_count": promoted,
            "unresolved_source_trim_count": unresolved,
            "declared_status": declared,
            "status": effective,
            "reason": raw.get("reason", ""),
            "source_refs": sorted(source_refs),
        }
        if model_id not in model_ids:
            row["blocker"] = "SOURCE_EVIDENCE_MODEL_NOT_IN_RELEASE"
            blockers.append(row)
        elif unresolved:
            try:
                status = TrimResolutionStatus(declared)
            except ValueError:
                status = None
            if status not in UNRESOLVED_EXEMPTIONS:
                row["blocker"] = "SOURCE_EVIDENCE_NOT_FULLY_PROMOTED"
                blockers.append(row)
        counts[effective] = counts.get(effective, 0) + 1
        rows.append(row)

    return {
        "schema_version": _SCHEMA_VERSION,
        "tracked_models": len(rows),
        "counts": dict(sorted(counts.items())),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "models": rows,
    }


__all__ = [
    "apply_verified_trim_fragments",
    "load_reconciliation_with_overrides",
    "release_reconciliation_report_with_overrides",
]
