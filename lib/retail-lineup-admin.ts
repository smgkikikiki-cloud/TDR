import { adminDb } from "@/lib/supabase";

export type RetailLineupStatus =
  | "PREVIEW_READY"
  | "APPLYING"
  | "WRITTEN_PENDING_PUBLISH"
  | "COMPLETED"
  | "FAILED"
  | "STALE"
  | "CANCELLED";

export type RetailLineupCounts = {
  keep: number;
  create: number;
  reactivate: number;
  archive: number;
};

export type RetailLineupModelDiff = RetailLineupCounts & {
  modelId: string;
  beforeCurrent: number;
  afterCurrent: number;
};

export type RetailLineupPlanListRow = RetailLineupCounts & {
  id: string;
  importRunId: string | null;
  status: RetailLineupStatus;
  actor: string;
  sourceSha256: string;
  baselineHash: string;
  planHash: string;
  models: number;
  beforeCurrent: number;
  afterCurrent: number;
  modelDiffs: RetailLineupModelDiff[];
  approvedBy: string | null;
  appliedCommitSha: string | null;
  releaseId: string | null;
  error: string | null;
  createdAt: string;
  updatedAt: string;
};

export type RetailLineupPlanItem = {
  action: "KEEP" | "CREATE" | "REACTIVATE" | "ARCHIVE";
  modelId: string;
  generationId: string;
  canonicalTrimId: string;
  trimName: string;
  powertrain: string;
  identityResolution: string;
  reopenRequired: boolean;
};

export type RetailLineupPlanModel = {
  modelId: string;
  beforeCurrentTrimIds: string[];
  targetCurrentTrimIds: string[];
  counts: RetailLineupCounts;
  items: RetailLineupPlanItem[];
};

export type RetailLineupPlanDetail = RetailLineupPlanListRow & {
  schemaVersion: number;
  asOf: string;
  catalogYear: number;
  baseReleaseId: string;
  modelsDetail: RetailLineupPlanModel[];
};

export type RetailLineupWorkbookExport = {
  id: string;
  status: "QUEUED" | "PROCESSING" | "READY" | "FAILED";
  actor: string;
  modelIds: string[];
  catalogYear: number;
  baseReleaseId: string;
  storagePath: string | null;
  baselineHash: string | null;
  error: string | null;
  createdAt: string;
  completedAt: string | null;
};

export type RetailLineupQuery<T> = { data: T; error: string | null };

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function count(value: unknown): number {
  const n = Number(value ?? 0);
  return Number.isFinite(n) && n >= 0 ? Math.trunc(n) : 0;
}

function counts(raw: any): RetailLineupCounts {
  return {
    keep: count(raw?.keep),
    create: count(raw?.create),
    reactivate: count(raw?.reactivate),
    archive: count(raw?.archive),
  };
}

function modelDiffs(raw: any): RetailLineupModelDiff[] {
  if (!Array.isArray(raw?.model_diffs)) return [];
  return raw.model_diffs.map((row: any) => ({
    modelId: text(row?.model_id),
    beforeCurrent: count(row?.before_current),
    afterCurrent: count(row?.after_current),
    ...counts(row),
  })).filter((row: RetailLineupModelDiff) => row.modelId);
}

function listRow(raw: any): RetailLineupPlanListRow {
  const summary = raw?.summary && typeof raw.summary === "object" ? raw.summary : {};
  return {
    id: text(raw?.id),
    importRunId: text(raw?.import_run_id) || null,
    status: text(raw?.status) as RetailLineupStatus,
    actor: text(raw?.actor),
    sourceSha256: text(raw?.source_sha256),
    baselineHash: text(raw?.baseline_hash),
    planHash: text(raw?.plan_hash),
    models: count(summary.models),
    beforeCurrent: count(summary.before_current),
    afterCurrent: count(summary.after_current),
    modelDiffs: modelDiffs(summary),
    ...counts(summary),
    approvedBy: text(raw?.approved_by) || null,
    appliedCommitSha: text(raw?.applied_commit_sha) || null,
    releaseId: text(raw?.release_id) || null,
    error: text(raw?.error) || null,
    createdAt: text(raw?.created_at),
    updatedAt: text(raw?.updated_at),
  };
}

function planModel(raw: any): RetailLineupPlanModel | null {
  const modelId = text(raw?.model_id);
  if (!modelId) return null;
  const items: RetailLineupPlanItem[] = Array.isArray(raw?.items)
    ? raw.items.map((item: any) => ({
        action: text(item?.action) as RetailLineupPlanItem["action"],
        modelId: text(item?.model_id),
        generationId: text(item?.generation_id),
        canonicalTrimId: text(item?.canonical_trim_id),
        trimName: text(item?.trim_name),
        powertrain: text(item?.powertrain),
        identityResolution: text(item?.identity_resolution),
        reopenRequired: item?.reopen_required === true,
      })).filter((item: RetailLineupPlanItem) => item.canonicalTrimId)
    : [];
  return {
    modelId,
    beforeCurrentTrimIds: Array.isArray(raw?.before_current_trim_ids)
      ? raw.before_current_trim_ids.map(text).filter(Boolean) : [],
    targetCurrentTrimIds: Array.isArray(raw?.target_current_trim_ids)
      ? raw.target_current_trim_ids.map(text).filter(Boolean) : [],
    counts: counts(raw?.counts),
    items,
  };
}

function detailRow(raw: any): RetailLineupPlanDetail {
  const base = listRow(raw);
  const compiled = raw?.compiled_plan && typeof raw.compiled_plan === "object"
    ? raw.compiled_plan : {};
  return {
    ...base,
    schemaVersion: count(compiled.schema_version),
    asOf: text(compiled.as_of),
    catalogYear: count(compiled.catalog_year),
    baseReleaseId: text(compiled.base_release_id),
    modelsDetail: Array.isArray(compiled.models)
      ? compiled.models.map(planModel).filter((row: RetailLineupPlanModel | null): row is RetailLineupPlanModel => row !== null)
      : [],
  };
}

function friendlyDbError(error: any): string {
  if (!error) return "";
  if (error.code === "42P01" || /does not exist/i.test(String(error.message || ""))) {
    return "Retail Lineup Bootstrap ยังไม่ได้ลง migration ใน Supabase";
  }
  return String(error.message || error.code || "อ่านสถานะ Retail Lineup Bootstrap ไม่ได้");
}

export async function listRetailLineupPlans(limit = 30): Promise<RetailLineupQuery<RetailLineupPlanListRow[]>> {
  const db = adminDb();
  if (!db) return { data: [], error: "ยังไม่ได้ตั้งค่า Supabase server credential" };
  const { data, error } = await db.from("retail_lineup_plans")
    .select("id,import_run_id,status,actor,source_sha256,baseline_hash,plan_hash,summary,approved_by,applied_commit_sha,release_id,error,created_at,updated_at")
    .order("created_at", { ascending: false }).limit(limit);
  if (error) return { data: [], error: friendlyDbError(error) };
  return { data: (data || []).map(listRow), error: null };
}

export async function loadRetailLineupPlan(planId: string): Promise<RetailLineupQuery<RetailLineupPlanDetail | null>> {
  const db = adminDb();
  if (!db) return { data: null, error: "ยังไม่ได้ตั้งค่า Supabase server credential" };
  const { data, error } = await db.from("retail_lineup_plans")
    .select("*").eq("id", planId).maybeSingle();
  if (error) return { data: null, error: friendlyDbError(error) };
  return { data: data ? detailRow(data) : null, error: null };
}

export async function listRetailLineupWorkbookExports(limit = 12): Promise<RetailLineupQuery<RetailLineupWorkbookExport[]>> {
  const db = adminDb();
  if (!db) return { data: [], error: "ยังไม่ได้ตั้งค่า Supabase server credential" };
  const { data, error } = await db.from("retail_lineup_workbook_exports")
    .select("id,status,actor,model_ids,catalog_year,base_release_id,storage_path,baseline_hash,error,created_at,completed_at")
    .order("created_at", { ascending: false }).limit(limit);
  if (error) return { data: [], error: friendlyDbError(error) };
  return {
    data: (data || []).map((row: any) => ({
      id: text(row.id),
      status: text(row.status) as RetailLineupWorkbookExport["status"],
      actor: text(row.actor),
      modelIds: Array.isArray(row.model_ids) ? row.model_ids.map(text).filter(Boolean) : [],
      catalogYear: count(row.catalog_year),
      baseReleaseId: text(row.base_release_id),
      storagePath: text(row.storage_path) || null,
      baselineHash: text(row.baseline_hash) || null,
      error: text(row.error) || null,
      createdAt: text(row.created_at),
      completedAt: text(row.completed_at) || null,
    })),
    error: null,
  };
}
