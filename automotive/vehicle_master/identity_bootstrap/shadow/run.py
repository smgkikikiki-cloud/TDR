"""Shadow run: pinned Ice package + TDR catalog snapshot -> snapshot -> engine -> decisions. Read-only; returns data, writes nothing."""
from __future__ import annotations

import time
from pathlib import Path

from identity_bootstrap import engine
from identity_bootstrap.contract import loader
from identity_bootstrap.providers import ice

from . import package, stand_in, tdr_catalog

VM = Path(__file__).resolve().parents[2]
DEFAULT_MODELS = VM / "vehreg" / "data" / "2026" / "models"
DEFAULT_LEGACY = VM / "integration_data" / "tdr_2026-09-09.json"
DEFAULT_PACKAGE = VM.parents[1] / "data" / "packages" / "2569-09" / "v3_M7.0" / package.PINNED["file"]


def build(mode: str, pkg: dict, catalog: dict, policy: dict, refined: bool = False) -> tuple[dict, stand_in.StandIn]:
    si = stand_in.StandIn(catalog, policy, refined)
    dims = pkg["dims"]
    brand = {r["brand"]: si.brand_for(r["brand"]) for r in dims}
    tokens = {r["model_group_id"]: si.lex.tokens(r["model_name"], (r["brand"], *brand[r["brand"]].get("spellings", []))) for r in dims}
    subject_rel = si.subject_relations(dims, tokens)
    cache: dict[str, list[dict]] = {}

    def relations_for(row: dict) -> list[dict]:
        gid = row["model_group_id"]
        if gid not in cache:
            b = brand[row["brand"]]
            spell = (row["brand"], *b.get("spellings", []))
            cache[gid] = si.target_relations(b, row["model_name"], spell) + subject_rel[gid]
        return cache[gid]

    snapshot = ice.build_snapshot(
        source_label=package.PINNED["source_label"], policy_version=policy["version"], as_of_period_be=pkg["periods"][1], dims=dims,
        first_seen_be=pkg["first_seen"], id_changes=pkg["id_changes"], identities=catalog["identities"],
        brand_for=lambda raw: brand[raw], resolution_for=lambda row: si.activation(relations_for(row), mode), relations_for=relations_for)
    return snapshot, si


def run(mode: str, package_path: Path = DEFAULT_PACKAGE, models_dir: Path = DEFAULT_MODELS, legacy: Path = DEFAULT_LEGACY,
        pkg: dict | None = None, refined: bool = False) -> dict:
    policy, registry = loader.load_policy(), loader.load_reason_codes()
    pkg = pkg or package.load(package_path)
    catalog = tdr_catalog.load(models_dir, legacy)
    snapshot, si = build(mode, pkg, catalog, policy, refined)
    started = time.perf_counter()
    decisions = engine.decide(snapshot, policy, registry)
    return {"mode": mode, "package": pkg, "catalog": catalog, "snapshot": snapshot, "decisions": decisions, "policy": policy, "registry": registry,
            "stand_in": si, "refined": refined, "seconds": round(time.perf_counter() - started, 2)}
