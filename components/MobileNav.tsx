"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { primaryNav, loginCta, pricingCta, resolveActiveNavHref } from "@/lib/navigation";

/** Matches the .mobileNavToggle breakpoint in saas-shell.css. The drawer only
 * exists below this width, so crossing it (resize, tablet rotation) must
 * close the drawer -- otherwise the overlay can outlive the hamburger that
 * opened it. */
const MOBILE_BREAKPOINT_QUERY = "(min-width: 701px)";

/** Explicit mobile menu for <=700px, replacing the old horizontal-scroll nav
 * row that gave no hint more items existed off-screen. Tablet keeps the
 * scrollable row (still usable with a pointer/wider viewport). */
export function MobileNav() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname() || "/";
  const resolved = resolveActiveNavHref(pathname);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // A route change (link click, back/forward) always closes the drawer.
  useEffect(() => { setOpen(false); }, [pathname]);

  // Crossing into desktop width (resize, tablet rotation) must close the
  // drawer -- it has no desktop trigger, so a stale open=true would leave
  // the overlay/panel visible with no hamburger left to close it.
  useEffect(() => {
    const query = window.matchMedia(MOBILE_BREAKPOINT_QUERY);
    const onChange = (event: MediaQueryListEvent | MediaQueryList) => {
      if (event.matches) setOpen(false);
    };
    onChange(query);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return (
    <>
      <button
        type="button"
        className="mobileNavToggle"
        aria-expanded={open}
        aria-controls="mobileNavPanel"
        aria-label={open ? "ปิดเมนู" : "เปิดเมนู"}
        onClick={() => setOpen((value) => !value)}
      >
        <span /><span /><span />
      </button>

      {open ? (
        <div className="mobileNavOverlay" onClick={() => setOpen(false)}>
          <nav
            id="mobileNavPanel"
            className="mobileNavPanel"
            aria-label="เมนูหลัก (มือถือ)"
            onClick={(event) => event.stopPropagation()}
          >
            <button type="button" className="mobileNavClose" aria-label="ปิดเมนู" onClick={() => setOpen(false)}>×</button>
            {primaryNav.map((item) => {
              const active = resolved === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link key={item.href} href={item.href} className={active ? "navOn" : undefined} aria-current={active ? "page" : undefined}>
                  {item.label}
                </Link>
              );
            })}
            <Link href={loginCta.href}>{loginCta.label}</Link>
            <Link href={pricingCta.href} className="mobileNavPricing">{pricingCta.label}</Link>
          </nav>
        </div>
      ) : null}
    </>
  );
}
