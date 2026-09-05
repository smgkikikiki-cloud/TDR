"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { primaryNav } from "@/lib/navigation";

/** /plants and /brands are sub-views, so they light up their parent section. */
const SECTION_OF: Record<string, string> = { "/plants": "/production", "/brands": "/models", "/search": "/models" };

export function NavLinks() {
  const pathname = usePathname() || "/";
  const section = Object.entries(SECTION_OF).find(([p]) => pathname === p || pathname.startsWith(`${p}/`))?.[1];
  return (
    <nav aria-label="เมนูหลัก">
      {primaryNav.map((item) => {
        const active = section === item.href || pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link key={item.href} href={item.href} className={active ? "navOn" : undefined} aria-current={active ? "page" : undefined}>
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
