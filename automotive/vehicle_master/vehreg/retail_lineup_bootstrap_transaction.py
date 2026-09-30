"""Chunk 4: whole-workbook transaction boundary for Retail Lineup Bootstrap.

The immutable plan is applied only to a copied canonical tree.  The staged tree
must then build the same enriched serving release used by production.  Only
files reported by the staged apply engine are promoted, and promotion rolls
back files already replaced if a later replacement raises.

This module still has no Admin/Supabase integration.  Chunk 5 owns durable
preview-plan state; Chunk 6 owns the Admin UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from tdr_bridge.release import ReleaseBuilder
from tdr_bridge.release_enriched import enrich_release

from .catalog import Catalog, DATA_DIR
from .current_retail import load_current_retail_index
from .retail_lifecycle_review import load_trim_lifecycle_decisions
from .retail_lineup_bootstrap import (
    LineupAction,
    RetailLineupBootstrapError,
    RetailLineupPlan,
    baseline_hash_for_models,
)
from .retail_lineup_bootstrap_apply import (
    RetailLineupApplyResult,
    apply_retail_lineup_plan_to_staged_tree,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = ROOT / "integration_data" / "tdr_2026-09-09.json"
DEFAULT_OVERRIDES = ROOT / "integration_data" / "crosswalk_overrides.json"


@dataclass(frozen=True, slots=True)
class RetailLineupReleaseValidation:
    release_id: str
    source_hash: str
    counts: dict[str, int]
    trim_reconciliation_counts: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "source_hash": self.source_hash,
            "counts": dict(self.counts),
            "trim_reconciliation_counts": dict(self.trim_reconciliation_counts),
        }


@dataclass(frozen=True, slots=True)
class RetailLineupTransactionResult:
    plan_hash: str
    baseline_hash: str
    changed_files: tuple[str, ...]
    counts: dict[str, int]
    release: RetailLineupReleaseValidation
    idempotent_replay: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "plan_hash": self.plan_hash,
            "baseline_hash": self.baseline_hash,
            "changed_files": list(self.changed_files),
            "counts": dict(self.counts),
            "release": self.release.as_dict(),
            "idempotent_replay": self.idempotent_replay,
        }


def _json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RetailLineupBootstrapError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RetailLineupBootstrapError(f"{label} {path} must contain a JSON object")
    return value


def _safe_relative(raw: str | Path) -> Path:
    path = Path(str(raw))
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise RetailLineupBootstrapError(f"unsafe staged changed path {raw!r}")
    return path


def _live_baseline(plan: RetailLineupPlan, data_dir: Path) -> str:
    catalog = Catalog.load(data_dir, int(plan.catalog_year))
    current = load_current_retail_index(data_dir=data_dir, year=int(plan.catalog_year))
    lifecycle = load_trim_lifecycle_decisions(data_dir=data_dir, year=int(plan.catalog_year))
    return baseline_hash_for_models(
        catalog,
        [model.model_id for model in plan.models],
        current_retail_index=current,
        lifecycle_decisions=lifecycle,
        as_of=plan.as_of,
    )


def validate_retail_lineup_staged_release(
    plan: RetailLineupPlan,
    *,
    data_dir: Path | str,
    inventory_path: Path | str = DEFAULT_INVENTORY,
    overrides_path: Path | str = DEFAULT_OVERRIDES,
) -> RetailLineupReleaseValidation:
    """Build and verify the enriched serving release from the staged tree."""
    staged = Path(data_dir)
    year = int(plan.catalog_year)

    Catalog.load(staged, year)

    inventory = _json_object(Path(inventory_path), label="TDR inventory")
    overrides = _json_object(Path(overrides_path), label="crosswalk overrides")
    base = ReleaseBuilder(
        inventory,
        data_dir=staged,
        year=year,
        canonical_revision=f"bootstrap-preview:{plan.plan_hash}",
        overrides=overrides,
    ).build(as_of=date.fromisoformat(plan.as_of))
    release = enrich_release(
        base,
        data_dir=staged,
        source_aliases=overrides.get("source_aliases", {}),
    )

    rows_by_id: dict[str, dict[str, Any]] = {}
    for row in release.get("market_trims", []):
        trim_id = str(row.get("canonical_id") or "").strip()
        if not trim_id:
            continue
        if trim_id in rows_by_id:
            raise RetailLineupBootstrapError(
                f"serving release duplicated MarketTrim {trim_id}")
        rows_by_id[trim_id] = row

    for model in plan.models:
        serving_current = {
            trim_id for trim_id, row in rows_by_id.items()
            if str(row.get("model_id") or "") == model.model_id
            and str(row.get("status") or "").upper() == "CURRENT"
        }
        expected = set(model.target_current_trim_ids)
        if serving_current != expected:
            raise RetailLineupBootstrapError(
                f"serving CURRENT mismatch for {model.model_id}: "
                f"expected {sorted(expected)}, got {sorted(serving_current)}")

        for item in model.items:
            row = rows_by_id.get(item.canonical_trim_id)
            if row is None:
                raise RetailLineupBootstrapError(
                    f"serving release omitted MarketTrim {item.canonical_trim_id}")
            status = str(row.get("status") or "").upper()
            expected_status = "HISTORICAL" if item.action is LineupAction.ARCHIVE else "CURRENT"
            if status != expected_status:
                raise RetailLineupBootstrapError(
                    f"serving status mismatch for {item.canonical_trim_id}: "
                    f"expected {expected_status}, got {status or '<blank>'}")

    reconciliation = release.get("trim_reconciliation") or {}
    counts = reconciliation.get("counts") or {}
    return RetailLineupReleaseValidation(
        release_id=str(release.get("release_id") or ""),
        source_hash=str(release.get("source_hash") or ""),
        counts={str(k): int(v) for k, v in (release.get("counts") or {}).items()},
        trim_reconciliation_counts={str(k): int(v) for k, v in counts.items()
        if isinstance(v, (int, bool))},
    )


def _promotion_order(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    return tuple(sorted(paths, key=lambda path: ("canonical_state" in path.parts, str(path))))


def _cleanup_promotion_temps(live_data: Path, ordered: tuple[Path, ...]) -> None:
    for relative in ordered:
        target = live_data / relative
        for suffix in (".rlb-tmp", ".rlb-rollback"):
            try:
                target.with_name(target.name + suffix).unlink(missing_ok=True)
            except OSError:
                pass


def _promote_with_rollback(staged_data: Path, live_data: Path,
                           changed_files: tuple[str, ...]) -> tuple[str, ...]:
    relatives = tuple(_safe_relative(raw) for raw in changed_files)
    if len(set(relatives)) != len(relatives):
        raise RetailLineupBootstrapError("staged apply returned duplicate changed paths")
    ordered = _promotion_order(relatives)

    for relative in ordered:
        source = staged_data / relative
        if not source.is_file():
            raise RetailLineupBootstrapError(
                f"staged apply reported missing changed file {relative}")

    originals: dict[Path, bytes | None] = {}
    for relative in ordered:
        target = live_data / relative
        originals[relative] = target.read_bytes() if target.is_file() else None

    promoted: list[Path] = []
    try:
        for relative in ordered:
            source = staged_data / relative
            target = live_data / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".rlb-tmp")
            temporary.write_bytes(source.read_bytes())
            os.replace(temporary, target)
            promoted.append(relative)
    except Exception as exc:
        rollback_errors: list[str] = []
        for relative in reversed(promoted):
            target = live_data / relative
            original = originals[relative]
            try:
                if original is None:
                    target.unlink(missing_ok=True)
                else:
                    temporary = target.with_name(target.name + ".rlb-rollback")
                    temporary.write_bytes(original)
                    os.replace(temporary, target)
            except Exception as rollback_exc:  # pragma: no cover - catastrophic filesystem failure
                rollback_errors.append(f"{relative}: {rollback_exc}")
        _cleanup_promotion_temps(live_data, ordered)
        detail = f"; rollback failures: {rollback_errors}" if rollback_errors else ""
        raise RetailLineupBootstrapError(
            f"bootstrap promotion failed and rollback was attempted: {exc}{detail}") from exc

    _cleanup_promotion_temps(live_data, ordered)
    return tuple(str(path) for path in ordered)


def apply_retail_lineup_plan_atomically(
    plan: RetailLineupPlan,
    *,
    data_dir: Path | str = DATA_DIR,
    actor: str,
    submitted_at: str,
    source_ref: str = "",
    reason: str = "",
    inventory_path: Path | str = DEFAULT_INVENTORY,
    overrides_path: Path | str = DEFAULT_OVERRIDES,
) -> RetailLineupTransactionResult:
    """Apply one immutable workbook plan as a whole-tree transaction.

    Any apply/validation failure happens only in the copied tree. Live files are
    considered for promotion only after the staged enriched release passes.
    Immediately before promotion the target-model baseline is checked again so
    a concurrent canonical edit cannot be silently overwritten.
    """
    live = Path(data_dir)
    if not live.is_dir():
        raise RetailLineupBootstrapError(f"canonical data directory does not exist: {live}")

    with tempfile.TemporaryDirectory(prefix="tdr-retail-lineup-bootstrap-") as temp:
        staged = Path(temp) / "data"
        shutil.copytree(live, staged)

        applied: RetailLineupApplyResult = apply_retail_lineup_plan_to_staged_tree(
            plan,
            data_dir=staged,
            actor=actor,
            submitted_at=submitted_at,
            source_ref=source_ref,
            reason=reason,
        )
        release = validate_retail_lineup_staged_release(
            plan,
            data_dir=staged,
            inventory_path=inventory_path,
            overrides_path=overrides_path,
        )

        if applied.idempotent_replay and not applied.changed_files:
            promoted: tuple[str, ...] = ()
        else:
            current_live_baseline = _live_baseline(plan, live)
            if current_live_baseline != plan.baseline_hash:
                raise RetailLineupBootstrapError(
                    "STALE_BASELINE_BEFORE_PROMOTION: live canonical state changed "
                    f"after staging ({plan.baseline_hash} != {current_live_baseline})")
            promoted = _promote_with_rollback(staged, live, applied.changed_files)

    return RetailLineupTransactionResult(
        plan_hash=plan.plan_hash,
        baseline_hash=plan.baseline_hash,
        changed_files=promoted,
        counts=dict(applied.counts),
        release=release,
        idempotent_replay=applied.idempotent_replay,
    )


__all__ = [
    "RetailLineupReleaseValidation",
    "RetailLineupTransactionResult",
    "apply_retail_lineup_plan_atomically",
    "validate_retail_lineup_staged_release",
]
