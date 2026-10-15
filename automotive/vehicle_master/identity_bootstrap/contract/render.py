"""Render the generated appendices of SPEC.md from the machine-readable contract files.

    python -m identity_bootstrap.contract.render            # print every appendix
    python -m identity_bootstrap.contract.render --check    # exit 1 if SPEC.md is out of date
    python -m identity_bootstrap.contract.render --write    # rewrite the generated blocks in SPEC.md

The appendices are DERIVED data (policy index, reason-code registry, edge-case taxonomy, lifecycle). They are generated so SPEC.md can
never drift from the YAML: a test fails when the committed blocks differ from what this module renders.
Run from automotive/vehicle_master.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from . import loader

SPEC = loader.contract_dir("v1") / "SPEC.md"
_BLOCK = re.compile(r"<!-- BEGIN GENERATED: (?P<name>[a-z_]+) -->\n(?P<body>.*?)<!-- END GENERATED: (?P=name) -->\n", re.S)


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _value(value) -> str:
    return "`" + _cell(json.dumps(value, ensure_ascii=False, separators=(", ", ": "))) + "`"


def policy_index() -> str:
    policy = loader.load_policy()
    prov = policy["provenance"]
    rows = ["| Key | Value | Provenance |", "|---|---|---|"]
    for section, body in policy.items():
        if section in ("version", "provenance"):
            continue
        if isinstance(body, dict):
            for key, value in body.items():
                rows.append(f"| `{section}.{key}` | {_value(value)} | {prov[section]} |")
        else:
            rows.append(f"| `{section}` | {_value(body)} | {prov.get(section, '-')} |")
    return "\n".join(rows) + "\n"


def reason_codes() -> str:
    reg = loader.load_reason_codes()["codes"]
    rows = ["| Code | Area | Kind | Route | Clearable | Rank | Meaning |", "|---|---|---|---|---|---|---|"]
    for code, e in sorted(reg.items(), key=lambda kv: (kv[1]["primary_rank"], kv[0])):
        rows.append(f"| `{code}` | {e['area']} | {e['kind']} | {e['route']} | {e['clearable']} | {e['primary_rank']} | {_cell(e['summary'])} |")
    return "\n".join(rows) + "\n"


def taxonomy() -> str:
    t = loader.load_taxonomy()
    rows = ["| Id | Expected outcome | Codes | Edge case |", "|---|---|---|---|"]
    for e in t["entries"]:
        rows.append(f"| `{e['id']}` | {e['outcome']} | {', '.join('`' + c + '`' for c in e['codes']) or '-'} | {_cell(e['title'])} |")
    return "\n".join(rows) + "\n"


def lifecycle() -> str:
    lc = loader.load_lifecycle()
    rows = ["| Transition | From | To | Actors | Proposal for | Guard |", "|---|---|---|---|---|---|"]
    for t in lc["transitions"]:
        frm = t["from"] if "from" in t else t["from_states"]
        rows.append(f"| `{t['id']}` | {_value(frm)} | {_value(t['to'])} | {', '.join(t['actors'])} | {', '.join(t.get('proposal_for', [])) or '-'} | `{t['guard']}` |")
    rows += ["", "| Surface | Sees identities in state |", "|---|---|"]
    for surface, states in lc["visibility"].items():
        rows.append(f"| `{surface}` | {', '.join(states)} |")
    return "\n".join(rows) + "\n"


RENDERERS = {"policy_index": policy_index, "reason_codes": reason_codes, "taxonomy": taxonomy, "lifecycle": lifecycle}


def render_block(name: str) -> str:
    return f"<!-- BEGIN GENERATED: {name} -->\n{RENDERERS[name]()}<!-- END GENERATED: {name} -->\n"


def rendered_spec(text: str) -> str:
    return _BLOCK.sub(lambda m: render_block(m.group("name")), text)


def main(argv: list[str]) -> int:
    text = SPEC.read_text(encoding="utf-8")
    if "--write" in argv:
        SPEC.write_text(rendered_spec(text), encoding="utf-8")
        return 0
    if "--check" in argv:
        if rendered_spec(text) != text:
            print("SPEC.md generated blocks are stale; run: python -m identity_bootstrap.contract.render --write")
            return 1
        return 0
    for name in RENDERERS:
        print(render_block(name))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
