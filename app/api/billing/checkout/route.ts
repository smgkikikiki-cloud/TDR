import { NextRequest, NextResponse } from "next/server";
import { BillingError, createRegistrationCheckout, REGISTRATION_PLAN } from "@/lib/billing";

export const dynamic = "force-dynamic";

function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

function cleanEnv(value: string | undefined) {
  const trimmed = value?.trim();
  if (!trimmed) return null;
  if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

function appOrigin(request: NextRequest) {
  const configured = cleanEnv(process.env.TDR_APP_URL)?.replace(/\/$/, "");
  if (configured) return configured;

  const vercelProductionHost = cleanEnv(process.env.VERCEL_PROJECT_PRODUCTION_URL);
  if (vercelProductionHost) return `https://${vercelProductionHost.replace(/^https?:\/\//, "").replace(/\/$/, "")}`;

  if (process.env.NODE_ENV !== "production") return request.nextUrl.origin;

  // Stable production fallback so Checkout does not fail only because one
  // deployment environment omitted TDR_APP_URL. Replace this when a custom
  // canonical domain is introduced.
  return "https://tdr-kiki-ed8b.vercel.app";
}

export async function POST(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  let body: Record<string, unknown> = {};
  try { body = await request.json(); } catch {}
  const plan = typeof body.plan === "string" ? body.plan : REGISTRATION_PLAN;
  if (plan !== REGISTRATION_PLAN) return NextResponse.json({ error: "unsupported billing plan" }, { status: 400 });

  try {
    const origin = appOrigin(request);
    const session = await createRegistrationCheckout({
      accessToken,
      successUrl: `${origin}/member/billing?checkout=success`,
      cancelUrl: `${origin}/member/billing?checkout=cancelled`,
    });
    return NextResponse.json(session, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof BillingError) return NextResponse.json({ error: error.message }, { status: error.status });
    console.error("billing checkout error", error);
    return NextResponse.json({ error: "could not start checkout" }, { status: 500 });
  }
}
