"use client";

import { useEffect, useRef } from "react";

/** The filter rail is a plain always-open disclosure on desktop (its summary is
 *  hidden by CSS) and a collapsed one on narrow screens, where an expanded rail
 *  would push the results off the first screen. Rendered open so it still works
 *  with JavaScript off. */
export function FilterDisclosure({ label, children }: { label: string; children: React.ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const mq = window.matchMedia("(max-width: 900px)");
    const apply = () => { el.open = !mq.matches; };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  return (
    <details className="sfRailShell" ref={ref} open>
      <summary>{label}</summary>
      {children}
    </details>
  );
}
