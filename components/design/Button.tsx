import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";

/** There is deliberately no generic solid-navy variant: the one general primary CTA is the solid `accent`
 *  button (max one per viewport, DESIGN §3); every other button is `secondary` (outline) or `ghost`.
 *  `contact` is the single navy exception: the Enterprise "Contact →" button (owner decision). */
export type ButtonVariant = "secondary" | "ghost" | "accent" | "contact";
const VARIANT_CLASS: Record<ButtonVariant, string> = {
  secondary: "tdr-btn--secondary",
  ghost: "tdr-btn--ghost",
  accent: "tdr-btn--accent",
  contact: "tdr-btn--contact",
};

type Base = { variant?: ButtonVariant; children: ReactNode; className?: string };
type AsButton = Base & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className" | "children"> & { href?: undefined };
type AsLink = Base & { href: string; prefetch?: boolean; "aria-label"?: string };

/** Defaults to `secondary`. With `href` it renders a Next link, otherwise a real <button>. */
export function Button(props: AsButton | AsLink) {
  const { variant = "secondary", className, children } = props;
  const cls = ["tdr-btn", VARIANT_CLASS[variant], className].filter(Boolean).join(" ");
  if (props.href !== undefined) {
    const { href, prefetch, "aria-label": ariaLabel } = props;
    return <Link className={cls} href={href} prefetch={prefetch} aria-label={ariaLabel}>{children}</Link>;
  }
  const { variant: _variant, className: _className, children: _children, href: _href, type, ...rest } = props;
  return <button type={type ?? "button"} className={cls} {...rest}>{children}</button>;
}
