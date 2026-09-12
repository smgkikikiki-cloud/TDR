import { NextRequest, NextResponse } from "next/server";
import {
  BillingError,
  createRegistrationCheckout,
  REGISTRATION_ANNUAL_PLAN,
  REGISTRATION_PLAN,
  type RegistrationPlan,
} from "@/lib/billing";

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

  return "https://tdr-xi.vercel.app";
}

export async function POST(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  let body: Record<string, unknown> = {};
  try { body = await request.json(); } catch {}
  const requestedPlan = typeof body.plan === "string" ? body.plan : REGISTRATION_PLAN;
  const supportedPlans = new Set<string>([REGISTRATION_PLAN, REGISTRATION_ANNUAL_PLAN]);
  if (!supportedPlans.has(requestedPlan)) {
    return NextResponse.json({ error: "unsupported billing plan" }, { status: 400 });
  }
  const plan = requestedPlan as RegistrationPlan;

  try {
    const origin = appOrigin(request);
    const session = await createRegistrationCheckout({
      accessToken,
      plan,
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
