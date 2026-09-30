"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "@/components/ThemeToggle";
import { isNavItemActive, memberEntry, pricingEntry, primaryNav, signupEntry } from "@/lib/navigation";

/** Matches the width where the header nav row is shown again (tdr-nav in shell.css). */
const DESKTOP_QUERY = "(min-width: 1024px)";

/** Burger drawer for <1024px. The nav row is hidden there, and so are the header links
 *  that no longer fit at each width, so the drawer carries all of them. */
export function MobileNav() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname() || "/";

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => { setOpen(false); }, [pathname]);

  useEffect(() => {
    const query = window.matchMedia(DESKTOP_QUERY);
    const onChange = (event: MediaQueryListEvent | MediaQueryList) => { if (event.matches) setOpen(false); };
    onChange(query);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return (
    <>
      <button
        type="button"
        className="tdr-icon-btn tdr-burger"
        aria-expanded={open}
        aria-controls="tdrDrawer"
        aria-label={open ? "ปิดเมนู" : "เปิดเมนู"}
        onClick={() => setOpen((value) => !value)}
      >
        ☰
      </button>

      {open ? (
        <div className="tdr-drawer-overlay" onClick={() => setOpen(false)}>
          <nav id="tdrDrawer" className="tdr-drawer" aria-label="เมนูหลัก (มือถือและแท็บเล็ต)" onClick={(event) => event.stopPropagation()}>
            <button type="button" className="tdr-icon-btn tdr-drawer__close" aria-label="ปิดเมนู" onClick={() => setOpen(false)}>×</button>
            {primaryNav.map((item) => {
              const active = isNavItemActive(pathname, item.href);
              return (
                <Link key={item.href} href={item.href} className={active ? "on" : undefined} aria-current={active ? "page" : undefined}>
                  {item.label}
                </Link>
              );
            })}
            <hr />
            <Link href={pricingEntry.href}>{pricingEntry.label}</Link>
            <Link href={memberEntry.href}>{memberEntry.label}</Link>
            <Link href={signupEntry.href} className="tdr-btn tdr-btn--primary">{signupEntry.label}</Link>
            <ThemeToggle className="tdr-drawer__theme" />
          </nav>
        </div>
      ) : null}
    </>
  );
}
