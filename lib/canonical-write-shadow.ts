import { createHash } from "node:crypto";

import { adminDb } from "@/lib/supabase";

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

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${stable(record[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function commandKey(sourceModelId: string, payload: LegacyCanonicalModelBundle): string {
  const digest = createHash("sha256").update(stable(payload)).digest("hex");
  return `tdr-model-save:${sourceModelId}:${digest}`;
}

/**
 * Phase-C shadow bridge.
 *
 * The legacy TDR model editor still performs its old Supabase writes until the
 * canonical pipeline has passed an end-to-end cutover.  Every save also lands
 * here as an idempotent command.  A command is executable only when an explicit
 * verified UUID -> canonical-ID crosswalk exists; names/slugs are never treated
 * as authority.
 */
export async function enqueueCanonicalModelShadow(args: {
  sourceModelId: string;
  payload: LegacyCanonicalModelBundle;
  actor?: string;
  reason?: string;
}): Promise<CanonicalShadowResult> {
  const db = adminDb();
  if (!db) return { enqueued: false, status: "disabled", canonicalId: null };

  const { data: mapping, error: mapError } = await db
    .from("canonical_object_map")
    .select("canonical_id,status")
    .eq("source_table", "models")
    .eq("source_id", args.sourceModelId)
    .eq("canonical_entity_type", "model")
    .maybeSingle();

  // A missing table means migration_v12 has not been applied yet.  Shadow mode
  // must not break the existing editor while deployment catches up.
  if (mapError) {
    if (mapError.code === "42P01" || mapError.code === "PGRST205") {
      return { enqueued: false, status: "disabled", canonicalId: null };
    }
    throw mapError;
  }

  const verified = mapping?.status === "verified" && Boolean(mapping?.canonical_id);
  const status: "queued" | "needs_crosswalk" = verified ? "queued" : "needs_crosswalk";
  const row = {
    command_key: commandKey(args.sourceModelId, args.payload),
    source_table: "models",
    source_id: args.sourceModelId,
    canonical_entity_type: "model",
    canonical_id: verified ? mapping!.canonical_id : null,
    operation: "UPSERT_MODEL_BUNDLE",
    payload: args.payload,
    actor: args.actor || "tdr-admin",
    reason: args.reason || "legacy TDR model editor shadow write",
    status,
  };

  const { error } = await db.from("canonical_write_commands").insert(row);
  if (error) {
    // Exact retries of the same form payload are deliberately idempotent.
    if (error.code === "23505") {
      return { enqueued: false, duplicate: true, status, canonicalId: row.canonical_id };
    }
    // Same deployment-safety rule as the mapping read above.
    if (error.code === "42P01" || error.code === "PGRST205") {
      return { enqueued: false, status: "disabled", canonicalId: row.canonical_id };
    }
    throw error;
  }

  return { enqueued: true, status, canonicalId: row.canonical_id };
}
