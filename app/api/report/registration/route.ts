import { NextRequest, NextResponse } from "next/server";
import {
  getRegistrationAnalytics,
  isRegistrationDimension,
  normalizeReportPeriod,
  RegistrationAccessError,
} from "@/lib/registration-analytics";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const authorization = request.headers.get("authorization") || "";
  const match = /^Bearer\s+(.+)$/i.exec(authorization);
  if (!match) {
    return NextResponse.json({ error: "member bearer token required" }, { status: 401 });
  }

  const dimensionValue = request.nextUrl.searchParams.get("dimension") || "coverage";
  if (!isRegistrationDimension(dimensionValue)) {
    return NextResponse.json({ error: "unsupported registration analytics dimension" }, { status: 400 });
  }

  const requestedPeriod = request.nextUrl.searchParams.get("period");
  const period = normalizeReportPeriod(requestedPeriod);
  if (requestedPeriod && !period) {
    return NextResponse.json({ error: "period must be YYYY-MM or YYYY-MM-DD" }, { status: 400 });
  }

  const limitValue = Number(request.nextUrl.searchParams.get("limit") || "100");
  const limit = Number.isFinite(limitValue) ? limitValue : 100;

  try {
    const rows = await getRegistrationAnalytics({
      accessToken: match[1],
      dimension: dimensionValue,
      period,
      limit,
    });

    return NextResponse.json(
      { dimension: dimensionValue, period, rows },
      { headers: { "Cache-Control": "private, no-store" } }
    );
  } catch (error) {
    if (error instanceof RegistrationAccessError) {
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    console.error("registration report error", error);
    return NextResponse.json({ error: "registration analytics unavailable" }, { status: 500 });
  }
}
