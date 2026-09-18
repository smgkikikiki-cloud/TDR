/** Grouped digits that do not depend on where the code is running.
 *
 *  `toLocaleString` resolves against whatever ICU data the runtime has, and
 *  Node's and the browser's do not have to agree. When a client component is
 *  server-rendered and then hydrated, a difference of one character is enough
 *  for React to throw the whole subtree away and warn. Charts are full of
 *  numbers, so they format them here instead.
 */
export function groupedNumber(value: number, fractionDigits = 0): string {
  if (!Number.isFinite(value)) return "—";
  const fixed = Math.abs(value).toFixed(fractionDigits);
  const [whole, fraction] = fixed.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${value < 0 ? "-" : ""}${grouped}${fraction ? `.${fraction}` : ""}`;
}

/** Thousands as "54k" for a chart's own labels, where the axis has no room
 *  for six digits and the exact figure is a hover or a table away. */
export function compactNumber(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return Math.abs(value) >= 1000 ? `${Math.round(value / 1000)}k` : groupedNumber(value);
}
