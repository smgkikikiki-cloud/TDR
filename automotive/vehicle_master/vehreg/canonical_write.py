"""Canonical write pipeline for TDR vehicle facts.

Phase C establishes one validated write path for vehicle identity/catalog facts,
price facts and comparable specs before any serving projection is allowed to
become authoritative.

The pipeline is deliberately file-backed because the imported Vehicle Master
remains the canonical store during consolidation.  Supabase is a serving and
command surface, not a second master.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Optional

from .catalog import Catalog, CatalogError, DATA_DIR, DEFAULT_YEAR, year_dir
from .comparable_specs import (
    ComparableSpecError,
    SpecLedger,
    SpecRegistry,
)
from .normalize import slug
from .pricing import PriceLedger, PricingError, PriceType
from .entities import to_jsonable


class CanonicalWriteError(ValueError):
    pass


_ALLOWED_COMMANDS = {
    "UPSERT_MODEL_BUNDLE",
    "WITHDRAW_MODEL",
    "APPEND_PRICE",
    "APPEND_SPEC",
}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


@dataclass(frozen=True, slots=True)
class CanonicalWriteCommand:
    command_id: str
    operation: str
    year: int
    actor: str
    reason: str
    canonical_id: Optional[str]
    payload: dict[str, Any]
    submitted_at: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CanonicalWriteCommand":
        if not isinstance(raw, dict):
            raise CanonicalWriteError("command must be an object")
        unknown = set(raw) - {
            "command_id", "operation", "year", "actor", "reason",
            "canonical_id", "payload", "submitted_at",
        }
        if unknown:
            raise CanonicalWriteError(f"unknown command fields: {sorted(unknown)}")
        command_id = str(raw.get("command_id") or "").strip()
        if not _SAFE_ID.fullmatch(command_id):
            raise CanonicalWriteError("command_id must be a safe stable token")
        operation = str(raw.get("operation") or "").strip().upper()
        if operation not in _ALLOWED_COMMANDS:
            raise CanonicalWriteError(f"unknown operation {operation!r}")
        try:
            year = int(raw.get("year") or DEFAULT_YEAR)
        except (TypeError, ValueError) as exc:
            raise CanonicalWriteError("year must be an integer") from exc
        if year < 2000 or year > 2100:
            raise CanonicalWriteError("year is outside the supported range")
        payload = raw.get("payload")
        if not isinstance(payload, dict):
            raise CanonicalWriteError("payload must be an object")
        submitted_at = str(raw.get("submitted_at") or "").strip()
        if not submitted_at:
            submitted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return cls(
            command_id=command_id,
            operation=operation,
            year=year,
            actor=str(raw.get("actor") or "system").strip() or "system",
            reason=str(raw.get("reason") or "").strip(),
            canonical_id=(str(raw.get("canonical_id") or "").strip() or None),
            payload=deepcopy(payload),
            submitted_at=submitted_at,
        )


@dataclass(frozen=True, slots=True)
class WriteResult:
    command_id: str
    revision_id: str
    topic: str
    entity_type: str
    entity_id: str
    changed_files: tuple[str, ...]
    idempotent_replay: bool = False


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_canonical_json(payload) + "\n")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalWriteError(f"cannot read {path}: {exc}") from exc


def _state_dir(data_dir: Path | str, year: int) -> Path:
    return Path(data_dir) / str(year) / "canonical_state"


def _revision_rows(data_dir: Path | str, year: int) -> list[dict[str, Any]]:
    path = _state_dir(data_dir, year) / "revisions.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _find_revision(data_dir: Path | str, year: int,
                   command_id: str) -> Optional[dict[str, Any]]:
    for row in reversed(_revision_rows(data_dir, year)):
        if row.get("command_id") == command_id:
            return row
    return None


def _load_brand_payloads(data_dir: Path | str,
                         year: int) -> dict[str, dict[str, Any]]:
    folder = year_dir(data_dir, year)
    out: dict[str, dict[str, Any]] = {}
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.json")):
        payload = _load_json(path)
        brand = payload.get("brand") or {}
        brand_id = slug(brand.get("id") or brand.get("name_en") or path.stem)
        out[brand_id] = payload
    return out


def _validate_payloads(payloads: dict[str, dict[str, Any]], year: int) -> Catalog:
    catalog = Catalog(year)
    for brand_id in sorted(payloads):
        catalog.add_brand_payload(payloads[brand_id], source=f"<canonical {brand_id}>")
    catalog.build_indexes()
    problems = catalog.validate()
    if problems:
        raise CanonicalWriteError("catalog validation failed: " + "; ".join(problems))
    return catalog


def _model_raw_id(model_id: str) -> tuple[str, str]:
    brand_id, dot, local_id = model_id.partition(".")
    if not dot or not brand_id or not local_id:
        raise CanonicalWriteError(
            "model canonical_id must look like '<brand>.<model>'")
    return brand_id, local_id


def _find_model_raw(payload: dict[str, Any], local_id: str) -> Optional[dict[str, Any]]:
    for model in payload.get("models", []):
        candidate = slug(model.get("id") or model.get("name_en") or "")
        if candidate == local_id:
            return model
    return None


def _find_generation_raw(model: dict[str, Any], generation_id: str,
                         model_id: str) -> Optional[dict[str, Any]]:
    prefix = model_id + "."
    if not generation_id.startswith(prefix):
        raise CanonicalWriteError("generation_id is not under canonical model")
    local = generation_id[len(prefix):]
    for generation in model.get("generations", []):
        if slug(generation.get("code") or generation.get("id") or "gen1") == local:
            return generation
    return None


def _upsert_by_identity(items: list[dict[str, Any]], incoming: dict[str, Any],
                        identity_fn) -> None:
    identity = identity_fn(incoming)
    for index, existing in enumerate(items):
        if identity_fn(existing) == identity:
            merged = deepcopy(existing)
            merged.update(deepcopy(incoming))
            items[index] = merged
            return
    items.append(deepcopy(incoming))


def _catalog_snapshot(catalog: Catalog, model_id: str) -> dict[str, Any]:
    model = catalog.models[model_id]
    brand = catalog.brands[model.brand_id]
    generations = catalog.generations_of(model_id)
    return {
        "brand": to_jsonable(brand),
        "model": to_jsonable(model),
        "generations": [to_jsonable(g) for g in generations],
        "variants": [to_jsonable(v) for v in catalog.variants_of(model_id)],
        "trims": [to_jsonable(t) for t in catalog.trims_of(model_id)],
    }


class CanonicalWritePipeline:
    """Validated, idempotent, revisioned writer for canonical vehicle facts.

    Successful writes append one immutable revision and one outbox event, then
    write a shadow projection.  No Supabase serving table is modified here.
    """

    def __init__(self, data_dir: Path | str = DATA_DIR) -> None:
        self.data_dir = Path(data_dir)

    def apply(self, raw_command: dict[str, Any] | CanonicalWriteCommand) -> WriteResult:
        command = (raw_command if isinstance(raw_command, CanonicalWriteCommand)
                   else CanonicalWriteCommand.from_dict(raw_command))
        replay = _find_revision(self.data_dir, command.year, command.command_id)
        if replay:
            return WriteResult(
                command_id=command.command_id,
                revision_id=str(replay["revision_id"]),
                topic=str(replay["topic"]),
                entity_type=str(replay["entity_type"]),
                entity_id=str(replay["entity_id"]),
                changed_files=tuple(replay.get("changed_files") or ()),
                idempotent_replay=True,
            )

        if command.operation == "UPSERT_MODEL_BUNDLE":
            topic, entity_type, entity_id, before, after, changed = \
                self._upsert_model_bundle(command)
        elif command.operation == "WITHDRAW_MODEL":
            topic, entity_type, entity_id, before, after, changed = \
                self._withdraw_model(command)
        elif command.operation == "APPEND_PRICE":
            topic, entity_type, entity_id, before, after, changed = \
                self._append_price(command)
        elif command.operation == "APPEND_SPEC":
            topic, entity_type, entity_id, before, after, changed = \
                self._append_spec(command)
        else:  # guarded by parser; retained for callers constructing dataclass directly
            raise CanonicalWriteError(f"unsupported operation {command.operation}")

        revision_id = hashlib.sha256(
            f"{command.year}:{command.command_id}:{_hash(before)}:{_hash(after)}".encode()
        ).hexdigest()[:24]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        revision = {
            "schema_version": 1,
            "revision_id": revision_id,
            "command_id": command.command_id,
            "operation": command.operation,
            "year": command.year,
            "topic": topic,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor": command.actor,
            "reason": command.reason,
            "submitted_at": command.submitted_at,
            "applied_at": now,
            "before_hash": _hash(before),
            "after_hash": _hash(after),
            "before": before,
            "after": after,
            "changed_files": list(changed),
        }
        state = _state_dir(self.data_dir, command.year)
        _append_jsonl(state / "revisions.jsonl", revision)
        event = {
            "schema_version": 1,
            "event_id": f"{revision_id}:{topic}",
            "revision_id": revision_id,
            "topic": topic,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "state": "PENDING",
            "created_at": now,
            "payload": after,
        }
        _append_jsonl(state / "outbox.jsonl", event)
        _atomic_json(state / "shadow" / f"{revision_id}.json", {
            "schema_version": 1,
            "release_kind": "SHADOW",
            "revision": revision,
            "event": event,
        })
        return WriteResult(
            command_id=command.command_id,
            revision_id=revision_id,
            topic=topic,
            entity_type=entity_type,
            entity_id=entity_id,
            changed_files=tuple(changed),
        )

    def _upsert_model_bundle(self, command: CanonicalWriteCommand):
        bundle = command.payload
        brand_patch = bundle.get("brand")
        model_patch = bundle.get("model")
        generation_patch = bundle.get("generation")
        if not all(isinstance(x, dict) for x in
                   (brand_patch, model_patch, generation_patch)):
            raise CanonicalWriteError(
                "UPSERT_MODEL_BUNDLE requires brand/model/generation objects")
        canonical_id = command.canonical_id or str(model_patch.get("canonical_id") or "")
        if not canonical_id:
            brand_hint = slug(brand_patch.get("id") or brand_patch.get("name_en") or "")
            model_hint = slug(model_patch.get("id") or model_patch.get("name_en") or "")
            if not brand_hint or not model_hint:
                raise CanonicalWriteError(
                    "new model bundle needs canonical_id or stable brand/model ids")
            canonical_id = f"{brand_hint}.{model_hint}"
        brand_id, local_model_id = _model_raw_id(canonical_id)
        if slug(brand_patch.get("id") or brand_patch.get("name_en") or brand_id) != brand_id:
            raise CanonicalWriteError("brand payload disagrees with canonical_id")

        payloads = _load_brand_payloads(self.data_dir, command.year)
        brand_payload = deepcopy(payloads.get(brand_id) or {
            "brand": {"id": brand_id}, "models": [],
        })
        existing_model = _find_model_raw(brand_payload, local_model_id)
        before = deepcopy(existing_model) if existing_model is not None else None

        brand_node = brand_payload.setdefault("brand", {"id": brand_id})
        brand_node.update({k: deepcopy(v) for k, v in brand_patch.items()
                           if k != "canonical_id"})
        brand_node["id"] = brand_id
        if not brand_node.get("name_en"):
            raise CanonicalWriteError("brand.name_en is required")

        if existing_model is None:
            if not model_patch.get("name_en"):
                raise CanonicalWriteError("new model requires model.name_en")
            existing_model = {"id": local_model_id, "generations": []}
            brand_payload.setdefault("models", []).append(existing_model)
        existing_model.update({k: deepcopy(v) for k, v in model_patch.items()
                               if k not in {"canonical_id", "generations"}})
        existing_model["id"] = local_model_id

        code = str(generation_patch.get("code") or "").strip()
        if not code:
            raise CanonicalWriteError("generation.code is required")
        generation_id = f"{canonical_id}.{slug(code)}"
        generation = _find_generation_raw(existing_model, generation_id, canonical_id)
        if generation is None:
            generation = {"code": code, "variants": [], "trims": []}
            existing_model.setdefault("generations", []).append(generation)
        generation.update({k: deepcopy(v) for k, v in generation_patch.items()
                           if k not in {"variants", "trims"}})
        generation["code"] = code
        generation.setdefault("variants", [])
        generation.setdefault("trims", [])

        for raw in bundle.get("variants") or []:
            if not isinstance(raw, dict) or not raw.get("name"):
                raise CanonicalWriteError("every variant requires a name")
            incoming = deepcopy(raw)
            if incoming.get("canonical_id"):
                full = str(incoming.pop("canonical_id"))
                if not full.startswith(generation_id + "."):
                    raise CanonicalWriteError("variant canonical_id has wrong parent")
                incoming["id"] = full.rsplit(".", 1)[-1]
            _upsert_by_identity(
                generation["variants"], incoming,
                lambda row: slug(row.get("id") or row.get("name") or ""),
            )

        for raw in bundle.get("trims") or []:
            if not isinstance(raw, dict) or not raw.get("name"):
                raise CanonicalWriteError("every market trim requires a name")
            incoming = deepcopy(raw)
            if incoming.get("canonical_id"):
                full = str(incoming.pop("canonical_id"))
                prefix = generation_id + ".trim."
                if not full.startswith(prefix):
                    raise CanonicalWriteError("trim canonical_id has wrong parent")
                incoming["id"] = full[len(prefix):]
            _upsert_by_identity(
                generation["trims"], incoming,
                lambda row: slug(row.get("id") or
                                 f"{row.get('name','')} {row.get('powertrain','')}"),
            )

        payloads[brand_id] = brand_payload
        catalog = _validate_payloads(payloads, command.year)
        if canonical_id not in catalog.models:
            raise CanonicalWriteError("validated catalog did not contain target model")
        after = _catalog_snapshot(catalog, canonical_id)
        target = year_dir(self.data_dir, command.year) / f"{brand_id}.json"
        _atomic_json(target, brand_payload)
        return "catalog", "model", canonical_id, before, after, (str(target),)

    def _withdraw_model(self, command: CanonicalWriteCommand):
        model_id = command.canonical_id or str(command.payload.get("model_id") or "")
        if not model_id:
            raise CanonicalWriteError("WITHDRAW_MODEL requires canonical_id")
        brand_id, local_model_id = _model_raw_id(model_id)
        payloads = _load_brand_payloads(self.data_dir, command.year)
        brand_payload = payloads.get(brand_id)
        if not brand_payload:
            raise CanonicalWriteError(f"unknown brand {brand_id!r}")
        model = _find_model_raw(brand_payload, local_model_id)
        if model is None:
            raise CanonicalWriteError(f"unknown model {model_id!r}")
        before = deepcopy(model)
        model["retail_status"] = "HISTORICAL"
        if command.payload.get("ended"):
            ended = str(command.payload["ended"])
            for generation in model.get("generations", []):
                if not generation.get("ended"):
                    generation["ended"] = ended
        catalog = _validate_payloads(payloads, command.year)
        after = _catalog_snapshot(catalog, model_id)
        target = year_dir(self.data_dir, command.year) / f"{brand_id}.json"
        _atomic_json(target, brand_payload)
        return "catalog", "model", model_id, before, after, (str(target),)

    def _append_price(self, command: CanonicalWriteCommand):
        record = deepcopy(command.payload)
        trim_id = command.canonical_id or str(record.get("trim_id") or "")
        if not trim_id:
            raise CanonicalWriteError("APPEND_PRICE requires trim_id/canonical_id")
        record["trim_id"] = trim_id
        catalog = Catalog.load(self.data_dir, command.year)
        if trim_id not in catalog.trims:
            raise CanonicalWriteError(f"unknown MarketTrim {trim_id!r}")
        ledger = PriceLedger.load(self.data_dir, year=command.year, catalog=catalog)
        before = [to_jsonable(r) for r in ledger.records_for(
            trim_id, include_retracted=True)]
        ledger.add_payload({"prices": [record]}, source=f"<command {command.command_id}>")
        if PriceType.parse(record.get("price_type")) is PriceType.LIST_PRICE:
            # Force conflict detection on the exact day this claim starts.
            start = record.get("effective_from") or record.get("observed_at")
            ledger.current_list_price(
                trim_id, as_of=date.fromisoformat(start) if start else date.today())
        folder = Path(self.data_dir) / str(command.year) / "market" / "prices"
        target = folder / f"canonical_{command.command_id}.json"
        if target.exists():
            raise CanonicalWriteError(
                "command file already exists without a revision; manual recovery required")
        _atomic_json(target, {"prices": [record]})
        after_ledger = PriceLedger.load(
            self.data_dir, year=command.year, catalog=catalog)
        after = [to_jsonable(r) for r in after_ledger.records_for(
            trim_id, include_retracted=True)]
        return "price", "market_trim", trim_id, before, after, (str(target),)

    def _append_spec(self, command: CanonicalWriteCommand):
        fact = deepcopy(command.payload)
        trim_id = command.canonical_id or str(fact.get("trim_id") or "")
        if not trim_id:
            raise CanonicalWriteError("APPEND_SPEC requires trim_id/canonical_id")
        fact["trim_id"] = trim_id
        catalog = Catalog.load(self.data_dir, command.year)
        registry = SpecRegistry.load(self.data_dir, command.year)
        ledger = SpecLedger.load(
            self.data_dir, command.year, registry=registry, catalog=catalog)
        before = [to_jsonable(row) for row in ledger.facts if row.trim_id == trim_id]
        ledger.add_payload(
            {"schema_version": 1, "facts": [fact]},
            source=f"<command {command.command_id}>",
        )
        problems = ledger.validate()
        if problems:
            raise CanonicalWriteError("spec validation failed: " + "; ".join(problems))
        root = (Path(self.data_dir) / str(command.year) / "product" /
                "comparable_specs" / "facts")
        target = root / f"canonical_{command.command_id}.json"
        if target.exists():
            raise CanonicalWriteError(
                "command file already exists without a revision; manual recovery required")
        _atomic_json(target, {"schema_version": 1, "facts": [fact]})
        after_ledger = SpecLedger.load(
            self.data_dir, command.year, registry=registry, catalog=catalog)
        after = [to_jsonable(row) for row in after_ledger.facts if row.trim_id == trim_id]
        return "spec", "market_trim", trim_id, before, after, (str(target),)


__all__ = [
    "CanonicalWriteCommand",
    "CanonicalWriteError",
    "CanonicalWritePipeline",
    "WriteResult",
]
