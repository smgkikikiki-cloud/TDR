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
from .comparable_specs import ComparableSpecError, SpecLedger, SpecRegistry
from .normalize import slug, trim_identity, trim_local_id
from .pricing import PriceLedger, PricingError, PriceType
from .entities import to_jsonable
from .product import close_price, correct_price, save_campaign


class CanonicalWriteError(ValueError):
    pass


_ALLOWED_COMMANDS = {
    "UPSERT_MODEL_BUNDLE",
    "WITHDRAW_MODEL",
    "APPEND_PRICE",
    "CORRECT_PRICE",
    "CLOSE_PRICE",
    "UPSERT_CAMPAIGN",
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


def _existing_target_matches(path: Path, payload: dict[str, Any]) -> bool:
    """Recognize a data-first write left behind before its revision marker."""
    if not path.is_file():
        return False
    try:
        return _load_json(path) == payload
    except CanonicalWriteError:
        return False


def _fact_filename(fact_id: str) -> str:
    """A filesystem-safe, collision-free stem for one spec fact.

    A fact_id carries ':' and '.' separators and can be long, so it is folded
    to a safe stem; the sha suffix keeps two ids that fold together -- or one
    that had to be truncated -- in separate files.
    """
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", fact_id)
    digest = hashlib.sha256(fact_id.encode("utf-8")).hexdigest()[:12]
    return f"canonical_{safe[:120]}_{digest}"


def _spec_facts_on_disk(path: Path) -> Optional[list[dict[str, Any]]]:
    """The facts a spec command wrote last time, or None if it never ran."""
    if not path.is_file():
        return None
    try:
        payload = _load_json(path)
    except CanonicalWriteError:
        return None
    facts = payload.get("facts") if isinstance(payload, dict) else None
    if not isinstance(facts, list) or not all(isinstance(row, dict) for row in facts):
        return None
    return facts


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


def _repair_replay_audit(data_dir: Path | str, year: int,
                         revision: dict[str, Any]) -> tuple[str, ...]:
    """Restore outbox/shadow artifacts if a data-first batch copy was interrupted."""
    state = _state_dir(data_dir, year)
    event_id = f"{revision['revision_id']}:{revision['topic']}"
    outbox = state / "outbox.jsonl"
    event_exists = False
    if outbox.is_file():
        for line in outbox.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("event_id") == event_id:
                event_exists = True
                break
    event = {
        "schema_version": 1,
        "event_id": event_id,
        "revision_id": revision["revision_id"],
        "topic": revision["topic"],
        "entity_type": revision["entity_type"],
        "entity_id": revision["entity_id"],
        "state": "PENDING",
        "created_at": revision["applied_at"],
        "payload": revision["after"],
    }
    repaired: list[str] = []
    if not event_exists:
        _append_jsonl(outbox, event)
        repaired.append(str(outbox))
    shadow = state / "shadow" / f"{revision['revision_id']}.json"
    if not shadow.is_file():
        _atomic_json(shadow, {
            "schema_version": 1,
            "release_kind": "SHADOW",
            "revision": revision,
            "event": event,
        })
        repaired.append(str(shadow))
    return tuple(repaired)


def _resolve_recorded_change(data_dir: Path | str, year: int, recorded: str) -> str:
    root = Path(data_dir)
    path = Path(recorded)
    if not path.is_absolute():
        return str(root / path)
    try:
        path.relative_to(root)
        return str(path)
    except ValueError:
        parts = path.parts
        try:
            year_index = parts.index(str(year))
        except ValueError as exc:
            raise CanonicalWriteError(f"recorded changed file is outside canonical data: {path}") from exc
        return str(root.joinpath(*parts[year_index:]))


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
        raise CanonicalWriteError("model canonical_id must look like '<brand>.<model>'")
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


def _live_row_starting_with(ledger: PriceLedger, trim_id: str, record: dict[str, Any]):
    """The live price for this exact scope, if it starts on the same day.

    Scope means trim, price type and -- for a promotion -- the campaign and
    option it belongs to, so a campaign price never collides with the list
    price beside it.
    """
    start = record.get("effective_from") or record.get("observed_at")
    if not start:
        return None
    try:
        price_type = PriceType.parse(record.get("price_type") or "LIST_PRICE")
        current = ledger.current_price_for_scope(
            trim_id, price_type, as_of=date.fromisoformat(str(start)),
            campaign_id=(str(record["campaign_id"]) if record.get("campaign_id") else None),
            option_id=(str(record["option_id"]) if record.get("option_id") else None))
    except (PricingError, ValueError):
        # Already unresolvable, or a date this code cannot read. Either way
        # the ordinary append path reports it rather than this one guessing.
        return None
    if current is None:
        return None
    return current if (current.effective_from or current.observed_at) == str(start) else None


def _price_snapshot(data_dir: Path | str, year: int, trim_id: str) -> list[dict[str, Any]]:
    catalog = Catalog.load(data_dir, year)
    ledger = PriceLedger.load(data_dir, year=year, catalog=catalog)
    return [to_jsonable(row) for row in ledger.records_for(trim_id, include_retracted=True)]


def _campaign_snapshot(data_dir: Path | str, year: int,
                       campaign_id: str) -> Optional[dict[str, Any]]:
    folder = Path(data_dir) / str(year) / "market" / "campaigns"
    if not folder.is_dir():
        return None
    for path in sorted(folder.glob("*.json")):
        payload = _load_json(path)
        for campaign in payload.get("campaigns", []):
            if str(campaign.get("id") or "") == campaign_id:
                return deepcopy(campaign)
    return None


def _as_of_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise CanonicalWriteError("as_of must be YYYY-MM-DD") from exc


class CanonicalWritePipeline:
    """Validated, idempotent, revisioned writer for canonical vehicle facts."""

    def __init__(self, data_dir: Path | str = DATA_DIR) -> None:
        self.data_dir = Path(data_dir)
        # One instance writes one batch, so what it reads it can keep.
        #
        # Without this, every APPEND_SPEC re-read the whole catalogue and every
        # spec fact file three times over. That is unnoticeable for an admin
        # editing one trim and quadratic for a bulk import: 36,000 facts meant
        # roughly two billion file reads, and the monthly ECO Sticker import
        # simply could not finish. The caches below are per instance and are
        # updated by this pipeline's own writes, so a command still sees
        # everything the commands before it in the same batch did.
        self._catalog_cache: dict[int, Catalog] = {}
        self._registry_cache: dict[int, SpecRegistry] = {}
        #: year -> trim_id -> {fact file -> payload}
        self._fact_index: dict[int, dict[str, dict[Path, dict[str, Any]]]] = {}
        #: year -> command_id -> revision row, for the replay check every
        #: command starts with.
        self._revision_index: dict[int, dict[str, dict[str, Any]]] = {}

    def _catalog(self, year: int) -> Catalog:
        if year not in self._catalog_cache:
            self._catalog_cache[year] = Catalog.load(self.data_dir, year)
        return self._catalog_cache[year]

    def _registry(self, year: int) -> SpecRegistry:
        if year not in self._registry_cache:
            self._registry_cache[year] = SpecRegistry.load(self.data_dir, year)
        return self._registry_cache[year]

    def _facts_by_trim(self, year: int) -> dict[str, dict[Path, dict[str, Any]]]:
        """Every spec fact on disk, indexed by the trim it describes.

        Read once per instance. A fact about one trim can never conflict with a
        fact about another -- SpecLedger.validate groups by
        (trim_id, field_key, qualifier, start) -- so a command only ever needs
        its own trim's facts, and reading the other 36,000 to prove that was
        the whole cost.
        """
        if year in self._fact_index:
            return self._fact_index[year]
        index: dict[str, dict[Path, dict[str, Any]]] = {}
        root = Path(self.data_dir) / str(year) / "product" / "comparable_specs" / "facts"
        if root.is_dir():
            for path in sorted(root.glob("*.json")):
                try:
                    payload = _load_json(path)
                except CanonicalWriteError:
                    continue
                for fact in (payload.get("facts") or []) if isinstance(payload, dict) else []:
                    if isinstance(fact, dict):
                        index.setdefault(str(fact.get("trim_id") or ""), {})[path] = payload
        self._fact_index[year] = index
        return index

    def _trim_ledger(self, year: int, trim_id: str, *, skip: Optional[Path] = None,
                     extra: Optional[dict[str, Any]] = None) -> SpecLedger:
        """A ledger holding one trim's facts, optionally without one file and
        with one staged payload added."""
        ledger = SpecLedger(self._registry(year), year, catalog=self._catalog(year))
        for path, payload in sorted(self._facts_by_trim(year).get(trim_id, {}).items()):
            if skip is not None and path == skip:
                continue
            ledger.add_payload(payload, source=str(path))
        if extra is not None:
            ledger.add_payload(extra, source="<staged>")
        return ledger

    def _remember_fact_file(self, year: int, path: Path, payload: dict[str, Any]) -> None:
        """Keep the index true after this pipeline writes a fact file."""
        index = self._facts_by_trim(year)
        for facts in index.values():
            facts.pop(path, None)
        for fact in (payload.get("facts") or []):
            if isinstance(fact, dict):
                index.setdefault(str(fact.get("trim_id") or ""), {})[path] = payload

    def _forget_catalog(self, year: int) -> None:
        """A command that rewrote a model file invalidates the loaded catalogue."""
        self._catalog_cache.pop(year, None)

    def _replayed(self, year: int, command_id: str) -> Optional[dict[str, Any]]:
        """The revision this command already wrote, if it has run before.

        Every command begins with this question, and answering it used to mean
        reading and parsing the entire revision log -- one JSON object per edit
        the catalogue has ever taken. At 18,000 revisions that is 18,000 parses
        to answer a dictionary lookup, per command, and it grows with every
        command that answers it. The log is read once per instance and kept as
        an index that this pipeline's own writes append to.

        Later rows win, matching the reversed scan this replaces: a command_id
        is not supposed to repeat, but if it does, the most recent revision is
        the one that describes the tree.
        """
        if year not in self._revision_index:
            index: dict[str, dict[str, Any]] = {}
            for row in _revision_rows(self.data_dir, year):
                command = row.get("command_id")
                if command:
                    index[str(command)] = row
            self._revision_index[year] = index
        return self._revision_index[year].get(command_id)

    def _remember_revision(self, year: int, revision: dict[str, Any]) -> None:
        command_id = revision.get("command_id")
        if command_id and year in self._revision_index:
            self._revision_index[year][str(command_id)] = revision

    def apply(self, raw_command: dict[str, Any] | CanonicalWriteCommand) -> WriteResult:
        command = (raw_command if isinstance(raw_command, CanonicalWriteCommand)
                   else CanonicalWriteCommand.from_dict(raw_command))
        replay = self._replayed(command.year, command.command_id)
        if replay:
            repaired = _repair_replay_audit(self.data_dir, command.year, replay)
            replay_files = tuple(
                _resolve_recorded_change(self.data_dir, command.year, str(path))
                for path in (replay.get("changed_files") or ())
            )
            return WriteResult(
                command_id=command.command_id,
                revision_id=str(replay["revision_id"]),
                topic=str(replay["topic"]),
                entity_type=str(replay["entity_type"]),
                entity_id=str(replay["entity_id"]),
                changed_files=replay_files + repaired,
                idempotent_replay=True,
            )

        if command.operation == "UPSERT_MODEL_BUNDLE":
            topic, entity_type, entity_id, before, after, changed = self._upsert_model_bundle(command)
        elif command.operation == "WITHDRAW_MODEL":
            topic, entity_type, entity_id, before, after, changed = self._withdraw_model(command)
        elif command.operation == "APPEND_PRICE":
            topic, entity_type, entity_id, before, after, changed = self._append_price(command)
        elif command.operation == "CORRECT_PRICE":
            topic, entity_type, entity_id, before, after, changed = self._correct_price(command)
        elif command.operation == "CLOSE_PRICE":
            topic, entity_type, entity_id, before, after, changed = self._close_price(command)
        elif command.operation == "UPSERT_CAMPAIGN":
            topic, entity_type, entity_id, before, after, changed = self._upsert_campaign(command)
        elif command.operation == "APPEND_SPEC":
            topic, entity_type, entity_id, before, after, changed = self._append_spec(command)
        else:
            raise CanonicalWriteError(f"unsupported operation {command.operation}")

        revision_id = hashlib.sha256(
            f"{command.year}:{command.command_id}:{_hash(before)}:{_hash(after)}".encode()
        ).hexdigest()[:24]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        durable_changed = [str(Path(path).relative_to(self.data_dir)) for path in changed]
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
            "changed_files": durable_changed,
        }
        state = _state_dir(self.data_dir, command.year)
        _append_jsonl(state / "revisions.jsonl", revision)
        self._remember_revision(command.year, revision)
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
        if not all(isinstance(x, dict) for x in (brand_patch, model_patch, generation_patch)):
            raise CanonicalWriteError("UPSERT_MODEL_BUNDLE requires brand/model/generation objects")
        canonical_id = command.canonical_id or str(model_patch.get("canonical_id") or "")
        if not canonical_id:
            brand_hint = slug(brand_patch.get("id") or brand_patch.get("name_en") or "")
            model_hint = slug(model_patch.get("id") or model_patch.get("name_en") or "")
            if not brand_hint or not model_hint:
                raise CanonicalWriteError("new model bundle needs canonical_id or stable brand/model ids")
            canonical_id = f"{brand_hint}.{model_hint}"
        brand_id, local_model_id = _model_raw_id(canonical_id)
        if slug(brand_patch.get("id") or brand_patch.get("name_en") or brand_id) != brand_id:
            raise CanonicalWriteError("brand payload disagrees with canonical_id")

        payloads = _load_brand_payloads(self.data_dir, command.year)
        brand_payload = deepcopy(payloads.get(brand_id) or {"brand": {"id": brand_id}, "models": []})
        existing_model = _find_model_raw(brand_payload, local_model_id)
        before = deepcopy(existing_model) if existing_model is not None else None
        brand_node = brand_payload.setdefault("brand", {"id": brand_id})
        brand_node.update({k: deepcopy(v) for k, v in brand_patch.items() if k != "canonical_id"})
        brand_node["id"] = brand_id
        if not brand_node.get("name_en"):
            raise CanonicalWriteError("brand.name_en is required")
        if existing_model is None:
            if not model_patch.get("name_en"):
                raise CanonicalWriteError("new model requires model.name_en")
            existing_model = {"id": local_model_id, "generations": []}
            brand_payload.setdefault("models", []).append(existing_model)
        existing_model.update({k: deepcopy(v) for k, v in model_patch.items() if k not in {"canonical_id", "generations"}})
        existing_model["id"] = local_model_id
        code = str(generation_patch.get("code") or "").strip()
        if not code:
            raise CanonicalWriteError("generation.code is required")
        generation_id = f"{canonical_id}.{slug(code)}"
        generation = _find_generation_raw(existing_model, generation_id, canonical_id)
        if generation is None:
            generation = {"code": code, "variants": [], "trims": []}
            existing_model.setdefault("generations", []).append(generation)
        generation.update({k: deepcopy(v) for k, v in generation_patch.items() if k not in {"variants", "trims"}})
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
            _upsert_by_identity(generation["variants"], incoming, lambda row: slug(row.get("id") or row.get("name") or ""))
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
            # Same identity rule the catalog loader uses, so an incoming trim
            # matches the row it is meant to update.
            _upsert_by_identity(
                generation["trims"], incoming,
                lambda row: trim_local_id(row.get("id"), row.get("name", ""),
                                          row.get("powertrain", ""))
            )
        payloads[brand_id] = brand_payload
        catalog = _validate_payloads(payloads, command.year)
        if canonical_id not in catalog.models:
            raise CanonicalWriteError("validated catalog did not contain target model")
        after = _catalog_snapshot(catalog, canonical_id)
        target = year_dir(self.data_dir, command.year) / f"{brand_id}.json"
        _atomic_json(target, brand_payload)
        self._forget_catalog(command.year)
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
        self._forget_catalog(command.year)
        return "catalog", "model", model_id, before, after, (str(target),)

    def _append_price(self, command: CanonicalWriteCommand):
        record = deepcopy(command.payload)
        trim_id = command.canonical_id or str(record.get("trim_id") or "")
        if not trim_id:
            raise CanonicalWriteError("APPEND_PRICE requires trim_id/canonical_id")
        record["trim_id"] = trim_id
        catalog = self._catalog(command.year)
        if trim_id not in catalog.trims:
            raise CanonicalWriteError(f"unknown MarketTrim {trim_id!r}")
        ledger = PriceLedger.load(self.data_dir, year=command.year, catalog=catalog)
        before = [to_jsonable(r) for r in ledger.records_for(trim_id, include_retracted=True)]

        same_day = _live_row_starting_with(ledger, trim_id, record)
        if same_day is not None:
            if same_day.amount_thb == int(record["amount_thb"]):
                # The same number saved again. Recording it twice would leave
                # two live rows the resolver then refuses to choose between.
                return "price", "market_trim", trim_id, before, before, ()
            return self._replace_same_day_price(command, trim_id, record, same_day, before)

        ledger.add_payload({"prices": [record]}, source=f"<command {command.command_id}>")
        if PriceType.parse(record.get("price_type")) is PriceType.LIST_PRICE:
            start = record.get("effective_from") or record.get("observed_at")
            ledger.current_list_price(trim_id, as_of=date.fromisoformat(start) if start else date.today())
        folder = Path(self.data_dir) / str(command.year) / "market" / "prices"
        target = folder / f"canonical_{command.command_id}.json"
        target_payload = {"prices": [record]}
        if target.exists() and not _existing_target_matches(target, target_payload):
            raise CanonicalWriteError("command file already exists without a revision; manual recovery required")
        _atomic_json(target, target_payload)
        after_ledger = PriceLedger.load(self.data_dir, year=command.year, catalog=catalog)
        after = [to_jsonable(r) for r in after_ledger.records_for(trim_id, include_retracted=True)]
        return "price", "market_trim", trim_id, before, after, (str(target),)

    def _replace_same_day_price(self, command: CanonicalWriteCommand, trim_id: str,
                                record: dict[str, Any], live, before):
        """A price changed again on the day it was set.

        Two rows starting the same day are not two prices that were both
        true -- they are one decision made twice, and the resolver refuses
        to pick between them, which used to make the owner's second save of
        the day fail outright. The first number is retracted, not given a
        history it never had, and the new one takes its place.
        """
        start = str(record.get("effective_from") or record.get("observed_at"))
        try:
            result = correct_price(
                self.data_dir, command.year,
                trim_id=trim_id,
                price_type=PriceType.parse(record.get("price_type") or "LIST_PRICE").value,
                amount_thb=int(record["amount_thb"]),
                reason=command.reason or f"replaces the price saved earlier on {start}",
                reviewer=command.actor or "owner",
                mode="retract",
                effective_from=start,
                campaign_id=(str(record.get("campaign_id")) if record.get("campaign_id") else None),
                option_id=(str(record.get("option_id")) if record.get("option_id") else None),
                source=str(record.get("source") or ""),
                source_ref=str(record.get("source_ref") or ""),
                reference_price_thb=(int(record["reference_price_thb"])
                                     if record.get("reference_price_thb") not in (None, "") else None),
                as_of=date.fromisoformat(start),
                write=True,
            )
        except (CatalogError, PricingError, KeyError, TypeError, ValueError) as exc:
            raise CanonicalWriteError(f"same-day price replacement failed: {exc}") from exc
        after = _price_snapshot(self.data_dir, command.year, trim_id)
        return "price", "market_trim", trim_id, before, after, tuple(result.get("paths") or ())

    def _correct_price(self, command: CanonicalWriteCommand):
        payload = deepcopy(command.payload)
        trim_id = command.canonical_id or str(payload.get("trim_id") or "")
        if not trim_id:
            raise CanonicalWriteError("CORRECT_PRICE requires trim_id/canonical_id")
        if not command.reason:
            raise CanonicalWriteError("CORRECT_PRICE requires command.reason")
        catalog = self._catalog(command.year)
        if trim_id not in catalog.trims:
            raise CanonicalWriteError(f"unknown MarketTrim {trim_id!r}")
        before = _price_snapshot(self.data_dir, command.year, trim_id)
        try:
            result = correct_price(
                self.data_dir, command.year,
                trim_id=trim_id,
                price_type=PriceType.parse(payload.get("price_type") or "LIST_PRICE").value,
                amount_thb=int(payload["amount_thb"]),
                reason=command.reason,
                reviewer=command.actor,
                mode=str(payload.get("mode") or "supersede").lower(),
                effective_from=(str(payload.get("effective_from")) if payload.get("effective_from") else None),
                campaign_id=(str(payload.get("campaign_id")) if payload.get("campaign_id") else None),
                option_id=(str(payload.get("option_id")) if payload.get("option_id") else None),
                source=str(payload.get("source") or ""),
                source_ref=str(payload.get("source_ref") or ""),
                reference_price_thb=(int(payload["reference_price_thb"]) if payload.get("reference_price_thb") not in (None, "") else None),
                as_of=_as_of_date(payload.get("as_of")),
                write=True,
            )
        except (CatalogError, PricingError, KeyError, TypeError, ValueError) as exc:
            raise CanonicalWriteError(f"price correction failed: {exc}") from exc
        if not result.get("changed"):
            raise CanonicalWriteError(str(result.get("note") or "price correction produced no change"))
        after = _price_snapshot(self.data_dir, command.year, trim_id)
        return "price", "market_trim", trim_id, before, after, tuple(result.get("paths") or ())

    def _close_price(self, command: CanonicalWriteCommand):
        payload = deepcopy(command.payload)
        trim_id = command.canonical_id or str(payload.get("trim_id") or "")
        if not trim_id:
            raise CanonicalWriteError("CLOSE_PRICE requires trim_id/canonical_id")
        if not command.reason:
            raise CanonicalWriteError("CLOSE_PRICE requires command.reason")
        ends = str(payload.get("ends") or "")
        if not ends:
            raise CanonicalWriteError("CLOSE_PRICE requires ends")
        catalog = self._catalog(command.year)
        if trim_id not in catalog.trims:
            raise CanonicalWriteError(f"unknown MarketTrim {trim_id!r}")
        before = _price_snapshot(self.data_dir, command.year, trim_id)
        try:
            result = close_price(
                self.data_dir, command.year,
                trim_id=trim_id,
                price_type=PriceType.parse(payload.get("price_type") or "LIST_PRICE").value,
                ends=ends,
                reason=command.reason,
                reviewer=command.actor,
                campaign_id=(str(payload.get("campaign_id")) if payload.get("campaign_id") else None),
                option_id=(str(payload.get("option_id")) if payload.get("option_id") else None),
                as_of=_as_of_date(payload.get("as_of")),
                write=True,
            )
        except (CatalogError, PricingError, TypeError, ValueError) as exc:
            raise CanonicalWriteError(f"price close failed: {exc}") from exc
        after = _price_snapshot(self.data_dir, command.year, trim_id)
        return "price", "market_trim", trim_id, before, after, tuple(result.get("paths") or ())

    def _upsert_campaign(self, command: CanonicalWriteCommand):
        campaign = deepcopy(command.payload.get("campaign") or command.payload)
        if not isinstance(campaign, dict):
            raise CanonicalWriteError("UPSERT_CAMPAIGN requires a campaign object")
        campaign_id = command.canonical_id or str(campaign.get("id") or "")
        if not campaign_id:
            raise CanonicalWriteError("UPSERT_CAMPAIGN requires campaign id/canonical_id")
        campaign["id"] = campaign_id
        before = _campaign_snapshot(self.data_dir, command.year, campaign_id)
        try:
            probe = save_campaign(self.data_dir, command.year, campaign, write=False)
            if before == campaign:
                raise CanonicalWriteError("campaign already matches canonical payload")
            result = save_campaign(self.data_dir, command.year, campaign, write=True)
        except CanonicalWriteError:
            raise
        except (CatalogError, PricingError, TypeError, ValueError) as exc:
            raise CanonicalWriteError(f"campaign write failed: {exc}") from exc
        after = _campaign_snapshot(self.data_dir, command.year, campaign_id)
        if after is None:
            raise CanonicalWriteError("campaign write did not produce canonical state")
        return "campaign", "campaign", campaign_id, before, after, (str(result.get("path") or probe.get("path")),)

    def _append_spec(self, command: CanonicalWriteCommand):
        fact = deepcopy(command.payload)
        trim_id = command.canonical_id or str(fact.get("trim_id") or "")
        # A trim being created by an earlier command in this same batch has no
        # canonical_id the author could have known: it is derived by a rule
        # that folds Thai marks and strips corporate words, so it is not
        # reproducible outside this module. Such a command names the trim by
        # reference instead and we resolve it here, with the one rule.
        reference = fact.pop("trim_ref", None)
        if reference is not None:
            if not isinstance(reference, dict):
                raise CanonicalWriteError("APPEND_SPEC trim_ref must be an object")
            generation_id = str(reference.get("generation_id") or "")
            if not generation_id:
                raise CanonicalWriteError("APPEND_SPEC trim_ref requires generation_id")
            if not (reference.get("id") or reference.get("name")):
                raise CanonicalWriteError("APPEND_SPEC trim_ref requires id or name")
            resolved = trim_identity(generation_id, reference.get("id"),
                                     reference.get("name", ""),
                                     reference.get("powertrain", ""))
            if trim_id and trim_id != resolved:
                raise CanonicalWriteError(
                    f"APPEND_SPEC trim_ref resolves to {resolved!r}, "
                    f"which contradicts trim_id {trim_id!r}")
            trim_id = resolved
        if not trim_id:
            raise CanonicalWriteError("APPEND_SPEC requires trim_id/canonical_id")
        fact["trim_id"] = trim_id
        field_key = str(fact.get("field_key") or "")
        if not field_key:
            raise CanonicalWriteError("APPEND_SPEC requires field_key")
        # A caller that cannot know the trim_id cannot compose a fact_id out of
        # it either, so the same rule that resolved the trim derives the id:
        # one fact per trim per field, which is exactly what the editor's one
        # box per field means.
        if not str(fact.get("fact_id") or "").strip():
            fact["fact_id"] = f"admin:{trim_id}:{field_key}"

        catalog = self._catalog(command.year)
        root = Path(self.data_dir) / str(command.year) / "product" / "comparable_specs" / "facts"
        target = root / f"{_fact_filename(str(fact['fact_id']))}.json"
        target_payload = {"schema_version": 1, "facts": [fact]}

        # The file is named after the fact it holds, not the command that
        # happened to write it, so re-stating a fact revises it in place. That
        # is what makes correcting a value ordinary: a second file for the same
        # field would be a second fact with the same start date and a different
        # value, which SpecLedger.validate rejects as a conflict, forever. A
        # file holding some *other* fact is a genuine collision and still stops.
        prior = _spec_facts_on_disk(target)
        revises_own = prior is not None and \
            [row.get("fact_id") for row in prior] == [fact["fact_id"]]
        if target.exists() and not revises_own \
                and not _existing_target_matches(target, target_payload):
            raise CanonicalWriteError("spec fact file already exists for another fact; manual recovery required")

        # Only this trim's facts are read. Validation groups by
        # (trim_id, field_key, qualifier, start), so another trim's facts can
        # neither create nor hide a conflict here -- and a problem sitting in
        # some unrelated trim is not this command's to refuse, which is the
        # one behaviour that changes: the whole-tree read used to fail an edit
        # over data it was not touching.
        before = [to_jsonable(row) for row in self._trim_ledger(command.year, trim_id).facts]
        staged = self._trim_ledger(command.year, trim_id,
                                   skip=target if revises_own else None,
                                   extra={"schema_version": 1, "facts": [fact]})
        problems = staged.validate()
        if problems:
            raise CanonicalWriteError("spec validation failed: " + "; ".join(problems))
        _atomic_json(target, target_payload)
        self._remember_fact_file(command.year, target, target_payload)
        # The staged ledger is, by construction, the tree as it now stands for
        # this trim, so the post-write state does not have to be read back.
        after = [to_jsonable(row) for row in staged.facts]
        return "spec", "market_trim", trim_id, before, after, (str(target),)


__all__ = [
    "CanonicalWriteCommand",
    "CanonicalWriteError",
    "CanonicalWritePipeline",
    "WriteResult",
]
