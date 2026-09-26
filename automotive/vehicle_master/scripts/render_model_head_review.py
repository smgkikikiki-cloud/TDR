#!/usr/bin/env python3
"""Render a zero-dependency visual review page from a Model-head discovery manifest."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def render(rows: list[dict]) -> str:
    cards = []
    for row in rows:
        model_id = row.get("model_id", "")
        candidates = row.get("review_candidates") or []
        selected = row.get("selected_image")
        image_urls: list[tuple[str, str]] = []
        if selected:
            image_urls.append((selected, "selected"))
        for i, candidate in enumerate(candidates, 1):
            url = candidate.get("image_url")
            if url and all(url != existing for existing, _ in image_urls):
                image_urls.append((url, f"candidate {i}"))
        thumbs = []
        for idx, (url, label) in enumerate(image_urls):
            thumbs.append(f'''<button class="thumb" data-model="{esc(model_id)}" data-url="{esc(url)}" onclick="pick(this)">
              <img src="{esc(url)}" loading="lazy" referrerpolicy="no-referrer">
              <span>{esc(label)}</span>
            </button>''')
        if not thumbs:
            thumbs.append('<div class="none">No image candidate</div>')
        source = row.get("source_url") or ""
        source_link = f'<a href="{esc(source)}" target="_blank" rel="noreferrer">source</a>' if source else ""
        cards.append(f'''<article class="card" data-model="{esc(model_id)}">
          <header><strong>{esc(row.get('brand'))} {esc(row.get('model'))}</strong><code>{esc(model_id)}</code></header>
          <div class="meta"><span>{esc(row.get('status'))}</span><span>{esc(row.get('reason'))}</span>{source_link}</div>
          <div class="thumbs">{''.join(thumbs)}</div>
          <div class="actions">
            <button class="approve" onclick="approve('{esc(model_id)}')">USE SELECTED</button>
            <button class="reject" onclick="rejectModel('{esc(model_id)}')">SKIP</button>
            <span class="decision" id="decision-{esc(model_id)}">undecided</span>
          </div>
        </article>''')
    return f'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Model head review</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#111;color:#eee}} .top{{position:sticky;top:0;z-index:9;background:#181818;padding:12px;display:flex;gap:12px;align-items:center;border-bottom:1px solid #333}}
.top button{{padding:9px 14px;font-weight:700}} #summary{{margin-left:auto}} main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:12px;padding:12px}}
.card{{background:#1b1b1b;border:1px solid #333;border-radius:10px;padding:10px}} header{{display:flex;justify-content:space-between;gap:8px;align-items:center}} code{{font-size:11px;color:#aaa}} .meta{{font-size:12px;color:#aaa;display:flex;gap:8px;flex-wrap:wrap;margin:6px 0}} .meta a{{color:#8ab4f8}}
.thumbs{{display:flex;gap:8px;overflow:auto}} .thumb{{min-width:180px;max-width:220px;background:#222;border:2px solid transparent;border-radius:8px;padding:4px;color:#ddd;cursor:pointer}} .thumb img{{width:100%;height:120px;object-fit:contain;background:#fff;border-radius:5px}} .thumb.chosen{{border-color:#35c46a}} .thumb span{{display:block;font-size:11px;padding:3px}}
.none{{height:120px;display:grid;place-items:center;color:#777}} .actions{{display:flex;gap:8px;align-items:center;margin-top:8px}} .approve{{background:#146c2e;color:white;border:0;border-radius:6px;padding:8px}} .reject{{background:#8b1e1e;color:white;border:0;border-radius:6px;padding:8px}} .decision{{font-size:12px;color:#aaa}} .done{{opacity:.45}}
</style></head><body>
<div class="top"><strong>Model head review — {len(rows)} models</strong><button onclick="downloadDecisions()">Download decisions.json</button><span id="summary">0 decided</span></div>
<main>{''.join(cards)}</main>
<script>
const decisions={{}}; const picks={{}};
function pick(btn){{document.querySelectorAll(`[data-model="${{CSS.escape(btn.dataset.model)}}"].thumb`).forEach(x=>x.classList.remove('chosen'));btn.classList.add('chosen');picks[btn.dataset.model]=btn.dataset.url;}}
function setDecision(model, decision, url=null){{decisions[model]={{decision,url}};document.getElementById('decision-'+model).textContent=decision+(url?' ✓':'');document.querySelector(`article[data-model="${{CSS.escape(model)}}"]`).classList.add('done');document.getElementById('summary').textContent=Object.keys(decisions).length+' decided';}}
function approve(model){{let url=picks[model];if(!url){{const first=document.querySelector(`article[data-model="${{CSS.escape(model)}}"] .thumb`);url=first?.dataset.url||null;}} if(!url){{alert('No candidate to approve');return;}} setDecision(model,'approve',url);}}
function rejectModel(model){{setDecision(model,'skip',null);}}
function downloadDecisions(){{const blob=new Blob([JSON.stringify({{generated_at:new Date().toISOString(),decisions}},null,2)],{{type:'application/json'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='model_head_decisions.json';a.click();URL.revokeObjectURL(a.href);}}
</script></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = load_rows(args.manifest)
    out = args.output or args.manifest.with_suffix(".review.html")
    out.write_text(render(rows), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "review_html": str(out)}))


if __name__ == "__main__":
    main()
