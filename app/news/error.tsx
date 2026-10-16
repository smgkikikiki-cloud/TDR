"use client";

import { Card } from "@/components/design";

/** A render failure shows an inline error card with a retry, never a blank page. */
export default function NewsError({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="tdr-wrap tdr-news">
      <Card tone="dashed">
        <div role="alert">
          <b className="tdr-card__title">ข่าว</b>
          <p>โหลดข้อมูลไม่สำเร็จ</p>
          <button type="button" className="tdr-btn tdr-btn--secondary" onClick={reset}>ลองอีกครั้ง</button>
        </div>
      </Card>
    </div>
  );
}
