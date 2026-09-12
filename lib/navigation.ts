/** Public product navigation. Market Intelligence is the paid flagship; the
 * catalogue, vehicle compare and analysis remain directly discoverable. */
export const primaryNav = [
  { href: "/market", label: "Market Intelligence" },
  { href: "/models", label: "แคทตาล็อกรถยนต์" },
  { href: "/compare", label: "เทียบรถ" },
  { href: "/news", label: "บทวิเคราะห์" },
];

export const loginCta = { href: "/member/login", label: "เข้าสู่ระบบ" };
export const pricingCta = { href: "/pricing", label: "ดูแพ็กเกจ" };

/** Brand, search and forward-looking launch routes are views of the vehicle
 * catalogue product, so they should light up "แคทตาล็อกรถยนต์" in any nav
 * that renders primaryNav -- desktop and mobile alike. */
const NAV_SECTION_OF: Record<string, string> = {
  "/brands": "/models",
  "/search": "/models",
  "/upcoming": "/models",
};

export function resolveActiveNavHref(pathname: string): string {
  const section = Object.entries(NAV_SECTION_OF)
    .find(([path]) => pathname === path || pathname.startsWith(`${path}/`))?.[1];
  return section || pathname;
}
