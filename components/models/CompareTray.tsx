"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Button } from "@/components/design";
import { COMPARE_MAX, compareHref } from "@/lib/models/list";

/** Models the reader has ticked for comparison. At most COMPARE_MAX (the four slots of /compare).
 *  A tick is a MODEL, never a trim: the tray hands models to /compare as `?models=<model id>`, and /compare opens its
 *  own picker on each model's trim list, so no trim is ever chosen on the reader's behalf. Kept in sessionStorage so
 *  it survives filter changes and reloads within the tab, and nowhere else (nothing leaves the browser). */
const STORAGE_KEY = "tdr-compare-models";

export type TrayModel = { id: string; name: string; brand: string };

type Ctx = {
  items: TrayModel[];
  has: (id: string) => boolean;
  full: boolean;
  toggle: (model: TrayModel) => void;
  remove: (id: string) => void;
};
const TrayContext = createContext<Ctx | null>(null);

function readStored(): TrayModel[] {
  try {
    const parsed = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((m) => m && typeof m.id === "string" && typeof m.name === "string")
      .map((m) => ({ id: m.id, name: m.name, brand: typeof m.brand === "string" ? m.brand : "" }))
      .slice(0, COMPARE_MAX);
  } catch {
    return [];
  }
}

export function CompareProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<TrayModel[]>([]);

  useEffect(() => { setItems(readStored()); }, []);

  const write = useCallback((next: TrayModel[]) => {
    setItems(next);
    try { window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch { /* private mode: the tray still works for this page view */ }
  }, []);

  const value = useMemo<Ctx>(() => ({
    items,
    has: (id) => items.some((m) => m.id === id),
    full: items.length >= COMPARE_MAX,
    toggle: (model) => {
      if (items.some((m) => m.id === model.id)) write(items.filter((m) => m.id !== model.id));
      else if (items.length < COMPARE_MAX) write([...items, model]);
    },
    remove: (id) => write(items.filter((m) => m.id !== id)),
  }), [items, write]);

  return <TrayContext.Provider value={value}>{children}</TrayContext.Provider>;
}

function useTray(): Ctx {
  const ctx = useContext(TrayContext);
  if (!ctx) throw new Error("CompareToggle and CompareTray must sit inside CompareProvider");
  return ctx;
}

/** The "เทียบ" checkbox on a model card, or the outline "เพิ่มเข้าเทียบ" button on the model page. */
export function CompareToggle({ model, variant = "card" }: { model: TrayModel; variant?: "card" | "button" }) {
  const tray = useTray();
  const on = tray.has(model.id);
  const blocked = !on && tray.full;
  const title = blocked ? `เทียบได้สูงสุด ${COMPARE_MAX} รุ่น` : undefined;
  if (variant === "button") {
    return (
      <button type="button" className="tdr-btn tdr-btn--secondary" aria-pressed={on} disabled={blocked} title={title} onClick={() => tray.toggle(model)}>
        {on ? "✓ " : ""}เพิ่มเข้าเทียบ
      </button>
    );
  }
  return (
    <label className={blocked ? "tdr-models-cmpbox tdr-models-cmpbox--off" : "tdr-models-cmpbox"} title={title}>
      <input type="checkbox" checked={on} disabled={blocked} onChange={() => tray.toggle(model)} aria-label={`เทียบ ${[model.brand, model.name].filter(Boolean).join(" ")}`} />
      <span>เทียบ</span>
    </label>
  );
}

/** Sticky tray: what is ticked, a remove button each, and the hand-off to /compare. Renders nothing while empty. */
export function CompareTray() {
  const tray = useTray();
  if (!tray.items.length) return null;
  return (
    <div className="tdr-models-tray" role="region" aria-label="รถที่เลือกเทียบ">
      <div className="tdr-wrap tdr-models-tray__in">
        <div className="tdr-models-tray__list">
          <b>เลือกเทียบแล้ว <span className="tdr-models-mono">{tray.items.length}/{COMPARE_MAX}</span></b>
          <ul>
            {tray.items.map((m) => (
              <li key={m.id}>
                <span>{[m.brand, m.name].filter(Boolean).join(" ")}</span>
                <button type="button" aria-label={`เอา ${[m.brand, m.name].filter(Boolean).join(" ")} ออกจากการเทียบ`} onClick={() => tray.remove(m.id)}>×</button>
              </li>
            ))}
          </ul>
        </div>
        <Button variant="accent" href={compareHref(tray.items.map((m) => m.id))}>เทียบสเปก →</Button>
      </div>
    </div>
  );
}
