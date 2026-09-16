import { NextRequest, NextResponse } from "next/server";
import { resolveAccessContext, getSalesModuleSelection, setSalesModuleSelection, AccessPolicyError } from "@/lib/access-policy-server";
import { currentSalesModuleCycleKey, validateSalesModuleSelection, SALES_MODULES, type SalesModule } from "@/lib/access-policy";
import { recordEvent } from "@/lib/telemetry";

export const dynamic = "force-dynamic";

function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

export async function GET(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  try {
    const ctx = await resolveAccessContext(accessToken);
    const cycleKey = currentSalesModuleCycleKey();
    const selection = ctx.tier === "FREE" ? await getSalesModuleSelection(ctx.db, ctx.userId, cycleKey) : null;
    return NextResponse.json({
      tier: ctx.tier,
      cycle_key: cycleKey,
      pick_count: ctx.policy.salesModulePickCount,
      available_modules: SALES_MODULES,
      selection,
    }, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof AccessPolicyError) return NextResponse.json({ error: error.message }, { status: error.status });
    console.error("sales-modules status error", error);
    return NextResponse.json({ error: "could not load sales module status" }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  let body: Record<string, unknown> = {};
  try { body = await request.json(); } catch {}
  const modules = Array.isArray(body.modules) ? body.modules.map(String) : [];

  try {
    const ctx = await resolveAccessContext(accessToken);
    if (ctx.tier !== "FREE") {
      return NextResponse.json({ error: "module selection only applies to the Free tier -- paid tiers have every module" }, { status: 400 });
    }
    const pickCount = ctx.policy.salesModulePickCount ?? 4;
    const validationError = validateSalesModuleSelection(modules, pickCount);
    if (validationError) return NextResponse.json({ error: validationError }, { status: 400 });

    const cycleKey = currentSalesModuleCycleKey();
    await setSalesModuleSelection(ctx.db, ctx.userId, cycleKey, modules as SalesModule[]);
    await recordEvent({ eventName: "sales_modules_selected", userId: ctx.userId, props: { modules, cycle_key: cycleKey } });
    return NextResponse.json({ cycle_key: cycleKey, selection: modules }, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof AccessPolicyError) return NextResponse.json({ error: error.message }, { status: error.status });
    console.error("sales-modules selection error", error);
    return NextResponse.json({ error: "could not save sales module selection" }, { status: 500 });
  }
}
