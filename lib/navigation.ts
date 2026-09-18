/** The primary navigation IS the product: the free vehicle database and its
 * comparison tool, then the two subscriber layers. Nothing else belongs here —
 * brands, plants and search are views of the database, not sections of their
 * own, and they are reached from inside it. */
export const primaryNav = [
  { href: "/models", label: "ฐานข้อมูลรถยนต์" },
  { href: "/compare", label: "เปรียบเทียบสเปก" },
  { href: "/market", label: "ข้อมูลตลาดรถยนต์" },
  { href: "/research", label: "บทวิเคราะห์เชิงลึก" },
];

/** Where the header's account entry points. */
export const memberEntry = { href: "/member/login", label: "เข้าสู่ระบบ" };

/** Brand and search routes are views of the canonical vehicle catalogue, so
 *  they light up the catalogue's nav entry rather than nothing at all. Shared
 *  by the desktop row and the mobile drawer so the two can never disagree
 *  about where the reader is. */
const NAV_SECTION_OF: Record<string, string> = { "/brands": "/models", "/search": "/models" };

export function resolveActiveNavHref(pathname: string): string {
  const section = Object.entries(NAV_SECTION_OF)
    .find(([path]) => pathname === path || pathname.startsWith(`${path}/`))?.[1];
  return section || pathname;
}

export function isNavItemActive(pathname: string, href: string): boolean {
  const resolved = resolveActiveNavHref(pathname);
  return resolved === href || pathname === href || pathname.startsWith(`${href}/`);
}
