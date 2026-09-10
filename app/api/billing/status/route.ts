import { NextRequest, NextResponse } from "next/server";
import { BillingError, getBillingStatus } from "@/lib/billing";
import { adminDb, publicDb } from "@/lib/supabase";

export const dynamic = "force-dynamic";

function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

function normalizedSecretKind() {
  const raw = process.env.SUPABASE_SECRET_KEY;
  const trimmed = raw?.trim();
  const unquoted = trimmed && ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'")))
    ? trimmed.slice(1, -1).trim()
    : trimmed;

  if (raw?.startsWith("sb_secret_")) return "sb_secret";
  if (unquoted?.startsWith("sb_secret_")) return "sb_secret_wrapped";
  if (process.env.SUPABASE_SERVICE_ROLE_KEY) return "service_role";
  if (raw) return "other_secret";
  return "missing";
}

async function profileDiagnostic(accessToken: string) {
  const auth = publicDb();
  const db = adminDb();
  if (!auth || !db) return "diagnostic unavailable";

  const { data: authData, error: authError } = await auth.auth.getUser(accessToken);
  if (authError || !authData.user) {
    return `auth probe failed: ${authError?.message || "no user"}`;
  }

  const probe = await db
    .from("tdr_customer_profiles")
    .select("phone_e164")
    .eq("user_id", authData.user.id)
    .maybeSingle();

  if (!probe.error) return "profile probe unexpectedly succeeded";
  return `${probe.error.code || "unknown"}: ${probe.error.message} [http ${probe.status}; key ${normalizedSecretKind()}]`;
}

export async function GET(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  try {
    const status = await getBillingStatus(accessToken);
    return NextResponse.json(status, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof BillingError) {
      if (error.message === "could not load customer profile") {
        const detail = await profileDiagnostic(accessToken).catch((diagnosticError) =>
          `diagnostic crashed: ${diagnosticError instanceof Error ? diagnosticError.message : "unknown error"}`
        );
        console.error("billing profile diagnostic", detail);
        return NextResponse.json({ error: `${error.message} — ${detail}` }, { status: error.status });
      }
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    console.error("billing status error", error);
    return NextResponse.json({ error: "billing status unavailable" }, { status: 500 });
  }
}
