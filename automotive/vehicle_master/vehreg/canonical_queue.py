"""Adapter/worker contract for Phase-C Supabase canonical command rows.

The queue is intentionally not a second master. A row is executable only when
it already carries a verified canonical model ID. Legacy child powertrain/trim
payloads are rejected until those child identities have their own verified
crosswalks; model-name similarity never creates a Variant/MarketTrim mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from .canonical_write import CanonicalWriteError, CanonicalWritePipeline, WriteResult


class CanonicalQueueError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AdaptedQueueCommand:
    command: dict[str, Any]
    ignored_legacy_fields: tuple[str, ...] = ()


def _canonical_generation_for_model(catalog: Catalog, model_id: str):
    generations = catalog.generations_of(model_id)
    if len(generations) != 1:
        raise CanonicalQueueError(
            f"{model_id}: model-level legacy row cannot choose between "
            f"{len(generations)} canonical generations; verify generation crosswalk first"
        )
    return generations[0]


def adapt_legacy_model_shadow(row: dict[str, Any], *,
                              data_dir: Path | str = DATA_DIR,
                              year: int = DEFAULT_YEAR) -> AdaptedQueueCommand:
    """Convert one verified legacy model shadow row into a canonical command.

    Only facts whose semantic owner is unambiguous at model/generation level are
    carried. Legacy powertrain/trim children require separate verified child
    mappings and therefore block the adapter rather than being guessed.
    """
    if row.get("status") != "queued":
        raise CanonicalQueueError("only queued rows are executable")
    canonical_id = str(row.get("canonical_id") or "").strip()
    if not canonical_id:
        raise CanonicalQueueError("verified canonical_id is required")
    payload = row.get("payload")
    if not isinstance(payload, dict):
        raise CanonicalQueueError("queue payload must be an object")

    powertrains = payload.get("powertrains") or []
    trims = payload.get("trims") or []
    if powertrains or trims:
        raise CanonicalQueueError(
            "legacy child powertrain/trim rows require verified child crosswalks; "
            "do not infer Variant or MarketTrim identity"
        )

    catalog = Catalog.load(data_dir, year)
    model = catalog.models.get(canonical_id)
    if model is None:
        raise CanonicalQueueError(f"unknown canonical model {canonical_id!r}")
    brand = catalog.brands[model.brand_id]
    generation = _canonical_generation_for_model(catalog, canonical_id)
    legacy_model = payload.get("model") or {}
    if not isinstance(legacy_model, dict):
        raise CanonicalQueueError("legacy model payload must be an object")

    model_patch: dict[str, Any] = {"id": canonical_id.split(".", 1)[1]}
    ignored: list[str] = []

    # Safe model-grain facts. Body-type parser in the canonical loader accepts
    # reader-facing spellings such as "Crossover" without changing taxonomy.
    for source_key, target_key in (
        ("name_th", "name_th"),
        ("body_type", "body_type"),
        ("notes", "notes"),
    ):
        value = legacy_model.get(source_key)
        if value not in (None, ""):
            model_patch[target_key] = value

    generation_patch: dict[str, Any] = {"code": generation.code or generation.id.rsplit(".", 1)[-1]}
    for source_key, target_key in (("segment", "segment"), ("seats", "seats")):
        value = legacy_model.get(source_key)
        if value not in (None, ""):
            generation_patch[target_key] = value

    # These legacy fields either belong to another canonical layer, require
    # evidence the legacy editor does not carry, or are TDR-only editorial.
    for key in (
        "generation", "market_position", "production_type", "production_country",
        "launch_quarter", "launch_year", "payload_capacity_kg", "length_mm",
        "width_mm", "wheelbase_mm", "status", "unconfirmed_fields",
        "brand_id", "slug",
    ):
        if legacy_model.get(key) not in (None, "", [], {}):
            ignored.append(key)

    command_key = str(row.get("command_key") or row.get("id") or "").strip()
    if not command_key:
        raise CanonicalQueueError("queue row needs command_key or id")
    command = {
        "command_id": command_key,
        "operation": "UPSERT_MODEL_BUNDLE",
        "year": year,
        "actor": str(row.get("actor") or "tdr-admin"),
        "reason": str(row.get("reason") or "Phase C legacy shadow adapter"),
        "canonical_id": canonical_id,
        "submitted_at": str(row.get("created_at") or
                            datetime.now(timezone.utc).isoformat(timespec="seconds")),
        "payload": {
            "brand": {
                "id": brand.id,
                "name_en": brand.name_en,
                "name_th": brand.name_th,
            },
            "model": model_patch,
            "generation": generation_patch,
            "variants": [],
            "trims": [],
        },
    }
    return AdaptedQueueCommand(command, tuple(sorted(ignored)))


def process_legacy_model_shadow(row: dict[str, Any], *,
                                data_dir: Path | str = DATA_DIR,
                                year: int = DEFAULT_YEAR) -> tuple[WriteResult, AdaptedQueueCommand]:
    adapted = adapt_legacy_model_shadow(row, data_dir=data_dir, year=year)
    result = CanonicalWritePipeline(data_dir).apply(adapted.command)
    return result, adapted


def revision_payload(data_dir: Path | str, year: int, revision_id: str) -> dict[str, Any]:
    """Read the exact canonical revision that a DB worker should mirror back."""
    path = Path(data_dir) / str(year) / "canonical_state" / "revisions.jsonl"
    if not path.is_file():
        raise CanonicalQueueError("canonical revision log does not exist")
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("revision_id") == revision_id:
            return row
    raise CanonicalQueueError(f"revision {revision_id!r} not found")


__all__ = [
    "AdaptedQueueCommand",
    "CanonicalQueueError",
    "adapt_legacy_model_shadow",
    "process_legacy_model_shadow",
    "revision_payload",
]
