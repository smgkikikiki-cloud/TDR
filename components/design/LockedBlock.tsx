import type { CSSProperties } from "react";
import type { Tier } from "@/lib/design/format";
import { Button } from "@/components/design/Button";
import { TierBadge } from "@/components/design/TierBadge";

/** A locked data block: a static decorative placeholder, the tier badge, a message and an optional CTA.
 *  It deliberately takes NO children, so real values can never be rendered, blurred or leaked into the DOM
 *  (DESIGN §10.5). The message and CTA text come from the page. */
export function LockedBlock({ tier, message, cta, height = 120 }: {
  tier: Tier; message: string; cta?: { label: string; href: string }; height?: number;
}) {
  return (
    <div className="tdr-locked" role="group" aria-label={message} style={{ "--tdr-locked-h": `${height}px` } as CSSProperties}>
      <div className="tdr-locked__ghost" aria-hidden="true" />
      <div className="tdr-locked__msg">
        <TierBadge tier={tier} locked />
        <p>{message}</p>
        {cta ? <Button variant="secondary" href={cta.href}>{cta.label}</Button> : null}
      </div>
    </div>
  );
}
