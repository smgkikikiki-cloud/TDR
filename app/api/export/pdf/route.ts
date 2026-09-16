import { NextRequest, NextResponse } from "next/server";
import { requireActivatedAccess, requireUsage, AccessPolicyError } from "@/lib/access-policy-server";
import { FEATURES } from "@/lib/access-policy";
import { recordEvent } from "@/lib/telemetry";

export const dynamic = "force-dynamic";

// No PDF-generation library is installed in this repo (no
// pdfkit/puppeteer/react-pdf/jspdf -- confirmed by inspecting package.json
// before this was first written). Per the no-unimplemented-features-as-live
// policy, this stays entirely hidden (404) until
// FEATURES.pdf_export_reports.released flips true and a real PDF renderer
// exists -- a route that quietly downloads a .txt while claiming to be a
// PDF export is exactly what that policy forbids. See the delivery
// report's item 6/9.
function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

export async function GET(request: NextRequest) {
  if (!FEATURES.pdf_export_reports.released) {
    return NextResponse.json({ error: "PDF export is not released yet", state: "teaser" }, { status: 404 });
  }

  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  try {
    const ctx = await requireActivatedAccess(accessToken);
    const reportId = request.nextUrl.searchParams.get("report") || "summary";
    const quota = await requireUsage(ctx, "pdf_export", ctx.policy.pdfMonthlyLimit, ["pdf_export", reportId]);

    const watermark = ctx.policy.pdfWatermark ? "TDR Free -- not for redistribution\n\n" : "";
    const body = `${watermark}Thailand Development Report -- Export Summary\nGenerated: ${new Date().toISOString()}\nTier: ${ctx.tier}\n\n(This is a scaffold export: no PDF library is installed yet and no real report content model exists. This proves the quota/watermark/tier boundary only.)\n`;

    await recordEvent({ eventName: "pdf_exported", userId: ctx.userId, props: { tier: ctx.tier } });

    return new NextResponse(body, {
      status: 200,
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Content-Disposition": "attachment; filename=tdr-report-scaffold.txt",
        "Cache-Control": "private, no-store",
        "X-TDR-Quota-Used": String(quota.used),
        "X-TDR-Quota-Limit": quota.limit === null ? "unlimited" : String(quota.limit),
      },
    });
  } catch (error) {
    if (error instanceof AccessPolicyError) return NextResponse.json({ error: error.message }, { status: error.status });
    console.error("pdf export route error", error);
    return NextResponse.json({ error: "export unavailable" }, { status: 500 });
  }
}
