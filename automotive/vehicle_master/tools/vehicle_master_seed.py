"""Seed the Vehicle DB v3 master tables (migration_v57) from the active release.

    python -m tools.vehicle_master_seed --release-id vehicle-2026-… --as-of 2026-10-01 --dry-run --out /tmp/vm-seed
    python -m tools.vehicle_master_seed --release-id vehicle-2026-… --as-of 2026-10-01 --apply

Phase 0 step 2 of docs/vehicle-db/VEHICLE_DB_V3.md. Two stages, both pinned to
one release and its as_of:

1. ``vehicle_master_seed_from_release`` copies serving identity/state from
   that release's projections inside the database (row-for-row, ids
   unchanged).
2. The supplemental sections -- state the release does not carry
   (ENGINE_INVENTORY.md §8) -- are built here from the canonical JSON tree at
   the release's ``canonical_revision`` and sent through
   ``vehicle_master_seed_supplemental``.

Before anything is sent, that tree is rebuilt with the pinned as_of using the
revision's own code, and the run stops unless the rebuild reproduces the
release's ``source_hash`` exactly. That is the proof the supplemental rows
come from the same master state that produced the serving snapshot; the
database then independently refuses any served price or fact whose content
differs from the release row with the same id.

Nothing here touches the existing tables, views or the release pipeline.
Requires Python 3.10+ (CI uses 3.12) and a full git clone that contains
the release's canonical_revision.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, Callable

from tdr_bridge.external_identity_registry import parse_registry
from tdr_bridge.publish import _clean_env_value, _rpc, _strip_wrapper_quotes
from tdr_bridge.release import _price_row
from vehreg.current_retail import load_current_retail_sets
from vehreg.entities import to_jsonable
from vehreg.model_operational_state import load_model_operational_states
from vehreg.product import ProductMaster
from vehreg.retail_lifecycle_review import load_trim_lifecycle_decisions

VM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = VM_ROOT.parents[1]
VM_REL = VM_ROOT.relative_to(REPO_ROOT).as_posix()

#: Same inputs as .github/workflows/vehicle-release.yml, relative to the
#: vehicle_master directory of the pinned tree.
INVENTORY = "integration_data/tdr_2026-09-09.json"
OVERRIDES = "integration_data/crosswalk_overrides.json"
IDENTITY_REGISTRY = "integration_data/external_identity_registry.json"

#: Send order. Variants before anything that reports on them; campaigns
#: before the check looks for price → campaign references.
SECTIONS = (
    "variants", "catalog_trims", "prices", "campaigns", "facts", "eco_evidence",
    "current_retail_sets", "trim_lifecycle_decisions", "model_operational_states",
    "legacy_identities",
)
CHUNK_SIZE = 500


class SeedError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Pinned tree
# ---------------------------------------------------------------------------

def extract_tree(revision: str, dest: Path, *, repo_root: Path = REPO_ROOT) -> Path:
    """``automotive/vehicle_master`` exactly as committed at ``revision``."""
    archive = dest / "tree.tar"
    with archive.open("wb") as out:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "archive", "--format=tar", revision, "--", VM_REL],
            stdout=out, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise SeedError(f"git archive {revision} failed: {result.stderr.decode(errors='replace')}"
                        " (a full clone containing the release's canonical_revision is required)")
    with tarfile.open(archive) as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dest, filter="data")
        else:  # pragma: no cover - Python without PEP 706
            tar.extractall(dest)
    archive.unlink()
    return dest / VM_REL


def rebuild_release(tree: Path, *, revision: str, as_of: str, out: Path) -> dict:
    """Rebuild the release with the pinned tree's own code, as CI did."""
    result = subprocess.run(
        [sys.executable, "-m", "tdr_bridge.release_enriched",
         "--inventory", INVENTORY, "--overrides", OVERRIDES,
         "--revision", revision, "--as-of", as_of, "--out", str(out)],
        cwd=tree, capture_output=True, text=True)
    if result.returncode != 0:
        raise SeedError(f"rebuilding the release at {revision} failed:\n{result.stderr[-4000:]}")
    return json.loads(out.read_text(encoding="utf-8"))


def verify_rebuild(rebuilt: dict, manifest: dict) -> None:
    for key in ("release_id", "source_hash", "canonical_revision", "as_of", "counts"):
        if rebuilt.get(key) != manifest.get(key):
            raise SeedError(
                f"rebuilt release does not reproduce the pinned release: {key} "
                f"{rebuilt.get(key)!r} != {manifest.get(key)!r}")


# ---------------------------------------------------------------------------
# Supplemental sections (pure: tree in, rows out)
# ---------------------------------------------------------------------------

def build_supplemental(data_dir: Path, year: int, *, registry_path: Path | None) -> dict[str, list[dict]]:
    master = ProductMaster.load(data_dir, year)
    problems = master.validate()
    if problems:
        raise SeedError("canonical product validation failed: " + "; ".join(problems[:10]))
    catalog = master.catalog

    variants = []
    for variant in sorted(catalog.variants.values(), key=lambda v: v.id):
        variants.append({"canonical_id": variant.id, "payload": to_jsonable(asdict(variant))})

    catalog_trims = [
        {"canonical_id": trim.id, "payload": to_jsonable(asdict(trim))}
        for trim in sorted(catalog.trims.values(), key=lambda t: t.id)
    ]

    prices: dict[str, dict] = {}
    for record in master.prices.records:
        row = _price_row(record)
        if row["record_id"] in prices and prices[row["record_id"]] != row:
            raise SeedError(f"record_id collision {row['record_id']}")
        prices[row["record_id"]] = row

    campaigns = [
        {"campaign_id": campaign.id, "payload": to_jsonable(asdict(campaign))}
        for campaign in sorted(master.prices.campaigns.values(), key=lambda c: c.id)
    ]

    facts = [
        {"fact_id": fact.fact_id, "payload": {"trim_id": fact.trim_id, **to_jsonable(asdict(fact))}}
        for fact in sorted(master.comparable_specs.facts, key=lambda f: f.fact_id)
    ]

    eco = [
        {"trim_id": trim_id, "payload": to_jsonable(spec)}
        for trim_id, spec in sorted(master.eco.records.items())
    ]

    sidecars = {
        "current_retail_sets": [
            {"model_id": row["model_id"], "payload": row}
            for row in load_current_retail_sets(data_dir=data_dir, year=year)],
        "trim_lifecycle_decisions": [
            {"trim_id": row["trim_id"], "payload": row}
            for row in load_trim_lifecycle_decisions(data_dir=data_dir, year=year)],
        "model_operational_states": [
            {"model_id": row["model_id"], "payload": row}
            for row in load_model_operational_states(data_dir=data_dir, year=year)],
    }

    legacy = []
    if registry_path is not None and registry_path.is_file():
        text = registry_path.read_text(encoding="utf-8")
        parse_registry(text, source=str(registry_path))  # validates; raises on a bad file
        legacy = [{"payload": binding} for binding in json.loads(text).get("bindings", [])]

    return {
        "variants": variants,
        "catalog_trims": catalog_trims,
        "prices": [{"record_id": rid, "payload": row} for rid, row in sorted(prices.items())],
        "campaigns": campaigns,
        "facts": facts,
        "eco_evidence": eco,
        **sidecars,
        "legacy_identities": legacy,
    }


def expected_counts(sections: dict[str, list[dict]]) -> dict[str, int]:
    return {name: len(sections[name]) for name in SECTIONS}


def cross_check_release(sections: dict[str, list[dict]], release: dict) -> None:
    """Served rows must be exactly the non-retracted prices / a subset of facts."""
    served_prices = {row["record_id"] for row in release["price_ledger"]}
    live = {row["record_id"] for row in sections["prices"]
            if not row["payload"].get("retracted_at")}
    if live != served_prices:
        raise SeedError(f"non-retracted prices differ from the release: "
                        f"{len(live - served_prices)} extra, {len(served_prices - live)} missing")
    fact_ids = {row["fact_id"] for row in sections["facts"]}
    missing = {row["fact_id"] for row in release["spec_facts"]} - fact_ids
    if missing:
        raise SeedError(f"{len(missing)} served facts are not in the fact store, e.g. {sorted(missing)[:3]}")
    trims = {row["canonical_id"] for row in release["market_trims"]}
    stray = {row["canonical_id"] for row in sections["catalog_trims"]} - trims
    if stray:
        raise SeedError(f"{len(stray)} catalog trims are not in the release, e.g. {sorted(stray)[:3]}")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def _env() -> tuple[str, str]:
    url = _clean_env_value(
        os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL"),
        "SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL").rstrip("/")
    key = _clean_env_value(
        os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SECRET_KEY/SERVICE_ROLE_KEY are required")
    return url, _strip_wrapper_quotes(key)


def fetch_active_manifest(*, url: str, key: str) -> dict:
    from urllib.request import Request, urlopen
    from tdr_bridge.publish import _headers

    def get(path: str) -> list:
        with urlopen(Request(f"{url}/rest/v1/{path}", headers=_headers(key)), timeout=30) as resp:
            return json.loads(resp.read().decode())

    state = get("canonical_vehicle_state?scope=eq.vehicle_catalog&select=active_release_id")
    if not state:
        raise SeedError("no active vehicle_catalog release")
    rows = get("canonical_vehicle_releases?select=release_id,canonical_revision,source_hash,as_of,counts"
               f"&release_id=eq.{state[0]['active_release_id']}")
    return rows[0]


def chunks(rows: list, size: int = CHUNK_SIZE):
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def apply(sections: dict[str, list[dict]], *, release_id: str, as_of: str,
          rpc: Callable[[str, dict], Any], log=print) -> dict:
    log(json.dumps({"stage": "release",
                    "result": rpc("vehicle_master_seed_from_release",
                                  {"p_release_id": release_id, "p_as_of": as_of})}))
    for name in SECTIONS:
        for chunk in chunks(sections[name]):
            rpc("vehicle_master_seed_supplemental",
                {"p_release_id": release_id, "p_as_of": as_of, "p_section": name, "p_rows": chunk})
        log(json.dumps({"stage": "supplemental", "section": name, "rows": len(sections[name])}))
    result = rpc("vehicle_master_finish_supplemental",
                 {"p_release_id": release_id, "p_as_of": as_of,
                  "p_expected": expected_counts(sections)})
    log(json.dumps({"stage": "finish", "result": result}))
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--release-id", required=True,
                        help="pinned release; must be the active one")
    parser.add_argument("--as-of", required=True, type=date.fromisoformat,
                        help="pinned as_of; must equal the release's as_of")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true",
                      help="build and verify everything, write sections to --out, send nothing")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--out", type=Path, help="directory for the built sections (dry run)")
    parser.add_argument("--manifest", type=Path,
                        help="release manifest JSON instead of reading it from Supabase "
                             "(dry run only; release_id, canonical_revision, source_hash, as_of, counts)")
    parser.add_argument("--workdir", type=Path, help="where to extract the pinned tree (default: temp)")
    args = parser.parse_args(argv)
    as_of = args.as_of.isoformat()

    if args.manifest:
        if args.apply:
            parser.error("--manifest is only for --dry-run; --apply reads the active release")
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        url = key = None
    else:
        url, key = _env()
        manifest = fetch_active_manifest(url=url, key=key)
    if manifest["release_id"] != args.release_id:
        raise SeedError(f"active release is {manifest['release_id']}, not the pinned {args.release_id}")
    if str(manifest["as_of"]) != as_of:
        raise SeedError(f"release as_of is {manifest['as_of']}, not the pinned {as_of}")

    with tempfile.TemporaryDirectory(prefix="vm-seed-", dir=args.workdir) as tmp:
        tmp_path = Path(tmp)
        tree = extract_tree(manifest["canonical_revision"], tmp_path)
        rebuilt = rebuild_release(tree, revision=manifest["canonical_revision"], as_of=as_of,
                                  out=tmp_path / "release.json")
        verify_rebuild(rebuilt, manifest)
        year = int(rebuilt["year"])
        sections = build_supplemental(tree / "vehreg" / "data", year,
                                      registry_path=tree / IDENTITY_REGISTRY)
        cross_check_release(sections, rebuilt)

    summary = {"release_id": args.release_id, "as_of": as_of,
               "canonical_revision": manifest["canonical_revision"],
               "source_hash": manifest["source_hash"], "release_counts": manifest["counts"],
               "supplemental_expected": expected_counts(sections)}
    print(json.dumps(summary, ensure_ascii=False))

    if args.dry_run:
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            for name in SECTIONS:
                (args.out / f"{name}.json").write_text(
                    json.dumps(sections[name], ensure_ascii=False), encoding="utf-8")
            (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return 0

    apply(sections, release_id=args.release_id, as_of=as_of,
          rpc=lambda name, params: _rpc(name, params, url=url, service_key=key))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SeedError as exc:
        print(f"vehicle_master_seed: {exc}", file=sys.stderr)
        raise SystemExit(1)
