import { NextRequest, NextResponse } from "next/server";
import { BillingError, createBillingPortal } from "@/lib/billing";

export const dynamic = "force-dynamic";

function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

function normalizeOrigin(value: string | undefined | null) {
  if (!value) return null;
  const trimmed = value.trim().replace(/^['"]|['"]$/g, "").replace(/\/$/, "");
  if (!trimmed) return null;
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}

function appOrigin(request: NextRequest) {
  return normalizeOrigin(process.env.TDR_APP_URL)
    || normalizeOrigin(process.env.VERCEL_PROJECT_PRODUCTION_URL)
    || (process.env.NODE_ENV !== "production" ? request.nextUrl.origin : null)
    || "https://tdr-xi.vercel.app";
}

export async function POST(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  try {
    const session = await createBillingPortal({
      accessToken,
      returnUrl: `${appOrigin(request)}/member/billing`,
    });
    return NextResponse.json(session, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof BillingError) return NextResponse.json({ error: error.message }, { status: error.status });
    console.error("billing portal error", error);
    return NextResponse.json({ error: "could not open billing portal" }, { status: 500 });
  }
}
