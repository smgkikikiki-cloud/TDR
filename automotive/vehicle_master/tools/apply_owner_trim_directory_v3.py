#!/usr/bin/env python3
"""Run the refined owner-directory mapper and assign stable explicit trim IDs.

The canonical default slug intentionally drops punctuation, so distinct showroom
names such as `D` and `D+` can otherwise collapse to the same MarketTrim id.
Owner-directory rows therefore receive an explicit semantic id that preserves
`+` as `plus` and includes exact powertrain identity.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import apply_owner_trim_directory_v2 as refined

base = refined.base


def id_slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = value.replace("+", " plus ").replace("&", " and ")
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    value = re.sub(r"_+", "_", value)
    return value or "trim"


def add_explicit_owner_ids() -> int:
    changed = 0
    for path in sorted(base.MODELS_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        file_changed = False
        for model in payload.get("models", []):
            for generation in model.get("generations", []):
                used: set[str] = {
                    id_slug(str(trim["id"]))
                    for trim in generation.get("trims", [])
                    if trim.get("id")
                }
                for trim in generation.get("trims", []):
                    refs = trim.get("source_refs", {})
                    if not refs.get("owner_directory") or trim.get("id"):
                        continue
                    candidate = id_slug(
                        f"{trim.get('name', 'trim')} {trim.get('powertrain', '')}"
                    )
                    if candidate in used:
                        # Stable source-backed suffix only when a semantic id is
                        # already occupied within this generation.
                        source_ref = refs["owner_directory"][0]
                        source_index = source_ref.rsplit(":", 1)[-1]
                        candidate = id_slug(f"{candidate} source {source_index}")
                    suffix = 2
                    unique = candidate
                    while unique in used:
                        unique = f"{candidate}_{suffix}"
                        suffix += 1
                    trim["id"] = unique
                    used.add(unique)
                    changed += 1
                    file_changed = True
        if file_changed:
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    return changed


def main() -> int:
    result = base.main()
    if result:
        return result
    count = add_explicit_owner_ids()
    report_path: Path = base.REPORT_PATH
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["explicit_owner_trim_ids_added"] = count
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"explicit_owner_trim_ids_added={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
