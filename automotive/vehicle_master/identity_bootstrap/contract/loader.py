"""Load the versioned Identity Bootstrap contract files. Strict by design: duplicate keys are errors, never last-wins."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

CONTRACT_ROOT = Path(__file__).resolve().parent

SCHEMA_FILES = ("input.schema.json", "decision.schema.json", "event.schema.json", "case.schema.json")


class DuplicateKeyError(ValueError):
    pass


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys (PyYAML silently keeps the last one)."""


def _construct_mapping(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise DuplicateKeyError(f"duplicate YAML key {key!r} (line {key_node.start_mark.line + 1})")
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _json_object(pairs: list[tuple[str, Any]]) -> dict:
    keys = [key for key, _ in pairs]
    duplicates = {key for key in keys if keys.count(key) > 1}
    if duplicates:
        raise DuplicateKeyError(f"duplicate JSON key(s) {sorted(duplicates)}")
    return dict(pairs)


def contract_dir(version: str = "v1") -> Path:
    path = CONTRACT_ROOT / version
    if not path.is_dir():
        raise FileNotFoundError(f"no such contract version: {version}")
    return path


def load_yaml(name: str, version: str = "v1") -> dict:
    with (contract_dir(version) / name).open(encoding="utf-8") as handle:
        return yaml.load(handle, Loader=_StrictLoader)


def load_json(name: str, version: str = "v1") -> dict:
    with (contract_dir(version) / name).open(encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=_json_object)


def load_policy(version: str = "v1") -> dict:
    return load_yaml("policy.yaml", version)


def load_reason_codes(version: str = "v1") -> dict:
    return load_yaml("reason_codes.yaml", version)


def load_taxonomy(version: str = "v1") -> dict:
    return load_yaml("taxonomy.yaml", version)


def load_lifecycle(version: str = "v1") -> dict:
    return load_yaml("lifecycle.yaml", version)


def load_schema_registry(version: str = "v1") -> dict[str, dict]:
    return {name: load_json(name, version) for name in SCHEMA_FILES}


def load_cases(version: str = "v1") -> list[dict]:
    """One JSON object per non-empty line."""
    cases = []
    with (contract_dir(version) / "cases.jsonl").open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                cases.append(json.loads(line, object_pairs_hook=_json_object))
            except ValueError as exc:
                raise ValueError(f"cases.jsonl line {number}: {exc}") from exc
    return cases
