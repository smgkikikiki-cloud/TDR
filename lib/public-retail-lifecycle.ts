export type PublicRetailLifecycle = "CURRENT" | "HISTORICAL" | "UNVERIFIED";

/**
 * Public surfaces must fail closed. Only the canonical uppercase lifecycle
 * values are trusted as CURRENT/HISTORICAL. Legacy `discontinued` is accepted
 * as historical so old editorial rows cannot leak back into the live catalogue.
 * Everything else — including legacy lowercase `current`, null and unknown
 * values — is UNVERIFIED.
 */
export function publicRetailLifecycle(value: unknown): PublicRetailLifecycle {
  const raw = String(value ?? "").trim();
  if (raw === "CURRENT") return "CURRENT";
  if (raw === "HISTORICAL" || raw.toLowerCase() === "discontinued") return "HISTORICAL";
  return "UNVERIFIED";
}

export function isVerifiedCurrent(value: unknown): boolean {
  return publicRetailLifecycle(value) === "CURRENT";
}

export function isHistorical(value: unknown): boolean {
  return publicRetailLifecycle(value) === "HISTORICAL";
}

/** The main catalogue may expose identity records that are still awaiting
 * lifecycle review, but it must not mix historical records back into the live
 * browsing surface. UNVERIFIED is rendered neutrally by the caller. */
export function isCatalogVisible(value: unknown): boolean {
  return publicRetailLifecycle(value) !== "HISTORICAL";
}

/** Compatibility status for older public components while the UI migrates to
 * explicit lifecycle semantics. HISTORICAL maps to the old discontinued token;
 * UNVERIFIED is deliberately not mapped to current. */
export function publicCompatibilityStatus(value: unknown): string {
  const lifecycle = publicRetailLifecycle(value);
  if (lifecycle === "HISTORICAL") return "discontinued";
  return lifecycle;
}
