"use client";

import { useState } from "react";
import { Chip } from "@/components/design";

/** Gallery-only client demo: the caller owns `pressed`; Chip just renders the toggle button. */
export function ChipDemo() {
  const [suv, setSuv] = useState(true);
  const [ev, setEv] = useState(false);
  return (
    <div className="tdr-gallery__row">
      <Chip pressed={suv} count={116} onClick={() => setSuv((v) => !v)} aria-label="กรอง SUV">SUV</Chip>
      <Chip pressed={ev} onClick={() => setEv((v) => !v)}>EV</Chip>
      <Chip pressed={false} disabled>Disabled</Chip>
      <span className="tdr-gallery__note" aria-live="polite" data-testid="chip-state">SUV={String(suv)} EV={String(ev)}</span>
    </div>
  );
}
