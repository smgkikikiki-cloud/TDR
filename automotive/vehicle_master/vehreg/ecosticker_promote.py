"""Human-gated ECO Sticker -> canonical MarketTrim command export.

ECO Sticker is evidence, not product authority.  The ingest phase may propose a
model/generation/powertrain candidate, but no candidate becomes a MarketTrim
until a human explicitly names the trim in a promotion bundle.

This module does not mutate canonical data.  It validates an immutable ECO
snapshot plus human decisions and emits a normal CanonicalInputBatch whose
commands are UPSERT_MODEL_BUNDLE.  The existing canonical-input worker remains
the only write path.

Deliberate omissions from the generated trim payload:
- ECO recommended price (it remains ECO_STICKER_PRICE evidence, never MSRP)
- tyre / wheel fields
- dimensions / battery fields
Those belong to their own evidence/projection paths and must not hitch a ride on
an identity promotion.
"""

from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from .ecosticker_ingest import (
    AGENT_REVIEWER,
    ECOIngestError,
    load_normalized_snapshot,
    snapshot_dir,
)
from .input_pipeline import CanonicalInputBatch
from .normalize import slug


SCHEMA_VERSION = 1
_ALLOWED_ACTIONS = {"create_market_trim", "reject", "defer"}


class ECOTrimPromotionError(ValueError):
    pass


def _aware_timestamp(raw: object) -> str:
    value = str(raw or "").strip()
    if not value:
        raise ECOTrimPromotionError("reviewed_at is required")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ECOTrimPromotionError("reviewed_at must be ISO-8601") from exc
    if stamp.tzinfo is None:
        raise ECOTrimPromotionError("reviewed_at must include a timezone")
    return stamp.isoformat(timespec="seconds")


def _load_manifest(data_dir: Path | str, year: int, snapshot_date: str) -> dict[str, Any]:
    root = snapshot_dir(data_dir, year, snapshot_date)
    path = root / "manifest.json"
    normalized = root / "normalized.jsonl.gz"
    if not path.is_file() or not normalized.is_file():
        raise ECOTrimPromotionError(f"ECO snapshot {snapshot_date} is incomplete")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        raw = gzip.decompress(normalized.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ECOTrimPromotionError(f"cannot verify ECO snapshot: {exc}") from exc
    expected = str(manifest.get("normalized_sha256") or "")
    actual = hashlib.sha256(raw).hexdigest()
    if not expected or actual != expected:
        raise ECOTrimPromotionError("ECO normalized snapshot hash does not match manifest")
    if str(manifest.get("snapshot_date") or "") != snapshot_date:
        raise ECOTrimPromotionError("ECO manifest snapshot_date mismatch")
    return manifest


def _load_review(path: Path | str, snapshot_date: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ECOTrimPromotionError(f"{path}: invalid promotion review JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ECOTrimPromotionError("promotion review must be an object")
    allowed = {"schema_version", "snapshot_date", "reviewer", "origin", "reviewed_at", "decisions"}
    unknown = set(payload) - allowed
    if unknown:
        raise ECOTrimPromotionError(f"unknown promotion review fields: {sorted(unknown)}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ECOTrimPromotionError(f"schema_version must be {SCHEMA_VERSION}")
    if str(payload.get("snapshot_date") or "") != snapshot_date:
        raise ECOTrimPromotionError("promotion review snapshot_date mismatch")
    reviewer = str(payload.get("reviewer") or "").strip()
    if not reviewer:
        raise ECOTrimPromotionError("reviewer is required")
    if reviewer.lower() == AGENT_REVIEWER or str(payload.get("origin") or "").strip().upper() != "HUMAN":
        raise ECOTrimPromotionError("MarketTrim creation requires explicit HUMAN review")
    reviewed_at = _aware_timestamp(payload.get("reviewed_at"))
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise ECOTrimPromotionError("decisions must be a non-empty array")
    return {**payload, "reviewer": reviewer, "reviewed_at": reviewed_at}


def _existing_eco_sources(catalog: Catalog) -> dict[str, str]:
    out: dict[str, str] = {}
    for trim in catalog.trims.values():
        for source_id in trim.source_refs.get("ecosticker", ()):
            out[str(source_id).lower()] = trim.id
    return out


def _canonical_trim_id(generation_id: str, trim_name: str,
                       powertrain: str, local_id: str = "") -> str:
    identity = slug(local_id or f"{trim_name} {powertrain}")
    if not identity:
        raise ECOTrimPromotionError("trim_local_id/trim_name cannot produce a stable id")
    return f"{generation_id}.trim.{identity}"


def build_market_trim_input_batch(review_path: Path | str, *,
                                  data_dir: Path | str = DATA_DIR,
                                  year: int = DEFAULT_YEAR,
                                  snapshot_date: str) -> dict[str, Any]:
    """Validate human ECO decisions and return a canonical input batch dict.

    The returned value is ready for CanonicalInputBatch / the existing input
    worker.  Nothing is written here.
    """
    manifest = _load_manifest(data_dir, year, snapshot_date)
    review = _load_review(review_path, snapshot_date)
    records = load_normalized_snapshot(data_dir, year, snapshot_date=snapshot_date)
    records_by_source = {str(row.get("source_id") or "").lower(): row for row in records}
    catalog = Catalog.load(data_dir, year)
    attached_sources = _existing_eco_sources(catalog)

    commands: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    seen_trim_ids: set[str] = set()
    for position, raw in enumerate(review["decisions"], 1):
        if not isinstance(raw, dict):
            raise ECOTrimPromotionError(f"decision {position}: must be an object")
        allowed = {"source_id", "action", "trim_name", "trim_local_id", "notes"}
        unknown = set(raw) - allowed
        if unknown:
            raise ECOTrimPromotionError(f"decision {position}: unknown fields {sorted(unknown)}")
        source_id = str(raw.get("source_id") or "").strip().lower()
        if not source_id or source_id not in records_by_source:
            raise ECOTrimPromotionError(f"decision {position}: unknown source_id {source_id!r}")
        if source_id in seen_sources:
            raise ECOTrimPromotionError(f"decision {position}: duplicate source_id {source_id}")
        seen_sources.add(source_id)
        action = str(raw.get("action") or "").strip().lower()
        if action not in _ALLOWED_ACTIONS:
            raise ECOTrimPromotionError(f"decision {position}: unsupported action {action!r}")
        if action != "create_market_trim":
            if raw.get("trim_name") or raw.get("trim_local_id"):
                raise ECOTrimPromotionError(
                    f"decision {position}: trim fields are only allowed for create_market_trim")
            continue

        record = records_by_source[source_id]
        if record.get("review_status") != "ready_for_review":
            raise ECOTrimPromotionError(
                f"decision {position}: ECO row is {record.get('review_status')!r}; "
                "resolve model/generation/powertrain ambiguity before creating a MarketTrim")
        model_id = str(record.get("matched_model_id") or "").strip()
        generation_id = str(record.get("matched_generation_id") or "").strip()
        powertrain = str(record.get("powertrain_candidate") or "").strip().upper()
        if not (model_id and generation_id and powertrain):
            raise ECOTrimPromotionError(
                f"decision {position}: unique model, generation and powertrain are required")
        model = catalog.models.get(model_id)
        if model is None:
            raise ECOTrimPromotionError(f"decision {position}: unknown canonical model {model_id}")
        generation_ids = {generation.id for generation in catalog.generations_of(model_id)}
        if generation_id not in generation_ids:
            raise ECOTrimPromotionError(
                f"decision {position}: generation {generation_id} is not under model {model_id}")

        trim_name = str(raw.get("trim_name") or "").strip()
        if not trim_name:
            raise ECOTrimPromotionError(
                f"decision {position}: HUMAN reviewer must provide trim_name; raw ECO label is not canonical authority")
        trim_id = _canonical_trim_id(
            generation_id, trim_name, powertrain,
            str(raw.get("trim_local_id") or "").strip(),
        )
        if source_id in attached_sources:
            raise ECOTrimPromotionError(
                f"decision {position}: ECO source is already attached to {attached_sources[source_id]}; "
                "use accept_existing_trim rather than creating a duplicate")
        if trim_id in catalog.trims or trim_id in seen_trim_ids:
            raise ECOTrimPromotionError(
                f"decision {position}: canonical MarketTrim {trim_id} already exists or is duplicated")
        seen_trim_ids.add(trim_id)

        brand = catalog.brands[model.brand_id]
        generation = catalog.generations[generation_id]
        command_id = f"eco-trim:{snapshot_date}:{source_id}"
        commands.append({
            "command_id": command_id,
            "operation": "UPSERT_MODEL_BUNDLE",
            "canonical_id": model_id,
            "reason": str(raw.get("notes") or "").strip()
                      or f"HUMAN-reviewed ECO Sticker MarketTrim identity {source_id}",
            "payload": {
                "brand": {
                    "id": brand.id,
                    "name_en": brand.name_en,
                    "name_th": brand.name_th,
                },
                "model": {
                    "id": model_id.split(".", 1)[1],
                    "name_en": model.name_en,
                },
                "generation": {
                    "code": generation.code or generation.id.rsplit(".", 1)[-1],
                },
                "variants": [],
                "trims": [{
                    "canonical_id": trim_id,
                    "name": trim_name,
                    "powertrain": powertrain,
                    "source_refs": {"ecosticker": [source_id]},
                }],
            },
        })

    if not commands:
        raise ECOTrimPromotionError("promotion review contains no create_market_trim decisions")

    digest = hashlib.sha256(
        json.dumps(commands, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    source_hash = str(manifest["normalized_sha256"])
    batch = {
        "schema_version": 1,
        "batch_id": f"eco-trims-{snapshot_date}-{digest}",
        "year": year,
        "source": {
            "kind": "ECO",
            "ref": f"ecosticker:snapshot:{snapshot_date}:sha256:{source_hash}",
        },
        "actor": review["reviewer"],
        "reason": f"HUMAN-reviewed ECO MarketTrim promotion from snapshot {snapshot_date}",
        "submitted_at": review["reviewed_at"],
        "commands": commands,
    }
    # Parse through the same contract the worker uses before returning anything.
    CanonicalInputBatch.from_dict(batch)
    return batch


def write_market_trim_input_batch(review_path: Path | str, output_path: Path | str, *,
                                  data_dir: Path | str = DATA_DIR,
                                  year: int = DEFAULT_YEAR,
                                  snapshot_date: str) -> dict[str, Any]:
    batch = build_market_trim_input_batch(
        review_path, data_dir=data_dir, year=year, snapshot_date=snapshot_date)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return batch


__all__ = [
    "ECOTrimPromotionError",
    "build_market_trim_input_batch",
    "write_market_trim_input_batch",
]
