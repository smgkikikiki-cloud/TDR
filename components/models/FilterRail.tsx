"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";
import { Button } from "@/components/design";

const SHEET_QUERY = "(max-width: 1023px)";
const FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled])";

/** The filter rail. At >=1024px it is the sticky left column (children render as-is, server-side, links only, so it
 *  works without JavaScript). At <=1023px the rail is hidden and a "ตัวกรอง" button opens the same content as a bottom
 *  sheet: focus enters the sheet, Tab stays inside, Escape / the close button / the scrim / "ดูผลลัพธ์" close it and
 *  return focus to the button. The sheet stays open while filters change so several can be set in a row. */
export function FilterRail({ label, resultLabel, children }: { label: string; resultLabel: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const openerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);

  const close = useCallback((returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) openerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") close(true); };
    window.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = previous; window.removeEventListener("keydown", onKey); };
  }, [open, close]);

  useEffect(() => {
    const query = window.matchMedia(SHEET_QUERY);
    const onChange = () => { if (!query.matches) close(false); };
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [close]);

  function trap(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Tab") return;
    const items = Array.from(sheetRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1], active = document.activeElement;
    if (!sheetRef.current?.contains(active)) { event.preventDefault(); first.focus(); }
    else if (event.shiftKey && active === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && active === last) { event.preventDefault(); first.focus(); }
  }

  return (
    <>
      <button ref={openerRef} type="button" className="tdr-btn tdr-btn--secondary tdr-models-filters-btn" aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen(true)}>{label}</button>
      <aside className={open ? "tdr-models-rail tdr-models-rail--sheet" : "tdr-models-rail"} aria-label="ตัวกรอง">
        {open ? (
          <div className="tdr-models-sheet-scrim" onClick={() => close(true)} aria-hidden="true" />
        ) : null}
        <div
          ref={sheetRef}
          className="tdr-models-rail__panel"
          role={open ? "dialog" : undefined}
          aria-modal={open ? "true" : undefined}
          aria-label={open ? "ตัวกรอง" : undefined}
          onKeyDown={open ? trap : undefined}
        >
          <div className="tdr-models-sheet-head">
            <b>ตัวกรอง</b>
            <button ref={closeRef} type="button" className="tdr-models-sheet-close" aria-label="ปิดตัวกรอง" onClick={() => close(true)}>×</button>
          </div>
          {children}
          <div className="tdr-models-sheet-foot">
            <Button variant="secondary" onClick={() => close(true)}>{resultLabel}</Button>
          </div>
        </div>
      </aside>
    </>
  );
}
