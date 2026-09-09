import { NextRequest, NextResponse } from "next/server";
import { BillingError, processStripeWebhook, verifyStripeWebhook } from "@/lib/billing";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  const rawBody = await request.text();
  try {
    verifyStripeWebhook(rawBody, request.headers.get("stripe-signature"));
    const event = JSON.parse(rawBody);
    const result = await processStripeWebhook(event);
    return NextResponse.json({ received: true, duplicate: result.duplicate });
  } catch (error) {
    if (error instanceof BillingError) {
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    console.error("Stripe webhook error", error);
    return NextResponse.json({ error: "billing webhook failed" }, { status: 500 });
  }
}
