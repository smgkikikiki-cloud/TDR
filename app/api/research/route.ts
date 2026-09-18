import { NextRequest, NextResponse } from "next/server";
import { requireActivatedAccess, requireUsage, AccessPolicyError } from "@/lib/access-policy-server";
import { FEATURES } from "@/lib/access-policy";
import { recordEvent } from "@/lib/telemetry";

export const dynamic = "force-dynamic";

// This repo has no research-article content model at all (no table, no
// admin authoring UI). Per the no-unimplemented-features-as-live policy,
// this stays entirely hidden (404, not a working-but-fake feature) until
// FEATURES.research_reports.released flips true and real content exists
// -- see lib/access-policy.ts and the delivery report's item 6/9.
const STUB_RESEARCH_ITEMS = [
  { id: "th-ev-2026-q3", title: "Thailand BEV adoption, Q3 2026", teaser: "Registration share by segment and what changed since Q2." },
];

function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

export async function GET(request: NextRequest) {
  if (!FEATURES.research_reports.released) {
    return NextResponse.json({ error: "research reports are not released yet", state: "teaser" }, { status: 404 });
  }

  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  const mode = request.nextUrl.searchParams.get("mode") === "full" ? "full" : "preview";

  try {
    const ctx = await requireActivatedAccess(accessToken);
    if (mode === "preview") {
      await recordEvent({ eventName: "research_preview_viewed", userId: ctx.userId });
      return NextResponse.json({ mode, items: STUB_RESEARCH_ITEMS.map((item) => ({ id: item.id, title: item.title, teaser: item.teaser })) });
    }

    if (ctx.policy.researchAccess !== "full") {
      return NextResponse.json({ error: "full research requires a Pro plan" }, { status: 403 });
    }
    // Server-computed fingerprint (the requested item ids), never a raw
    // client-supplied token -- see lib/access-policy-server.ts::requireUsage.
    const requestedItemIds = request.nextUrl.searchParams.getAll("item").sort().join(",") || "all";
    const quota = await requireUsage(ctx, "research_full", ctx.policy.researchFullMonthlyLimit, ["research_full", requestedItemIds]);
    await recordEvent({ eventName: "research_full_opened", userId: ctx.userId });
    return NextResponse.json({
      mode,
      quota,
      items: STUB_RESEARCH_ITEMS.map((item) => ({ id: item.id, title: item.title, body: `${item.teaser} (full research content is not yet authored -- this is a scaffold.)` })),
    });
  } catch (error) {
    if (error instanceof AccessPolicyError) return NextResponse.json({ error: error.message }, { status: error.status });
    console.error("research route error", error);
    return NextResponse.json({ error: "research unavailable" }, { status: 500 });
  }
}
