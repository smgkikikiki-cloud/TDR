"""Build an auditable AutoLife/Headlight price worklist for every 2026 model.

This is deliberately a research artifact, not a Price Ledger writer.  A result
must be reviewed and bound to a MarketTrim before it can become canonical.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "vehreg" / "data" / "2026" / "models"
DEFAULT_OUT = (
    ROOT / "vehreg" / "data" / "2026" / "market" / "prices" / "research"
    / f"autolife_headlight_{date.today().isoformat()}.json"
)

SOURCES = {
    "autolifethailand": "https://autolifethailand.tv",
    "headlightmag": "https://www.headlightmag.com",
}

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
PRICE_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[,.]\d{3}){1,2}|\d{6,8})(?:\s*)(?:บาท|THB)",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[,.]\d{3}){1,2}|\d{6,8})(?!\d)")
BAD_TITLE = re.compile(
    r"คาดการณ์|คาดราคา|ลุ้นราคา|มือสอง|used|display|demo|ส่วนลด|ราคาพิเศษ",
    re.IGNORECASE,
)
PRICE_TITLE = re.compile(r"ราคาอย่างเป็นทางการ|official price|เปิดราคา", re.IGNORECASE)


def text(raw: str) -> str:
    clean = TAG_RE.sub(" ", html.unescape(raw or ""))
    return SPACE_RE.sub(" ", clean).strip()


def folded(raw: str) -> str:
    raw = unicodedata.normalize("NFKC", text(raw)).casefold()
    return re.sub(r"[^a-z0-9ก-๙]+", "", raw)


def get_json(url: str, timeout: int = 25) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "TDR-price-research/1.0 (+catalog audit)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def model_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(MODELS_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        brand = payload["brand"]
        for model in payload.get("models", []):
            rows.append({
                "model_id": f"{brand['id']}.{model['id']}",
                "brand": brand["name_en"],
                "model": model["name_en"],
                "name_th": model.get("name_th") or "",
                "market_scope": model.get("market_scope") or "CORE",
                "incomplete": bool(model.get("incomplete")),
            })
    return rows


def relevant(title: str, row: dict[str, Any]) -> bool:
    title_folded = folded(title)
    model_folded = folded(row["model"])
    if model_folded and model_folded in title_folded:
        return True
    # Punctuation differences such as Q8 e-tron / Q8 etron are common.
    tokens = re.findall(r"[a-z0-9]+", row["model"].casefold())
    strong = [token for token in tokens if len(token) >= 2]
    return bool(strong) and all(token in title_folded for token in strong)


def amounts(raw: str) -> list[int]:
    found: set[int] = set()
    for match in PRICE_RE.finditer(text(raw)):
        value = int(match.group(1).replace(",", "").replace(".", ""))
        if 250_000 <= value <= 50_000_000:
            found.add(value)
    return sorted(found)


def title_amounts(raw: str) -> list[int]:
    """Titles commonly put one บาท after a whole min–max range."""
    clean = text(raw)
    if not re.search(r"ราคา|บาท|price", clean, re.IGNORECASE):
        return []
    found: set[int] = set()
    for match in NUMBER_RE.finditer(clean):
        value = int(match.group(1).replace(",", "").replace(".", ""))
        if 250_000 <= value <= 50_000_000:
            found.add(value)
    return sorted(found)


def snippets(raw: str) -> list[str]:
    body = text(raw)
    out: list[str] = []
    for match in PRICE_RE.finditer(body):
        start = max(0, match.start() - 100)
        end = min(len(body), match.end() + 100)
        excerpt = body[start:end].strip()
        if excerpt not in out:
            out.append(excerpt)
        if len(out) == 8:
            break
    return out


def search_source(source: str, base: str, row: dict[str, Any]) -> dict[str, Any]:
    query = f"{row['brand']} {row['model']} ราคาอย่างเป็นทางการ"
    url = (
        f"{base}/wp-json/wp/v2/search?search="
        f"{urllib.parse.quote(query)}&per_page=10"
    )
    try:
        hits = get_json(url)
    except Exception as exc:  # network state is evidence too
        return {"source": source, "query": query, "error": str(exc), "articles": []}

    candidates = [hit for hit in hits if relevant(hit.get("title", ""), row)]
    candidates.sort(
        key=lambda hit: (
            bool(PRICE_TITLE.search(text(hit.get("title", "")))),
            not bool(BAD_TITLE.search(text(hit.get("title", "")))),
            int(hit.get("id") or 0),
        ),
        reverse=True,
    )
    articles: list[dict[str, Any]] = []
    for hit in candidates[:2]:
        hit_title = text(hit.get("title", ""))
        hit_amounts = title_amounts(hit_title)
        if hit_amounts:
            articles.append({
                "title": hit_title,
                "url": hit.get("url"),
                "published_at": None,
                "modified_at": None,
                "price_amounts_thb": hit_amounts,
                "price_excerpts": [hit_title],
                "official_price_title": bool(PRICE_TITLE.search(hit_title)),
                "excluded_title": bool(BAD_TITLE.search(hit_title)),
                "evidence_surface": "title",
            })
            continue
        try:
            post = get_json(f"{base}/wp-json/wp/v2/posts/{hit['id']}")
            title = text(post.get("title", {}).get("rendered", hit.get("title", "")))
            content = post.get("content", {}).get("rendered", "")
            article = {
                "title": title,
                "url": post.get("link") or hit.get("url"),
                "published_at": post.get("date"),
                "modified_at": post.get("modified"),
                "price_amounts_thb": sorted(set(title_amounts(title) + amounts(content))),
                "price_excerpts": snippets(content),
                "official_price_title": bool(PRICE_TITLE.search(title)),
                "excluded_title": bool(BAD_TITLE.search(title)),
                "evidence_surface": "article",
            }
            articles.append(article)
        except Exception as exc:
            articles.append({
                "title": text(hit.get("title", "")),
                "url": hit.get("url"),
                "error": str(exc),
                "price_amounts_thb": [],
            })
    return {"source": source, "query": query, "articles": articles}


def preferred_amounts(result: dict[str, Any]) -> list[int]:
    for article in result.get("articles", []):
        if article.get("official_price_title") and not article.get("excluded_title"):
            values = article.get("price_amounts_thb") or []
            if values:
                return values
    for article in result.get("articles", []):
        if not article.get("excluded_title"):
            values = article.get("price_amounts_thb") or []
            if values:
                return values
    return []


def research(row: dict[str, Any]) -> dict[str, Any]:
    evidence = {
        source: search_source(source, base, row)
        for source, base in SOURCES.items()
    }
    left = preferred_amounts(evidence["autolifethailand"])
    right = preferred_amounts(evidence["headlightmag"])
    if left and right:
        disposition = "AGREE" if left == right else "CONFLICT"
    elif left or right:
        disposition = "ONE_SOURCE"
    else:
        disposition = "NOT_FOUND"
    return {
        **row,
        "disposition": disposition,
        "preferred_amounts_thb": {
            "autolifethailand": left,
            "headlightmag": right,
        },
        "evidence": evidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    rows = model_rows()
    if args.limit:
        rows = rows[: args.limit]
    started = time.time()
    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(research, row): row for row in rows}
        for done, future in enumerate(concurrent.futures.as_completed(futures), 1):
            result = future.result()
            results.append(result)
            print(f"[{done}/{len(rows)}] {result['model_id']}: {result['disposition']}", flush=True)

    results.sort(key=lambda row: row["model_id"])
    summary: dict[str, int] = {}
    for row in results:
        summary[row["disposition"]] = summary.get(row["disposition"], 0) + 1
    payload = {
        "schema_version": 1,
        "researched_at": date.today().isoformat(),
        "source_policy": ["autolifethailand", "headlightmag", "third_source_only_on_conflict"],
        "model_count": len(results),
        "summary": summary,
        "elapsed_seconds": round(time.time() - started, 1),
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "summary": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
