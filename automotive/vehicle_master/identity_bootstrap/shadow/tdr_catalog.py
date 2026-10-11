"""The TDR side of the shadow run: the file-backed canonical catalog snapshot (vehreg/data/2026/models/*.json) as stand-in for `vehicle_models`.

CAVEAT (reported with every result): this is the repository's file snapshot that seeded Vehicle Master (migration v57), not a read of the live
database. Models an admin added to the DB afterwards are invisible here, so CREATE counts are an upper bound on what a live run would create.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def load(models_dir: Path, legacy_snapshot: Path | None = None) -> dict:
    slugs = {}
    if legacy_snapshot and legacy_snapshot.exists():
        for m in json.loads(legacy_snapshot.read_text(encoding="utf-8"))["models"]:
            hit = re.search(r"source=([a-z0-9_.]+)", m.get("notes") or "")
            if hit and m.get("slug"):
                slugs[hit.group(1)] = m["slug"]
    brands, identities, aliases = {}, [], {}
    for path in sorted(Path(models_dir).glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        b = data["brand"]
        brands[b["id"]] = b
        for m in data["models"]:
            cid = f"{b['id']}.{m['id']}"
            row = {"canonical_id": cid, "brand_id": b["id"], "name_en": m["name_en"], "identity_state": None, "deleted": False}
            if cid in slugs:
                row["slug"] = slugs[cid]
            identities.append(row)
            aliases[cid] = [a for a in m.get("aliases", []) if a.strip()]
    return {"brands": brands, "identities": identities, "aliases": aliases, "models_dir": str(models_dir)}
