import Link from "next/link";
import { BodyIcon } from "@/components/design";
import { formatNumber } from "@/lib/design/format";
import type { BodyIconName } from "@/lib/body-families";

/** One body-family tile of /models (and brand pages): icon, label and the count under the other active filters.
 *  It links to the family's `body` param; `on` marks the active family. "ทั้งหมด" has no icon (a grid glyph). */
export function BodyTypeTile({ href, label, count, icon, on }: {
  href: string; label: string; count: number; icon?: BodyIconName; on?: boolean;
}) {
  const cls = ["tdr-models-tile", on ? "tdr-models-tile--on" : "", count === 0 && !on ? "tdr-models-tile--empty" : ""].filter(Boolean).join(" ");
  return (
    <Link prefetch={false} href={href} className={cls} aria-current={on ? "true" : undefined}>
      {icon ? <BodyIcon icon={icon} width={52} height={26} /> : <span className="tdr-models-tile__all" aria-hidden="true">▦</span>}
      <b>{label}</b>
      <em>{formatNumber(count)}</em>
    </Link>
  );
}
