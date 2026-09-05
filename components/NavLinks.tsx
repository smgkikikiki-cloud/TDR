"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { primaryNav } from "@/lib/navigation";

export function NavLinks() {
  const pathname = usePathname() || "/";
  return (
    <nav aria-label="เมนูหลัก">
      {primaryNav.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        const classes = [item.href === "/reports" ? "reportNavLink" : null, active ? "navOn" : null]
          .filter(Boolean)
          .join(" ");
        return (
          <Link key={item.href} href={item.href} className={classes || undefined} aria-current={active ? "page" : undefined}>
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
