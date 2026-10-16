/** The primary navigation (design/DESIGN.md §7): the four sections, in this order,
 *  English labels. Hrefs point at the pages that exist today; the target pages move
 *  with their own PRs (Intelligence hub, Analysis) and only this file changes then. */
export const primaryNav = [
  { href: "/market", label: "Automotive Intelligence" },
  { href: "/models", label: "Vehicle Database" },
  { href: "/compare", label: "Compare Specs" },
  { href: "/research", label: "Analysis Report" },
];

/** Header actions. Sign-up and sign-in share the member page until the auth pages ship. */
export const pricingEntry = { href: "/pricing", label: "แพ็กเกจ" };
export const memberEntry = { href: "/member/login", label: "เข้าสู่ระบบ" };
export const signupEntry = { href: "/member/login", label: "สมัครสมาชิก" };

/** Phone bottom bar (design/DESIGN.md §6): home · Intelligence · database · account. */
export const bottomNav = [
  { href: "/", label: "หน้าแรก", icon: "⌂", match: (path: string) => path === "/" },
  { href: "/market", label: "Intelligence", icon: "◔", match: (path: string) => path === "/market" || path.startsWith("/market/") || path.startsWith("/member/market") },
  { href: "/models", label: "ฐานข้อมูล", icon: "▦", match: (path: string) => path === "/models" || path.startsWith("/models/") || path.startsWith("/brands") || path.startsWith("/search") },
  { href: "/member/login", label: "บัญชี", icon: "☺", match: (path: string) => path.startsWith("/member") && !path.startsWith("/member/market") },
];

/** Brand and search routes are views of the canonical vehicle catalogue, and the member
 *  market workspace is the Intelligence section, so they light up that section's nav entry
 *  rather than nothing at all. Shared by the desktop row and the drawer so the two can
 *  never disagree about where the reader is. */
const NAV_SECTION_OF: Record<string, string> = {
  "/brands": "/models",
  "/search": "/models",
  "/member/market": "/market",
};

export function resolveActiveNavHref(pathname: string): string {
  const section = Object.entries(NAV_SECTION_OF)
    .find(([path]) => pathname === path || pathname.startsWith(`${path}/`))?.[1];
  return section || pathname;
}

export function isNavItemActive(pathname: string, href: string): boolean {
  const resolved = resolveActiveNavHref(pathname);
  return resolved === href || pathname === href || pathname.startsWith(`${href}/`);
}
