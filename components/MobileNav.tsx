"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "@/components/ThemeToggle";
import { isNavItemActive, memberEntry, pricingEntry, primaryNav, signupEntry } from "@/lib/navigation";

/** Matches the width where the header nav row is shown again (tdr-nav in shell.css). */
const DESKTOP_QUERY = "(min-width: 1024px)";
const FOCUSABLE = "a[href], button:not([disabled])";

/** Burger drawer for <1024px. The nav row is hidden there, and so are the header links
 *  that no longer fit at each width, so the drawer carries all of them.
 *  Keyboard: focus moves into the drawer on open, Tab/Shift+Tab stay inside it while open,
 *  and Escape, the close button, the scrim and the burger all return focus to the burger. */
export function MobileNav() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname() || "/";
  const burgerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLDivElement>(null);

  /** Closes the drawer. Focus goes back to the burger unless the close came from navigation
   *  or a resize, where the reader is somewhere else and the burger may not even be visible. */
  const close = useCallback((returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) burgerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") close(true); };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, close]);

  useEffect(() => { close(false); }, [pathname, close]);

  useEffect(() => {
    const query = window.matchMedia(DESKTOP_QUERY);
    const onChange = (event: MediaQueryListEvent | MediaQueryList) => { if (event.matches) close(false); };
    onChange(query);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [close]);

  /** Keeps Tab inside the drawer: wraps at both ends and pulls stray focus back in. */
  function trapTab(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Tab") return;
    const items = Array.from(drawerRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (!drawerRef.current?.contains(active)) { event.preventDefault(); first.focus(); }
    else if (event.shiftKey && active === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && active === last) { event.preventDefault(); first.focus(); }
  }

  return (
    <>
      <button
        ref={burgerRef}
        type="button"
        className="tdr-icon-btn tdr-burger"
        aria-expanded={open}
        aria-controls="tdrDrawer"
        aria-haspopup="dialog"
        aria-label={open ? "ปิดเมนู" : "เปิดเมนู"}
        onClick={() => (open ? close(true) : setOpen(true))}
      >
        ☰
      </button>

      {open ? (
        <div className="tdr-drawer-overlay" onClick={() => close(true)}>
          <div
            id="tdrDrawer"
            ref={drawerRef}
            className="tdr-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="เมนู"
            onClick={(event) => event.stopPropagation()}
            onKeyDown={trapTab}
          >
            <button ref={closeRef} type="button" className="tdr-icon-btn tdr-drawer__close" aria-label="ปิดเมนู" onClick={() => close(true)}>×</button>
            <nav className="tdr-drawer__nav" aria-label="เมนูหลัก (มือถือและแท็บเล็ต)">
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
              <Link href={signupEntry.href} className="tdr-btn tdr-signup">{signupEntry.label}</Link>
            </nav>
            <ThemeToggle className="tdr-drawer__theme" />
          </div>
        </div>
      ) : null}
    </>
  );
}
