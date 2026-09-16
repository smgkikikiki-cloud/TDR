import { NextRequest, NextResponse } from "next/server";
import { resolveAccessContext, requireUsage, AccessPolicyError } from "@/lib/access-policy-server";
import { recordEvent } from "@/lib/telemetry";

export const dynamic = "force-dynamic";

// SCAFFOLD: this repo has no research-article content model at all (no
// table, no admin authoring UI). This route only proves out the
// preview-vs-full access boundary and the research_full monthly quota so
// the tier policy has a real enforcement point to attach to once product
// defines actual research content. See the delivery report's item 9.
const STUB_RESEARCH_ITEMS = [
  { id: "th-ev-2026-q3", title: "Thailand BEV adoption, Q3 2026", teaser: "Registration share by segment and what changed since Q2." },
];

function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

export async function GET(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  const mode = request.nextUrl.searchParams.get("mode") === "full" ? "full" : "preview";

  try {
    const ctx = await resolveAccessContext(accessToken);
    if (mode === "preview") {
      await recordEvent({ eventName: "research_preview_viewed", userId: ctx.userId });
      return NextResponse.json({ mode, items: STUB_RESEARCH_ITEMS.map((item) => ({ id: item.id, title: item.title, teaser: item.teaser })) });
    }

    if (ctx.policy.researchAccess !== "full") {
      return NextResponse.json({ error: "full research requires an Individual or Pro plan" }, { status: 403 });
    }
    const quota = await requireUsage(ctx, "research_full", ctx.policy.researchFullMonthlyLimit, request.headers.get("x-tdr-action-id"));
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
