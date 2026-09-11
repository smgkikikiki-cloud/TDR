"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { primaryNav } from "@/lib/navigation";

/** Brand, search and forward-looking launch routes are views of the vehicle catalogue product. */
const SECTION_OF: Record<string, string> = {
  "/brands": "/models",
  "/search": "/models",
  "/upcoming": "/models",
};

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
