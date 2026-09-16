// Minimal auditable server-side product-event recorder (see
// migration_v32_access_policy_and_quotas.sql::tdr_product_events). No
// analytics/telemetry system existed anywhere in this repo before this
// migration -- confirmed by a repo-wide search for
// analytics_event/track(/telemetry/posthog/segment/mixpanel/amplitude.
// Never pass payment-card data in `props`.
import { adminDb } from "@/lib/supabase";

export const PRODUCT_EVENT_NAMES = [
  "account_created",
  "profile_completed",
  "sales_modules_selected",
  "compare_run",
  "compare_quota_hit",
  "sales_run",
  "sales_quota_hit",
  "research_preview_viewed",
  "research_full_opened",
  "pdf_exported",
  "upgrade_viewed",
  "checkout_started",
  "subscription_started",
  "corporate_cta_clicked",
] as const;

export type ProductEventName = (typeof PRODUCT_EVENT_NAMES)[number];

export async function recordEvent(args: {
  eventName: ProductEventName;
  userId?: string | null;
  customerId?: string | null;
  props?: Record<string, unknown>;
}): Promise<void> {
  const db = adminDb();
  if (!db) return;
  const { error } = await db.from("tdr_product_events").insert({
    event_name: args.eventName,
    user_id: args.userId ?? null,
    customer_id: args.customerId ?? null,
    event_props: args.props ?? {},
  });
  if (error) console.error("telemetry insert failed", args.eventName, error.message);
}
