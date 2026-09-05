"use client";

import { usePathname } from "next/navigation";

/** The admin editor draws its own shell. Without this the public header and
 *  footer still render underneath it — invisible, but in the DOM, so the login
 *  page shipped two submit buttons and keyboard users could tab into the
 *  storefront nav from behind the editor. */
export function PublicChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  if (pathname === "/admin" || pathname.startsWith("/admin/")) return null;
  return <>{children}</>;
}
