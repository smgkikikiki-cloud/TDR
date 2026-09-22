import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { adminDb } from "@/lib/supabase";

/** Where an uploaded source file waits for the worker. */
export const IMPORT_BUCKET = "source-imports";

export function safeImportName(raw: string): string {
  const name = raw.normalize("NFKC").trim().replace(/[^\w.\-]+/g, "_");
  if (!name || name.length > 120) throw new Error("ชื่อไฟล์ไม่ถูกต้อง");
  return name;
}

export type ImportRun = {
  id: string;
  originalName: string;
  sourceKind: string;
  status: string;
  rowsRead: number | null;
  patched: number | null;
  created: number | null;
  exceptions: number | null;
  error: string | null;
  createdAt: string;
};

/** What the owner watches: upload -> processing -> completed. */
export async function listImportRuns(limit = 25): Promise<ImportRun[]> {
  const db = adminDb();
  if (!db) return [];
  const { data, error } = await db.from("import_runs")
    .select("id,original_name,source_kind,status,rows_read,patched,created,exceptions,error,created_at")
    .order("created_at", { ascending: false }).limit(limit);
  if (error) return [];
  return (data || []).map((row: any) => ({
    id: String(row.id), originalName: row.original_name, sourceKind: row.source_kind,
    status: row.status, rowsRead: row.rows_read, patched: row.patched,
    created: row.created, exceptions: row.exceptions, error: row.error,
    createdAt: row.created_at,
  }));
}

export type RunException = ImportException & {
  runId: string;
  runLabel: string;
  sourceKind: string;
  kind?: string;
  period?: string;
  units?: number;
};

/** Unresolved rows from uploaded files, read from the run that produced
 *  them. The worker's temp directory is long gone by now; this is why the
 *  rows were stored on the row itself. */
export async function listRunExceptions(limit = 50): Promise<RunException[]> {
  const db = adminDb();
  if (!db) return [];
  const { data, error } = await db.from("import_runs")
    .select("id,original_name,source_kind,exception_rows,created_at")
    .not("exception_rows", "eq", "[]")
    .order("created_at", { ascending: false }).limit(limit);
  if (error) return [];
  return (data || []).flatMap((run: any) =>
    (Array.isArray(run.exception_rows) ? run.exception_rows : []).map((row: any) => ({
      ...row,
      runId: String(run.id),
      runLabel: String(run.original_name || run.id),
      sourceKind: String(run.source_kind || ""),
      reason: String(row?.reason || "ระบุสาเหตุไม่ได้"),
    })));
}

/** Where tools/import_source.py leaves what it did. Read straight from the
 *  repo, the same way the catalogue itself is read -- an import run is a
 *  fact about the data, so it lives with the data rather than in a table. */
const ROOT = path.join(process.cwd(), "automotive/vehicle_master/vehreg/data");

export type ImportReport = {
  stem: string;
  rows_read: number;
  rows_placed: number;
  patched: number;
  created: number;
  unchanged: number;
  exceptions: number;
  conflicts: number;
  commands: number;
  applied: boolean;
};

export type ImportException = {
  source_id?: string;
  model_id?: string;
  brand?: string;
  model?: string;
  trim_name?: string;
  powertrain?: string;
  reason: string;
};

function trimsDir(year: number) {
  return path.join(ROOT, String(year), "market", "trims");
}

function readJson<T>(file: string): T | null {
  try {
    return JSON.parse(readFileSync(file, "utf8")) as T;
  } catch {
    return null;
  }
}

export function importReports(year: number): ImportReport[] {
  let names: string[] = [];
  try {
    names = readdirSync(trimsDir(year));
  } catch {
    return [];
  }
  return names
    .filter((name) => name.startsWith("import_") && name.endsWith("_report.json"))
    .map((name) => {
      const report = readJson<ImportReport>(path.join(trimsDir(year), name));
      return report ? { ...report, stem: name.replace(/_report\.json$/, "") } : null;
    })
    .filter((row): row is ImportReport => row !== null);
}

export function importExceptions(year: number): { stem: string; rows: ImportException[] }[] {
  return importReports(year).map((report) => ({
    stem: report.stem,
    rows: readJson<{ exceptions: ImportException[] }>(
      path.join(trimsDir(year), `${report.stem}_exceptions.json`))?.exceptions ?? [],
  }));
}
