"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { isNavItemActive, primaryNav } from "@/lib/navigation";

export function NavLinks() {
  const pathname = usePathname() || "/";
  return (
    <nav aria-label="เมนูหลัก">
      {primaryNav.map((item) => {
        const active = isNavItemActive(pathname, item.href);
        return (
          <Link key={item.href} href={item.href} className={active ? "navOn" : undefined} aria-current={active ? "page" : undefined}>
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
