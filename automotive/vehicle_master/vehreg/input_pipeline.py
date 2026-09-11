"""One validated, idempotent input path for canonical vehicle-market facts.

The batch pipeline is deliberately separate from DLT registration ingestion.
It stages every command against a copy of the canonical data tree first, then
copies the validated files into the real tree and writes the batch commit marker
last. A single accepted batch therefore feeds the same release projection used
by every TDR catalogue, price, specification and fitment surface.

Review dispositions also use this staging path, but remain workflow metadata:
they are committed through the same batch/PR workflow without entering PriceLedger
facts or the registration database. Trim retail lifecycle review is consumed by
the enriched serving release, but remains separate from MarketTrim identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from .canonical_write import CanonicalWriteCommand, CanonicalWriteError, CanonicalWritePipeline
from .catalog import DATA_DIR, DEFAULT_YEAR
from .eco_review_write import upsert_review_dispositions
from .price_coverage_review import upsert_coverage_disposition
from .retail_lifecycle_review import upsert_trim_lifecycle_disposition


class CanonicalInputError(ValueError):
    pass


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SOURCE_KINDS = {"ADMIN", "ECO", "OEM", "MEDIA", "PRICE_HARVEST", "MIGRATION", "API"}
_MAX_COMMANDS = 500
_SPECIAL_OPERATIONS = {
    "UPSERT_ECO_REVIEW",
    "UPSERT_PRICE_COVERAGE_REVIEW",
    "UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW",
}
_PRICE_COVERAGE_REASONS = {
    "AWAITING_FINAL_LIST_PRICE",
    "OFFICIAL_EVIDENCE_CONFLICT",
    "NO_RELIABLE_EVIDENCE",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)


def _validated_human_actor(command: dict[str, Any], operation: str) -> str:
    actor = str(command.get("actor") or "").strip()
    if not actor or actor.lower() in {"system", "agent", "agent-proposed"}:
        raise CanonicalInputError(f"{operation} requires an explicit HUMAN actor")
    return actor


def _validated_submitted_at(command: dict[str, Any], operation: str) -> datetime:
    submitted_at = str(command.get("submitted_at") or "").strip()
    try:
        parsed = datetime.fromisoformat(submitted_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CanonicalInputError(f"{operation} submitted_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise CanonicalInputError(f"{operation} submitted_at must include timezone")
    return parsed


def _validate_eco_review_command(command: dict[str, Any]) -> None:
    unknown = set(command) - {
        "operation", "command_id", "year", "actor", "reason", "submitted_at", "payload",
    }
    if unknown:
        raise CanonicalInputError(f"UPSERT_ECO_REVIEW unknown fields: {sorted(unknown)}")
    payload = command.get("payload")
    if not isinstance(payload, dict):
        raise CanonicalInputError("UPSERT_ECO_REVIEW requires payload object")
    unknown_payload = set(payload) - {"snapshot_date", "action", "source_ids", "notes"}
    if unknown_payload:
        raise CanonicalInputError(f"UPSERT_ECO_REVIEW payload unknown fields: {sorted(unknown_payload)}")
    snapshot_date = str(payload.get("snapshot_date") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", snapshot_date):
        raise CanonicalInputError("UPSERT_ECO_REVIEW snapshot_date must be YYYY-MM-DD")
    try:
        datetime.fromisoformat(snapshot_date)
    except ValueError as exc:
        raise CanonicalInputError("UPSERT_ECO_REVIEW snapshot_date is invalid") from exc
    action = str(payload.get("action") or "").strip().lower()
    if action not in {"reject", "defer", "reopen"}:
        raise CanonicalInputError("UPSERT_ECO_REVIEW action must be reject, defer or reopen")
    source_ids = payload.get("source_ids")
    if not isinstance(source_ids, list) or not source_ids or len(source_ids) > 100:
        raise CanonicalInputError("UPSERT_ECO_REVIEW source_ids must contain 1–100 IDs")
    normalized_ids = [str(value or "").strip().lower() for value in source_ids]
    if any(not value for value in normalized_ids) or len(normalized_ids) != len(set(normalized_ids)):
        raise CanonicalInputError("UPSERT_ECO_REVIEW source_ids must be non-empty and unique")
    _validated_human_actor(command, "UPSERT_ECO_REVIEW")
    _validated_submitted_at(command, "UPSERT_ECO_REVIEW")


def _validate_price_coverage_review_command(command: dict[str, Any]) -> None:
    unknown = set(command) - {
        "operation", "command_id", "year", "actor", "reason", "submitted_at", "payload",
    }
    if unknown:
        raise CanonicalInputError(
            f"UPSERT_PRICE_COVERAGE_REVIEW unknown fields: {sorted(unknown)}")
    payload = command.get("payload")
    if not isinstance(payload, dict):
        raise CanonicalInputError("UPSERT_PRICE_COVERAGE_REVIEW requires payload object")
    unknown_payload = set(payload) - {
        "trim_id", "action", "reason_code", "source_ref", "notes",
    }
    if unknown_payload:
        raise CanonicalInputError(
            "UPSERT_PRICE_COVERAGE_REVIEW payload unknown fields: "
            f"{sorted(unknown_payload)}")
    trim_id = str(payload.get("trim_id") or "").strip()
    if not trim_id or len(trim_id) > 255:
        raise CanonicalInputError("UPSERT_PRICE_COVERAGE_REVIEW trim_id is required")
    action = str(payload.get("action") or "").strip().lower()
    if action not in {"defer", "reopen"}:
        raise CanonicalInputError(
            "UPSERT_PRICE_COVERAGE_REVIEW action must be defer or reopen")
    reason_code = str(payload.get("reason_code") or "").strip().upper()
    source_ref = str(payload.get("source_ref") or "").strip()
    if action == "defer":
        if reason_code not in _PRICE_COVERAGE_REASONS:
            raise CanonicalInputError(
                "UPSERT_PRICE_COVERAGE_REVIEW reason_code must be one of "
                f"{sorted(_PRICE_COVERAGE_REASONS)}")
        if not source_ref.startswith(("https://", "http://")):
            raise CanonicalInputError(
                "UPSERT_PRICE_COVERAGE_REVIEW defer requires http(s) source_ref")
    _validated_human_actor(command, "UPSERT_PRICE_COVERAGE_REVIEW")
    _validated_submitted_at(command, "UPSERT_PRICE_COVERAGE_REVIEW")


def _validate_trim_lifecycle_review_command(command: dict[str, Any]) -> None:
    operation = "UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW"
    unknown = set(command) - {
        "operation", "command_id", "year", "actor", "reason", "submitted_at", "payload",
    }
    if unknown:
        raise CanonicalInputError(f"{operation} unknown fields: {sorted(unknown)}")
    payload = command.get("payload")
    if not isinstance(payload, dict):
        raise CanonicalInputError(f"{operation} requires payload object")
    unknown_payload = set(payload) - {"trim_id", "action", "source_ref", "notes"}
    if unknown_payload:
        raise CanonicalInputError(f"{operation} payload unknown fields: {sorted(unknown_payload)}")
    trim_id = str(payload.get("trim_id") or "").strip()
    if not trim_id or len(trim_id) > 255:
        raise CanonicalInputError(f"{operation} trim_id is required")
    action = str(payload.get("action") or "").strip().lower()
    if action not in {"current", "historical", "reopen"}:
        raise CanonicalInputError(f"{operation} action must be current, historical or reopen")
    source_ref = str(payload.get("source_ref") or "").strip()
    if action != "reopen" and not source_ref.startswith(("https://", "http://")):
        raise CanonicalInputError(f"{operation} current/historical requires http(s) source_ref")
    _validated_human_actor(command, operation)
    _validated_submitted_at(command, operation)


def _apply_eco_review_command(staged: Path, command: dict[str, Any]) -> tuple[dict[str, Any], Path | None]:
    _validate_eco_review_command(command)
    payload = command["payload"]
    reviewed_at = _validated_submitted_at(command, "UPSERT_ECO_REVIEW").date().isoformat()
    result = upsert_review_dispositions(
        data_dir=staged,
        year=int(command["year"]),
        snapshot_date=str(payload["snapshot_date"]),
        source_ids=payload["source_ids"],
        action=str(payload["action"]),
        reviewer=str(command["actor"]),
        reviewed_at=reviewed_at,
        notes=str(payload.get("notes") or command.get("reason") or ""),
        write=True,
    )
    path = Path(result["path"])
    return ({
        "command_id": str(command["command_id"]),
        "revision_id": f"eco-review-{_hash(command)[:16]}",
        "topic": "eco_review",
        "entity_type": "ecosticker_review",
        "entity_id": str(payload["snapshot_date"]),
        "idempotent_replay": not bool(result["changed"]),
    }, path if result["changed"] else None)


def _apply_price_coverage_review_command(
        staged: Path, command: dict[str, Any]) -> tuple[dict[str, Any], Path | None]:
    _validate_price_coverage_review_command(command)
    payload = command["payload"]
    reviewed_at = _validated_submitted_at(
        command, "UPSERT_PRICE_COVERAGE_REVIEW").date().isoformat()
    result = upsert_coverage_disposition(
        data_dir=staged,
        year=int(command["year"]),
        trim_id=str(payload["trim_id"]),
        action=str(payload["action"]),
        reason_code=str(payload.get("reason_code") or ""),
        reviewer=str(command["actor"]),
        reviewed_at=reviewed_at,
        source_ref=str(payload.get("source_ref") or ""),
        notes=str(payload.get("notes") or command.get("reason") or ""),
        write=True,
    )
    path = Path(result["path"])
    return ({
        "command_id": str(command["command_id"]),
        "revision_id": f"price-coverage-review-{_hash(command)[:16]}",
        "topic": "price_coverage_review",
        "entity_type": "price_coverage_review",
        "entity_id": str(payload["trim_id"]),
        "idempotent_replay": not bool(result["changed"]),
    }, path if result["changed"] else None)


def _apply_trim_lifecycle_review_command(
        staged: Path, command: dict[str, Any]) -> tuple[dict[str, Any], Path | None]:
    operation = "UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW"
    _validate_trim_lifecycle_review_command(command)
    payload = command["payload"]
    reviewed_at = _validated_submitted_at(command, operation).date().isoformat()
    result = upsert_trim_lifecycle_disposition(
        data_dir=staged,
        year=int(command["year"]),
        trim_id=str(payload["trim_id"]),
        action=str(payload["action"]),
        reviewer=str(command["actor"]),
        reviewed_at=reviewed_at,
        source_ref=str(payload.get("source_ref") or ""),
        notes=str(payload.get("notes") or command.get("reason") or ""),
        write=True,
    )
    path = Path(result["path"])
    return ({
        "command_id": str(command["command_id"]),
        "revision_id": f"trim-retail-lifecycle-review-{_hash(command)[:16]}",
        "topic": "trim_retail_lifecycle_review",
        "entity_type": "market_trim_retail_lifecycle_review",
        "entity_id": str(payload["trim_id"]),
        "idempotent_replay": not bool(result["changed"]),
    }, path if result["changed"] else None)


@dataclass(frozen=True, slots=True)
class CanonicalInputBatch:
    batch_id: str
    year: int
    source_kind: str
    source_ref: str | None
    actor: str
    reason: str
    submitted_at: str
    commands: tuple[dict[str, Any], ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CanonicalInputBatch":
        if not isinstance(raw, dict):
            raise CanonicalInputError("input batch must be an object")
        unknown = set(raw) - {
            "schema_version", "batch_id", "year", "source", "actor", "reason",
            "submitted_at", "commands",
        }
        if unknown:
            raise CanonicalInputError(f"unknown input batch fields: {sorted(unknown)}")
        if raw.get("schema_version", 1) != 1:
            raise CanonicalInputError("unsupported input batch schema_version")
        batch_id = str(raw.get("batch_id") or "").strip()
        if not _SAFE_ID.fullmatch(batch_id):
            raise CanonicalInputError("batch_id must be a safe stable token")
        try:
            year = int(raw.get("year") or DEFAULT_YEAR)
        except (TypeError, ValueError) as exc:
            raise CanonicalInputError("year must be an integer") from exc
        if year < 2000 or year > 2100:
            raise CanonicalInputError("year is outside the supported range")
        source = raw.get("source") or {}
        if not isinstance(source, dict):
            raise CanonicalInputError("source must be an object")
        source_kind = str(source.get("kind") or "").strip().upper()
        if source_kind in {"DLT", "REGISTRATION"}:
            raise CanonicalInputError(
                "registration input is a separate analytics pipeline and cannot enter Vehicle Master"
            )
        if source_kind not in _SOURCE_KINDS:
            raise CanonicalInputError(f"unsupported source kind {source_kind!r}")
        source_ref = str(source.get("ref") or "").strip() or None
        commands = raw.get("commands")
        if not isinstance(commands, list) or not commands:
            raise CanonicalInputError("commands must be a non-empty array")
        if len(commands) > _MAX_COMMANDS:
            raise CanonicalInputError(f"one batch may contain at most {_MAX_COMMANDS} commands")
        submitted_at = str(raw.get("submitted_at") or "").strip()
        if not submitted_at:
            raise CanonicalInputError("submitted_at is required for deterministic retries")
        try:
            submitted_datetime = datetime.fromisoformat(submitted_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CanonicalInputError("submitted_at must be an ISO-8601 timestamp") from exc
        if submitted_datetime.tzinfo is None:
            raise CanonicalInputError("submitted_at must include a timezone")
        actor = str(raw.get("actor") or "system").strip() or "system"
        reason = str(raw.get("reason") or "").strip()
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, item in enumerate(commands, start=1):
            if not isinstance(item, dict):
                raise CanonicalInputError(f"commands[{index - 1}] must be an object")
            command = {
                **item,
                "command_id": str(item.get("command_id") or f"{batch_id}:{index}"),
                "year": year,
                "actor": str(item.get("actor") or actor),
                "reason": str(item.get("reason") or reason),
                "submitted_at": str(item.get("submitted_at") or submitted_at),
            }
            operation = str(command.get("operation") or "").strip().upper()
            if operation in _SPECIAL_OPERATIONS:
                command["operation"] = operation
                if operation == "UPSERT_ECO_REVIEW":
                    if source_kind != "ECO":
                        raise CanonicalInputError("UPSERT_ECO_REVIEW requires source.kind ECO")
                    _validate_eco_review_command(command)
                elif operation == "UPSERT_PRICE_COVERAGE_REVIEW":
                    if source_kind != "ADMIN":
                        raise CanonicalInputError(
                            "UPSERT_PRICE_COVERAGE_REVIEW requires source.kind ADMIN")
                    _validate_price_coverage_review_command(command)
                elif operation == "UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW":
                    if source_kind != "ADMIN":
                        raise CanonicalInputError(
                            "UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW requires source.kind ADMIN")
                    _validate_trim_lifecycle_review_command(command)
                parsed_id = str(command["command_id"])
            else:
                parsed = CanonicalWriteCommand.from_dict(command)
                if parsed.year != year:
                    raise CanonicalInputError("all commands in a batch must use the batch year")
                parsed_id = parsed.command_id
            if parsed_id in seen:
                raise CanonicalInputError(f"duplicate command_id {parsed_id!r}")
            seen.add(parsed_id)
            normalized.append(command)
        return cls(
            batch_id=batch_id,
            year=year,
            source_kind=source_kind,
            source_ref=source_ref,
            actor=actor,
            reason=reason,
            submitted_at=submitted_at,
            commands=tuple(normalized),
        )

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "batch_id": self.batch_id,
            "year": self.year,
            "source": {"kind": self.source_kind, "ref": self.source_ref},
            "actor": self.actor,
            "reason": self.reason,
            "submitted_at": self.submitted_at,
            "commands": list(self.commands),
        }


@dataclass(frozen=True, slots=True)
class CanonicalInputResult:
    batch_id: str
    batch_hash: str
    status: str
    results: tuple[dict[str, Any], ...]
    changed_files: tuple[str, ...]
    idempotent_replay: bool = False


class CanonicalInputPipeline:
    def __init__(self, data_dir: Path | str = DATA_DIR) -> None:
        self.data_dir = Path(data_dir)

    def _marker(self, batch: CanonicalInputBatch) -> Path:
        return (
            self.data_dir / str(batch.year) / "canonical_state" /
            "input_batches" / f"{batch.batch_id}.json"
        )

    def apply(self, raw: dict[str, Any] | CanonicalInputBatch) -> CanonicalInputResult:
        batch = raw if isinstance(raw, CanonicalInputBatch) else CanonicalInputBatch.from_dict(raw)
        batch_hash = _hash(batch.semantic_payload())
        marker = self._marker(batch)
        if marker.is_file():
            saved = json.loads(marker.read_text(encoding="utf-8"))
            if saved.get("batch_hash") != batch_hash:
                raise CanonicalInputError(
                    f"batch_id {batch.batch_id!r} was already used with different content"
                )
            return CanonicalInputResult(
                batch_id=batch.batch_id,
                batch_hash=batch_hash,
                status=str(saved.get("status") or "APPLIED"),
                results=tuple(saved.get("results") or ()),
                changed_files=tuple(saved.get("changed_files") or ()),
                idempotent_replay=True,
            )

        if not self.data_dir.is_dir():
            raise CanonicalInputError(f"canonical data directory does not exist: {self.data_dir}")

        with tempfile.TemporaryDirectory(prefix="tdr-canonical-input-") as temp:
            staged = Path(temp) / "data"
            shutil.copytree(self.data_dir, staged)
            writer = CanonicalWritePipeline(staged)
            write_results: list[dict[str, Any]] = []
            changed_relative: set[Path] = set()
            canonical_write_applied = False
            for command in batch.commands:
                operation = str(command.get("operation") or "").strip().upper()
                if operation in _SPECIAL_OPERATIONS:
                    try:
                        if operation == "UPSERT_ECO_REVIEW":
                            review_result, changed_path = _apply_eco_review_command(staged, command)
                        elif operation == "UPSERT_PRICE_COVERAGE_REVIEW":
                            review_result, changed_path = _apply_price_coverage_review_command(
                                staged, command)
                        else:
                            review_result, changed_path = _apply_trim_lifecycle_review_command(
                                staged, command)
                    except (CanonicalInputError, ValueError, KeyError, TypeError) as exc:
                        raise CanonicalInputError(
                            f"batch {batch.batch_id!r} rejected at {command['command_id']}: {exc}"
                        ) from exc
                    write_results.append(review_result)
                    if changed_path is not None:
                        changed_relative.add(changed_path.relative_to(staged))
                    continue
                try:
                    result = writer.apply(command)
                except (CanonicalWriteError, ValueError) as exc:
                    raise CanonicalInputError(
                        f"batch {batch.batch_id!r} rejected at {command['command_id']}: {exc}"
                    ) from exc
                canonical_write_applied = True
                write_results.append({
                    "command_id": result.command_id,
                    "revision_id": result.revision_id,
                    "topic": result.topic,
                    "entity_type": result.entity_type,
                    "entity_id": result.entity_id,
                    "idempotent_replay": result.idempotent_replay,
                })
                for changed in result.changed_files:
                    changed_relative.add(Path(changed).relative_to(staged))

            # Review-only batches must not pretend pre-existing revision/outbox/
            # shadow files changed. Those audit artifacts belong only to normal
            # canonical writes. This also fixes the older ECO/price-review path.
            if canonical_write_applied:
                state = staged / str(batch.year) / "canonical_state"
                for name in ("revisions.jsonl", "outbox.jsonl"):
                    path = state / name
                    if path.is_file():
                        changed_relative.add(path.relative_to(staged))
                for path in (state / "shadow").glob("*.json"):
                    changed_relative.add(path.relative_to(staged))

            # Data/review artifacts first and audit state second. Canonical
            # writes can recover identical targets if a process dies between
            # them. Review state is workflow metadata and intentionally has no
            # canonical writer outbox entry of its own.
            ordered = sorted(changed_relative, key=lambda path: "canonical_state" in path.parts)
            for relative in ordered:
                _atomic_bytes(self.data_dir / relative, (staged / relative).read_bytes())

        saved = {
            "schema_version": 1,
            "batch_id": batch.batch_id,
            "batch_hash": batch_hash,
            "status": "APPLIED",
            "year": batch.year,
            "source": {"kind": batch.source_kind, "ref": batch.source_ref},
            "actor": batch.actor,
            "reason": batch.reason,
            "submitted_at": batch.submitted_at,
            "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "results": write_results,
            "changed_files": [str(path) for path in ordered],
        }
        _atomic_bytes(marker, (json.dumps(saved, ensure_ascii=False, indent=2) + "\n").encode())
        return CanonicalInputResult(
            batch_id=batch.batch_id,
            batch_hash=batch_hash,
            status="APPLIED",
            results=tuple(write_results),
            changed_files=tuple(saved["changed_files"] + [str(marker.relative_to(self.data_dir))]),
        )


__all__ = [
    "CanonicalInputBatch", "CanonicalInputError", "CanonicalInputPipeline", "CanonicalInputResult",
]
