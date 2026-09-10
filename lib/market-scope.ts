export function normalizeRequestedMarketScopes(values?: string[]): string[] | undefined {
  const cleaned = [...new Set((values || [])
    .map((value) => String(value || "").trim().toUpperCase())
    .filter(Boolean))];
  if (cleaned.includes("ALL")) return undefined;
  const requested = cleaned.length ? cleaned : ["CORE"];
  return requested.includes("MIXED") ? requested : [...requested, "MIXED"];
}
