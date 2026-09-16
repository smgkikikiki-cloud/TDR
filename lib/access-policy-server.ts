// Server-side wiring for the access-policy module: token resolution, tier
// lookup, and the atomic quota-consumption RPC call. Split from
// lib/access-policy.ts (which stays `@/`-import-free and unit-testable)
// because this file needs the Supabase admin client.
import { adminDb } from "@/lib/supabase";
import {
  getPolicy,
  periodKeyForMetric,
  resetsAtForMetric,
  resolveTierFromEntitlements,
  type EntitlementRow,
  type SalesModule,
  type Tier,
  type TierPolicy,
  type UsageMetric,
} from "@/lib/access-policy";

export class AccessPolicyError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export interface AccessContext {
  db: NonNullable<ReturnType<typeof adminDb>>;
  userId: string;
  tier: Tier;
  policy: TierPolicy;
}

export async function resolveAccessContext(accessToken: string): Promise<AccessContext> {
  const db = adminDb();
  if (!db) throw new AccessPolicyError(503, "access policy database is not configured");

  const { data: userData, error: userError } = await db.auth.getUser(accessToken);
  if (userError || !userData.user) {
    throw new AccessPolicyError(401, "invalid or expired member session");
  }

  const { data: entitlementRows, error: entitlementError } = await db
    .from("tdr_entitlements")
    .select("product,status,valid_until")
    .eq("user_id", userData.user.id);
  if (entitlementError) throw new AccessPolicyError(503, "could not resolve account tier");

  const tier = resolveTierFromEntitlements((entitlementRows ?? []) as EntitlementRow[]);
  return { db, userId: userData.user.id, tier, policy: getPolicy(tier) };
}

export interface QuotaResult {
  allowed: boolean;
  used: number;
  limit: number | null;
  remaining: number | null;
  resets_at: string;
}

// Consumes one unit of `metric` quota for `userId`, atomically, via the
// tdr_consume_usage() RPC (see migration_v32). `actionId`, when provided,
// lets several internal calls that make up one logical user action (e.g.
// the member dashboard's 7-call Sales Tools fan-out) share a single quota
// decision instead of each independently consuming quota.
export async function consumeUsage(
  db: AccessContext["db"],
  userId: string,
  metric: UsageMetric,
  limit: number | null,
  actionId?: string | null,
): Promise<QuotaResult> {
  const now = new Date();
  const periodKey = periodKeyForMetric(metric, now);
  const { data, error } = await db.rpc("tdr_consume_usage", {
    p_user_id: userId,
    p_metric: metric,
    p_period_key: periodKey,
    p_limit: limit,
    p_action_id: actionId ?? null,
  });
  if (error) throw new AccessPolicyError(503, `could not verify ${metric} quota`);
  const row = Array.isArray(data) ? data[0] : data;
  const used = Number(row?.used ?? 0);
  return {
    allowed: Boolean(row?.allowed),
    used,
    limit,
    remaining: limit === null ? null : Math.max(limit - used, 0),
    resets_at: resetsAtForMetric(metric, now),
  };
}

export async function requireUsage(
  ctx: AccessContext,
  metric: UsageMetric,
  limit: number | null,
  actionId?: string | null,
): Promise<QuotaResult> {
  const result = await consumeUsage(ctx.db, ctx.userId, metric, limit, actionId);
  if (!result.allowed) {
    throw new AccessPolicyError(429, `${metric} quota exceeded for this period`);
  }
  return result;
}

export async function getSalesModuleSelection(
  db: AccessContext["db"],
  userId: string,
  cycleKey: string,
): Promise<SalesModule[] | null> {
  const { data, error } = await db
    .from("tdr_sales_module_selection")
    .select("modules")
    .eq("user_id", userId)
    .eq("cycle_key", cycleKey)
    .maybeSingle();
  if (error) throw new AccessPolicyError(503, "could not load sales module selection");
  return (data?.modules as SalesModule[] | undefined) ?? null;
}

export async function setSalesModuleSelection(
  db: AccessContext["db"],
  userId: string,
  cycleKey: string,
  modules: SalesModule[],
): Promise<void> {
  const existing = await getSalesModuleSelection(db, userId, cycleKey);
  if (existing) {
    const same = existing.length === modules.length && existing.every((m) => modules.includes(m));
    if (!same) {
      throw new AccessPolicyError(409, "sales module selection is locked for this cycle");
    }
    return;
  }
  const { error } = await db.from("tdr_sales_module_selection").insert({
    user_id: userId,
    cycle_key: cycleKey,
    modules,
  });
  if (error) throw new AccessPolicyError(503, "could not save sales module selection");
}
