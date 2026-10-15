"""The TDR side of the shadow run: the canonical catalog files (vehreg/data/2026/models/*.json) standing in for `vehicle_models`.

Milestone 3 VERIFIED this against the production Vehicle Master with a READ-ONLY comparison (shadow/universe/vehicle_master_live_2026-10-11.json): all 323 models and
62 brands are identical on id, brand, name and aliases, the 5 HISTORICAL ids match, there are no soft-deleted rows, and the live table has no identity_state column
(so no DISCOVERED / pending / withdrawn identities exist). The only live-only facts are 2 slugs that do not follow the {brand}-{local} rule, recorded in the same file.
"""
from __future__ import annotations

import json
from pathlib import Path


UNIVERSE = Path(__file__).with_name("universe") / "vehicle_master_live_2026-10-11.json"


def load(models_dir: Path, legacy_snapshot: Path | None = None, with_slugs: bool = True) -> dict:
    """`with_slugs=False` reproduces the milestone-2 universe (no slug reservation) so the effect of the fuller universe can be measured."""
    verification = json.loads(UNIVERSE.read_text(encoding="utf-8"))
    exceptions = verification["slug_rule"]["exceptions"]
    historical = set(verification["comparison_with_file_snapshot"]["historical_ids_equal"])
    brands, identities, aliases = {}, [], {}
    for path in sorted(Path(models_dir).glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        b = data["brand"]
        brands[b["id"]] = b
        for m in data["models"]:
            cid = f"{b['id']}.{m['id']}"
            row = {"canonical_id": cid, "brand_id": b["id"], "name_en": m["name_en"], "identity_state": None, "deleted": False}
            if with_slugs:
                row["slug"] = exceptions.get(cid) or f"{b['id']}-{m['id']}".replace("_", "-")
            identities.append(row)
            aliases[cid] = [a for a in m.get("aliases", []) if a.strip()]
    return {"brands": brands, "identities": identities, "aliases": aliases, "models_dir": str(models_dir), "historical": sorted(historical),
            "verification": verification}
