import { NextRequest, NextResponse } from "next/server";
import { resolveAccessContext, requireUsage, AccessPolicyError } from "@/lib/access-policy-server";
import { recordEvent } from "@/lib/telemetry";

export const dynamic = "force-dynamic";

// SCAFFOLD: no PDF-generation library is installed in this repo (no
// pdfkit/puppeteer/react-pdf/jspdf -- confirmed by inspecting package.json
// before writing this route). This proves out the pdf_export monthly
// quota, the Free-tier watermark requirement, and the "PDF is a
// presentation artifact, never a raw-data dump" boundary (it renders only
// a short text summary, not machine-readable tables), but returns a plain
// text/plain file rather than a real PDF. See the delivery report's item 9
// for what a real implementation needs (a PDF library decision + real
// report content).
function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

export async function GET(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  try {
    const ctx = await resolveAccessContext(accessToken);
    const quota = await requireUsage(ctx, "pdf_export", ctx.policy.pdfMonthlyLimit, request.headers.get("x-tdr-action-id"));

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
