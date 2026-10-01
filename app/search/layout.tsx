import type { ReactNode } from "react";
import "../models/models.css";
import "./search.css";
import { CompareProvider, CompareTray } from "@/components/models/CompareTray";

export const dynamic = "force-dynamic";
export const revalidate = 0;

/** /search (P07) is a migrated design page; its model results are ModelCards with the compare tick, so it shares the
 *  catalogue's CompareProvider and tray. */
export default function SearchLayout({ children }: { children: ReactNode }) {
  return (
    <div className="designPage tdr-models tdr-search-page">
      <CompareProvider>
        {children}
        <CompareTray />
      </CompareProvider>
    </div>
  );
}
