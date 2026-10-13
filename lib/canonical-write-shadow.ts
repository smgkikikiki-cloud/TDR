/** Retired Phase-C shadow bridge. No runtime callers at Issue #236 audit.
 * Keep the historical API as a no-write compatibility guard; v60 retired its DB path. */
export type LegacyCanonicalModelBundle = {
  model: Record<string, unknown>;
  powertrains: Array<Record<string, unknown>>;
  trims: Array<Record<string, unknown>>;
};

export type CanonicalShadowResult = {
  enqueued: boolean;
  duplicate?: boolean;
  status: "queued" | "needs_crosswalk" | "disabled";
  canonicalId?: string | null;
};


export async function enqueueCanonicalModelShadow(_args: {
  sourceModelId: string; payload: LegacyCanonicalModelBundle; actor?: string; reason?: string;
}): Promise<CanonicalShadowResult> {
  return { enqueued: false, status: "disabled", canonicalId: null };
}
