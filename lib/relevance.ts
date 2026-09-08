/** Ordering the catalogue by what a visitor came to see.
 *
 *  The grid used to arrive in `updated_at` order — whichever row an editor
 *  touched last — which is why a 2019 model could sit above this year's launch.
 *  Relevance here is two things at once, because the owner's brief was a split
 *  between cars that sell and cars that are new:
 *
 *    sales      units registered over the last twelve months, scaled against
 *               the best-selling car of the same body type
 *    freshness  1.0 for a launch inside a year, fading to 0 across five
 *
 *  They are added, not blended, so a car can lead on either: a best-seller with
 *  no news, or a launch with no sales history yet. An old car with modest sales
 *  scores low on both and sinks, which is the behaviour that was asked for.
 *
 *  Both halves degrade to nothing rather than to noise. If the registrations
 *  table is empty every sales score is 0 and the order is newest-first; if a
 *  model has no launch year its freshness is 0 and it rides on sales alone.
 */

export const FRESH_FULL_MONTHS = 12;
export const FRESH_ZERO_MONTHS = 60;

export function freshness(model: any, now = new Date()): number {
  const year = Number(model?.launch_year);
  if (!Number.isFinite(year) || year < 1950) return 0;
  const month = Number(model?.launch_month);
  const launched = new Date(year, Number.isFinite(month) && month >= 1 && month <= 12 ? month - 1 : 0, 1);
  const months = (now.getFullYear() - launched.getFullYear()) * 12 + (now.getMonth() - launched.getMonth());
  if (months <= FRESH_FULL_MONTHS) return 1;            // includes a future launch
  if (months >= FRESH_ZERO_MONTHS) return 0;
  return (FRESH_ZERO_MONTHS - months) / (FRESH_ZERO_MONTHS - FRESH_FULL_MONTHS);
}

/** Best-seller of each body type, so the scale is per body rather than global
 *  and a pickup is not measured against a coupe. */
export function bodyPeaks(models: any[], sales: Map<string, number>): Map<string, number> {
  const peaks = new Map<string, number>();
  for (const m of models) {
    const body = m?.body_type || "";
    const units = sales.get(m?.id) || 0;
    if (units > (peaks.get(body) || 0)) peaks.set(body, units);
  }
  return peaks;
}

export function relevance(model: any, sales: Map<string, number>, peaks: Map<string, number>, now?: Date): number {
  const peak = peaks.get(model?.body_type || "") || 0;
  const units = sales.get(model?.id) || 0;
  const salesScore = peak > 0 ? units / peak : 0;
  return salesScore + freshness(model, now);
}

/** Order a catalogue list. Ties fall back to the name so the grid is stable. */
export function byRelevance(models: any[], sales: Map<string, number>, now?: Date): any[] {
  const peaks = bodyPeaks(models, sales);
  return [...models]
    .map((m, i) => ({ m, i, score: relevance(m, sales, peaks, now) }))
    .sort((a, b) => b.score - a.score || a.i - b.i)
    .map((x) => x.m);
}
