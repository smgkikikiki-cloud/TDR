import type { ReactNode } from "react";
import type { BodyIconName } from "@/lib/body-families";

/** Side-view line icons for the six body families (design/reference/home_v7.html and models_v1.html). Decorative:
 *  the label next to it carries the meaning. Drawn with currentColor and SVG attributes only, so it needs no CSS. */
const SHAPES: Record<BodyIconName, ReactNode> = {
  sedan: <><path d="M4 17h40v-4l-6-2-6-5H16l-6 5-6 2z" /><circle cx="13" cy="18" r="3" /><circle cx="35" cy="18" r="3" /></>,
  suv: <><path d="M4 17h40v-6l-5-2-5-5H12l-4 5-4 1z" /><path d="M13 9h22" /><circle cx="13" cy="18" r="3.2" /><circle cx="35" cy="18" r="3.2" /></>,
  pickup: <><path d="M4 17h40v-6H24V5h-9l-5 6-6 1z" /><path d="M24 11h20" /><circle cx="12" cy="18" r="3.2" /><circle cx="36" cy="18" r="3.2" /></>,
  mpv: <><path d="M4 17h40v-5l-3-5c-1-2-3-3-6-3H13l-6 7-3 1z" /><circle cx="12" cy="18" r="3" /><circle cx="36" cy="18" r="3" /></>,
  hatchback: <><path d="M6 17h34v-6l-4-5H18l-6 5-6 1z" /><circle cx="14" cy="18" r="3" /><circle cx="33" cy="18" r="3" /></>,
  van: <><path d="M4 17h40V6c0-1-1-2-2-2H10L4 11z" /><path d="M4 11h12V4" /><circle cx="12" cy="18" r="3" /><circle cx="36" cy="18" r="3" /></>,
};

export function BodyIcon({ icon, width = 44, height = 22 }: { icon: BodyIconName; width?: number; height?: number }) {
  return (
    <svg viewBox="0 0 48 24" width={width} height={height} fill="none" stroke="currentColor" strokeWidth={1.8}
         strokeLinejoin="round" strokeLinecap="round" aria-hidden="true" focusable="false">
      {SHAPES[icon]}
    </svg>
  );
}
