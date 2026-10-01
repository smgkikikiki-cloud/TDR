"use client";

import { BlockError } from "@/components/models/states";

/** A render failure inside the Vehicle Database group shows an inline error card, never a blank page. */
export default function ModelsError({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="tdr-wrap">
      <BlockError title="ฐานข้อมูลรถยนต์" />
      <p className="tdr-models-muted"><button type="button" className="tdr-btn tdr-btn--secondary" onClick={reset}>ลองอีกครั้ง</button></p>
    </div>
  );
}
