import Link from "next/link";
import type { ReactNode } from "react";
import { formatNumber } from "@/lib/design/format";

type Props = {
  children: ReactNode;
  /** Small mono count after the label, e.g. the number of models. */
  count?: number | string;
  /** Renders a link. */
  href?: string;
  /** Renders a toggle button; the value is aria-pressed. Without href or pressed it is a plain tag. */
  pressed?: boolean;
  className?: string;
};

/** Filter chip / tag. Brand names are shown as text chips, never logos (DESIGN §9). */
export function Chip({ children, count, href, pressed, className }: Props) {
  const cls = ["tdr-chip", className].filter(Boolean).join(" ");
  const inner = <>{children}{count !== undefined ? <span className="tdr-chip__count">{formatNumber(count)}</span> : null}</>;
  if (href !== undefined) return <Link className={cls} href={href}>{inner}</Link>;
  if (pressed !== undefined) return <button type="button" className={cls} aria-pressed={pressed}>{inner}</button>;
  return <span className={cls}>{inner}</span>;
}
