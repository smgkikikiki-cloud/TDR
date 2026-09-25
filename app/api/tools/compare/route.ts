import { NextRequest, NextResponse } from "next/server";
import { getCanonicalCompareTrimsByIds } from "@/lib/compare-canonical-data";
import { compareValue, indexSpecFields, rowIsDifferent, visibleCompareGroups, type CompareSpecField, type FreeCompareTrim } from "@/lib/free-compare";
import { evaluateCompareWinner } from "@/lib/compare-winners";
import { loadSpecFieldRegistry } from "@/lib/spec-field-registry";
import { requireMemberAccess, requireUsage, AccessPolicyError } from "@/lib/access-policy-server";
import { recordEvent } from "@/lib/telemetry";
import {
  ANON_COMPARE_COOKIE, ANON_COMPARE_DAILY_LIMIT, allowanceFrom, bangkokDayKey, cookieOptions, encodeCount,
} from "@/lib/anon-allowance";

export const dynamic = "force-dynamic";

function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

/** The comparison itself, which is the same work whoever asked for it.
 *
 *  Entitlement decides whether it runs and what quota line comes back with
 *  it; it does not change a single number in the table. */
async function buildComparison(requestedIds: string[], diffOnly: boolean) {
  // A comparison has at most four selected trims. Fetch those rich payloads
  // directly rather than reading/sorting the entire 1,500+ row trim projection.
  const selected = (await getCanonicalCompareTrimsByIds(requestedIds)) as FreeCompareTrim[];
  // Which fields are comparable, and what they are called, comes from the
  // canonical registry rather than a list kept here -- the same file
  // APPEND_SPEC validates against, so a field is comparable the day it is
  // defined.
  const specFields = loadSpecFieldRegistry(new Date().getFullYear()) as unknown as CompareSpecField[];
  const definitions = indexSpecFields(specFields);
  const groups = visibleCompareGroups(selected, diffOnly, specFields).map((group) => ({
    title: group.title,
    rows: group.rows.map((row) => {
      const winner = evaluateCompareWinner(selected, row.key, definitions);
      return {
        key: row.key,
        label: row.label,
        different: rowIsDifferent(selected, row.key, definitions),
        values: selected.map((trim) => compareValue(trim, row.key, definitions)),
        comparisonMode: winner.comparisonMode,
        comparable: winner.comparable,
        bestIndexes: winner.bestIndexes,
      };
    }),
  }));
  return {
    selected: selected.map((trim) => ({
      id: trim.id,
      brand_name: trim.brand_name,
      model_name: trim.model_name,
      name: trim.name,
      model_slug: trim.model_slug,
      image_url: (trim as any).image_url ?? null,
      // Header metadata, not comparable rows -- see lib/free-compare.ts.
      retail_status: trim.retail_status ?? null,
      launch_year: trim.launch_year ?? null,
      launch_quarter: trim.launch_quarter ?? null,
    })),
    missing_selection: requestedIds.length !== selected.length,
    groups,
  };
}

async function anonymousComparison(requestedIds: string[], diffOnly: boolean, remaining: number) {
  const body = await buildComparison(requestedIds, diffOnly);
  return NextResponse.json({
    ...body,
    quota: { used: 0, limit: null, remaining: null, resets_at: "" },
    anonymous: { remaining, limit: ANON_COMPARE_DAILY_LIMIT },
  }, { headers: { "Cache-Control": "private, no-store" } });
}

export async function GET(request: NextRequest) {
  const accessToken = bearer(request);

  const requestedIds = [...new Set(request.nextUrl.searchParams.getAll("trims").filter(Boolean))].slice(0, 4);
  if (requestedIds.length < 2) {
    return NextResponse.json({ error: "select at least 2 trims to compare" }, { status: 400 });
  }
  const diffOnly = request.nextUrl.searchParams.get("diff") === "1";

  // Comparing specifications is the free product. An anonymous reader gets a
  // real trial of it -- ten comparisons a day, counted per press of the
  // button -- before being asked for an account, because a tool nobody has
  // used is a tool nobody signs up for. The allowance is a cookie: see
  // lib/anon-allowance.
  if (!accessToken) {
    const scope = bangkokDayKey();
    const allowance = allowanceFrom(
      request.cookies.get(ANON_COMPARE_COOKIE)?.value, scope, ANON_COMPARE_DAILY_LIMIT);
    if (allowance.exhausted) {
      return NextResponse.json({
        error: "ใช้สิทธิ์เทียบรถวันนี้ครบแล้ว สมัครบัญชีฟรีเพื่อเทียบได้ไม่จำกัด หรือกลับมาใหม่พรุ่งนี้",
        signup_required: true,
      }, { status: 401 });
    }
    const response = await anonymousComparison(requestedIds, diffOnly, allowance.remaining - 1);
    response.cookies.set(
      ANON_COMPARE_COOKIE, encodeCount(scope, allowance.used + 1), cookieOptions());
    return response;
  }

  try {
    const ctx = await requireMemberAccess(accessToken);
    const quota = await requireUsage(ctx, "vehicle_compare", ctx.policy.compareDailyLimit, [
      [...requestedIds].sort().join(","), diffOnly,
    ]);

    const body = await buildComparison(requestedIds, diffOnly);

    await recordEvent({ eventName: "compare_run", userId: ctx.userId, props: { trim_count: body.selected.length } });

    return NextResponse.json({ ...body, quota },
      { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof AccessPolicyError) {
      if (error.status === 429) {
        const ctx = await requireMemberAccess(accessToken).catch(() => null);
        if (ctx) await recordEvent({ eventName: "compare_quota_hit", userId: ctx.userId });
      }
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    console.error("compare tool error", error);
    return NextResponse.json({ error: "could not compare vehicles" }, { status: 500 });
  }
}
