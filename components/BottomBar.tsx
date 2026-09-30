"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { bottomNav } from "@/lib/navigation";

/** Phone bottom bar (≤767px): home · Intelligence · database · account. Hidden above that in shell.css. */
export function BottomBar() {
  const pathname = usePathname() || "/";
  return (
    <nav className="tdr-bottom" aria-label="เมนูล่าง">
      {bottomNav.map((item) => {
        const active = item.match(pathname);
        return (
          <Link key={item.label} href={item.href} className={active ? "on" : undefined} aria-current={active ? "page" : undefined}>
            <b aria-hidden="true">{item.icon}</b>{item.label}
          </Link>
        );
      })}
    </nav>
  );
}
