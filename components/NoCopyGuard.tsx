"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

/** Makes casual copying of the public site's text (prices, specs, article
 *  bodies) take an extra step -- view source, dev tools -- instead of one
 *  click: blocks the browser's own copy/cut and right-click context menu,
 *  and CSS (globals.css, body.no-copy) turns off text selection.
 *
 *  Never applied under /admin -- staff actively select and copy data while
 *  managing it, same reason PublicChrome hides the public header/footer
 *  there.
 *
 *  This is not an anti-scraping measure. A bot reads the page's HTML/API
 *  directly and never touches the browser's copy command; this only adds
 *  friction for a human using the browser normally, and any of them can
 *  still read the page source, use dev tools, or turn off JavaScript. */
export function NoCopyGuard() {
  const pathname = usePathname() || "/";
  const active = !(pathname === "/admin" || pathname.startsWith("/admin/"));

  useEffect(() => {
    document.body.classList.toggle("no-copy", active);
    if (!active) return;
    const block = (event: Event) => event.preventDefault();
    document.addEventListener("copy", block);
    document.addEventListener("cut", block);
    document.addEventListener("contextmenu", block);
    return () => {
      document.body.classList.remove("no-copy");
      document.removeEventListener("copy", block);
      document.removeEventListener("cut", block);
      document.removeEventListener("contextmenu", block);
    };
  }, [active]);

  return null;
}
