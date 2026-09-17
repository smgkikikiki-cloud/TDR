"use client";

import { AdminErrorPanel } from "@/components/admin/AdminErrorPanel";

/** Outer fallback: catches anything thrown above the (secure) layout, where
 * the admin shell itself is not available. */
export default function AdminError(props: { error: Error & { digest?: string }; reset: () => void }) {
  return <AdminErrorPanel {...props} />;
}
