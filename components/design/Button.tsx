import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "accent" | "contact";
const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: "tdr-btn--primary",
  secondary: "tdr-btn--secondary",
  ghost: "tdr-btn--ghost",
  accent: "tdr-btn--accent",
  contact: "tdr-btn--contact",
};

type Base = { variant?: ButtonVariant; children: ReactNode; className?: string };
type AsButton = Base & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className" | "children"> & { href?: undefined };
type AsLink = Base & { href: string; prefetch?: boolean; "aria-label"?: string };

/** One solid `accent` button per viewport (DESIGN §3); use `secondary`/`ghost` for the rest.
 *  With `href` it renders a Next link, otherwise a real <button>. */
export function Button(props: AsButton | AsLink) {
  const { variant = "primary", className, children } = props;
  const cls = ["tdr-btn", VARIANT_CLASS[variant], className].filter(Boolean).join(" ");
  if (props.href !== undefined) {
    const { href, prefetch, "aria-label": ariaLabel } = props;
    return <Link className={cls} href={href} prefetch={prefetch} aria-label={ariaLabel}>{children}</Link>;
  }
  const { variant: _variant, className: _className, children: _children, href: _href, type, ...rest } = props;
  return <button type={type ?? "button"} className={cls} {...rest}>{children}</button>;
}
