import { NextResponse } from "next/server";
import { isAdmin } from "@/lib/admin-auth";
import { adminDb } from "@/lib/supabase";

const BATCH_KEY = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ batchKey: string }> },
) {
  if (!(await isAdmin())) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const { batchKey } = await params;
  if (!BATCH_KEY.test(batchKey)) {
    return NextResponse.json({ error: "invalid batch key" }, { status: 400 });
  }

  const db = adminDb();
  if (!db) {
    return NextResponse.json({ error: "Supabase server credential is not configured" }, { status: 503 });
  }

  const { data, error } = await db
    .from("canonical_input_batches")
    .select("batch_key,status,attempts,release_id,error,updated_at,processing_started_at,staged_at,published_at")
    .eq("batch_key", batchKey)
    .maybeSingle();

  if (error) {
    console.error("canonical batch status read failed", error);
    return NextResponse.json({ error: "status read failed" }, { status: 500 });
  }
  if (!data) {
    return NextResponse.json({ error: "batch not found" }, { status: 404 });
  }

  return NextResponse.json({
    batchKey: data.batch_key,
    status: data.status,
    attempts: data.attempts,
    releaseId: data.release_id,
    error: data.error,
    updatedAt: data.updated_at,
    processingStartedAt: data.processing_started_at,
    stagedAt: data.staged_at,
    publishedAt: data.published_at,
  }, {
    headers: { "cache-control": "no-store" },
  });
}
