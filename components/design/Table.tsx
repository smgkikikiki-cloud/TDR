import type { ReactNode } from "react";

/** Shared table treatment. Scrolls inside its own wrapper so a wide table never overflows the page.
 *  Right-align numeric cells with className="tdr-num" (mono, tabular). `caption` names the table for assistive tech. */
export function Table({ caption, children }: { caption: string; children: ReactNode }) {
  return (
    <div className="tdr-table-wrap" role="region" aria-label={caption} tabIndex={0}>
      <table className="tdr-table">
        <caption className="sr-only" style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>{caption}</caption>
        {children}
      </table>
    </div>
  );
}
