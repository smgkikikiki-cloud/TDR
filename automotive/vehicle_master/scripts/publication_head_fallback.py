#!/usr/bin/env python3
"""One-time fallback: propose publication feature images for unresolved Models."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import html
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vehreg.official_media.pipeline import fetch_bytes, USER_AGENT

SITES = ("https://www.headlightmag.com", "https://autolifethailand.tv")
BAD = re.compile(r"mirror|wheel|tyre|tire|headlight|taillight|interior|dashboard|seat|engine|logo|collage", re.I)
EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/avif": ".avif"}


def compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", html.unescape(re.sub("<[^>]+>", " ", value)).casefold())


def propose(row: dict, cache: Path) -> dict:
    if row["status"] == "READY":
        return row
    brand, model = row["brand"], row["model"]
    brand_term = compact(brand)
    model_term = compact(model)
    if len(model_term) < 2:
        return row
    for base in SITES:
        query = urlencode({"search": f"{brand} {model}", "per_page": 6, "_embed": 1})
        url = f"{base}/wp-json/wp/v2/posts?{query}"
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(req, timeout=18) as response:
                posts = json.load(response)
        except Exception:
            continue
        if not isinstance(posts, list):
            continue
        for post in posts:
            title = compact(post.get("title", {}).get("rendered", ""))
            if brand_term not in title or model_term not in title:
                continue
            media = (post.get("_embedded") or {}).get("wp:featuredmedia") or []
            if not media:
                continue
            image = media[0]
            image_url = image.get("source_url")
            alt = image.get("alt_text", "")
            width = (image.get("media_details") or {}).get("width")
            # A multi-model article may feature the *other* car. Require the
            # media itself to carry the full model name, not just the title.
            if (not image_url or model_term not in compact(image_url + " " + alt)
                    or (width and width < 900) or BAD.search(image_url + " " + alt)):
                continue
            try:
                body, mime = fetch_bytes(image_url)
                mime = mime.split(";", 1)[0].lower()
                if mime not in EXT or not (20_000 <= len(body) <= 20 * 1024 * 1024):
                    continue
                sha = hashlib.sha256(body).hexdigest()
                relative = Path("model-head") / row["model_id"] / (sha + EXT[mime])
                target = cache / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_bytes(body)
            except Exception:
                continue
            row.update({
                "selected_image": image_url, "source_url": post["link"],
                "source_domain": urlparse(post["link"]).hostname,
                "source_type": "automotive_publication",
                "sha256": sha, "storage_path": relative.as_posix(),
                "status": "NEEDS_REVIEW",
                "reason": "publication_feature_image;verify_model_generation_and_composition",
                "publication_title": html.unescape(re.sub("<[^>]+>", " ", post["title"]["rendered"])),
                "approved": False,
            })
            return row
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=ROOT / "data/media/cache")
    parser.add_argument("--model-ids", nargs="*")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.input.read_text().splitlines()]
    ids = set(args.model_ids or [])
    chosen = [row for row in rows if row["status"] != "READY" and (not ids or row["model_id"] in ids)]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(propose, row, args.cache): row["model_id"] for row in chosen}
        for future in as_completed(futures):
            row = future.result()
            print(row["model_id"], row["reason"], flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


if __name__ == "__main__":
    main()
