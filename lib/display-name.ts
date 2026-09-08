/** Model and brand names are shown in Latin script only.
 *
 *  The database keeps `name_th` NOT NULL and `name_en` nullable, and every page
 *  read `name_th`, so the catalogue displayed Thai names for cars whose real
 *  names are Latin — "โตโยต้า ยารีส เอทีฟ" for a car badged Yaris Ativ. The
 *  brand and model name a buyer recognises is the badge on the car.
 *
 *  Falling back to `name_th` when `name_en` is missing would put the Thai name
 *  straight back on screen, so the fallback is the slug, which is Latin by
 *  construction because it is the URL. Only if that fails too does anything
 *  else get shown, and then only so a row is never nameless.
 */

const THAI = /[฀-๿]/;
const LATIN = /[A-Za-z]/;

/** "toyota-yaris-ativ" -> "Toyota Yaris Ativ", "mg4" -> "MG4", "bmw-x5" -> "BMW X5".
 *
 *  A slug is always lower case, so a word cannot be left alone on the grounds
 *  that it already carries capitals - the first attempt did that and rendered
 *  "mg4". Short words are marques or model codes and go up whole; longer ones
 *  are ordinary words and get a leading capital. It is an approximation, used
 *  only when `name_en` is missing, and the fix for a wrong one is to fill in
 *  `name_en` rather than to teach this more special cases. */
export function titleFromSlug(slug?: string | null): string {
  if (!slug) return "";
  return slug
    .split(/[-_]+/)
    .filter(Boolean)
    .map((w) => (w.replace(/[^a-z]/g, "").length <= 3
      ? w.toUpperCase()
      : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ");
}

/** The name to print for a model, brand, or anything else carrying the pair. */
export function displayName(row: any, fallback = ""): string {
  if (!row) return fallback;
  const en = typeof row.name_en === "string" ? row.name_en.trim() : "";
  if (en && LATIN.test(en) && !THAI.test(en)) return en;
  const fromSlug = titleFromSlug(row.slug);
  if (fromSlug && !THAI.test(fromSlug)) return fromSlug;
  // Nothing Latin to show. A name in the wrong script beats no name at all.
  return en || (typeof row.name_th === "string" ? row.name_th : "") || fallback;
}

/** Two-letter mark for a brand with no logo. */
export function initials(row: any): string {
  const name = displayName(row);
  return name.slice(0, 2).toUpperCase();
}

/** Sort comparator for anything shown by name. */
export function byDisplayName(a: any, b: any): number {
  return displayName(a).localeCompare(displayName(b), "en");
}
