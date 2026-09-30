"use client";

import { useId, useState } from "react";

/** The source badge of a spec row. The observed date shows on hover (title) and on tap / Enter (the button toggles a
 *  small note), so touch and keyboard readers get it too. With no date the badge is plain text. */
export function SourceBadge({ label, known, observedAt }: { label: string; known: boolean; observedAt: string | null }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const cls = known ? "tdr-models-src" : "tdr-models-src tdr-models-src--unknown";
  if (!observedAt) return <span className={cls}>{label}</span>;
  return (
    <span className="tdr-models-src-wrap">
      <button type="button" className={cls} title={`ข้อมูล ณ วันที่ ${observedAt}`} aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>{label}</button>
      {open ? <span id={id} className="tdr-models-src-note" role="note">ข้อมูล ณ วันที่ {observedAt}</span> : null}
    </span>
  );
}
