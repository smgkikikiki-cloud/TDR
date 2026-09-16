import type { ReactNode } from "react";

// Vehicle media is published independently of Vercel builds. Keep the catalogue
// and model-detail subtree server-rendered against the current canonical
// Supabase projection so newly approved hero media appears without a redeploy.
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function ModelsLayout({ children }: { children: ReactNode }) {
  return children;
}
