import type { ReactNode } from "react";
import "./models.css";
import { CompareProvider, CompareTray } from "@/components/models/CompareTray";

// Vehicle media is published independently of Vercel builds. Keep the catalogue
// and model-detail subtree server-rendered against the current canonical
// Supabase projection so newly approved hero media appears without a redeploy.
export const dynamic = "force-dynamic";
export const revalidate = 0;

/** The Vehicle Database group (P02 /models, P03 model, P04 trim) is a migrated design page: `.designPage` lifts the
 *  legacy frame (globals.css) and the compare tray is shared by all three, so a model ticked on the list stays
 *  ticked on a model page. */
export default function ModelsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="designPage tdr-models">
      <CompareProvider>
        {children}
        <CompareTray />
      </CompareProvider>
    </div>
  );
}
