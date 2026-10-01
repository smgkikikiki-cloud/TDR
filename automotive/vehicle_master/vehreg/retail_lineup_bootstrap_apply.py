"""Chunk 2: apply an immutable Retail Lineup Bootstrap plan to a staged tree.

This module has no Excel/Admin/Supabase integration. The caller owns the staged
``data_dir``; Chunk 4 will add whole-workbook promotion/rollback around it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from .canonical_write import CanonicalWritePipeline
from .catalog import Catalog
from .current_retail import load_current_retail_index, replace_current_retail_set
from .normalize import slug
from .retail_lifecycle_review import (
    load_trim_lifecycle_decisions,
    upsert_bootstrap_trim_lifecycle_disposition,
)
from .retail_lineup_bootstrap import (
    LineupAction, RetailLineupBootstrapError, RetailLineupPlan,
    baseline_hash_for_models,
)


@dataclass(frozen=True, slots=True)
class RetailLineupApplyResult:
    plan_hash: str
    baseline_hash: str
    changed_files: tuple[str, ...]
    create_revision_ids: tuple[str, ...]
    counts: dict[str, int]
    idempotent_replay: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "plan_hash": self.plan_hash,
            "baseline_hash": self.baseline_hash,
            "changed_files": list(self.changed_files),
            "create_revision_ids": list(self.create_revision_ids),
            "counts": dict(self.counts),
            "idempotent_replay": self.idempotent_replay,
        }


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _plan_hash(plan: RetailLineupPlan) -> str:
    return _hash({
        "schema_version": plan.schema_version,
        "as_of": plan.as_of,
        "catalog_year": plan.catalog_year,
        "base_release_id": plan.base_release_id,
        "baseline_hash": plan.baseline_hash,
        "models": [model.as_dict() for model in plan.models],
    })


def _audit_inputs(actor: str, submitted_at: str, source_ref: str) -> tuple[str, datetime, str]:
    actor = str(actor or "").strip()
    if not actor or actor.lower() in {"system", "agent", "agent-proposed"}:
        raise RetailLineupBootstrapError("bootstrap apply requires an explicit HUMAN actor")
    try:
        submitted = datetime.fromisoformat(str(submitted_at).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RetailLineupBootstrapError("submitted_at must be ISO-8601") from exc
    if submitted.tzinfo is None:
        raise RetailLineupBootstrapError("submitted_at must include timezone")
    source_ref = str(source_ref or "").strip()
    if source_ref and not source_ref.startswith(("https://", "http://")):
        raise RetailLineupBootstrapError("source_ref, if supplied, must be an http(s) URL")
    return actor, submitted, source_ref


def _decisions(root: Path, year: int) -> dict[str, dict[str, Any]]:
    return {row["trim_id"]: row for row in load_trim_lifecycle_decisions(
        data_dir=root, year=year)}


def _post_state_matches(plan: RetailLineupPlan, root: Path, year: int) -> bool:
    try:
        catalog = Catalog.load(root, year)
        current = load_current_retail_index(data_dir=root, year=year)
        decisions = _decisions(root, year)
    except (OSError, ValueError):
        return False
    for model in plan.models:
        if set(current.get(model.model_id, ())) != set(model.target_current_trim_ids):
            return False
        for item in model.items:
            trim = catalog.trims.get(item.canonical_trim_id)
            if item.action is LineupAction.ARCHIVE:
                if trim is None or decisions.get(item.canonical_trim_id, {}).get("status") != "HISTORICAL":
                    return False
                continue
            if trim is None or str(trim.generation_id) != item.generation_id:
                return False
            held_pt = str(getattr(trim.powertrain, "value", trim.powertrain)).strip()
            if str(trim.name).strip() != item.trim_name or held_pt != item.powertrain:
                return False
            if item.reopen_required and decisions.get(item.canonical_trim_id, {}).get("status") == "HISTORICAL":
                return False
    return True


def _relative(root: Path, raw: str | Path) -> str:
    try:
        return str(Path(raw).relative_to(root))
    except ValueError as exc:
        raise RetailLineupBootstrapError(f"bootstrap writer escaped staged tree: {raw}") from exc


def _create_commands(plan: RetailLineupPlan, catalog: Catalog,
                     actor: str, submitted_at: str, reason: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Any]] = {}
    for model in plan.models:
        for item in model.items:
            if item.action is LineupAction.CREATE:
                grouped.setdefault((item.model_id, item.generation_id), []).append(item)
    commands = []
    for (model_id, generation_id), items in sorted(grouped.items()):
        model, gen = catalog.models.get(model_id), catalog.generations.get(generation_id)
        if model is None or gen is None or str(gen.model_id) != model_id:
            raise RetailLineupBootstrapError(f"unknown CREATE parent {model_id}/{generation_id}")
        code = str(getattr(gen, "code", "") or "").strip()
        if not code or f"{model_id}.{slug(code)}" != generation_id:
            raise RetailLineupBootstrapError(f"generation {generation_id} has no reproducible canonical code")
        brand_id = str(getattr(model, "brand_id", "") or "")
        brand = catalog.brands.get(brand_id)
        if brand is None:
            raise RetailLineupBootstrapError(f"unknown brand {brand_id!r}")
        digest = hashlib.sha256(f"{model_id}|{generation_id}".encode()).hexdigest()[:10]
        commands.append({
            "operation": "UPSERT_MODEL_BUNDLE",
            "command_id": f"rlb-{plan.plan_hash[:12]}-create-{digest}",
            "year": int(plan.catalog_year or catalog.year),
            "actor": actor, "reason": reason, "submitted_at": submitted_at,
            "canonical_id": model_id,
            "payload": {
                "brand": {"id": brand_id, "name_en": str(brand.name_en)},
                "model": {}, "generation": {"code": code}, "variants": [],
                "trims": [{
                    "canonical_id": item.canonical_trim_id,
                    "name": item.trim_name,
                    "powertrain": item.powertrain,
                    "aliases": [],
                } for item in sorted(items, key=lambda x: x.canonical_trim_id)],
            },
        })
    return commands


def apply_retail_lineup_plan_to_staged_tree(
    plan: RetailLineupPlan, *, data_dir: Path | str, actor: str,
    submitted_at: str, source_ref: str = "", reason: str = "",
) -> RetailLineupApplyResult:
    """Apply CREATE -> REOPEN -> CURRENT SET -> ARCHIVE on a caller-owned stage."""
    root = Path(data_dir)
    if not root.is_dir():
        raise RetailLineupBootstrapError(f"canonical data directory does not exist: {root}")
    if plan.schema_version != 1 or _plan_hash(plan) != plan.plan_hash:
        raise RetailLineupBootstrapError("PLAN_HASH_MISMATCH: immutable plan content changed")
    actor, submitted, source_ref = _audit_inputs(actor, submitted_at, source_ref)
    year = int(plan.catalog_year or 0)
    if year < 2000 or year > 2100:
        raise RetailLineupBootstrapError("plan.catalog_year is outside supported range")

    catalog = Catalog.load(root, year)
    current = load_current_retail_index(data_dir=root, year=year)
    decisions = load_trim_lifecycle_decisions(data_dir=root, year=year)
    actual = baseline_hash_for_models(
        catalog, [m.model_id for m in plan.models], current_retail_index=current,
        lifecycle_decisions=decisions, as_of=plan.as_of)
    if actual != plan.baseline_hash:
        if _post_state_matches(plan, root, year):
            return RetailLineupApplyResult(plan.plan_hash, plan.baseline_hash, (), (), dict(plan.counts), True)
        raise RetailLineupBootstrapError(
            f"STALE_BASELINE: plan {plan.baseline_hash} != current {actual}")

    why = str(reason or "").strip() or f"Retail Lineup Bootstrap plan {plan.plan_hash}"
    reviewed_at, changed, revisions = submitted.date().isoformat(), set(), []

    writer = CanonicalWritePipeline(root)
    for command in _create_commands(plan, catalog, actor, submitted.isoformat(), why):
        result = writer.apply(command)
        revisions.append(result.revision_id)
        changed.update(_relative(root, path) for path in result.changed_files)

    for model in plan.models:
        for item in model.items:
            if item.action is LineupAction.REACTIVATE and item.reopen_required:
                result = upsert_bootstrap_trim_lifecycle_disposition(
                    data_dir=root, year=year, trim_id=item.canonical_trim_id,
                    action="reopen", reviewer=actor, reviewed_at=reviewed_at,
                    source_ref=source_ref, notes=why, write=True)
                if result["changed"]:
                    changed.add(_relative(root, result["path"]))

    # Set replacement deliberately comes before archive. Raw UNVERIFIED parent
    # models may record HISTORICAL only after an approved set exists and excludes
    # the trim; intermediate staged state is never served.
    for model in plan.models:
        result = replace_current_retail_set(
            data_dir=root, year=year, model_id=model.model_id,
            trim_ids=list(model.target_current_trim_ids), reviewer=actor,
            reviewed_at=reviewed_at, source_ref=source_ref, notes=why, write=True)
        if result["changed"]:
            changed.add(_relative(root, result["path"]))

    for model in plan.models:
        for item in model.items:
            if item.action is LineupAction.ARCHIVE:
                result = upsert_bootstrap_trim_lifecycle_disposition(
                    data_dir=root, year=year, trim_id=item.canonical_trim_id,
                    action="historical", reviewer=actor, reviewed_at=reviewed_at,
                    source_ref=source_ref, notes=why, write=True)
                if result["changed"]:
                    changed.add(_relative(root, result["path"]))

    Catalog.load(root, year)
    if not _post_state_matches(plan, root, year):
        raise RetailLineupBootstrapError("staged state does not match immutable bootstrap plan")
    return RetailLineupApplyResult(
        plan.plan_hash, plan.baseline_hash, tuple(sorted(changed)),
        tuple(revisions), dict(plan.counts), False)


__all__ = ["RetailLineupApplyResult", "apply_retail_lineup_plan_to_staged_tree"]
