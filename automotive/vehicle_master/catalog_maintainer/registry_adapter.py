"""Read-only bridge to the canonical comparable-spec registry.

The source of truth is the same JSON read by lib/spec-field-registry.ts. This
adapter has no fallback registry: absent files, version changes, or checksum
drift fail closed. The small priority overlay remains separate policy input.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

REGISTRY_RELATIVE = Path("automotive/vehicle_master/vehreg/data/2026/product/comparable_specs/registry.json")
EDITOR_RELATIVE = Path("lib/trim-editor-fields.ts")
REGISTRY_SHA256 = "2e2f344005aaba99ea613e47b45af14e72a42e3029d942d21bda4a0be34c6d2b"
EDITOR_SHA256 = "defbfc98aea9502ed6a689a6fb2b485a25b8fe7fbaf731a84ecf5b2821596ba7"


class RegistryDriftError(ValueError):
    pass


def repository_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / REGISTRY_RELATIVE).is_file() and (parent / EDITOR_RELATIVE).is_file():
            return parent
    raise RegistryDriftError("canonical Vehicle Master registry/editor sources are missing")


def _read_pinned(path: Path, expected: str) -> bytes:
    if not path.is_file():
        raise RegistryDriftError(f"canonical source missing: {path}")
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise RegistryDriftError(f"canonical source checksum drift: {path}; expected {expected}, got {actual}")
    return raw


def _editor_aliases(source: str) -> dict[str, str]:
    """Extract only explicitly paired MarketTrim/editor names from the TS map."""
    starts = list(re.finditer(r'(?m)^\s*(?:\{\s*)?key:\s*"([^"\\]+)"', source))
    aliases: dict[str, set[str]] = {}
    for i, match in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(source)
        chunk = source[match.start():end]
        targets = re.search(r"targets:\s*\{([^}]*)\}", chunk, re.S)
        if not targets:
            continue
        fields = re.search(r'trimField:\s*"([^"\\]+)"', targets.group(1))
        spec = re.search(r'specKey:\s*"([^"\\]+)"', targets.group(1))
        if spec:
            aliases.setdefault(match.group(1), set()).add(spec.group(1))
            if fields:
                aliases.setdefault(fields.group(1), set()).add(spec.group(1))
    ambiguous = {key: sorted(values) for key, values in aliases.items() if len(values) != 1}
    if ambiguous:
        raise RegistryDriftError(f"ambiguous canonical field aliases: {ambiguous}")
    return {key: next(iter(values)) for key, values in aliases.items()}


def load_registry(*, root: Path | None = None) -> dict:
    root = root or repository_root()
    raw = _read_pinned(root / REGISTRY_RELATIVE, REGISTRY_SHA256)
    editor = _read_pinned(root / EDITOR_RELATIVE, EDITOR_SHA256)
    payload = json.loads(raw)
    if payload.get("schema_version") != 1 or not isinstance(payload.get("fields"), list):
        raise RegistryDriftError("canonical comparable-spec registry schema is unsupported")
    fields = {row.get("key"): row for row in payload["fields"]}
    if None in fields or len(fields) != len(payload["fields"]):
        raise RegistryDriftError("canonical comparable-spec keys must be unique")
    aliases = _editor_aliases(editor.decode("utf-8"))
    dangling = {alias: key for alias, key in aliases.items() if key not in fields}
    if dangling:
        raise RegistryDriftError(f"editor aliases target absent canonical keys: {dangling}")
    return {"schema_version": 1, "year": 2026,
            "registry_sha256": REGISTRY_SHA256, "editor_sha256": EDITOR_SHA256,
            "fields": fields, "aliases": aliases}


def resolve_key(key: str, registry: dict) -> str | None:
    if key in registry["fields"]:
        return key
    return registry["aliases"].get(key)


def adapt_snapshot(snapshot: dict, trim_ids: tuple[str, ...], registry: dict) -> tuple[dict, dict[str, str], list[dict]]:
    """Canonicalize known aliases and use registry applicability/units.

    Tier remains the maintainer's policy overlay. Unknown synthetic fixture keys
    are surfaced as OUT_OF_SCOPE by the caller, never silently invented here.
    """
    canonical = json.loads(json.dumps(snapshot))
    tiers: dict[str, str] = {}
    out_of_scope = []
    rows = []
    for source in snapshot.get("field_registry", []):
        key = source["key"]
        target = resolve_key(key, registry)
        if not target:
            if key.upper() in {"LIST_PRICE", "CAMPAIGN_PRICE", "ECO_STICKER_PRICE", "MSRP", "PRICE"} or source.get("owner") == "PRICE_LEDGER":
                reason = "PRICE_LEDGER_OWNED"
            elif source.get("tier") == "P3":
                reason = "P3_NO_STANDALONE_RETRIEVAL"
            else:
                reason = "UNRESOLVED_SYNTHETIC_FIELD_ALIAS"
            out_of_scope.append({"field_key": key, "tier": source.get("tier"), "reason_code": reason,
                                 "applicable_powertrains": source.get("applicable_powertrains", [])})
            continue
        if target in tiers and tiers[target] != source["tier"]:
            raise RegistryDriftError(f"priority overlay maps conflicting tiers to {target}")
        tiers[target] = source["tier"]
        definition = registry["fields"][target]
        rows.append({"key": target, "group": definition["group"], "tier": source["tier"],
                     "applicable_powertrains": definition.get("applicable_powertrains", []),
                     "canonical_unit": definition.get("canonical_unit"),
                     "value_type": definition["value_type"], "comparison_qualifiers": definition.get("comparison_qualifiers", [])})
    canonical["field_registry"] = rows
    for fact in canonical.get("facts", []):
        target = resolve_key(fact["field_key"], registry)
        if target:
            fact["field_key"] = target
    for model in canonical.get("models", []):
        model["specs"] = _map_payload(model.get("specs", {}), registry)
    for generation in canonical.get("generations", []):
        generation["specs"] = _map_payload(generation.get("specs", {}), registry)
    for variant in canonical.get("variants", []):
        variant["specs"] = _map_payload(variant.get("specs", {}), registry)
    for trim in canonical.get("trims", []):
        trim["specs"] = _map_payload(trim.get("specs", {}), registry)
    return canonical, tiers, out_of_scope


def _map_payload(specs: dict, registry: dict) -> dict:
    out = {}
    for key, value in specs.items():
        target = resolve_key(key, registry)
        if not target:
            continue
        if target in out and out[target] != value:
            raise RegistryDriftError(f"payload aliases conflict for canonical field {target}")
        out[target] = value
    return out
