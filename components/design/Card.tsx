import Link from "next/link";
import type { ReactNode } from "react";

type Props = { children: ReactNode; tone?: "default" | "raised" | "dashed"; href?: string; as?: "div" | "article" | "section"; className?: string };

/** Bordered card, no shadow (DESIGN §5). `dashed` is the empty / "coming soon" look. With `href` the whole card links. */
export function Card({ children, tone = "default", href, as: As = "div", className }: Props) {
  const cls = ["tdr-card", tone === "raised" ? "tdr-card--raised" : tone === "dashed" ? "tdr-card--dashed" : "", className].filter(Boolean).join(" ");
  if (href !== undefined) return <Link className={cls} href={href}>{children}</Link>;
  return <As className={cls}>{children}</As>;
}

export function CardHead({ title, aside }: { title: ReactNode; aside?: ReactNode }) {
  return <div className="tdr-card__head"><h3 className="tdr-card__title">{title}</h3>{aside ? <div>{aside}</div> : null}</div>;
}
