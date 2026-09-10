export function normalizeRequestedMarketScopes(values?: string[]): string[] | undefined {
  const cleaned = [...new Set((values || [])
    .map((value) => String(value || "").trim().toUpperCase())
    .filter(Boolean))];
  if (cleaned.includes("ALL")) return undefined;
  return cleaned.length ? cleaned : ["CORE"];
}
