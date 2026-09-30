import { TIER_CLASS, TIER_LABEL, type Tier } from "@/lib/design/format";

/** Free / Member / Pro / Enterprise stay four distinct badges. Use "member" for a report gated to signed-in
 *  members (required_tier MEMBER); "free" only means the Free plan. `locked` adds the lock icon. */
export function TierBadge({ tier, locked, label }: { tier: Tier; locked?: boolean; label?: string }) {
  return (
    <span className={`tdr-tier ${TIER_CLASS[tier]}`}>
      {locked ? (
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
          <rect x="3" y="7" width="10" height="7" rx="1.5" />
          <path d="M5 7V5a3 3 0 0 1 6 0v2" />
        </svg>
      ) : null}
      {label ?? TIER_LABEL[tier]}
    </span>
  );
}
