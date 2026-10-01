"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { usePathname, useRouter } from "next/navigation";

type Suggest = { models: { slug: string; name: string; brand: string }[]; brands: { slug: string; name: string }[] };
type Status = "idle" | "loading" | "ok" | "error";
const FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled])";

/** Header search (P07): an icon button that opens an overlay with the query box, live suggestions (up to 6 models, up to 4
 *  brands as text chips) and "ดูผลทั้งหมด →". Enter submits to /search?q=. Keyboard: focus enters the input, Tab stays inside,
 *  Escape / the close button / the scrim close it and return focus to the icon. Brands are text, never logos. */
export function SearchOverlay() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [data, setData] = useState<Suggest>({ models: [], brands: [] });
  const router = useRouter();
  const pathname = usePathname();
  const openerRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const close = useCallback((returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) openerRef.current?.focus();
  }, []);

  useEffect(() => { close(false); }, [pathname, close]);

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    inputRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(true); };
    window.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = previous; window.removeEventListener("keydown", onKey); };
  }, [open, close]);

  // Live suggestions: debounced, and a newer keystroke cancels the older request.
  useEffect(() => {
    const term = q.replace(/\s+/g, " ").trim();
    if (!open || !term) { setStatus("idle"); setData({ models: [], brands: [] }); return; }
    setStatus("loading");
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      fetch(`/api/search/suggest?q=${encodeURIComponent(term)}`, { signal: controller.signal })
        .then(async (r) => { if (!r.ok) throw new Error("bad"); return r.json(); })
        .then((body) => { setData({ models: body.models || [], brands: body.brands || [] }); setStatus("ok"); })
        .catch((err) => { if (err?.name !== "AbortError") setStatus("error"); });
    }, 200);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [q, open]);

  function trap(e: ReactKeyboardEvent<HTMLDivElement>) {
    if (e.key !== "Tab") return;
    const items = Array.from(panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1], active = document.activeElement;
    if (!panelRef.current?.contains(active)) { e.preventDefault(); first.focus(); }
    else if (e.shiftKey && active === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus(); }
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const term = q.replace(/\s+/g, " ").trim();
    router.push(term ? `/search?q=${encodeURIComponent(term)}` : "/search");
  }

  const term = q.replace(/\s+/g, " ").trim();
  const empty = status === "ok" && !data.models.length && !data.brands.length;

  return (
    <>
      <button ref={openerRef} type="button" className="tdr-icon-btn tdr-search-btn" aria-label="ค้นหา" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}>
        <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" /><path d="M13 13l4.5 4.5" /></svg>
      </button>
      {open ? createPortal(
        <div className="tdr-search-overlay" onClick={() => close(true)}>
          <div ref={panelRef} className="tdr-search" role="dialog" aria-modal="true" aria-label="ค้นหารุ่นรถหรือแบรนด์" onClick={(e) => e.stopPropagation()} onKeyDown={trap}>
            <form className="tdr-search__form" role="search" onSubmit={submit}>
              <input ref={inputRef} type="search" className="tdr-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="ค้นหารุ่นรถหรือแบรนด์" aria-label="ค้นหารุ่นรถหรือแบรนด์" autoComplete="off" />
              <button type="submit" className="tdr-btn tdr-btn--secondary">ค้นหา</button>
              <button type="button" className="tdr-icon-btn tdr-search__close" aria-label="ปิดการค้นหา" onClick={() => close(true)}>×</button>
            </form>
            <div className="tdr-search__body" aria-live="polite">
              {status === "loading" ? <div className="tdr-search__sk" aria-hidden="true"><span /><span /><span /></div> : null}
              {status === "error" ? <p className="tdr-search__note" role="alert">ค้นหาไม่สำเร็จ · <button type="button" className="tdr-search__retry" onClick={() => setQ((v) => v + " ")}>ลองอีกครั้ง</button></p> : null}
              {empty ? <p className="tdr-search__note">ไม่พบ “{term}” ในฐานข้อมูล</p> : null}
              {status === "ok" && data.models.length ? (
                <div className="tdr-search__group">
                  <h2>รุ่นรถ</h2>
                  <ul>{data.models.map((m) => <li key={m.slug}><Link href={`/models/${m.slug}`}><b>{m.name}</b><small>{m.brand}</small></Link></li>)}</ul>
                </div>
              ) : null}
              {status === "ok" && data.brands.length ? (
                <div className="tdr-search__group">
                  <h2>แบรนด์</h2>
                  <div className="tdr-chips">{data.brands.map((b) => <Link key={b.slug} href={`/brands/${b.slug}`} className="tdr-chip">{b.name}</Link>)}</div>
                </div>
              ) : null}
              {term ? <Link className="tdr-search__all" href={`/search?q=${encodeURIComponent(term)}`}>ดูผลทั้งหมด →</Link> : null}
            </div>
          </div>
        </div>,
        document.body,
      ) : null}
    </>
  );
}
