// Billing plan catalog. Replaces the single-plan assumption
// (REGISTRATION_PLAN/REGISTRATION_PRODUCT in lib/billing.ts, kept for
// backward compatibility) with a small, explicit table of self-service
// plans. Each plan's Stripe Price ID comes from an env var so no live
// Stripe price is ever hardcoded here; annual prices are intentionally
// not decided yet (see docs/BILLING.md) and are reported as unconfigured
// until product sets a price and the corresponding env var.
import { TIER_PRODUCT, type Tier } from "@/lib/access-policy";

export type BillingInterval = "monthly" | "annual";

export interface PlanDefinition {
  planCode: string;
  tier: Extract<Tier, "INDIVIDUAL" | "PRO">;
  product: string;
  interval: BillingInterval;
  /** THB, or null when the price has not been decided yet (annual plans). */
  priceThb: number | null;
  /** Env var holding this plan's Stripe Price ID. */
  stripePriceEnvVar: string;
}

export const PLAN_CATALOG: PlanDefinition[] = [
  {
    planCode: "individual_monthly",
    tier: "INDIVIDUAL",
    product: TIER_PRODUCT.INDIVIDUAL,
    interval: "monthly",
    priceThb: 399,
    stripePriceEnvVar: "STRIPE_PRICE_INDIVIDUAL_MONTHLY",
  },
  {
    planCode: "individual_annual",
    tier: "INDIVIDUAL",
    product: TIER_PRODUCT.INDIVIDUAL,
    interval: "annual",
    // Not decided yet -- must be materially better than 12x monthly per
    // product requirement, but the exact figure is a pricing decision this
    // implementation must not invent.
    priceThb: null,
    stripePriceEnvVar: "STRIPE_PRICE_INDIVIDUAL_ANNUAL",
  },
  {
    planCode: "pro_monthly",
    tier: "PRO",
    product: TIER_PRODUCT.PRO,
    interval: "monthly",
    priceThb: 990,
    stripePriceEnvVar: "STRIPE_PRICE_PRO_MONTHLY",
  },
  {
    planCode: "pro_annual",
    tier: "PRO",
    product: TIER_PRODUCT.PRO,
    interval: "annual",
    priceThb: null,
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
