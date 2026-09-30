import Link from "next/link";
import type { ButtonHTMLAttributes, ComponentProps, HTMLAttributes, ReactNode } from "react";
import { formatNumber } from "@/lib/design/format";

type Common = {
  children: ReactNode;
  /** Small mono count after the label, e.g. the number of models. */
  count?: number | string;
  className?: string;
};

/** Tag: a plain label. */
type TagProps = Common & Omit<HTMLAttributes<HTMLSpanElement>, "className" | "children"> & { href?: undefined; pressed?: undefined };
/** Link: navigates; accepts the normal Next link props (aria-current, prefetch, scroll, ...). */
type LinkChipProps = Common & Omit<ComponentProps<typeof Link>, "className" | "children" | "href"> & { href: string; pressed?: undefined };
/** Toggle: a real <button aria-pressed>. Accepts onClick, disabled, aria-label and every other button attribute.
 *  The primitive holds no filter state; the caller owns `pressed` and what a click does. */
type ToggleProps = Common & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className" | "children" | "aria-pressed"> & { pressed: boolean; href?: undefined };

/** Filter chip / tag. Brand names are shown as text chips, never logos (DESIGN §9). */
export function Chip(props: TagProps | LinkChipProps | ToggleProps) {
  const { children, count, className } = props;
  const cls = ["tdr-chip", className].filter(Boolean).join(" ");
  const inner = <>{children}{count !== undefined ? <span className="tdr-chip__count">{formatNumber(count)}</span> : null}</>;

  if (props.href !== undefined) {
    const { children: _c, count: _n, className: _k, pressed: _p, ...rest } = props;
    return <Link {...rest} className={cls}>{inner}</Link>;
  }
  if (props.pressed !== undefined) {
    const { children: _c, count: _n, className: _k, pressed, type, ...rest } = props;
    return <button {...rest} type={type ?? "button"} className={cls} aria-pressed={pressed}>{inner}</button>;
  }
  const { children: _c, count: _n, className: _k, href: _h, pressed: _p, ...rest } = props;
  return <span {...rest} className={cls}>{inner}</span>;
}
