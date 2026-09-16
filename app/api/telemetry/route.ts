import { NextRequest, NextResponse } from "next/server";
import { adminDb } from "@/lib/supabase";
import { recordEvent } from "@/lib/telemetry";

export const dynamic = "force-dynamic";

// Only UI-only events that have no natural server-side call site are
// accepted here (an unauthenticated visitor viewing pricing, or clicking
// the Corporate CTA, never hits an authenticated API route). Every other
// required event (account_created, compare_run, sales_run, pdf_exported,
// etc.) is recorded directly from the server route that performs the
// action -- see lib/telemetry.ts.
const CLIENT_EVENT_NAMES = new Set(["upgrade_viewed", "corporate_cta_clicked"]);

function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

export async function POST(request: NextRequest) {
  let body: Record<string, unknown> = {};
  try { body = await request.json(); } catch {}
  const eventName = typeof body.event === "string" ? body.event : "";
  if (!CLIENT_EVENT_NAMES.has(eventName)) {
    return NextResponse.json({ error: "unsupported client event" }, { status: 400 });
  }

  let userId: string | null = null;
  const accessToken = bearer(request);
  if (accessToken) {
    const db = adminDb();
    const { data } = (await db?.auth.getUser(accessToken)) ?? { data: null };
    userId = data?.user?.id ?? null;
  }

  await recordEvent({
    eventName: eventName as "upgrade_viewed" | "corporate_cta_clicked",
    userId,
    props: typeof body.props === "object" && body.props ? (body.props as Record<string, unknown>) : {},
  });
  return NextResponse.json({ ok: true });
}
