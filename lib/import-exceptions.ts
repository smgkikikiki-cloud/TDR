/**
 * The work an import could not do by itself.
 *
 * Everything an importer could place deterministically is already written;
 * what is here is the remainder, one durable row per unresolved thing. It
 * used to live in a JSON array on the run, capped at 500, so a file with
 * 900 unplaceable rows silently lost 400 of them -- work nobody could see
 * and nobody would ever be asked to do.
 *
 * A registration label that turns up unknown every month produces one row
 * per monthly file. They are grouped here, because they are one decision:
 * resolving the label closes every month that was waiting on it.
 */

import { adminDb } from "@/lib/supabase";

export type OpenException = {
  id: string;
  runId: string;
  runLabel: string;
  sourceKind: string;
  kind: string;
  reason: string;
  identity: Record<string, any>;
  createdAt: string;
};

/** One unresolved registration label, and every month waiting on it. */
export type RegistrationGap = {
  ids: string[];
  brandRaw: string;
  modelRaw: string;
  registrationType: string;
  /** MODEL unless the source itself published the grade. Never inferred. */
  grain: "MODEL" | "TRIM";
  units: number;
  months: number;
  latestPeriod: string;
  reason: string;
};

export const REGISTRATION_KIND = "REGISTRATION_IDENTITY";

export async function listOpenExceptions(limit = 1000): Promise<OpenException[]> {
  const db = adminDb();
  if (!db) return [];
  const { data, error } = await db.from("import_run_exceptions")
    .select("id,run_id,source_kind,kind,reason,source_identity,created_at")
    .eq("status", "OPEN")
    .order("created_at", { ascending: false })
    .limit(limit);
  if (error) return [];
  const rows = data || [];
  const runIds = [...new Set(rows.map((row: any) => String(row.run_id)))];
  const labels = new Map<string, string>();
  if (runIds.length) {
    const { data: runs } = await db.from("import_runs")
      .select("id,original_name").in("id", runIds);
    for (const run of runs || []) labels.set(String(run.id), String(run.original_name || run.id));
  }
  return rows.map((row: any) => ({
    id: String(row.id),
    runId: String(row.run_id),
    runLabel: labels.get(String(row.run_id)) || String(row.run_id),
    sourceKind: String(row.source_kind || ""),
    kind: String(row.kind || "UNKNOWN"),
    reason: String(row.reason || ""),
    identity: (row.source_identity && typeof row.source_identity === "object"
      ? row.source_identity : {}) as Record<string, any>,
    createdAt: String(row.created_at || ""),
  }));
}

/** Group the registration labels: one row per label, not per month. */
export function registrationGaps(rows: OpenException[]): RegistrationGap[] {
  const gaps = new Map<string, RegistrationGap>();
  for (const row of rows) {
    if (row.kind !== REGISTRATION_KIND) continue;
    const brandRaw = String(row.identity.brand_name_raw || row.identity.brand || "");
    const modelRaw = String(row.identity.model_name_raw || row.identity.model || "");
    if (!brandRaw || !modelRaw) continue;
    const registrationType = String(row.identity.registration_type || "*");
    const key = `${registrationType}|${brandRaw}|${modelRaw}`;
    const period = String(row.identity.period || "");
    const units = Number(row.identity.units || row.identity.registrations || 0) || 0;
    const existing = gaps.get(key);
    if (existing) {
      existing.ids.push(row.id);
      existing.units += units;
      existing.months += 1;
      if (period > existing.latestPeriod) existing.latestPeriod = period;
      continue;
    }
    gaps.set(key, {
      ids: [row.id],
      brandRaw,
      modelRaw,
      registrationType,
      // Only the source can make a mapping trim-grained.
      grain: String(row.identity.grain || "MODEL") === "TRIM" ? "TRIM" : "MODEL",
      units,
      months: 1,
      latestPeriod: period,
      reason: row.reason,
    });
  }
  return [...gaps.values()].sort((a, b) => b.units - a.units);
}

/** Everything that is not a registration label: vehicles, prices, bad rows. */
export function otherExceptions(rows: OpenException[]): OpenException[] {
  return rows.filter((row) => row.kind !== REGISTRATION_KIND);
}
