import { NextRequest, NextResponse } from "next/server";
import { confirmPhoneVerification, PhoneVerificationError } from "@/lib/phone-verification";
import { resolveAccessContext, evaluateAndPersistActivation, AccessPolicyError } from "@/lib/access-policy-server";

export const dynamic = "force-dynamic";

function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

// Step 2 of TDR-owned phone verification: called AFTER the browser's own
// supabase.auth.verifyOtp({..., type: "phone_change"}) call reports
// success. Never trusts that report by itself -- confirmPhoneVerification()
// independently re-reads this caller's OWN current Supabase Auth state via
// their OWN access token and proves it actually matches what THEY reserved
// before marking the TDR reservation confirmed. Then re-evaluates and
// persists activation, since a confirmed phone may be the last missing
// activation criterion.
export async function POST(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  try {
    const confirmation = await confirmPhoneVerification(accessToken);
    const ctx = await resolveAccessContext(accessToken);
    const activation = await evaluateAndPersistActivation(ctx);
    return NextResponse.json({ ...confirmation, activation }, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof PhoneVerificationError) return NextResponse.json({ error: error.message }, { status: error.status });
    if (error instanceof AccessPolicyError) return NextResponse.json({ error: error.message }, { status: error.status });
    console.error("phone confirmation error", error);
    return NextResponse.json({ error: "could not confirm phone verification" }, { status: 500 });
  }
}
