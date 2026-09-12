"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { primaryNav, resolveActiveNavHref } from "@/lib/navigation";

export function NavLinks() {
  const pathname = usePathname() || "/";
  const resolved = resolveActiveNavHref(pathname);
  return (
    <nav aria-label="เมนูหลัก">
      {primaryNav.map((item) => {
        const active = resolved === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link key={item.href} href={item.href} className={active ? "navOn" : undefined} aria-current={active ? "page" : undefined}>
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
