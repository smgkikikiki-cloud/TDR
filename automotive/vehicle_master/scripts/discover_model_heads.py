#!/usr/bin/env python3
"""One-time Model head discovery. Read-only against production; writes a review manifest locally."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
# Reuse verified OEM hints without invoking the old Generation publisher.
import ingest_official_media_followup  # noqa: F401,E402
from vehreg.official_media.adapters import get_source, get_page_hints, MODEL_PAGE_HINTS, SOURCES
from vehreg.official_media.models import OfficialSource
from vehreg.official_media.models import ImageSlot, ReviewStatus, VehicleIdentity
from vehreg.official_media.pipeline import collect_candidates, fetch_bytes
from vehreg.catalog import Catalog, DATA_DIR

REJECT = re.compile(
    r"mirror|wheel|tyre|tire|headlight|tail.?light|lamp|badge|logo|icon|"
    r"charge.?port|interior|dashboard|cockpit|seat|infotainment|engine|"
    r"grille|accessor|brochure|collage|detail|close.?up|2[-_ ]cars|mobile",
    re.I,
)
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/avif": ".avif"}
# Visual inspection of the first 14-model pilot: these exact binaries were a
# wheel/mirror close-up, interior collage, tiny-car portrait, tiny-car scenery,
# and two clipped vehicles; the full contact sheet also caught promotional\n# collages, tiny cars and a close-up. Hashes avoid guessing from anonymous OEM CDN paths.
PILOT_REJECTED_SHA256 = {
    "1e0027ab167b2926191c29799a0dfb47707f62268ffdf8b5399377dc9600a120",
    "c501af89009f17ceb2509dcb2d16be343667dfa553d832f57e8ef1012cf2f674",
    "7f890a97d9e84b058fc3c43b73965345e3416c7fe40a89526b8404a0215f3f63",
    "a877ddba5fd5d9e3a1edbb5d177b13d34d7bbb58a52130ea69d9e11293f3e33c",
    "166241e267704d81e6967fec436ee01d798bf5d60f25ee1c4bae1a8f66c6d489",
    "b4f8eb6602503f86d0c642965f24a09102d06f20e5a49dba63d8ae7fd4e4255a",
    "c7f68b391afb65a0b70e1d6911f8445126594b4c89e25853ac13c3ddc4666ef9",
    "b1bef4505e9bea83fba6abd971043f8fe9d2ef155be71028e3fe951f739f17b5",
    "c558c07628b16903392cf20b6e7195c1f0465a22f2eb2eab1b20f0f6f0498460",
    "2d3985b30511d97fb979959c86e5c82cec6290241180329b69754a7f248d0166",
    "8d9a38ed7960efbcb4f2b2d02362099659cb5c3d9f72e6f20141a9ee5cee9420",
    "27cfc6a5c8bbbd09ff4725d37068145fd29ccde7941c800d04c8106fbe07abc3",
    "49346f46eb8da0bd386d4de522ed8c5a5db70abd0f973b5ce5504639f6386dca",
    "66025652a781596679302dd3862fa6232e543016afba6a97668e292f17061025",
    "683b622fea48613de6b0e9d1c7cbeba3ae0a8086a41c8572b76b7c84d1eb53e8",
}
PILOT_IDS = (
    "toyota.camry.xv80", "toyota.hilux_champ.champ", "honda.civic.fe",
    "byd.seal.seal", "mg.mg4.mg4e", "gwm.haval_h6.h6hev",
    "bmw.bmw_3.g20", "toyota.corolla_cross.xg10", "byd.atto3.atto3",
    "honda.crv.rs", "mg.mg_s5_ev.gen1", "tesla.model3.m3h",
    "xpeng.xpeng_g6.g6", "zeekr.zeekr_x.zx",
)


def activate_existing_oem_registry(models: list[dict]) -> None:
    """Reuse verified canonical model-page URLs from the Price Feed registry."""
    path = ROOT / "vehreg/data/2026/market/pricefeed/targets.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    official_ids = {p["source_id"] for p in registry.get("source_profiles", [])
                    if p.get("kind") == "OEM"}
    by_id = {m["canonical_id"]: m for m in models}
    pages = defaultdict(list)
    for target in registry.get("targets", []):
        model_id = target.get("model_hint")
        if (target.get("source_id") not in official_ids
                or target.get("role") != "CURRENT_MODEL_PAGE"
                or target.get("enabled") is False or model_id not in by_id):
            continue
        url = target.get("url", "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            continue
        row = by_id[model_id]
        pages[row["brand_id"]].append((row["generation_id"], url))
    for brand, entries in pages.items():
        for generation_id, url in entries:
            MODEL_PAGE_HINTS[generation_id] = tuple(dict.fromkeys(
                (url, *MODEL_PAGE_HINTS.get(generation_id, ()))))
        if brand not in SOURCES:
            hosts = tuple(sorted({urlparse(url).hostname for _, url in entries}))
            SOURCES[brand] = OfficialSource(
                brand_id=brand, seed_urls=(entries[0][1],),
                allowed_hosts=hosts,
            )


def active_rows(table: str, select: str) -> list[dict]:
    base = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not base or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SECRET_KEY (or service-role key) required")
    result = []
    for offset in range(0, 10000, 500):
        url = f"{base.rstrip('/')}/rest/v1/{table}?" + urlencode({
            "select": select, "limit": 500, "offset": offset,
        })
        req = Request(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
        with urlopen(req, timeout=30) as response:
            chunk = json.load(response)
        result.extend(chunk)
        if len(chunk) < 500:
            return result
    raise RuntimeError(f"{table}: pagination bound exceeded")


def candidate_ok(candidate) -> bool:
    if candidate.status is not ReviewStatus.APPROVED:
        return False
    if candidate.slot not in (ImageSlot.HERO, ImageSlot.FRONT_3Q, ImageSlot.SIDE):
        return False
    if REJECT.search(candidate.alt + " " + urlparse(candidate.image_url).path):
        return False
    if candidate.width and candidate.width < 900:
        return False
    if candidate.height and candidate.height < 450:
        return False
    return True


def discover(row: dict, catalog: Catalog, current: dict, cache: Path, max_pages: int) -> dict:
    model_id, generation_id = row["canonical_id"], row["generation_id"]
    prior = current.get(model_id) or current.get(generation_id)
    base = {
        "model_id": model_id, "generation_id": generation_id,
        "brand": row["brand_id"], "model": row["name_en"],
        "existing_image": prior["public_url"] if prior else None,
        "existing_source": prior.get("source_url") if prior else None,
        "selected_image": None, "source_url": None, "source_domain": None,
        "status": "NO_IMAGE", "reason": "", "sha256": None, "storage_path": None,
        "review_candidates": [],
    }
    generation = catalog.generations.get(generation_id)
    model = catalog.models.get(model_id)
    source = get_source(row["brand_id"])
    if not source or not generation or not model:
        base["status"] = "NEEDS_REVIEW" if prior else "NO_IMAGE"
        base["reason"] = ("no_verified_official_adapter" if not source
                          else "canonical_identity_not_in_catalog_snapshot")
        return base
    identity = VehicleIdentity(
        brand_id=row["brand_id"], model_id=model_id, generation_id=generation_id,
        model_name=model.name_en, generation_code=generation.code,
        model_year=catalog.year, aliases=tuple(dict.fromkeys((model.nameplate, *model.aliases))),
    )
    try:
        discovered = collect_candidates(identity, max_pages=max_pages)
        base["review_candidates"] = [
            {"image_url": c.image_url, "source_page": c.source_page,
             "score": c.score, "slot": c.slot.value, "alt": c.alt[:120]}
            for c in discovered[:3]
        ]
        candidates = [c for c in discovered if candidate_ok(c)]
    except Exception as exc:
        base["status"] = "NEEDS_REVIEW" if prior else "NO_IMAGE"
        base["reason"] = f"discovery_failed:{type(exc).__name__}"
        return base
    if not candidates:
        base["status"] = "NEEDS_REVIEW" if prior or base["review_candidates"] else "NO_IMAGE"
        base["source_url"] = (get_page_hints(generation_id) or source.seed_urls)[0]
        base["reason"] = "no_confident_exterior_candidate;existing_image_unverified" if prior else "no_confident_exterior_candidate"
        return base
    for candidate in candidates[:3]:
        try:
            body, mime = fetch_bytes(candidate.image_url)
            mime = mime.split(";", 1)[0].lower()
            if mime not in EXTENSIONS or not (20_000 <= len(body) <= 20 * 1024 * 1024):
                continue
            digest = hashlib.sha256(body).hexdigest()
            if digest in PILOT_REJECTED_SHA256:
                continue
            relative = Path("model-head") / model_id / (digest + EXTENSIONS[mime])
            target = cache / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(body)  # original bytes; never crop or transform
            base.update({
                "selected_image": candidate.image_url,
                "source_url": candidate.source_page,
                "source_domain": urlparse(candidate.source_page).hostname,
                "source_type": candidate.source_type.value,
                "sha256": digest, "storage_path": relative.as_posix(),
                "confidence": candidate.score, "width": candidate.width, "height": candidate.height,
                "status": "READY", "reason": "provisional_official_exterior;visual_review_required",
            })
            return base
        except Exception:
            continue
    base["status"] = "NEEDS_REVIEW"
    base["reason"] = "candidate_download_or_format_failed"
    return base


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--model-ids", nargs="*")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--max-pages", type=int, default=4)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output", type=Path, default=ROOT / "integration_data/model_head_manifest.jsonl")
    parser.add_argument("--cache", type=Path, default=ROOT / "data/media/cache")
    args = parser.parse_args()

    models = sorted(active_rows("current_vehicle_models",
        "canonical_id,brand_id,name_en,generation_id"), key=lambda r: r["canonical_id"])
    assets = active_rows("vehicle_media_assets",
        "vehicle_id,visual_key,public_url,image_type,source_url,status,confidence")
    bindings = active_rows("vehicle_media_bindings", "entity_id,entity_type,visual_key")
    by_visual = defaultdict(list)
    for asset in assets:
        if asset["status"] == "approved" and asset["image_type"] in ("hero", "front_3q"):
            by_visual[asset["visual_key"]].append(asset)
    bound = {b["entity_id"]: b for b in bindings}
    current = {}
    for row in models:
        key = row["canonical_id"] if row["canonical_id"] in bound else row["generation_id"]
        visual = bound[key]["visual_key"] if key in bound else key
        selected = sorted(by_visual[visual], key=lambda a: (a["image_type"] != "hero", -a["confidence"]))
        if selected:
            current[row["canonical_id"]] = selected[0]

    if args.pilot:
        wanted = set(PILOT_IDS)
        models = [m for m in models if m["generation_id"] in wanted]
    if args.model_ids:
        wanted = set(args.model_ids)
        models = [m for m in models if m["canonical_id"] in wanted]
    catalog = Catalog.load(args.data_dir, args.year)
    activate_existing_oem_registry(models)
    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        jobs = [pool.submit(discover, row, catalog, current, args.cache, args.max_pages) for row in models]
        for job in as_completed(jobs):
            result = job.result()
            results.append(result)
            print(f"{result['model_id']}: {result['status']} {result['reason']}", flush=True)
    results.sort(key=lambda r: r["model_id"])
    hashes = defaultdict(set)
    for row in results:
        if row["sha256"]:
            hashes[row["sha256"]].add(row["model_id"])
    for row in results:
        if row["sha256"] and len(hashes[row["sha256"]]) > 1:
            row["status"], row["reason"] = "NEEDS_REVIEW", "same_binary_for_multiple_models"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in results))
    review = args.output.with_suffix(".review.csv")
    with review.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["model_id", "brand", "model", "existing_image",
            "selected_image", "source_url", "status", "reason"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(row for row in results if row["status"] != "READY")
    print(json.dumps({"total": len(results), **Counter(row["status"] for row in results),
        "existing_images": sum(bool(row["existing_image"]) for row in results),
        "manifest": str(args.output), "review": str(review)}))


if __name__ == "__main__":
    main()
