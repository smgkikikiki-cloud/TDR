"""One validated, idempotent input path for canonical vehicle-market facts.

The batch pipeline is deliberately separate from DLT registration ingestion.
It stages every command against a copy of the canonical data tree first, then
copies the validated files into the real tree and writes the batch commit marker
last. A single accepted batch therefore feeds the same release projection used
by every TDR catalogue, price, specification and fitment surface.
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


class CanonicalInputError(ValueError):
    pass


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SOURCE_KINDS = {"ADMIN", "ECO", "OEM", "MEDIA", "PRICE_HARVEST", "MIGRATION", "API"}
_MAX_COMMANDS = 500


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)


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
            parsed = CanonicalWriteCommand.from_dict(command)
            if parsed.year != year:
                raise CanonicalInputError("all commands in a batch must use the batch year")
            if parsed.command_id in seen:
                raise CanonicalInputError(f"duplicate command_id {parsed.command_id!r}")
            seen.add(parsed.command_id)
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
            write_results = []
            changed_relative: set[Path] = set()
            for command in batch.commands:
                try:
                    result = writer.apply(command)
                except (CanonicalWriteError, ValueError) as exc:
                    raise CanonicalInputError(
                        f"batch {batch.batch_id!r} rejected at {command['command_id']}: {exc}"
                    ) from exc
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

            state = staged / str(batch.year) / "canonical_state"
            for name in ("revisions.jsonl", "outbox.jsonl"):
                path = state / name
                if path.is_file():
                    changed_relative.add(path.relative_to(staged))
            for path in (state / "shadow").glob("*.json"):
                changed_relative.add(path.relative_to(staged))

            # Data first and audit state second. The canonical writer can safely
            # recover an identical target file if a process dies between them.
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
