"""Shadow run: pinned Ice package + TDR catalog snapshot -> snapshot -> engine -> decisions. Read-only; returns data, writes nothing."""
from __future__ import annotations

import time
from pathlib import Path

from identity_bootstrap import engine
from identity_bootstrap.contract import loader
from identity_bootstrap.providers import ice

from . import ir_export, package, stand_in, tdr_catalog

VM = Path(__file__).resolve().parents[2]
DEFAULT_MODELS = VM / "vehreg" / "data" / "2026" / "models"
DEFAULT_LEGACY = VM / "integration_data" / "tdr_2026-09-09.json"
DEFAULT_PACKAGE = VM.parents[1] / "data" / "packages" / "2569-09" / "v3_M7.0" / package.PINNED["file"]


def build(mode: str, pkg: dict, catalog: dict, policy: dict, export: ir_export.RelationExport, **stand_in_options) -> tuple[dict, stand_in.StandIn]:
    ir_export.verify_universe(export, pkg["dims"], catalog)            # fail closed: same Ice groups, same TDR models, and the brand/status/aliases the routing reads
    si = stand_in.StandIn(catalog, policy, export, **stand_in_options)
    dims = pkg["dims"]
    by_brand: dict[str, list[str]] = {}
    for r in dims:
        by_brand.setdefault(r["brand"], []).append(r["model_group_id"])
    brand = {raw: si.brand_from_export(raw, gids) for raw, gids in by_brand.items()}       # relation-first: the producer's pool + typed brand relation, never the local alias table
    subject_rel = si.subject_relations([r["model_group_id"] for r in dims])
    cache: dict[str, list[dict]] = {}

    def relations_for(row: dict) -> list[dict]:
        gid = row["model_group_id"]
        if gid not in cache:
            cache[gid] = si.target_relations(gid) + subject_rel[gid]
        return cache[gid]

    snapshot = ice.build_snapshot(
        source_label=package.PINNED["source_label"], policy_version=policy["version"], as_of_period_be=pkg["periods"][1], dims=dims,
        first_seen_be=pkg["first_seen"], id_changes=pkg["id_changes"], identities=catalog["identities"],
        brand_for=lambda raw: brand[raw], resolution_for=lambda row: si.activation(relations_for(row), mode), relations_for=relations_for)
    return snapshot, si


def run(mode: str, package_path: Path = DEFAULT_PACKAGE, models_dir: Path = DEFAULT_MODELS, legacy: Path = DEFAULT_LEGACY,
        pkg: dict | None = None, export: ir_export.RelationExport | None = None, with_slugs: bool = True, policy: dict | None = None, **stand_in_options) -> dict:
    policy, registry = policy or loader.load_policy(), loader.load_reason_codes()
    pkg = pkg or package.load(package_path)
    catalog = tdr_catalog.load(models_dir, legacy, with_slugs)
    export = export or ir_export.load()
    snapshot, si = build(mode, pkg, catalog, policy, export, **stand_in_options)
    started = time.perf_counter()
    decisions = engine.decide(snapshot, policy, registry)
    return {"mode": mode, "package": pkg, "catalog": catalog, "snapshot": snapshot, "decisions": decisions, "policy": policy, "registry": registry,
            "stand_in": si, "export": export, "seconds": round(time.perf_counter() - started, 2)}
