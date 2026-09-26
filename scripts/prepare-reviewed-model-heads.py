#!/usr/bin/env python3
"""Prepare a reviewed model-head decision batch into a hash-addressed apply manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

MAX_BYTES = 20 * 1024 * 1024
MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/avif": ".avif",
}


def sniff(body: bytes, header: str) -> tuple[str, str]:
    mime = header.split(";", 1)[0].strip().lower()
    if mime not in MIME_EXT:
        if body.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif body.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP":
            mime = "image/webp"
        elif len(body) >= 12 and body[4:8] == b"ftyp" and body[8:12] in {b"avif", b"avis"}:
            mime = "image/avif"
    if mime not in MIME_EXT:
        raise ValueError(f"unsupported image content type: {header!r}")
    return mime, MIME_EXT[mime]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decisions", required=True, type=Path)
    ap.add_argument("--cache", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    payload = json.loads(args.decisions.read_text(encoding="utf-8"))
    approved = payload.get("approved") or []
    if not approved:
        raise SystemExit("no approved rows")

    rows = []
    seen = set()
    for item in approved:
        model_id = item["model_id"]
        if model_id in seen:
            raise ValueError(f"duplicate model_id: {model_id}")
        seen.add(model_id)
        image_url = item["selected_image"]
        source_url = item["source_url"]
        source = urlparse(source_url)
        image = urlparse(image_url)
        if source.scheme != "https" or source.hostname != item["source_domain"]:
            raise ValueError(f"{model_id}: source provenance mismatch")
        if image.scheme != "https" or not image.hostname:
            raise ValueError(f"{model_id}: selected image must be https")

        req = Request(image_url, headers={
            "User-Agent": "Mozilla/5.0 TDR-model-head-review/1.0",
            "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8",
        })
        with urlopen(req, timeout=45) as response:
            body = response.read(MAX_BYTES + 1)
            header = response.headers.get("Content-Type", "")
        if not body or len(body) > MAX_BYTES:
            raise ValueError(f"{model_id}: invalid image size {len(body)}")
        mime, ext = sniff(body, header)
        digest = hashlib.sha256(body).hexdigest()
        rel = Path("model-head") / model_id / f"{digest}{ext}"
        target = args.cache / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)

        rows.append({
            "model_id": model_id,
            "generation_id": item["generation_id"],
            "status": "READY",
            "approved": True,
            "selected_image": image_url,
            "source_url": source_url,
            "source_domain": item["source_domain"],
            "source_type": item.get("source_type") or "official_site",
            "sha256": digest,
            "storage_path": rel.as_posix(),
            "confidence": item.get("confidence") or 90,
            "width": None,
            "height": None,
            "mime": mime,
        })
        print(f"{model_id}: prepared {len(body)} bytes {digest[:12]}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    print(json.dumps({"approved": len(rows), "output": str(args.output)}))


if __name__ == "__main__":
    main()
