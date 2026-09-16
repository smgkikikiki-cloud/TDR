import { NextRequest, NextResponse } from "next/server";
import { resolveAccessContext, AccessPolicyError } from "@/lib/access-policy-server";
import { FEATURES, resolveFeatureState, type FeatureKey } from "@/lib/access-policy";

export const dynamic = "force-dynamic";

// Exposes the reserved-capability ladder (see lib/access-policy.ts::FEATURES)
// so routes/components never hand-roll their own tier check for a feature
// like provincial_registration. Returns "teaser" for everyone while the
// feature is unreleased -- this route never queries the underlying
// (unfinished) data pipeline itself.
function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

export async function GET(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  try {
    const ctx = await resolveAccessContext(accessToken);
    const features = Object.fromEntries(
      (Object.keys(FEATURES) as FeatureKey[]).map((key) => [
        key,
        {
          label: FEATURES[key].label,
          label_th: FEATURES[key].labelTh,
          state: resolveFeatureState(key, ctx.tier),
        },
      ]),
    );
    return NextResponse.json({ tier: ctx.tier, features }, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof AccessPolicyError) return NextResponse.json({ error: error.message }, { status: error.status });
    console.error("features route error", error);
    return NextResponse.json({ error: "could not load feature status" }, { status: 500 });
  }
}
