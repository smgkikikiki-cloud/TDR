"""Render the generated appendices of SPEC.md from the machine-readable contract files.

    python -m identity_resolution.contract.render            # print every appendix
    python -m identity_resolution.contract.render --check    # exit 1 if SPEC.md is out of date
    python -m identity_resolution.contract.render --write    # rewrite the generated blocks in SPEC.md

The appendices are DERIVED data (the policy key index, the reason-code registry, the edge-case taxonomy). They are
generated so that SPEC.md can never drift from policy.yaml, reason_codes.yaml and taxonomy.yaml: a test fails when
the committed blocks differ from what this module renders.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from . import loader

#: Maps whose entries are listed as one policy key (their content is long and structured; policy.yaml is the source).
MAP_LEAVES = frozenset({
    "aliases.brand", "aliases.model", "attributes.body.compatibility", "state.write_matrix", "review.routing", "fingerprint.bands",
})
SKIP_ROOTS = frozenset({"policy", "provenance", "alias_provenance"})


def policy_leaves(policy: dict) -> list[tuple[str, Any]]:
    """Every policy key a decision can depend on, as (dotted path, value)."""
    leaves: list[tuple[str, Any]] = []

    def walk(node: Any, path: str) -> None:
        if path in MAP_LEAVES or not isinstance(node, dict):
            leaves.append((path, node))
            return
        for key, value in node.items():
            walk(value, f"{path}.{key}" if path else str(key))

    for root, value in policy.items():
        if root not in SKIP_ROOTS:
            walk(value, root)
    return leaves


def provenance_of(path: str, provenance: dict) -> str | None:
    """The tag of the longest provenance key that is `path` or an ancestor of it."""
    parts = path.split(".")
    for end in range(len(parts), 0, -1):
        tag = provenance.get(".".join(parts[:end]))
        if tag is not None:
            return tag
    return None


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _value(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
    if len(text) > 90:
        count = len(value) if hasattr(value, "__len__") else 1
        return f"({count} entries — see policy.yaml)"
    return text


def render_policy_index(policy: dict) -> str:
    rows = ["| Policy key | Value | Provenance |", "|---|---|---|"]
    for path, value in policy_leaves(policy):
        rows.append(f"| `{path}` | `{_cell(_value(value))}` | {provenance_of(path, policy['provenance']) or '—'} |")
    return "\n".join(rows)


def render_reason_codes(registry: dict) -> str:
    rows = ["| Code | Kind | Roles | Effect | Primary for | Summary |", "|---|---|---|---|---|---|"]
    for code, spec in registry["codes"].items():
        rows.append("| `{}` | {} | {} | {} | {} | {} |".format(
            code, spec["kind"], ", ".join(spec["roles"]), spec["effect"], ", ".join(spec.get("primary_for", [])) or "—", _cell(spec["summary"])))
    return "\n".join(rows)


def render_taxonomy(taxonomy: dict) -> str:
    rows = ["| Id | Edge case | Origin | Reason codes |", "|---|---|---|---|"]
    for entry in taxonomy["entries"]:
        rows.append("| `{}` | {} | {} | {} |".format(entry["id"], _cell(entry["title"]), entry["origin"], ", ".join(f"`{c}`" for c in entry["codes"]) or "—"))
    return "\n".join(rows)


def render_all(version: str = "v1") -> dict[str, str]:
    return {
        "policy-index": render_policy_index(loader.load_policy(version)),
        "reason-codes": render_reason_codes(loader.load_reason_codes(version)),
        "taxonomy": render_taxonomy(loader.load_taxonomy(version)),
    }


_BLOCK = re.compile(r"(?P<begin><!-- BEGIN GENERATED:(?P<name>[a-z-]+) -->\n)(?P<body>.*?)\n?(?P<end><!-- END GENERATED:(?P=name) -->)", re.S)


def spec_blocks(spec_text: str) -> dict[str, str]:
    return {m.group("name"): m.group("body") for m in _BLOCK.finditer(spec_text)}


def rewrite_spec(spec_text: str, rendered: dict[str, str]) -> str:
    return _BLOCK.sub(lambda m: m.group("begin") + rendered[m.group("name")] + "\n" + m.group("end"), spec_text)


def main(argv: list[str]) -> int:
    rendered = render_all()
    spec_path = loader.contract_dir() / "SPEC.md"
    if "--write" in argv:
        spec_path.write_text(rewrite_spec(spec_path.read_text(encoding="utf-8"), rendered), encoding="utf-8")
        return 0
    if "--check" in argv:
        current = spec_blocks(spec_path.read_text(encoding="utf-8"))
        stale = [name for name, body in rendered.items() if current.get(name) != body]
        if stale:
            print("SPEC.md generated blocks are stale: " + ", ".join(stale) + "  (run: python -m identity_resolution.contract.render --write)")
            return 1
        return 0
    for name, body in rendered.items():
        print(f"## {name}\n\n{body}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
