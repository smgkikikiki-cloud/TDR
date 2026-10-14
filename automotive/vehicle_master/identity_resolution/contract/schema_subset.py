"""A stdlib validator for the JSON Schema subset the v1 contract uses.

The repository's CI installs PyYAML but not ``jsonschema``, and the contract must be machine-checked
there. Rather than add a dependency, the schemas are written in a small, explicit subset and this module
validates exactly that subset. ``unsupported_keywords`` lets a test fail the moment a schema uses a
keyword this validator would silently ignore, so the two can never drift apart.

Supported: type, enum, const, required, properties, additionalProperties, items, minItems, maxItems,
minimum, maximum, minLength, pattern, oneOf, anyOf, allOf, if/then/else, $ref (local ``#/...`` or
``<file>#/...`` through a registry). Annotation keywords are ignored by design.
"""
from __future__ import annotations

import re
from typing import Any, Iterator

ANNOTATIONS = frozenset({"$schema", "$id", "$comment", "title", "description", "examples", "default", "$defs"})
SUPPORTED = frozenset({
    "type", "enum", "const", "required", "properties", "additionalProperties", "items", "minItems",
    "maxItems", "minimum", "maximum", "minLength", "pattern", "oneOf", "anyOf", "allOf", "if", "then",
    "else", "$ref",
}) | ANNOTATIONS

Registry = dict[str, dict]


def _subschemas(schema: dict) -> Iterator[dict]:
    for key in ("items", "additionalProperties", "if", "then", "else"):
        value = schema.get(key)
        if isinstance(value, dict):
            yield value
    for key in ("oneOf", "anyOf", "allOf"):
        for value in schema.get(key, []):
            yield value
    for value in schema.get("properties", {}).values():
        yield value
    for value in schema.get("$defs", {}).values():
        yield value


def unsupported_keywords(schema: dict, path: str = "#") -> list[str]:
    """Every keyword in ``schema`` that this validator does not implement (with its location)."""
    problems = [f"{path}: {key}" for key in schema if key not in SUPPORTED]
    for index, sub in enumerate(_subschemas(schema)):
        problems.extend(unsupported_keywords(sub, f"{path}/{index}"))
    return problems


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "number": _is_number,
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def _equal(a: Any, b: Any) -> bool:
    """JSON equality: True != 1, 1 == 1.0."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _is_number(a) and _is_number(b):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_equal(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _resolve(ref: str, root: dict, registry: Registry) -> tuple[dict, dict]:
    document, _, pointer = ref.partition("#")
    target_root = registry[document] if document else root
    node: Any = target_root
    for part in [p for p in pointer.split("/") if p]:
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node, target_root


def validate(instance: Any, schema: dict, *, registry: Registry | None = None,
             root: dict | None = None, path: str = "$") -> list[str]:
    """Return a list of human-readable violations (empty = valid)."""
    registry = registry or {}
    root = root if root is not None else schema
    errors: list[str] = []

    if "$ref" in schema:
        target, target_root = _resolve(schema["$ref"], root, registry)
        errors.extend(validate(instance, target, registry=registry, root=target_root, path=path))

    expected = schema.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        if not any(_TYPE_CHECKS[name](instance) for name in names):
            errors.append(f"{path}: expected type {expected}, got {type(instance).__name__}")
            return errors

    if "enum" in schema and not any(_equal(instance, option) for option in schema["enum"]):
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']}")
    if "const" in schema and not _equal(instance, schema["const"]):
        errors.append(f"{path}: expected const {schema['const']!r}, got {instance!r}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: string shorter than {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append(f"{path}: {instance!r} does not match {schema['pattern']!r}")

    if _is_number(instance):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} > maximum {schema['maximum']}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(instance):
                errors.extend(validate(item, schema["items"], registry=registry, root=root, path=f"{path}[{index}]"))

    if isinstance(instance, dict):
        for name in schema.get("required", []):
            if name not in instance:
                errors.append(f"{path}: missing required property {name!r}")
        properties = schema.get("properties", {})
        for name, value in instance.items():
            if name in properties:
                errors.extend(validate(value, properties[name], registry=registry, root=root, path=f"{path}.{name}"))
            else:
                extra = schema.get("additionalProperties", True)
                if extra is False:
                    errors.append(f"{path}: unexpected property {name!r}")
                elif isinstance(extra, dict):
                    errors.extend(validate(value, extra, registry=registry, root=root, path=f"{path}.{name}"))

    for sub in schema.get("allOf", []):
        errors.extend(validate(instance, sub, registry=registry, root=root, path=path))
    if "anyOf" in schema and not any(
            not validate(instance, sub, registry=registry, root=root, path=path) for sub in schema["anyOf"]):
        errors.append(f"{path}: matches none of anyOf")
    if "oneOf" in schema:
        matches = sum(1 for sub in schema["oneOf"] if not validate(instance, sub, registry=registry, root=root, path=path))
        if matches != 1:
            errors.append(f"{path}: matches {matches} of oneOf (exactly 1 required)")
    if "if" in schema:
        condition_holds = not validate(instance, schema["if"], registry=registry, root=root, path=path)
        branch = schema.get("then") if condition_holds else schema.get("else")
        if branch is not None:
            errors.extend(validate(instance, branch, registry=registry, root=root, path=path))

    return errors
