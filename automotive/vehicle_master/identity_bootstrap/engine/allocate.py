"""Deterministic canonical id allocation (SPEC §10). The id depends on (brand_id, canonical name) only."""
from __future__ import annotations

import importlib


def slug_function(policy: dict):
    module, _, attribute = policy["allocation"]["local_segment_function"].rpartition(".")
    return getattr(importlib.import_module(module), attribute)    # resolved at run time: the one slug rule, never reimplemented


def allocate(brand_id: str, name: str, identities: list[dict], policy: dict, slugger=None) -> dict:
    cfg = policy["allocation"]
    if cfg["collision_resolution"] != "REVIEW":
        raise ValueError("v1 has no auto-suffix")
    local = (slugger or slug_function(policy))(name)
    if not local or local in cfg["forbidden_local_segments"]:
        return {"ok": False, "reason": "NAME_UNSPECIFIED"}
    canonical_id = cfg["id_format"].format(brand_id=brand_id, local=local)
    slug = f"{brand_id}-{local}".replace("_", "-")
    taken = sorted({i["canonical_id"] for i in identities if i["canonical_id"] == canonical_id or i.get("slug") == slug})   # deleted and WITHDRAWN rows reserve ids
    return {"ok": True, "canonical_id": canonical_id, "slug": slug, "local_segment": local, "collision": bool(taken), "taken_by": taken}
