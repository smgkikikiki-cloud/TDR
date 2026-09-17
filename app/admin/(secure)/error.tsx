"use client";

import { AdminErrorPanel } from "@/components/admin/AdminErrorPanel";

/** Sits inside the (secure) layout, so a failed page or server action keeps
 * the admin shell and its nav instead of dropping the editor onto a bare
 * page with no way back. */
export default function SecureAdminError(props: { error: Error & { digest?: string }; reset: () => void }) {
  return <AdminErrorPanel {...props} />;
}
