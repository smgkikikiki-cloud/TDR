import { NextRequest, NextResponse } from "next/server";
import { resolveAccessContext, AccessPolicyError } from "@/lib/access-policy-server";
import { FEATURES, resolveFeatureState, type FeatureAudience, type FeatureKey } from "@/lib/access-policy";

export const dynamic = "force-dynamic";

// Exposes the reserved-capability ladder (see lib/access-policy.ts::FEATURES)
// so routes/components never hand-roll their own tier check for a feature
// like provincial_registration. Returns "teaser" for everyone while the
// feature is unreleased -- this route never queries the underlying
// (unfinished) data pipeline itself. Also exposes the PLANNED full ladder
// (`ladder`) alongside today's resolved state (`current_state`), so a UI
// can communicate "here's what this becomes for each tier" without
// pretending any of it is live yet -- and `surface`, so a consumer (e.g.
// the Sales Tools dashboard) can filter to only the reserved capabilities
// that actually belong on it.
const LADDER_AUDIENCES: FeatureAudience[] = ["FREE", "INDIVIDUAL", "PRO", "CORPORATE"];

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
      (Object.keys(FEATURES) as FeatureKey[]).map((key) => {
        const feature = FEATURES[key];
        return [
          key,
          {
            label: feature.label,
            label_th: feature.labelTh,
            surface: feature.surface,
            released: feature.released,
            current_state: resolveFeatureState(key, ctx.tier),
            ladder: Object.fromEntries(LADDER_AUDIENCES.map((audience) => [audience, feature.stateByAudience[audience]])),
          },
        ];
      }),
    );
    return NextResponse.json({ tier: ctx.tier, features }, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof AccessPolicyError) return NextResponse.json({ error: error.message }, { status: error.status });
    console.error("features route error", error);
    return NextResponse.json({ error: "could not load feature status" }, { status: 500 });
  }
}
