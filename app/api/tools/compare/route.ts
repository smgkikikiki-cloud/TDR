import { NextRequest, NextResponse } from "next/server";
import { getCanonicalCompareTrims } from "@/lib/canonical-data";
import { compareValue, rowIsDifferent, visibleCompareGroups, type FreeCompareTrim } from "@/lib/free-compare";
import { resolveAccessContext, requireUsage, AccessPolicyError } from "@/lib/access-policy-server";
import { recordEvent } from "@/lib/telemetry";

export const dynamic = "force-dynamic";

function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

export async function GET(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "sign in with a free TDR account to compare vehicles" }, { status: 401 });

  const requestedIds = [...new Set(request.nextUrl.searchParams.getAll("trims").filter(Boolean))].slice(0, 4);
  if (requestedIds.length < 2) {
    return NextResponse.json({ error: "select at least 2 trims to compare" }, { status: 400 });
  }
  const diffOnly = request.nextUrl.searchParams.get("diff") === "1";
  const actionId = request.headers.get("x-tdr-action-id");

  try {
    const ctx = await resolveAccessContext(accessToken);
    const quota = await requireUsage(ctx, "vehicle_compare", ctx.policy.compareDailyLimit, actionId);

    const all = (await getCanonicalCompareTrims(600)) as FreeCompareTrim[];
    const byId = new Map(all.map((trim) => [trim.id, trim]));
    const selected = requestedIds.map((id) => byId.get(id)).filter(Boolean) as FreeCompareTrim[];
    const groups = visibleCompareGroups(selected, diffOnly).map((group) => ({
      title: group.title,
      rows: group.rows.map((row) => ({
        key: row.key,
        label: row.label,
        different: rowIsDifferent(selected, row.key),
        values: selected.map((trim) => compareValue(trim, row.key)),
      })),
    }));

    await recordEvent({ eventName: "compare_run", userId: ctx.userId, props: { trim_count: selected.length } });

    return NextResponse.json({
      selected: selected.map((trim) => ({ id: trim.id, brand_name: trim.brand_name, model_name: trim.model_name, name: trim.name, model_slug: trim.model_slug })),
      missing_selection: requestedIds.length !== selected.length,
      groups,
      quota,
    }, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof AccessPolicyError) {
      if (error.status === 429) {
        const ctx = await resolveAccessContext(accessToken).catch(() => null);
        if (ctx) await recordEvent({ eventName: "compare_quota_hit", userId: ctx.userId });
      }
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    console.error("compare tool error", error);
    return NextResponse.json({ error: "could not compare vehicles" }, { status: 500 });
  }
}
