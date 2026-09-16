"""Row-level dispositions for source trim evidence that should not be canonical.

A source row can be known-wrong for the current canonical retail surface without
being "unknown": a source may describe an obsolete lineup, aggregate two real
SKUs, or explicitly name a non-market concept. Such rows remain auditable here
instead of being counted forever as unresolved research debt.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Mapping

from vehreg.catalog import CatalogError, DATA_DIR, DEFAULT_YEAR
from tdr_bridge.trim_fragments import release_reconciliation_report_with_overrides

SCHEMA_VERSION = 1
ALLOWED_DISPOSITIONS = frozenset({
    "SUPERSEDED_BY_VERIFIED_LINEUP",
    "AGGREGATE_SOURCE_ROW",
    "NON_MARKET_SOURCE_ROW",
    "DUPLICATE_SOURCE_ROW",
})


def _trim_root(data_dir: Path | str, year: int) -> Path:
    return Path(data_dir) / str(year) / "market" / "trims"


def _disposition_paths(data_dir: Path | str, year: int) -> list[Path]:
    return sorted(_trim_root(data_dir, year).glob("source_dispositions_*.json"))


def _owner_source_rows(data_dir: Path | str, year: int) -> dict[str, set[str]]:
    """Index the owner evidence itself so disposition names cannot be invented."""
    root = _trim_root(data_dir, year) / "research"
    out: dict[str, set[str]] = {}
    for path in sorted(root.glob("*/records_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for record in payload.get("records", []):
            if not isinstance(record, Mapping):
                continue
            source_ref = str(record.get("source_ref") or "").strip()
            names = record.get("submodels_trims") or []
            if source_ref and isinstance(names, list):
                out.setdefault(source_ref, set()).update(
                    str(name).strip() for name in names if str(name).strip()
                )
    return out


def load_source_dispositions(
    data_dir: Path | str = DATA_DIR,
    year: int = DEFAULT_YEAR,
) -> dict[str, list[dict]]:
    owner_rows = _owner_source_rows(data_dir, year)
    by_model: dict[str, list[dict]] = {}
    seen: set[tuple[str, str, str]] = set()

    for path in _disposition_paths(data_dir, year):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise CatalogError(f"{path}: unsupported schema {payload.get('schema_version')!r}")
        rows = payload.get("dispositions")
        if not isinstance(rows, list):
            raise CatalogError(f"{path}: dispositions must be an array")
        for raw in rows:
            if not isinstance(raw, Mapping):
                raise CatalogError(f"{path}: disposition row must be an object")
            model_id = str(raw.get("model_id") or "").strip()
            source_ref = str(raw.get("source_ref") or "").strip()
            source_name = str(raw.get("source_name") or "").strip()
            disposition = str(raw.get("disposition") or "").strip()
            reason = str(raw.get("reason") or "").strip()
            evidence_refs = raw.get("evidence_refs")
            if not model_id or not source_ref or not source_name:
                raise CatalogError(f"{path}: model_id, source_ref and source_name required")
            if disposition not in ALLOWED_DISPOSITIONS:
                raise CatalogError(f"{path}: {source_name}: invalid disposition {disposition!r}")
            if not reason:
                raise CatalogError(f"{path}: {source_name}: reason required")
            if not isinstance(evidence_refs, list) or not evidence_refs or not all(
                isinstance(ref, str) and ref.strip() for ref in evidence_refs
            ):
                raise CatalogError(f"{path}: {source_name}: nonempty evidence_refs required")
            if source_ref not in owner_rows:
                raise CatalogError(f"{path}: unknown owner source_ref {source_ref!r}")
            if source_name not in owner_rows[source_ref]:
                raise CatalogError(
                    f"{path}: {source_name!r} is not a source row under {source_ref}"
                )
            key = (model_id, source_ref, source_name)
            if key in seen:
                raise CatalogError(f"{path}: duplicate disposition for {source_ref}:{source_name}")
            seen.add(key)
            row = dict(raw)
            row["evidence_refs"] = [str(ref).strip() for ref in evidence_refs]
            by_model.setdefault(model_id, []).append(row)
    return by_model


def release_reconciliation_report_with_dispositions(
    release: Mapping,
    *,
    data_dir: Path | str = DATA_DIR,
    year: int = DEFAULT_YEAR,
) -> dict:
    """Split accounted source rows into canonical, disposed, and truly unresolved."""
    base = release_reconciliation_report_with_overrides(
        release, data_dir=data_dir, year=year,
    )
    out = deepcopy(base)
    dispositions = load_source_dispositions(data_dir=data_dir, year=year)
    blockers = [dict(row) for row in out.get("blockers", [])]
    blocker_by_model = {str(row.get("model_id") or ""): row for row in blockers}
    counts: dict[str, int] = {}

    total_disposed = 0
    total_unresolved = 0
    for row in out.get("models", []):
        model_id = str(row.get("model_id") or "")
        source_refs = set(row.get("source_refs") or [])
        model_dispositions = dispositions.get(model_id, [])
        for disposition in model_dispositions:
            if disposition["source_ref"] not in source_refs:
                raise CatalogError(
                    f"{model_id}: disposition source_ref is not tracked by reconciliation"
                )
        disposed = len(model_dispositions)
        prior_unresolved = int(row.get("unresolved_source_trim_count") or 0)
        if disposed > prior_unresolved:
            raise CatalogError(
                f"{model_id}: {disposed} disposed source rows exceed {prior_unresolved} unresolved rows"
            )
        genuine_unresolved = prior_unresolved - disposed
        source_count = int(row.get("source_trim_count") or 0)
        promoted = int(row.get("canonical_source_trim_count") or 0)
        if promoted + disposed + genuine_unresolved != source_count:
            raise CatalogError(f"{model_id}: source-row accounting does not balance")

        row["disposed_source_trim_count"] = disposed
        row["source_dispositions"] = model_dispositions
        row["unresolved_source_trim_count"] = genuine_unresolved
        if genuine_unresolved == 0:
            declared = str(row.get("declared_status") or "")
            if declared == "NON_MARKET":
                row["status"] = "NON_MARKET"
            else:
                row["status"] = "RECONCILED" if disposed else "CANONICAL"
            blocker_by_model.pop(model_id, None)
        total_disposed += disposed
        total_unresolved += genuine_unresolved
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    out["counts"] = dict(sorted(counts.items()))
    out["blockers"] = list(blocker_by_model.values())
    out["blocker_count"] = len(out["blockers"])
    out["source_row_totals"] = {
        "source_trim_rows": sum(int(row.get("source_trim_count") or 0) for row in out["models"]),
        "canonical_source_rows": sum(int(row.get("canonical_source_trim_count") or 0) for row in out["models"]),
        "disposed_source_rows": total_disposed,
        "unresolved_source_rows": total_unresolved,
    }
    return out


__all__ = [
    "ALLOWED_DISPOSITIONS",
    "load_source_dispositions",
    "release_reconciliation_report_with_dispositions",
]
