/** The Upcoming boundary for P06 (brand pages) and P07 (/search). PR 12 (`feat/upcoming`, table v53) owns the real data
 *  source, which is server-side editorial content (not Vehicle Master, not news, not canonical embryonic records).
 *
 *  Until it lands, `upcomingSource` returns no rows, so the strip and the search group are omitted. Nothing here, and
 *  nothing in the pages that call it, invents a car, a count or a placeholder. PR 12 replaces `upcomingSource` with its
 *  implementation; the pages and components do not change.
 *
 *  The card is presentation-ready: stage, confidence and window arrive already labelled by the source (the Thai copy
 *  belongs to P16), so this PR writes none of it. Plain TypeScript, no imports (run by scripts/check-brands-search.ts). */

export const UPCOMING_CARD_MAX = 3;

export type UpcomingCard = {
  slug: string;
  name: string;
  brandText: string;
  /** True when the name is not the official one (shows the "ชื่อชั่วคราว" badge, P16). */
  nameProvisional: boolean;
  stage: { step: number; label: string };
  confidence: { level: number; label: string };
  windowText: string | null;
  /** DELAYED state: an amber flag, never green/red. */
  delayed: boolean;
  /** Licensed image only (image_license <> NONE); otherwise null and the card has no picture. */
  image: { url: string; credit: string } | null;
  tags: string[];
};

export interface UpcomingSource {
  /** Up to `limit` published, active upcoming cars of one brand (matched by canonical brand id or brand text). */
  forBrand(brand: { slug: string; canonicalId?: string | null; name: string }, limit: number): Promise<UpcomingCard[]>;
  /** Up to `limit` published, active upcoming cars matching a search query. */
  matching(query: string, limit: number): Promise<UpcomingCard[]>;
}

/** The source while PR 12 is absent: no rows, no query, no fake data. */
export const noUpcomingSource: UpcomingSource = {
  async forBrand() { return []; },
  async matching() { return []; },
};

/** PR 12 swaps this for the real source. */
export const upcomingSource: UpcomingSource = noUpcomingSource;

/** At most `max` cards, in the order the source gave them. */
export function capUpcoming(rows: readonly UpcomingCard[] | null | undefined, max = UPCOMING_CARD_MAX): UpcomingCard[] {
  return (rows || []).slice(0, Math.max(0, max));
}

/** A source failure must not blank the page: it resolves to no rows. */
export async function safeUpcoming(load: () => Promise<UpcomingCard[]>, max = UPCOMING_CARD_MAX): Promise<UpcomingCard[]> {
  try { return capUpcoming(await load(), max); } catch { return []; }
}
