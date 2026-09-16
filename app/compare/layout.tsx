import type { ReactNode } from "react";

// Comparison thumbnails share the canonical media projection with /models.
// Media ingestion can publish between app deploys, so do not freeze this route
// into a build-time snapshot.
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function CompareLayout({ children }: { children: ReactNode }) {
  return children;
}
