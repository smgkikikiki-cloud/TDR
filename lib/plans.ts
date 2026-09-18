// Billing plan catalog. Replaces the single-plan assumption
// (REGISTRATION_PLAN/REGISTRATION_PRODUCT in lib/billing.ts, kept for
// backward compatibility) with a small, explicit table of self-service
// plans. Each plan's Stripe Price ID comes from an env var so no live
// Stripe price is ever hardcoded here -- setting the prices below only
// changes what this app *displays* and *expects*; the amount actually
// charged is whatever the Stripe Price object behind that env var was
// created with. Keeping the two in sync is an operational step outside
// this repo (create/update the Price in Stripe, then point the env var
// at it), not something code can enforce.
//
// Individual was scrapped as a sellable tier (docs/PRODUCT_ACCESS.md) --
// Pro is the only paid product now, offered at three commitment lengths
// instead of two separate tiers. Quarterly and annual bill the full
// period upfront (Stripe's native recurring interval + interval_count),
// not a discounted monthly charge.
import { TIER_PRODUCT, type Tier } from "@/lib/access-policy";

export type BillingInterval = "monthly" | "quarterly" | "annual";

export interface PlanDefinition {
  planCode: string;
  tier: Extract<Tier, "PRO">;
  product: string;
  interval: BillingInterval;
  /** THB per month, for display/comparison across intervals. */
  priceThbPerMonth: number;
  /** THB actually billed per Stripe invoice at this interval. */
  priceThbPerInterval: number;
  /** Env var holding this plan's Stripe Price ID. */
  stripePriceEnvVar: string;
}

export const PLAN_CATALOG: PlanDefinition[] = [
  {
    planCode: "pro_monthly",
    tier: "PRO",
    product: TIER_PRODUCT.PRO,
    interval: "monthly",
    priceThbPerMonth: 1290,
    priceThbPerInterval: 1290,
    stripePriceEnvVar: "STRIPE_PRICE_PRO_MONTHLY",
  },
  {
    planCode: "pro_quarterly",
    tier: "PRO",
    product: TIER_PRODUCT.PRO,
    interval: "quarterly",
    priceThbPerMonth: 990,
    priceThbPerInterval: 990 * 3,
    stripePriceEnvVar: "STRIPE_PRICE_PRO_QUARTERLY",
  },
  {
    planCode: "pro_annual",
    tier: "PRO",
    product: TIER_PRODUCT.PRO,
    interval: "annual",
    priceThbPerMonth: 790,
    priceThbPerInterval: 790 * 12,
    stripePriceEnvVar: "STRIPE_PRICE_PRO_ANNUAL",
  },
];

export function findPlan(planCode: string): PlanDefinition | null {
  return PLAN_CATALOG.find((plan) => plan.planCode === planCode) ?? null;
}

export function planPriceId(plan: PlanDefinition): string | null {
  return process.env[plan.stripePriceEnvVar] || null;
}

export function isPlanConfigured(plan: PlanDefinition): boolean {
  return Boolean(planPriceId(plan));
}
