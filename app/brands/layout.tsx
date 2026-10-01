import type { ReactNode } from "react";
import "../models/models.css";
import "./brands.css";
import { CompareProvider, CompareTray } from "@/components/models/CompareTray";

// Brand pages read the same canonical projection as the catalogue (media included), so they stay server-rendered.
export const dynamic = "force-dynamic";
export const revalidate = 0;

/** The brand index (P05) and brand pages (P06) are migrated design pages. A brand page shows ModelCards with the compare
 *  tick, so it shares the catalogue's CompareProvider and sticky tray. */
export default function BrandsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="designPage tdr-models tdr-brands">
      <CompareProvider>
        {children}
        <CompareTray />
      </CompareProvider>
    </div>
  );
}
