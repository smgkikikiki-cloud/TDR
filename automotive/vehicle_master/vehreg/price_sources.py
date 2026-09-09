"""Price-intelligence source and fetch-target registry.

A source answers *who is speaking* and how much authority that voice carries.
A target answers *which page/feed is being watched* and what temporal role that
page has. Keeping those separate is important: an OEM's current model page,
promotion archive and launch press release are all first-party, but they do not
mean the same thing when reconciling a price.

This module is configuration only. It performs no network access and writes no
price records. Existing :mod:`vehreg.pricefeed` source loading remains valid;
this richer registry sits alongside it so P2 adapters can consume explicit
fetch targets without breaking the current WordPress harvester.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

from .catalog import DATA_DIR, DEFAULT_YEAR
from .pricefeed import Source, feed_dir, load_sources


SCHEMA_VERSION = 1


class SourceKind(str, Enum):
    OEM = "OEM"
    MEDIA = "MEDIA"
    GOVERNMENT = "GOVERNMENT"
    DEALER = "DEALER"
    OTHER = "OTHER"

    @classmethod
    def parse(cls, raw: object) -> "SourceKind":
        try:
            return cls(str(raw or "OTHER").strip().upper())
        except ValueError as exc:
            raise ValueError(f"unknown source kind {raw!r}") from exc


class TargetRole(str, Enum):
    """Temporal/semantic role of one fetch target, not source authority."""

    CURRENT_MODEL_PAGE = "CURRENT_MODEL_PAGE"
    PRICE_LIST = "PRICE_LIST"
    PROMOTION_INDEX = "PROMOTION_INDEX"
    PROMOTION = "PROMOTION"
    PRESS_RELEASE = "PRESS_RELEASE"
    LAUNCH_PAGE = "LAUNCH_PAGE"
    BLOG = "BLOG"
    DISCOVERY_FEED = "DISCOVERY_FEED"

    @classmethod
    def parse(cls, raw: object) -> "TargetRole":
        try:
            return cls(str(raw or "").strip().upper())
        except ValueError as exc:
            raise ValueError(f"unknown target role {raw!r}") from exc


@dataclass(frozen=True, slots=True)
class SourceProfile:
    """Richer metadata for a source already known to ``pricefeed.Source``."""

    source_id: str
    kind: SourceKind
    legacy: bool = False
    notes: str = ""

    def validate(self, sources: dict[str, Source]) -> list[str]:
        problems: list[str] = []
        if not self.source_id:
            problems.append("source profile requires source_id")
        elif self.source_id not in sources:
            problems.append(f"source profile references unknown source {self.source_id}")
        if not isinstance(self.kind, SourceKind):
            problems.append(f"source profile {self.source_id}: kind must be SourceKind")
        return problems


@dataclass(frozen=True, slots=True)
class SourceTarget:
    """One URL/feed P2 may fetch.

    ``adapter`` and ``poll_minutes`` override the source defaults only for this
    target. ``model_hint`` is a canonical model id hint, never permission to
    skip entity/trim matching.
    """

    id: str
    source_id: str
    url: str
    role: TargetRole
    adapter: str = ""
    poll_minutes: Optional[int] = None
    enabled: bool = True
    model_hint: str = ""
    notes: str = ""

    def validate(self, sources: dict[str, Source]) -> list[str]:
        problems: list[str] = []
        if not self.id:
            problems.append("target id is required")
        if not self.source_id:
            problems.append(f"target {self.id}: source_id is required")
        elif self.source_id not in sources:
            problems.append(f"target {self.id}: unknown source {self.source_id}")
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or not parsed.netloc:
            problems.append(f"target {self.id}: url must be absolute https")
        if not isinstance(self.role, TargetRole):
            problems.append(f"target {self.id}: role must be TargetRole")
        if self.poll_minutes is not None and (
                type(self.poll_minutes) is not int or self.poll_minutes <= 0):
            problems.append(f"target {self.id}: poll_minutes must be positive")
        if not isinstance(self.enabled, bool):
            problems.append(f"target {self.id}: enabled must be boolean")
        return problems


class SourceTargetRegistry:
    """Validated source profiles plus explicit fetch targets."""

    def __init__(self, *, sources: dict[str, Source],
                 profiles: Iterable[SourceProfile] = (),
                 targets: Iterable[SourceTarget] = ()) -> None:
        self.sources = dict(sources)
        self.profiles = {profile.source_id: profile for profile in profiles}
        self.targets = {target.id: target for target in targets}

    def validate(self) -> list[str]:
        problems: list[str] = []
        for profile in self.profiles.values():
            problems.extend(profile.validate(self.sources))
        for target in self.targets.values():
            problems.extend(target.validate(self.sources))
        return problems

    def targets_for(self, *, source_id: Optional[str] = None,
                    role: Optional[TargetRole] = None,
                    enabled_only: bool = True) -> list[SourceTarget]:
        rows = list(self.targets.values())
        if source_id is not None:
            rows = [target for target in rows if target.source_id == source_id]
        if role is not None:
            rows = [target for target in rows if target.role is role]
        if enabled_only:
            rows = [target for target in rows if target.enabled]
        return sorted(rows, key=lambda target: target.id)

    def effective_adapter(self, target: SourceTarget) -> str:
        return target.adapter or self.sources[target.source_id].adapter

    def effective_poll_minutes(self, target: SourceTarget) -> int:
        return target.poll_minutes or self.sources[target.source_id].poll_minutes


def _registry_path(data_dir: Path | str, year: int) -> Path:
    return feed_dir(data_dir, year) / "targets.json"


def _profile_from_dict(raw: object, source: str) -> SourceProfile:
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: source profile must be an object")
    allowed = {"source_id", "kind", "legacy", "notes"}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"{source}: unknown source profile fields: {sorted(unknown)}")
    return SourceProfile(
        source_id=str(raw.get("source_id") or "").strip(),
        kind=SourceKind.parse(raw.get("kind")),
        legacy=bool(raw.get("legacy", False)),
        notes=str(raw.get("notes") or "").strip(),
    )


def _target_from_dict(raw: object, source: str) -> SourceTarget:
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: target must be an object")
    allowed = {"id", "source_id", "url", "role", "adapter", "poll_minutes",
               "enabled", "model_hint", "notes"}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"{source}: unknown target fields: {sorted(unknown)}")
    poll = raw.get("poll_minutes")
    if poll is not None and (isinstance(poll, bool) or not str(poll).isdigit()):
        raise ValueError(f"{source}: poll_minutes must be a positive integer")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"{source}: enabled must be boolean")
    return SourceTarget(
        id=str(raw.get("id") or "").strip(),
        source_id=str(raw.get("source_id") or "").strip(),
        url=str(raw.get("url") or "").strip(),
        role=TargetRole.parse(raw.get("role")),
        adapter=str(raw.get("adapter") or "").strip(),
        poll_minutes=int(poll) if poll is not None else None,
        enabled=enabled,
        model_hint=str(raw.get("model_hint") or "").strip(),
        notes=str(raw.get("notes") or "").strip(),
    )


def load_source_target_registry(data_dir: Path | str = DATA_DIR,
                                year: int = DEFAULT_YEAR) -> SourceTargetRegistry:
    """Load the existing source registry plus P1 target metadata."""

    sources = load_sources(data_dir, year)
    path = _registry_path(data_dir, year)
    if not path.is_file():
        return SourceTargetRegistry(sources=sources)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"{path}: schema_version must be {SCHEMA_VERSION}, got "
            f"{payload.get('schema_version')!r}")
    if not isinstance(payload.get("source_profiles"), list):
        raise ValueError(f"{path}: source_profiles must be an array")
    if not isinstance(payload.get("targets"), list):
        raise ValueError(f"{path}: targets must be an array")

    profiles_list = [_profile_from_dict(raw, str(path))
                     for raw in payload["source_profiles"]]
    if len({profile.source_id for profile in profiles_list}) != len(profiles_list):
        raise ValueError(f"{path}: duplicate source profile")
    targets_list = [_target_from_dict(raw, str(path)) for raw in payload["targets"]]
    if len({target.id for target in targets_list}) != len(targets_list):
        raise ValueError(f"{path}: duplicate target id")

    registry = SourceTargetRegistry(
        sources=sources, profiles=profiles_list, targets=targets_list)
    problems = registry.validate()
    if problems:
        raise ValueError(f"{path}: " + "; ".join(sorted(set(problems))))
    return registry
